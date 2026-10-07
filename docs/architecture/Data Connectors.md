# SAJHA MCP Server — Data Connectors

Schema-aware, governed, read-only access to enterprise data stores as MCP tools. An
administrator describes a **connection** once (a database, a warehouse, a vector database or a
search cluster); SAJHA generates a small, fixed set of tools for it, so an MCP client or
Ask SAJHA can discover the tables, read their columns and query them, under the same access
control, policy engine, audit, metrics and cache as every other tool.

This document owns the topic: the design, what was built, how to operate it and its limits.
Per-connector setup (drivers, options, privileges to grant) is in the
[Data Connectors Reference Guide](../tools/enterprise/Data%20Connectors%20Reference%20Guide.md);
every `connectors.*` key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#data-connectors);
the walkthrough is [Tutorial 25](../tutorials/TUTORIAL_25_connect_a_database.md); terms are in
the [Glossary](../../GLOSSARY.md).

**Nothing changes by default.** No connection ships; until an administrator adds one, the
feature has no tools and opens no connections.

---

## 1. Why, and what was there before

SAJHA already had four ways to put SQL behind a tool, each built for a different job:

| Existing piece | What it does | Why it is not the answer here |
|---|---|---|
| Studio DB-query creator (`sajha/studio/dbquery_tool_generator.py`) | One hand-written SQL template becomes one tool | Not schema-aware: the model cannot discover tables, and every question needs an admin to write a query first |
| `sqlselect_*` and `duckdb_*` tools | Read-only SQL over local files in DuckDB | Local files only; DuckDB's parser is the guard |
| OLAP semantic layer (`sajha/olap/`) | Declared datasets, dimensions and measures over DuckDB | A curated model, not a live enterprise database |
| Legacy pool (`sajha/core/db/db_connection_pool*.py`) | A generic DB-API pool with eviction threads | Hard-codes drivers (`cx_Oracle`, `psycopg2`) and knows nothing of read-only sessions, timeouts or per-user credentials |

Data Connectors reuse what fits (the OLAP read-only check for DuckDB, the policy engine's PII
redaction for masking, the secret store, connected accounts, the tool registry and storage
backend that API Import writes through) and add the parts that were missing: drivers for the
enterprise stores, a statement guard that works for every SQL dialect, a schema catalog, and
generated tools.

---

## 2. Shape

```
 config/connectors/<id>.json  (storage backend; the admin page writes it)
        │  save / startup sync
        ▼
 sajha/connectors/service.py ── writes ──► config/tools/<id>__list_tables.json   ┐
        │                                  config/tools/<id>__describe_table.json│ ConnectorTool
        │                                  config/tools/<id>__query.json         │ (one generic
        │                                  config/tools/<id>__<view>.json        │  implementation)
        │                                  config/tools/<id>__search.json        ┘
        ▼
 MCP · REST · Ask SAJHA · A2A · composites
        │
        ▼
 BaseMCPTool.execute_with_tracking   RBAC was checked by the front end; policy rules,
        │                            connected-account binding, validation, cache, breaker,
        │                            metrics and the usage ledger happen here (as for every tool)
        ▼
 ConnectorTool.execute ── reads the connection record (fresh on every worker)
        │
        ├─ guard.check()      one read-only SELECT; allowlisted tables; denied functions;
        │                     masked-column rules (sqlglot when installed, else a conservative scanner)
        ├─ driver.session()   read-only session/transaction, statement timeout (per kind)
        ├─ execute + fetch    parameters bound by the driver; row, byte and time caps
        ├─ masking.apply()    hide / null / redact / hash / partial / pii per column
        └─ audit + metrics    connector.query record; sajha_connector_* series
```

