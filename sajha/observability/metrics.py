"""
SAJHA MCP Server — Prometheus metrics: a small registry, the text exposition format, and
the instrumentation points every subsystem calls.

No ``prometheus_client`` dependency: counters, gauges and histograms with labels, a
per-family series cap (``observability.metrics.max_series``), "collected" families read
from their owner at scrape time, and the 0.0.4 text format. With several workers and a
shared state store, each worker publishes a snapshot and ``/metrics`` merges them under a
``worker`` label (docs/architecture/Observability.md, section 2.4).

The ``record_*`` functions are the instrumentation points. Each one feeds the registry,
the usage ledger (tool and LLM calls), the alert window, the legacy JSON collector and,
when configured, OpenTelemetry metrics. None of them ever raises.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import gc
import logging
import math
import os
import platform
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from sajha.observability import settings as S

logger = logging.getLogger(__name__)

BUCKETS: Tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
OTHER = '_other'

Sample = Tuple[str, Dict[str, str], float]


# ── registry ────────────────────────────────────────────────────────

class _Family:
    kind = 'untyped'

    def __init__(self, registry: 'Registry', name: str, help_: str, labels: Sequence[str] = ()):
        self.name, self.help, self.labelnames = name, help_, tuple(labels)
        self._series: Dict[Tuple[str, ...], Any] = {}
        self._lock = threading.Lock()
        self._registry = registry
        registry.register(self)

    def _key(self, values: Sequence[Any]) -> Tuple[str, ...]:
        key = tuple('' if v is None else str(v) for v in values)
        if len(key) != len(self.labelnames):
            raise ValueError(f'{self.name}: expected labels {self.labelnames}, got {key}')
        if key not in self._series and len(self._series) >= self._registry.max_series():
            key = tuple(OTHER for _ in key)
            self._registry.dropped(self.name)
        return key

    def reset(self) -> None:
        with self._lock:
            self._series.clear()

    def samples(self) -> List[Sample]:
        raise NotImplementedError


class Counter(_Family):
    kind = 'counter'

    def inc(self, labels: Sequence[Any] = (), amount: float = 1.0) -> None:
        if amount < 0:
            return
        with self._lock:
            k = self._key(labels)
            self._series[k] = self._series.get(k, 0.0) + amount

    def value(self, labels: Sequence[Any] = ()) -> float:
        return self._series.get(tuple(str(v) for v in labels), 0.0)

    def samples(self) -> List[Sample]:
        with self._lock:
            return [(self.name, dict(zip(self.labelnames, k)), v) for k, v in self._series.items()]


class Gauge(_Family):
    kind = 'gauge'

    def set(self, labels: Sequence[Any] = (), value: float = 0.0) -> None:
        with self._lock:
            self._series[self._key(labels)] = float(value)

    def samples(self) -> List[Sample]:
        with self._lock:
            return [(self.name, dict(zip(self.labelnames, k)), v) for k, v in self._series.items()]


class Histogram(_Family):
    kind = 'histogram'

    def __init__(self, registry, name, help_, labels=(), buckets: Sequence[float] = BUCKETS):
        super().__init__(registry, name, help_, labels)
        self.buckets = tuple(sorted(buckets))

    def observe(self, labels: Sequence[Any] = (), value: float = 0.0) -> None:
        with self._lock:
            k = self._key(labels)
            st = self._series.get(k)
            if st is None:
                st = self._series[k] = [[0] * len(self.buckets), 0.0, 0]
            for i, b in enumerate(self.buckets):
                if value <= b:
                    st[0][i] += 1
            st[1] += value
            st[2] += 1

    def samples(self) -> List[Sample]:
        out: List[Sample] = []
        with self._lock:
            for k, (counts, total, n) in self._series.items():
                base = dict(zip(self.labelnames, k))
                for b, c in zip(self.buckets, counts):
                    out.append((self.name + '_bucket', {**base, 'le': _fmt(b)}, c))
                out.append((self.name + '_bucket', {**base, 'le': '+Inf'}, n))
                out.append((self.name + '_sum', base, total))
                out.append((self.name + '_count', base, n))
        return out


Collected = Tuple[str, str, str, List[Sample]]      # name, type, help, samples


class Registry:
    def __init__(self):
        self._families: Dict[str, _Family] = {}
        self._collectors: List[Callable[[], Iterable[Collected]]] = []
        self._dropped: Dict[str, int] = {}
        self._lock = threading.Lock()

    def register(self, fam: _Family) -> None:
        with self._lock:
            self._families[fam.name] = fam

    def family(self, name: str) -> Optional[_Family]:
        return self._families.get(name)

    def add_collector(self, fn: Callable[[], Iterable[Collected]]) -> None:
        self._collectors.append(fn)

    @staticmethod
    def max_series() -> int:
        return S.max_series()

    def dropped(self, name: str) -> None:
        self._dropped[name] = self._dropped.get(name, 0) + 1

    def reset(self) -> None:
        for f in self._families.values():
            f.reset()
        self._dropped.clear()

    def collect(self) -> List[Collected]:
        """Every family as (name, type, help, samples): the registered ones, then collected ones."""
        out: List[Collected] = [(f.name, f.kind, f.help, f.samples()) for f in self._families.values()]
        out.append(('sajha_metrics_series_dropped_total', 'counter',
                    'Label sets folded into _other because a family reached observability.metrics.max_series.',
                    [('sajha_metrics_series_dropped_total', {'family': k}, float(v))
                     for k, v in self._dropped.items()]))
        for fn in self._collectors:
            try:
                out.extend(fn())
            except Exception as e:
                logger.debug(f'metrics collector {getattr(fn, "__name__", fn)} failed: {e}')
        return out


# ── exposition ──────────────────────────────────────────────────────

CONTENT_TYPE = 'text/plain; version=0.0.4; charset=utf-8'


def _fmt(v: float) -> str:
    if v is None:
        return 'NaN'
    if isinstance(v, float):
        if math.isinf(v):
            return '+Inf' if v > 0 else '-Inf'
        if math.isnan(v):
            return 'NaN'
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def _esc_label(v: str) -> str:
    return str(v).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def _esc_help(v: str) -> str:
    return str(v).replace('\\', '\\\\').replace('\n', '\\n')


def render(families: Iterable[Collected]) -> str:
    """The Prometheus text exposition format (one HELP/TYPE per family, merged by name)."""
    merged: Dict[str, List] = {}
    order: List[str] = []
    for name, kind, help_, samples in families:
        if name not in merged:
            merged[name] = [kind, help_, []]
            order.append(name)
        merged[name][2].extend(samples)
    lines: List[str] = []
    for name in order:
        kind, help_, samples = merged[name]
        lines.append(f'# HELP {name} {_esc_help(help_)}')
        lines.append(f'# TYPE {name} {kind}')
        for sname, labels, value in samples:
            if labels:
                body = ','.join(f'{k}="{_esc_label(v)}"' for k, v in labels.items())
                lines.append(f'{sname}{{{body}}} {_fmt(float(value))}')
            else:
                lines.append(f'{sname} {_fmt(float(value))}')
    return '\n'.join(lines) + '\n'


# ── SAJHA's families ────────────────────────────────────────────────

REGISTRY = Registry()

HTTP_REQUESTS = Counter(REGISTRY, 'sajha_http_requests_total', 'HTTP requests by route template, method and status.',
                        ('method', 'route', 'status'))
HTTP_LATENCY = Histogram(REGISTRY, 'sajha_http_request_duration_seconds', 'HTTP request latency in seconds.',
                         ('method', 'route'))
MCP_REQUESTS = Counter(REGISTRY, 'sajha_mcp_requests_total',
                       'MCP JSON-RPC requests by era (modern = 2026-07-28, legacy = 2025-11-25 and earlier), '
                       'method and outcome.', ('era', 'method', 'outcome'))
MCP_LATENCY = Histogram(REGISTRY, 'sajha_mcp_request_duration_seconds', 'MCP request latency in seconds.',
                        ('era', 'method'))
TOOL_CALLS = Counter(REGISTRY, 'sajha_tool_calls_total', 'Tool calls by tool, group and outcome.',
                     ('tool', 'group', 'outcome'))
TOOL_LATENCY = Histogram(REGISTRY, 'sajha_tool_call_duration_seconds', 'Tool call latency in seconds.',
                         ('tool', 'group'))
TOOL_CACHE_HITS = Counter(REGISTRY, 'sajha_tool_cache_hits_total', 'Tool calls answered from the tool cache.',
                          ('tool', 'group'))
LLM_CALLS = Counter(REGISTRY, 'sajha_llm_calls_total', 'LLM gateway calls by provider, model and outcome.',
                    ('provider', 'model', 'outcome'))
LLM_LATENCY = Histogram(REGISTRY, 'sajha_llm_call_duration_seconds', 'LLM call latency in seconds.',
                        ('provider', 'model'))
LLM_TOKENS = Counter(REGISTRY, 'sajha_llm_tokens_total', 'LLM tokens by provider, model and direction.',
                     ('provider', 'model', 'direction'))
LLM_COST = Counter(REGISTRY, 'sajha_llm_cost_usd_total', 'LLM spend in US dollars by provider and model.',
                   ('provider', 'model'))
ASK_RUNS = Counter(REGISTRY, 'sajha_ask_runs_total', 'Ask SAJHA runs by what stopped them.', ('stopped_by',))
AUTH_FAILURES = Counter(REGISTRY, 'sajha_auth_failures_total', 'Failed authentications by method.', ('method',))
AUTH_LOCKOUTS = Counter(REGISTRY, 'sajha_auth_lockouts_total', 'Accounts locked after repeated failed sign-ins.')
SANDBOX_RUNS = Counter(REGISTRY, 'sajha_sandbox_runs_total', 'Sandbox runs by backend and outcome.',
                       ('backend', 'outcome'))
SANDBOX_LATENCY = Histogram(REGISTRY, 'sajha_sandbox_run_duration_seconds', 'Sandbox run duration in seconds.',
                            ('backend',))
ALERTS_FIRED = Counter(REGISTRY, 'sajha_alerts_fired_total', 'In-process alert rules fired.', ('rule',))
USAGE_DROPPED = Counter(REGISTRY, 'sajha_usage_events_dropped_total',
                        'Usage-ledger rows dropped because the write queue was full.')


# ── collected families ──────────────────────────────────────────────

_START = time.time()


def _process_families() -> Iterable[Collected]:
    from sajha.core.config import get_settings
    out: List[Collected] = [('sajha_info', 'gauge', 'SAJHA build information (app.version).',
                             [('sajha_info', {'version': get_settings().app_version}, 1.0)])]
    t = os.times()
    out.append(('process_cpu_seconds_total', 'counter', 'User and system CPU time in seconds.',
                [('process_cpu_seconds_total', {}, t.user + t.system)]))
    out.append(('process_start_time_seconds', 'gauge', 'Process start time, seconds since the epoch.',
                [('process_start_time_seconds', {}, _START)]))
    rss = None
    try:
        with open('/proc/self/statm') as f:
            rss = int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except Exception:
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        except Exception:
            rss = None
    if rss is not None:
        out.append(('process_resident_memory_bytes', 'gauge', 'Resident memory in bytes.',
                    [('process_resident_memory_bytes', {}, float(rss))]))
    try:
        out.append(('process_open_fds', 'gauge', 'Open file descriptors.',
                    [('process_open_fds', {}, float(len(os.listdir('/proc/self/fd'))))]))
    except Exception:
        pass
    out.append(('process_threads', 'gauge', 'Live Python threads.',
                [('process_threads', {}, float(threading.active_count()))]))
    out.append(('python_gc_collections_total', 'counter', 'Garbage collections by generation.',
                [('python_gc_collections_total', {'generation': str(i)}, float(s.get('collections', 0)))
                 for i, s in enumerate(gc.get_stats())]))
    out.append(('python_info', 'gauge', 'Python interpreter.',
                [('python_info', {'implementation': platform.python_implementation(),
                                  'version': platform.python_version()}, 1.0)]))
    return out


def _cache_and_breaker_families() -> Iterable[Collected]:
    out: List[Collected] = []
    try:
        from sajha.core.cache import get_tool_cache
        st = get_tool_cache().stats()
        out.append(('sajha_tool_cache_entries', 'gauge', 'Entries in the tool output cache.',
                    [('sajha_tool_cache_entries', {}, float(st.get('size', st.get('entries', 0)) or 0))]))
        out.append(('sajha_tool_cache_requests_total', 'counter', 'Tool cache lookups by result.',
                    [('sajha_tool_cache_requests_total', {'result': 'hit'}, float(st.get('hits', 0))),
                     ('sajha_tool_cache_requests_total', {'result': 'miss'}, float(st.get('misses', 0)))]))
    except Exception:
        pass
    try:
        from sajha.core.circuit_breaker import get_circuit_registry
        samples = []
        for b in get_circuit_registry().all_status():
            for state in ('closed', 'open', 'half_open'):
                samples.append(('sajha_circuit_breaker_state', {'breaker': str(b.get('name', '')), 'state': state},
                                1.0 if str(b.get('state', '')).lower() == state else 0.0))
        out.append(('sajha_circuit_breaker_state', 'gauge',
                    'Circuit breaker state: 1 for the current state of each breaker.', samples))
    except Exception:
        pass
    return out


def _federation_families() -> Iterable[Collected]:
    """Upstream health, when sajha.federation exists and its manager runs (feature detection)."""
    try:
        from sajha.federation.manager import get_federation
    except Exception:
        return []
    fed = get_federation()
    if fed is None:
        return []
    try:
        status = fed.status()
    except Exception:
        return []
    up, calls, fails = [], [], []
    for s in status:
        uid = str(s.get('id', ''))
        up.append(('sajha_federation_upstream_up', {'upstream': uid, 'state': str(s.get('state', ''))},
                   1.0 if s.get('state') == 'connected' else 0.0))
        calls.append(('sajha_federation_upstream_calls_total', {'upstream': uid}, float(s.get('calls') or 0)))
        fails.append(('sajha_federation_upstream_failures_total', {'upstream': uid}, float(s.get('failures') or 0)))
    return [('sajha_federation_upstream_up', 'gauge', 'Federated upstream connected (1) or not (0), with its state.', up),
            ('sajha_federation_upstream_calls_total', 'counter', 'Calls forwarded to each federated upstream.', calls),
            ('sajha_federation_upstream_failures_total', 'counter', 'Failed calls to each federated upstream.', fails)]


REGISTRY.add_collector(_process_families)
REGISTRY.add_collector(_cache_and_breaker_families)
REGISTRY.add_collector(_federation_families)


# ── multi-worker merge ──────────────────────────────────────────────

_SNAP_PREFIX = 'obs:metrics:'


def _shared_store():
    mode = S.get_str('observability.metrics.multiworker', 'auto').strip().lower()
    if mode in ('off', 'false', 'no', 'none'):
        return None
    try:
        from sajha.core.state import get_state_store
        store = get_state_store()
        return store if getattr(store, 'shared', False) else None
    except Exception:
        return None


def _worker_id() -> str:
    try:
        from sajha.core.state import WORKER_ID
        return WORKER_ID
    except Exception:
        return f'{platform.node()}:{os.getpid()}'


def publish_snapshot() -> bool:
    """Write this worker's families to the shared state store (multi-worker scrapes)."""
    store = _shared_store()
    if store is None:
        return False
    interval = max(1.0, S.get_float('observability.metrics.publish_interval_seconds', 15.0))
    fams = [[n, k, h, [[sn, lb, v] for sn, lb, v in smp]] for n, k, h, smp in REGISTRY.collect()]
    store.set(_SNAP_PREFIX + _worker_id(), {'at': time.time(), 'families': fams}, ttl=interval * 3)
    return True


