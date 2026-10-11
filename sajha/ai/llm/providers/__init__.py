"""
SAJHA Intelligence Layer — native providers (plain httpx; boto3 only for Bedrock) and the offline mock.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Importing this package registers every built-in provider with the registry; the factory then builds
them from configuration (``ai.providers``), the mock included. Code never constructs a provider itself.

Import safety: a vendor library (boto3, google-auth, PyJWT) is imported only when its provider is
used, so a missing one leaves that provider down with a clear error. Each provider module is loaded
on its own as well, so one that fails to import is logged and skipped and the rest still register;
SAJHA never fails to start because of a provider. The mock is built in and needs nothing, so it is
loaded unguarded: without it there would be no offline default.
"""

import importlib
import logging

logger = logging.getLogger(__name__)

from sajha.ai.llm.providers.mock import MockProvider                      # noqa: F401,E402

# (module, provider classes it registers), in registration order
BUILTIN_MODULES = (
    ("anthropic", "AnthropicProvider"),
    ("openai_compat", "OpenAIProvider, AzureOpenAIProvider, OpenAICompatibleProvider and its presets"),
    ("gemini", "GeminiProvider"),
    ("mistral", "MistralProvider"),
    ("cohere", "CohereProvider"),
    ("ollama", "OllamaProvider"),
    ("bedrock", "BedrockProvider"),
)

FAILED: dict = {}          # module -> error, for providers that could not be imported


def _load(module: str) -> None:
    try:
        importlib.import_module(f"{__name__}.{module}")
    except Exception as e:                       # a broken or partly installed provider never stops startup
        FAILED[module] = f"{e.__class__.__name__}: {e}"
        logger.error(f"LLM provider module {module!r} could not be imported and is unavailable: {e}")


for _module, _ in BUILTIN_MODULES:
    _load(_module)
