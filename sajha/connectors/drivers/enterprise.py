"""
SAJHA MCP Server — Data Connectors: SQL Server (pyodbc) and Oracle (python-oracledb, thin mode).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SQL Server has no session-level read-only switch: the connection asks for
``ApplicationIntent=ReadOnly`` (routed to a readable secondary where one exists) and the login
should hold only ``db_datareader``; the statement guard is the other wall. Oracle runs every
statement in ``SET TRANSACTION READ ONLY``; ``call_timeout`` bounds its time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.connectors.drivers.base import SQLDriver
from sajha.connectors.model import Connection


def _odbc_value(v: str) -> str:
    """An ODBC connection-string value, braced so ; and } inside it cannot end the value."""
    return '{' + str(v).replace('}', '}}') + '}'


class SQLServerDriver(SQLDriver):
    kind = 'sqlserver'
    module = 'pyodbc'
    pip = 'pyodbc'
    paramstyle = 'qmark'
    quote_char = '['
    limit_style = 'top'
    default_schema = 'dbo'

    def connection_string(self, conn: Connection, secret) -> str:
        o = conn.options
        server = str(o.get('host', 'localhost'))
        if o.get('port'):
            server += f",{int(o['port'])}"
        parts = {
            'DRIVER': o.get('odbc_driver') or 'ODBC Driver 18 for SQL Server', 'SERVER': server,
            'DATABASE': o.get('database') or '', 'ApplicationIntent': 'ReadOnly',
            'Encrypt': o.get('encrypt', 'yes'), 'TrustServerCertificate': o.get('trust_server_certificate', 'no'),
            'APP': 'sajha-connector',
        }
        if o.get('authentication'):
            parts['Authentication'] = o['authentication']
        if o.get('user'):
            parts['UID'] = o['user']
            parts['PWD'] = secret('password') or ''
        elif not o.get('authentication'):
            parts['Trusted_Connection'] = 'yes'
        return ';'.join(f'{k}={_odbc_value(v)}' for k, v in parts.items() if v != '')

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        return mod.connect(self.connection_string(conn, secret), autocommit=False,
                           timeout=int(conn.options.get('connect_timeout') or 10))

    def prepare(self, dbc: Any, conn: Connection) -> None:
        try:
            dbc.timeout = int(conn.timeout_seconds)          # pyodbc: per-statement query timeout
        except Exception:
            pass

    def cancel(self, dbc: Any) -> None:
        cur = getattr(dbc, '_sajha_cursor', None)
        if cur is not None and hasattr(cur, 'cancel'):
            cur.cancel()

    def execute(self, cur, sql, params, conn) -> None:
        try:
            cur.connection._sajha_cursor = cur
        except Exception:
            pass
        super().execute(cur, sql, params, conn)

    def server_version(self, dbc, conn) -> str:
        return str(self.rows(dbc, 'SELECT @@VERSION')[0][0]).split('\n', 1)[0]

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, """
            SELECT s.name, o.name, CASE o.type WHEN 'V' THEN 'view' ELSE 'table' END,
                   CAST(ep.value AS NVARCHAR(4000))
            FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
            LEFT JOIN sys.extended_properties ep
              ON ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.class = 1 AND ep.name = 'MS_Description'
            WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
            ORDER BY 1, 2""")
        return [{'schema': r[0], 'name': r[1], 'type': r[2], 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        target = f'{self.quote(schema)}.{self.quote(table)}'
        rows = self.rows(dbc, """
            SELECT c.name, t.name, c.is_nullable, CAST(ep.value AS NVARCHAR(4000))
            FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id
            LEFT JOIN sys.extended_properties ep
              ON ep.major_id = c.object_id AND ep.minor_id = c.column_id AND ep.class = 1
             AND ep.name = 'MS_Description'
            WHERE c.object_id = OBJECT_ID(?) ORDER BY c.column_id""", [target])
        pk = self.rows(dbc, """
            SELECT c.name FROM sys.indexes i
            JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.is_primary_key = 1 AND i.object_id = OBJECT_ID(?) ORDER BY ic.key_ordinal""", [target])
        return {'columns': [{'name': r[0], 'type': r[1], 'nullable': bool(r[2]), 'comment': r[3] or ''}
                            for r in rows],
                'primary_key': [r[0] for r in pk]}


class OracleDriver(SQLDriver):
    kind = 'oracle'
    module = 'oracledb'
    pip = 'oracledb'
    paramstyle = 'named'
    limit_style = 'fetch'

    def default_schema_for(self, conn: Connection) -> str:
        return str(conn.options.get('schema') or conn.options.get('user') or '').upper()

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        o = conn.options
        dsn = o.get('dsn')
        if not dsn:
            dsn = f"{o.get('host', 'localhost')}:{int(o.get('port') or 1521)}/{o.get('service_name') or o.get('database') or ''}"
        return mod.connect(user=o.get('user') or '', password=secret('password') or '', dsn=dsn)

    def prepare(self, dbc: Any, conn: Connection) -> None:
        try:
            dbc.call_timeout = int(conn.timeout_seconds * 1000)
        except Exception:
            pass

    def begin(self, dbc: Any, conn: Connection) -> None:
        cur = dbc.cursor()
        try:
            cur.execute('SET TRANSACTION READ ONLY')
        finally:
            cur.close()

    def server_version(self, dbc, conn) -> str:
        return 'Oracle ' + str(getattr(dbc, 'version', '') or '')

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, """
            SELECT t.owner, t.table_name, t.table_type, t.comments FROM all_tab_comments t
            WHERE t.owner IN (SELECT username FROM all_users WHERE oracle_maintained = 'N')
            ORDER BY 1, 2""")
        return [{'schema': r[0], 'name': r[1], 'type': 'view' if str(r[2]).upper() == 'VIEW' else 'table',
                 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        p = {'s': schema, 't': table}
        rows = self.rows(dbc, """
            SELECT c.column_name, c.data_type, c.nullable, cc.comments FROM all_tab_columns c
            LEFT JOIN all_col_comments cc
              ON cc.owner = c.owner AND cc.table_name = c.table_name AND cc.column_name = c.column_name
            WHERE c.owner = :s AND c.table_name = :t ORDER BY c.column_id""", p)
        pk = self.rows(dbc, """
            SELECT cc.column_name FROM all_constraints k
            JOIN all_cons_columns cc ON cc.owner = k.owner AND cc.constraint_name = k.constraint_name
            WHERE k.constraint_type = 'P' AND k.owner = :s AND k.table_name = :t ORDER BY cc.position""", p)
        return {'columns': [{'name': r[0], 'type': r[1], 'nullable': str(r[2]).upper() == 'Y', 'comment': r[3] or ''}
                            for r in rows],
                'primary_key': [r[0] for r in pk]}