def exposition() -> str:
    """The text /metrics serves: this worker, plus other live workers' snapshots when shared."""
    own = REGISTRY.collect()
    store = _shared_store()
    if store is None:
        return render(own)
    me = _worker_id()
    try:
        publish_snapshot()
    except Exception as e:
        logger.debug(f'metrics snapshot publish failed: {e}')

    def tag(fams, wid):
        return [(n, k, h, [(sn, {**lb, 'worker': wid}, v) for sn, lb, v in smp]) for n, k, h, smp in fams]

    merged = tag(own, me)
    try:
        for key, snap in store.scan(_SNAP_PREFIX):
            wid = key[len(_SNAP_PREFIX):] if key.startswith(_SNAP_PREFIX) else key.rsplit(':', 3)[-1]
            if wid == me or not isinstance(snap, dict):
                continue
            fams = [(f[0], f[1], f[2], [(s[0], dict(s[1]), float(s[2])) for s in f[3]])
                    for f in snap.get('families') or []]
            merged.extend(tag(fams, wid))
    except Exception as e:
        logger.debug(f'metrics snapshot merge failed: {e}')
    return render(merged)


_publisher: Optional[threading.Thread] = None
_publisher_stop = threading.Event()


def start_publisher() -> bool:
    global _publisher
    if _publisher is not None or _shared_store() is None:
        return False
    interval = max(1.0, S.get_float('observability.metrics.publish_interval_seconds', 15.0))

    def loop():
        while not _publisher_stop.wait(interval):
            try:
                publish_snapshot()
            except Exception as e:
                logger.debug(f'metrics snapshot publish failed: {e}')

    _publisher = threading.Thread(target=loop, name='sajha-metrics-publisher', daemon=True)
    _publisher.start()
    return True


