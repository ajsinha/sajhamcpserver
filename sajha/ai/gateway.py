"""
SAJHA MCP Server — LLM Gateway
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Central intelligence layer. Routes requests to the right provider/model
based on system defaults, user preferences, and task requirements.

Usage:
    from sajha.ai.gateway import get_gateway
    gw = get_gateway()
    response = gw.complete("Summarize AAPL financials", user_id="analyst_01")
"""

import json
import time
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sajha.ai.providers import (
    LLMProvider, LLMResponse, EmbeddingResponse, ModelInfo,
    ProviderType, create_provider,
)

logger = logging.getLogger(__name__)


@dataclass
class GatewayConfig:
    """Gateway configuration — loaded from application.yml ai: section."""
    default_provider: str = 'anthropic'
    default_model: str = 'claude-sonnet-4-20250514'
    default_embedding_provider: str = 'openai'
    default_embedding_model: str = 'text-embedding-3-small'
    max_tokens_default: int = 1024
    temperature_default: float = 0.7
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    budget_tracking_enabled: bool = True


class ResponseCache:
    """In-memory LRU cache for LLM responses."""

    def __init__(self, max_size: int = 500, ttl: int = 3600):
        self._cache: Dict[str, tuple] = {}  # key → (response, timestamp)
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _key(self, messages, model, system='', temperature=0.7):
        raw = json.dumps({'m': messages, 'model': model, 's': system, 't': temperature}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages, model, system='', temperature=0.7) -> Optional[LLMResponse]:
        k = self._key(messages, model, system, temperature)
        with self._lock:
            if k in self._cache:
                resp, ts = self._cache[k]
                if time.time() - ts < self._ttl:
                    self._hits += 1
                    return resp
                del self._cache[k]
            self._misses += 1
        return None

    def put(self, messages, model, response: LLMResponse, system='', temperature=0.7):
        k = self._key(messages, model, system, temperature)
        with self._lock:
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache, key=lambda x: self._cache[x][1])
                del self._cache[oldest]
            self._cache[k] = (response, time.time())

    def stats(self) -> Dict:
        return {'size': len(self._cache), 'hits': self._hits, 'misses': self._misses,
                'hit_rate': f"{self._hits / max(self._hits + self._misses, 1) * 100:.1f}%"}


class TokenTracker:
    """Track token usage per user/provider/model for budgeting."""

    def __init__(self):
        self._usage: Dict[str, Dict] = {}  # user_id → {provider → {model → {input, output, cost, count}}}
        self._lock = threading.Lock()

    def record(self, user_id: str, response: LLMResponse):
        with self._lock:
            if user_id not in self._usage:
                self._usage[user_id] = {}
            u = self._usage[user_id]
            if response.provider not in u:
                u[response.provider] = {}
            p = u[response.provider]
            if response.model not in p:
                p[response.model] = {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0, 'count': 0}
            m = p[response.model]
            m['input_tokens'] += response.input_tokens
            m['output_tokens'] += response.output_tokens
            m['cost_usd'] += response.cost_usd
            m['count'] += 1

    def get_usage(self, user_id: str = '') -> Dict:
        with self._lock:
            if user_id:
                return self._usage.get(user_id, {})
            return dict(self._usage)

    def get_total_cost(self, user_id: str = '') -> float:
        usage = self.get_usage(user_id)
        total = 0.0
        for provider in usage.values():
            for model in provider.values():
                total += model.get('cost_usd', 0.0)
        return total


