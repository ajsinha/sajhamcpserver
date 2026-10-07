"""
SAJHA Intelligence Layer — the abstract LLM API.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Two abstract base classes every provider module implements, shaped like an OpenAI client
(docs/architecture/LLM Tools.md §13.3):

    LLMModel      one model: chat_completions_create / chat_completions_stream and their async
                  twins, embeddings_create / aembeddings_create, and info() (one entry of
                  GET /v1/models). A chat model refuses embeddings with UnsupportedFeature and an
                  embedding model refuses chat the same way.
    LLMProvider   a vendor or runtime: a factory for its LLMModel objects (model, chat_model,
                  embedding_model), its catalogue (models), health, configuration and close.

Application code never sees which provider is behind an LLMModel: the factory
(sajha.ai.llm.llm_factory) hands out GovernedModel proxies that implement LLMModel and delegate
to a provider's model after policy, budgets, cache, retries and fallback. Provider authors
subclass the shared implementations in sajha.ai.llm.spi (ProviderBase, ChatModel,
EmbeddingModel), which implement these classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, AsyncIterator, ClassVar, Dict, Iterator, List, Optional, Type

if TYPE_CHECKING:   # pragma: no cover
    from sajha.ai.llm.canonical import ChatCompletion, ChatCompletionChunk, EmbeddingsResponse
    from sajha.ai.llm.model import HealthStatus, ModelInfo


class LLMModel(ABC):
    """One model behind an OpenAI-style interface. ``request`` is a canonical request object, a
    dict, or keyword fields (``messages=[...]``, ``input=[...]``)."""

    @abstractmethod
    def info(self) -> "ModelInfo":
        """The model as one entry of GET /v1/models (id, provider, kind, capabilities)."""

    @abstractmethod
    def chat_completions_create(self, request: Any = None, /, **fields) -> "ChatCompletion":
        """POST /v1/chat/completions."""

    @abstractmethod
    async def achat_completions_create(self, request: Any = None, /, **fields) -> "ChatCompletion":
        """The native-async twin of chat_completions_create."""

    @abstractmethod
    def chat_completions_stream(self, request: Any = None, /, **fields) -> Iterator["ChatCompletionChunk"]:
        """POST /v1/chat/completions with stream=true, as chunks."""

    @abstractmethod
    def achat_completions_stream(self, request: Any = None, /, **fields) -> AsyncIterator["ChatCompletionChunk"]:
        """The async twin of chat_completions_stream (an async generator)."""

    @abstractmethod
    def embeddings_create(self, request: Any = None, /, **fields) -> "EmbeddingsResponse":
        """POST /v1/embeddings."""

    @abstractmethod
    async def aembeddings_create(self, request: Any = None, /, **fields) -> "EmbeddingsResponse":
        """The async twin of embeddings_create."""


class LLMProvider(ABC):
    """A vendor or runtime: credentials, HTTP clients, a model catalogue, and a factory for its
    models. Register a concrete subclass (sajha.ai.llm.spi.register_provider) and the factory
    builds it from ``ai.providers`` in application.yml."""

    name: ClassVar[str] = ""
    config_model: ClassVar[Type[Any]]

    @classmethod
    @abstractmethod
    def from_settings(cls, name: str, config: Optional[Dict[str, Any]] = None, **kw) -> "LLMProvider":
        """Build the provider from its ``ai.providers[].config`` block plus env, DB and secrets."""

    @property
    @abstractmethod
    def active(self) -> bool:
        """Enabled (explicitly, or ``auto`` with credentials present)."""

    @abstractmethod
    def models(self) -> List["ModelInfo"]:
        """Every model of this provider with resolved capabilities (like GET /v1/models)."""

    @abstractmethod
    def model(self, name: str = "", kind: str = "") -> LLMModel:
        """A model by id; ``kind`` (chat | embedding) defaults to what the catalogue says."""

    @abstractmethod
    def chat_model(self, model_id: str = "", **options) -> LLMModel:
        """A chat model (the provider's default when ``model_id`` is empty)."""

    @abstractmethod
    def embedding_model(self, model_id: str = "") -> LLMModel:
        """An embedding model (the provider's default when ``model_id`` is empty)."""

    @abstractmethod
    def health(self) -> "HealthStatus":
        """Cheap and bounded; the factory caches it for ai.gateway.health_ttl_s."""

    @abstractmethod
    def describe_config(self) -> Dict[str, Any]:
        """The effective configuration with the source of each value (secrets masked)."""

    @abstractmethod
    def close(self) -> None:
        """Release HTTP clients and other resources."""


__all__ = ["LLMModel", "LLMProvider"]
