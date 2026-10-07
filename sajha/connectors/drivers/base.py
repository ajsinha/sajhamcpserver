"""
SAJHA MCP Server — Data Connectors: the SQL driver interface.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A driver knows one kind of database: how to open a DB-API connection (credentials come from
secret references, or the caller's connected-account token), how to make the session
read-only and time-limited, how to list tables and describe one, how to quote identifiers,
and how to cancel a running statement. Every Python driver package is imported on first use
only; a missing one raises :class:`DriverMissing` naming the package to install.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.connectors.model import Connection

SecretFn = Callable[[str], str]


class DriverMissing(RuntimeError):
    """The Python package a connector kind needs is not installed."""


class ConnectorError(RuntimeError):
    """A data-connection call failed (connection refused, SQL error, ...); the message is safe to show."""


class QueryTimeout(ConnectorError):
    """A statement ran past the connection's time limit and was cancelled."""


def require(kind: str, module: str, pip: str):
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise DriverMissing(f"The {kind} connector needs the Python package {module.split('.')[0]}"
                            f"{'' if module.count('.') == 0 else ' (' + module + ')'}: pip install '{pip}'"
                            f" ({e.__class__.__name__}: {e})") from None


def installed(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


_TYPE_INT = re.compile(r'^(tiny|small|medium|big)?int(eger)?\d*\b|^(small|big)?serial|^int[248]$|^long$|^byte$|^short$',
                       re.IGNORECASE)
_TYPE_NUM = re.compile(r'^(numeric|decimal|real|double|float|money|number|smallmoney|dec\b|fixed)', re.IGNORECASE)


def json_schema_for(db_type: str) -> Dict[str, Any]:
    """A JSON Schema for a value of a database column type (best effort, used by curated views)."""
    t = (db_type or '').strip().lower()
    if _TYPE_INT.match(t) or re.match(r'^number\(\s*\d+\s*(,\s*0\s*)?\)$', t):
        return {'type': 'integer'}
    if _TYPE_NUM.match(t):
        return {'type': 'number'}
    if t.startswith(('bool', 'bit')):
        return {'type': 'boolean'}
    if t == 'date':
        return {'type': 'string', 'format': 'date'}
    if t.startswith(('timestamp', 'datetime', 'smalldatetime')):
        return {'type': 'string', 'format': 'date-time'}
    return {'type': 'string'}


class SQLDriver:
    kind = ''
    module = ''
    pip = ''
    paramstyle = 'pyformat'          # pyformat | named | qmark | dollar | at
    quote_char = '"'
    limit_style = 'limit'            # limit | top | fetch
    default_schema = ''
    #: placeholders for the driver's own introspection SQL: name -> placeholder text
    #: (introspection uses the same paramstyle as caller SQL)

    # ── connections ────────────────────────────────────────────────
    def load(self):
        return require(self.kind, self.module, self.pip)

    def connect(self, conn: Connection, secret: SecretFn, token: Optional[str]) -> Any:
        raise NotImplementedError

    def prepare(self, dbc: Any, conn: Connection) -> None:
        """Session set-up after connecting: read-only, timeouts."""

    def begin(self, dbc: Any, conn: Connection) -> None:
        """Before each statement (a read-only transaction where the database needs one per transaction)."""

    def end(self, dbc: Any) -> None:
        """After each statement: end the transaction."""
        try:
            dbc.rollback()
        except Exception:
            pass

    def cancel(self, dbc: Any) -> None:
        """Best-effort cancel of the running statement (called from the watchdog thread)."""
        fn = getattr(dbc, 'cancel', None) or getattr(dbc, 'interrupt', None)
        if callable(fn):
            fn()

    def close(self, dbc: Any) -> None:
        try:
            dbc.close()
        except Exception:
            pass

    def ping(self, dbc: Any) -> bool:
        return True

    def server_version(self, dbc: Any, conn: Connection) -> str:
        return ''

    def extra_check(self, dbc: Any, sql: str) -> None:
        """A second, database-native check of caller SQL (DuckDB's parser)."""

    def cursor(self, dbc: Any) -> Any:
        return dbc.cursor()

    def close_cursor(self, cur: Any) -> None:
        try:
            cur.close()
        except Exception:
            pass

    def execute(self, cur: Any, sql: str, params: Any, conn: Connection) -> None:
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)

    def is_timeout(self, error: BaseException) -> bool:
        text = str(error).lower()
        return any(s in text for s in ('statement timeout', 'canceling statement', 'cancelled', 'canceled',
                                       'max_execution_time', 'maximum statement execution time', 'interrupted',
                                       'timeout', 'timed out', 'ora-01013', 'query execution was interrupted'))

    # ── SQL text ───────────────────────────────────────────────────
    def quote(self, name: str) -> str:
        from sajha.connectors.guard import quote
        return quote(name, self.quote_char)

    def qualified(self, schema: str, table: str) -> str:
        return f'{self.quote(schema)}.{self.quote(table)}' if schema else self.quote(table)

    def sample_sql(self, schema: str, table: str, columns: List[str], n: int) -> str:
        cols = ', '.join(self.quote(c) for c in columns) if columns else '*'
        target = self.qualified(schema, table)
        if self.limit_style == 'top':
            return f'SELECT TOP ({int(n)}) {cols} FROM {target}'
        if self.limit_style == 'fetch':
            return f'SELECT {cols} FROM {target} FETCH FIRST {int(n)} ROWS ONLY'
        return f'SELECT {cols} FROM {target} LIMIT {int(n)}'

    def ph(self, name: str) -> str:
        """The placeholder for a bound parameter called ``name`` in SQL this driver writes."""
        return {'pyformat': f'%({name})s', 'named': f':{name}', 'qmark': '?', 'dollar': f'${name}',
                'at': f'@{name}'}[self.paramstyle]

    def bind(self, names_values: List[Tuple[str, Any]]) -> Any:
        """The parameters object for SQL written with :meth:`ph` (in order of appearance)."""
        if self.paramstyle == 'qmark':
            return [v for _, v in names_values]
        return {k: v for k, v in names_values}

    # ── catalog ────────────────────────────────────────────────────
    def list_tables(self, dbc: Any, conn: Connection) -> List[Dict[str, Any]]:
        """[{schema, name, type, comment}] of every table and view (filtered by the caller)."""
        raise NotImplementedError

    def describe(self, dbc: Any, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        """{columns: [{name, type, nullable, comment}], primary_key: [..]}."""
        raise NotImplementedError

    def default_schema_for(self, conn: Connection) -> str:
        return str(conn.options.get('schema') or self.default_schema or '')

    def catalog_names(self, conn: Connection) -> List[str]:
        """Names a three-part table reference may use as its first part (this database)."""
        out = []
        for k in ('database', 'catalog', 'project'):
            if conn.options.get(k):
                out.append(str(conn.options[k]).lower())
        return out

    # helpers
    def rows(self, dbc: Any, sql: str, params: Any = None) -> List[tuple]:
        cur = dbc.cursor()
        try:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            return [tuple(r) for r in cur.fetchall()]
        finally:
            try:
                cur.close()
            except Exception:
                pass


def info_schema_describe(drv: SQLDriver, dbc, schema: str, table: str, comment_col: Optional[str] = None,
                         prefix: str = '') -> List[Dict[str, Any]]:
    """Columns from ``information_schema.columns`` (with an optional comment column)."""
    comment = f', {comment_col}' if comment_col else ', NULL'
    sql = (f'SELECT column_name, data_type, is_nullable{comment}, ordinal_position '
           f'FROM {prefix}information_schema.columns WHERE table_schema = {drv.ph("s")} '
           f'AND table_name = {drv.ph("t")} ORDER BY ordinal_position')
    rows = drv.rows(dbc, sql, drv.bind([('s', schema), ('t', table)]))
    return [{'name': r[0], 'type': str(r[1] or ''), 'nullable': str(r[2]).upper() in ('YES', 'Y', 'TRUE', '1'),
             'comment': r[3] or ''} for r in rows]
