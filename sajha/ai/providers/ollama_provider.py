"""Ollama — uses the official 'ollama' Python SDK. Local models, air-gapped."""
import time
import logging
from typing import Dict, Iterator, List
from sajha.ai.providers import LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    provider_type = 'ollama'

    def __init__(self, base_url: str = 'http://localhost:11434', **kwargs):
        import ollama
        self._client = ollama.Client(host=base_url)
        self._base_url = base_url

    def complete(self, messages, model, temperature=0.7, max_tokens=1024,
                 system='', tools=None, **kwargs) -> LLMResponse:
        start = time.time()
        msgs = []
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs.extend(messages)

        response = self._client.chat(
            model=model, messages=msgs, stream=False,
            options={'temperature': temperature, 'num_predict': max_tokens},
        )

        content = response.get('message', {}).get('content', '')
        inp_tok = response.get('prompt_eval_count', 0)
        out_tok = response.get('eval_count', 0)

        return LLMResponse(
            content=content, model=model, provider='ollama',
            input_tokens=inp_tok, output_tokens=out_tok,
            total_tokens=inp_tok + out_tok, finish_reason='stop',
            latency_ms=int((time.time() - start) * 1000),
            cost_usd=0.0,  # local models are free
            raw=response,
        )

    def stream(self, messages, model, temperature=0.7, max_tokens=1024,
               system='', **kwargs) -> Iterator[str]:
        msgs = []
        if system:
            msgs.append({'role': 'system', 'content': system})
        msgs.extend(messages)

        stream = self._client.chat(
            model=model, messages=msgs, stream=True,
            options={'temperature': temperature, 'num_predict': max_tokens},
        )
        for chunk in stream:
            content = chunk.get('message', {}).get('content', '')
            if content:
                yield content

    def embed(self, texts, model='nomic-embed-text') -> EmbeddingResponse:
        embeddings = []
        for text in texts:
            response = self._client.embeddings(model=model, prompt=text)
            embeddings.append(response.get('embedding', []))
        return EmbeddingResponse(
            embeddings=embeddings, model=model, provider='ollama',
            dimensions=len(embeddings[0]) if embeddings else 0,
        )

    def list_models(self) -> List[ModelInfo]:
        """List locally available Ollama models."""
        try:
            response = self._client.list()
            return [
                ModelInfo(
                    id=m.get('name', ''), name=m.get('name', ''),
                    provider='ollama', tags=['local'],
                )
                for m in response.get('models', [])
            ]
        except Exception:
            return []

    def health_check(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False
