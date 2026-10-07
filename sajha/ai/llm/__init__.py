"""
SAJHA Intelligence Layer — SAJHA-owned LLM abstractions.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Everything above the registry (the gateway, the intelligence service, consumers) codes only
against these types; nothing in this package imports a vendor SDK (Bedrock's optional boto3
is imported lazily). See docs/architecture/Intelligence Layer.md.

The canonical model format is OpenAI Chat Completions, typed (canonical.py): requests,
responses, stream chunks and embeddings, with SAJHA-only data in a ``sajha`` field. Models and
the gateway expose an OpenAI-style client surface (``chat_completions_create``,
``chat_completions_stream``, ``achat_completions_create``, ``embeddings_create``); providers
translate at the edge (adapter.py, providers/). The original types (types.py: ChatRequest,
ChatResponse, stream events) remain, converted losslessly by convert.py.
"""

from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    Choice, ChoiceDelta, ChunkAccumulator, ChunkChoice, CompletionUsage, ContentPart,
                                    DeltaToolCall, EmbeddingsRequest, EmbeddingsResponse, FunctionCall,
                                    FunctionDefinition, ImageURL, MessageSajha, ResponseFormat, ResponseSajha,
                                    SajhaRequest, StreamOptions, ToolCall, ToolDefinition)
from sajha.ai.llm.errors import (AuthenticationFailed, BudgetExceeded, ConfigurationError, ContentFiltered,
                                 ContextTooLong, InvalidRequest, LLMError, ModelFailed, NoModelAvailable, PolicyDenied,
                                 ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor,
                                ModelInfo, Needs)
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import (load_class, load_entry_points, register_model, register_provider,
                                   registered_providers)
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import AISettings, ModelOverride, ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, Part, RequestContext,
                                StreamEvent, TextDelta, TextPart, ToolCallDelta, ToolCallPart, ToolResultPart,
                                ToolSpec, Usage, UsageEvent)

__all__ = [
    "AISettings", "AuthenticationFailed", "BudgetExceeded", "ChatCompletion", "ChatCompletionChunk",
    "ChatCompletionRequest", "ChatMessage", "ChatModel", "ChatRequest", "ChatResponse", "Choice", "ChoiceDelta",
    "ChunkAccumulator", "ChunkChoice", "CompletionUsage", "ConfigurationError", "ContentFiltered", "ContentPart",
    "ContextTooLong", "DeltaToolCall", "Done", "EmbeddingModel", "EmbeddingsRequest", "EmbeddingsResponse",
    "FunctionCall", "FunctionDefinition", "HealthStatus", "ImagePart", "ImageURL", "InvalidRequest", "LLMError",
    "LLMProvider", "Message", "MessageSajha", "ModelCapabilities", "ModelDescriptor", "ModelFailed", "ModelInfo",
    "ModelOverride", "Needs", "NoModelAvailable", "Part", "PolicyDenied", "ProviderConfig", "ProviderUnavailable",
    "RateLimited", "RequestContext", "ResponseFormat", "ResponseSajha", "SajhaRequest", "SecretStore",
    "StreamEvent", "StreamOptions", "TextDelta", "TextPart", "ToolCall", "ToolCallDelta", "ToolCallPart",
    "ToolDefinition", "ToolResultPart", "ToolSpec", "UnsupportedFeature", "Usage", "UsageEvent", "load_class",
    "load_entry_points", "register_model", "register_provider", "registered_providers",
]