class LLMGateway:
    """
    Central gateway for all LLM interactions in SAJHA.

    Features:
    - Multi-provider routing (Anthropic, OpenAI, Bedrock, Together, Ollama, Azure)
    - User-level model overrides (stored in user_ai_preferences DB table)
    - Response caching (same prompt+model → cached response)
    - Token budget tracking per user
    - System-wide defaults configurable via application.yml
    """

    def __init__(self, config: GatewayConfig = None):
        self.config = config or GatewayConfig()
        self._providers: Dict[str, LLMProvider] = {}
        self._user_preferences: Dict[str, Dict] = {}  # user_id → {provider, model}
        self._cache = ResponseCache(ttl=self.config.cache_ttl_seconds)
        self._tracker = TokenTracker()
        logger.info(f"LLMGateway initialized: default={self.config.default_provider}/{self.config.default_model}")

    def register_provider(self, provider_type: str, **config) -> LLMProvider:
        """Register and configure an LLM provider."""
        provider = create_provider(provider_type, **config)
        self._providers[provider_type] = provider
        logger.info(f"Provider registered: {provider_type}")
        return provider

    def get_provider(self, provider_type: str) -> Optional[LLMProvider]:
        return self._providers.get(provider_type)

    def set_user_preference(self, user_id: str, provider: str = '', model: str = '',
                            temperature: float = 0.0, max_tokens: int = 0):
        """Set user-level LLM preferences (overrides system defaults)."""
        pref = {}
        if provider: pref['provider'] = provider
        if model: pref['model'] = model
        if temperature > 0: pref['temperature'] = temperature
        if max_tokens > 0: pref['max_tokens'] = max_tokens
        self._user_preferences[user_id] = pref
        logger.info(f"User preference set: {user_id} → {pref}")

    def get_user_preference(self, user_id: str) -> Dict:
        return self._user_preferences.get(user_id, {})

    def clear_user_preference(self, user_id: str):
        self._user_preferences.pop(user_id, None)

    def _resolve_provider_model(self, user_id: str = '', provider: str = '',
                                 model: str = '') -> tuple:
        """Resolve provider and model: explicit → user pref → system default."""
        pref = self._user_preferences.get(user_id, {})
        p = provider or pref.get('provider', '') or self.config.default_provider
        m = model or pref.get('model', '') or self.config.default_model
        return p, m

    def complete(
        self,
        prompt: str,
        user_id: str = '',
        provider: str = '',
        model: str = '',
        system: str = '',
        temperature: float = 0.0,
        max_tokens: int = 0,
        tools: Optional[List[Dict]] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> LLMResponse:
        """
        Send a completion request through the gateway.

        Resolution order for provider/model:
        1. Explicit parameters (provider=, model=)
        2. User preferences (set via set_user_preference)
        3. System defaults (from GatewayConfig)
        """
        p_type, m = self._resolve_provider_model(user_id, provider, model)
        pref = self._user_preferences.get(user_id, {})
        temp = temperature or pref.get('temperature', 0) or self.config.temperature_default
        max_tok = max_tokens or pref.get('max_tokens', 0) or self.config.max_tokens_default

        messages = [{'role': 'user', 'content': prompt}]

        # Cache check
        if use_cache and self.config.cache_enabled and not tools:
            cached = self._cache.get(messages, m, system, temp)
            if cached:
                return cached

        # Get provider
        prov = self._providers.get(p_type)
        if not prov:
            raise ValueError(f"Provider '{p_type}' not registered. Available: {list(self._providers.keys())}")

        # Execute
        response = prov.complete(messages, m, temperature=temp, max_tokens=max_tok,
                                  system=system, tools=tools, **kwargs)

        # Track tokens
        if self.config.budget_tracking_enabled and user_id:
            self._tracker.record(user_id, response)

        # Cache response
        if use_cache and self.config.cache_enabled and not tools:
            self._cache.put(messages, m, response, system, temp)

        return response

    def complete_messages(
        self,
        messages: List[Dict[str, str]],
        user_id: str = '',
        provider: str = '',
        model: str = '',
        system: str = '',
        temperature: float = 0.0,
        max_tokens: int = 0,
        **kwargs,
    ) -> LLMResponse:
        """Multi-turn completion with full message history."""
        p_type, m = self._resolve_provider_model(user_id, provider, model)
        pref = self._user_preferences.get(user_id, {})
        temp = temperature or pref.get('temperature', 0) or self.config.temperature_default
        max_tok = max_tokens or pref.get('max_tokens', 0) or self.config.max_tokens_default

        prov = self._providers.get(p_type)
        if not prov:
            raise ValueError(f"Provider '{p_type}' not registered")

        response = prov.complete(messages, m, temperature=temp, max_tokens=max_tok,
                                  system=system, **kwargs)
        if self.config.budget_tracking_enabled and user_id:
            self._tracker.record(user_id, response)
        return response

    def embed(self, texts: List[str], provider: str = '', model: str = '') -> EmbeddingResponse:
        """Generate embeddings via the configured embedding provider."""
        p_type = provider or self.config.default_embedding_provider
        m = model or self.config.default_embedding_model
        prov = self._providers.get(p_type)
        if not prov:
            raise ValueError(f"Embedding provider '{p_type}' not registered")
        return prov.embed(texts, model=m)

    def list_all_models(self) -> List[ModelInfo]:
        """List models across all registered providers."""
        models = []
        for p_type, prov in self._providers.items():
            try:
                models.extend(prov.list_models())
            except Exception as e:
                logger.warning(f"Failed to list models for {p_type}: {e}", exc_info=True)
        return models

    def health_check_all(self) -> Dict[str, bool]:
        """Check health of all registered providers."""
        results = {}
        for p_type, prov in self._providers.items():
            try:
                results[p_type] = prov.health_check()
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                results[p_type] = False
        return results

    def get_stats(self) -> Dict:
        return {
            'providers': list(self._providers.keys()),
            'default_provider': self.config.default_provider,
            'default_model': self.config.default_model,
            'cache': self._cache.stats(),
            'user_preferences': len(self._user_preferences),
            'total_models': len(self.list_all_models()),
        }

    def get_token_usage(self, user_id: str = '') -> Dict:
        return self._tracker.get_usage(user_id)

    def get_total_cost(self, user_id: str = '') -> float:
        return self._tracker.get_total_cost(user_id)


# ── Singleton ────────────────────────────────────────────────

_gateway: Optional[LLMGateway] = None


def init_gateway(config: Dict[str, Any], db_session=None) -> LLMGateway:
    """Initialize the LLM gateway from database tables.

    Reads llm_providers and llm_models tables to configure providers.
    Falls back to env vars if no DB session provided.
    """
    global _gateway
    import os

    gc = GatewayConfig(
        default_provider=config.get('ai.default_provider', os.environ.get('SAJHA_AI_DEFAULT_PROVIDER', 'anthropic')),
        default_model=config.get('ai.default_model', os.environ.get('SAJHA_AI_DEFAULT_MODEL', 'claude-sonnet-4-20250514')),
        default_embedding_provider=config.get('ai.embedding_provider', 'openai'),
        default_embedding_model=config.get('ai.embedding_model', 'text-embedding-3-small'),
        cache_enabled=config.get('ai.cache.enabled', True),
        cache_ttl_seconds=int(config.get('ai.cache.ttl_seconds', 3600) or 3600),
    )
    _gateway = LLMGateway(gc)

    # ── Load providers from database ─────────────────────────
    if db_session:
        try:
            from sajha.db.dao import LLMProviderDAO, LLMModelDAO
            provider_dao = LLMProviderDAO(db_session)
            model_dao = LLMModelDAO(db_session)

            # Find default provider from DB
            default_prov = provider_dao.get_default()
            if default_prov:
                gc.default_provider = default_prov.provider_type

            # Find default model from DB
            if default_prov:
                default_model = model_dao.get_default_for_provider(default_prov.provider_type)
                if default_model:
                    gc.default_model = default_model.model_id

            # Find default embedding model
            emb_models = model_dao.get_embedding_models()
            if emb_models:
                gc.default_embedding_model = emb_models[0].model_id
                gc.default_embedding_provider = emb_models[0].provider_type

            # Register each enabled provider from DB
            for prov_rec in provider_dao.get_all_enabled():
                try:
                    prov_config = {
                        'api_key': prov_rec.api_key or os.environ.get(f'SAJHA_{prov_rec.provider_type.upper()}_API_KEY',
                                   os.environ.get(f'{prov_rec.provider_type.upper()}_API_KEY', '')),
                    }
                    if prov_rec.base_url:
                        prov_config['base_url'] = prov_rec.base_url
                    if prov_rec.region:
                        prov_config['region'] = prov_rec.region
                    if prov_rec.extra_config:
                        import json
                        prov_config.update(json.loads(prov_rec.extra_config))

                    # Only register if there's a key or it's a keyless provider
                    if prov_config.get('api_key') or prov_rec.provider_type in ('bedrock', 'ollama'):
                        _gateway.register_provider(prov_rec.provider_type, **prov_config)
                except Exception as e:
                    logger.warning(f"Failed to register DB provider {prov_rec.provider_type}: {e}", exc_info=True)

            logger.info(f"Gateway loaded {len(_gateway._providers)} providers from database")
        except Exception as e:
            logger.warning(f"Failed to load providers from DB, falling back to env: {e}", exc_info=True)
            _init_gateway_from_env(config, _gateway)
    else:
        _init_gateway_from_env(config, _gateway)

    return _gateway


def _init_gateway_from_env(config: Dict, gateway: LLMGateway):
    """Fallback: register providers from environment variables."""
    import os
    providers_config = {
        'anthropic': {'api_key': config.get('ai.anthropic.api_key', os.environ.get('ANTHROPIC_API_KEY', ''))},
        'openai': {'api_key': config.get('ai.openai.api_key', os.environ.get('OPENAI_API_KEY', ''))},
        'bedrock': {'region': config.get('ai.bedrock.region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))},
        'together': {'api_key': config.get('ai.together.api_key', os.environ.get('TOGETHER_API_KEY', ''))},
        'ollama': {'base_url': config.get('ai.ollama.base_url', os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434'))},
    }
    for p_type, p_config in providers_config.items():
        if p_config.get('api_key') or p_type in ('bedrock', 'ollama'):
            try:
                gateway.register_provider(p_type, **p_config)
            except Exception as e:
                logger.warning(f"Failed to register env provider {p_type}: {e}", exc_info=True)


def get_gateway() -> Optional[LLMGateway]:
    return _gateway
