"""
SAJHA MCP Server — the usage ledger behind the Usage & cost dashboard.

One row per tool call and per LLM call in ``obs_usage_events`` (SAJHA's database; the
table is defined in ``db/scripts/<dialect>/schema.sql``, and is created here only on SQLite). Rows are
queued and written in batches by a daemon thread, so the database is never on a call's
path; the queue is bounded and drops (``sajha_usage_events_dropped_total``) rather than
grow. :func:`report` answers every figure the dashboard shows, :func:`csv_rows` its CSV
export. Design: docs/architecture/Observability.md, section 4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import (BigInteger, Column, DateTime, Float, Index, Integer, MetaData, String, Table, and_,
                        delete, select)

from sajha.observability import settings as S

logger = logging.getLogger(__name__)

metadata = MetaData()

usage_events = Table(
    'obs_usage_events', metadata,
    Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True),
    Column('ts', DateTime, nullable=False),
    Column('day', String(10), nullable=False),
    Column('kind', String(8), nullable=False),            # tool | llm
    Column('user_id', String(200)),
    Column('api_key', String(200)),
    Column('roles', String(500)),                         # ",admin,user," for LIKE filtering
    Column('auth_type', String(20)),
    Column('tool', String(255)),
    Column('tool_group', String(100)),
    Column('provider', String(100)),
    Column('model', String(200)),
    Column('outcome', String(40)),
    Column('latency_ms', Float),
    Column('input_tokens', Integer),
    Column('output_tokens', Integer),
    Column('cost_usd', Float),
    Index('ix_obs_usage_day_kind', 'day', 'kind'),
    Index('ix_obs_usage_user_day', 'user_id', 'day'),
    Index('ix_obs_usage_ts', 'ts'),
)

_queue: Optional[queue.Queue] = None
_writer: Optional[threading.Thread] = None
_stop = threading.Event()
_created_for = None
_lock = threading.Lock()
_last_purge = 0.0
_warned_missing = False


def enabled() -> bool:
    return S.get_bool('observability.usage.enabled', True)


def _engine():
    try:
        from sajha.db.engine import get_engine
        return get_engine()
    except Exception:
        return None


def ensure_table(engine=None) -> bool:
    global _created_for, _warned_missing
    engine = engine or _engine()
    if engine is None:
        return False
    if _created_for is engine:
        return True
    with _lock:
        if _created_for is not engine:
            if engine.dialect.name == 'sqlite':
                metadata.create_all(engine, tables=[usage_events], checkfirst=True)
            else:
                from sqlalchemy import inspect
                if not inspect(engine).has_table('obs_usage_events'):
                    # No DDL outside SQLite: the table comes from db/scripts/<dialect>/schema.sql.
                    if _warned_missing:
                        return False
                    _warned_missing = True
                    from sajha.db.schema import apply_command
                    logger.warning('Usage ledger off: table obs_usage_events is missing; create it from the '
                                   f'schema file:  {apply_command(engine)}  (docs/getting-started/Database Setup.md)')
                    return False
            _created_for = engine
    return True


def _q() -> queue.Queue:
    global _queue
    if _queue is None:
        _queue = queue.Queue(maxsize=max(100, S.get_int('observability.usage.queue_size', 10000)))
    return _queue


def record(kind: str, caller: Any, **fields: Any) -> None:
    """Queue one row (never blocks, never raises)."""
    if not enabled():
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    roles = tuple(getattr(caller, 'roles', ()) or ())
    row = {'ts': now, 'day': now.strftime('%Y-%m-%d'), 'kind': kind,
           'user_id': str(getattr(caller, 'user_id', '') or 'anonymous')[:200],
           'api_key': (str(getattr(caller, 'api_key', '') or '') or None),
           'roles': (',' + ','.join(roles) + ',') if roles else None,
           'auth_type': str(getattr(caller, 'auth_type', '') or '') or None,
           'tool': None, 'tool_group': None, 'provider': None, 'model': None, 'outcome': None,
           'latency_ms': None, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
    row.update({k: v for k, v in fields.items() if k in row})
    try:
        _q().put_nowait(row)
    except queue.Full:
        from sajha.observability.metrics import USAGE_DROPPED
        USAGE_DROPPED.inc(())
        return
    _ensure_writer()


def _ensure_writer() -> None:
    global _writer
    if _writer is not None and _writer.is_alive():
        return
    with _lock:
        if _writer is None or not _writer.is_alive():
            _stop.clear()
            _writer = threading.Thread(target=_loop, name='sajha-usage-writer', daemon=True)
            _writer.start()


def _drain(limit: int = 200) -> List[Dict[str, Any]]:
    q, rows = _q(), []
    while len(rows) < limit:
        try:
            rows.append(q.get_nowait())
        except queue.Empty:
            break
    return rows


def flush() -> int:
    """Write everything queued now (tests, shutdown). Returns rows written."""
    total = 0
    engine = _engine()
    while True:
        rows = _drain(500)
        if not rows:
            return total
        if engine is None or not ensure_table(engine):
            return total
        try:
            with engine.begin() as conn:
                conn.execute(usage_events.insert(), rows)
            total += len(rows)
        except Exception as e:
            logger.warning(f'usage ledger: write of {len(rows)} rows failed: {e}')
            return total


def _purge(engine) -> None:
    global _last_purge
    if time.time() - _last_purge < 86400:
        return
    _last_purge = time.time()
    days = S.get_int('observability.usage.retention_days', 90)
    if days <= 0:
        return
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    try:
        with engine.begin() as conn:
            n = conn.execute(delete(usage_events).where(usage_events.c.ts < cutoff)).rowcount
        if n:
            logger.info(f'usage ledger: purged {n} rows older than {days} days')
    except Exception as e:
        logger.debug(f'usage ledger purge failed: {e}')


def _loop() -> None:
    while not _stop.is_set():
        _stop.wait(1.0)
        try:
            if flush():
                pass
            engine = _engine()
            if engine is not None and ensure_table(engine):
                _purge(engine)
        except Exception as e:
            logger.debug(f'usage writer: {e}')


def shutdown() -> None:
    _stop.set()
    try:
        flush()
    except Exception:
        pass


# ── queries ─────────────────────────────────────────────────────────

def _day(s: Optional[str], default: date) -> date:
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d').date() if s else default
    except ValueError:
        return default


def parse_range(since: Optional[str], until: Optional[str]) -> tuple:
    today = datetime.now(timezone.utc).date()
    u = _day(until, today)
    s = _day(since, u - timedelta(days=6))
    if s > u:
        s, u = u, s
    return s, u


def _rows(since: date, until: date, filters: Dict[str, str], limit: int) -> List[Dict[str, Any]]:
    engine = _engine()
    if engine is None or not ensure_table(engine):
        return []
    c = usage_events.c
    cond = [c.day >= since.isoformat(), c.day <= until.isoformat()]
    for key, col in (('user', c.user_id), ('api_key', c.api_key), ('provider', c.provider),
                     ('model', c.model), ('tool', c.tool)):
        if filters.get(key):
            cond.append(col == filters[key])
    if filters.get('role'):
        cond.append(c.roles.like(f'%,{filters["role"]},%'))
    q = select(usage_events).where(and_(*cond)).order_by(c.ts.desc()).limit(limit)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _blank() -> Dict[str, Any]:
    return {'tool_calls': 0, 'tool_errors': 0, 'llm_calls': 0, 'llm_errors': 0, 'input_tokens': 0,
            'output_tokens': 0, 'cost_usd': 0.0, '_lat': []}


def _add(acc: Dict[str, Any], r: Dict[str, Any]) -> None:
    if r['kind'] == 'tool':
        acc['tool_calls'] += 1
        if r['outcome'] in ('error', 'circuit_open'):
            acc['tool_errors'] += 1
        if r['latency_ms'] is not None:
            acc['_lat'].append(float(r['latency_ms']))
    else:
        acc['llm_calls'] += 1
        if r['outcome'] not in ('ok', 'cache_hit'):
            acc['llm_errors'] += 1
        acc['input_tokens'] += int(r['input_tokens'] or 0)
        acc['output_tokens'] += int(r['output_tokens'] or 0)
        acc['cost_usd'] += float(r['cost_usd'] or 0.0)


def _finish(key: str, acc: Dict[str, Any], name: str = 'key') -> Dict[str, Any]:
    lat = acc.pop('_lat')
    out = {name: key, **acc}
    out['cost_usd'] = round(out['cost_usd'], 6)
    out['tokens'] = out['input_tokens'] + out['output_tokens']
    out['error_rate'] = round(acc['tool_errors'] / acc['tool_calls'], 4) if acc['tool_calls'] else 0.0
    out['p50_ms'] = round(percentile(lat, 50), 1)
    out['p95_ms'] = round(percentile(lat, 95), 1)
    out['p99_ms'] = round(percentile(lat, 99), 1)
    return out


def _table(groups: Dict[str, Dict[str, Any]], sort: str = 'cost_usd') -> List[Dict[str, Any]]:
    rows = [_finish(k, v) for k, v in groups.items()]
    rows.sort(key=lambda x: (-x[sort], -x['tool_calls'], -x['llm_calls'], x['key']))
    return rows


def report(since: Optional[str] = None, until: Optional[str] = None,
           filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Every figure the dashboard shows, for [since, until] (UTC days, inclusive)."""
    s, u = parse_range(since, until)
    filters = {k: v for k, v in (filters or {}).items() if v}
    limit = max(1000, S.get_int('observability.usage.max_rows_for_percentiles', 200000))
    rows = _rows(s, u, filters, limit)
    total = _blank()
    by: Dict[str, Dict[str, Dict[str, Any]]] = {d: defaultdict(_blank) for d in
                                                ('user', 'api_key', 'role', 'model', 'tool', 'day')}
    cost_by_day_provider: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        _add(total, r)
        _add(by['day'][r['day']], r)
        _add(by['user'][r['user_id'] or 'anonymous'], r)
        if r['api_key']:
            _add(by['api_key'][r['api_key']], r)
        for role in (r['roles'] or '').strip(',').split(','):
            if role:
                _add(by['role'][role], r)
        if r['kind'] == 'llm':
            _add(by['model'][f"{r['provider']}/{r['model']}"], r)
            cost_by_day_provider[r['day']][r['provider'] or '?'] += float(r['cost_usd'] or 0.0)
        else:
            _add(by['tool'][r['tool'] or '?'], r)
    days = []
    d = s
    while d <= u:
        days.append(d.isoformat())
        d += timedelta(days=1)
    day_rows = {k: _finish(k, v, 'day') for k, v in by['day'].items()}
    series = [day_rows.get(dy) or _finish(dy, _blank(), 'day') for dy in days]
    providers = sorted({p for v in cost_by_day_provider.values() for p in v})
    return {
        'since': s.isoformat(), 'until': u.isoformat(), 'filters': filters,
        'rows': len(rows), 'sampled': len(rows) >= limit,
        'totals': _finish('total', total),
        'days': series,
        'cost_by_provider': {'providers': providers,
                             'series': {p: [round(cost_by_day_provider.get(dy, {}).get(p, 0.0), 6) for dy in days]
                                        for p in providers}},
        'by_user': _table(by['user']), 'by_api_key': _table(by['api_key']), 'by_role': _table(by['role']),
        'by_model': _table(by['model']), 'by_tool': _table(by['tool'], 'tool_calls'),
    }


