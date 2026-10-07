"""
SAJHA Intelligence Layer — the provider SPI (for code that adds a provider or a model).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Application code uses ``sajha.ai.llm`` (the factory, GovernedModel, the canonical types and the
errors) and never this module. A provider module, inside this package or a plug-in shipped
elsewhere (``ai.providers[].class: package.module:Class`` or an entry point in the
``sajha.llm_providers`` group), builds on the shared implementations exported here:

    ProviderBase      implements the abstract LLMProvider (credentials, HTTP clients, catalogue,
                      model construction, health); set ``name`` and ``config_model``
    ChatModel         implements the abstract LLMModel for chat; implement ``_create`` and
                      ``_stream`` (canonical hooks), or use HTTPChatModel and supply
                      ``build_request`` / ``parse_response`` / a StreamTranslator
    EmbeddingModel    implements LLMModel for embeddings; implement ``_embed``
    register_provider / register_model    put a class in the registry

See docs/architecture/Extending the Intelligence Layer.md. The pre-6.x interface
(``LegacyLLMProvider`` + ``register_provider_class``) is still served, deprecated.
"""

from sajha.ai.llm.adapter import HTTPChatModel, StreamTranslator, WireCall, system_text
from sajha.ai.llm.base import LLMModel, LLMProvider
from sajha.ai.llm.http import get_json, post_json, safe_json_loads
from sajha.ai.llm.legacy import (LegacyLLMProvider, LegacyModelInfo, LLMResponse, get_registered_types,
                                 register_provider_class, unregister_provider_class)
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor,
                                ModelInfo, Needs, estimate_tokens)
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.providers.openai_compat import OpenAIChatModel
from sajha.ai.llm.registry import (load_class, load_entry_points, register_model, register_provider,
                                   registered_providers, unregister_model, unregister_provider)
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import Layered, ModelOverride, ProviderConfig

__all__ = [
    "ChatModel", "EmbeddingModel", "HTTPChatModel", "HealthStatus", "LLMModel", "LLMProvider", "LLMResponse",
    "Layered", "LegacyLLMProvider", "LegacyModelInfo", "ModelCapabilities", "ModelDescriptor", "ModelInfo",
    "ModelOverride", "Needs", "OpenAIChatModel", "ProviderBase", "ProviderConfig", "SecretStore",
    "StreamTranslator", "WireCall", "estimate_tokens", "get_json", "get_registered_types", "load_class",
    "load_entry_points", "post_json", "register_model", "register_provider", "register_provider_class",
    "registered_providers", "safe_json_loads", "system_text", "unregister_model", "unregister_provider",
    "unregister_provider_class",
]