| Code | What |
|---|---|
| `sajha/connectors/model.py` | the connection record: parse, validate (secret references only), normalise |
| `sajha/connectors/store.py` | records at `<connectors.records_dir>/<id>.json` through the storage backend |
| `sajha/connectors/settings.py` | `connectors.*` keys, read live |
| `sajha/connectors/sqltext.py` | a small SQL tokenizer: comments, strings, quoted identifiers, `:name` parameters |
| `sajha/connectors/guard.py` | the statement guard (sqlglot and fallback) |
| `sajha/connectors/drivers/` | one driver per SQL kind: connect, read-only session, introspection, quoting, cancel |
| `sajha/connectors/vector.py` | pgvector, Qdrant, Elasticsearch / OpenSearch search adapters |
| `sajha/connectors/pool.py` | idle-connection pool per connection (never for per-user credentials) |
| `sajha/connectors/catalog.py` | the schema catalog cache (tables, columns, comments) |
| `sajha/connectors/masking.py` | column masking (reuses `sajha/policy/redact.py`) |
| `sajha/connectors/engine.py` | runs list / describe / query / view / search for a connection |
| `sajha/connectors/tools.py` | `ConnectorTool`, the one implementation every generated tool uses |
| `sajha/connectors/service.py` | save, test, sync tools, delete, catalog refresh, kinds |
| `sajha/routes/connectors_routes.py` | the Data Connectors admin page and its JSON API |
| `sajha/web/templates/admin/connectors.html` | the page |
| `tests/test_connectors*.py` | every behaviour below |

---

## 3. The connection record

One JSON document per connection, at `config/connectors/<id>.json` (the directory is
`connectors.records_dir`), read and written through the storage backend (local, S3, Azure
Blob or GCS), so no database table and no schema change is needed. An administrator writes it
on the Data Connectors page (`/admin/connectors`) or by hand; a hand-written file is picked up
at start-up or with **Sync tools**.

```json
{
  "id": "shop",
  "title": "Shop database",
  "description": "Orders, customers and products of the web shop.",
  "kind": "postgresql",
  "enabled": true,
  "options": {"host": "db.internal", "port": 5432, "database": "shop", "user": "sajha_ro"},
  "secrets": {"password": "env:SHOP_DB_PASSWORD"},
  "limits": {"max_rows": 500, "max_bytes": 2097152, "timeout_seconds": 30},
  "allow": {"schemas": ["public"], "tables": ["*"], "deny_tables": ["public.audit_*"]},
  "masking": [{"column": "customers.email", "mode": "partial"},
              {"column": "*.ssn", "mode": "hide"}],
  "tools": {"query": true},
  "views": [],
  "cache_ttl": 0
}
```

* **`id`** is the tool prefix: lower case, a letter first, letters, digits and `_`, at most 40
  characters.
* **Secrets are references only**: `env:NAME`, `file:/path` or `db:llm_providers/<type>`,
  resolved by the server's secret store when a connection opens. A credential-looking key
  under `options` (`password`, `token`, `private_key`, `credentials_json`, ...) is refused, as
  is a `secrets` value that is not a reference. The page never shows a resolved value; errors
  pass through the secret redactor.
* **`limits`** default to `connectors.default_*` and are capped by `connectors.max_*`.
* **`allow`**: `schemas` (exact names; empty means every non-system schema), `tables` and
  `deny_tables` (glob patterns over `schema.table` or `table`, case-insensitive). Only allowed
  tables appear in the catalog and may appear in a query.
* **`masking`**, **`views`**, **`vector`** and **`auth`** are sections 7, 8, 9 and 10.

---

## 4. Drivers

Drivers are optional: none is imported until a connection of its kind is used, and a missing
one fails with the package to install (`The snowflake connector needs the Python package
snowflake.connector: pip install 'snowflake-connector-python'`). The **Kinds** list on the page
shows which are installed.

