"""
SAJHA MCP Server — Data Connectors: SQLite and DuckDB database files.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SQLite files are opened ``mode=ro`` (the file cannot be written through this connection) with
``PRAGMA query_only``; a progress handler enforces the deadline. DuckDB files are opened
``read_only=True`` with ``enable_external_access=false`` (no file, HTTP or S3 functions) and
the configuration locked, and DuckDB's own parser checks caller SQL a second time
(sajha/olap/sql_safety.read_only_sql, the check the duckdb_* tools use).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote as urlquote

from sajha.connectors.drivers.base import ConnectorError, SQLDriver, info_schema_describe
from sajha.connectors.model import Connection


def _path(conn: Connection) -> str:
    from sajha.core.config import resolve_placeholders
    p = resolve_placeholders(str(conn.options.get('path') or ''))
    if not p or p == ':memory:':
        raise ConnectorError('options.path: a database file is required')
    p = os.path.abspath(os.path.expanduser(p))
    if not os.path.isfile(p):
        raise ConnectorError(f'database file not found: {p}')
    return p


class SQLiteDriver(SQLDriver):
    kind = 'sqlite'
    module = 'sqlite3'
    pip = 'sqlite3 (part of Python)'
    paramstyle = 'named'
    default_schema = 'main'

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        sqlite3 = self.load()
        dbc = sqlite3.connect(f'file:{urlquote(_path(conn))}?mode=ro', uri=True, check_same_thread=False,
                              timeout=5)
        return dbc

    def prepare(self, dbc: Any, conn: Connection) -> None:
        dbc.execute('PRAGMA query_only = ON')
        try:
            dbc.execute('PRAGMA trusted_schema = OFF')
        except Exception:
            pass
        state = {'deadline': 0.0}
        dbc_state[id(dbc)] = state

        def progress():
            return 1 if state['deadline'] and time.monotonic() > state['deadline'] else 0
        dbc.set_progress_handler(progress, 2000)

    def begin(self, dbc: Any, conn: Connection) -> None:
        st = dbc_state.get(id(dbc))
        if st is not None:
            st['deadline'] = time.monotonic() + conn.timeout_seconds

    def end(self, dbc: Any) -> None:
        st = dbc_state.get(id(dbc))
        if st is not None:
            st['deadline'] = 0.0
        try:
            dbc.rollback()
        except Exception:
            pass

    def close(self, dbc: Any) -> None:
        dbc_state.pop(id(dbc), None)
        super().close(dbc)

    def cancel(self, dbc: Any) -> None:
        dbc.interrupt()

    def server_version(self, dbc, conn) -> str:
        return 'SQLite ' + str(self.rows(dbc, 'SELECT sqlite_version()')[0][0])

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                              "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name")
        return [{'schema': 'main', 'name': r[0], 'type': r[1], 'comment': ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        rows = self.rows(dbc, f'PRAGMA {self.quote(schema or "main")}.table_info({self.quote(table)})')
        cols = [{'name': r[1], 'type': r[2] or '', 'nullable': not r[3], 'comment': ''} for r in rows]
        pk = [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: r[5])]
        return {'columns': cols, 'primary_key': pk}


dbc_state: Dict[int, Dict[str, float]] = {}


class DuckDBDriver(SQLDriver):
    kind = 'duckdb'
    module = 'duckdb'
    pip = 'duckdb'
    paramstyle = 'dollar'
    default_schema = 'main'

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        duckdb = self.load()
        path = _path(conn)
        config = {'enable_external_access': False, 'autoinstall_known_extensions': False,
                  'autoload_known_extensions': False, 'lock_configuration': True}
        try:
            return duckdb.connect(path, read_only=True, config=config)
        except duckdb.Error as e:
            if 'unrecognized configuration' not in str(e).lower() and 'invalid' not in str(e).lower():
                raise
            return duckdb.connect(path, read_only=True, config={'enable_external_access': False})

    def end(self, dbc: Any) -> None:
        pass                                    # autocommit; the database is read-only

    def cancel(self, dbc: Any) -> None:
        dbc.interrupt()

    def extra_check(self, dbc: Any, sql: str) -> None:
        from sajha.olap.sql_safety import OLAPQueryError, read_only_sql
        try:
            read_only_sql(dbc, sql)
        except OLAPQueryError as e:
            from sajha.connectors.guard import GuardError
            raise GuardError(str(e)) from None

    def cursor(self, dbc: Any) -> Any:
        return dbc                  # DuckDB's cursor() is a second connection that interrupt() does not reach

    def close_cursor(self, cur: Any) -> None:
        pass

    def server_version(self, dbc, conn) -> str:
        return 'DuckDB ' + str(self.rows(dbc, 'SELECT version()')[0][0])

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        try:
            rows = self.rows(dbc, "SELECT schema_name, table_name, 'table', comment FROM duckdb_tables() "
                                  "WHERE NOT internal UNION ALL "
                                  "SELECT schema_name, view_name, 'view', comment FROM duckdb_views() "
                                  "WHERE NOT internal ORDER BY 1, 2")
        except Exception:
            rows = self.rows(dbc, "SELECT table_schema, table_name, table_type, NULL FROM information_schema.tables "
                                  "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2")
        return [{'schema': r[0], 'name': r[1], 'type': 'view' if 'VIEW' in str(r[2]).upper() else 'table',
                 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        try:
            rows = self.rows(dbc, 'SELECT column_name, data_type, is_nullable, comment FROM duckdb_columns() '
                                  'WHERE schema_name = $s AND table_name = $t ORDER BY column_index',
                             {'s': schema, 't': table})
            cols = [{'name': r[0], 'type': r[1], 'nullable': bool(r[2]), 'comment': r[3] or ''} for r in rows]
        except Exception:
            cols = info_schema_describe(self, dbc, schema, table)
        pk: List[str] = []
        try:
            for r in self.rows(dbc, "SELECT constraint_column_names FROM duckdb_constraints() WHERE schema_name = $s "
                                    "AND table_name = $t AND constraint_type = 'PRIMARY KEY'", {'s': schema, 't': table}):
                pk = list(r[0] or [])
        except Exception:
            pass
        return {'columns': cols, 'primary_key': pk}
