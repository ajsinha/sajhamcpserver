"""
SAJHA Intelligence Layer — Mistral (La Plateforme).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Mistral's chat API follows the Chat Completions shape (tools, json_schema response_format,
SSE streaming), so it uses the OpenAI pass-through adapter; differences are config defaults:
``tool_choice: "any"`` for a required call, ``max_tokens`` and ``random_seed`` for the seed.
Role "developer" is sent as "system". Embeddings: mistral-embed via /v1/embeddings.
"""

from typing import ClassVar, Dict, List, Literal

from sajha.ai.llm.model import ModelCapabilities
from sajha.ai.llm.providers.openai_compat import (COMPAT_FEATURES, OpenAIChatModel, OpenAIConfig,
                                                  OpenAIEmbeddingModel, OpenAIProvider)
from sajha.ai.llm.registry import register_provider


class MistralConfig(OpenAIConfig):
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_tokens"
    tool_choice_required: str = "any"
    seed_param: str = "random_seed"
    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["MISTRAL_API_KEY"],
                                                  "base_url": ["MISTRAL_BASE_URL"]}


@register_provider
class MistralProvider(OpenAIProvider):
    name = "mistral"
    config_model = MistralConfig
    default_base_url = "https://api.mistral.ai/v1"
    catalog_key = "mistral"
    developer_role = False
    feature_defaults = {**COMPAT_FEATURES, "json_mode": True}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, context_window=128_000)
    chat_model_class = OpenAIChatModel
    embedding_model_class = OpenAIEmbeddingModel

    def auth_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