DIMENSIONS = ('user', 'api_key', 'role', 'model', 'tool', 'day')
CSV_COLUMNS = ['key', 'tool_calls', 'tool_errors', 'error_rate', 'p50_ms', 'p95_ms', 'p99_ms', 'llm_calls',
               'llm_errors', 'input_tokens', 'output_tokens', 'tokens', 'cost_usd']


def csv_rows(rep: Dict[str, Any], dimension: str) -> Iterable[List[Any]]:
    rows = rep['days'] if dimension == 'day' else rep[f'by_{dimension}']
    yield [dimension] + CSV_COLUMNS[1:]
    for r in rows:
        yield [r.get('day', r.get('key'))] + [r[c] for c in CSV_COLUMNS[1:]]


def budgets(user_ids: Iterable[str] = (), roles: Iterable[str] = ()) -> Dict[str, Any]:
    """Today's tokens against ai.budgets, from the LLM factory's token tracker (the enforcing counters)."""
    try:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
    except Exception:
        gw = None
    if gw is None:
        return {'enabled': False, 'available': False, 'users': [], 'roles': []}
    bs = gw.settings.budgets
    tracker = gw.tracker
    users = []
    for uid in sorted(set(user_ids)):
        used = tracker.daily_user_tokens(uid)
        limit = bs.per_user_daily_tokens or None
        users.append({'key': uid, 'used': used, 'limit': limit,
                      'share': round(used / limit, 4) if limit else None})
    role_rows = []
    for r in sorted(set(roles) | set((bs.per_role_daily_tokens or {}).keys())):
        used = tracker.daily_role_tokens(r)
        limit = (bs.per_role_daily_tokens or {}).get(r)
        role_rows.append({'key': r, 'used': used, 'limit': limit,
                          'share': round(used / limit, 4) if limit else None})
    return {'enabled': bool(bs.enabled), 'available': True, 'users': users, 'roles': role_rows,
            'per_user_daily_tokens': bs.per_user_daily_tokens or None}
