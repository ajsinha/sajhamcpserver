"""
SAJHA Intelligence Layer — the pre-6.x provider interface and its adapter (internal, deprecated).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The old provider ABC (``LegacyLLMProvider``, formerly ``sajha.ai.providers.LLMProvider``), its
registry (``register_provider_class``) and result types live here, so custom providers written
against it keep working: the factory wraps every class registered with
``register_provider_class`` in ``LegacyProviderAdapter`` and serves it through aliases, policy and
budgets like any other provider. The old interface has no tool-call parsing, so wrapped models
declare ``tools=False`` and tool requests go to the alias's next candidate.

New providers subclass sajha.ai.llm.spi.ProviderBase instead; extension code imports these names
from sajha.ai.llm.spi, not from this module.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from pydantic import Field

from sajha.ai.llm.errors import ProviderUnavailable, UnsupportedFeature
from sajha.ai.llm.model import ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import ChatRequest, ChatResponse, Message, TextPart

logger = logging.getLogger(__name__)


# ── the pre-6.x interface ───────────────────────────────────────

@dataclass
class LegacyModelInfo:
    """A model as the pre-6.x interface describes it."""
    id: str
    name: str
    provider: str
    context_window: int = 0
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    max_output_tokens: int = 4096
    tags: List[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """A completion as the pre-6.x interface returns it."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class EmbeddingResponse:
    embeddings: List[List[float]]
    model: str
    provider: str
    total_tokens: int = 0
    dimensions: int = 0


class LegacyLLMProvider(ABC):
    """The pre-6.x provider ABC (deprecated; subclass sajha.ai.llm.spi.ProviderBase instead)."""

    provider_type: str = "unknown"

    @abstractmethod
    def complete(self, messages: List[Dict[str, str]], model: str, temperature: float = 0.7,
                 max_tokens: int = 1024, system: str = "", tools: Optional[List[Dict]] = None,
                 **kwargs) -> LLMResponse:
        ...

    @abstractmethod
    def stream(self, messages: List[Dict[str, str]], model: str, temperature: float = 0.7,
               max_tokens: int = 1024, system: str = "", **kwargs) -> Iterator[str]:
        ...

    def embed(self, texts: List[str], model: str = "") -> EmbeddingResponse:
        raise NotImplementedError(f"{self.provider_type} does not support embeddings")

    @abstractmethod
    def list_models(self) -> List[LegacyModelInfo]:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...

    def get_default_model(self) -> str:
        models = self.list_models()
        return models[0].id if models else ""

    def get_default_embedding_model(self) -> str:
        return ""


_legacy_classes: Dict[str, type] = {}          # provider_type -> LegacyLLMProvider subclass
_legacy_instances: Dict[str, LegacyLLMProvider] = {}


def register_provider_class(provider_type: str, cls: type) -> None:
    """Register a pre-6.x provider class; the factory serves it through LegacyProviderAdapter."""
    if not issubclass(cls, LegacyLLMProvider):
        raise TypeError(f"{cls.__name__} must extend LegacyLLMProvider")
    _legacy_classes[provider_type] = cls
    logger.info(f"legacy LLM provider class registered: {provider_type} -> {cls.__name__}")


def unregister_provider_class(provider_type: str) -> None:
    _legacy_classes.pop(provider_type, None)
    for k in [k for k in _legacy_instances if k.startswith(provider_type + ":")]:
        _legacy_instances.pop(k, None)


def get_registered_types() -> Dict[str, str]:
    """Registered pre-6.x provider types -> class names."""
    return {k: v.__name__ for k, v in _legacy_classes.items()}


def create_provider(provider_type: str, **config) -> LegacyLLMProvider:
    """A cached instance of a registered pre-6.x provider class."""
    key = f"{provider_type}:{hash(frozenset(config.items()))}"
    if key in _legacy_instances:
        return _legacy_instances[key]
    cls = _legacy_classes.get(provider_type)
    if cls is None:
        raise ValueError(f"Unknown legacy LLM provider '{provider_type}' "
                         f"(registered: {sorted(_legacy_classes) or '(none)'})")
    inst = cls(**config)
    _legacy_instances[key] = inst
    return inst


