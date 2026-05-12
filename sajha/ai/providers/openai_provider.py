"""OpenAI (GPT + Embeddings) — uses the official 'openai' Python SDK."""
import time
import logging
from typing import Dict, Iterator, List, Optional
from sajha.ai.providers import LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    provider_type = 'openai'

    def __init__(self, api_key: str = '', base_url: str = '', **kwargs):
        import openai
        client_kwargs = {}
        if api_key:
            client_kwargs['api_key'] = api_key
        if base_url:
            client_kwargs['base_url'] = base_url
        self._client = openai.OpenAI(**client_kwargs)

    def complete(self, messages, model, temperature=0.7, max_tokens=1024,
                 system='', tools=None, **kwargs) -> LLMResponse:
        start = time.time()
        msgs = []
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs.extend(messages)

        call_kwargs = {
            'model': model,
            'messages': msgs,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if tools:
            call_kwargs['tools'] = tools

        response = self._client.chat.completions.create(**call_kwargs)

        choice = response.choices[0] if response.choices else None
        content = choice.message.content or '' if choice else ''

        return LLMResponse(
            content=content,
            model=response.model,
            provider='openai',
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            finish_reason=choice.finish_reason if choice else 'stop',
            latency_ms=int((time.time() - start) * 1000),
            raw=response.model_dump(),
        )

    def stream(self, messages, model, temperature=0.7, max_tokens=1024,
               system='', **kwargs) -> Iterator[str]:
        msgs = []
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs.extend(messages)

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
        dims = len(embeddings[0]) if embeddings else 0
        return EmbeddingResponse(
            embeddings=embeddings, model=model, provider='openai',
            total_tokens=response.usage.total_tokens if response.usage else 0,
            dimensions=dims,
        )

    def list_models(self) -> List[ModelInfo]:
        return []  # managed via DB

    def health_check(self) -> bool:
        try:
            r = self._client.chat.completions.create(
                model='gpt-4o-mini', messages=[{'role': 'user', 'content': 'ping'}], max_tokens=5)
            return bool(r.choices)
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {e}", exc_info=True)
            return False

    def get_default_embedding_model(self) -> str:
        return 'text-embedding-3-small'