| Kind | Python package | Read-only enforcement (beyond the guard) | Timeout |
|---|---|---|---|
| `postgresql`, `pgvector` | `psycopg2` (or `psycopg` 3) | session `default_transaction_read_only=on`, `readonly` session; `search_path` set to the allowed schemas | `statement_timeout`, plus `cancel()` |
| `redshift` | `psycopg2` (or `psycopg` 3) | read-only session (`SET SESSION CHARACTERISTICS ... READ ONLY`) | `statement_timeout`, plus `cancel()` |
| `mysql`, `mariadb` | `pymysql` | `SET SESSION TRANSACTION READ ONLY`; each query in `START TRANSACTION READ ONLY` | `MAX_EXECUTION_TIME` (MySQL) / `max_statement_time` (MariaDB), socket read timeout |
| `sqlserver` | `pyodbc` | `ApplicationIntent=ReadOnly`; no session-level read-only exists: use a login with only `db_datareader` | `Connection.timeout` |
| `oracle` | `oracledb` (thin mode) | `SET TRANSACTION READ ONLY` before every query | `call_timeout` |
| `snowflake` | `snowflake-connector-python` | none in Snowflake: use a role with only `SELECT` (and `USAGE`) | `STATEMENT_TIMEOUT_IN_SECONDS` |
| `bigquery` | `google-cloud-bigquery` | none: use a principal with BigQuery Data Viewer and Job User | job timeout; `maximum_bytes_billed` caps the scan |
| `databricks` | `databricks-sql-connector` | none: grant only `SELECT` (Unity Catalog) | `STATEMENT_TIMEOUT` session setting |
| `sqlite` | standard library | opened `mode=ro` (the file cannot be written) and `PRAGMA query_only` | progress-handler deadline |
| `duckdb` | `duckdb` | opened `read_only=True` with `enable_external_access=false` and the configuration locked (no file or network functions) | `interrupt()` |
| `qdrant` | none (HTTP) | only collection listing, collection info and point search are sent | HTTP timeout |
| `elasticsearch`, `opensearch` | none (HTTP) | only `_cat/indices`, `_mapping` and `_search` are sent | HTTP timeout |

Read-only enforcement is layered on purpose. The guard (section 5) is the same everywhere;
the session setting is a second, independent wall where the database has one; and the
account SAJHA logs in with should hold only read privileges, which is the wall that does not
depend on SAJHA at all. Where a database has no read-only session (SQL Server, Snowflake,
BigQuery, Databricks), the reference guide says which privileges to grant.

Connections are pooled per connection (`connectors.pool_size` idle connections, recycled after
`connectors.pool_max_age_seconds`); a connection that timed out, errored or was cancelled is
discarded, not returned. Per-user connections (section 10) are never pooled.

---

## 5. The statement guard

`<id>__query` takes caller-written SQL. Before anything reaches a driver, `guard.check()`
requires all of:

1. **One statement.** Comments and string literals are understood, so `SELECT 1; DROP TABLE x`
   and `SELECT 1 /* ; */` are told apart; a trailing `;` is dropped.
2. **A read-only query**: `SELECT`, `WITH ... SELECT`, set operations and `VALUES`. Rejected:
   every DDL and DML statement, `COPY`, `CALL`/`EXEC`, `SET`, `PRAGMA`, `ATTACH`, `LOAD`,
   transaction control, `EXPLAIN` (`EXPLAIN ANALYZE` runs the statement), `SELECT ... INTO`, a
   data-modifying CTE (`WITH d AS (DELETE ... RETURNING *) SELECT ...`) and locking clauses
   (`FOR UPDATE`, `FOR SHARE`).
3. **No denied function**: functions that touch files, the network, other servers, dynamic
   SQL, server state or sequences, by name or prefix (`pg_read_file`, `pg_ls_dir`, `lo_*`,
   `dblink*`, `query_to_xml`, `set_config`, `nextval`, `pg_terminate_backend`, `load_file`,
   `benchmark`, `xp_*`, `sp_*`, `openrowset`, `openquery`, `utl_*`, `dbms_*`, `read_csv*`,
   `read_parquet`, `read_*`, `glob`, `load_extension`, `system$*`, `external_query`, ...).
   Table functions in `FROM` are allowed only from a short list (`generate_series`, `unnest`,
   `range`).
4. **Only allowed tables**: every table the query reads (common table expressions excluded)
   must be in the connection's catalog after the allowlist. A table qualified with a database
   or catalog other than the connection's is refused, and so is any system catalog that was
   not allowlisted (`pg_catalog`, `information_schema`, `sys`, `mysql`, ...).
5. **Masked columns respected** (section 7).

