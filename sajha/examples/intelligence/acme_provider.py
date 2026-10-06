"""
Example provider: "Acme LLM", a fictional in-house HTTP LLM service.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The worked example of docs/architecture/Extending the Intelligence Layer.md (section 2).
tests/ai/test_extension_examples.py runs it through the provider contract suite and through
IntelligenceService.ask, against the fake in acme_fake_server.py.

Acme's wire API is invented for the example and deliberately unlike any vendor's, so every
mapping a provider does is visible:

  POST /v1/generate  {"model", "system", "turns", "functions", "function_mode", "json_schema",
                      "temperature", "max_new_tokens", "stop", "safety", "stream"}
                     -> {"model", "output": {"text", "calls": [{"call_id", "function", "args"}]},
                         "stop": "done" | "call" | "max_tokens" | "blocked",
                         "tokens": {"in", "out", "cached"}}
                     with "stream": true, Server-Sent Events: text {"delta"},
                     call {"index", "call_id", "function", "args_fragment"}, end {"stop", "tokens"},
                     fault {"kind", "detail"}
  POST /v1/embed     {"model", "inputs"} -> {"vectors": [[...]], "tokens": {"in"}}
  GET  /v1/models    {"models": [{"id", "kind", "context", "max_out", "features": [...]}]}
  GET  /v1/health    {"status": "ok" | "degraded"}
  errors             {"fault": {"kind": "quota" | "auth" | "too_long" | "policy" | "busy", "detail"}}
                     (quota carries the header x-acme-retry-in, in seconds)
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional

import httpx

from sajha.ai.llm import (AuthenticationFailed, ChatModel, ContentFiltered, ContextTooLong, EmbeddingModel,
                          HealthStatus, LLMError, LLMProvider, ModelCapabilities, ModelDescriptor, ProviderConfig,
                          ProviderUnavailable, RateLimited, register_provider)
from sajha.ai.llm.http import get_json, iter_sse, post_json, safe_json_loads, stream_post
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, Message, TextDelta, TextPart, ToolCallDelta,
                                ToolCallPart, Usage, UsageEvent)


# ── 1. Settings: one pydantic field per setting ─────────────────────────────

class AcmeConfig(ProviderConfig):
    """Inherits enabled, api_key, api_key_ref, base_url, timeouts, retries, models, ...
    Each field below is ai.providers[name=acme].config.<field> in application.yml and
    SAJHA_AI_ACME_<FIELD> in the environment, with no further code."""
    tenant: str = "default"                               # sent as X-Acme-Tenant
    safety: Literal["standard", "strict"] = "standard"    # Acme's own content policy level
    default_model: Optional[str] = "acme-large"
    default_embedding_model: Optional[str] = "acme-embed"
    live_models: bool = True                              # ask GET /v1/models for the model list

    # the vendor's own variables, read after SAJHA_AI_ACME_* and before application.yml
    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["ACME_LLM_KEY"], "base_url": ["ACME_LLM_URL"]}


# ── 2. Errors: Acme's fault kinds onto SAJHA's taxonomy ─────────────────────

FAULTS = {"quota": RateLimited, "auth": AuthenticationFailed, "too_long": ContextTooLong,
          "policy": ContentFiltered, "busy": ProviderUnavailable}


def fault_error(fault: Dict[str, Any], provider: str, model: str = "", status: Optional[int] = None,
                retry_after: Optional[float] = None) -> Optional[LLMError]:
    cls = FAULTS.get(str(fault.get("kind") or ""))
    if cls is None:
        return None                      # unknown kind: let map_http_error decide by status
    msg = f"{provider}: {fault.get('kind')}: {fault.get('detail') or ''}".strip()
    if cls is RateLimited:
        return RateLimited(msg, retry_after=retry_after, provider=provider, model=model, status=status)
    return cls(msg, provider=provider, model=model, status=status)


# ── 3. The chat model: SAJHA's neutral request <-> Acme's wire format ───────

FINISH = {"done": "stop", "call": "tool_calls", "max_tokens": "length", "blocked": "content_filter"}


class AcmeChatModel(ChatModel):

    def payload(self, request: ChatRequest, stream: bool = False) -> Dict[str, Any]:
        system = [request.system] if request.system else []
        turns: List[Dict[str, Any]] = []
        for m in request.messages:
            if m.role == "system":
                system.append(m.text)
            elif m.role == "user":
                turns.append({"speaker": "user", "text": m.text})
            elif m.role == "assistant":
                turns.append({"speaker": "assistant", "text": m.text,
                              "calls": [{"call_id": c.id, "function": c.name, "args": c.arguments}
                                        for c in m.tool_calls]})
            for r in m.tool_results:                       # role "tool": one turn per result
                turns.append({"speaker": "tool", "call_id": r.call_id, "result": r.content_text(),
                              "error": r.is_error})
        body: Dict[str, Any] = {"model": self.id, "system": "\n\n".join(s for s in system if s),
                                "turns": turns, "max_new_tokens": self.effective_max_tokens(request),
                                "safety": self.provider.config.safety, "stream": stream}
        t = self.effective_temperature(request)            # None when the model takes no temperature
        if t is not None:
            body["temperature"] = t
        if request.stop:
            body["stop"] = list(request.stop)
        if request.tools and request.tool_choice != "none":
            body["functions"] = [{"name": s.name, "doc": s.description,
                                  "params": s.input_schema or {"type": "object", "properties": {}}}
                                 for s in request.tools]
            body["function_mode"] = self._function_mode(request.tool_choice)
        if request.response_schema:
            body["json_schema"] = request.response_schema
        return body

    def _function_mode(self, tool_choice: str) -> str:
        if tool_choice == "auto" or not self.capabilities.forced_tool_choice:
            return "auto"                                  # cannot force: degrade to auto
        if tool_choice == "required":
            return "any"
        return tool_choice                                 # a tool name

    def _message(self, output: Dict[str, Any]) -> Message:
        parts: List[Any] = [TextPart(output["text"])] if output.get("text") else []
        for c in output.get("calls") or []:
            parts.append(ToolCallPart(c.get("call_id") or "", c.get("function") or "", c.get("args") or {}))
        return Message("assistant", parts)

    def _usage(self, tokens: Dict[str, Any]) -> Usage:
        return self.make_usage(tokens.get("in") or 0, tokens.get("out") or 0, tokens.get("cached") or 0)

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)                             # UnsupportedFeature -> the gateway's next candidate
        t0 = time.time()
        with self.provider.slot():                         # max_concurrency
            data = post_json(self.provider.http, "/v1/generate", self.payload(request),
                             provider=self.provider.name, model=self.id, classify=self.provider.classify)
        msg = self._message(data.get("output") or {})
        finish = "tool_calls" if msg.tool_calls else FINISH.get(data.get("stop") or "done", "stop")
        return ChatResponse(msg, finish, self._usage(data.get("tokens") or {}), data.get("model") or self.id,
                            self.provider.name, int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)             # one Done event
            return
        self.validate(request)
        t0 = time.time()
        text: List[str] = []
        calls: Dict[int, Dict[str, str]] = {}
        end: Dict[str, Any] = {}
        with self.provider.slot():
            with stream_post(self.provider.http, "/v1/generate", self.payload(request, stream=True),
                             provider=self.provider.name, model=self.id, classify=self.provider.classify) as resp:
                for event, data in iter_sse(resp):
                    ev = safe_json_loads(data)
                    if event == "text":
                        text.append(ev.get("delta") or "")
                        yield TextDelta(ev.get("delta") or "")
                    elif event == "call":
                        i = int(ev.get("index") or 0)
                        slot = calls.setdefault(i, {"call_id": "", "function": "", "args": ""})
                        slot["call_id"] = slot["call_id"] or ev.get("call_id") or ""
                        slot["function"] = slot["function"] or ev.get("function") or ""
                        slot["args"] += ev.get("args_fragment") or ""
                        yield ToolCallDelta(slot["call_id"], ev.get("function") or "", ev.get("args_fragment") or "", i)
                    elif event == "fault":                 # an error after the stream started
                        raise (fault_error(ev, self.provider.name, self.id)
                               or ProviderUnavailable(f"acme: {ev}", provider=self.provider.name, model=self.id))
                    elif event == "end":
                        end = ev
        parts: List[Any] = [TextPart("".join(text))] if text else []
        parts += [ToolCallPart(c["call_id"], c["function"], safe_json_loads(c["args"]))
                  for _, c in sorted(calls.items())]
        msg = Message("assistant", parts)
        usage = self._usage(end.get("tokens") or {})
        finish = "tool_calls" if msg.tool_calls else FINISH.get(end.get("stop") or "done", "stop")
        yield UsageEvent(usage)                            # usage, then Done, always last
        yield Done(ChatResponse(msg, finish, usage, self.id, self.provider.name, int((time.time() - t0) * 1000)))


# ── 4. The embedding model ──────────────────────────────────────────────────

class AcmeEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        with self.provider.slot():
            data = post_json(self.provider.http, "/v1/embed", {"model": self.id, "inputs": list(texts)},
                             provider=self.provider.name, model=self.id, classify=self.provider.classify)
        return data.get("vectors") or []


# ── 5. The provider: credentials, client, catalogue, health ─────────────────

#: Acme's feature words -> SAJHA capability flags
FEATURES = {"functions": "tools", "json": "structured_output", "vision": "vision", "stream": "streaming"}

#: What we know without asking the server (and what list_models shows when it cannot be asked).
KNOWN_MODELS = [
    ModelDescriptor("acme-large", ModelCapabilities(
        tools=True, structured_output=True, streaming=True, context_window=128_000, max_output_tokens=8_192,
        input_cost_per_mtok=0.40, output_cost_per_mtok=1.60, tags=frozenset({"reasoning"})), source="builtin"),
    ModelDescriptor("acme-small", ModelCapabilities(
        tools=True, structured_output=False, streaming=True, context_window=32_000, max_output_tokens=4_096,
        input_cost_per_mtok=0.05, output_cost_per_mtok=0.20, tags=frozenset({"fast", "cheap"})), source="builtin"),
    ModelDescriptor("acme-embed", ModelCapabilities(
        chat=False, embedding=True, streaming=False, dimensions=768, input_cost_per_mtok=0.02),
        kind="embedding", source="builtin"),
]


@register_provider
class AcmeProvider(LLMProvider):
    name = "acme"                                          # the registry key and the config section
    config_model = AcmeConfig
    requires_key = True                                    # enabled: auto -> on when a key resolves
    default_base_url = "https://llm.acme.internal"
    # a model id Acme serves that neither KNOWN_MODELS, /v1/models nor config describes
    unknown_model_capabilities = ModelCapabilities(tools=True, context_window=32_000)
    chat_model_class = AcmeChatModel
    embedding_model_class = AcmeEmbeddingModel

    def auth_headers(self) -> Dict[str, str]:
        headers = {"X-Acme-Tenant": self.config.tenant}
        if self.api_key:                                   # api_key, or api_key_ref via the SecretStore
            headers["X-Acme-Key"] = self.api_key
        return headers

    def classify(self, resp: httpx.Response) -> Optional[LLMError]:
        """post_json/stream_post call this on a 4xx/5xx before the generic status mapping."""
        try:
            fault = (resp.json() or {}).get("fault") or {}
        except Exception:
            return None
        retry_in = resp.headers.get("x-acme-retry-in")
        return fault_error(fault, self.name, status=resp.status_code,
                           retry_after=float(retry_in) if retry_in else None)

    def live_models(self) -> List[ModelDescriptor]:
        """Merged by LLMProvider.list_models() under config `models:` overrides."""
        known = {d.id: d for d in KNOWN_MODELS}
        if not self.config.live_models:
            return list(known.values())
        try:
            data = get_json(self.http, "/v1/models", provider=self.name, timeout=self.config.health_timeout_s * 3)
        except Exception:
            return list(known.values())                    # unreachable: still list what we know
        out = dict(known)
        for m in data.get("models") or []:
            if m.get("id") in known:
                continue                                   # our curated capabilities and prices win
            flags = {FEATURES[f]: True for f in m.get("features") or [] if f in FEATURES}
            if m.get("kind") == "embedding":
                caps = ModelCapabilities(chat=False, embedding=True, streaming=False, dimensions=int(m.get("dims") or 0))
            else:
                caps = ModelCapabilities(context_window=int(m.get("context") or 0),
                                         max_output_tokens=int(m.get("max_out") or 4096),
                                         **{"streaming": False, **flags})
            out[m["id"]] = ModelDescriptor(m["id"], caps, kind=m.get("kind") or "chat", source="live")
        return list(out.values())

    def health(self) -> HealthStatus:
        """The gateway caches this for ai.gateway.health_ttl_s; keep it cheap and bounded."""
        base = super().health()                            # disabled, not configured, no key
        if not base.ok:
            return base
        try:
            data = get_json(self.http, "/v1/health", provider=self.name, timeout=self.config.health_timeout_s)
        except Exception as e:
            return HealthStatus("down", f"{self.base_url} unreachable ({e.__class__.__name__})")
        status = data.get("status") if isinstance(data, dict) else None
        return HealthStatus("ok" if status == "ok" else "degraded", f"{self.base_url}: {status}")