# ── the adapter ─────────────────────────────────────────────────

class LegacyConfig(ProviderConfig):
    legacy_type: str = ""
    region: Optional[str] = None
    legacy_kwargs: Dict[str, Any] = Field(default_factory=dict)


def _legacy_messages(request: ChatRequest) -> List[Dict[str, str]]:
    out = []
    for m in request.messages:
        if m.role == "system":
            continue
        text = m.text
        for r in m.tool_results:
            text += f"\n[tool result {r.call_id}]\n{r.content_text()}"
        for c in m.tool_calls:
            text += f"\n[called {c.name}({c.arguments})]"
        out.append({"role": "assistant" if m.role == "assistant" else "user", "content": text})
    return out


class LegacyChatModel(ChatModel):
    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        legacy = self.provider.legacy()
        system = "\n\n".join([request.system] + [m.text for m in request.messages if m.role == "system"]).strip()
        try:
            with self.provider.slot():
                r = legacy.complete(_legacy_messages(request), self.id,
                                    temperature=request.temperature if request.temperature is not None else 0.7,
                                    max_tokens=self.effective_max_tokens(request), system=system)
        except Exception as e:
            raise ProviderUnavailable(f"{self.provider.name}: {e}", provider=self.provider.name, model=self.id)
        usage = self.make_usage(r.input_tokens, r.output_tokens)
        if r.cost_usd:
            usage.cost_usd = r.cost_usd
        finish = {"length": "length", "max_tokens": "length"}.get(r.finish_reason, "stop")
        return ChatResponse(Message("assistant", [TextPart(r.content)] if r.content else []), finish, usage,
                            r.model or self.id, self.provider.name, int((time.time() - t0) * 1000), raw=r.raw)


class LegacyEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        try:
            with self.provider.slot():
                return self.provider.legacy().embed(list(texts), model=self.id).embeddings
        except NotImplementedError:
            raise UnsupportedFeature(f"{self.provider.name} has no embeddings", provider=self.provider.name)


class LegacyProviderAdapter(ProviderBase):
    name = "legacy"
    config_model = LegacyConfig
    requires_key = False
    unknown_model_capabilities = ModelCapabilities(tools=False, structured_output=False, streaming=False)
    chat_model_class = LegacyChatModel
    embedding_model_class = LegacyEmbeddingModel

    def __init__(self, *a, legacy_instance=None, **kw):
        super().__init__(*a, **kw)
        self._legacy = legacy_instance

    def legacy(self):
        if self._legacy is None:
            kwargs = dict(self.config.legacy_kwargs or {})
            if self.api_key:
                kwargs.setdefault("api_key", self.api_key)
            if self.config.base_url:
                kwargs.setdefault("base_url", self.config.base_url)
            if self.config.region:
                kwargs.setdefault("region", self.config.region)
            self._legacy = create_provider(self.config.legacy_type or self.name, **kwargs)
        return self._legacy

    def live_models(self) -> List[ModelDescriptor]:
        out = []
        for mi in self.legacy().list_models():
            caps = ModelCapabilities(tools=False, structured_output=False, streaming=False,
                                     vision=bool(mi.supports_vision), context_window=mi.context_window,
                                     max_output_tokens=mi.max_output_tokens,
                                     input_cost_per_mtok=mi.input_cost_per_1k * 1000,
                                     output_cost_per_mtok=mi.output_cost_per_1k * 1000,
                                     tags=frozenset(mi.tags or []))
            out.append(ModelDescriptor(mi.id, caps, mi.name, source="live"))
        return out

    def default_chat_model_id(self) -> str:
        if self.config.default_model:
            return self.config.default_model
        try:
            return self.legacy().get_default_model()
        except Exception:
            return ""

    def default_embedding_model_id(self) -> str:
        return self.config.default_embedding_model or (self.legacy().get_default_embedding_model() or "")

    def health(self) -> HealthStatus:
        if not self.active:
            return HealthStatus("down", "disabled")
        try:
            return HealthStatus("ok" if self.legacy().health_check() else "down", "legacy health_check")
        except Exception as e:
            return HealthStatus("down", str(e)[:200])
