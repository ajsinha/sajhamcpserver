"""Together.ai — uses the official 'together' Python SDK."""
import time
import logging
from typing import Dict, Iterator, List
from sajha.ai.providers import LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo

logger = logging.getLogger(__name__)


class TogetherProvider(LLMProvider):
    provider_type = 'together'

    def __init__(self, api_key: str = '', base_url: str = '', **kwargs):
        import together
        if api_key:
            self._client = together.Together(api_key=api_key)
        else:
            self._client = together.Together()  # uses TOGETHER_API_KEY env var

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
            content=content,
            model=response.model or model,
            provider='together',
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            finish_reason=choice.finish_reason if choice else 'stop',
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

    def embed(self, texts, model='togethercomputer/m2-bert-80M-8k-retrieval') -> EmbeddingResponse:
        response = self._client.embeddings.create(input=texts, model=model)
        embeddings = [d.embedding for d in response.data]
        return EmbeddingResponse(
            embeddings=embeddings, model=model, provider='together',
            dimensions=len(embeddings[0]) if embeddings else 0,
        )

    def list_models(self) -> List[ModelInfo]:
        return []  # managed via DB

    def health_check(self) -> bool:
        try:
            r = self._client.chat.completions.create(
                model='meta-llama/Llama-3.3-70B-Instruct-Turbo',
                messages=[{'role': 'user', 'content': 'ping'}], max_tokens=5)
            return bool(r.choices)
        except Exception as e:
            logger.warning(f"Together health check failed: {e}", exc_info=True)
            return False
