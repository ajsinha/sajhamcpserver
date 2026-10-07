"""
SAJHA MCP Server — Data Connectors: Snowflake, BigQuery and Databricks SQL.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

None of the three has a read-only session: the statement guard and a principal with read
privileges only are the walls (docs/tools/enterprise/Data Connectors Reference Guide.md says
what to grant). Each can sign in as the calling user with their connected-account token
(``auth.type: connected_account``): Snowflake ``authenticator=oauth``, BigQuery OAuth
credentials, a Databricks access token.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sajha.connectors.drivers.base import ConnectorError, SQLDriver, info_schema_describe, require
from sajha.connectors.model import Connection


class SnowflakeDriver(SQLDriver):
    kind = 'snowflake'
    module = 'snowflake.connector'
    pip = 'snowflake-connector-python'
    paramstyle = 'pyformat'
    default_schema = 'PUBLIC'

    def default_schema_for(self, conn: Connection) -> str:
        return str(conn.options.get('schema') or 'PUBLIC')

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        o = conn.options
        kw: Dict[str, Any] = {
            'account': o.get('account') or '', 'user': o.get('user') or '',
            'session_parameters': {'STATEMENT_TIMEOUT_IN_SECONDS': int(conn.timeout_seconds),
                                   'QUERY_TAG': str(o.get('query_tag') or 'sajha-connector')},
            'login_timeout': int(o.get('connect_timeout') or 30), 'network_timeout': conn.timeout_seconds + 30,
            'application': 'SAJHA', 'autocommit': False,
        }
        for k in ('warehouse', 'database', 'schema', 'role', 'host'):
            if o.get(k):
                kw[k] = o[k]
        if token:
            kw['authenticator'] = 'oauth'
            kw['token'] = token
        else:
            pw = secret('password')
            if pw:
                kw['password'] = pw
            if o.get('authenticator'):
                kw['authenticator'] = o['authenticator']
        return mod.connect(**kw)

    def server_version(self, dbc, conn) -> str:
        return 'Snowflake ' + str(self.rows(dbc, 'SELECT CURRENT_VERSION()')[0][0])

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, "SELECT table_schema, table_name, table_type, comment FROM information_schema.tables "
                              "WHERE table_schema <> 'INFORMATION_SCHEMA' ORDER BY 1, 2", {})
        return [{'schema': r[0], 'name': r[1], 'type': 'view' if 'VIEW' in str(r[2]).upper() else 'table',
                 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        return {'columns': info_schema_describe(self, dbc, schema, table, 'comment'), 'primary_key': []}


class BigQueryDriver(SQLDriver):
    kind = 'bigquery'
    module = 'google.cloud.bigquery'
    pip = 'google-cloud-bigquery'
    paramstyle = 'pyformat'
    quote_char = '`'

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        bq = self.load()
        dbapi = require(self.kind, 'google.cloud.bigquery.dbapi', self.pip)
        o = conn.options
        creds = None
        if token:
            oauth2 = require(self.kind, 'google.oauth2.credentials', 'google-auth')
            creds = oauth2.Credentials(token)
        else:
            info = secret('credentials_json')
            if info:
                sa = require(self.kind, 'google.oauth2.service_account', 'google-auth')
                try:
                    creds = sa.Credentials.from_service_account_info(json.loads(info))
                except ValueError as e:
                    raise ConnectorError(f'secrets.credentials_json is not a service-account key: {e}') from None
        client = bq.Client(project=o.get('project') or None, credentials=creds, location=o.get('location') or None)
        return dbapi.connect(client)

    def execute(self, cur, sql, params, conn: Connection) -> None:
        bq = self.load()
        job = bq.QueryJobConfig(use_query_cache=True)
        billed = conn.options.get('maximum_bytes_billed')
        if billed:
            job.maximum_bytes_billed = int(billed)
        try:
            job.job_timeout_ms = int(conn.timeout_seconds * 1000)
        except Exception:
            pass
        cur.execute(sql, params, job_config=job)

    def end(self, dbc) -> None:
        pass                                             # BigQuery has no transaction to close

    def _datasets(self, conn: Connection) -> List[str]:
        ds = list(conn.allow_schemas) or [d.strip() for d in str(conn.options.get('datasets') or '').split(',')
                                          if d.strip()]
        if not ds:
            raise ConnectorError('a BigQuery connection lists its datasets under allow.schemas')
        return ds

    def server_version(self, dbc, conn) -> str:
        return f"BigQuery (project {conn.options.get('project') or 'default'})"

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        out = []
        for ds in self._datasets(conn):
            rows = self.rows(dbc, f'SELECT table_schema, table_name, table_type FROM '
                                  f'{self.quote(ds)}.INFORMATION_SCHEMA.TABLES ORDER BY table_name')
            out += [{'schema': r[0], 'name': r[1], 'type': 'view' if 'VIEW' in str(r[2]).upper() else 'table',
                     'comment': ''} for r in rows]
        return out

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        q = self.quote(schema)
        rows = self.rows(dbc, f"""
            SELECT c.column_name, c.data_type, c.is_nullable, f.description
            FROM {q}.INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN {q}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS f
              ON f.table_name = c.table_name AND f.column_name = c.column_name AND f.field_path = c.column_name
            WHERE c.table_name = %(t)s ORDER BY c.ordinal_position""", {'t': table})
        return {'columns': [{'name': r[0], 'type': r[1], 'nullable': str(r[2]).upper() == 'YES',
                             'comment': r[3] or ''} for r in rows], 'primary_key': []}


class DatabricksDriver(SQLDriver):
    kind = 'databricks'
    module = 'databricks.sql'
    pip = 'databricks-sql-connector'
    paramstyle = 'named'
    quote_char = '`'
    default_schema = 'default'

    def connect(self, conn: Connection, secret, token: Optional[str]) -> Any:
        mod = self.load()
        o = conn.options
        kw: Dict[str, Any] = {
            'server_hostname': o.get('host') or o.get('server_hostname') or '', 'http_path': o.get('http_path') or '',
            'access_token': token or secret('token') or secret('access_token') or '',
            'session_configuration': {'STATEMENT_TIMEOUT': str(int(conn.timeout_seconds))},
            '_user_agent_entry': 'SAJHA',
        }
        for k in ('catalog', 'schema'):
            if o.get(k):
                kw[k] = o[k]
        return mod.connect(**kw)

    def end(self, dbc) -> None:
        pass                                             # autocommit warehouse: nothing to roll back

    def server_version(self, dbc, conn) -> str:
        return 'Databricks SQL ' + str(self.rows(dbc, 'SELECT current_version()')[0][0])

    def _prefix(self, conn: Connection) -> str:
        cat = conn.options.get('catalog')
        return f'{self.quote(str(cat))}.' if cat else ''

    def list_tables(self, dbc, conn: Connection) -> List[Dict[str, Any]]:
        rows = self.rows(dbc, f"SELECT table_schema, table_name, table_type, comment FROM "
                              f"{self._prefix(conn)}information_schema.tables "
                              f"WHERE table_schema <> 'information_schema' ORDER BY 1, 2")
        return [{'schema': r[0], 'name': r[1], 'type': 'view' if 'VIEW' in str(r[2]).upper() else 'table',
                 'comment': r[3] or ''} for r in rows]

    def describe(self, dbc, conn: Connection, schema: str, table: str) -> Dict[str, Any]:
        return {'columns': info_schema_describe(self, dbc, schema, table, 'comment', self._prefix(conn)),
                'primary_key': []}
