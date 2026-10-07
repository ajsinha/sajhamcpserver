"""
SAJHA MCP Server — LLM Gateway
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The only thing consumers call. It turns "a request for a kind of model" into a call on a
concrete model and applies policy around it:

  * aliases, not model ids, in code: ``default``, ``fast``, ``reasoning``, ``embedding`` map to
    ordered ``provider/model`` candidates (a bare provider name = its default model); the first
    active, healthy candidate whose capabilities fit wins; a user's saved preference goes first;
  * role policy (allowed provider/model globs, tool use, output-token cap) checked before a call;
  * retries with jittered backoff for RateLimited / ProviderUnavailable, then fallback to the
    next candidate; a circuit breaker per provider (SAJHA's CircuitBreaker);
  * budgets from the token tracker, per user and per role, per UTC day;
  * the response cache keyed on the canonical request;
  * one OpenTelemetry span per call (prompts excluded unless ai.gateway.trace_prompts).

The interface is shaped like an OpenAI-style client over the canonical Chat Completions types
(sajha/ai/llm/canonical.py; docs/architecture/LLM Tools.md §13):

    gw.chat_completions_create(model="reasoning", messages=[...], tools=[...]) -> ChatCompletion
    gw.chat_completions_stream(...)          -> Iterator[ChatCompletionChunk]
    await gw.achat_completions_create(...)   native async (HTTP providers use httpx.AsyncClient)
    gw.achat_completions_stream(...)         async iterator of chunks
    gw.embeddings_create(model="embedding", input=[...]) -> EmbeddingsResponse
    gw.models(ctx)                           -> list[ModelInfo] the caller's role may use

The caller's identity travels in ``sajha.context`` (a RequestContext); the response's ``sajha``
says which provider and model answered, the cost, whether the cache answered, the fallback
attempts, the trace id, and what SAJHA did on the caller's behalf (``ignored``,
``usage_estimated``, ``structured_output``).

    from sajha.ai.gateway import get_gateway
    from sajha.ai.llm.canonical import ChatMessage, SajhaRequest
    gw = get_gateway()
    c = gw.chat_completions_create(model="default", messages=[ChatMessage.user("Hello")],
                                   sajha=SajhaRequest(context=ctx))
    c.text, c.sajha.provider, c.sajha.cost_usd

The original interface (chat / stream / achat on ChatRequest and ChatResponse) and the pre-6.x
API (complete, complete_messages, embed, list_all_models, health_check_all, user preferences,
stats) are thin shims over the canonical calls (lossless converters in convert.py), so every
existing caller keeps working.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChunkAccumulator,
                                    CompletionUsage, EmbeddingsRequest, EmbeddingsResponse, SajhaRequest,
                                    StreamOptions, check_request, completion_to_chunks)
from sajha.ai.llm.convert import events_from_chunks, from_canonical_response, to_canonical_request
from sajha.ai.llm.errors import (AuthenticationFailed, BudgetExceeded, ConfigurationError,
                                 ContextTooLong, InvalidRequest, LLMError, ModelFailed, NoModelAvailable,
                                 PolicyDenied, ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.model import ChatModel, EmbeddingModel, HealthStatus, ModelInfo, Needs
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import AISettings, ModelOverride, RolePolicy, load_ai_yaml
from sajha.ai.llm.types import ChatRequest, ChatResponse, ImagePart, Message, RequestContext, Usage

logger = logging.getLogger(__name__)


# ── Response cache ──────────────────────────────────────────────

class ResponseCache:
    """In-memory TTL cache of ChatCompletions keyed on (qualified model, canonical request)."""

    def __init__(self, max_size: int = 500, ttl: int = 3600):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def key(model: str, request: Any) -> str:
        """(qualified model, canonical request) -> key. Accepts a ChatCompletionRequest or a ChatRequest."""
        form = request.cache_key() if hasattr(request, "cache_key") else request.canonical()
        raw = json.dumps({"model": model, "req": form}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[1] < self._ttl:
                self._hits += 1
                return hit[0]
            if hit:
                del self._cache[key]
            self._misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._cache) >= self._max_size and key not in self._cache:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (value, time.time())

    def clear(self):
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict:
        return {"size": len(self._cache), "hits": self._hits, "misses": self._misses,
                "hit_rate": f"{self._hits / max(self._hits + self._misses, 1) * 100:.1f}%"}


# ── Token tracker (usage + budgets) ─────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class TokenTracker:
    """
    Usage per user/provider/model (all time) and per user / per role per UTC day.

    With a shared state store (``state.backend`` redis or database) the counters
    live there, so daily budgets hold across every worker instead of each
    worker granting the full budget.  With the memory backend each tracker keeps
    its own private counters, as before.
    """

    _DAY_TTL = 2 * 86400

    def __init__(self, store=None):
        if store is None:
            from sajha.core.state import get_state_store
            from sajha.core.state.memory import MemoryStateStore
            shared = get_state_store()
            store = shared if shared.shared else MemoryStateStore("")
        self._store = store

    def record_usage(self, user_id: str, roles: List[str], provider: str, model: str, usage: Usage) -> None:
        day = _today()

        def add(cur):
            cur = cur or {}
            m = cur.setdefault(provider, {}).setdefault(
                model, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "count": 0})
            m["input_tokens"] += usage.input_tokens
            m["output_tokens"] += usage.output_tokens
            m["cost_usd"] += usage.cost_usd
            m["count"] += 1
            return cur

        self._store.update(f"llm:usage:{user_id}", add)
        self._store.incr(f"llm:daily:user:{user_id}:{day}", usage.total_tokens, ttl=self._DAY_TTL)
        for r in roles or []:
            self._store.incr(f"llm:daily:role:{r}:{day}", usage.total_tokens, ttl=self._DAY_TTL)

    def record(self, user_id: str, response) -> None:
        """Legacy: record an LLMResponse-like object."""
        self.record_usage(user_id, [], response.provider, response.model,
                          Usage(response.input_tokens, response.output_tokens, 0, response.cost_usd))

    def daily_user_tokens(self, user_id: str, day: str = "") -> int:
        return int(self._store.get(f"llm:daily:user:{user_id}:{day or _today()}") or 0)

    def daily_role_tokens(self, role: str, day: str = "") -> int:
        return int(self._store.get(f"llm:daily:role:{role}:{day or _today()}") or 0)

    def get_usage(self, user_id: str = "") -> Dict:
        if user_id:
            return self._store.get(f"llm:usage:{user_id}") or {}
        return {k[len("llm:usage:"):]: v for k, v in self._store.scan("llm:usage:")}

    def get_total_cost(self, user_id: str = "") -> float:
        usage = self.get_usage(user_id)
        if not user_id:
            return sum(m.get("cost_usd", 0.0) for u in usage.values() for p in u.values() for m in p.values())
        return sum(m.get("cost_usd", 0.0) for p in usage.values() for m in p.values())


class EmbeddingVectors(list):
    """A list of vectors that also carries .embeddings/.model/.provider/.dimensions (legacy shape)."""

    def __init__(self, vectors, model: str = "", provider: str = ""):
        super().__init__(vectors)
        self.model = model
        self.provider = provider

    @property
    def embeddings(self):
        return list(self)

    @property
    def dimensions(self) -> int:
        return len(self[0]) if self else 0

    @property
    def total_tokens(self) -> int:
        return 0


@dataclass
class Attempt:
    candidate: str
    outcome: str
    detail: str = ""


# ── The gateway ─────────────────────────────────────────────────

class LLMGateway:
    def __init__(self, settings: Optional[AISettings] = None, providers: Optional[Dict[str, LLMProvider]] = None,
                 *, secrets: Optional[SecretStore] = None, build_errors: Optional[List[str]] = None):
        self.settings = settings or AISettings({})
        self.providers: Dict[str, LLMProvider] = dict(providers or {})
        self.secrets = secrets or SecretStore()
        self.build_errors = list(build_errors or [])
        cs = self.settings.cache
        self._cache = ResponseCache(max_size=cs.max_entries, ttl=cs.ttl_seconds)
        self._tracker = TokenTracker()
        self._user_preferences: Dict[str, Dict] = {}
        self._system_default: Optional[str] = None
        self._health: Dict[str, Tuple[HealthStatus, float]] = {}
        self._breakers: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._rng = random.Random()
        self.sleep = time.sleep          # injectable (tests)
        self.audit_hook = None           # callable(dict) for per-call audit, optional
        active = [n for n, p in self.providers.items() if p.active]
        logger.info(f"LLMGateway initialized: providers={active} default={self.settings.aliases.get('default')}")

    # ── providers ──────────────────────────────────────────────
    @property
    def _providers(self) -> Dict[str, LLMProvider]:
        """Active providers (the old attribute name; app.py logs its size)."""
        return {n: p for n, p in self.providers.items() if p.active}

    def add_provider(self, provider: LLMProvider) -> LLMProvider:
        with self._lock:
            self.providers[provider.name] = provider
            self._health.pop(provider.name, None)
        return provider

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self.providers.get(name)

    def provider_health(self, name: str, refresh: bool = False) -> HealthStatus:
        p = self.providers.get(name)
        if p is None:
            return HealthStatus("down", "unknown provider")
        now = time.time()
        cached = self._health.get(name)
        if cached and not refresh and now - cached[1] < self.settings.gateway.health_ttl_s:
            return cached[0]
        try:
            h = p.health()
        except Exception as e:
            h = HealthStatus("down", f"health check failed: {e.__class__.__name__}")
        self._health[name] = (h, now)
        return h

    def _mark_down(self, name: str, detail: str) -> None:
        self._health[name] = (HealthStatus("down", detail), time.time())

    def breaker(self, name: str):
        from sajha.core.circuit_breaker import CircuitBreaker
        with self._lock:
            b = self._breakers.get(name)
            if b is None:
                bs = self.settings.breaker
                b = CircuitBreaker(f"llm:{name}", failure_threshold=bs.failure_threshold,
                                   recovery_timeout=bs.recovery_timeout_s)
                self._breakers[name] = b
            return b

    # ── policy and budgets ─────────────────────────────────────
    def effective_policy(self, ctx: Optional[RequestContext]) -> Optional[RolePolicy]:
        """Union of the caller's role policies (most permissive wins); None = unrestricted."""
        ps = self.settings.policy
        if not ps.enabled or ctx is None:
            return None
        roles = list(ctx.roles or [])
        pols = [ps.roles.get(r, ps.default) for r in roles] or [ps.default]
        if any(p is None for p in pols):
            return None                      # a role without a policy and no default: unrestricted
        allowed: List[str] = []
        for p in pols:
            allowed.extend(p.allowed)
        caps = [p.max_output_tokens for p in pols]
        daily = [p.daily_tokens for p in pols]
        return RolePolicy(allowed=allowed, tools=any(p.tools for p in pols),
                          max_output_tokens=None if None in caps else max(caps),
                          daily_tokens=None if None in daily else max(daily))

    @staticmethod
    def _allowed(policy: Optional[RolePolicy], qualified: str) -> bool:
        if policy is None:
            return True
        return any(fnmatch.fnmatchcase(qualified, pat) or pat == "*" for pat in policy.allowed)

    def policy_allows_tools(self, ctx: Optional[RequestContext]) -> bool:
        p = self.effective_policy(ctx)
        return True if p is None else p.tools

    def check_budget(self, ctx: Optional[RequestContext]) -> None:
        bs = self.settings.budgets
        if not bs.enabled or ctx is None:
            return
        owner = ctx.budget_owner
        used = self._tracker.daily_user_tokens(owner)
        limits = []
        if bs.per_user_daily_tokens:
            limits.append(bs.per_user_daily_tokens)
        pol = self.effective_policy(ctx)
        if pol is not None and pol.daily_tokens:
            limits.append(pol.daily_tokens)
        if limits and used >= min(limits):
            raise BudgetExceeded(f"daily token budget of {min(limits)} reached for {owner} ({used} used)")
        for r in ctx.roles or []:
            lim = bs.per_role_daily_tokens.get(r)
            if lim and self._tracker.daily_role_tokens(r) >= lim:
                raise BudgetExceeded(f"daily token budget of {lim} reached for role {r}")

    # ── resolution ─────────────────────────────────────────────
    def _expand(self, model: str, ctx: Optional[RequestContext], kind: str) -> List[str]:
        entries = list(self.settings.aliases.get(model, [])) if model in self.settings.aliases else [model]
        is_alias = model in self.settings.aliases
        if is_alias and kind == "chat":
            if model == "default" and self._system_default:
                entries.insert(0, self._system_default)
            pref = self._user_preferences.get(ctx.user_id, {}) if ctx and ctx.user_id else {}
            if pref.get("provider") or pref.get("model"):
                pm = pref.get("model", "")
                entries.insert(0, pm if "/" in pm else f"{pref.get('provider', '')}/{pm}".rstrip("/"))
        seen, out = set(), []
        for e in entries:
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return out

    @staticmethod
    def _split(entry: str) -> Tuple[str, str]:
        prov, _, mid = entry.partition("/")
        return prov, ("" if mid == "*" else mid)

    @staticmethod
    def request_needs(request: Any, needs: Any = None) -> Needs:
        """Capability flags a request needs (a pre-filter; the model's own check is authoritative)."""
        n = Needs.parse(needs)
        flags = set(n.flags)
        if isinstance(request, ChatCompletionRequest):
            if request.wants_tools:
                flags.add("tools")
            if request.has_images:
                flags.add("vision")
            return Needs(frozenset(flags), n.tags, n.min_context)
        if request.tools and request.tool_choice != "none":
            flags.add("tools")
        if request.response_schema:
            flags.add("structured_output")
        if any(isinstance(p, ImagePart) for m in request.messages for p in m.parts):
            flags.add("vision")
        return Needs(frozenset(flags), n.tags, n.min_context)

    def candidates(self, model: str = "default", needs: Any = None, ctx: Optional[RequestContext] = None,
                   attempts: Optional[List[Attempt]] = None) -> List[ChatModel]:
        need = Needs.parse(needs)
        policy = self.effective_policy(ctx)
        out: List[ChatModel] = []
        attempts = attempts if attempts is not None else []
        for entry in self._expand(model, ctx, "chat"):
            pname, mid = self._split(entry)
            p = self.providers.get(pname)
            if p is None:
                attempts.append(Attempt(entry, "skipped", "no such provider"))
                continue
            if not p.active:
                attempts.append(Attempt(entry, "skipped", "provider disabled"))
                continue
            h = self.provider_health(pname)
            if not h.ok:
                attempts.append(Attempt(entry, "skipped", f"unhealthy: {h.detail}"))
                continue
            if self.settings.breaker.enabled and not self.breaker(pname).can_execute():
                attempts.append(Attempt(entry, "skipped", "circuit open"))
                continue
            try:
                cm = p.chat_model(mid)
            except LLMError as e:
                attempts.append(Attempt(entry, "skipped", str(e)))
                continue
            avail = getattr(p, "model_available", None)
            if avail is not None and not avail(cm.id):
                attempts.append(Attempt(entry, "skipped", f"model {cm.id} not available"))
                continue
            if need and not cm.capabilities.satisfies(need):
                attempts.append(Attempt(cm.qualified_id, "skipped", f"lacks {sorted(need.flags | need.tags)}"))
                continue
            if not self._allowed(policy, cm.qualified_id):
                attempts.append(Attempt(cm.qualified_id, "skipped", "not allowed for the caller's role"))
                continue
            if any(c.qualified_id == cm.qualified_id for c in out):
                continue
            out.append(cm)
        return out

    def resolve(self, model: str = "default", needs: Any = None, ctx: Optional[RequestContext] = None) -> ChatModel:
        attempts: List[Attempt] = []
        cands = self.candidates(model, needs, ctx, attempts)
        if not cands:
            raise NoModelAvailable(self._no_model_msg(model, attempts))
        return cands[0]

    def models(self, ctx: Optional[RequestContext] = None) -> List[ModelInfo]:
        """Every model of every active provider the caller's role may use (like GET /v1/models)."""
        policy = self.effective_policy(ctx)
        out: List[ModelInfo] = []
        for name, p in self.providers.items():
            if not p.active:
                continue
            try:
                out.extend(mi for mi in p.models() if self._allowed(policy, mi.qualified_id))
            except Exception as e:
                logger.warning(f"Failed to list models for {name}: {e}")
        return out

    @staticmethod
    def _no_model_msg(model: str, attempts: List[Attempt]) -> str:
        detail = "; ".join(f"{a.candidate}: {a.outcome} ({a.detail})" for a in attempts[-12:])
        return f"no model available for '{model}'" + (f" — {detail}" if detail else "")

    # ── calls: shared steps ────────────────────────────────────
    def _prepare(self, request: Any, ctx: Optional[RequestContext]) -> Any:
        """Policy (tool use, output-token cap), request refusals, n cap and budget, before any call.
        Accepts a ChatCompletionRequest (or, for older callers, a ChatRequest) and returns the same type."""
        if isinstance(request, ChatRequest):
            from sajha.ai.llm.convert import from_canonical_request
            return from_canonical_request(self._prepare(to_canonical_request(request), ctx))
        check_request(request)
        policy = self.effective_policy(ctx)
        if policy is not None:
            if request.wants_tools and not policy.tools:
                raise PolicyDenied("tool use is not permitted for the caller's role")
            if policy.max_output_tokens:
                cap = policy.max_output_tokens
                cur = request.max_output_tokens
                if cur is None or cur > cap:
                    request = request.model_copy(update={"max_completion_tokens": cap, "max_tokens": None})
        if (request.n or 1) > self.settings.gateway.max_samples:
            raise InvalidRequest(f"n={request.n} exceeds ai.gateway.max_samples ({self.settings.gateway.max_samples})")
        self.check_budget(ctx)
        return request

    def _cacheable(self, request: Any, cm: ChatModel) -> bool:
        cs = self.settings.cache
        if not cs.enabled:
            return False
        if cs.cache_nonzero_temperature:
            return True
        if request.temperature == 0:
            return True
        return request.temperature is None and "deterministic" in cm.capabilities.tags

    def _backoff(self, attempt: int, cfg) -> float:
        rs = self.settings.retry
        base = cfg.backoff_base_s if cfg.backoff_base_s is not None else rs.backoff_base_s
        cap = cfg.backoff_max_s if cfg.backoff_max_s is not None else rs.backoff_max_s
        d = min(cap, base * (2 ** attempt))
        j = rs.jitter
        return max(0.0, d * (1 + self._rng.uniform(-j, j)))

    @contextmanager
    def _span(self, name: str, attrs: Dict[str, Any]):
        tracer = None
        try:
            from sajha.observability import get_otel
            otel = get_otel()
            tracer = getattr(otel, "_tracer", None) if otel is not None else None
        except Exception:
            tracer = None
        if tracer is None:
            try:
                from opentelemetry import trace
                tracer = trace.get_tracer("sajha.ai")
            except Exception:
                tracer = None
        if tracer is None:
            yield None
            return
        with tracer.start_as_current_span(name, attributes={k: v for k, v in attrs.items() if v is not None}) as sp:
            yield sp

    def _record(self, ctx: Optional[RequestContext], provider: str, model: str, usage: Usage) -> None:
        owner = ctx.budget_owner if ctx else "anonymous"
        self._tracker.record_usage(owner, list(ctx.roles) if ctx else [], provider, model, usage)

    @staticmethod
    def _observe(ctx: Optional[RequestContext], provider: str, model: str, outcome: str, seconds: float,
                 usage: Optional[Usage] = None) -> None:
        """Metrics and the usage ledger (sajha/observability); never raises."""
        try:
            from sajha.observability.metrics import record_llm
            u = usage or Usage()
            record_llm(provider, model, outcome, seconds, u.input_tokens, u.output_tokens, u.cost_usd, ctx=ctx)
        except Exception:
            pass

    def _retry_budget(self, model: Any) -> int:
        cfg = model.provider.config
        return cfg.max_retries if cfg.max_retries is not None else self.settings.retry.max_retries

    def _retry_delay(self, e: LLMError, attempt: int, cfg) -> float:
        rs = self.settings.retry
        if isinstance(e, RateLimited) and e.retry_after is not None:
            return min(e.retry_after, rs.max_retry_after_s)
        return self._backoff(attempt, cfg)

    def _call_with_retries(self, model: Any, call):
        """``call()`` with retries on RateLimited / ProviderUnavailable (jittered backoff, Retry-After)."""
        retries = self._retry_budget(model)
        last: Optional[LLMError] = None
        for attempt in range(retries + 1):
            try:
                return call()
            except (RateLimited, ProviderUnavailable) as e:
                last = e
                delay = self._retry_delay(e, attempt, model.provider.config)
            if attempt < retries:
                logger.info(f"LLM retry {attempt + 1}/{retries} on {model.qualified_id} in {delay:.2f}s: {last}")
                self.sleep(delay)
        assert last is not None
        raise last

    async def _asleep(self, delay: float) -> None:
        if self.sleep is time.sleep:
            import anyio
            await anyio.sleep(delay)
        else:
            self.sleep(delay)                 # an injected (test) sleep

    async def _acall_with_retries(self, model: Any, call):
        retries = self._retry_budget(model)
        last: Optional[LLMError] = None
        for attempt in range(retries + 1):
            try:
                return await call()
            except (RateLimited, ProviderUnavailable) as e:
                last = e
                delay = self._retry_delay(e, attempt, model.provider.config)
            if attempt < retries:
                logger.info(f"LLM retry {attempt + 1}/{retries} on {model.qualified_id} in {delay:.2f}s: {last}")
                await self._asleep(delay)
        assert last is not None
        raise last

    def _span_attrs(self, cm: ChatModel, alias: str, ctx: Optional[RequestContext],
                    request: ChatCompletionRequest) -> Dict[str, Any]:
        attrs = {"llm.provider": cm.provider.name, "llm.model": cm.id, "llm.alias": alias,
                 "user.id": ctx.user_id if ctx else None}
        if self.settings.gateway.trace_prompts:
            attrs["llm.prompt"] = json.dumps(request.cache_key(), default=str)[:4000]
        return attrs

    def _cache_key(self, cm: ChatModel, request: ChatCompletionRequest) -> Optional[str]:
        return ResponseCache.key(cm.qualified_id, request) if self._cacheable(request, cm) else None

    def _cache_hit(self, ctx, cm: ChatModel, key: Optional[str], request: ChatCompletionRequest,
                   attempts: List[Attempt]) -> Optional[ChatCompletion]:
        if not key:
            return None
        hit = self._cache.get(key)
        if hit is None:
            return None
        comp = hit.model_copy(deep=True)
        comp.usage = CompletionUsage()
        sj = comp.ensure_sajha()
        sj.cached, sj.cost_usd, sj.latency_ms = True, 0.0, 0
        sj.attempts = [vars(a) for a in attempts]
        self._audit(ctx, cm, "cache_hit", Usage(), request)
        self._observe(ctx, cm.provider.name, cm.id, "cache_hit", 0.0)
        return comp

    def _on_failure(self, ctx, cm: ChatModel, e: LLMError, span, t0: float, attempts: List[Attempt]) -> bool:
        """Bookkeeping for a failed candidate; True when the next candidate should be tried."""
        pname = cm.provider.name
        if isinstance(e, (RateLimited, ProviderUnavailable)):
            self.breaker(pname).record_failure()
            outcome = "error"
        elif isinstance(e, AuthenticationFailed):
            self._mark_down(pname, "authentication failed")
            outcome = "auth_failed"
        elif isinstance(e, (UnsupportedFeature, ContextTooLong, ConfigurationError, ModelFailed)):
            outcome = e.code
        else:                                # ContentFiltered, InvalidRequest, ...: a property of the request
            self._span_outcome(span, e.code, e)
            self._observe(ctx, pname, cm.id, e.code, time.perf_counter() - t0)
            return False
        attempts.append(Attempt(cm.qualified_id, "failed", str(e)))
        self._span_outcome(span, outcome, e)
        self._observe(ctx, pname, cm.id, outcome, time.perf_counter() - t0)
        return True

    def _on_success(self, ctx, cm: ChatModel, request: ChatCompletionRequest, comp: ChatCompletion, span,
                    t0: float, attempts: List[Attempt], key: Optional[str]) -> ChatCompletion:
        pname = cm.provider.name
        self.breaker(pname).record_success()
        sj = comp.ensure_sajha()
        sj.attempts = [vars(a) for a in attempts]
        sj.trace_id = sj.trace_id or (ctx.trace_id if ctx else "") or (request.sajha.trace_id if request.sajha else "")
        u = comp.usage or CompletionUsage()
        usage = Usage(u.prompt_tokens, u.completion_tokens, u.cached_tokens, sj.cost_usd)
        self._record(ctx, sj.provider or pname, comp.model or cm.id, usage)
        self._observe(ctx, sj.provider or pname, comp.model or cm.id, "ok", time.perf_counter() - t0, usage)
        if span is not None:
            try:
                span.set_attribute("llm.input_tokens", usage.input_tokens)
                span.set_attribute("llm.output_tokens", usage.output_tokens)
                span.set_attribute("llm.latency_ms", sj.latency_ms)
                span.set_attribute("llm.cache_hit", False)
                span.set_attribute("llm.outcome", comp.finish_reason)
            except Exception:
                pass
        # refusals (content_filter) and truncated answers are never cached
        if key and all(ch.finish_reason in ("stop", "tool_calls") for ch in comp.choices):
            self._cache.put(key, comp.model_copy(deep=True))
        self._audit(ctx, cm, "ok", usage, request)
        return comp

    @staticmethod
    def _span_outcome(span, outcome: str, err: Exception) -> None:
        if span is None:
            return
        try:
            from opentelemetry.trace import StatusCode
            span.set_attribute("llm.outcome", outcome)
            span.set_status(StatusCode.ERROR, str(err)[:200])
        except Exception:
            pass

    def _audit(self, ctx, cm, outcome, usage: Optional[Usage], request: Optional[ChatCompletionRequest] = None) -> None:
        if self.audit_hook:
            try:
                rec = {"user": ctx.user_id if ctx else "", "model": cm.qualified_id, "outcome": outcome,
                       "usage": usage.to_dict() if usage is not None else None}
                if request is not None and request.user:
                    rec["end_user"] = request.user          # the caller's label; never sent to a vendor
                if request is not None and request.metadata:
                    rec["metadata"] = dict(request.metadata)
                self.audit_hook(rec)
            except Exception:
                pass

    def _begin(self, request: Any, fields: Dict[str, Any]):
        req = ChatCompletionRequest.coerce(request, **fields)
        alias, ctx = req.model or "default", req.context
        req = self._prepare(req, ctx)
        attempts: List[Attempt] = []
        cands = self.candidates(alias, self.request_needs(req, req.sajha.needs if req.sajha else None), ctx, attempts)
        if not cands:
            raise NoModelAvailable(self._no_model_msg(alias, attempts))
        return req, alias, ctx, attempts, cands

    # ── the canonical interface ────────────────────────────────
    def chat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        """A Chat Completions call through policy, budgets, cache, retries, breakers and fallback.

        ``model`` is an alias (``default``, ``fast``, ``reasoning``) or ``provider/model``; the
        caller's identity rides in ``sajha.context`` (a RequestContext)."""
        req, alias, ctx, attempts, cands = self._begin(request, fields)
        if req.stream:
            raise InvalidRequest("stream=true: use chat_completions_stream")
        last_err: Optional[LLMError] = None
        for cm in cands:
            key = self._cache_key(cm, req)
            hit = self._cache_hit(ctx, cm, key, req, attempts)
            if hit is not None:
                return hit
            with self._span("llm.chat", self._span_attrs(cm, alias, ctx, req)) as span:
                t0 = time.perf_counter()
                try:
                    comp = self._call_with_retries(cm, lambda: cm.chat_completions_create(req))
                except LLMError as e:
                    if self._on_failure(ctx, cm, e, span, t0, attempts):
                        last_err = e
                        continue
                    raise
                return self._on_success(ctx, cm, req, comp, span, t0, attempts, key)
        raise NoModelAvailable(self._no_model_msg(alias, attempts)) from last_err

    async def achat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        """The native-async twin of chat_completions_create (HTTP providers call their vendor
        with httpx.AsyncClient; others run in a worker thread)."""
        req, alias, ctx, attempts, cands = self._begin(request, fields)
        if req.stream:
            raise InvalidRequest("stream=true: use achat_completions_stream")
        last_err: Optional[LLMError] = None
        for cm in cands:
            key = self._cache_key(cm, req)
            hit = self._cache_hit(ctx, cm, key, req, attempts)
            if hit is not None:
                return hit
            with self._span("llm.chat", self._span_attrs(cm, alias, ctx, req)) as span:
                t0 = time.perf_counter()
                try:
                    comp = await self._acall_with_retries(cm, lambda: cm.achat_completions_create(req))
                except LLMError as e:
                    if self._on_failure(ctx, cm, e, span, t0, attempts):
                        last_err = e
                        continue
                    raise
                return self._on_success(ctx, cm, req, comp, span, t0, attempts, key)
        raise NoModelAvailable(self._no_model_msg(alias, attempts)) from last_err

    def chat_completions_stream(self, request: Any = None, /, **fields) -> Iterator[ChatCompletionChunk]:
        """Stream chunks from the first candidate that starts; falls back only before the first
        chunk. The final usage chunk is sent when ``stream_options.include_usage`` is set."""
        req, alias, ctx, attempts, cands = self._begin(request, fields)
        include = req.include_usage
        last_err: Optional[LLMError] = None
        for cm in cands:
            key = self._cache_key(cm, req)
            hit = self._cache_hit(ctx, cm, key, req, attempts)
            if hit is not None:
                yield from completion_to_chunks(hit, include_usage=include)
                return
            started, t0, acc = False, time.perf_counter(), ChunkAccumulator()
            try:
                for c in cm.chat_completions_stream(req):
                    started = True
                    out = self._stream_step(ctx, cm, req, c, acc, t0, attempts, key)
                    if out is not None and (include or not out.is_usage):
                        yield out
                return
            except LLMError as e:
                if started or not self._on_failure(ctx, cm, e, None, t0, attempts):
                    raise
                last_err = e
        raise NoModelAvailable(self._no_model_msg(alias, attempts)) from last_err

    async def achat_completions_stream(self, request: Any = None, /, **fields) -> AsyncIterator[ChatCompletionChunk]:
        req, alias, ctx, attempts, cands = self._begin(request, fields)
        include = req.include_usage
        last_err: Optional[LLMError] = None
        for cm in cands:
            key = self._cache_key(cm, req)
            hit = self._cache_hit(ctx, cm, key, req, attempts)
            if hit is not None:
                for c in completion_to_chunks(hit, include_usage=include):
                    yield c
                return
            started, t0, acc = False, time.perf_counter(), ChunkAccumulator()
            try:
                async for c in cm.achat_completions_stream(req):
                    started = True
                    out = self._stream_step(ctx, cm, req, c, acc, t0, attempts, key)
                    if out is not None and (include or not out.is_usage):
                        yield out
                return
            except LLMError as e:
                if started or not self._on_failure(ctx, cm, e, None, t0, attempts):
                    raise
                last_err = e
        raise NoModelAvailable(self._no_model_msg(alias, attempts)) from last_err

    def _stream_step(self, ctx, cm, req, c: ChatCompletionChunk, acc: ChunkAccumulator, t0: float,
                     attempts: List[Attempt], key: Optional[str]) -> ChatCompletionChunk:
        acc.add(c)
        if c.is_usage:                       # the last chunk: account for the whole answer
            comp = acc.result()
            done = self._on_success(ctx, cm, req, comp, None, t0, attempts, key)
            c.sajha = done.sajha
        return c

    # ── the original interface (ChatRequest / ChatResponse), over the canonical one ──
    @staticmethod
    def _legacy_request(request: ChatRequest, model: str, needs: Any) -> ChatCompletionRequest:
        creq = to_canonical_request(request, model)
        creq.sajha.needs = needs
        return creq

    def chat(self, request: ChatRequest, *, model: str = "default", needs: Any = None) -> ChatResponse:
        return from_canonical_response(self.chat_completions_create(self._legacy_request(request, model, needs)))

    def stream(self, request: ChatRequest, *, model: str = "default", needs: Any = None) -> Iterator:
        """Legacy events (TextDelta, ToolCallDelta, UsageEvent, Done) from the canonical stream."""
        creq = self._legacy_request(request, model, needs)
        creq.stream_options = StreamOptions(include_usage=True)
        yield from events_from_chunks(self.chat_completions_stream(creq))

    async def achat(self, request: ChatRequest, *, model: str = "default", needs: Any = None) -> ChatResponse:
        creq = self._legacy_request(request, model, needs)
        return from_canonical_response(await self.achat_completions_create(creq))

    async def aembed(self, texts: List[str], model: str = "embedding", purpose: Optional[str] = None
                     ) -> "EmbeddingVectors":
        import anyio
        return await anyio.to_thread.run_sync(lambda: self.embed(texts, model=model, purpose=purpose))

    # ── embeddings ─────────────────────────────────────────────
    def embedding_model(self, model: str = "embedding") -> EmbeddingModel:
        attempts: List[Attempt] = []
        for entry in self._expand(model, None, "embedding"):
            pname, mid = self._split(entry)
            p = self.providers.get(pname)
            if p is None or not p.active:
                attempts.append(Attempt(entry, "skipped", "unavailable"))
                continue
            if not self.provider_health(pname).ok:
                attempts.append(Attempt(entry, "skipped", "unhealthy"))
                continue
            try:
                em = p.embedding_model(mid)
            except LLMError as e:
                attempts.append(Attempt(entry, "skipped", str(e)))
                continue
            avail = getattr(p, "model_available", None)
            if avail is not None and not avail(em.id):
                attempts.append(Attempt(entry, "skipped", "model not pulled"))
                continue
            return em
        raise NoModelAvailable(self._no_model_msg(model, attempts))

    def embeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        """Embeddings through the alias's candidates, with retries and fallback.

        ``sajha.input_purpose`` (query | document) selects the vendor's input type where it has
        one (Cohere ``input_type``, Gemini ``taskType``)."""
        req = EmbeddingsRequest.coerce(request, **fields)
        target = req.model or "embedding"
        ctx = req.sajha.context if req.sajha else None
        policy = self.effective_policy(ctx)
        last: Optional[Exception] = None
        tried: List[str] = []
        for entry in self._expand(target, None, "embedding"):
            try:
                em = self.embedding_model(entry)
            except NoModelAvailable as e:
                last = e
                continue
            if not self._allowed(policy, em.qualified_id):
                continue
            tried.append(em.qualified_id)
            try:
                resp = self._call_with_retries(em, lambda: em.embeddings_create(req))
            except (RateLimited, ProviderUnavailable, AuthenticationFailed, UnsupportedFeature) as e:
                last = e
                if isinstance(e, AuthenticationFailed):
                    self._mark_down(em.provider.name, "authentication failed")
                continue
            if ctx is not None:
                sj = resp.sajha
                self._record(ctx, em.provider.name, em.id,
                             Usage(resp.usage.prompt_tokens, 0, 0, sj.cost_usd if sj else 0.0))
            return resp
        raise NoModelAvailable(f"no embedding model available for '{target}' (tried {tried})") from last

    async def aembeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        import anyio
        return await anyio.to_thread.run_sync(lambda: self.embeddings_create(request, **fields))

    def embed(self, texts: List[str], provider: str = "", model: str = "", purpose: Optional[str] = None
              ) -> EmbeddingVectors:
        """embed(texts, model="embedding", purpose="query"|"document"|None) -> vectors. Also accepts
        the legacy (provider=, model=) form."""
        target = model or "embedding"
        if provider:
            target = f"{provider}/{model}" if model else provider
        elif model and model not in self.settings.aliases and "/" not in model:
            target = "embedding"
        resp = self.embeddings_create(model=target, input=list(texts),
                                      sajha=SajhaRequest(input_purpose=purpose) if purpose else None)
        return EmbeddingVectors(resp.vectors, resp.model, resp.sajha.provider if resp.sajha else "")


    # ── preferences and defaults ───────────────────────────────
    def set_user_preference(self, user_id: str, provider: str = "", model: str = "",
                            temperature: float = 0.0, max_tokens: int = 0):
        pref = {}
        if provider: pref["provider"] = provider
        if model: pref["model"] = model
        if temperature > 0: pref["temperature"] = temperature
        if max_tokens > 0: pref["max_tokens"] = max_tokens
        self._user_preferences[user_id] = pref

    def get_user_preference(self, user_id: str) -> Dict:
        return self._user_preferences.get(user_id, {})

    def clear_user_preference(self, user_id: str):
        self._user_preferences.pop(user_id, None)

    def set_system_default(self, provider: str = "", model: str = "") -> None:
        """Put provider[/model] first in the 'default' alias (the settings page's 'make default')."""
        self._system_default = (f"{provider}/{model}" if model else provider) if provider else None

    @property
    def config(self) -> SimpleNamespace:
        """Legacy view: default_provider / default_model of the 'default' alias, as resolved now."""
        try:
            cm = self.resolve("default")
            return SimpleNamespace(default_provider=cm.provider.name, default_model=cm.id)
        except LLMError:
            return SimpleNamespace(default_provider="", default_model="")

    # ── legacy shims ───────────────────────────────────────────
    def _legacy_target(self, user_id: str, provider: str, model: str) -> str:
        if provider and model:
            return f"{provider}/{model}"
        if provider:
            return provider
        if model and "/" in model:
            return model
        if model:
            # a bare model id: find the provider that lists it
            for p in self.providers.values():
                if p.active and any(d.id == model for d in p.list_models()):
                    return f"{p.name}/{model}"
        return "default"

    def complete(self, prompt: str, user_id: str = "", provider: str = "", model: str = "", system: str = "",
                 temperature: float = 0.0, max_tokens: int = 0, tools: Optional[List[Dict]] = None,
                 use_cache: bool = True, **kwargs):
        return self.complete_messages([{"role": "user", "content": prompt}], user_id=user_id, provider=provider,
                                      model=model, system=system, temperature=temperature, max_tokens=max_tokens,
                                      tools=tools, use_cache=use_cache, **kwargs)

    def complete_messages(self, messages: List[Dict[str, str]], user_id: str = "", provider: str = "",
                          model: str = "", system: str = "", temperature: float = 0.0, max_tokens: int = 0,
                          tools: Optional[List[Dict]] = None, use_cache: bool = True, roles=None, **kwargs):
        from sajha.ai.llm.types import TextPart, ToolSpec
        from sajha.ai.providers import LLMResponse
        pref = self._user_preferences.get(user_id, {})
        msgs = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                system = (system + "\n\n" + m.get("content", "")).strip()
            else:
                msgs.append(Message("assistant" if role == "assistant" else "user",
                                    [TextPart(m.get("content", ""))]))
        req = ChatRequest(msgs, system=system,
                          tools=[ToolSpec.from_mcp(t) for t in tools or []],
                          temperature=temperature or pref.get("temperature") or 0.0,
                          max_output_tokens=max_tokens or pref.get("max_tokens") or None,
                          metadata=RequestContext(user_id=user_id, roles=list(roles or [])))
        if not use_cache:
            req.temperature = req.temperature or 0.0001
        resp = self.chat(req, model=self._legacy_target(user_id, provider, model))
        return LLMResponse(content=resp.text, model=resp.model, provider=resp.provider,
                           input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                           total_tokens=resp.usage.total_tokens, finish_reason=resp.finish_reason,
                           latency_ms=resp.latency_ms, cost_usd=resp.usage.cost_usd)

    def list_all_models(self):
        from sajha.ai.providers import ModelInfo
        out = []
        for name, p in self.providers.items():
            if not p.active:
                continue
            try:
                for d in p.list_models():
                    c = d.capabilities
                    out.append(ModelInfo(id=d.id, name=d.display_name or d.id, provider=name,
                                         context_window=c.context_window,
                                         input_cost_per_1k=c.input_cost_per_mtok / 1000,
                                         output_cost_per_1k=c.output_cost_per_mtok / 1000,
                                         supports_tools=c.tools, supports_vision=c.vision,
                                         supports_streaming=c.streaming, max_output_tokens=c.max_output_tokens,
                                         tags=sorted(c.tags) + (["embedding"] if d.kind == "embedding" else [])))
            except Exception as e:
                logger.warning(f"Failed to list models for {name}: {e}")
        return out

    def health_check_all(self) -> Dict[str, bool]:
        return {n: self.provider_health(n, refresh=True).ok for n, p in self.providers.items() if p.active}

    def get_stats(self) -> Dict:
        return {
            "providers": [n for n, p in self.providers.items() if p.active],
            "default_provider": self.config.default_provider,
            "default_model": self.config.default_model,
            "aliases": self.settings.aliases,
            "cache": self._cache.stats(),
            "user_preferences": len(self._user_preferences),
            "total_models": len(self.list_all_models()),
            "breakers": {n: b.to_dict() for n, b in self._breakers.items()},
        }

    def get_token_usage(self, user_id: str = "") -> Dict:
        return self._tracker.get_usage(user_id)

    def get_total_cost(self, user_id: str = "") -> float:
        return self._tracker.get_total_cost(user_id)

    # ── effective configuration ────────────────────────────────
    def describe_config(self) -> Dict[str, Any]:
        providers = {}
        for name, p in self.providers.items():
            d = p.describe_config()
            d["health"] = self.provider_health(name).to_dict() if p.active else {"status": "disabled", "detail": ""}
            providers[name] = d
        resolved = {}
        for alias in self.settings.aliases:
            try:
                if alias == "embedding":
                    resolved[alias] = self.embedding_model(alias).qualified_id
                else:
                    resolved[alias] = self.resolve(alias).qualified_id
            except LLMError as e:
                resolved[alias] = f"unavailable: {e}"
        mock_only = all(v.startswith("mock/") for v in resolved.values() if not v.startswith("unavailable"))
        return {
            "active_providers": [n for n, p in self.providers.items() if p.active],
            "resolved_aliases": resolved,
            "mock_active": mock_only,
            "note": ("The mock provider is serving every alias (no real provider is enabled). Enable one with "
                     "SAJHA_AI_<PROVIDER>_ENABLED=true, set its key, and point an alias at it, e.g. "
                     "SAJHA_AI_ALIASES_DEFAULT=openai,mock/mock-planner.") if mock_only else "",
            "sections": self.settings.describe(),
            "providers": providers,
            "build_errors": self.build_errors,
        }

    def close(self):
        for p in self.providers.values():
            try:
                p.close()
            except Exception:
                pass


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


