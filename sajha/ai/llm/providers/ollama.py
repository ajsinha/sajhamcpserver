"""
SAJHA Intelligence Layer — Ollama, native API (plain httpx). Local, keyless, first-class.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

  /api/chat    chat, tools (message.tool_calls with object arguments; SAJHA synthesises ids),
               structured output via ``format`` (a JSON Schema), NDJSON streaming
  /api/embed   embeddings (batch input)
  /api/tags    the models pulled on this host -> list_models() (merged with the catalogue and
               config overrides), so a freshly pulled model appears without a restart
  /api/show    per-model capability detection (tools, vision, embedding, context length)

base_url defaults to http://localhost:11434; OLLAMA_HOST is honoured (a bare host:port gets
http://). keep_alive, num_ctx, think and any other ``options`` are passed through. health()
probes /api/tags with a short timeout and caches the answer, so an absent Ollama costs one
quick probe per health TTL, not one per request.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, ClassVar, Dict, Iterator, List, Optional, Union

from pydantic import Field

from sajha.ai.llm.http import get_json, iter_ndjson, post_json, stream_post
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities,
                                ModelDescriptor)
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, UsageEvent)

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


class OllamaChatModel(ChatModel):
    def _options(self, request: ChatRequest) -> Dict[str, Any]:
        cfg = self.provider.config
        opts: Dict[str, Any] = dict(cfg.options or {})
        t = self.effective_temperature(request)
        if t is not None:
            opts["temperature"] = t
        opts["num_predict"] = self.effective_max_tokens(request)
        if request.stop:
            opts["stop"] = list(request.stop)
        if cfg.num_ctx:
            opts["num_ctx"] = cfg.num_ctx
        return opts

    def payload(self, request: ChatRequest, stream: bool) -> Dict[str, Any]:
        cfg = self.provider.config
        names: Dict[str, str] = {}
        msgs: List[Dict[str, Any]] = []
        if request.system:
            msgs.append({"role": "system", "content": request.system})
        for m in request.messages:
            for c in m.tool_calls:
                names[c.id] = c.name
            if m.role in ("system", "user"):
                if m.text or any(isinstance(p, ImagePart) for p in m.parts):
                    um: Dict[str, Any] = {"role": m.role, "content": m.text}
                    imgs = [base64.b64encode(p.data).decode() for p in m.parts if isinstance(p, ImagePart)]
                    if imgs:
                        um["images"] = imgs
                    msgs.append(um)
            elif m.role == "assistant":
                am: Dict[str, Any] = {"role": "assistant", "content": m.text}
                if m.tool_calls:
                    am["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                        for c in m.tool_calls]
                msgs.append(am)
            for r in m.tool_results:
                msgs.append({"role": "tool", "tool_name": r.name or names.get(r.call_id, ""),
                             "content": ("ERROR: " if r.is_error else "") + r.content_text()})
        body: Dict[str, Any] = {"model": self.id, "messages": msgs, "stream": stream,
                                "options": self._options(request)}
        if request.tools and request.tool_choice != "none":
            body["tools"] = [{"type": "function", "function": {"name": s.name, "description": s.description,
                                                               "parameters": s.input_schema or {"type": "object"}}}
                             for s in request.tools]
        if request.response_schema:
            body["format"] = request.response_schema
        if cfg.keep_alive is not None:
            body["keep_alive"] = cfg.keep_alive
        if cfg.think is not None:
            body["think"] = cfg.think
        return body

    def _calls(self, raw: List[Dict[str, Any]], start: int = 0) -> List[ToolCallPart]:
        out = []
        for i, tc in enumerate(raw or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"_raw": args}
            name = fn.get("name", "")
            out.append(ToolCallPart(tc.get("id") or f"ocall_{start + i + 1}_{name}", name, args))
        return out

    def _usage(self, data: Dict[str, Any]):
        return self.make_usage(data.get("prompt_eval_count") or 0, data.get("eval_count") or 0)

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        with self.provider.slot():
            data = post_json(self.provider.http, "/api/chat", self.payload(request, False),
                             provider=self.provider.name, model=self.id)
        m = data.get("message") or {}
        parts: List[Any] = [TextPart(m["content"])] if m.get("content") else []
        calls = self._calls(m.get("tool_calls") or [])
        parts.extend(calls)
        finish = "tool_calls" if calls else FINISH.get(data.get("done_reason") or "stop", "stop")
        return ChatResponse(Message("assistant", parts), finish, self._usage(data), data.get("model") or self.id,
                            self.provider.name, int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        text: List[str] = []
        calls: List[ToolCallPart] = []
        final: Dict[str, Any] = {}
        with self.provider.slot():
            with stream_post(self.provider.http, "/api/chat", self.payload(request, True),
                             provider=self.provider.name, model=self.id) as resp:
                for chunk in iter_ndjson(resp):
                    if chunk.get("error"):
                        from sajha.ai.llm.errors import ProviderUnavailable
                        raise ProviderUnavailable(f"ollama: {chunk['error']}", provider=self.provider.name,
                                                  model=self.id)
                    m = chunk.get("message") or {}
                    if m.get("content"):
                        text.append(m["content"])
                        yield TextDelta(m["content"])
                    for c in self._calls(m.get("tool_calls") or [], len(calls)):
                        calls.append(c)
                        yield ToolCallDelta(c.id, c.name, json.dumps(c.arguments), len(calls) - 1)
                    if chunk.get("done"):
                        final = chunk
        parts: List[Any] = [TextPart("".join(text))] if text else []
        parts.extend(calls)
        usage = self._usage(final)
        finish = "tool_calls" if calls else FINISH.get(final.get("done_reason") or "stop", "stop")
        yield UsageEvent(usage)
        yield Done(ChatResponse(Message("assistant", parts), finish, usage, self.id, self.provider.name,
                                int((time.time() - t0) * 1000)))


class OllamaEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        cfg = self.provider.config
        body: Dict[str, Any] = {"model": self.id, "input": list(texts)}
        if cfg.keep_alive is not None:
            body["keep_alive"] = cfg.keep_alive
        if cfg.embedding_dimensions:
            body["dimensions"] = cfg.embedding_dimensions
        with self.provider.slot():
            data = post_json(self.provider.http, "/api/embed", body, provider=self.provider.name, model=self.id)
        return data.get("embeddings") or []


@register_provider
class OllamaProvider(LLMProvider):
    name = "ollama"
    config_model = OllamaConfig
    requires_key = False
    default_base_url = "http://localhost:11434"
    catalog_key = "ollama"
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, context_window=8_192,
                                                   forced_tool_choice=False, tags=frozenset({"local"}))
    chat_model_class = OllamaChatModel
    embedding_model_class = OllamaEmbeddingModel
    live_models_ttl_s = 30.0

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
