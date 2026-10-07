"""
SAJHA Intelligence Layer — Ollama, native API (plain httpx). Local, keyless, first-class.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

  /api/chat    chat, tools (message.tool_calls with object arguments; SAJHA synthesises ids),
               structured output via ``format`` (a JSON Schema), NDJSON streaming
  /api/embed   embeddings (batch input)
  /api/tags    the models pulled on this host -> list_models() (merged with the catalogue and
               config overrides), so a freshly pulled model appears without a restart
  /api/show    per-model capability detection (tools, vision, embedding, context length)

The adapter translates the canonical Chat Completions format to /api/chat: system/developer
-> system; images (data: URLs) -> ``images``; tool results carry ``tool_name`` (looked up from
the call); temperature, top_p, seed, stop and max tokens -> ``options``; json_schema ->
``format`` = the schema, json_object -> ``format: "json"``; reasoning_effort -> ``think``.
Ollama has no tool_choice, so "required" and named choices are refused (forced_tool_choice
false), never quietly downgraded to auto.

base_url defaults to http://localhost:11434; OLLAMA_HOST is honoured (a bare host:port gets
http://). keep_alive, num_ctx, think and any other ``options`` are passed through. health()
probes /api/tags with a short timeout and caches the answer, so an absent Ollama costs one
quick probe per health TTL, not one per request.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, ClassVar, Dict, List, Optional, Union

from pydantic import Field

from sajha.ai.llm.adapter import (HTTPChatModel, StreamTranslator, WireCall, assistant_text, tool_names,
                                  tool_result_text)
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    FunctionCall, ToolCall, split_data_url)
from sajha.ai.llm.errors import ProviderUnavailable
from sajha.ai.llm.http import get_json, post_json
from sajha.ai.llm.model import EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig

logger = logging.getLogger(__name__)
FINISH = {"stop": "stop", "length": "length", "load": "stop", "unload": "stop"}


class OllamaConfig(ProviderConfig):
    base_url: Optional[str] = "http://localhost:11434"
    keep_alive: Optional[Union[str, int]] = None        # e.g. "5m", 0, -1
    num_ctx: Optional[int] = None
    think: Optional[bool] = None
    options: Dict[str, Any] = Field(default_factory=dict)   # any Ollama runtime option
    detect_capabilities: bool = True                   # ask /api/show per model
    live_models: bool = True                           # list pulled models via /api/tags
    health_timeout_s: float = 1.0
    health_ttl_s: float = 30.0
    read_timeout_s: float = 300.0                      # local models can be slow to load

    vendor_env: ClassVar[Dict[str, List[str]]] = {"base_url": ["OLLAMA_HOST", "OLLAMA_BASE_URL"],
                                                  "api_key": ["OLLAMA_API_KEY"]}


def _norm(model_id: str) -> str:
    return model_id[:-7] if model_id.endswith(":latest") else model_id


# ── wire mapping (pure; golden-tested) ─────────────────────────────

THINK = {"none": False, "minimal": False, "low": "low", "medium": "medium", "high": "high", "xhigh": "high"}


def to_ollama_body(request: ChatCompletionRequest, *, model: str, cfg: "OllamaConfig", max_tokens: int,
                   temperature: Optional[float], stream: bool) -> Dict[str, Any]:
    names = tool_names(request)
    msgs: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer", "user"):
            imgs = [split_data_url(p.image_url.url)[1] for p in m.images]
            if m.text or imgs:
                um: Dict[str, Any] = {"role": "user" if m.role == "user" else "system", "content": m.text}
                if imgs:
                    um["images"] = imgs
                msgs.append(um)
        elif m.role == "assistant":
            am: Dict[str, Any] = {"role": "assistant", "content": assistant_text(m)}
            if m.tool_calls:
                am["tool_calls"] = [{"function": {"name": c.function.name, "arguments": c.function.args()}}
                                    for c in m.tool_calls]
            msgs.append(am)
        elif m.role == "tool":
            tname = (m.sajha.tool_name if m.sajha and m.sajha.tool_name else "") or names.get(m.tool_call_id or "", "")
            msgs.append({"role": "tool", "tool_name": tname, "content": tool_result_text(m)})
    opts: Dict[str, Any] = dict(cfg.options or {})
    if temperature is not None:
        opts["temperature"] = temperature
    if request.top_p is not None:
        opts["top_p"] = request.top_p
    if request.seed is not None:
        opts["seed"] = request.seed
    opts["num_predict"] = max_tokens
    if request.stop_list:
        opts["stop"] = request.stop_list
    if cfg.num_ctx:
        opts["num_ctx"] = cfg.num_ctx
    body: Dict[str, Any] = {"model": model, "messages": msgs, "stream": stream, "options": opts}
    if request.wants_tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t.name, "description": (t.function.description or "") if t.function else "",
            "parameters": t.parameters_or_default}} for t in request.tools or []]
    kind = request.output_kind
    if kind == "json_schema":
        body["format"] = request.output_schema
    elif kind == "json_object":
        body["format"] = "json"
    if cfg.keep_alive is not None:
        body["keep_alive"] = cfg.keep_alive
    if request.reasoning_effort is not None:
        body["think"] = THINK.get(request.reasoning_effort, True)
    elif cfg.think is not None:
        body["think"] = cfg.think
    body.update(request.extra_body or {})
    return body


def ollama_calls(raw: List[Dict[str, Any]], start: int = 0) -> List[ToolCall]:
    out = []
    for i, tc in enumerate(raw or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments") or {}
        if not isinstance(args, str):
            args = json.dumps(args)
        name = fn.get("name", "")
        out.append(ToolCall(id=tc.get("id") or f"ocall_{start + i + 1}_{name}",
                            function=FunctionCall(name=name, arguments=args or "{}")))
    return out


def ollama_usage(data: Dict[str, Any]) -> Optional[CompletionUsage]:
    if "prompt_eval_count" not in data and "eval_count" not in data:
        return None
    return CompletionUsage.of(data.get("prompt_eval_count") or 0, data.get("eval_count") or 0)


def parse_ollama(data: Dict[str, Any], model: str) -> ChatCompletion:
    m = data.get("message") or {}
    calls = ollama_calls(m.get("tool_calls") or [])
    finish = "tool_calls" if calls else FINISH.get(data.get("done_reason") or "stop", "stop")
    return ChatCompletion(model=data.get("model") or model, choices=[Choice(message=ChatMessage(
        role="assistant", content=m.get("content") or None, tool_calls=calls or None), finish_reason=finish)],
        usage=ollama_usage(data))


class OllamaStreamTranslator(StreamTranslator):
    def feed(self, event: str, chunk: Any) -> List:
        if chunk.get("error"):
            raise ProviderUnavailable(f"ollama: {chunk['error']}", provider=self.model.provider.name,
                                      model=self.model.id)
        out: List = []
        m = chunk.get("message") or {}
        out += self.text(m.get("content") or "")
        for c in ollama_calls(m.get("tool_calls") or [], len(self._calls)):
            out += self.tool_start(c.id, c.id, c.function.name, c.function.arguments)
        if chunk.get("done"):
            self.model_name = chunk.get("model") or self.model_name
            self.usage = ollama_usage(chunk)
            self.finish = FINISH.get(chunk.get("done_reason") or "stop", "stop")
        return out


class OllamaChatModel(HTTPChatModel):
    stream_format = "ndjson"

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        return WireCall("/api/chat", to_ollama_body(request, model=self.id, cfg=self.provider.config,
                                                    max_tokens=self.effective_max_tokens(request),
                                                    temperature=self.effective_temperature(request), stream=stream))

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        return parse_ollama(data, self.id)

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return OllamaStreamTranslator(self, request)


class OllamaEmbeddingModel(EmbeddingModel):
    def _embed(self, texts, purpose=None, dimensions=None):
        cfg = self.provider.config
        body: Dict[str, Any] = {"model": self.id, "input": list(texts)}
        if cfg.keep_alive is not None:
            body["keep_alive"] = cfg.keep_alive
        dims = dimensions or cfg.embedding_dimensions
        if dims:
            body["dimensions"] = dims
        with self.provider.slot():
            data = post_json(self.provider.http, "/api/embed", body, provider=self.provider.name, model=self.id)
        return data.get("embeddings") or []


@register_provider
class OllamaProvider(ProviderBase):
    name = "ollama"
    config_model = OllamaConfig
    requires_key = False
    default_base_url = "http://localhost:11434"
    catalog_key = "ollama"
    feature_defaults = {"seed": True, "reasoning_effort": "tagged", "json_mode": True, "variable_dimensions": True}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, context_window=8_192,
                                                   forced_tool_choice=False, tags=frozenset({"local"}))
    chat_model_class = OllamaChatModel
    embedding_model_class = OllamaEmbeddingModel
    live_models_ttl_s = 30.0

    def resolve_capabilities(self, caps: ModelCapabilities) -> ModelCapabilities:
        """/api/chat has no tool_choice: no model can be forced to call a tool, whatever the catalogue says."""
        from dataclasses import replace
        return replace(super().resolve_capabilities(caps), forced_tool_choice=False, named_tool_choice=False)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._health: Optional[HealthStatus] = None
        self._health_at = 0.0
        self._tags: Optional[List[str]] = None
        self._show_cache: Dict[str, ModelCapabilities] = {}
        self._hlock = threading.Lock()

    @property
    def base_url(self) -> str:
        url = (self.config.base_url or self.default_base_url).strip().rstrip("/")
        if "://" not in url:
            host = url if url and not url.startswith(":") else "localhost" + url
            if host.startswith("0.0.0.0"):
                host = "127.0.0.1" + host[7:]
            if ":" not in host:
                host += ":11434"
            url = "http://" + host
        return url

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # live catalogue
    def tags(self, refresh: bool = False) -> List[str]:
        if self._tags is not None and not refresh and time.time() - self._models_cache_at < self.live_models_ttl_s:
            return self._tags
        data = get_json(self.http, "/api/tags", provider=self.name, timeout=self.config.health_timeout_s * 3)
        self._tags = [_norm(m.get("name") or m.get("model") or "") for m in data.get("models") or []]
        return self._tags

    def _show(self, model_id: str) -> Optional[ModelCapabilities]:
        if model_id in self._show_cache:
            return self._show_cache[model_id]
        try:
            data = post_json(self.http, "/api/show", {"model": model_id}, provider=self.name)
        except Exception:
            return None
        caps_list = set(data.get("capabilities") or [])
        ctx = 0
        for k, v in (data.get("model_info") or {}).items():
            if k.endswith(".context_length") and isinstance(v, int):
                ctx = v
        if "embedding" in caps_list and "completion" not in caps_list:
            caps = ModelCapabilities(chat=False, embedding=True, streaming=False, tags=frozenset({"local"}))
        else:
            caps = ModelCapabilities(tools=("tools" in caps_list) if caps_list else True,
                                     structured_output=True, vision="vision" in caps_list,
                                     context_window=min(ctx, self.config.num_ctx or ctx) if ctx else 8_192,
                                     forced_tool_choice=False,
                                     tags=frozenset({"local"} | ({"reasoning"} if "thinking" in caps_list else set())))
        self._show_cache[model_id] = caps
        return caps

    def live_models(self) -> List[ModelDescriptor]:
        if not self.config.live_models or not self.health().ok:
            return []
        out = []
        for mid in self.tags(refresh=True):
            caps = self._show(mid) if self.config.detect_capabilities else None
            if caps is None:
                kind = "embedding" if "embed" in mid else "chat"
                caps = (ModelCapabilities(chat=False, embedding=True, streaming=False, tags=frozenset({"local"}))
                        if kind == "embedding" else self.unknown_model_capabilities)
            out.append(ModelDescriptor(mid, caps, kind="embedding" if caps.embedding else "chat", source="live"))
        return out

    def list_models(self) -> List[ModelDescriptor]:
        models = super().list_models()
        # a live entry with detected capabilities beats the catalogue's guess
        live = {d.id: d for d in (self.live_models() if self.config.live_models and self._health_ok_cached() else [])}
        out = []
        for d in models:
            ld = live.get(d.id)
            if ld is not None and self.config.detect_capabilities and d.source in ("catalog", "live"):
                out.append(ModelDescriptor(d.id, ld.capabilities, d.display_name, ld.kind, "live"))
            else:
                out.append(d)
        return out

    def _health_ok_cached(self) -> bool:
        return self._health is not None and self._health.ok

    def model_available(self, model_id: str) -> bool:
        if not self.config.live_models:
            return True
        try:
            return _norm(model_id) in self.tags()
        except Exception:
            return False

    def default_chat_model_id(self) -> str:
        if self.config.default_model:
            return self.config.default_model
        preferred = super().default_chat_model_id()
        try:
            pulled = self.tags() if self.health().ok else []
        except Exception:
            pulled = []
        if not pulled or preferred in pulled:
            return preferred
        chats = [d for d in self.list_models() if d.kind == "chat" and d.id in pulled]
        withtools = [d.id for d in chats if d.capabilities.tools]
        return (withtools or [d.id for d in chats] or [preferred])[0]

    def default_embedding_model_id(self) -> str:
        if self.config.default_embedding_model:
            return self.config.default_embedding_model
        preferred = super().default_embedding_model_id()
        try:
            pulled = self.tags() if self.health().ok else []
        except Exception:
            pulled = []
        if not pulled or preferred in pulled:
            return preferred
        embs = [d.id for d in self.list_models() if d.kind == "embedding" and d.id in pulled]
        return embs[0] if embs else preferred

    def health(self) -> HealthStatus:
        if self.config.enabled is False:
            return HealthStatus("down", "disabled")
        with self._hlock:
            if self._health is not None and time.time() - self._health_at < self.config.health_ttl_s:
                return self._health
            try:
                data = get_json(self.http, "/api/tags", provider=self.name, timeout=self.config.health_timeout_s)
                n = len(data.get("models") or [])
                self._tags = [_norm(m.get("name") or m.get("model") or "") for m in data.get("models") or []]
                self._health = HealthStatus("ok" if n else "degraded",
                                            f"{self.base_url}: {n} model(s) pulled")
            except Exception as e:
                self._health = HealthStatus("down", f"{self.base_url} unreachable ({e.__class__.__name__})")
            self._health_at = time.time()
            return self._health
