"""
SAJHA Intelligence Layer — the LLM factory.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The one way application code reaches a model:

    from sajha.ai.llm import ChatMessage, SajhaRequest, llm_factory
    f = llm_factory()                                   # the process-wide factory (None before startup)
    m = f.model("reasoning", context=ctx)               # a GovernedModel (an LLMModel proxy)
    c = m.chat_completions_create(messages=[ChatMessage.user("Hello")])
    c.text, c.sajha.provider, c.sajha.cost_usd
    v = f.model("embedding").embeddings_create(input=["a", "b"]).vectors

The factory builds every provider from application.yml (``ai.providers``, ``ai.aliases``) and the
registry (built-ins, ``package.module:Class``, entry points in ``sajha.llm_providers``), resolves
secrets (env, ``api_key_ref``, the database), and keeps one instance per provider. ``model()``
returns a GovernedModel proxy that applies policy, budgets, cache, retries, breakers, fallback,
audit, usage and tracing (governed.py) and then delegates to the provider's own model object,
which translates to the vendor wire format (adapter.py, providers/). ``provider(name)`` returns a
provider for admin and catalog pages; calling code never constructs providers or models itself.

The factory is also an OpenAI-style client: ``f.chat_completions_create(model="fast", ...)`` is
``f.model("fast").chat_completions_create(...)``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

from sajha.ai.llm import registry
from sajha.ai.llm.base import LLMProvider
from sajha.ai.llm.canonical import ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, EmbeddingsRequest, \
    EmbeddingsResponse
from sajha.ai.llm.errors import ConfigurationError, LLMError
from sajha.ai.llm.governed import GovernedModel, Governor
from sajha.ai.llm.secrets import SecretStore, db_secret_lookup
from sajha.ai.llm.settings import AISettings, ModelOverride, load_ai_yaml

logger = logging.getLogger(__name__)


class LLMFactory(Governor):
    """Providers built from configuration, and governed models handed out by name."""

    def model(self, name: str = "default", *, kind: str = "", context: Any = None,
              needs: Any = None) -> GovernedModel:
        """A GovernedModel for an alias (``default``, ``fast``, ``reasoning``, ``embedding``, ...) or
        ``provider/model``. ``kind`` is ``chat`` or ``embedding`` (default: ``embedding`` for the
        ``embedding`` alias, else ``chat``); it only changes what ``info()`` describes."""
        name = name or "default"
        if not kind:
            kind = "embedding" if name == "embedding" else "chat"
        return GovernedModel(self, name, kind=kind, context=context, needs=needs)

    def provider(self, name: str) -> Optional[LLMProvider]:
        """A provider instance by name, for admin and catalog uses (None when unknown)."""
        return self.providers.get(name)

    def provider_names(self) -> List[str]:
        return list(self.providers)

    @staticmethod
    def provider_types() -> Dict[str, str]:
        """Every registered provider type -> ``module:Class`` (built-ins, configured classes, entry
        points), whether or not a factory is running."""
        return {n: f"{c.__module__}:{c.__name__}" for n, c in registry.registered_providers().items()}

    @staticmethod
    def legacy_provider_types() -> Dict[str, str]:
        """Pre-6.x provider types registered with register_provider_class -> class name."""
        from sajha.ai.llm.legacy import get_registered_types
        return get_registered_types()

    # ── the OpenAI-style client surface (model= picks the target) ──
    def chat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        req = ChatCompletionRequest.coerce(request, **fields)
        return self.model(req.model or "default").chat_completions_create(req)

    async def achat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        req = ChatCompletionRequest.coerce(request, **fields)
        return await self.model(req.model or "default").achat_completions_create(req)

    def chat_completions_stream(self, request: Any = None, /, **fields) -> Iterator[ChatCompletionChunk]:
        req = ChatCompletionRequest.coerce(request, **fields)
        return self.model(req.model or "default").chat_completions_stream(req)

    def achat_completions_stream(self, request: Any = None, /, **fields) -> AsyncIterator[ChatCompletionChunk]:
        req = ChatCompletionRequest.coerce(request, **fields)
        return self.model(req.model or "default").achat_completions_stream(req)

    def embeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        req = EmbeddingsRequest.coerce(request, **fields)
        return self.model(req.model or "embedding", kind="embedding").embeddings_create(req)

    async def aembeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        req = EmbeddingsRequest.coerce(request, **fields)
        return await self.model(req.model or "embedding", kind="embedding").aembeddings_create(req)


# ── construction ────────────────────────────────────────────────

def _db_provider_rows(db_session) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[ModelOverride]]]:
    rows, models = {}, {}
    if db_session is None:
        return rows, models
    try:
        from sajha.db.dao import LLMModelDAO, LLMProviderDAO
        for rec in LLMProviderDAO(db_session).get_all():
            d = {"api_key": rec.api_key, "base_url": rec.base_url, "region": rec.region}
            if rec.extra_config:
                try:
                    d.update(json.loads(rec.extra_config))
                except Exception:
                    pass
            rows[rec.provider_type] = {k: v for k, v in d.items() if v not in (None, "")}
        for m in LLMModelDAO(db_session).get_all():
            models.setdefault(m.provider_type, []).append(ModelOverride(
                id=m.model_id, kind="embedding" if m.supports_embeddings else "chat",
                display_name=m.display_name or "", enabled=bool(m.enabled),
                tools=bool(m.supports_tools), vision=bool(m.supports_vision),
                streaming=bool(m.supports_streaming), context_window=m.context_window or None,
                max_output_tokens=m.max_output_tokens or None,
                input_cost_per_mtok=(m.input_cost_per_1k or 0) * 1000,
                output_cost_per_mtok=(m.output_cost_per_1k or 0) * 1000,
                tags=[t.strip() for t in (m.tags or "").split(",") if t.strip()] or None))
    except Exception as e:
        logger.warning(f"ai: could not read llm_providers/llm_models: {e}")
    return rows, models


_LEGACY_KEYS = {"api_key": "api_key", "base_url": "base_url", "endpoint": "base_url", "region": "region"}


def build_llm_factory(raw: Optional[Dict[str, Any]] = None, *, db_session=None, environ: Optional[Dict[str, str]] = None,
                      transports: Optional[Dict[str, Any]] = None, secrets: Optional[SecretStore] = None,
                      db_lookup=None) -> "LLMFactory":
    """Build a factory from the ai: section (raw YAML dict; application.yml when None), the
    environment, and optionally the llm_providers / llm_models tables. The registry supplies the
    classes: built-ins, ``ai.providers[].class: package.module:Class``, and entry points."""
    raw = load_ai_yaml() if raw is None else raw
    settings = AISettings(raw, environ)
    registry.ensure_builtins()
    if settings.gateway.load_entry_points:
        registry.load_entry_points()
    secrets = secrets or SecretStore(db_lookup=db_lookup or (db_secret_lookup if db_session is not None else None),
                                     environ=environ)
    db_rows, db_models = (_db_provider_rows(db_session) if settings.gateway.use_db_providers else ({}, {}))
    transports = transports or {}
    errors: List[str] = []

    entries: Dict[str, Dict[str, Any]] = {n: {"cls": c, "config": {}} for n, c in registry.registered_providers().items()}
    for item in raw.get("providers") or []:
        if not isinstance(item, dict) or not item.get("name"):
            errors.append(f"ai.providers entry without a name: {item!r}")
            continue
        name = item["name"]
        try:
            if item.get("class"):
                cls = registry.load_class(item["class"])
            elif item.get("type"):
                cls = registry.provider_class(item["type"])
            else:
                cls = registry.provider_class(name)
            if cls is None:
                raise ConfigurationError(f"unknown provider '{item.get('type') or name}' "
                                         f"(registered: {sorted(registry.registered_providers())})")
        except LLMError as e:
            errors.append(f"ai.providers[{name}]: {e}")
            logger.error(f"ai.providers[{name}]: {e}")
            continue
        cfg = dict(item.get("config") or {})
        for k in ("enabled",):
            if k in item and k not in cfg:
                cfg[k] = item[k]
        entries[name] = {"cls": cls, "config": cfg}
    # legacy pre-6.x keys (ai.<vendor>.api_key etc.) as config values
    for name, ent in entries.items():
        legacy = raw.get(name)
        if isinstance(legacy, dict):
            for k, target in _LEGACY_KEYS.items():
                if legacy.get(k) and target in ent["cls"].config_model.model_fields:
                    ent["config"].setdefault(target, legacy[k])
    # providers registered with the old register_provider_class()
    try:
        from sajha.ai.llm.legacy import LegacyProviderAdapter, get_registered_types
        for t in get_registered_types():
            if t not in entries:
                entries[t] = {"cls": LegacyProviderAdapter, "config": {"legacy_type": t}}
    except Exception as e:
        logger.debug(f"legacy provider scan failed: {e}")

    providers: Dict[str, LLMProvider] = {}
    for name, ent in entries.items():
        cls = ent["cls"]
        fields = cls.config_model.model_fields
        db = {k: v for k, v in db_rows.get(name, {}).items() if k in fields}
        try:
            providers[name] = cls.from_settings(name, ent["config"], db=db, db_models=db_models.get(name),
                                                secrets=secrets, environ=environ,
                                                transport=transports.get(name))
        except Exception as e:
            errors.append(f"ai.providers[{name}]: {e}")
            logger.error(f"ai provider '{name}' not created: {e}")
    return LLMFactory(settings, providers, secrets=secrets, build_errors=errors)


# ── the process-wide factory ────────────────────────────────────

_factory: Optional[LLMFactory] = None


def init_llm_factory(config: Any = None, db_session=None, *, raw: Optional[Dict[str, Any]] = None) -> LLMFactory:
    """Build and install the process-wide factory (closing the previous one). ``config`` (the
    flattened application config) is accepted for compatibility; ai.* is read from the YAML."""
    global _factory
    old = _factory
    _factory = build_llm_factory(raw, db_session=db_session)
    if old is not None:
        old.close()
    return _factory


def set_llm_factory(factory: Optional[LLMFactory]) -> None:
    global _factory
    _factory = factory


def llm_factory() -> Optional[LLMFactory]:
    """The process-wide factory, or None before the intelligence layer starts."""
    return _factory
