"""AWS Bedrock LLM Provider — Claude, Titan, Llama, Mistral via Bedrock."""
import time, json, logging
from typing import Dict, Iterator, List, Optional
from sajha.ai.providers import LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo

logger = logging.getLogger(__name__)

MODELS = [
    ModelInfo(id='anthropic.claude-sonnet-4-20250514-v1:0', name='Claude Sonnet 4 (Bedrock)',
             provider='bedrock', context_window=200000, input_cost_per_1k=0.003,
             output_cost_per_1k=0.015, supports_tools=True, supports_vision=True,
             max_output_tokens=8192, tags=['balanced', 'tools']),
    ModelInfo(id='anthropic.claude-haiku-3-5-20241022-v1:0', name='Claude Haiku 3.5 (Bedrock)',
             provider='bedrock', context_window=200000, input_cost_per_1k=0.0008,
             output_cost_per_1k=0.004, supports_tools=True, max_output_tokens=8192,
             tags=['fast', 'cheap']),
    ModelInfo(id='meta.llama3-1-70b-instruct-v1:0', name='Llama 3.1 70B (Bedrock)',
             provider='bedrock', context_window=128000, input_cost_per_1k=0.00099,
             output_cost_per_1k=0.00099, supports_tools=False, max_output_tokens=4096,
             tags=['open-source']),
    ModelInfo(id='amazon.titan-embed-text-v2:0', name='Titan Embeddings v2',
             provider='bedrock', context_window=8192, tags=['embeddings']),
]

class BedrockProvider(LLMProvider):
    provider_type = 'bedrock'

    def __init__(self, region: str = 'us-east-1', profile: str = '', **kwargs):
        self.region = region
        self.profile = profile
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            session_kwargs = {'region_name': self.region}
            if self.profile:
                session_kwargs['profile_name'] = self.profile
            session = boto3.Session(**session_kwargs)
            self._client = session.client('bedrock-runtime')
        return self._client

    def complete(self, messages, model, temperature=0.7, max_tokens=1024,
                 system='', tools=None, **kwargs) -> LLMResponse:
        start = time.time()
        client = self._get_client()

        if model.startswith('anthropic.'):
            body = {'anthropic_version': 'bedrock-2023-05-31', 'max_tokens': max_tokens,
                    'temperature': temperature, 'messages': messages}
            if system:
                body['system'] = system
            if tools:
                body['tools'] = tools
            resp = client.invoke_model(modelId=model, body=json.dumps(body),
                                        contentType='application/json')
            data = json.loads(resp['body'].read())
            content = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
            usage = data.get('usage', {})
            inp_tok, out_tok = usage.get('input_tokens', 0), usage.get('output_tokens', 0)
        elif model.startswith('meta.'):
            body = {'prompt': self._format_llama(messages, system), 'max_gen_len': max_tokens,
                    'temperature': temperature}
            resp = client.invoke_model(modelId=model, body=json.dumps(body),
                                        contentType='application/json')
            data = json.loads(resp['body'].read())
            content = data.get('generation', '')
            inp_tok, out_tok = data.get('prompt_token_count', 0), data.get('generation_token_count', 0)
        else:
            raise ValueError(f"Unsupported Bedrock model: {model}")

        mi = next((m for m in MODELS if m.id == model), None)
        cost = (inp_tok * mi.input_cost_per_1k + out_tok * mi.output_cost_per_1k) / 1000 if mi else 0
        return LLMResponse(content=content, model=model, provider='bedrock',
                           input_tokens=inp_tok, output_tokens=out_tok,
                           total_tokens=inp_tok + out_tok, finish_reason='stop',
                           latency_ms=int((time.time() - start) * 1000), cost_usd=cost, raw=data)

    def stream(self, messages, model, **kwargs):
        raise NotImplementedError("Bedrock streaming via invoke_model_with_response_stream — TODO")

    def embed(self, texts, model='amazon.titan-embed-text-v2:0') -> EmbeddingResponse:
        client = self._get_client()
        embeddings = []
        total_tokens = 0
        for text in texts:
            resp = client.invoke_model(modelId=model,
                                        body=json.dumps({'inputText': text}),
                                        contentType='application/json')
            data = json.loads(resp['body'].read())
            embeddings.append(data.get('embedding', []))
            total_tokens += data.get('inputTextTokenCount', 0)
        dims = len(embeddings[0]) if embeddings else 0
        return EmbeddingResponse(embeddings=embeddings, model=model, provider='bedrock',
                                 total_tokens=total_tokens, dimensions=dims)

    def _format_llama(self, messages, system=''):
        parts = []
        if system:
            parts.append(f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system}<|eot_id|>")
        for m in messages:
            parts.append(f"<|start_header_id|>{m['role']}<|end_header_id|>\n{m['content']}<|eot_id|>")
        parts.append("<|start_header_id|>assistant<|end_header_id|>")
        return '\n'.join(parts)

    def list_models(self): return MODELS.copy()
    def health_check(self):
        try:
            self._get_client().list_foundation_models(byProvider='anthropic')
            return True
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            return False
    def get_default_model(self): return 'anthropic.claude-sonnet-4-20250514-v1:0'
    def get_default_embedding_model(self): return 'amazon.titan-embed-text-v2:0'