**sqlglot** (`pip install sqlglot`) parses the query in the connection's dialect and checks the
syntax tree. Without it, a conservative scanner works on the token stream: denied keywords
anywhere outside strings and quoted identifiers, function names before `(`, table names after
`FROM` and `JOIN`, and a masked column's name anywhere at all. The scanner refuses some
harmless queries the parser would allow (a column called `update`, say); it is built to fail
closed. Set `connectors.require_sqlglot: true` to refuse caller SQL when sqlglot is missing.
For DuckDB, DuckDB's own parser checks the text too (`sajha/olap/sql_safety.py::read_only_sql`,
the check the OLAP and `duckdb_*` tools use).

**Parameters.** A query may contain `:name` placeholders with values in `params`; the
tokenizer rewrites them to the driver's style (`%(name)s`, `?`, `:name`, `$name`) outside
strings, comments and `::` casts, and the driver binds them. A value is never written into the
SQL text.

**The row cap is in the SQL as well as in the fetch.** When the query has no top-level `LIMIT`,
`LIMIT <max_rows + 1>` is appended on its own line (so a trailing `--` comment cannot swallow
it), and the result is checked again. SQL Server and Oracle are capped by the fetch alone.

---

## 6. Limits and the result

| Limit | Where | What happens |
|---|---|---|
| Rows | `limits.max_rows` (`connectors.default_max_rows`, at most `connectors.max_rows_limit`) and the caller's `max_rows` (lower only) | rows past the cap are not fetched; `truncated: true`, `truncated_reason: "rows"` |
| Bytes | `limits.max_bytes` (`connectors.default_max_bytes`, at most `connectors.max_bytes_limit`) | the JSON size of fetched rows; fetching stops at the cap; `truncated_reason: "bytes"` |
| Time | `limits.timeout_seconds` (`connectors.default_timeout_seconds`, at most `connectors.max_timeout_seconds`) | the database's own statement timeout, and a watchdog that cancels the statement and discards the connection; the call fails with `timed out after Ns` |
| Calls | the policy engine | rate limits and quotas on `<id>__*`, like any tool |

`<id>__query` returns:

```json
{"connection": "shop", "columns": [{"name": "id", "type": "int4"}],
 "rows": [{"id": 1}], "row_count": 1, "truncated": false,
 "masked_columns": ["email"], "elapsed_ms": 12}
```

Values are made JSON-safe: decimals and dates become strings, binary values a length marker.

---

## 7. Column masking

`masking` is a list of `{"column": <pattern>, "mode": <mode>}`. The pattern is a glob over
`column`, `table.column` or `schema.table.column` (case-insensitive). A pattern naming a table
applies whenever that table is read; a bare column pattern applies to every table.

| Mode | Result value |
|---|---|
| `hide` | the column is removed from results and samples, shown as hidden in `describe_table`, and a query may not name it at all |
| `null` | `null` |
| `redact` | `[REDACTED]` |
| `hash` | a stable 16-hex-digit SHA-256 of the connection id and the value (joins and counts still work) |
| `partial` | every letter and digit but the last four replaced with `*` |
| `pii` | the policy engine's PII redaction on the text (emails, phone numbers, card numbers, national IDs; `sajha/policy/redact.py`) |

Masking applies to `describe_table` samples, `query` results, view tools and search results.
A result column is masked by its name, so the guard stops the ways of renaming a masked column:
with sqlglot, a masked column may appear only as a plain, un-aliased column in the outermost
`SELECT` (not in `WHERE`, `JOIN`, `ORDER BY`, functions, subqueries, CTEs or set operations,
where it could be probed or renamed), a query reading a table with masked columns may not
pass a whole row to a function (`row_to_json(t)`, `t.*` inside a call); without sqlglot, a
masked column's name may not appear in the query at all (`SELECT *` still works and is masked).
Masking does not depend on the caller, so the tool cache cannot leak an unmasked value.

Masking in SAJHA is a second line. For data that must never leave the database, use the
database's own column privileges or masking policies as well (PostgreSQL column `GRANT`,
Snowflake masking policies, BigQuery policy tags, SQL Server dynamic data masking).

---

## 8. The generated tools

For a SQL connection (every kind but `qdrant`, `elasticsearch` and `opensearch`):

