"""Anthropic (Claude) — uses the official 'anthropic' Python SDK."""
import time
import logging
from typing import Dict, Iterator, List, Optional
from sajha.ai.providers import LLMProvider, LLMResponse, ModelInfo

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    provider_type = 'anthropic'

    def __init__(self, api_key: str = '', base_url: str = '', **kwargs):
        import anthropic
        client_kwargs = {}
        if api_key:
            client_kwargs['api_key'] = api_key
        if base_url:
            client_kwargs['base_url'] = base_url
        self._client = anthropic.Anthropic(**client_kwargs)

    def complete(self, messages, model, temperature=0.7, max_tokens=1024,
                 system='', tools=None, **kwargs) -> LLMResponse:
        start = time.time()
        call_kwargs = {
            'model': model,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'messages': messages,
        }
        if system:
            call_kwargs['system'] = system
        if tools:
            call_kwargs['tools'] = tools

        response = self._client.messages.create(**call_kwargs)

        content = ''.join(
            block.text for block in response.content
            if hasattr(block, 'text')
        )

        return LLMResponse(
            content=content,
            model=response.model,
            provider='anthropic',
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            finish_reason=response.stop_reason or 'stop',
            latency_ms=int((time.time() - start) * 1000),
            cost_usd=0.0,  # calculated by gateway from DB model pricing
            raw=response.model_dump(),
        )

    def stream(self, messages, model, temperature=0.7, max_tokens=1024,
               system='', **kwargs) -> Iterator[str]:
        call_kwargs = {
            'model': model,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'messages': messages,
            'stream': True,
        }
        if system:
            call_kwargs['system'] = system

        with self._client.messages.stream(**{k: v for k, v in call_kwargs.items() if k != 'stream'}) as stream:
            for text in stream.text_stream:
                yield text

    def list_models(self) -> List[ModelInfo]:
        # SDK doesn't have a list-models endpoint; return empty
        # Models are managed via the llm_models DB table
        return []

    def health_check(self) -> bool:
        try:
            r = self._client.messages.create(
                model='claude-haiku-3-5-20241022',
                max_tokens=5,
                messages=[{'role': 'user', 'content': 'ping'}],
            )
            return bool(r.content)
        except Exception as e:
            logger.warning(f"Anthropic health check failed: {e}", exc_info=True)
            return False
