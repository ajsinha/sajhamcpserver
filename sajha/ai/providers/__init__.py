"""
SAJHA MCP Server — LLM Provider Abstraction
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Abstract base for all LLM providers. Concrete implementations:
- AnthropicProvider (Claude via API)
- OpenAIProvider (GPT via API)
- BedrockProvider (AWS Bedrock — Claude, Titan, Llama, Mistral)
- TogetherProvider (Together.ai — open-source models)
- OllamaProvider (Local models via Ollama)
- AzureOpenAIProvider (Azure-hosted OpenAI models)

Usage:
    from sajha.ai.providers import create_provider
    provider = create_provider('anthropic', api_key='sk-...')
    response = provider.complete([{"role": "user", "content": "Hello"}], model="claude-sonnet-4-20250514")
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────

class ProviderType(str, Enum):
    ANTHROPIC = 'anthropic'
    OPENAI = 'openai'
    BEDROCK = 'bedrock'
    TOGETHER = 'together'
    OLLAMA = 'ollama'
    AZURE_OPENAI = 'azure_openai'


@dataclass
class ModelInfo:
    """Describes an available model."""
    id: str                          # e.g. "claude-sonnet-4-20250514"
    name: str                        # e.g. "Claude Sonnet 4"
    provider: str                    # e.g. "anthropic"
    context_window: int = 0          # max tokens
    input_cost_per_1k: float = 0.0   # USD per 1K input tokens
    output_cost_per_1k: float = 0.0  # USD per 1K output tokens
    supports_tools: bool = True
    supports_vision: bool = False
    supports_streaming: bool = True
    max_output_tokens: int = 4096
    tags: List[str] = field(default_factory=list)  # ["fast", "reasoning", "code"]


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str        # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM completion."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = 'stop'
    latency_ms: int = 0
    cost_usd: float = 0.0
    raw: Optional[Dict[str, Any]] = None  # full provider response


@dataclass
class EmbeddingResponse:
    """Response from an embedding request."""
    embeddings: List[List[float]]
    model: str
    provider: str
    total_tokens: int = 0
    dimensions: int = 0


# ── Abstract Base ────────────────────────────────────────────

class LLMProvider(ABC):
    """
    Abstract LLM provider. All providers implement the same interface.
    SAJHA's LLMGateway delegates to these providers based on config.
    """

    provider_type: str = 'unknown'

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system: str = '',
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> LLMResponse:
        """Synchronous completion. Returns full response."""
        ...

    @abstractmethod
    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system: str = '',
        **kwargs,
    ) -> Iterator[str]:
        """Streaming completion. Yields content chunks."""
        ...

    def embed(
        self,
        texts: List[str],
        model: str = '',
    ) -> EmbeddingResponse:
        """Generate embeddings. Not all providers support this."""
        raise NotImplementedError(f"{self.provider_type} does not support embeddings")

    @abstractmethod
    def list_models(self) -> List[ModelInfo]:
        """List available models for this provider."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Test provider connectivity. Returns True if healthy."""
        ...

    def get_default_model(self) -> str:
        """Return the recommended default model for this provider."""
        models = self.list_models()
        return models[0].id if models else ''

    def get_default_embedding_model(self) -> str:
        """Return the default embedding model."""
        return ''


# ── Provider Registry (Factory Pattern) ──────────────────────
#
# Register provider classes by type. Adding a new provider
# (including custom/local ones) requires only:
#
#   from sajha.ai.providers import register_provider_class
#   register_provider_class('my_local', MyLocalProvider)
#
# The factory instantiates from the registry — no if/elif chain.

_registry: Dict[str, type] = {}    # provider_type → LLMProvider subclass
_instances: Dict[str, LLMProvider] = {}  # cache_key → instantiated provider


def register_provider_class(provider_type: str, cls: type) -> None:
    """Register a provider class in the factory.

    Args:
        provider_type: Unique identifier (e.g. 'anthropic', 'my_local_llm')
        cls: Class that extends LLMProvider

    Usage:
        # In your custom provider file:
        class MyLocalProvider(LLMProvider):
            provider_type = 'my_local'
            ...

        register_provider_class('my_local', MyLocalProvider)

        # Then configure in DB (llm_providers table) or application.yml
    """
    if not issubclass(cls, LLMProvider):
        raise TypeError(f"{cls.__name__} must extend LLMProvider")
    _registry[provider_type] = cls
    logger.info(f"LLM provider class registered: {provider_type} → {cls.__name__}")


def get_registered_types() -> Dict[str, str]:
    """Return all registered provider types → class names."""
    return {k: v.__name__ for k, v in _registry.items()}


def create_provider(provider_type: str, **config) -> LLMProvider:
    """Create (or return cached) provider instance from the registry.

    Resolution order:
    1. Check instance cache (same type + config → same instance)
    2. Look up class in _registry
    3. Instantiate with **config
    4. Cache and return

    Raises ValueError if provider_type is not registered.
    """
    cache_key = f"{provider_type}:{hash(frozenset(config.items()))}"
    if cache_key in _instances:
        return _instances[cache_key]

    cls = _registry.get(provider_type)
    if cls is None:
        available = ', '.join(sorted(_registry.keys())) or '(none)'
        raise ValueError(
            f"Unknown LLM provider: '{provider_type}'. "
            f"Registered: [{available}]. "
            f"Use register_provider_class('{provider_type}', YourProviderClass) to add it."
        )

    provider = cls(**config)
    _instances[cache_key] = provider
    logger.info(f"LLM provider created: {provider_type} ({cls.__name__})")
    return provider


def get_provider(provider_type: str) -> Optional[LLMProvider]:
    """Get a cached provider instance by type."""
    for key, p in _instances.items():
        if key.startswith(provider_type + ':'):
            return p
    return None


# ── Auto-Register Built-in Providers ─────────────────────────
# Each built-in provider registers itself on import.
# Custom providers register via register_provider_class().

def _auto_register_builtins():
    """Register all built-in provider classes. Called once at module load."""
    from sajha.ai.providers.anthropic_provider import AnthropicProvider
    from sajha.ai.providers.openai_provider import OpenAIProvider
    from sajha.ai.providers.bedrock_provider import BedrockProvider
    from sajha.ai.providers.together_provider import TogetherProvider
    from sajha.ai.providers.ollama_provider import OllamaProvider
    from sajha.ai.providers.azure_openai_provider import AzureOpenAIProvider

    register_provider_class(ProviderType.ANTHROPIC, AnthropicProvider)
    register_provider_class(ProviderType.OPENAI, OpenAIProvider)
    register_provider_class(ProviderType.BEDROCK, BedrockProvider)
    register_provider_class(ProviderType.TOGETHER, TogetherProvider)
    register_provider_class(ProviderType.OLLAMA, OllamaProvider)
    register_provider_class(ProviderType.AZURE_OPENAI, AzureOpenAIProvider)


try:
    _auto_register_builtins()
except ImportError as e:
    logger.warning(f"Some built-in LLM providers failed to register: {e}")