| Tool | Arguments | What |
|---|---|---|
| `<id>__list_tables` | `schema?`, `pattern?`, `refresh?` | allowed tables and views with their comments |
| `<id>__describe_table` | `table` (`schema.table` or `table`), `samples?` | columns, types, nullability, comments, primary key where the database reports it, masked sample rows |
| `<id>__query` | `sql`, `params?`, `max_rows?` | one read-only SELECT (sections 5 and 6) |
| `<id>__<view>` | the view's typed filters, `limit?` | a curated view (below) |
| `<id>__search` | `query` or `vector`, `top_k?`, `filters?` | `pgvector` only (section 9) |

Descriptions are written for planners: each names the next tool to call (list, then describe,
then query) and carries the connection's `description`, so Ask SAJHA's tool search shortlists
them for questions about that data. Every generated tool is annotated `readOnlyHint: true`,
`destructiveHint: false`, `idempotentHint: true`. `"tools": {"query": false}` turns caller SQL
off for a connection, leaving the catalog tools and the views.

**Curated views ("views as tools").** An administrator picks a table or view, the columns to
return and the columns a caller may filter on; SAJHA generates a typed tool:

```json
{"name": "orders_by_status", "title": "Orders by status", "table": "public.orders",
 "description": "Recent orders, newest first.",
 "columns": ["id", "customer_id", "status", "total", "created_at"],
 "filters": [{"column": "status", "operators": ["eq", "in"], "enum": ["new", "paid", "shipped"]},
             {"column": "created_at", "operators": ["gte", "lte"]},
             {"column": "customer_id", "operators": ["eq"], "required": true}],
 "order_by": [{"column": "created_at", "direction": "desc"}],
 "max_rows": 100}
```

Each filter operator becomes one argument: `eq` → `<col>`, `in` → `<col>_in` (array), `gte` →
`<col>_from`, `lte` → `<col>_to`, `gt` → `<col>_after`, `lt` → `<col>_before`, `contains` →
`<col>_contains` (a `LIKE` with the value's `%` and `_` escaped). JSON Schema types come from the
column types in the catalog; `additionalProperties` is false. The SQL is built from identifiers
checked against the catalog (when the view is saved and again on each call) and quoted by the
driver; every value is a bound parameter. A view tool needs no SQL from the caller, so it suits
a connection with `"query": false`, and suits policies that constrain arguments.

---

## 9. Vector databases and search engines

Vector stores answer a nearest-neighbour search; the query text is embedded through the
intelligence layer's gateway (`vector.embedding_model`, default the `embedding` alias), or the
caller passes a `vector`. Two vector databases are supported, chosen because one runs inside a
database many sites already have and the other is the most common dedicated vector store; both
need no extra Python package:

| Kind | How | Tools |
|---|---|---|
| `pgvector` | a PostgreSQL connection with a `vector` block (`table`, `vector_column`, `text_column`, `id_column`, `metadata_columns`, `distance`: `cosine`, `l2` or `inner`); the search is a parameterised `ORDER BY <col> <=> $vector LIMIT k` on the read-only session | the SQL tools and `<id>__search` |
| `qdrant` | the Qdrant REST API (`options.url`, `secrets.api_key`); collections allowlisted by `allow.tables`; optional `vector.vector_name` for named vectors | `<id>__list_collections`, `<id>__describe_collection`, `<id>__search` |
| `elasticsearch`, `opensearch` | the REST API (`options.url`, `secrets.api_key` or `options.user` + `secrets.password`); indices allowlisted by `allow.tables`; full-text `simple_query_string`, plus k-NN when `vector.vector_field` is set | `<id>__list_collections`, `<id>__describe_collection`, `<id>__search` |

`filters` on a search are equality matches on metadata (payload, `_source`) fields, built by
SAJHA (a Qdrant `must` filter, an Elasticsearch `term` filter, a bound SQL parameter); the
caller never sends query DSL. Results are `{"id", "score", "text", "metadata"}` with masking
applied to `metadata`. Weaviate and Chroma are not built: both are reachable today through
federation of their MCP servers, and the adapter interface (`VectorAdapter` in
`sajha/connectors/vector.py`) is small enough to add one.

This is separate from Ask SAJHA's own document index (`ai.rag`, `sajha/ai/rag/`), which keeps
SAJHA's guides and admin uploads; a connector searches a store the enterprise already has.

---

## 10. Per-user credentials

For Snowflake, BigQuery and Databricks, a connection can act as each user instead of a
service account:

```json
"auth": {"type": "connected_account", "provider": "snowflake", "scopes": ["session:role:ANALYST"]}
```

The generated tools then carry `"auth": {"connected_account": ...}`, so
`BaseMCPTool.execute_with_tracking` binds the caller's token from their connected account
([Connected Accounts](Connected%20Accounts.md)) and the driver signs in with it
(Snowflake `authenticator=oauth`, BigQuery OAuth credentials, Databricks access token). The
database then enforces that user's own grants. Such tools are never cached (the cache already
refuses per-user tools), their connections are never pooled, and their catalog is cached per
user. The feature is detected at run time: without `sajha.accounts`, saving such a connection
is refused with the reason.

