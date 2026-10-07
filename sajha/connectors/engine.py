"""
SAJHA MCP Server — Data Connectors: running list / describe / query / view for a connection.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Everything a generated tool does with a SQL database happens here: open a session (pooled,
read-only, time-limited; sajha/connectors/drivers/), check caller SQL (guard.py), bind
parameters (sqltext.py), fetch under the row, byte and time caps, mask (masking.py), and
record the call (audit record and ``sajha_connector_*`` metrics). Vector and search kinds are
in vector.py. Design: docs/architecture/Data Connectors.md, sections 4 to 8 and 11.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sajha.connectors import catalog, guard, masking, pool, settings, sqltext
from sajha.connectors.drivers import ConnectorError, DriverMissing, QueryTimeout, get_driver, json_schema_for
from sajha.connectors.model import Connection, View

logger = logging.getLogger(__name__)

__all__ = ['ConnectorError', 'DriverMissing', 'QueryTimeout', 'list_tables', 'describe_table', 'query',
           'run_view', 'session', 'view_args', 'view_input_schema']


# ── metrics ─────────────────────────────────────────────────────────────

def _families():
    from sajha.observability import metrics as M
    fam = getattr(_families, 'cache', None)
    if fam is None or M.REGISTRY.family('sajha_connector_queries_total') is not fam[0]:
        fam = (M.REGISTRY.family('sajha_connector_queries_total') or
               M.Counter(M.REGISTRY, 'sajha_connector_queries_total',
                         'Data-connector calls by connection, operation and outcome.', ('connection', 'op', 'outcome')),
               M.REGISTRY.family('sajha_connector_rows_total') or
               M.Counter(M.REGISTRY, 'sajha_connector_rows_total', 'Rows returned by data connectors.',
                         ('connection',)),
               M.REGISTRY.family('sajha_connector_query_duration_seconds') or
               M.Histogram(M.REGISTRY, 'sajha_connector_query_duration_seconds',
                           'Data-connector call duration in seconds.', ('connection', 'op')))
        _families.cache = fam
    return fam


def _metric(conn_id: str, op: str, outcome: str, seconds: float, rows: int = 0) -> None:
    try:
        from sajha.observability import settings as S
        if not S.metrics_enabled():
            return
        calls, nrows, latency = _families()
        calls.inc((conn_id, op, outcome))
        if rows:
            nrows.inc((conn_id,), rows)
        latency.observe((conn_id, op), seconds)
    except Exception as e:
        logger.debug(f'connector metrics: {e}')


def _audit(conn: Connection, event: str, tool: str, op: str, outcome: str, details: Dict[str, Any]) -> None:
    try:
        from sajha import audit
        from sajha.observability.caller import current
        c = current()
        audit.record(event, actor={'user': getattr(c, 'user_id', '') or 'anonymous',
                                   'api_key': getattr(c, 'api_key', '') or '',
                                   'roles': list(getattr(c, 'roles', ()) or ()),
                                   'auth': getattr(c, 'auth_type', '') or ''},
                     resource={'type': 'data_connection', 'id': conn.id}, outcome=outcome,
                     details={'tool': tool, 'op': op, 'kind': conn.kind, **details})
    except Exception as e:
        logger.debug(f'connector audit: {e}')


def _sql_details(sql: str) -> Dict[str, Any]:
    d: Dict[str, Any] = {'sql_sha256': hashlib.sha256((sql or '').encode('utf-8', 'replace')).hexdigest()}
    if settings.audit_sql():
        d['sql'] = (sql or '')[:4000]
    return d


# ── values ──────────────────────────────────────────────────────────────

def jsonable(v: Any, _depth: int = 0) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f'<{len(bytes(v))} bytes>'
    if isinstance(v, uuid.UUID):
        return str(v)
    if _depth < 8 and isinstance(v, (list, tuple, set)):
        return [jsonable(x, _depth + 1) for x in v]
    if _depth < 8 and isinstance(v, dict):
        return {str(k): jsonable(x, _depth + 1) for k, x in v.items()}
    return str(v)


def _redact(text: str, extra: List[str]) -> str:
    try:
        from sajha.federation.security import redact
        return redact(text, [e for e in extra if e])
    except Exception:
        return text


# ── sessions ────────────────────────────────────────────────────────────

def _token(conn: Connection) -> Optional[str]:
    if not conn.per_user:
        return None
    try:
        from sajha.accounts.injection import current_token
        tok = current_token(conn.auth['provider'])
    except ImportError:
        raise ConnectorError('per-user credentials need the connected-accounts feature (sajha.accounts)') from None
    except RuntimeError as e:
        raise ConnectorError(str(e)) from None
    return getattr(tok, 'access_token', None) or str(tok)


@contextmanager
def session(conn: Connection) -> Iterator[Tuple[Any, Any, Dict[str, Any]]]:
    """(driver, DB-API connection, state). Set ``state['broken']`` to discard the connection."""
    drv = get_driver(conn.kind)
    used: List[str] = []

    def secret(name: str) -> str:
        ref = conn.secrets.get(name)
        if not ref:
            return ''
        from sajha.federation.security import secrets
        value = secrets().resolve(ref) or ''
        if not value:
            raise ConnectorError(f'{conn.id}: secrets.{name}: the reference {ref} resolves to nothing')
        used.append(value)
        return value

    token = _token(conn)
    if token:
        used.append(token)
    key = (conn.id, conn.fingerprint())
    dbc = None if conn.per_user else pool.take(key)
    if dbc is None:
        try:
            dbc = drv.connect(conn, secret, token)
        except (DriverMissing, ConnectorError):
            raise
        except Exception as e:
            raise ConnectorError(_redact(f'{conn.id}: cannot connect: {e.__class__.__name__}: {e}', used)) from None
        pool.created(dbc)
        try:
            drv.prepare(dbc, conn)
        except Exception as e:
            pool.discard(dbc, drv.close)
            raise ConnectorError(_redact(f'{conn.id}: session set-up failed: {e.__class__.__name__}: {e}',
                                         used)) from None
    state: Dict[str, Any] = {'broken': False, 'secrets': used}
    try:
        yield drv, dbc, state
    except BaseException:
        raise
    finally:
        if state['broken'] or conn.per_user:
            pool.discard(dbc, drv.close)
        else:
            pool.give(key, dbc, drv.close)


def _unique(names: List[str]) -> List[str]:
    out, seen = [], {}
    for n in names:
        n = str(n)
        if n in seen:
            seen[n] += 1
            out.append(f'{n}_{seen[n]}')
        else:
            seen[n] = 1
            out.append(n)
    return out


def _type_name(code: Any) -> str:
    if code is None or isinstance(code, int):
        return ''
    name = getattr(code, '__name__', None) or getattr(code, 'name', None)
    return str(name if name else code)[:60]


def _execute(conn: Connection, drv, dbc, state: Dict[str, Any], sql: str, params: Any, max_rows: int,
             max_bytes: int) -> Dict[str, Any]:
    fired = threading.Event()

    def watchdog():
        fired.set()
        try:
            drv.cancel(dbc)
        except Exception as e:
            logger.debug(f'connector cancel: {e}')

    timer = threading.Timer(conn.timeout_seconds + 0.5, watchdog)
    timer.daemon = True
    cur = None
    try:
        drv.begin(dbc, conn)
        cur = drv.cursor(dbc)
        timer.start()
        drv.execute(cur, sql, params, conn)
        desc = cur.description or []
        base = [str(d[0]) for d in desc]
        names = _unique(base)
        types = [_type_name(d[1]) if len(d) > 1 else '' for d in desc]
        rows: List[Dict[str, Any]] = []
        size, truncated, reason = 2, False, ''
        while desc:
            want = max_rows + 1 - len(rows)
            if want <= 0:
                break
            batch = cur.fetchmany(min(500, want))
            if not batch:
                break
            for r in batch:
                row = {n: jsonable(v) for n, v in zip(names, r)}
                size += len(json.dumps(row, default=str, separators=(',', ':'))) + 1
                if size > max_bytes:
                    truncated, reason = True, 'bytes'
                    break
                rows.append(row)
            if truncated:
                break
        if len(rows) > max_rows:
            rows, truncated, reason = rows[:max_rows], True, 'rows'
        return {'columns': [{'name': n, 'type': t} for n, t in zip(names, types)], 'base_names': base,
                'rows': rows, 'truncated': truncated, 'truncated_reason': reason}
    except (guard.GuardError, ConnectorError):
        raise
    except Exception as e:
        if fired.is_set() or drv.is_timeout(e):
            state['broken'] = True
            raise QueryTimeout(f'{conn.id}: the query timed out after {conn.timeout_seconds}s and was cancelled') \
                from None
        if e.__class__.__name__ in ('OperationalError', 'InterfaceError'):
            state['broken'] = True
        msg = str(e).strip().split('\n')[0][:800]
        raise ConnectorError(_redact(f'{conn.id}: {e.__class__.__name__}: {msg}', state.get('secrets') or [])) \
            from None
    finally:
        timer.cancel()
        if cur is not None:
            drv.close_cursor(cur)
        try:
            drv.end(dbc)
        except Exception:
            state['broken'] = True


# ── catalog ─────────────────────────────────────────────────────────────

def _require_sql(conn: Connection) -> None:
    if conn.family != 'sql':
        raise ConnectorError(f'{conn.id} is a {conn.kind} connection, not a SQL database')


def allowed_tables(conn: Connection, refresh: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
    def loader():
        with session(conn) as (drv, dbc, state):
            try:
                return drv.list_tables(dbc, conn)
            except (ConnectorError, DriverMissing):
                raise
            except Exception as e:
                state['broken'] = e.__class__.__name__ in ('OperationalError', 'InterfaceError')
                raise ConnectorError(_redact(f'{conn.id}: listing tables failed: {e.__class__.__name__}: {e}',
                                             state['secrets'])) from None
            finally:
                try:
                    drv.end(dbc)
                except Exception:
                    state['broken'] = True
    return catalog.tables(conn, loader, refresh)


def resolver(conn: Connection, allowed: List[Dict[str, Any]]):
    drv = get_driver(conn.kind)
    default = drv.default_schema_for(conn)
    cats = drv.catalog_names(conn)
    return lambda cat, schema, name: catalog.resolve_in(conn, allowed, default, cats, cat or '', schema or '',
                                                        name or '')


def resolve_table(conn: Connection, table: Any, allowed: List[Dict[str, Any]]) -> Tuple[str, str]:
    if not isinstance(table, str) or not table.strip():
        raise ConnectorError('table is required (schema.table or table)')
    text = table.strip()
    res = resolver(conn, allowed)
    hit = res('', '', text)                       # a table whose name contains a dot
    if hit is None and '.' in text:
        parts = [p.strip().strip('"`[]') for p in text.split('.')]
        if len(parts) == 2:
            hit = res('', parts[0], parts[1])
        elif len(parts) == 3:
            hit = res(parts[0], parts[1], parts[2])
    elif hit is None:
        hit = res('', '', text.strip('"`[]'))
    if hit is None:
        raise ConnectorError(f'table {text} is not available on connection {conn.id} '
                             f'(call {conn.id}__list_tables; qualify the name with its schema if it is ambiguous)')
    return hit


def table_detail(conn: Connection, schema: str, table: str, refresh: bool = False) -> Dict[str, Any]:
    def loader():
        with session(conn) as (drv, dbc, state):
            try:
                return drv.describe(dbc, conn, schema, table)
            except (ConnectorError, DriverMissing):
                raise
            except Exception as e:
                raise ConnectorError(_redact(f'{conn.id}: describing {schema}.{table} failed: '
                                             f'{e.__class__.__name__}: {e}', state['secrets'])) from None
            finally:
                try:
                    drv.end(dbc)
                except Exception:
                    state['broken'] = True
    return catalog.described(conn, schema, table, loader, refresh)


# ── operations ──────────────────────────────────────────────────────────

def _timed(conn: Connection, op: str, tool: str, fn, audit_details: Optional[Dict[str, Any]] = None):
    t0 = time.perf_counter()
    try:
        out = fn()
    except guard.GuardError as e:
        _metric(conn.id, op, 'rejected', time.perf_counter() - t0)
        _audit(conn, 'connector.rejected', tool, op, 'rejected', {**(audit_details or {}), 'reason': str(e)[:500]})
        raise
    except QueryTimeout:
        _metric(conn.id, op, 'timeout', time.perf_counter() - t0)
        _audit(conn, 'connector.query', tool, op, 'timeout', dict(audit_details or {}))
        raise
    except Exception as e:
        _metric(conn.id, op, 'error', time.perf_counter() - t0)
        _audit(conn, 'connector.query', tool, op, 'error', {**(audit_details or {}), 'error': str(e)[:300]})
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    rows = int(out.get('row_count') or 0) if isinstance(out, dict) else 0
    _metric(conn.id, op, 'ok', ms / 1000.0, rows)
    det = dict(audit_details or {})
    if isinstance(out, dict):
        det.update({k: out[k] for k in ('row_count', 'truncated', 'tables') if k in out})
    det['ms'] = ms
    _audit(conn, 'connector.query', tool, op, 'ok', det)
    if isinstance(out, dict):
        out['elapsed_ms'] = ms
    return out


def list_tables(conn: Connection, schema: Optional[str] = None, pattern: Optional[str] = None,
                refresh: bool = False, tool: str = '') -> Dict[str, Any]:
    _require_sql(conn)

    def run():
        tables, truncated = allowed_tables(conn, bool(refresh))
        out = tables
        if schema:
            out = [t for t in out if (t.get('schema') or '').lower() == str(schema).lower()]
        if pattern:
            p = str(pattern).lower()
            if not any(ch in p for ch in '*?['):
                p = f'*{p}*'
            out = [t for t in out if fnmatch.fnmatchcase((t.get('name') or '').lower(), p)]
        items = [{'schema': t.get('schema') or '', 'name': t['name'], 'type': t.get('type') or 'table',
                  **({'comment': t['comment']} if t.get('comment') else {})} for t in out]
        return {'connection': conn.id, 'title': conn.label, 'kind': conn.kind, 'tables': items,
                'row_count': len(items), 'truncated': truncated,
                'next': f'Call {conn.id}__describe_table for a table\'s columns, then {conn.id}__query.'}
    return _timed(conn, 'list_tables', tool, run)


def describe_table(conn: Connection, table: Any, samples: Optional[int] = None, refresh: bool = False,
                   tool: str = '') -> Dict[str, Any]:
    _require_sql(conn)

    def run():
        allowed, _ = allowed_tables(conn)
        schema, name = resolve_table(conn, table, allowed)
        info = next((t for t in allowed if (t.get('schema') or '') == schema and t['name'] == name), {})
        detail = table_detail(conn, schema, name, bool(refresh))
        tables = [(schema, name)]
        cols, visible, masked = [], [], {}
        for c in detail.get('columns') or []:
            r = conn.mask_rules_for(c['name'], tables)
            entry = {'name': c['name'], 'type': c.get('type') or '', 'nullable': bool(c.get('nullable', True))}
            if c.get('comment'):
                entry['comment'] = c['comment']
            if r is not None:
                entry['masked'] = r.mode
                masked[c['name']] = r.mode
            if r is not None and r.mode == 'hide':
                cols.append({'name': c['name'], 'masked': 'hide'})
                continue
            cols.append(entry)
            visible.append(c['name'])
        n = settings.sample_rows() if samples is None else max(0, min(20, int(samples)))
        sample_rows: List[Dict[str, Any]] = []
        if n and visible:
            drv = get_driver(conn.kind)
            sql = drv.sample_sql(schema, name, visible, n)
            with session(conn) as (d, dbc, state):
                res = _execute(conn, d, dbc, state, sql, None, n, conn.max_bytes)
            rules = masking.plan(conn, [c['name'] for c in res['columns']], tables)
            sample_rows = masking.apply_rows(conn, res['rows'], rules)
        return {'connection': conn.id, 'schema': schema, 'table': name, 'type': info.get('type') or 'table',
                **({'comment': info['comment']} if info.get('comment') else {}),
                'columns': cols, 'primary_key': list(detail.get('primary_key') or []),
                'sample_rows': sample_rows, 'masked_columns': masked, 'tables': [f'{schema}.{name}'],
                'next': f'Query it with {conn.id}__query (one read-only SELECT; :name parameters bound '
                        f'from "params").'}
    return _timed(conn, 'describe_table', tool, run)


def _cap(conn: Connection, requested: Any, view_max: int = 0) -> int:
    cap = conn.max_rows
    if view_max:
        cap = min(cap, view_max)
    if requested not in (None, ''):
        try:
            cap = max(1, min(cap, int(requested)))
        except (TypeError, ValueError):
            raise ConnectorError('max_rows must be a whole number') from None
    return cap


def _finish(conn: Connection, res: Dict[str, Any], tables: List[Tuple[str, str]]) -> Dict[str, Any]:
    base = res.get('base_names') or [c['name'] for c in res['columns']]
    rules = {}
    for shown, b in zip([c['name'] for c in res['columns']], base):
        r = conn.mask_rules_for(b, tables)
        if r is not None:
            rules[shown] = r
    rows = masking.apply_rows(conn, res['rows'], rules)
    cols = [c for c in res['columns'] if not (rules.get(c['name']) and rules[c['name']].mode == 'hide')]
    out = {'connection': conn.id, 'columns': cols, 'rows': rows, 'row_count': len(rows),
           'truncated': res['truncated']}
    if res['truncated']:
        out['truncated_reason'] = res['truncated_reason']
    if rules:
        out['masked_columns'] = sorted(rules)
    out['tables'] = [f'{s}.{t}' if s else t for s, t in tables]
    return out


def query(conn: Connection, sql: Any, params: Optional[Dict[str, Any]] = None, max_rows: Any = None,
          tool: str = '') -> Dict[str, Any]:
    _require_sql(conn)
    if not conn.tool_enabled('query'):
        raise ConnectorError(f'caller-written SQL is turned off for {conn.id}; use its views or catalog tools')
    if params is not None and not isinstance(params, dict):
        raise guard.GuardError('params must be an object of name -> value')
    for k, v in (params or {}).items():
        if not isinstance(v, (str, int, float, bool)) and v is not None:
            raise guard.GuardError(f'parameter {k}: only text, numbers, booleans or null')

    def run():
        cap = _cap(conn, max_rows)
        allowed, _ = allowed_tables(conn)
        checked = guard.check(sql, conn, resolver(conn, allowed), limit=cap + 1,
                              require_parser=settings.require_sqlglot())
        drv = get_driver(conn.kind)
        try:
            text, bound = sqltext.bind_params(checked.sql, params or {}, drv.paramstyle,
                                              guard.DIALECTS.get(conn.kind, ''))
        except ValueError as e:
            raise guard.GuardError(str(e)) from None
        with session(conn) as (d, dbc, state):
            d.extra_check(dbc, text)
            res = _execute(conn, d, dbc, state, text, bound, cap, conn.max_bytes)
        out = _finish(conn, res, checked.tables)
        out['guard'] = checked.parser
        return out
    return _timed(conn, 'query', tool, run, _sql_details(sql if isinstance(sql, str) else ''))


# ── curated views ───────────────────────────────────────────────────────

_OP_SUFFIX = {'eq': '', 'in': '_in', 'gte': '_from', 'lte': '_to', 'gt': '_after', 'lt': '_before',
              'contains': '_contains'}
_OP_SQL = {'eq': '=', 'gte': '>=', 'lte': '<=', 'gt': '>', 'lt': '<'}


def _arg_base(column: str) -> str:
    a = re.sub(r'[^a-z0-9_]', '_', column.lower()).strip('_') or 'col'
    return a if a[0].isalpha() else f'c_{a}'


def view_args(view: View) -> List[Tuple[str, str, str]]:
    """[(argument, column, operator)] of a view, in schema order; raises on a name collision."""
    out, seen = [], {'limit'}
    for f in view.filters:
        for op in f.operators:
            arg = _arg_base(f.column) + _OP_SUFFIX[op]
            if arg in seen:
                raise ConnectorError(f'view {view.name}: argument {arg} is generated twice; rename a filter')
            seen.add(arg)
            out.append((arg, f.column, op))
    return out


def _find_view(conn: Connection, name: str) -> View:
    for v in conn.views:
        if v.name == name:
            return v
    raise ConnectorError(f'connection {conn.id} has no view {name!r}')


def _column_map(detail: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {c['name'].lower(): c for c in detail.get('columns') or []}


def _view_columns(conn: Connection, view: View, schema: str, table: str, detail: Dict[str, Any]
                  ) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    cmap = _column_map(detail)
    tables = [(schema, table)]
    if view.columns:
        out = []
        for c in view.columns:
            col = cmap.get(c.lower())
            if col is None:
                raise ConnectorError(f'view {view.name}: column {c} is not in {schema}.{table}')
            r = conn.mask_rules_for(col['name'], tables)
            if r is not None and r.mode == 'hide':
                raise ConnectorError(f'view {view.name}: column {c} is hidden on this connection')
            out.append(col['name'])
    else:
        out = []
        for c in detail.get('columns') or []:
            r = conn.mask_rules_for(c['name'], tables)
            if r is None or r.mode != 'hide':
                out.append(c['name'])
    for f in view.filters:
        col = cmap.get(f.column.lower())
        if col is None:
            raise ConnectorError(f'view {view.name}: filter column {f.column} is not in {schema}.{table}')
        if conn.mask_rules_for(col['name'], tables) is not None:
            raise ConnectorError(f'view {view.name}: column {f.column} is masked and cannot be a filter')
    for c, _d in view.order_by:
        if c.lower() not in cmap:
            raise ConnectorError(f'view {view.name}: order_by column {c} is not in {schema}.{table}')
    return out, cmap


def view_input_schema(conn: Connection, view: View, detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cmap = _column_map(detail or {})
    props: Dict[str, Any] = {}
    required: List[str] = []
    by_col = {f.column: f for f in view.filters}
    for arg, column, op in view_args(view):
        f = by_col[column]
        base = json_schema_for((cmap.get(column.lower()) or {}).get('type', ''))
        if op in ('gte', 'lte', 'gt', 'lt') and base.get('type') == 'boolean':
            base = {'type': 'string'}
        if op == 'contains':
            base = {'type': 'string', 'minLength': 1, 'maxLength': 200}
        if f.enum and op in ('eq', 'in'):
            base = dict(base, enum=list(f.enum))
        human = {'eq': 'equal to', 'in': 'one of', 'gte': 'on or after / at least', 'lte': 'on or before / at most',
                 'gt': 'after / greater than', 'lt': 'before / less than', 'contains': 'containing'}[op]
        desc = f'{column} {human}' + (f'. {f.description}' if f.description else '')
        if op == 'in':
            props[arg] = {'type': 'array', 'items': base, 'minItems': 1, 'maxItems': 100, 'description': desc}
        else:
            props[arg] = dict(base, description=desc)
        if f.required and op == f.operators[0]:
            required.append(arg)
    cap = min(conn.max_rows, view.max_rows or conn.max_rows)
    props['limit'] = {'type': 'integer', 'minimum': 1, 'maximum': cap,
                      'description': f'Rows to return (at most {cap}).'}
    schema: Dict[str, Any] = {'type': 'object', 'properties': props, 'additionalProperties': False}
    if required:
        schema['required'] = required
    return schema


def _escape_like(v: str) -> str:
    return v.replace('!', '!!').replace('%', '!%').replace('_', '!_')


def build_view_sql(conn: Connection, view: View, args: Dict[str, Any], schema: str, table: str,
                   detail: Dict[str, Any]) -> Tuple[str, Dict[str, Any], int]:
    """(SQL with :name placeholders, parameters, row cap) for one view call."""
    drv = get_driver(conn.kind)
    cols, cmap = _view_columns(conn, view, schema, table, detail)
    allowed_args = {a for a, _c, _o in view_args(view)} | {'limit'}
    extra = sorted(set(args or {}) - allowed_args)
    if extra:
        raise guard.GuardError(f'unknown argument(s) for {conn.id}__{view.name}: {", ".join(extra)}')
    where, params = [], {}
    for i, (arg, column, op) in enumerate(view_args(view)):
        if arg not in (args or {}) or args[arg] is None:
            f = next(x for x in view.filters if x.column == column)
            if f.required and op == f.operators[0]:
                raise guard.GuardError(f'{arg} is required')
            continue
        value = args[arg]
        col = drv.quote(cmap[column.lower()]['name'])
        if op == 'in':
            if not isinstance(value, list) or not value or len(value) > 100:
                raise guard.GuardError(f'{arg} must be a list of 1 to 100 values')
            names = []
            for j, v in enumerate(value):
                if isinstance(v, (dict, list)):
                    raise guard.GuardError(f'{arg}: values must be scalars')
                params[f'p{i}_{j}'] = v
                names.append(f':p{i}_{j}')
            where.append(f'{col} IN ({", ".join(names)})')
        elif op == 'contains':
            params[f'p{i}'] = f'%{_escape_like(str(value))}%'
            where.append(f"{col} LIKE :p{i} ESCAPE '!'")
        else:
            if isinstance(value, (dict, list)):
                raise guard.GuardError(f'{arg} must be a single value')
            params[f'p{i}'] = value
            where.append(f'{col} {_OP_SQL[op]} :p{i}')
    cap = _cap(conn, (args or {}).get('limit'), view.max_rows)
    select = ', '.join(drv.quote(c) for c in cols)
    sql = f'SELECT {select} FROM {drv.qualified(schema, table)}'
    if drv.limit_style == 'top':
        sql = f'SELECT TOP ({cap + 1}) {select} FROM {drv.qualified(schema, table)}'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    if view.order_by:
        sql += ' ORDER BY ' + ', '.join(f'{drv.quote(cmap[c.lower()]["name"])} {d.upper()}' for c, d in view.order_by)
    if drv.limit_style == 'limit':
        sql += f' LIMIT {cap + 1}'
    elif drv.limit_style == 'fetch':
        sql += f' FETCH FIRST {cap + 1} ROWS ONLY'
    return sql, params, cap


def run_view(conn: Connection, name: str, args: Dict[str, Any], tool: str = '') -> Dict[str, Any]:
    _require_sql(conn)
    view = _find_view(conn, name)

    def run():
        allowed, _ = allowed_tables(conn)
        schema, table = resolve_table(conn, view.table, allowed)
        detail = table_detail(conn, schema, table)
        sql, params, cap = build_view_sql(conn, view, args or {}, schema, table, detail)
        drv = get_driver(conn.kind)
        text, bound = sqltext.bind_params(sql, params, drv.paramstyle, guard.DIALECTS.get(conn.kind, ''))
        with session(conn) as (d, dbc, state):
            res = _execute(conn, d, dbc, state, text, bound, cap, conn.max_bytes)
        out = _finish(conn, res, [(schema, table)])
        out['view'] = view.name
        return out
    return _timed(conn, 'view', tool, run, {'view': view.name, 'arguments': sorted((args or {}).keys())})


# ── test / introspection for the admin page ─────────────────────────────

def test(conn: Connection) -> Dict[str, Any]:
    """Connect, report the server version and the number of allowed tables (no cache)."""
    if conn.family != 'sql':
        from sajha.connectors import vector
        return vector.test(conn)
    t0 = time.perf_counter()
    with session(conn) as (drv, dbc, state):
        try:
            version = drv.server_version(dbc, conn)
        except Exception as e:
            version = f'(version unavailable: {e.__class__.__name__})'
        try:
            drv.end(dbc)
        except Exception:
            state['broken'] = True
    tables, truncated = allowed_tables(conn, refresh=True)
    return {'success': True, 'connection': conn.id, 'kind': conn.kind, 'server_version': version,
            'tables': len(tables), 'truncated': truncated, 'ms': int((time.perf_counter() - t0) * 1000)}
