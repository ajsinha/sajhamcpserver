"""
SAJHA MCP Server — Business Intelligence: metric definitions (Business Intelligence §3.1, §3.3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A metric is a YAML document (one per file, or a list) under ``bi.metrics_dir`` (default
``config/bi/metrics``), read through the storage backend and re-read when a file is added,
changed or removed. A file that cannot be read, or a metric that fails a check, is left out
and raises the warning notice ``bi.metric:<file>`` (cleared when the file is fixed).

Checks when a file is read: the name rule; exactly one source; the measure is one aggregate
expression and fixed filters are boolean expressions, both without subqueries, statements,
comments, parameters, qualified names or denied functions (the connector guard's list); the
dimensions and time column are plain column names; a ratio names two metrics on the same source
and time column with the same fixed filters. Every column a definition uses is checked against the
source's catalog when it is queried (``compiler.py``), so a dropped column fails with its name.

Who may query (§3.3): the bi_* tools' own access control first, then the metric's ``roles`` (an
administrator passes; a metric without roles is open to whoever may call the tool), then, for a
connector source, the caller's access to that connection's tools and the connection's own guard.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sajha.connectors import sqltext

logger = logging.getLogger(__name__)

NOTICE_PREFIX = 'bi.metric:'
TYPES = ('sum', 'count', 'count_distinct', 'avg', 'ratio', 'min', 'max')
ADDITIVE = ('sum', 'count')
SOURCE_KEYS = ('connector', 'olap_dataset', 'duckdb_table', 'loaded')
_NAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_COLUMN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
_TABLE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$')
#: output names the compiler uses; a dimension may not take them
RESERVED = {'bi_period', 'bi_value', 'bi_num', 'bi_den', 'bi_as_of'}
AGGREGATES = {'sum', 'count', 'avg', 'min', 'max', 'median', 'stddev', 'stddev_samp', 'stddev_pop', 'variance',
              'var_samp', 'var_pop', 'approx_count_distinct', 'count_if', 'mode', 'any_value'}
_FORBIDDEN_WORDS = {'SELECT', 'FROM', 'WITH', 'UNION', 'INTERSECT', 'EXCEPT', 'MINUS', 'INSERT', 'UPDATE',
                    'DELETE', 'MERGE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE', 'INTO', 'JOIN',
                    'OVER', 'WINDOW', 'COPY', 'CALL', 'EXEC', 'EXECUTE', 'SET', 'PRAGMA', 'ATTACH', 'LOAD',
                    'INSTALL', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'UNNEST', 'LATERAL', 'VALUES'}
_KEYWORDS = {'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'AND', 'OR', 'NOT', 'NULL', 'IS', 'IN', 'AS',
             'TRUE', 'FALSE', 'LIKE', 'ILIKE', 'BETWEEN', 'FILTER', 'WHERE', 'INTERVAL', 'ESCAPE', 'ALL', 'ANY',
             'DAY', 'DAYS', 'MONTH', 'MONTHS', 'YEAR', 'YEARS', 'HOUR', 'MINUTE', 'SECOND', 'WEEK', 'QUARTER'}


class MetricError(ValueError):
    """A metric definition, or a request about a metric, was refused."""


@dataclass(frozen=True)
class Dimension:
    name: str
    column: str
    values: Tuple[str, ...] = ()
    description: str = ''


@dataclass
class Metric:
    name: str
    title: str = ''
    description: str = ''
    owner: str = ''
    source: Dict[str, str] = field(default_factory=dict)
    measure_sql: str = ''
    type: str = 'sum'
    numerator: str = ''
    denominator: str = ''
    time_column: str = ''
    grains: Tuple[str, ...] = ('day', 'week', 'month', 'quarter', 'year')
    fiscal_year_start: int = 1
    dimensions: List[Dimension] = field(default_factory=list)
    filters: List[str] = field(default_factory=list)
    format: Dict[str, Any] = field(default_factory=dict)
    roles: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    file: str = ''
    #: for a ratio, after resolution: the numerator's and denominator's measure SQL
    num_sql: str = ''
    den_sql: str = ''
    columns: Set[str] = field(default_factory=set)   # every column the definition uses (lower case)

    @property
    def source_kind(self) -> str:
        return next((k for k in SOURCE_KEYS if self.source.get(k)), '')

    @property
    def additive(self) -> bool:
        return self.type in ADDITIVE

    def dimension(self, name: Any) -> Dimension:
        for d in self.dimensions:
            if d.name == name:
                return d
        raise MetricError(f'{self.name} has no dimension {name!r}; its dimensions are '
                          f'{", ".join(d.name for d in self.dimensions) or "none"}')

    def summary(self) -> Dict[str, Any]:
        return {'name': self.name, 'title': self.title or self.name, 'description': self.description,
                'owner': self.owner, 'type': self.type, 'unit': self.format.get('unit', ''),
                'grains': list(self.grains), 'dimensions': [d.name for d in self.dimensions],
                'tags': list(self.tags), 'source_kind': self.source_kind}


# ── fragments: the measure and the fixed filters ─────────────────────────

def check_fragment(text: Any, what: str, dialect: str = '') -> Set[str]:
    """The column names an expression uses; :class:`MetricError` when it is not a plain expression."""
    from sajha.connectors import guard
    if not isinstance(text, str) or not text.strip():
        raise MetricError(f'{what} is empty')
    if len(text) > 2000:
        raise MetricError(f'{what} is longer than 2000 characters')
    try:
        toks = sqltext.tokenize(text, dialect)
    except sqltext.SQLTextError as e:
        raise MetricError(f'{what}: {e}') from None
    if any(t.kind == 'comment' for t in toks):
        raise MetricError(f'{what} may not contain comments')
    code = sqltext.code(toks)
    columns: Set[str] = set()
    has_aggregate = False
    depth = 0
    for i, t in enumerate(code):
        if t.kind == 'param':
            raise MetricError(f'{what} may not contain parameters ({t.text})')
        if t.kind == 'op':
            if t.text in (';', '.', '[', ']', '{', '}', '$', '?'):
                raise MetricError(f'{what} may not contain {t.text!r} (one expression over unqualified columns)')
            depth += {'(': 1, ')': -1}.get(t.text, 0)
            if depth < 0:
                raise MetricError(f'{what} has unbalanced parentheses')
            continue
        if t.kind not in ('word', 'qident'):
            continue
        nxt = code[i + 1] if i + 1 < len(code) else None
        prev = code[i - 1] if i else None
        if t.kind == 'word' and t.upper in _FORBIDDEN_WORDS:
            raise MetricError(f'{what} may not contain {t.upper} (no subqueries, statements or windows)')
        if nxt is not None and nxt.kind == 'op' and nxt.text == '(':
            if guard._denied_function(t.ident):
                raise MetricError(f'{what}: function {t.ident}() is not allowed')
            if t.ident.lower() in AGGREGATES:
                has_aggregate = True
            continue
        if t.kind == 'word' and (t.upper in _KEYWORDS or (prev is not None and prev.kind == 'word'
                                                           and prev.upper == 'AS')):
            continue                                   # a keyword, or a type name in CAST(x AS type)
        columns.add(t.ident.lower())
    if depth != 0:
        raise MetricError(f'{what} has unbalanced parentheses')
    if what.startswith('measure') and not has_aggregate:
        raise MetricError(f'{what} must be an aggregate expression (sum, count, avg, min, max, ...)')
    if what.startswith('filter') and has_aggregate:
        raise MetricError(f'{what} may not aggregate (it is applied to each row)')
    return columns


def _dialect(source: Dict[str, str]) -> str:
    if source.get('connector'):
        from sajha.connectors import store, guard
        conn, _ = store.get(source['connector'])
        return guard.DIALECTS.get(conn.kind, '') if conn is not None else ''
    return 'duckdb'


def _strings(v: Any, what: str) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list) and all(isinstance(x, (str, int, float)) for x in v):
        return [str(x) for x in v]
    raise MetricError(f'{what} must be a list of text')


def parse(doc: Any, file: str = '') -> Metric:
    """One metric from its YAML mapping, with the checks that need no other metric and no source."""
    if not isinstance(doc, dict):
        raise MetricError('a metric is a mapping (name, source, measure, ...)')
    name = doc.get('name')
    if not isinstance(name, str) or not _NAME.match(name) or '__' in name:
        raise MetricError(f'name {name!r}: lower case letters, digits and _, a letter first, at most 64, no __')
    known = {'name', 'title', 'description', 'owner', 'source', 'measure', 'time', 'dimensions', 'filters',
             'format', 'roles', 'tags'}
    extra = sorted(set(doc) - known)
    if extra:
        raise MetricError(f'{name}: unknown key(s) {", ".join(extra)}')
    m = Metric(name=name, file=file,
               title=str(doc.get('title') or ''), description=str(doc.get('description') or ''),
               owner=str(doc.get('owner') or ''),
               roles=_strings(doc.get('roles'), f'{name}: roles'), tags=_strings(doc.get('tags'), f'{name}: tags'))
    fmt = doc.get('format') or {}
    if not isinstance(fmt, dict):
        raise MetricError(f'{name}: format must be a mapping')
    m.format = {k: fmt[k] for k in ('unit', 'currency', 'decimals') if k in fmt}

    measure = doc.get('measure')
    if not isinstance(measure, dict):
        raise MetricError(f'{name}: measure is required ({{sql, type}} or {{type: ratio, ratio: ...}})')
    m.type = str(measure.get('type') or 'sum').lower()
    if m.type not in TYPES:
        raise MetricError(f'{name}: measure.type must be one of {", ".join(TYPES)}')
    source = doc.get('source')
    if m.type == 'ratio':
        ratio = measure.get('ratio')
        if not isinstance(ratio, dict) or not all(isinstance(ratio.get(k), str) for k in ('numerator', 'denominator')):
            raise MetricError(f'{name}: a ratio needs ratio: {{numerator: <metric>, denominator: <metric>}}')
        m.numerator, m.denominator = ratio['numerator'], ratio['denominator']
        if measure.get('sql'):
            raise MetricError(f'{name}: a ratio is defined by two metrics, not by sql')
    else:
        if not isinstance(source, dict):
            raise MetricError(f'{name}: source is required')
        m.measure_sql = measure.get('sql') if isinstance(measure.get('sql'), str) else ''
        if not m.measure_sql:
            raise MetricError(f'{name}: measure.sql is required')
    if source is not None:
        if not isinstance(source, dict):
            raise MetricError(f'{name}: source must be a mapping')
        given = [k for k in SOURCE_KEYS if source.get(k)]
        if len(given) != 1:
            raise MetricError(f'{name}: source needs exactly one of connector, olap_dataset, duckdb_table, loaded')
        if given[0] == 'loaded':
            raise MetricError(f'{name}: source loaded (a caller\'s loaded tool result) is not built yet')
        m.source = {k: str(v) for k, v in source.items() if k in SOURCE_KEYS + ('table',) and v}
        if given[0] == 'connector':
            if not _TABLE.match(m.source.get('table', '')):
                raise MetricError(f'{name}: a connector source needs table (schema.table or table)')
        elif 'table' in m.source:
            raise MetricError(f'{name}: table goes with a connector source only')
        if given[0] == 'duckdb_table' and not _COLUMN.match(m.source['duckdb_table']):
            raise MetricError(f'{name}: duckdb_table must be a table name')

    time_spec = doc.get('time')
    if time_spec is not None:
        if not isinstance(time_spec, dict) or not _COLUMN.match(str(time_spec.get('column') or '')):
            raise MetricError(f'{name}: time needs column (a column name)')
        m.time_column = time_spec['column']
        grains = _strings(time_spec.get('grains'), f'{name}: time.grains') or list(m.grains)
        bad = [g for g in grains if g not in ('day', 'week', 'month', 'quarter', 'year')]
        if bad:
            raise MetricError(f'{name}: unknown grain(s) {", ".join(bad)}')
        m.grains = tuple(grains)
        fs = time_spec.get('fiscal_year_start', 1)
        if not isinstance(fs, int) or not 1 <= fs <= 12:
            raise MetricError(f'{name}: time.fiscal_year_start is a month number, 1 to 12')
        m.fiscal_year_start = fs
    elif m.type != 'ratio':
        raise MetricError(f'{name}: time is required (time: {{column: ...}})')

    dims = doc.get('dimensions')
    if dims is not None:
        if not isinstance(dims, list):
            raise MetricError(f'{name}: dimensions must be a list')
        seen = set()
        for d in dims:
            if not isinstance(d, dict) or not _COLUMN.match(str(d.get('name') or '')):
                raise MetricError(f'{name}: each dimension needs name (letters, digits, _)')
            col = str(d.get('column') or d['name'])
            if not _COLUMN.match(col):
                raise MetricError(f'{name}: dimension {d["name"]}: column must be a column name')
            if d['name'] in seen or d['name'].lower() in RESERVED:
                raise MetricError(f'{name}: dimension name {d["name"]} is repeated or reserved')
            seen.add(d['name'])
            m.dimensions.append(Dimension(d['name'], col, tuple(_strings(d.get('values'), 'values')),
                                          str(d.get('description') or '')))
    m.filters = _strings(doc.get('filters'), f'{name}: filters')
    return m


def _finish(m: Metric, by_name: Dict[str, Metric]) -> None:
    """Resolve a ratio and check every expression (needs the other metrics and the source's dialect)."""
    if m.type == 'ratio':
        num, den = by_name.get(m.numerator), by_name.get(m.denominator)
        for role, ref, other in (('numerator', m.numerator, num), ('denominator', m.denominator, den)):
            if other is None:
                raise MetricError(f'{m.name}: {role} {ref!r} is not a metric')
            if other.type == 'ratio':
                raise MetricError(f'{m.name}: {role} {ref} is itself a ratio')
        if num.source != den.source or num.time_column != den.time_column:
            raise MetricError(f'{m.name}: numerator and denominator must share source and time column')
        if sorted(num.filters) != sorted(den.filters):
            raise MetricError(f'{m.name}: numerator and denominator must have the same fixed filters')
        if m.source and m.source != num.source:
            raise MetricError(f'{m.name}: a ratio\'s source is its numerator\'s')
        m.source = dict(num.source)
        m.time_column = m.time_column or num.time_column
        if m.time_column != num.time_column:
            raise MetricError(f'{m.name}: a ratio\'s time column is its numerator\'s')
        if m.fiscal_year_start == 1:
            m.fiscal_year_start = num.fiscal_year_start
        m.filters = list(num.filters) + [f for f in m.filters if f not in num.filters]
        if not m.dimensions:
            dd = {d.name: d for d in den.dimensions}
            m.dimensions = [d for d in num.dimensions if dd.get(d.name) == d]
        m.num_sql, m.den_sql = num.measure_sql, den.measure_sql
        m.format = m.format or {}
        m.owner = m.owner or num.owner
    dialect = _dialect(m.source)
    cols: Set[str] = set()
    if m.type == 'ratio':
        cols |= check_fragment(m.num_sql, f'measure of {m.numerator}', dialect)
        cols |= check_fragment(m.den_sql, f'measure of {m.denominator}', dialect)
    else:
        cols |= check_fragment(m.measure_sql, 'measure.sql', dialect)
    for i, f in enumerate(m.filters):
        cols |= check_fragment(f, f'filter {i + 1}', dialect)
    cols |= {m.time_column.lower()} | {d.column.lower() for d in m.dimensions}
    m.columns = cols


# ── the loaded set ───────────────────────────────────────────────────────

def metrics_dir() -> str:
    from sajha.core.config import _get
    return (_get('bi.metrics_dir', 'config/bi/metrics') or 'config/bi/metrics').rstrip('/')


class Registry:
    """The metrics of ``bi.metrics_dir``, re-read when the listing or a file's time changes."""

    CHECK_SECONDS = 2.0

    def __init__(self, directory: Optional[str] = None):
        self._dir = directory
        self._lock = threading.RLock()
        self._stamps: Optional[Tuple] = None
        self._checked = 0.0
        self.metrics: Dict[str, Metric] = {}
        self.refused: Dict[str, str] = {}

    @property
    def directory(self) -> str:
        return self._dir or metrics_dir()

    def _listing(self) -> Tuple:
        from sajha.core.storage import get_storage
        st = get_storage()
        out = []
        for p in st.list_files(self.directory, '*'):
            if p.endswith(('.yaml', '.yml')):
                try:
                    out.append((p, st.get_modified_time(p)))
                except Exception:
                    out.append((p, 0.0))
        return tuple(sorted(out))

    def ensure(self, force: bool = False) -> 'Registry':
        with self._lock:
            now = time.monotonic()
            if not force and self._stamps is not None and now - self._checked < self.CHECK_SECONDS:
                return self
            self._checked = now
            try:
                listing = self._listing()
            except Exception as e:
                logger.warning(f'bi: cannot list {self.directory}: {e}')
                listing = ()
            if force or listing != self._stamps:
                self._load([p for p, _ in listing])
                self._stamps = listing
            return self

    def _load(self, paths: List[str]) -> None:
        import yaml
        from sajha.core.storage import get_storage
        st = get_storage()
        parsed: Dict[str, Metric] = {}
        refused: Dict[str, str] = {}
        for p in paths:
            try:
                docs = yaml.safe_load(st.read_text(p))
            except Exception as e:
                refused[p] = f'cannot read it: {str(e).splitlines()[0][:300]}'
                continue
            docs = docs if isinstance(docs, list) else [docs]
            for doc in docs:
                try:
                    m = parse(doc, p)
                except MetricError as e:
                    refused[p] = str(e)
                    continue
                if m.name in parsed:
                    refused[p] = f'metric {m.name} is already defined in {parsed[m.name].file}'
                    continue
                parsed[m.name] = m
        good: Dict[str, Metric] = {}
        for name, m in parsed.items():
            try:
                _finish(m, parsed)
                good[name] = m
            except MetricError as e:
                refused[m.file] = str(e)
        self.metrics, self.refused = good, refused
        self._report(refused)
        logger.info(f'bi: {len(good)} metrics loaded from {self.directory}'
                    + (f', {len(refused)} file(s) refused' if refused else ''))

    def _report(self, refused: Dict[str, str]) -> None:
        try:
            from sajha import notices
            for n in notices.list_notices(state='open', source='bi'):
                nid = str(n.get('id') or '')
                if nid.startswith(NOTICE_PREFIX) and nid[len(NOTICE_PREFIX):] not in refused:
                    notices.clear_notice(nid)
            for path, why in sorted(refused.items()):
                logger.warning(f'bi: metric file {path} refused: {why}')
                notices.raise_notice(NOTICE_PREFIX + path, severity='warning', source='bi',
                                     title=f'A metric definition in {path} is refused',
                                     detail=why + '. The metric is left out of bi_list_metrics and the bi_* '
                                                  'tools until the file is fixed.',
                                     link='/help/guides/Business%20Intelligence.md', ttl_minutes=0)
        except Exception:
            pass

    def get(self, name: Any) -> Metric:
        self.ensure()
        m = self.metrics.get(name) if isinstance(name, str) else None
        if m is None:
            raise MetricError(f'unknown metric {name!r}: call bi_list_metrics for the metrics you may query')
        return m


_registry = Registry()


def registry() -> Registry:
    return _registry


def set_registry(reg: Registry) -> None:
    """Tests: use another metrics directory."""
    global _registry
    _registry = reg


# ── governance ───────────────────────────────────────────────────────────

def _caller():
    from sajha.observability.caller import current
    return current()


def _is_admin(c) -> bool:
    return bool(getattr(c, 'is_admin', False)) or 'admin' in (getattr(c, 'roles', ()) or ())


def may_query(m: Metric, caller=None) -> bool:
    c = caller or _caller()
    if _is_admin(c):
        return True
    if m.roles and not set(m.roles) & set(getattr(c, 'roles', ()) or ()):
        return False
    cid = m.source.get('connector')
    if cid and c.can_execute(f'{cid}__list_tables') is False:
        return False
    return True


def is_owner(m: Metric, caller=None) -> bool:
    c = caller or _caller()
    return _is_admin(c) or bool(m.owner) and (m.owner == getattr(c, 'user_id', '')
                                               or m.owner in (getattr(c, 'roles', ()) or ()))


def visible(caller=None) -> List[Metric]:
    reg = registry().ensure()
    return [m for _, m in sorted(reg.metrics.items()) if may_query(m, caller)]


def require(name: Any, caller=None) -> Metric:
    """The metric the caller may query; an unknown and a forbidden metric get the same answer."""
    try:
        m = registry().get(name)
    except MetricError:
        raise
    if not may_query(m, caller):
        raise MetricError(f'unknown metric {name!r}: call bi_list_metrics for the metrics you may query')
    return m
