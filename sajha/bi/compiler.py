"""
SAJHA MCP Server — Business Intelligence: a metric query compiled to one safe SELECT (§3.2).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The caller never writes SQL. The statement is built from three things only:

* the metric definition (measure, fixed filters, time column, dimension columns), checked when
  the file is read (``metrics.py``) and against the source's catalog on every call here;
* identifiers the caller names (``by``, filter dimensions, the grain), accepted only when the
  definition declares them, and written as the declared column, quoted by the source;
* values (filter values, period bounds), always ``:bi_pN`` / ``:bi_from`` / ``:bi_to`` parameters
  bound by the driver, never written into the text.

The statement then runs through the source's own path, so a metric adds a definition, never an
access path:

* ``connector``: the connection's allowlist and deny rules (an unlisted or denied table is not
  found), its statement guard (``guard.check``), read-only session, row/byte/time limits, masking
  of the result, audit (``connector.query`` with the SQL's hash) and metrics. A metric that uses a
  masked column at all is refused, so a masked value is never grouped, filtered or aggregated.
* ``duckdb_table``: the locked-down DuckDB sandbox the ``duckdb_*`` tools use (no file or URL
  access), after DuckDB's own read-only check (``sajha/olap/sql_safety.py::read_only_sql``).
* ``olap_dataset``: the OLAP semantic layer's dataset (its configured FROM and joins) in a fresh
  in-memory DuckDB, after the same read-only check.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sajha.bi import periods as P
from sajha.bi.metrics import Metric, MetricError

logger = logging.getLogger(__name__)

OPS = ('eq', 'ne', 'in', 'not_in', 'gte', 'lte', 'between', 'contains')
MAX_LIST = 200
_TRUNC_DIALECTS = ('duckdb', 'postgres', 'redshift', 'snowflake', 'databricks')


def max_rows() -> int:
    from sajha.core.config import _get
    try:
        return max(1, int(_get('bi.max_rows', '5000') or 5000))
    except ValueError:
        return 5000


# ── sources ─────────────────────────────────────────────────────────────

class Source:
    dialect = 'duckdb'

    def quote(self, name: str) -> str:
        from sajha.connectors.guard import quote
        return quote(name, '"')

    def columns(self) -> Dict[str, str]:            # lower-case name -> catalog name
        raise NotImplementedError

    def from_sql(self) -> str:
        raise NotImplementedError

    def masked(self, column: str) -> bool:
        return False

    def run(self, sql: str, params: Dict[str, Any], cap: int, tool: str) -> Dict[str, Any]:
        raise NotImplementedError

    def wire(self, v: Any) -> Any:
        """A period bound as the driver binds it."""
        return v


def _duckdb_rows(cur, sql: str, params: Dict[str, Any], cap: int) -> Dict[str, Any]:
    from sajha.connectors import sqltext
    from sajha.olap import sql_safety as sq
    text, bound = sqltext.bind_params(sql, params, 'dollar', 'duckdb')
    text = sq.read_only_sql(cur, text)
    res = cur.execute(text, bound) if bound else cur.execute(text)
    cols = [d[0] for d in res.description or []]
    rows = [dict(zip(cols, r)) for r in res.fetchmany(cap + 1)]
    truncated = len(rows) > cap
    return {'rows': rows[:cap], 'truncated': truncated}


class DuckDbTableSource(Source):
    def __init__(self, table: str):
        from sajha.core.config import _get, resolve_placeholders
        from sajha.tools.impl.duckdb_olap_tools_refactored import DuckDbSandbox
        directory = resolve_placeholders(_get('data.duckdb.dir', './data/duckdb') or './data/duckdb')
        self.sandbox = DuckDbSandbox.for_directory(directory)
        if self.sandbox.changed():
            self.sandbox.reload()
        cur = self.sandbox.cursor()
        rows = cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' "
                           "AND lower(table_name) = lower(?)", [table]).fetchall()
        if not rows:
            raise MetricError(f'DuckDB table {table!r} is not in {directory} (the duckdb_* tools\' tables)')
        self.table = rows[0][0]
        self._cols = {r[0].lower(): r[0] for r in cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'main' AND table_name = ?",
            [self.table]).fetchall()}

    def columns(self) -> Dict[str, str]:
        return self._cols

    def from_sql(self) -> str:
        return self.quote(self.table)

    def run(self, sql, params, cap, tool):
        return _duckdb_rows(self.sandbox.cursor(), sql, params, cap)


_semantic = None
_semantic_lock = threading.Lock()


def _semantic_layer():
    global _semantic
    with _semantic_lock:
        if _semantic is None:
            from sajha.olap.semantic_layer import SemanticLayer
            _semantic = SemanticLayer()
        return _semantic


class OlapDatasetSource(Source):
    def __init__(self, name: str):
        import duckdb
        from sajha.olap import sql_safety as sq
        ds = _semantic_layer().get_dataset(name)
        if ds is None:
            raise MetricError(f'OLAP dataset {name!r} is not defined (config/olap/datasets.json)')
        self._from = f'({sq.from_clause(ds)}) AS _bi_src'
        self.conn = duckdb.connect(':memory:')
        desc = self.conn.execute(f'DESCRIBE SELECT * FROM {self._from}').fetchall()
        self._cols = {r[0].lower(): r[0] for r in desc}

    def columns(self):
        return self._cols

    def from_sql(self):
        return self._from

    def run(self, sql, params, cap, tool):
        try:
            return _duckdb_rows(self.conn, sql, params, cap)
        finally:
            self.conn.close()


class ConnectorSource(Source):
    def __init__(self, cid: str, table: str):
        from sajha.connectors import engine, guard, store
        from sajha.connectors.drivers import get_driver
        conn, err = store.get(cid)
        if conn is None:
            raise MetricError(f'data connection {cid!r} is not available: {err or "no such connection"}')
        if conn.family != 'sql' or not conn.enabled:
            raise MetricError(f'data connection {cid} is not an enabled SQL connection')
        self.conn = conn
        self.drv = get_driver(conn.kind)
        self.dialect = guard.DIALECTS.get(conn.kind, '')
        self.allowed, _ = engine.allowed_tables(conn)
        # an unlisted or denied table is simply not found (engine.resolve_table raises ConnectorError)
        self.schema, self.table = engine.resolve_table(conn, table, self.allowed)
        detail = engine.table_detail(conn, self.schema, self.table)
        self._cols = {c['name'].lower(): c['name'] for c in detail.get('columns') or []}

    def quote(self, name):
        return self.drv.quote(name)

    def columns(self):
        return self._cols

    def from_sql(self):
        return self.drv.qualified(self.schema, self.table)

    def masked(self, column):
        return self.conn.mask_rules_for(column, [(self.schema, self.table)]) is not None

    def wire(self, v):
        return v.isoformat() if isinstance(v, date) else v

    def run(self, sql, params, cap, tool):
        from sajha.connectors import engine, guard, settings, sqltext
        conn = self.conn
        cap = min(cap, conn.max_rows)

        def go():
            checked = guard.check(sql, conn, engine.resolver(conn, self.allowed), limit=cap + 1,
                                  require_parser=settings.require_sqlglot())
            try:
                text, bound = sqltext.bind_params(checked.sql, params, self.drv.paramstyle, self.dialect)
            except ValueError as e:
                raise guard.GuardError(str(e)) from None
            with engine.session(conn) as (d, dbc, state):
                d.extra_check(dbc, text)
                res = engine._execute(conn, d, dbc, state, text, bound, cap, conn.max_bytes)
            out = engine._finish(conn, res, checked.tables)
            out['guard'] = checked.parser
            return out
        out = engine._timed(conn, 'bi_query', tool, go, engine._sql_details(sql))
        return {'rows': out['rows'], 'truncated': out['truncated'],
                'masked_columns': out.get('masked_columns') or []}


def open_source(m: Metric) -> Source:
    s = m.source
    if s.get('connector'):
        return ConnectorSource(s['connector'], s['table'])
    if s.get('duckdb_table'):
        return DuckDbTableSource(s['duckdb_table'])
    if s.get('olap_dataset'):
        return OlapDatasetSource(s['olap_dataset'])
    raise MetricError(f'{m.name}: its source kind is not supported')


# ── compilation ─────────────────────────────────────────────────────────

@dataclass
class Compiled:
    sql: str
    params: Dict[str, Any]
    by: List[str]
    grain: str = ''

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.sql.encode('utf-8')).hexdigest()[:16]


def _bucket(dialect: str, grain: str, col: str) -> str:
    if dialect == 'duckdb':
        return (f'CAST({col} AS DATE)' if grain == 'day'
                else f"CAST(date_trunc('{grain}', CAST({col} AS TIMESTAMP)) AS DATE)")
    if dialect in _TRUNC_DIALECTS:
        return f'CAST({col} AS DATE)' if grain == 'day' else f"CAST(date_trunc('{grain}', {col}) AS DATE)"
    if dialect == 'sqlite':
        return {
            'day': f'date({col})',
            'week': f"date({col}, '-' || ((CAST(strftime('%w', {col}) AS INTEGER) + 6) % 7) || ' days')",
            'month': f"strftime('%Y-%m-01', {col})",
            'quarter': f"printf('%s-%02d-01', strftime('%Y', {col}), "
                       f"((CAST(strftime('%m', {col}) AS INTEGER) - 1) / 3) * 3 + 1)",
            'year': f"strftime('%Y-01-01', {col})",
        }[grain]
    raise MetricError(f'grains need a DuckDB, PostgreSQL, Redshift, Snowflake, Databricks or SQLite source; '
                      f'ask without grain')


def _time_col(src: Source, m: Metric) -> str:
    col = src.quote(src.columns()[m.time_column.lower()])
    return f'CAST({col} AS DATE)' if src.dialect == 'duckdb' else col


def check_columns(m: Metric, src: Source) -> None:
    """Every column the definition uses exists in the source and none is masked."""
    cols = src.columns()
    missing = sorted(c for c in m.columns if c not in cols)
    if missing:
        raise MetricError(f'{m.name}: column(s) {", ".join(missing)} are not in its source (the definition '
                          f'needs fixing; the source has {", ".join(sorted(cols)[:40])})')
    masked = sorted(c for c in m.columns if src.masked(cols[c]))
    if masked:
        raise MetricError(f'{m.name}: column(s) {", ".join(masked)} are masked on connection '
                          f'{m.source.get("connector")}; a metric may not group, filter or aggregate a masked column')


def _scalar(v: Any, where: str) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    raise MetricError(f'{where}: values must be text, numbers or booleans')


def _filters(m: Metric, src: Source, filters: Any, params: Dict[str, Any]) -> List[str]:
    if not filters:
        return []
    if not isinstance(filters, list):
        raise MetricError('filters must be a list of {dimension, op, value}')
    out = []
    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            raise MetricError('each filter is {dimension, op, value}')
        d = m.dimension(f.get('dimension'))
        op = str(f.get('op') or 'eq').lower()
        if op not in OPS:
            raise MetricError(f'filter on {d.name}: op must be one of {", ".join(OPS)}')
        col = src.quote(src.columns()[d.column.lower()])
        val = f.get('value')
        where = f'filter on {d.name}'
        if op in ('in', 'not_in', 'between'):
            vals = val if isinstance(val, list) else [val]
            if op == 'between' and len(vals) != 2:
                raise MetricError(f'{where}: between needs [low, high]')
            if not vals or len(vals) > MAX_LIST:
                raise MetricError(f'{where}: {op} needs 1 to {MAX_LIST} values')
            names = []
            for j, v in enumerate(vals):
                params[f'bi_p{i}_{j}'] = _scalar(v, where)
                names.append(f':bi_p{i}_{j}')
            if op == 'between':
                out.append(f'{col} BETWEEN {names[0]} AND {names[1]}')
            else:
                out.append(f'{col} {"NOT IN" if op == "not_in" else "IN"} ({", ".join(names)})')
            check = vals if op != 'between' else []
        else:
            if isinstance(val, (list, dict)):
                raise MetricError(f'{where}: {op} takes one value')
            p = f'bi_p{i}'
            if op == 'contains':
                s = str(_scalar(val, where))
                params[p] = '%' + s.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
                out.append(f"{col} LIKE :{p} ESCAPE '!'")
            else:
                params[p] = _scalar(val, where)
                out.append(f'{col} {({"eq": "=", "ne": "<>", "gte": ">=", "lte": "<="})[op]} :{p}')
            check = [val] if op in ('eq', 'ne') else []
        if d.values and any(str(v) not in d.values for v in check):
            raise MetricError(f'{where}: values are {", ".join(d.values)}')
    return out


def compile_query(m: Metric, src: Source, by: Optional[List[str]] = None, filters: Any = None,
                  grain: Optional[str] = None, period: Optional[P.Period] = None,
                  order_by_value: bool = False) -> Compiled:
    check_columns(m, src)
    cols = src.columns()
    by = list(by or [])
    if len(set(by)) != len(by) or len(by) > 3:
        raise MetricError('by names at most three different dimensions')
    dims = [m.dimension(b) for b in by]
    params: Dict[str, Any] = {}
    select, group = [], []
    if grain:
        if grain not in m.grains:
            raise MetricError(f'{m.name} may be asked by {", ".join(m.grains)}, not {grain!r}')
        b = _bucket(src.dialect, grain, src.quote(cols[m.time_column.lower()]))
        select.append(f'{b} AS bi_period')
        group.append(b)
    for d in dims:
        c = src.quote(cols[d.column.lower()])
        select.append(f'{c} AS {src.quote(d.name)}')
        group.append(c)
    if m.type == 'ratio':
        select += [f'{m.num_sql} AS bi_num', f'{m.den_sql} AS bi_den']
    else:
        select.append(f'{m.measure_sql} AS bi_value')
    where = [f'({f})' for f in m.filters]
    if period is not None:
        t = _time_col(src, m)
        params['bi_from'], params['bi_to'] = src.wire(period.start), src.wire(period.end)
        where += [f'{t} >= :bi_from', f'{t} < :bi_to']
    where += _filters(m, src, filters, params)
    sql = f'SELECT {", ".join(select)}\nFROM {src.from_sql()}'
    if where:
        sql += '\nWHERE ' + ' AND '.join(where)
    if group:
        sql += '\nGROUP BY ' + ', '.join(group)
        order = (['bi_value DESC' if m.type != 'ratio' else 'bi_num DESC'] if order_by_value else []) + \
            [str(i + 1) for i in range(len(group))]
        sql += '\nORDER BY ' + ', '.join(order)
    return Compiled(sql, params, by, grain or '')


def compile_as_of(m: Metric, src: Source) -> Compiled:
    col = src.quote(src.columns()[m.time_column.lower()])
    sql = f'SELECT max({col}) AS bi_as_of\nFROM {src.from_sql()}'
    if m.filters:
        sql += '\nWHERE ' + ' AND '.join(f'({f})' for f in m.filters)
    return Compiled(sql, {}, [])


# ── running ─────────────────────────────────────────────────────────────

def _num(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, (float, Decimal)):
        return round(float(v), 6)
    try:
        f = float(v)
        return int(f) if f.is_integer() and '.' not in str(v) else round(f, 6)
    except (TypeError, ValueError):
        return v


def _plain(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


@dataclass
class Result:
    metric: Metric
    rows: List[Dict[str, Any]]
    truncated: bool
    fingerprint: str
    by: List[str]
    grain: str = ''
    period: Optional[P.Period] = None
    as_of: Optional[str] = None
    masked_columns: List[str] = field(default_factory=list)


def run(m: Metric, by: Optional[List[str]] = None, filters: Any = None, grain: Optional[str] = None,
        period: Optional[P.Period] = None, limit: Optional[int] = None, order_by_value: bool = False,
        tool: str = 'bi_query_metric', with_as_of: bool = True, src: Optional[Source] = None) -> Result:
    """Compile and run one metric query; rows are ``{period?, <dimension>..., value[, numerator, denominator]}``."""
    src = src or open_source(m)
    c = compile_query(m, src, by, filters, grain, period, order_by_value)
    cap = max_rows() if limit is None else max(1, min(int(limit), max_rows()))
    raw = src.run(c.sql, c.params, cap, tool)
    rows = []
    for r in raw['rows']:
        out: Dict[str, Any] = {}
        if grain:
            out['period'] = P.bucket_label(r.get('bi_period'), grain)
            out['period_start'] = _plain(r.get('bi_period'))
        for b in by or []:
            out[b] = _plain(r.get(b))
        if m.type == 'ratio':
            num, den = _num(r.get('bi_num')), _num(r.get('bi_den'))
            out['value'] = (num / den) if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den \
                else None
            out['numerator'], out['denominator'] = num, den
        else:
            out['value'] = _num(r.get('bi_value'))
        rows.append(out)
    as_of = None
    if with_as_of:
        if isinstance(src, OlapDatasetSource):
            src = open_source(m)                     # the OLAP source closes its connection after a run
        a = src.run(compile_as_of(m, src).sql, {}, 1, tool)
        as_of = _plain(a['rows'][0].get('bi_as_of')) if a['rows'] else None
        if isinstance(as_of, str) and len(as_of) > 10 and as_of[10] in ' T' and as_of.endswith(('00:00:00', '00:00')):
            as_of = as_of[:10]
    return Result(m, rows, bool(raw['truncated']), c.fingerprint, list(by or []), grain or '', period,
                  as_of, list(raw.get('masked_columns') or []))
