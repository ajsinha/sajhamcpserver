"""
SAJHA Intelligence Layer — the provider base class.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A provider owns credentials, the HTTP clients (sync and async) and the model catalogue, and
is a factory for ChatModel / EmbeddingModel objects. Its settings are a pydantic
``config_model`` resolved from env > vendor env > application.yml > DB > default (see
settings.py).

The provider interface mirrors an OpenAI-style client (LLM Tools.md §13.3):

    provider.models()            -> list[ModelInfo]    like GET /v1/models
    provider.model(name)         -> ChatModel | EmbeddingModel

Class attributes a provider sets besides ``name`` and ``config_model``:

    openai_compatible   True for Chat Completions servers: passed-through fields are accepted
    developer_role      True when the vendor takes role "developer" (else it is sent as system)
    feature_defaults    defaults for the canonical feature flags of its models (model.FEATURE_FLAGS);
                        "tagged" means "models tagged reasoning"

Credentials that expire (Entra ID, Google service accounts and workload identity) are served
per request by ``request_headers()`` / ``arequest_headers()``, which a provider overrides;
static ones go in ``auth_headers()``.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from abc import ABC
from contextlib import asynccontextmanager, contextmanager
from typing import Any, ClassVar, Dict, List, Optional, Type, Union

from sajha.ai.llm.catalog import CATALOG, DEFAULT_MODELS
from sajha.ai.llm.errors import ProviderUnavailable, UnsupportedFeature
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities,
                                ModelDescriptor, ModelInfo)
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import ModelOverride, ProviderConfig, describe, resolve_layers

logger = logging.getLogger(__name__)

_FLAG_MAP = {"t": ("tools", True), "s": ("structured_output", True), "v": ("vision", True),
             "n": ("temperature", False), "f": ("forced_tool_choice", False)}


def descriptor_from_row(row, source: str = "catalog") -> ModelDescriptor:
    mid, kind, ctx, max_out, cin, cout, flags, tags = row
    tagset = frozenset(t for t in tags.split(",") if t)
    if kind == "embedding":
        caps = ModelCapabilities(chat=False, embedding=True, streaming=False, dimensions=int(ctx),
                                 input_cost_per_mtok=cin, tags=tagset)
    else:
        kw = {attr: val for f, (attr, val) in _FLAG_MAP.items() if f in flags}
        caps = ModelCapabilities(context_window=int(ctx), max_output_tokens=int(max_out) or 4096,
                                 input_cost_per_mtok=cin, output_cost_per_mtok=cout, tags=tagset, **kw)
    return ModelDescriptor(mid, caps, kind=kind, source=source)


def apply_override(base: Optional[ModelDescriptor], ov: ModelOverride, default_caps: ModelCapabilities,
                   source: str) -> Optional[ModelDescriptor]:
    if not ov.enabled:
        return None
    if base is None:
        if ov.kind == "embedding":
            caps = ModelCapabilities(chat=False, embedding=True, streaming=False)
        else:
            caps = default_caps
        base = ModelDescriptor(ov.id, caps, kind=ov.kind, source=source)
    fields = ov.model_dump(exclude={"id", "kind", "display_name", "enabled", "deployment"})
    caps = base.capabilities.merged(**fields)
    return ModelDescriptor(ov.id, caps, display_name=ov.display_name or base.display_name,
                           kind=ov.kind or base.kind, source=source,
                           deployment=ov.deployment or base.deployment)


class LLMProvider(ABC):
    """A vendor or runtime. Subclass, set ``name`` and ``config_model``, register it."""

    name: ClassVar[str] = ""
    config_model: ClassVar[Type[ProviderConfig]] = ProviderConfig
    requires_key: ClassVar[bool] = True
    default_base_url: ClassVar[str] = ""
    catalog_key: ClassVar[str] = ""
    # capabilities assumed for a model id that is neither in the catalogue nor in config
    unknown_model_capabilities: ClassVar[ModelCapabilities] = ModelCapabilities(tools=True)
    chat_model_class: ClassVar[Optional[type]] = None
    embedding_model_class: ClassVar[Optional[type]] = None
    live_models_ttl_s: ClassVar[float] = 60.0
    openai_compatible: ClassVar[bool] = False
    developer_role: ClassVar[bool] = False
    feature_defaults: ClassVar[Dict[str, Any]] = {}

    def __init__(self, config: Optional[ProviderConfig] = None, secrets: Optional[SecretStore] = None, *,
                 instance_name: str = "", sources: Optional[Dict[str, str]] = None,
                 db_models: Optional[List[ModelOverride]] = None, transport: Any = None):
        self.config = config if config is not None else self.config_model()
        self.secrets = secrets or SecretStore()
        self.name = instance_name or type(self).name
        self.sources = dict(sources or {})
        self.db_models = list(db_models or [])
        self._transport = transport          # httpx transport injected by tests
        self._client = None
        self._client_lock = threading.Lock()
        self._aclients: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()   # event loop -> AsyncClient
        self._sem = threading.BoundedSemaphore(max(1, int(self.config.max_concurrency or 1)))
        self._models_cache: Optional[Dict[str, ModelDescriptor]] = None
        self._models_cache_at = 0.0

    # ── construction from settings ────────────────────────────────
    @classmethod
    def from_settings(cls, name: str, config: Optional[Dict[str, Any]] = None, *,
                      db: Optional[Dict[str, Any]] = None, db_models: Optional[List[ModelOverride]] = None,
                      secrets: Optional[SecretStore] = None, environ: Optional[Dict[str, str]] = None,
                      transport: Any = None) -> "LLMProvider":
        cfg, sources = resolve_layers(cls.config_model, name, config, db=db, environ=environ)
        return cls(cfg, secrets, instance_name=name, sources=sources, db_models=db_models, transport=transport)

    # ── credentials and activation ────────────────────────────────
    @property
    def api_key(self) -> Optional[str]:
        if self.config.api_key is not None:
            v = self.config.api_key.get_secret_value()
            if v:
                return v
        if self.config.api_key_ref:
            return self.secrets.resolve(self.config.api_key_ref)
        return None

    @property
    def base_url(self) -> str:
        return (self.config.base_url or self.default_base_url or "").rstrip("/")

    def auto_enabled(self) -> bool:
        return bool(self.api_key) if self.requires_key else True

    @property
    def active(self) -> bool:
        e = self.config.enabled
        return self.auto_enabled() if e == "auto" else bool(e)

    def auth_headers(self) -> Dict[str, str]:
        """Static headers set once on the HTTP clients."""
        return {}

    def request_headers(self) -> Dict[str, str]:
        """Per-request headers (short-lived tokens). Default: none."""
        return {}

    async def arequest_headers(self) -> Dict[str, str]:
        import anyio
        return await anyio.to_thread.run_sync(self.request_headers)

    def resolve_capabilities(self, caps: ModelCapabilities) -> ModelCapabilities:
        """A model's declared capabilities with unset feature flags taken from feature_defaults."""
        return caps.resolved(type(self).feature_defaults)

    # ── HTTP ───────────────────────────────────────────────────────
    @property
    def http(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    from sajha.ai.llm.http import build_client
                    self._client = build_client(self.config, base_url=self.base_url,
                                                headers=self.auth_headers(), transport=self._transport)
        return self._client

    @property
    def ahttp(self):
        """The httpx.AsyncClient for the running event loop (clients are bound to their loop)."""
        import asyncio
        loop = asyncio.get_running_loop()
        client = self._aclients.get(loop)
        if client is None:
            from sajha.ai.llm.http import build_async_client
            client = build_async_client(self.config, base_url=self.base_url, headers=self.auth_headers(),
                                        transport=self._transport)
            self._aclients[loop] = client
        return client

    @asynccontextmanager
    async def aslot(self, timeout: Optional[float] = None):
        """The async twin of slot(): waits without blocking the event loop."""
        import anyio
        t = timeout if timeout is not None else self.config.read_timeout_s
        deadline = time.monotonic() + t
        while not self._sem.acquire(blocking=False):
            if time.monotonic() >= deadline:
                raise ProviderUnavailable(f"{self.name}: max_concurrency reached", provider=self.name)
            await anyio.sleep(0.005)
        try:
            yield
        finally:
            self._sem.release()

    @contextmanager
    def slot(self, timeout: Optional[float] = None):
        """Bound concurrent calls to max_concurrency."""
        t = timeout if timeout is not None else self.config.read_timeout_s
        if not self._sem.acquire(timeout=t):
            raise ProviderUnavailable(f"{self.name}: max_concurrency reached", provider=self.name)
        try:
            yield
        finally:
            self._sem.release()

    # ── models ─────────────────────────────────────────────────────
    def live_models(self) -> List[ModelDescriptor]:
        """Models discovered from the provider itself (Ollama /api/tags). Default: none."""
        return []

    def list_models(self) -> List[ModelDescriptor]:
        now = time.time()
        if self._models_cache is not None and now - self._models_cache_at < self.live_models_ttl_s:
            return list(self._models_cache.values())
        out: Dict[str, ModelDescriptor] = {}
        if self.config.catalog:
            for row in CATALOG.get(self.catalog_key or type(self).name, []):
                d = descriptor_from_row(row)
                out[d.id] = d
        try:
            for d in self.live_models():
                base = out.get(d.id)
                out[d.id] = d if base is None else ModelDescriptor(d.id, base.capabilities, base.display_name,
                                                                   base.kind, "live", base.deployment)
        except Exception as e:
            logger.debug(f"{self.name}: live model listing failed: {e}")
        from sajha.ai.llm.registry import registered_models_for
        for mid, mcls in registered_models_for(self.name).items():
            caps = getattr(mcls, "capabilities", None)
            if isinstance(caps, ModelCapabilities):
                kind = "embedding" if issubclass(mcls, EmbeddingModel) else "chat"
                out[mid] = ModelDescriptor(mid, caps, kind=kind, source="registered")
        for source, overrides in (("db", self.db_models), ("config", self.config.models)):
            for ov in overrides:
                d = apply_override(out.get(ov.id), ov, self.unknown_model_capabilities, source)
                if d is None:
                    out.pop(ov.id, None)
                else:
                    out[ov.id] = d
        self._models_cache, self._models_cache_at = out, now
        return list(out.values())

    def models(self) -> List[ModelInfo]:
        """Every model of this provider with its resolved capabilities (like GET /v1/models)."""
        return [ModelInfo(d.id, self.name, d.kind, self.resolve_capabilities(d.capabilities),
                          d.display_name, d.source) for d in self.list_models()]

    def model(self, name: str = "", kind: str = "") -> Union[ChatModel, EmbeddingModel]:
        """A model by id; ``kind`` (chat | embedding) defaults to what the catalogue says."""
        if not kind:
            kind = self.describe_model(name).kind if name else "chat"
        return self.embedding_model(name) if kind == "embedding" else self.chat_model(name)

    def describe_model(self, model_id: str, kind: str = "chat") -> ModelDescriptor:
        for d in self.list_models():
            if d.id == model_id:
                return d
        if kind == "embedding":
            return ModelDescriptor(model_id, ModelCapabilities(chat=False, embedding=True, streaming=False,
                                                               dimensions=self.config.embedding_dimensions or 0),
                                   kind="embedding", source="unknown")
        return ModelDescriptor(model_id, self.unknown_model_capabilities, source="unknown")

    def default_chat_model_id(self) -> str:
        if self.config.default_model:
            return self.config.default_model
        d = DEFAULT_MODELS.get(self.catalog_key or type(self).name, ("", ""))[0]
        if d:
            return d
        chats = [m.id for m in self.list_models() if m.kind == "chat"]
        return chats[0] if chats else ""

    def default_embedding_model_id(self) -> str:
        if self.config.default_embedding_model:
            return self.config.default_embedding_model
        d = DEFAULT_MODELS.get(self.catalog_key or type(self).name, ("", ""))[1]
        if d:
            return d
        embs = [m.id for m in self.list_models() if m.kind == "embedding"]
        return embs[0] if embs else ""

    def chat_model(self, model_id: str = "", **options) -> ChatModel:
        model_id = model_id or self.default_chat_model_id()
        if not model_id:
            raise UnsupportedFeature(f"{self.name}: no model configured", provider=self.name)
        desc = self.describe_model(model_id)
        if desc.kind == "embedding":
            raise UnsupportedFeature(f"{self.name}/{model_id} is an embedding model", provider=self.name,
                                     model=model_id)
        from sajha.ai.llm.registry import model_class
        cls = model_class(self.name, model_id) or self.chat_model_class
        if cls is None or not issubclass(cls, ChatModel):
            raise UnsupportedFeature(f"{self.name} has no chat models", provider=self.name)
        caps = desc.capabilities
        if not self.config.streaming and caps.streaming:
            caps = caps.merged(streaming=False)
        return cls(self, model_id, caps, deployment=desc.deployment, **options)

    def embedding_model(self, model_id: str = "") -> EmbeddingModel:
        model_id = model_id or self.default_embedding_model_id()
        from sajha.ai.llm.registry import model_class
        cls = model_class(self.name, model_id) or self.embedding_model_class
        if not model_id or cls is None or not issubclass(cls, EmbeddingModel):
            raise UnsupportedFeature(f"{self.name} has no embedding models", provider=self.name)
        desc = self.describe_model(model_id, kind="embedding")
        dims = self.config.embedding_dimensions or desc.capabilities.dimensions
        return cls(self, model_id, dims, desc.capabilities)

    # ── health and lifecycle ───────────────────────────────────────
    def health(self) -> HealthStatus:
        """Cheap by default: configured or not. Local runtimes override with a probe."""
        if not self.active:
            return HealthStatus("down", "disabled" if self.config.enabled is False else "not configured")
        if self.requires_key and not self.api_key:
            return HealthStatus("down", "no API key")
        return HealthStatus("ok", "configured")

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._aclients = weakref.WeakKeyDictionary()     # async clients die with their loops

    def describe_config(self) -> Dict[str, Any]:
        sources = dict(self.sources)
        if sources.get("api_key") == "default" and self.config.api_key_ref and self.api_key:
            sources["api_key"] = f"ref:{self.config.api_key_ref}"
        fields = describe(self.config, sources)
        if self.config.api_key is None and self.config.api_key_ref:
            fields["api_key"] = {"value": "********" if self.api_key else "", "source": sources["api_key"]}
        return {"name": self.name, "class": f"{type(self).__module__}:{type(self).__name__}",
                "active": self.active, "requires_key": self.requires_key,
                "has_key": bool(self.api_key), "base_url": self.base_url, "settings": fields}