def build_gateway(raw: Optional[Dict[str, Any]] = None, *, db_session=None, environ: Optional[Dict[str, str]] = None,
                  transports: Optional[Dict[str, Any]] = None, secrets: Optional[SecretStore] = None,
                  db_lookup=None) -> LLMGateway:
    """Build the gateway from the ai: section (raw YAML dict), env, and optionally the DB tables."""
    from sajha.ai.llm import registry
    from sajha.ai.llm.secrets import db_secret_lookup
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
        from sajha.ai.providers import get_registered_types
        from sajha.ai.llm.legacy import LegacyProviderAdapter
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
    gw = LLMGateway(settings, providers, secrets=secrets, build_errors=errors)
    return gw


# ── Singleton ────────────────────────────────────────────────────

_gateway: Optional[LLMGateway] = None


def init_gateway(config: Any = None, db_session=None, *, raw: Optional[Dict[str, Any]] = None) -> LLMGateway:
    """Initialise the process-wide gateway. ``config`` (the flattened _CFG) is accepted for
    backward compatibility; ai.* is read from the raw YAML."""
    global _gateway
    old = _gateway
    _gateway = build_gateway(raw, db_session=db_session)
    if old is not None:
        old.close()
    return _gateway


def set_gateway(gw: Optional[LLMGateway]) -> None:
    global _gateway
    _gateway = gw


def get_gateway() -> Optional[LLMGateway]:
    return _gateway
