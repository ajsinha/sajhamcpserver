"""
Example provider: "Acme LLM", a fictional in-house HTTP LLM service.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The worked example of docs/architecture/Extending the Intelligence Layer.md (section 2).
tests/ai/test_extension_examples.py runs it through the provider contract suite and through
IntelligenceService.ask, against the fake in acme_fake_server.py.

The model is written against the canonical format (OpenAI Chat Completions, typed in
sajha/ai/llm/canonical.py): three pure functions translate a ChatCompletionRequest to Acme's
body, Acme's reply to a ChatCompletion and Acme's stream events to chunks; HTTPChatModel
supplies the I/O, sync and native async. Acme's wire API is invented for the example and
deliberately unlike any vendor's, so every mapping a provider does is visible:

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

from typing import Any, ClassVar, Dict, List, Literal, Optional

import httpx

from sajha.ai.llm import (AuthenticationFailed, ContentFiltered, ContextTooLong, EmbeddingModel, HealthStatus,
                          LLMError, LLMProvider, ModelCapabilities, ModelDescriptor, ProviderConfig,
                          ProviderUnavailable, RateLimited, register_provider)
from sajha.ai.llm.adapter import HTTPChatModel, StreamTranslator, WireCall, system_text
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage, Choice,
                                    CompletionUsage, ToolCall)
from sajha.ai.llm.http import get_json, post_json, safe_json_loads


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


# ── 3. The chat model: the canonical Chat Completions format <-> Acme's wire format ──

FINISH = {"done": "stop", "call": "tool_calls", "max_tokens": "length", "blocked": "content_filter"}


def to_acme_body(request: ChatCompletionRequest, *, model: str, safety: str, max_tokens: int,
                 temperature: Optional[float], stream: bool) -> Dict[str, Any]:
    """Pure translation (golden-testable): canonical request -> Acme's /v1/generate body."""
    turns: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer"):
            continue                                       # joined into "system" below
        if m.role == "user":
            turns.append({"speaker": "user", "text": m.text})
        elif m.role == "assistant":
            turns.append({"speaker": "assistant", "text": m.text or m.refusal or "",
                          "calls": [{"call_id": c.id, "function": c.function.name, "args": c.function.args()}
                                    for c in m.tool_calls or []]})
        elif m.role == "tool":                             # one turn per tool result
            turns.append({"speaker": "tool", "call_id": m.tool_call_id, "result": m.text, "error": m.is_error})
    body: Dict[str, Any] = {"model": model, "system": system_text(request), "turns": turns,
                            "max_new_tokens": max_tokens, "safety": safety, "stream": stream}
    if temperature is not None:                            # None when the model takes no temperature
        body["temperature"] = temperature
    if request.stop_list:
        body["stop"] = request.stop_list
    if request.wants_tools:
        body["functions"] = [{"name": t.name, "doc": (t.function.description or "") if t.function else "",
                              "params": t.parameters_or_default} for t in request.tools or []]
        mode = request.tool_choice_mode                   # prepare() already refused what the model cannot force
        body["function_mode"] = {"required": "any", "named": request.tool_choice_name}.get(mode, "auto")
    if request.output_kind == "json_schema":
        body["json_schema"] = request.output_schema
    return body


def from_acme_output(output: Dict[str, Any], stop: str) -> tuple:
    """Acme's output -> (assistant ChatMessage, finish_reason)."""
    calls = [ToolCall.of(c.get("call_id") or "", c.get("function") or "", c.get("args") or {})
             for c in output.get("calls") or []]
    msg = ChatMessage(role="assistant", content=output.get("text") or None, tool_calls=calls or None)
    finish = "tool_calls" if calls else FINISH.get(stop or "done", "stop")
    if finish == "content_filter":                         # a refusal: say so, never an empty answer
        msg.refusal, msg.content = output.get("text") or "Blocked by Acme's content policy.", None
    return msg, finish


def acme_usage(tokens: Dict[str, Any]) -> CompletionUsage:
    return CompletionUsage.of(tokens.get("in") or 0, tokens.get("out") or 0, tokens.get("cached"))


class AcmeStreamTranslator(StreamTranslator):
    """Acme's SSE events -> chat.completion.chunk objects (close() adds the finish and usage chunks)."""

    def feed(self, event: str, data: Any) -> List[ChatCompletionChunk]:
        ev = safe_json_loads(data)
        if event == "text":
            return self.text(ev.get("delta") or "")
        if event == "call":
            i = int(ev.get("index") or 0)
            if i not in self._calls:
                return self.tool_start(i, ev.get("call_id") or "", ev.get("function") or "",
                                       ev.get("args_fragment") or "")
            return self.tool_args(i, ev.get("args_fragment") or "")
        if event == "fault":                               # an error after the stream started
            raise (fault_error(ev, self.model.provider.name, self.model.id)
                   or ProviderUnavailable(f"acme: {ev}", provider=self.model.provider.name, model=self.model.id))
        if event == "end":
            self.finish = FINISH.get(ev.get("stop") or "done", "stop")
            if self.finish == "content_filter":
                self.refusal = "Blocked by Acme's content policy."
            self.usage = acme_usage(ev.get("tokens") or {})
        return []


class AcmeChatModel(HTTPChatModel):
    """wire / parse / translator; HTTPChatModel does the I/O (sync, native async, streaming)."""

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        return WireCall("/v1/generate", to_acme_body(request, model=self.id, safety=self.provider.config.safety,
                                                     max_tokens=self.effective_max_tokens(request),
                                                     temperature=self.effective_temperature(request),
                                                     stream=stream))

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        msg, finish = from_acme_output(data.get("output") or {}, data.get("stop") or "done")
        return ChatCompletion(model=data.get("model") or self.id, choices=[Choice(message=msg, finish_reason=finish)],
                              usage=acme_usage(data.get("tokens") or {}))

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return AcmeStreamTranslator(self, request)

    def classify(self, resp: httpx.Response) -> Optional[LLMError]:
        return self.provider.classify(resp)


# ── 4. The embedding model ──────────────────────────────────────────────────

class AcmeEmbeddingModel(EmbeddingModel):
    def _embed(self, texts: List[str], purpose: Optional[str] = None, dimensions: Optional[int] = None):
        # Acme has no query/document distinction and a fixed size (variable_dimensions is false,
        # so embeddings_create refuses a "dimensions" request before this is called)
        with self.provider.slot():
            data = post_json(self.provider.http, "/v1/embed", {"model": self.id, "inputs": list(texts)},
                             provider=self.provider.name, model=self.id, classify=self.provider.classify)
        tokens = (data.get("tokens") or {}).get("in")
        return (data.get("vectors") or [], int(tokens)) if tokens is not None else (data.get("vectors") or [])


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
