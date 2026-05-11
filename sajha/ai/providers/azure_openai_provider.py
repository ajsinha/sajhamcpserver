"""Azure OpenAI — uses the official 'openai' SDK with Azure configuration."""
import time
import logging
from typing import Dict, Iterator, List
from sajha.ai.providers import LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(LLMProvider):
    provider_type = 'azure_openai'

    def __init__(self, api_key: str = '', base_url: str = '',
                 api_version: str = '2024-10-21', **kwargs):
        import openai
        self._client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=base_url,
            api_version=api_version,
        )

    def complete(self, messages, model, temperature=0.7, max_tokens=1024,
                 system='', tools=None, **kwargs) -> LLMResponse:
        start = time.time()
        msgs = []
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs.extend(messages)

        response = self._client.chat.completions.create(
            model=model, messages=msgs, temperature=temperature, max_tokens=max_tokens,
        )

        choice = response.choices[0] if response.choices else None
        content = choice.message.content or '' if choice else ''

        return LLMResponse(
            content=content, model=response.model or model,
            provider='azure_openai',
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            latency_ms=int((time.time() - start) * 1000),
        )

    def stream(self, messages, model, temperature=0.7, max_tokens=1024,
               system='', **kwargs) -> Iterator[str]:
        msgs = [{'role': 'system', 'content': system}] + list(messages) if system else list(messages)
        stream = self._client.chat.completions.create(
            model=model, messages=msgs, temperature=temperature,
            max_tokens=max_tokens, stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def embed(self, texts, model='text-embedding-3-small') -> EmbeddingResponse:
        response = self._client.embeddings.create(input=texts, model=model)
        embeddings = [d.embedding for d in response.data]
        return EmbeddingResponse(
            embeddings=embeddings, model=model, provider='azure_openai',
            total_tokens=response.usage.total_tokens if response.usage else 0,
            dimensions=len(embeddings[0]) if embeddings else 0,
        )

    def list_models(self) -> List[ModelInfo]:
        return []  # Azure deployments are custom

    def health_check(self) -> bool:
        try:
            r = self._client.chat.completions.create(
                model='gpt-4o', messages=[{'role': 'user', 'content': 'ping'}], max_tokens=5)
            return bool(r.choices)
        except Exception as e:
            logger.warning(f"Azure OpenAI health check failed: {e}")
            return False
