"""
SAJHA Intelligence Layer — SAJHA-owned LLM abstractions.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Everything above the registry (the gateway, the intelligence service, consumers) codes only
against these types; nothing in this package imports a vendor SDK (Bedrock's optional boto3
is imported lazily). See docs/architecture/Intelligence Layer.md.
"""

from sajha.ai.llm.errors import (AuthenticationFailed, BudgetExceeded, ConfigurationError, ContentFiltered,
                                 ContextTooLong, InvalidRequest, LLMError, NoModelAvailable, PolicyDenied,
                                 ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.model import (ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor,
                                Needs)
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import (load_class, load_entry_points, register_model, register_provider,
                                   registered_providers)
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import AISettings, ModelOverride, ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, Part, RequestContext,
                                StreamEvent, TextDelta, TextPart, ToolCallDelta, ToolCallPart, ToolResultPart,
                                ToolSpec, Usage, UsageEvent)

__all__ = [
    "AISettings", "AuthenticationFailed", "BudgetExceeded", "ChatModel", "ChatRequest", "ChatResponse",
    "ConfigurationError", "ContentFiltered", "ContextTooLong", "Done", "EmbeddingModel", "HealthStatus",
    "ImagePart", "InvalidRequest", "LLMError", "LLMProvider", "Message", "ModelCapabilities", "ModelDescriptor",
    "ModelOverride", "Needs", "NoModelAvailable", "Part", "PolicyDenied", "ProviderConfig", "ProviderUnavailable",
    "RateLimited", "RequestContext", "SecretStore", "StreamEvent", "TextDelta", "TextPart", "ToolCallDelta",
    "ToolCallPart", "ToolResultPart", "ToolSpec", "UnsupportedFeature", "Usage", "UsageEvent", "load_class",
    "load_entry_points", "register_model", "register_provider", "registered_providers",
]