---

## 11. Governance on every call

| Layer | How it applies |
|---|---|
| Access control | generated tools are registry tools: roles, API-key allow and deny lists and patterns (`shop__*`) decide who may see and call them |
| Policy | rules match `shop__query` like any tool; `when` conditions can test `sql` or a view's filters; redaction and injection screening run on the result |
| Audit | every call writes a `connector.query` record (connection, tool, operation, tables read, rows, truncation, milliseconds, the SHA-256 of the SQL; the SQL itself only with `connectors.audit_sql: true`), and refused statements a `connector.rejected` record; admin changes write `config.changed` records |
| Metrics | `sajha_connector_queries_total{connection,op,outcome}`, `sajha_connector_rows_total{connection}`, `sajha_connector_query_duration_seconds{connection,op}`, beside the per-tool series every tool has |
| Cache | the catalog is cached per process for `connectors.catalog_ttl_seconds` (refresh on the page, or `refresh: true`); results are cached when the connection sets `cache_ttl` (copied into each tool's config) |

---

## 12. The admin page and API

`/admin/connectors` (administrators): the connections with their kind, state and tools; add
and edit (kind-aware fields, secret references, limits, allowlist, masking, tool switches);
**Test** (connects, reports the server version and the number of allowed tables);
**Refresh catalog**; a catalog browser that describes a table; a view builder; **Sync tools**;
remove. Every change is audited.

| Route | What |
|---|---|
| `GET /admin/connectors` | the page |
| `GET /api/connectors` | connections, their tools and state |
| `GET /api/connectors/kinds` | each kind, its package and whether it is installed |
| `POST /api/connectors` | create or replace a connection (writes the record, syncs its tools) |
| `POST /api/connectors/test` | test an unsaved definition |
| `GET /api/connectors/{id}` | one connection's record |
| `DELETE /api/connectors/{id}` | remove it and its tools |
| `POST /api/connectors/{id}/refresh` | refresh its catalog |
| `GET /api/connectors/{id}/tables` | its catalog |
| `GET /api/connectors/{id}/describe?table=` | one table |
| `POST /api/connectors/sync` | regenerate every connection's tools |

---

## 13. Multi-worker behaviour

The record and the tool configs live in the storage backend; a tool reads its connection's
record when it runs (re-read when the file changes, at most every
`connectors.record_refresh_seconds`), so a change to limits, allowlist or masking reaches every
worker without regenerating tools. Tool configs change only when the set of tools changes; the
registry's file monitor (local storage) or a restart picks those up on other workers, as for
API Import. The catalog and the pools are per process.

---

## 14. Limits of this design

* SAJHA's masking and allowlist are enforced on query text it can analyse; a database-native
  control (grants, views, masking policies) is stronger and should back anything sensitive.
* Without sqlglot the guard is conservative (refuses more), and the table allowlist relies on
  `FROM` and `JOIN` scanning.
* There is no write access and no stored-procedure call, by design.
* Weaviate and Chroma adapters are not built (section 9).
* Snowflake, BigQuery and Databricks are tested with mocked DB-API connections; PostgreSQL,
  MySQL, SQLite and DuckDB against real databases.
