# Data Connectors Reference Guide

How to connect each kind of data store, which options and secrets it takes, what to grant the
account SAJHA signs in with, and the tools a connection gets. The design (the statement guard,
limits, masking, curated views, governance) is owned by
[Data Connectors](../../architecture/Data%20Connectors.md); every `connectors.*` key is in the
[Configuration Reference](../../getting-started/Configuration%20Reference.md#data-connectors); the
walkthrough is [Tutorial 25](../../tutorials/TUTORIAL_25_connect_a_database.md).

The kinds the server knows, with their packages and whether each is installed here, are on the
Data Connectors page (`/admin/connectors`, "Kinds and their drivers") and at
`GET /api/connectors/kinds`.

---

## 1. Every connection

A connection is a record at `config/connectors/<id>.json` (the page writes it). The fields
common to all kinds:

| Field | Meaning |
|---|---|
| `id` | Tool prefix: lower case, a letter first, letters, digits and `_`, no `__`, at most 40 characters |
| `kind` | One of the kinds below |
| `title`, `description` | Shown to people and to planners; say what the data is |
| `enabled` | `false` removes the tools and keeps the record |
| `options` | Connection options (per kind below); never credentials |
| `secrets` | Credential name to secret reference (`env:NAME`, `file:/path`, `db:llm_providers/<type>`) |
| `limits` | `max_rows`, `max_bytes`, `timeout_seconds` (and `max_bytes_billed` for BigQuery) |
| `allow` | `schemas` (exact), `tables` and `deny_tables` (globs over `schema.table` or `table`) |
| `masking` | `[{"column": "<glob>", "mode": "hide|null|redact|hash|partial|pii"}]` |
| `tools` | Switches: `list_tables`, `describe_table`, `query`, `search` (all on by default) |
| `views` | Curated views (SQL kinds) |
| `vector` | Vector or search settings (`pgvector`, `qdrant`, `elasticsearch`, `opensearch`) |
| `auth` | `{"type": "connected_account", "provider": ..., "scopes": [...]}` for per-user sign-in (Snowflake, BigQuery, Databricks) |
| `cache_ttl` | Seconds to cache tool results (0, the default, caches nothing) |

**Grant read privileges only.** SAJHA refuses writes in its statement guard and, where the
database has one, in a read-only session; the account's privileges are the wall that does not
depend on SAJHA. Each section below says what to grant.

---

## 2. SQL databases

Every SQL kind gets `<id>__list_tables`, `<id>__describe_table`, `<id>__query` and one tool per
curated view.

### PostgreSQL (`postgresql`)

Package: `psycopg2` (`pip install 'psycopg2-binary'`, in `requirements.txt`) or `psycopg` 3.

| Option | Default | |
|---|---|---|
| `host` | `localhost` | |
| `port` | `5432` | |
| `database` | | also accepted as `dbname` |
| `user` | | |
| `sslmode`, `sslrootcert`, `sslcert`, `sslkey`, `target_session_attrs` | | passed to libpq |
| `connect_timeout` | `10` | seconds |
| `application_name` | `sajha-connector` | shown in `pg_stat_activity` |

Secret: `password`. The session starts with `default_transaction_read_only=on` and
`statement_timeout`, and its `search_path` is the allowed schemas (when every name in
`allow.schemas` is a plain identifier), so an unqualified table name cannot reach another schema.

```sql
CREATE ROLE sajha_ro LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE shop TO sajha_ro;
GRANT USAGE ON SCHEMA public TO sajha_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sajha_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO sajha_ro;
```

### Amazon Redshift (`redshift`)

The PostgreSQL driver; default port `5439`; the same options and secret. Redshift does not take
start-up options, so the read-only characteristic and `statement_timeout` are set with `SET`
after connecting. Grant `USAGE` on the schemas and `SELECT` on the tables.

### MySQL and MariaDB (`mysql`, `mariadb`)

Package: `pymysql` (in `requirements.txt`).

| Option | Default |
|---|---|
| `host` | `localhost` |
| `port` | `3306` |
| `database` | (none: every database the account sees, filtered by `allow`) |
| `user` | |
| `charset` | `utf8mb4` |
| `ssl_ca` | |
| `connect_timeout` | `10` |

Secret: `password`. Sessions are `TRANSACTION READ ONLY`, every statement runs in
`START TRANSACTION READ ONLY`, and `MAX_EXECUTION_TIME` (MySQL) or `max_statement_time`
(MariaDB) bounds it; a timed-out statement is stopped with `KILL QUERY`. A MySQL schema is a
database, so `allow.schemas` lists databases.

```sql
CREATE USER 'sajha_ro'@'%' IDENTIFIED BY '...';
GRANT SELECT ON shop.* TO 'sajha_ro'@'%';
```

### SQL Server (`sqlserver`)

Package: `pyodbc` (`pip install 'pyodbc'`) and a Microsoft ODBC driver on the host.

| Option | Default |
|---|---|
| `host`, `port`, `database`, `user` | |
| `odbc_driver` | `ODBC Driver 18 for SQL Server` |
| `encrypt` | `yes` |
| `trust_server_certificate` | `no` |
| `authentication` | (for example `ActiveDirectoryServicePrincipal`) |

Secret: `password`. Without `user` or `authentication`, Windows integrated sign-in is used. The
connection asks for `ApplicationIntent=ReadOnly`; SQL Server has no read-only session, so grant
only `db_datareader`. Results are capped by the fetch (no `LIMIT` in T-SQL).

```sql
CREATE LOGIN sajha_ro WITH PASSWORD = '...';
CREATE USER sajha_ro FOR LOGIN sajha_ro;
ALTER ROLE db_datareader ADD MEMBER sajha_ro;
```

### Oracle (`oracle`)

Package: `oracledb` (`pip install 'oracledb'`), thin mode: no Oracle client needed.

| Option | Default |
|---|---|
| `dsn` | (or the three below) |
| `host`, `port` | `localhost`, `1521` |
| `service_name` | also accepted as `database` |
| `user` | |

Secret: `password`. Every statement runs in `SET TRANSACTION READ ONLY`; `call_timeout` bounds
it. The catalog lists schemas that are not Oracle-maintained. Grant `CREATE SESSION` and
`SELECT` on the tables to expose.

### Snowflake (`snowflake`)

Package: `snowflake-connector-python`.

| Option | |
|---|---|
| `account` | the account identifier |
| `user`, `warehouse`, `database`, `schema`, `role` | |
| `authenticator` | for service sign-in other than a password |
| `query_tag` | default `sajha-connector` |

Secret: `password`, or per-user sign-in with `auth` (the connected-account provider's OAuth
token, `authenticator=oauth`). `STATEMENT_TIMEOUT_IN_SECONDS` bounds each statement. Snowflake
has no read-only session: use a role with only `USAGE` on the warehouse, database and schema and
`SELECT` on the tables.

### BigQuery (`bigquery`)

Package: `google-cloud-bigquery` (and `google-auth`, which it brings).

| Option | |
|---|---|
| `project` | the billing project |
| `location` | |

Secrets: `credentials_json` (a service-account key as JSON), or none for Application Default
Credentials, or per-user sign-in with `auth` (a Google connected account with a BigQuery scope).
List the datasets under `allow.schemas` (required). `limits.max_bytes_billed` sets
`maximum_bytes_billed` on every query job, so an expensive scan fails instead of running. Grant
BigQuery Data Viewer on the datasets and BigQuery Job User on the project.

### Databricks SQL (`databricks`)

Package: `databricks-sql-connector`.

| Option | |
|---|---|
| `host` | the workspace host name (also `server_hostname`) |
| `http_path` | the SQL warehouse's HTTP path |
| `catalog`, `schema` | Unity Catalog defaults |

Secret: `token` (a personal access or service-principal token), or per-user sign-in with `auth`.
The `STATEMENT_TIMEOUT` session setting bounds each statement. Grant `USE CATALOG`,
`USE SCHEMA` and `SELECT`.

### SQLite and DuckDB files (`sqlite`, `duckdb`)

No extra package (DuckDB is in `requirements.txt`). Option: `path` (the database file; it must
exist). SQLite opens it `mode=ro` with `PRAGMA query_only`; DuckDB opens it `read_only=True`
with `enable_external_access=false`, so file, HTTP and S3 functions are off even below the
guard. Neither can be written through a connection.

---

## 3. Vector databases and search

### pgvector (`pgvector`)

A PostgreSQL connection (same options, secret and grants) whose `vector` block names the table:

```json
"vector": {"table": "public.docs", "vector_column": "embedding", "text_column": "body",
           "id_column": "id", "metadata_columns": ["title", "url", "lang"],
           "distance": "cosine", "embedding_model": "embedding"}
```

`distance` is `cosine` (`<=>`), `l2` (`<->`) or `inner` (`<#>`). The connection gets the SQL tools
and `<id>__search`; `filters` match `metadata_columns` only. The query text is embedded through
the gateway alias `embedding_model`; it must produce vectors of the column's dimension.

### Qdrant (`qdrant`)

No package (REST over `httpx`). Options: `url` (for example `http://qdrant:6333`), `collection`
(the default one), `verify_tls`. Secret: `api_key`. `vector`: `vector_name` (for named vectors),
`text_field` (the payload field returned as `text`, default `text`), `embedding_model`.
Collections are allowlisted by `allow.tables`. Tools: `<id>__list_collections`,
`<id>__describe_collection`, `<id>__search`.

### Elasticsearch and OpenSearch (`elasticsearch`, `opensearch`)

No package (REST). Options: `url`, `user` (with secret `password`), `index` (the default one),
`verify_tls`. Secrets: `api_key` (Elasticsearch `ApiKey` header) or `password`. `vector`:
`fields` (fields for full-text search; default all), `text_field`, and for k-NN `vector_field`,
`num_candidates` and `embedding_model`. Indices are allowlisted by `allow.tables`; indices whose
name starts with `.` are never listed. Grant a role with `read` and `view_index_metadata` on the
indices.

---

## 4. The tools, by example

```text
shop__list_tables      {"pattern": "order"}
shop__describe_table   {"table": "public.orders"}
shop__query            {"sql": "SELECT status, count(*) AS n FROM orders WHERE created_at >= :since GROUP BY status",
                        "params": {"since": "2026-01-01"}}
shop__orders_by_status {"status_in": ["paid", "shipped"], "created_at_from": "2026-01-01", "limit": 20}
kb__search             {"query": "refund policy for damaged goods", "top_k": 5, "filters": {"lang": "en"}}
```

What each returns, the limits that apply and the errors it can give are in
[Data Connectors](../../architecture/Data%20Connectors.md) sections 6 to 9.

---

## 5. Troubleshooting

| Symptom | Cause |
|---|---|
| `The <kind> connector needs the Python package ...: pip install '...'` | The driver is not installed on the server |
| `secrets.password: the reference env:X resolves to nothing` | The environment variable (or file) is not set on this server |
| `table x is not available on connection <id>` | Not in the allowlist, a system catalog, or ambiguous without a schema (qualify it) |
| `function f() is not allowed on a data connection` | A denied function (files, network, dynamic SQL, server state) |
| `column c is masked: select it as a plain column ...` | A masked column used in a filter, a function or under another name |
| `the query timed out after Ns and was cancelled` | `limits.timeout_seconds`; narrow the query or raise the limit |
| `truncated: true` | The row or byte cap; add filters or aggregate |
| Many harmless queries refused | sqlglot is not installed and the scanner is conservative: `pip install 'sqlglot'` |

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
