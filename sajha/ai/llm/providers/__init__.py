"""
SAJHA Intelligence Layer — native providers (plain httpx; boto3 only for Bedrock).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Importing this package registers every built-in provider with the registry.
"""

from sajha.ai.llm.providers.anthropic import AnthropicProvider            # noqa: F401
from sajha.ai.llm.providers.openai_compat import (                        # noqa: F401
    AzureOpenAIProvider, OpenAICompatibleProvider, OpenAIProvider)
from sajha.ai.llm.providers.gemini import GeminiProvider                  # noqa: F401
from sajha.ai.llm.providers.mistral import MistralProvider                # noqa: F401
from sajha.ai.llm.providers.cohere import CohereProvider                  # noqa: F401
from sajha.ai.llm.providers.ollama import OllamaProvider                  # noqa: F401
from sajha.ai.llm.providers.bedrock import BedrockProvider                # noqa: F401
