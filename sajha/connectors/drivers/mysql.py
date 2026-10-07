"""
SAJHA MCP Server — Data Connectors: MySQL and MariaDB (PyMySQL).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every session is ``TRANSACTION READ ONLY`` and every statement runs inside
``START TRANSACTION READ ONLY``; MySQL's ``MAX_EXECUTION_TIME`` (MariaDB's
``max_statement_time``) and the socket read timeout bound the time. Backslash escapes are
forced on (``NO_BACKSLASH_ESCAPES`` removed from ``sql_mode``) so string literals end where
the statement guard's tokenizer says they do; multi-statement execution is never enabled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.connectors.drivers.base import SQLDriver, info_schema_describe
from sajha.connectors.model import Connection

SYSTEM_SCHEMAS = ('mysql', 'information_schema', 'performance_schema', 'sys')


class MySQLDriver(SQLDriver):
    kind = 'mysql'
    module = 'pymysql'
    pip = 'pymysql'
    paramstyle = 'pyformat'
    quote_char = '`'

    def default_schema_for(self, conn: Connection) -> str:
        return str(conn.options.get('database') or '')

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        o = conn.options
        kw: Dict[str, Any] = {
            'host': o.get('host', 'localhost'), 'port': int(o.get('port') or 3306), 'user': o.get('user') or '',
            'password': secret('password') or '', 'charset': o.get('charset', 'utf8mb4'),
            'connect_timeout': int(o.get('connect_timeout') or 10),
            'read_timeout': conn.timeout_seconds + 5, 'write_timeout': conn.timeout_seconds + 5,
            'autocommit': False, 'client_flag': 0,
        }
        if o.get('database'):
            kw['database'] = o['database']
        if o.get('ssl_ca'):
            kw['ssl'] = {'ca': o['ssl_ca']}
        dbc = mod.connect(**kw)
        try:
            dbc._sajha_kw = dict(kw, read_timeout=10)     # for KILL QUERY from a second connection
        except Exception:
            pass
        return dbc

    def _mariadb(self, dbc) -> bool:
        info = getattr(dbc, 'get_server_info', None)
        try:
            return 'mariadb' in str(info() if callable(info) else '').lower() or self.kind == 'mariadb'
        except Exception:
            return self.kind == 'mariadb'

    def prepare(self, dbc: Any, conn: Connection) -> None:
        cur = dbc.cursor()
        try:
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute("SET SESSION sql_mode = REPLACE(@@sql_mode, 'NO_BACKSLASH_ESCAPES', '')")
            if self._mariadb(dbc):
                cur.execute(f'SET SESSION max_statement_time = {int(conn.timeout_seconds)}')
            else:
                cur.execute(f'SET SESSION MAX_EXECUTION_TIME = {int(conn.timeout_seconds * 1000)}')
        finally:
            cur.close()
        dbc.commit()

    def begin(self, dbc: Any, conn: Connection) -> None:
        cur = dbc.cursor()
        try:
            cur.execute('START TRANSACTION READ ONLY')
        finally:
            cur.close()

    def cancel(self, dbc: Any) -> None:
        """KILL QUERY from a second connection (PyMySQL has no cancel)."""
        tid = getattr(dbc, 'thread_id', None)
        tid = tid() if callable(tid) else tid
        params = getattr(dbc, '_sajha_kw', None)
        if not tid or not params:
            return
        try:
            other = self.load().connect(**params)
            try:
                c = other.cursor()
                c.execute(f'KILL QUERY {int(tid)}')
            finally:
                other.close()
        except Exception:
            pass

    def server_version(self, dbc, conn) -> str:
        return str(self.rows(dbc, 'SELECT VERSION()')[0][0])

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, 'SELECT table_schema, table_name, table_type, table_comment '
                              'FROM information_schema.tables '
                              "WHERE table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys') "
                              'ORDER BY 1, 2', {})
        return [{'schema': r[0], 'name': r[1], 'type': 'view' if 'VIEW' in str(r[2]).upper() else 'table',
                 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        cols = info_schema_describe(self, dbc, schema, table, 'column_comment')
        pk = self.rows(dbc, 'SELECT column_name FROM information_schema.key_column_usage '
                            "WHERE constraint_name = 'PRIMARY' AND table_schema = %(s)s AND table_name = %(t)s "
                            'ORDER BY ordinal_position', {'s': schema, 't': table})
        return {'columns': cols, 'primary_key': [r[0] for r in pk]}


class MariaDBDriver(MySQLDriver):
    kind = 'mariadb'