def stop_publisher() -> None:
    global _publisher
    _publisher_stop.set()
    _publisher = None


# ── instrumentation points ──────────────────────────────────────────

_listeners: List[Callable[[str, Dict[str, Any]], None]] = []


def add_listener(fn: Callable[[str, Dict[str, Any]], None]) -> None:
    """fn(kind, event): the alert window subscribes here."""
    if fn not in _listeners:
        _listeners.append(fn)


def _emit(kind: str, event: Dict[str, Any]) -> None:
    for fn in list(_listeners):
        try:
            fn(kind, event)
        except Exception as e:
            logger.debug(f'observability listener failed: {e}')


def tool_group(name: str) -> str:
    """GLOSSARY "Tool group": the text before the first '_'."""
    return name.split('_')[0] if '_' in name else name


def _tool_labels(name: str) -> Tuple[str, str]:
    group = tool_group(name)
    mode = S.tool_label_mode()
    if mode == 'group':
        return group, group
    if mode == 'none':
        return '_all', group
    return name, group


def _otel(name: str, kind: str, value: float, attrs: Dict[str, Any]) -> None:
    try:
        from sajha.observability import tracing
        tracing.record_metric(name, kind, value, attrs)
    except Exception:
        pass


def _guard(fn):
    def wrapper(*a, **kw):
        if not S.metrics_enabled() and fn.__name__ not in ('record_tool', 'record_llm'):
            return None
        try:
            return fn(*a, **kw)
        except Exception as e:
            logger.debug(f'{fn.__name__} failed: {e}', exc_info=True)
            return None
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_guard
def record_http(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.inc((method, route, str(status)))
    HTTP_LATENCY.observe((method, route), seconds)
    _otel('sajha.http.requests', 'counter', 1, {'http.request.method': method, 'http.route': route,
                                                'http.response.status_code': status})
    _emit('http', {'status': int(status), 'ms': seconds * 1000})


@_guard
def record_mcp(era: str, method: str, outcome: str, seconds: float) -> None:
    MCP_REQUESTS.inc((era, method, outcome))
    MCP_LATENCY.observe((era, method), seconds)
    _otel('sajha.mcp.requests', 'counter', 1, {'mcp.era': era, 'mcp.method': method, 'mcp.outcome': outcome})


@_guard
def record_tool(name: str, outcome: str, seconds: float, error: str = '') -> None:
    """One tool call: outcome ok | error | cache_hit | circuit_open | input_required."""
    from sajha.observability import caller as C
    who = C.current()
    if S.metrics_enabled():
        tool, group = _tool_labels(name)
        TOOL_CALLS.inc((tool, group, outcome))
        if outcome == 'cache_hit':
            TOOL_CACHE_HITS.inc((tool, group))
        if outcome in ('ok', 'error', 'cache_hit'):
            TOOL_LATENCY.observe((tool, group), seconds)
        _otel('sajha.tool.calls', 'counter', 1, {'sajha.tool.group': group, 'sajha.tool.outcome': outcome})
        _otel('sajha.tool.duration', 'histogram', seconds, {'sajha.tool.group': group})
    _emit('tool', {'tool': name, 'outcome': outcome, 'ms': seconds * 1000})
    if outcome in ('ok', 'error', 'cache_hit'):
        try:
            from sajha.observability import get_collector
            col = get_collector()
            if col is not None:
                col.record_execution(name, seconds * 1000, outcome != 'error', error)
        except Exception:
            pass
    if outcome != 'input_required':
        from sajha.observability import usage
        usage.record(kind='tool', caller=who, tool=name, tool_group=tool_group(name), outcome=outcome,
                     latency_ms=seconds * 1000)


@_guard
def record_llm(provider: str, model: str, outcome: str, seconds: float, input_tokens: int = 0,
               output_tokens: int = 0, cost_usd: float = 0.0, ctx: Any = None) -> None:
    """One gateway model call (a cache hit is a call that cost nothing)."""
    from sajha.observability import caller as C
    who = C.from_request_context(ctx)
    if S.metrics_enabled():
        LLM_CALLS.inc((provider, model, outcome))
        if outcome in ('ok', 'cache_hit'):
            LLM_LATENCY.observe((provider, model), seconds)
        if input_tokens:
            LLM_TOKENS.inc((provider, model, 'input'), input_tokens)
        if output_tokens:
            LLM_TOKENS.inc((provider, model, 'output'), output_tokens)
        if cost_usd:
            LLM_COST.inc((provider, model), cost_usd)
        attrs = {'llm.provider': provider, 'llm.model': model}
        _otel('sajha.llm.calls', 'counter', 1, {**attrs, 'llm.outcome': outcome})
        _otel('sajha.llm.tokens', 'counter', input_tokens + output_tokens, attrs)
        _otel('sajha.llm.cost_usd', 'counter', cost_usd, attrs)
    _emit('llm', {'outcome': outcome, 'tokens': input_tokens + output_tokens, 'cost': cost_usd,
                  'ms': seconds * 1000})
    from sajha.observability import usage
    usage.record(kind='llm', caller=who, provider=provider, model=model, outcome=outcome,
                 latency_ms=seconds * 1000, input_tokens=input_tokens, output_tokens=output_tokens,
                 cost_usd=cost_usd)


@_guard
def record_ask(stopped_by: str) -> None:
    ASK_RUNS.inc((stopped_by or 'unknown',))


@_guard
def record_auth_failure(method: str) -> None:
    AUTH_FAILURES.inc((method,))
    _emit('auth', {'method': method})


@_guard
def record_lockout() -> None:
    AUTH_LOCKOUTS.inc(())


@_guard
def record_sandbox_run(result: Any) -> None:
    """A sajha.sandbox SandboxResult."""
    backend = str(getattr(result, 'backend', '') or 'unknown')
    if getattr(result, 'timed_out', False):
        outcome = 'timeout'
    elif getattr(result, 'output_truncated', False):
        outcome = 'output_limit'
    elif getattr(result, 'runner_error', None):
        outcome = 'runner_error'
    elif getattr(result, 'exit_code', 1) == 0:
        outcome = 'ok'
    else:
        outcome = 'error'
    SANDBOX_RUNS.inc((backend, outcome))
    SANDBOX_LATENCY.observe((backend,), float(getattr(result, 'duration_ms', 0.0) or 0.0) / 1000.0)


@_guard
def record_alert(rule: str) -> None:
    ALERTS_FIRED.inc((rule,))
