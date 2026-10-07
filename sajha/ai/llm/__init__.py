"""
SAJHA Intelligence Layer — the public LLM API.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every LLM SAJHA uses is reached through this package, behind OpenAI-style signatures. All
provider and model specifics live inside it (one module per provider under ``providers/``);
nothing outside it imports a vendor SDK, a provider module or a private module, or constructs a
provider or model (tests/test_llm_boundary.py enforces this).

What application code may use (and nothing else):

* ``llm_factory()`` — the process-wide LLMFactory (None before the intelligence layer starts);
  ``init_llm_factory`` / ``build_llm_factory`` / ``set_llm_factory`` create or install one.
* ``LLMFactory.model(name, context=ctx)`` — a ``GovernedModel`` for an alias (``default``,
  ``fast``, ``reasoning``, ``embedding``, ...) or ``provider/model``: an ``LLMModel`` proxy that
  applies role policy, budgets, the cache, retries, breakers, fallback across the alias's
  candidates, audit, usage/cost and tracing, then delegates to the provider's model.
  ``LLMFactory.provider(name)`` is for admin and catalog pages.
* ``LLMModel`` and ``LLMProvider`` — the abstract classes every provider module implements:
  ``chat_completions_create``, ``chat_completions_stream``, ``achat_completions_create``,
  ``achat_completions_stream``, ``embeddings_create``, ``aembeddings_create``, ``info()``;
  ``models()``, ``model()``, ``health()`` on a provider.
* The canonical OpenAI Chat Completions / Embeddings types (``ChatMessage``,
  ``ChatCompletionRequest``, ``ChatCompletion``, ``ChatCompletionChunk``, ``ToolDefinition``,
  ``ToolCall``, ``EmbeddingsRequest``, ``EmbeddingsResponse``, ...) with SAJHA-only data in a
  ``sajha`` field (``SajhaRequest`` / ``ResponseSajha``), and ``RequestContext`` (the caller's
  identity) and ``Usage``.
* The errors (``LLMError`` and its subclasses).
* Catalog value types: ``ModelInfo``, ``ModelCapabilities``, ``HealthStatus``.

Public submodules: ``canonical`` (the types and their helpers), ``errors``, ``settings``
(ai.* configuration sections) and ``secrets``. Code that adds a provider or a model uses
``sajha.ai.llm.spi``. Everything else (adapter, http, convert, legacy, registry, governed,
providers/, mock*) is internal. See docs/architecture/Intelligence Layer.md.
"""

from sajha.ai.llm.base import LLMModel, LLMProvider
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    Choice, ChoiceDelta, ChunkAccumulator, ChunkChoice, CompletionUsage, ContentPart,
                                    DeltaToolCall, EmbeddingsRequest, EmbeddingsResponse, FunctionCall,
                                    FunctionDefinition, ImageURL, MessageSajha, ResponseFormat, ResponseSajha,
                                    SajhaRequest, StreamOptions, ToolCall, ToolDefinition)
from sajha.ai.llm.errors import (AuthenticationFailed, BudgetExceeded, ConfigurationError, ContentFiltered,
                                 ContextTooLong, InvalidRequest, LLMError, ModelFailed, NoModelAvailable, PolicyDenied,
                                 ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.factory import LLMFactory, build_llm_factory, init_llm_factory, llm_factory, set_llm_factory
from sajha.ai.llm.governed import GovernedModel
from sajha.ai.llm.model import HealthStatus, ModelCapabilities, ModelInfo
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.types import RequestContext, Usage

__all__ = [
    # factory and proxy
    "GovernedModel", "LLMFactory", "build_llm_factory", "init_llm_factory", "llm_factory", "set_llm_factory",
    # abstract API
    "LLMModel", "LLMProvider",
    # canonical types
    "ChatCompletion", "ChatCompletionChunk", "ChatCompletionRequest", "ChatMessage", "Choice", "ChoiceDelta",
    "ChunkAccumulator", "ChunkChoice", "CompletionUsage", "ContentPart", "DeltaToolCall", "EmbeddingsRequest",
    "EmbeddingsResponse", "FunctionCall", "FunctionDefinition", "ImageURL", "MessageSajha", "RequestContext",
    "ResponseFormat", "ResponseSajha", "SajhaRequest", "StreamOptions", "ToolCall", "ToolDefinition", "Usage",
    # catalog values
    "HealthStatus", "ModelCapabilities", "ModelInfo", "SecretStore",
    # errors
    "AuthenticationFailed", "BudgetExceeded", "ConfigurationError", "ContentFiltered", "ContextTooLong",
    "InvalidRequest", "LLMError", "ModelFailed", "NoModelAvailable", "PolicyDenied", "ProviderUnavailable",
    "RateLimited", "UnsupportedFeature",
]
