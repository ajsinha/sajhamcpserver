"""
SAJHA MCP Server — Data Connectors: PostgreSQL, Redshift and pgvector (psycopg2, or psycopg 3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

PostgreSQL sessions start read-only (``default_transaction_read_only=on`` as a start-up
option, and ``readonly`` on the session), with ``statement_timeout`` and the search path set
to the allowed schemas. Redshift does not take start-up options, so the same settings are
made with ``SET`` after connecting.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sajha.connectors.drivers.base import SQLDriver, info_schema_describe, installed, require
from sajha.connectors.model import Connection

_SIMPLE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class PostgresDriver(SQLDriver):
    kind = 'postgresql'
    module = 'psycopg2'
    pip = 'psycopg2-binary'
    paramstyle = 'pyformat'
    default_schema = 'public'
    default_port = 5432
    startup_options = True

    def load(self):
        if not installed('psycopg2') and installed('psycopg'):
            return require(self.kind, 'psycopg', 'psycopg[binary]')
        return require(self.kind, self.module, self.pip)

    def _ms(self, conn: Connection) -> int:
        return int(conn.timeout_seconds * 1000)

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        o = conn.options
        kw: Dict[str, Any] = {
            'host': o.get('host', 'localhost'), 'port': int(o.get('port') or self.default_port),
            'dbname': o.get('database') or o.get('dbname') or '', 'user': o.get('user') or '',
            'connect_timeout': int(o.get('connect_timeout') or 10),
            'application_name': str(o.get('application_name') or 'sajha-connector'),
        }
        pw = secret('password')
        if pw:
            kw['password'] = pw
        for k in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'target_session_attrs'):
            if o.get(k):
                kw[k] = o[k]
        if self.startup_options:
            opts = ['-c default_transaction_read_only=on', f'-c statement_timeout={self._ms(conn)}',
                    f'-c idle_in_transaction_session_timeout={max(self._ms(conn) * 2, 60000)}']
            schemas = [s for s in conn.allow_schemas if _SIMPLE.match(s)]
            if schemas and len(schemas) == len(conn.allow_schemas):
                opts.append('-c search_path=' + ','.join(schemas))
            kw['options'] = ' '.join(opts)
        return mod.connect(**kw)

    def prepare(self, dbc: Any, conn: Connection) -> None:
        if hasattr(dbc, 'set_session'):                          # psycopg2
            dbc.set_session(readonly=True, autocommit=False)
        elif hasattr(dbc, 'read_only'):                          # psycopg 3
            dbc.read_only = True
        if not self.startup_options:
            cur = dbc.cursor()
            try:
                cur.execute('SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY')
                cur.execute(f'SET statement_timeout TO {self._ms(conn)}')
            finally:
                cur.close()
            dbc.commit()

    def server_version(self, dbc, conn) -> str:
        return str(self.rows(dbc, 'SELECT version()')[0][0])

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, """
            SELECT n.nspname, c.relname,
                   CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
                                  WHEN 'f' THEN 'foreign table' ELSE 'table' END,
                   obj_description(c.oid, 'pg_class')
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg\\_toast%%' AND n.nspname NOT LIKE 'pg\\_temp%%'
            ORDER BY 1, 2""", {})
        return [{'schema': r[0], 'name': r[1], 'type': r[2], 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        p = {'s': schema, 't': table}
        rows = self.rows(dbc, """
            SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
                   pg_catalog.col_description(c.oid, a.attnum)
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %(s)s AND c.relname = %(t)s AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum""", p)
        pk = self.rows(dbc, """
            SELECT a.attname FROM pg_catalog.pg_index i
            JOIN pg_catalog.pg_class c ON c.oid = i.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE i.indisprimary AND n.nspname = %(s)s AND c.relname = %(t)s""", p)
        return {'columns': [{'name': r[0], 'type': r[1], 'nullable': bool(r[2]), 'comment': r[3] or ''}
                            for r in rows],
                'primary_key': [r[0] for r in pk]}


class PgVectorDriver(PostgresDriver):
    kind = 'pgvector'


class RedshiftDriver(PostgresDriver):
    kind = 'redshift'
    default_port = 5439
    startup_options = False

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, """
            SELECT table_schema, table_name, CASE table_type WHEN 'VIEW' THEN 'view' ELSE 'table' END
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_schema NOT LIKE 'pg\\_%%'
            ORDER BY 1, 2""", {})
        return [{'schema': r[0], 'name': r[1], 'type': r[2], 'comment': ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        return {'columns': info_schema_describe(self, dbc, schema, table), 'primary_key': []}
