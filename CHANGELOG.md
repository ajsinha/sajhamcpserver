# SAJHA MCP Server — Changelog

Newest first. The current version is `app.version` in `config/application.yml`.

## Unreleased

MCP authorization (OAuth 2.1), MCP Apps and `x-mcp-header`: the items 6.0.0 deferred. Details: [OAuth Guide](docs/protocol/OAuth%20Guide.md), [MCP Apps and Headers Guide](docs/protocol/MCP%20Apps%20and%20Headers%20Guide.md), [MCP 2026-07-28 Compliance §4](docs/protocol/MCP%202026-07-28%20Compliance.md).

### Data connectors: enterprise databases, warehouses and vector stores as governed tools
Details: [Data Connectors](docs/architecture/Data%20Connectors.md), [Data Connectors Reference Guide](docs/tools/enterprise/Data%20Connectors%20Reference%20Guide.md), [Tutorial 25](docs/tutorials/TUTORIAL_25_connect_a_database.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#data-connectors).
- **Connections** (`sajha/connectors/`): one record per connection at `config/connectors/<id>.json` through the storage backend, written by the new **Data Connectors** page (`/admin/connectors`: add, test, browse the catalog, describe a table, curated-view builder, sync, remove; every change audited) or by hand. Credentials only as secret references (`env:`, `file:`, `db:`); a credential-looking option is refused.
- **Kinds:** PostgreSQL, Redshift, MySQL and MariaDB, SQL Server (pyodbc), Oracle (python-oracledb thin), Snowflake, BigQuery, Databricks SQL, SQLite and DuckDB files; pgvector, Qdrant and Elasticsearch / OpenSearch for search. Drivers are optional and imported on first use; a missing one names the package to install.
- **Generated tools:** `<id>__list_tables`, `<id>__describe_table` (columns, types, comments, primary key, masked sample rows) and `<id>__query` (one read-only SELECT with `:name` parameters bound by the driver), curated views as typed tools (`<id>__<view>`: chosen columns, filter arguments per operator, every value bound, SQL built from catalog-checked identifiers), and `<id>__search` / `__list_collections` / `__describe_collection` for vector and search kinds. Read-only annotations, output schemas and planner-friendly descriptions; RBAC, the policy engine, connected-account binding, the cache and the metrics apply as to every tool.
- **Read-only, three walls:** the statement guard (one statement; SELECT only; no DML or DDL anywhere, no `SELECT INTO`, data-modifying CTEs or locking clauses; denied file, network, dynamic-SQL and server-state functions; only allowlisted tables; masked-column rules; sqlglot when installed, else a conservative scanner; DuckDB's own parser too), a read-only session where the database has one (PostgreSQL, Redshift, MySQL/MariaDB, Oracle, SQLite `mode=ro`, DuckDB `read_only` with external access off), and the login's privileges (the reference guide lists the grants per kind).
- **Limits:** rows (also appended as `LIMIT`), result bytes and statement time (database timeouts plus a watchdog that cancels and discards the connection); `connectors.*` defaults and ceilings.
- **Masking:** `hide`, `null`, `redact`, `hash`, `partial` and `pii` (the policy engine's PII redaction) per column glob; applied to results, samples, views and search hits; the guard refuses queries that would rename or probe a masked column.
- **Per-user credentials** for Snowflake, BigQuery and Databricks through connected accounts (feature-detected); never pooled or cached.
- **Governance:** `connector.query` and `connector.rejected` audit records (SQL as a SHA-256 unless `connectors.audit_sql`), `sajha_connector_queries_total`, `sajha_connector_rows_total`, `sajha_connector_query_duration_seconds`; a per-process schema catalog cache and idle-connection pool.
- **Default unchanged:** no connection ships. **Schema:** no database change.
- Tests: `tests/test_connectors.py` (guard both ways, SQLite and DuckDB end to end, views and injection, mocked drivers, vector adapters, the page and API), `tests/test_connectors_live.py` (PostgreSQL 16 and MySQL 8 when `SAJHA_TEST_CONNECTORS_POSTGRES_URL` / `SAJHA_TEST_CONNECTORS_MYSQL_URL` are set).

### Tool quality: test harness, linter, health probes, evals, versions and canary
Details: [Tool Quality](docs/architecture/Tool%20Quality.md), [Tutorial 23](docs/tutorials/TUTORIAL_23_test_and_canary_your_tools.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#quality).
- **Test harness** (`sajha/quality/`, `python -m sajha.quality test`): per-tool test cases in `config/tool_tests/*.yaml` (or `tests` in a tool config) with assertions: JSON Schema match against the tool's `outputSchema` or an inline schema, JSONPath `equals` (numeric `tolerance`), `not_equals`, `contains`, `regex`, `type`, `min`/`max`, `length`, `exists`, and a `latency_ms` budget; expected failures (`error:`); version pins. Text, JSON and JUnit XML output; `--save` keeps the run for the Tool Health page. Shipped cases for three calculators and `wiki_search`.
- **HTTP cassettes:** a small VCR records a case's HTTP exchanges once (`--record`) and replays them offline (`--replay`, strict: an unrecorded request is an error, never a network call); intercepts `urllib.request`, `requests` and `httpx` (sync and async); no request headers stored, secret query parameters redacted, `Set-Cookie` dropped.
- **Schema linter** (`python -m sajha.quality lint`): MCP tool-name rule, description length, input and output schemas valid JSON Schema 2020-12 of `type: object`, property descriptions, `examples` and `default` that validate, boolean and coherent annotations, destructive-sounding names without `destructiveHint`, test-case arguments against the input schema; report and JUnit.
- **Health probes** (opt-in, `quality.probes.enabled`): a `probe:` block runs one case live on an interval or a cron schedule (the workflows cron parser), one worker per slot through a state-store claim; latest result and history in the state store; `sajha_tool_probe_runs_total`, `sajha_tool_probe_up`, `sajha_tool_probe_duration_seconds`. New **Tool Health** page (`/admin/tool-health`): probes with Run now, test runs, the linter.
- **Evals for Ask SAJHA** (`config/evals/*.yaml`, `python -m sajha.quality eval|compare|runs`): golden questions with expected and forbidden tools, answer checks (`contains`, `regex`, `number` with tolerance, ...) and limits (steps, tokens, cost, latency), run per model and planner; tool-selection accuracy, answer accuracy, pass rate, steps, tokens, cost, mean and p95 latency; comparison of two runs (metric deltas, regressed and improved questions). The shipped `calculators` set runs offline on the mock provider. New **Evals** page (`/admin/evals`): runs in the background, run detail, compare.
- **Tool versions and canary** (`config/tool_versions/<tool>.yaml`, `sajha/quality/versions.py`): several versions behind one MCP tool name (overrides of the registered config, or a whole config), routed per call at the top of `execute_with_tracking` by API-key pin, user, role, sticky canary percentage, then stable; `_meta["io.sajha/tool-version"]` on MCP results and `_meta` on `POST /api/tools/execute`. Automatic rollback when a canary's error rate or slow-call rate over a sliding window passes its thresholds, shared by every worker through the state store, audited and counted (`sajha_tool_version_rollbacks_total`, `sajha_tool_version_calls_total`). Deprecation with sunset dates: `_meta["io.sajha/deprecation"]` until the date; after it a version is never routed and a tool is hidden from `tools/list` and refuses calls. New **Tool Versions** page (`/admin/tool-versions`): edit (validated), canary, promote, clear a rollback. `GET /api/tool-versions` and `POST /api/tool-versions/{tool}/deprecate`, placeholders until now, now read and write the versions files.
- **Default unchanged:** probes are off and no tool has a versions file. **Schema:** one new table, `quality_runs`, in both schema files; on PostgreSQL run `db/scripts/postgresql/schema.sql` again before starting this version.
- Tests: `tests/test_quality_harness.py`, `tests/test_quality_lint.py`, `tests/test_quality_probes.py`, `tests/test_quality_evals.py`, `tests/test_quality_versions.py`, `tests/test_quality_pages.py`.

### Workflows: schedules, triggers and run history
Details: [Workflows](docs/architecture/Workflows.md), [Tutorial 22](docs/tutorials/TUTORIAL_22_schedule_a_workflow.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#workflows).
- **A workflow is a DAG of steps** (`sajha/workflows/`): `tool`, `composite`, `ask` (Ask SAJHA), `condition` with `then`/`else` branches, `foreach` over a list (capped, optionally parallel), `wait` and `approval` (the policy engine's approval store). Parameter mapping extends the composite syntax with `$steps.<id>.<path>`, `$item`, `$index` and `{{...}}` interpolation; dependencies are implied by what a step reads; `join` (`all_success`, `any_success`, `all_done`), `when`, `on_error`; per-step retries with exponential backoff and timeouts; a run timeout. Definitions in JSON or YAML, validated on save (cycles, unknown steps, bad cron or timezone).
- **Triggers:** timezone-aware cron (one fire per slot across workers: an atomic claim in the state store plus a unique run idempotency key), HMAC-SHA256-signed webhooks (`POST /api/workflows/{name}/hooks/{trigger}`, timestamp tolerance, replay refusal), file arrival on the storage backend (local, S3, Azure Blob, GCS listing polls), change-bus events, and manual runs from the page, the CLI and the API (`Idempotency-Key`).
- **Durable runs:** every run and every step (status, attempts, truncated input and output, timing, error) is stored; a worker's heartbeat lets another worker take over a run whose worker died (a conditional UPDATE, so one winner), reusing finished steps and re-running an interrupted step only when it is idempotent (else it is marked failed); long waits and approvals park the run and free the worker; cancel; re-run from a failed step reusing the steps before it; a concurrency limit per workflow across workers; outputs delivered through the async delivery router (webhook allow-list, file directory, Kafka).
- **Run as the owner:** steps run with the owner's current roles or API-key lists (re-read each run), as the caller the policy engine, usage ledger and audit see, with the new policy source `workflow`. Saves, runs, cancels, re-runs, resumes and finishes are audited.
- **Published as a tool** (administrators): `publish.enabled` registers the workflow as an ordinary registry tool, listed and callable on both MCP eras and federatable; a workflow cannot call itself through it.
- **Workflows page** (`/workflows`): list, form editor with a DAG view, JSON and YAML views, triggers and delivery, run with an input, run history and a per-step timeline. **CLI:** `sajha workflows list|run|runs|show`. New keys `workflows.*`.
- **Schema:** three new tables, `workflows`, `workflow_runs` and `workflow_run_steps`, in both schema files. SQLite creates them at start-up; on PostgreSQL run `db/scripts/postgresql/schema.sql` again (it only creates what is missing) before starting this version.
- Tests: `tests/test_workflows.py`.

### Describe a tool: a sentence to a reviewed, tested tool
Details: [Tool Generation](docs/architecture/Tool%20Generation.md), [Tutorial 24](docs/tutorials/TUTORIAL_24_describe_a_tool.md), [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md#describe-a-tool).
- **Studio → Describe a tool** (`/studio/describe`, admins) and `sajha studio describe "<text>"`: the model behind the new `toolsmith` gateway alias proposes a tool (kind `python`, `rest`, `dbquery`, `composite` or `openapi`; name, description, schemas, implementation, test cases). The proposal is checked as untrusted input (SQL read-only and on listed tables only, SSRF host checks, no generated credentials or sandbox secrets, risky imports flagged, hosts the description does not mention flagged), rendered into the exact files Studio's generators write, and kept as a draft bound to a SHA-256 of its content.
- **Tests before deploy:** Python cases run in the sandbox (offline cases with no network), REST cases against canned fixtures, DB queries on the listed database; live cases only on request. A deploy needs `approve: true`, the reviewed hash, tests run on that hash (failures only with `accept_failures`), and the policy engine's consent to the pseudo call `studio.deploy` (`require_approval` holds it for a second administrator). An OpenAPI proposal hands off to Import an API, prefilled. Generated Python tools always carry `sandbox.enabled: true`. A tool test harness, when installed, receives the cases (feature-detected).
- **Prompt-injection hygiene:** the description is length-capped, screened with federation's injection markers and passed as a nonce-fenced data block.
- **`mock-toolsmith`**: a deterministic, offline designer in the mock provider (`sajha/ai/llm/mock_toolsmith.py`) so the feature works with no keys; `ai.aliases.toolsmith` maps to it. New keys `studio.describe.*`.
- Tests: `tests/test_describe_tool.py`.

### Planners, conversation memory and document search (RAG)
Details: [Intelligence Layer](docs/architecture/Intelligence%20Layer.md#planners), [Extending the Intelligence Layer §4.5](docs/architecture/Extending%20the%20Intelligence%20Layer.md#45-a-planner-extension-point), [Tutorial 21](docs/tutorials/TUTORIAL_21_planners_memory_and_rag.md).
- **Planner extension point** (the design §4.5 proposed, now built): `ai.ask.planner` chooses the strategy that decides each step of an ask; the service keeps RBAC, refusal of tools not offered, confirmation, limits, synthesis, confidence, audit and the event schema. Built in: `react` (the previous loop, the default; `model` is an alias), `plan_execute` (one structured-output planning call returns a step plan with dependencies; independent steps run in parallel; one re-plan after a failure), `recipes` (regex or keyword recipes from `ai.ask.planner_config.recipes`, with optional answer templates, falling back to another planner) and `router` (rules, recipes, then `plan_execute` or `react` by question shape). Register more with `@register_planner`, a class path or a `sajha.planners` entry point; worked example `sajha/examples/intelligence/docs_first_planner.py`. New optional `plan` event; Ask SAJHA shows the plan as a collapsible list. `AskResult` gains `planner`, `plan`, `conversation_id`, `turn`, `standalone_question`. `GET /api/ai/planners`; admins may pass `planner` on one ask.
- **Conversation memory:** an ask with `conversation_id` (`"new"`, then the returned id) gets the recent turns as context, a gateway-written summary of older ones, and its question rewritten as a standalone question; the mock answers both calls deterministically. Per user, never shared; `ai.memory.retention_days` (30) and a per-user cap; `GET`/`DELETE /api/ai/conversations[/{id}]` (delete-my-history). Ask SAJHA now keeps a conversation (New chat starts a new one). **Schema:** two new tables, `ai_conversations` and `ai_conversation_turns`, in both schema files; on PostgreSQL run `db/scripts/postgresql/schema.sql` again before starting this version.
- **Document search:** the `sajha_search_docs` tool and the help page's **Ask the docs** box search an index of SAJHA's own guides, `ai.rag.sources` folders in the storage backend, and admin uploads (`/api/ai/docs/*`), with citations (document, section, link). Passages are embedded through the `embedding` alias (`mock-embed` by default) and ranked by fusing vector and BM25 rankings; the in-process store (pure Python, persisted through storage, re-embeds only changed documents) is the default, pgvector is used when PostgreSQL has the extension and the optional `rag_chunks` table (a commented section at the end of `db/scripts/postgresql/schema.sql`).
- **Fix:** tools added by Studio creators, composites, federation sync, API import or the file watcher are now searchable by Ask SAJHA at once. `ToolsRegistry.add_change_listener` fires on every register, unregister, enable and disable (once per `bulk()`), and the tool resolver listens: the lexical index rebuilds on the next search, the vector index re-syncs in the background with BM25 answering meanwhile. Previously only a full reload (or the API-import path) refreshed it.
- Tests: `tests/ai/test_planners.py`, `tests/ai/test_memory.py`, `tests/ai/test_rag.py`, `tests/ai/test_tool_index_sync.py`.

### Policy engine, tamper-evident audit and SIEM export
Details: [Policy and Audit](docs/architecture/Policy%20and%20Audit.md), [Tutorial 20](docs/tutorials/TUTORIAL_20_policies_approvals_and_audit.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#policy-and-audit).
- **Rules on every tool call:** `sajha/policy/` evaluates declarative rules (YAML or JSON in `config/policies/`, read through the storage backend, hot-reloaded) in `BaseMCPTool.execute_with_tracking`, the one place MCP (both eras, stdio, WebSocket), REST, the playground bridge, A2A, Ask SAJHA, async tasks and federated tools run a tool; composite steps are governed too. A rule matches on tool globs, groups, annotations (`destructiveHint`), caller (anonymous, user, role, API key, auth type), source and time window, and on argument values.
- **Effects and obligations:** `allow`, `deny` with a reason, `require_approval`; argument constraints (`enum`, `min`/`max`, `pattern`, `not_pattern`, length, type); rate limits and calendar quotas per tool, user or API key in the state store (shared by workers on `redis`/`database`); output redaction of emails, phone numbers, Luhn-valid card numbers, national IDs (US SSN, UK NINO, Aadhaar, PAN, Canadian SIN) and custom regexes, redacted or masked; prompt-injection screening of results (federation's markers) with `flag`, `strip` or `block`. Deny-overrides; `policy.default_effect: deny` is an allowlist mode.
- **Approvals:** `approver: caller` asks the user (an MRTR form on 2026-07-28 clients with elicitation; the Confirm button in Ask SAJHA); `approver: admin` (and every other client) queues the call on the new **Approvals** page (`/admin/approvals`) and returns its id; once approved, the same caller's identical call runs once. No self-approval by default; optional webhook or Slack notification through the alert webhook's SSRF guard. REST answers 403 (denied), 202 (approval pending), 429 with `Retry-After` (rate limit or quota); MCP a tool error with `_meta["io.sajha/policy"]`.
- **Default unchanged:** the shipped `config/policies/00-default.yaml` has no rules and the two example policies are disabled. Decisions are counted (`sajha_policy_decisions_total`, `sajha_policy_redactions_total`, `sajha_policy_output_flags_total`) and every non-allow decision is audited. **Policies** page (`/admin/policies`) with a test bench that evaluates a described call without running it.
- **Tamper-evident audit:** every audit record (every `AuditLogger` event and every policy decision) is hash-chained (`sha256` of canonical JSON that carries the previous hash), one chain per process so workers never contend, and anchored every `audit.chain.anchor_every` records, every `anchor_interval_seconds` and at shutdown with an RS256 signature from the server's OAuth key (public half at `/oauth/jwks`). `python -m sajha.audit verify` (and the new **Audit** page, `/admin/audit`) detects edited, deleted, inserted or reordered records, edited query columns, rewritten tails and truncation. `audit_log` is still written for the existing audit API.
- **SIEM export** (`audit.export.sinks`, or `SAJHA_AUDIT_EXPORT_SINKS`): syslog (RFC 5424, octet-counted, TCP or TLS), HTTP (Splunk HEC, Datadog, generic; SSRF-guarded, pinned address) and rotated JSON Lines files, as JSON, CEF or OCSF-style JSON; batched, retried with backoff, bounded queues with counted drops (`sajha_audit_export_total`).
- **Schema:** two new tables, `audit_chain` and `audit_anchors`, in both schema files. SQLite creates them at start-up; on PostgreSQL run `db/scripts/postgresql/schema.sql` again (it only creates what is missing) before starting this version.
- Tests: `tests/test_policy.py`, `tests/test_audit_chain.py`.

### Connected accounts: tools that act as the user at GitHub, Slack, Google, Microsoft 365, ...
Details: [Connected Accounts](docs/architecture/Connected%20Accounts.md), [Connected Account Tools Reference Guide](docs/tools/enterprise/Connected%20Account%20Tools%20Reference%20Guide.md), [Tutorial 18](docs/tutorials/TUTORIAL_18_connect_your_accounts.md).
- **Link once:** `/account/connections` (user menu → Connected accounts) links a user's own account at a third-party service with OAuth 2.0 authorization code, PKCE S256 where the service supports it, an exact redirect URI, and a single-use `state` bound to the SAJHA user and the browser; Connect and Disconnect are CSRF-protected forms; Disconnect revokes at the provider where it can.
- **Providers are configuration:** templates for `github`, `slack` (user tokens), `google`, `microsoft` (tenant), `atlassian` and `notion`, enabled by a client id and a `client_secret_ref` under `accounts.providers`, or `SAJHA_ACCOUNTS_PROVIDERS_<ID>_<FIELD>`; any OAuth 2.0 service as a custom provider. Each provider lists the only hosts its tokens may be sent to (`api_hosts`).
- **Token vault:** the `connected_accounts` table (added to both schema files) holds tokens as AES-256-GCM ciphertext bound to their user and provider; the key is `SAJHA_ACCOUNTS_VAULT_KEY` or generated into the secrets file, with `accounts.vault.previous_keys` for rotation and a `key_provider` hook for KMS. Refresh before expiry, one worker at a time (a state-store lock, safe for rotating refresh tokens); a refused refresh marks the link "reconnect".
- **Tool binding:** a tool config's `"auth": {"connected_account": "<provider>", "scopes": [...]}` makes every call run with the caller's token (MCP both eras, REST, Ask SAJHA); per-user results are never cached. New tools: `github_list_my_repos`, `github_create_issue`, `slack_post_message`, `google_drive_search`, `ms365_list_my_events`, and `connected_http_request` (an administrator binding of a provider's API by base URL, methods and path patterns). They are listed only while their provider is configured.
- **"Connect your account":** MCP 2026-07-28 clients with URL-mode elicitation get an MRTR URL elicitation and retry; 2025-11-25 clients get `-32042` URLElicitationRequiredError; others a tool error with the connect URL; REST answers 428 with `connect_url`; Ask SAJHA shows a **Connect &lt;service&gt;** card (`needs_connection` event, `stopped_by: needs_connection`).
- **Federation token passthrough:** an upstream with `auth: {type: connected_account, provider: ...}` receives each caller's own token on a connection opened for that call (discovery uses `auth.discovery`); the item 6.x deferred.
- **Administration:** `/admin/connections` shows who linked what (never a token), unlinks a user's account and re-encrypts the vault after a key change. Audit events `connected_account_*`.

### API Import: OpenAPI, Swagger and GraphQL to tools
Details: [API Import](docs/architecture/API%20Import.md), [Tutorial 19](docs/tutorials/TUTORIAL_19_import_an_openapi_spec.md).
- **Studio → Import an API** (`/studio/api-import`, admins): an OpenAPI 3.x or Swagger 2.0 spec (URL, upload or paste) or a GraphQL endpoint (introspection) becomes a preview of every operation: proposed tool name (`<prefix>_<operationId>`), JSON Schema 2020-12 input and output (every `$ref` inlined, local, relative and remote; cycles cut), `readOnlyHint` / `destructiveHint` / `idempotentHint`, flags for unsupported multipart bodies and name collisions. Filter by tag, method or path; choose the server and its variables; set credentials (API key in header, query or cookie; bearer; basic; OAuth 2.0 client credentials; the caller's connected account) as secret references; test-call one operation; deploy the selection, live at once.
- **No generated code:** every imported tool is a JSON config run by one executor (`sajha.api_import.executor.ImportedAPITool`), so no sandbox is involved; 2xx answers come back as `{status, body, next_page?}`, other statuses, timeouts and refused addresses as tool errors.
- **SSRF guard** on the spec URL, remote `$ref` documents, GraphQL endpoints, token URLs and every call (pinned vetted address, redirects re-checked, GET only); `api_import.allow_localhost`, `allow_private_networks`, `allowed_hosts`.
- **Re-import diff:** an import record per API (`config/api_imports/<api_id>.json`, storage backend; no database table) shows operations as new, changed, unchanged or removed, and a deploy updates tools in place. Caps: `api_import.max_tools` per API, spec, response and `$ref` limits; an optional calls-per-minute limit per API.
- **CLI:** `sajha studio import-openapi <url|file> [--dry-run] [--select 'GET /path'] [--auth JSON] [--graphql]`. Endpoints under `/admin/studio/api-import/`; Studio's delete removes an imported tool too.
- **Ask SAJHA shortlists tools imported this way at once:** a deploy refreshes the tool-search index (a hot-load alone did not).

### The web UI on phones and tablets
Details: [Architecture §10](docs/architecture/Architecture.md) ("Small screens").
- **No sideways page scroll** at 375, 390 or 768px wide: wide tables scroll inside their own box (`main.js` wraps them), the user and API key lists become one card per row on phones, Studio action bars and hero buttons wrap, and the "Full reference" link wraps.
- **Navigation:** the hamburger and every menu entry are at least 44px tall; the mega-menu panels open as a scrollable accordion with a chevron. **Touch:** controls at least 40px, inputs at 16px (no iOS zoom on focus), small print at least 12px, iOS safe-area insets, and a `title` is shown on tap.
- **Guides:** the contents list is a closed "Contents" disclosure on phones. **Charts** on Tool metrics, User activity and Reports keep a readable height.
- **Fixed:** a table with both `data-enhance` and the automatic table controls got two search bars and two pagers; table-enhance's controls landed inside the scroll box. The user and API key tables had broken `class` attributes.
- **Check:** `scripts/check_mobile.py` (Playwright) checks every page for page scroll, off-screen elements and a working phone menu, and reports small tap targets and small text; `tests/test_mobile_layout.py` keeps its route list live.

### Security: the duckdb_* tools are sandboxed; data resources follow the anonymous policy (behaviour change)
Details: [Security Model](docs/security/Security%20Model.md) ("Fixes", "Tool access"), [DuckDB Tool Reference Guide](docs/tools/analytics/DuckDB%20Tool%20Reference%20Guide.md), [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md#datasets-datasetsjson), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#anonymous-access-mcpanonymous).
- **`duckdb_query`, `duckdb_describe_table`, `duckdb_get_stats`, `duckdb_aggregate`, `duckdb_refresh_views`, `duckdb_list_tables`, `duckdb_list_files`:** table and column names were pasted into SQL (`DESCRIBE {table_name}`), `having` was raw SQL, `duckdb_query` blocked writes by keyword substring, and every query could read any file or URL (`read_text`, `read_csv`, `read_parquet`). Now the data files are copied into one in-memory sandbox per data directory, after which `enable_external_access` is off and the configuration locked; names must exist in the catalog and are quoted; `having` is `<name> <op> <value>` conditions joined by `AND` with bound values; `duckdb_query` runs one parser-checked `SELECT`/`EXPLAIN` statement (the `duckdb_sql` rule). Tables replace the old views, and `duckdb_analytics.db` is no longer written. Tests: `tests/test_duckdb_tools_sandbox.py`.
- **`sajha://data/*` resources** were listed and readable by anonymous callers. Anonymous callers now see only URIs matching the new `mcp.anonymous.resources` (default none; `SAJHA_MCP_ANONYMOUS_RESOURCES`) in `resources/list` and `resources/read`, both eras; signed-in callers read every data file. `POST /api/resources/read` now serves data files as well, with the same reader, path-traversal guard and policy.
- **The `customer_olap` dataset failed on every query:** its joins referenced a `customers` alias its `source_table` never set, its qualified columns (`customers.region`) could not resolve outside the joined subquery, filters on a column two joined files share (`product_category`) were ambiguous, and the shared `measures.json` entries (`total_revenue` = `SUM(amount)`) overrode its own. The source table is now `... AS customers`, its columns are unqualified, filters on a joined dataset apply over the joined row, and a dataset's inline dimension or measure wins over the shared definition of the same name.

### Database schema: one schema file per database; no DDL on PostgreSQL (behaviour change)
Details: [Database Setup](docs/getting-started/Database%20Setup.md).
- **PostgreSQL was unusable.** Every statement of the old `db/scripts/postgresql/001_schema.sql` failed (`CURRENT_TIMESTAMPTZ`, `DEFAULT FALSE` on integer columns, two primary keys on `prompt_tags`, integer seed values for booleans), and the start-up runner executed all statements in one transaction and counted failures as skips, so every pod logged "0 statements executed" and sign-in answered 500. SQLite's `prompt_tags` (same double primary key) was never created either.
- **One schema file per database, no migrations.** `db/scripts/postgresql/schema.sql` and `db/scripts/sqlite/schema.sql` hold every table, column, key and index SAJHA uses, including the tables features used to create on first use (the database state store `sajha_state`/`sajha_state_events`, the usage ledger `obs_usage_events`, the connected-accounts vault `connected_accounts`); `seed.sql` beside each holds the default roles, permissions and the `admin` user (flagged `must_change_password`). Every statement is `CREATE ... IF NOT EXISTS`, each file is one transaction. `001_schema.sql` and `002_seed.sql` are gone. The never-used tables `tenant_users`, `rate_limit_log`, `llm_usage` and `user_ai_preferences` are no longer created (existing ones are left alone). `tests/test_db_schema.py` keeps both files in step with each other and with every SQLAlchemy model and `Table` in the code, and applies the PostgreSQL file to a real server when `SAJHA_TEST_CONNECTORS_POSTGRES_URL` is set.
- **PostgreSQL: SAJHA never creates or alters tables.** An operator runs `schema.sql` (then `seed.sql`) once with `psql`. At start-up SAJHA checks that every table and column its code uses exists and, if not, refuses to start, naming what is missing and the `psql` command (`db.schema_check: strict`, the default; `warn` starts anyway). The state store, the usage ledger and the token vault only check for their tables there. PostgreSQL sessions run in UTC (`TIMESTAMPTZ` columns). **SQLite** (development) runs its `schema.sql` at start-up, and `seed.sql` only when the database is new.
- **Upgrades:** a release that changes the schema lists, in its entry here, the SQL to run for each database. This one needs nothing beyond `schema.sql` (PostgreSQL could not have been set up before; an existing SQLite database gets the new tables at start-up).
- **Helper** `python -m sajha.db` (`sajha db ...` from the client CLI): `check` (tables and columns the configured database lacks; exit 3 when any) and `sql --dialect postgresql|sqlite [--seed]` (prints a file for `psql -f`). It never changes the database.
- **Deployments.** Helm: `database.postgresql.schemaCheck`; the install notes print the two `psql` commands. Hetzner `deploy.sh` and cloud-init start only PostgreSQL and print the schema step; bare-metal `install.sh` prints the `psql` commands and starts SAJHA only after them; AWS: `psql` from a host that reaches RDS.
### Security: OLAP SQL injection, the rest of the public catalog (behaviour changes)
Details: [Security Model](docs/security/Security%20Model.md) ("Tool access", "Fixes"), [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md#what-callers-can-and-cannot-put-into-sql), [DuckDB Tool Reference Guide](docs/tools/analytics/DuckDB%20Tool%20Reference%20Guide.md#duckdb_sql), [FRED Tool Reference Guide](docs/tools/market-data/FRED%20Tool%20Reference%20Guide.md), [MCP Protocol Guide](docs/protocol/MCP%20Protocol%20Guide.md) ("Argument validation").
- **OLAP SQL injection.** Every OLAP engine (pivot, rollup, window, time series, statistics, cohort), `olap_top_n` / `olap_contribution`, `customer_olap_pivot` and `OLAPQueryBuilder` pasted filter values, dimension and measure names, operators, aggregations, sort directions and numbers into SQL (`{"value": "x' OR '1'='1"}` returned every row). Now (`sajha/olap/sql_safety.py`): filter values and `date_range` dates are DuckDB named parameters; dimension and measure names must be declared on the dataset in `config/olap/datasets.json` and resolve to their configured expressions (`Unknown dimension ...` otherwise; raw columns are no longer accepted); operators, aggregations, directions, time grains and comparison types are allowlisted; `n`, `bins`, `periods`, `limit` and window sizes must be integers. `sales_analysis` declares `date`, `quarter`, `order_year`, `order_month`, `payment_method` and `customer_id`, and `financial_metrics` `date` and `quarter`, which the shipped examples and cohort analysis use.
- **`duckdb_sql` is read-only for real.** `SELECT 1; DROP TABLE orders` ran both statements, and `read_text('/etc/passwd')` or a URL could be read. It now runs exactly one statement that DuckDB's parser classes as `SELECT` or `EXPLAIN`; the CSV files are loaded into tables, then external access is disabled and the configuration locked.
- **Prompts, catalog resources, completion and the agent card follow the tool-access policy.** `prompts/list`, `prompts/get`, `GET /api/prompts/list`, `GET /api/prompts/{name}`, the `sajha://tools/catalog` and `sajha://prompts/catalog` resources (MCP and `POST /api/resources/*`), `completion/complete`, the MCP `tool/schema`-style methods and `GET /.well-known/agent.json` described every tool and prompt to anyone. Signed-in callers now see the tools their access allows and every prompt; anonymous callers see `mcp.anonymous.tools` and the new `mcp.anonymous.prompts` (both empty by default), so the anonymous agent card has no skills. `tool/description` no longer fails with an internal error.
- **FRED:** every `fred_*` tool returned the *oldest* `limit` observations (FRED sorts ascending); they now request `sort_order=desc` and return the latest observations, newest first.
- **Plugins:** `min_sajha_version` was compared as a string (`"5.9.0" > "5.10.0"`); it is compared as a version.
- **OLAP semantic layer:** saving `datasets.json` wrote the resolved data directory (this machine's absolute path) over `${data.duckdb.dir}`; the original text is kept.
- **Docs:** the MCP Protocol Guide states the per-era answer to arguments that fail the `inputSchema` (unchanged: `-32602` on 2026-07-28, an `isError` result on 2025-11-25 per SEP-1303).

### Fixes from the documentation audit (some behaviour changes)
Details: [Security Model](docs/security/Security%20Model.md), [API Reference](docs/protocol/API%20Reference.md), [MCP Protocol Guide](docs/protocol/MCP%20Protocol%20Guide.md) ("Argument validation"), [SharePoint Tool Reference Guide](docs/tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md).
- **Security: OLAP operations.** An OLAP tool took the operation to run from a caller-supplied `_tool_name`, so any advertised OLAP tool could run every OLAP operation, including the unadvertised `olap_generate_sample_data` (which writes files). Each tool now runs only the operation it is registered as; `_tool_name` is refused.
- **Security: REST catalog.** `GET /api/tools/list`, `/api/tools/{tool}/schema` and `/api/tool-groups/*` needed no credentials and listed every tool. They now apply the MCP `tools/list` policy (anonymous callers: `mcp.anonymous`, no tools by default) and answer 401 where `/mcp` would. The console's `/tools` pages, `/help/tools`, `/about`, Ask SAJHA and the public landing page name only tools the viewer may see (counts stay whole-catalog). A tool's schema page shows its resolved configuration to administrators only.
- **Security: enable/disable** wrote a tool's resolved configuration, API keys included, back into its config file; now only `enabled` changes.
- **Tool arguments are validated against the tool's JSON Schema** (`pattern`, `enum`, `minimum`/`maximum`, types, `additionalProperties`, ...) in `BaseMCPTool.execute_with_tracking`, before the tool runs. A mismatch is `-32602` on 2026-07-28, an `isError` result on 2025-11-25 (input validation is a tool execution error there), 400 on `POST /api/tools/execute`. Schema fixes so valid calls pass: Yahoo `symbol` accepts `BRK-A`, `BTC-USD`, `7203.T`, `EURUSD=X`, `^GSPC` (and lower case); World Bank country codes and Wikipedia language codes accept what the tools accept; the SharePoint schemas' `required` moved to a top-level list.
- **FRED:** `fed_get_latest` and `fed_get_common_indicators` returned the *oldest* observation (limit 1, ascending); they ask for the newest first and skip missing (`.`) values.
- **Federation:** every upstream shared one rate-limit window; each now has its own.
- **Plugins:** `.py` tools in a plugin never registered (`register_tool` was called with two arguments); they register, and only classes the file defines count.
- **SharePoint tools** use Microsoft Graph throughout (the token was for Graph but calls went to the SharePoint REST API); the token expiry no longer raises (`timedelta`), values are URL-encoded and OData strings escaped, and `config/application.yml` gains empty `sharepoint.*` and `azure.tenant.id` keys read from `SHAREPOINT_SITE_URL`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`, `AZURE_TENANT_ID`. Unconfigured tools answer "SharePoint is not configured". The Studio SharePoint creator writes a valid schema.
- **`${key:default}`** is honoured by `PropertiesConfigurator` too, and the DuckDB/SQL-select tools and the OLAP datasets resolve their data directory instead of using the literal text (which created directories named `${data.duckdb.dir:.` in the working directory; removed).
- **Change events:** loading N tools published 3·N change events (about 1,500 rows in the database state store at start-up). Bulk registration (start-up, reloads, composites, federation sync, the config poller) now publishes at most once and not at all when the catalog did not change; repeats of an event relayed to other workers within 0.5 s are coalesced.
- **Landing page** counts (LLM provider types, database tables, HTTP endpoints) come from the running server instead of fixed numbers.
- **Removed dead code:** the top-level `oauth:` block in `config/application.yml` and its `Settings` fields (never read; MCP authorization is `mcp.auth`), `sajha/core/auth_manager.py` and `sajha/core/apikey_manager.py` (unused), the legacy SSE `Last-Event-ID` replay (each stream is per connection), and a second, unreachable `GET /health`.
- **Console:** the MCP Studio menu lists the SharePoint creator.
- **Deployment:** bare-metal `sajha.service` makes `logs/`, `temp/` and `sajha/tools/impl/` writable, and `nginx.conf` streams `POST /api/ai/ask` unbuffered; the Hetzner compose file passes the session secret (`SESSION_SECRET`); the AWS stack passes the `sajha/<env>/app` secret to the tasks (`SAJHA_SECRETS_ARN`, exported by `bootstrap.sh`); stale version headers removed.

### Security hardening (behaviour changes)
Details: [Security Model](docs/security/Security%20Model.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md).
- **Secrets.** `config/application.yml` no longer ships JWT or session secrets. Empty secrets are generated once into `data/secrets/server_secrets.json` (mode 0600, git-ignored; `auth.secrets_file`), so existing JWTs signed with the old placeholder stop working and users sign in again. A secret (or `mcp.mrtr.state_secret`) set to any placeholder SAJHA ever shipped stops start-up. The MRTR secret derives from the persisted session secret, so `requestState` survives restarts.
- **Tool access everywhere.** One policy (`sajha/auth/access.py`) for REST, MCP (both eras, SSE, WebSocket), A2A and async: users by role permissions (`read` lists, `execute` runs), API keys by their tool access mode (allowlist, denylist and regex are now enforced, and keys no longer get 403 on `POST /api/tools/execute`), external OAuth identities without an account by a role named `api_consumer` (none by default). **Anonymous MCP and A2A callers see and run no registry tools by default**: list them in `mcp.anonymous.tools`, grant a role with `mcp.anonymous.role`, or refuse anonymous callers with `mcp.anonymous.enabled: false`. MCP `logging/setLevel` changes the server log level only for admins.
- **A2A.** Tool runs need execute access; tasks are visible only to their creator.
- **Async execution.** Needs admin or `async:execute` plus tool access; file delivery only inside `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls` (empty = none) with the CIMD SSRF guard; tasks scoped to their owner. `async.*` and `shell.*` keys now take effect (they were dead code in `config.py`).
- **Admin-only endpoints.** `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`, `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity`, the tool configuration page; the shell endpoints need admin or `shell:execute`.
- **Sign-in.** Account lockout (`auth.login.max_failed_attempts`, `lockout_minutes`; 423) and a failed-sign-in limit per IP (`auth.login.ip_max_failures`, `ip_window_seconds`; 429) on the web form, `POST /api/auth/login` and the OAuth sign-in. The old 5-per-minute limit on the JSON login (which counted successful logins) is gone.
- **Passwords.** Change-password page `/account/password` and `POST /api/auth/change-password`; admin reset `POST /api/admin/users/{uid}/password`; password policy (8+ characters, no well-known defaults); `users.must_change_password` with a banner for the seed `admin`/`admin123`, admin-set passwords and default passwords. `POST /api/admin/users/create` now requires a password.
- **Errors.** Unauthenticated API/JSON requests (`/api`, `/mcp`, `/a2a`, `/admin/studio`, `/oauth`, any non-GET, or `Accept: application/json`) get a JSON 401 instead of a redirect; 403s on those are JSON too.
- **WebSocket.** An invalid `token`/`api_key` closes the connection (1008) instead of falling back to anonymous.
- **Config.** `.env` names that are not settings no longer stop start-up (`extra='ignore'`; unknown `SAJHA_*` names are logged). Storage env vars (`SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`, `AZURE_STORAGE_CONNECTION_STRING`, ...) now override `application.yml`. `ai.tool_search.enabled`/`persist` are parsed as booleans. New `alpha_vantage.api.key` (`ALPHA_VANTAGE_API_KEY`). `sajha/auth/password.py` no longer raises `NameError` on an invalid hash.
- **nginx** (`deployment/baremetal/nginx.conf`): `/mcp` and `/api/mcp` are proxied unbuffered (SSE responses to POST). Compose files no longer pass placeholder secrets.

### Observability: Prometheus, OpenTelemetry, usage and cost, alerts
Details: [Observability](docs/architecture/Observability.md), [Tutorial 16](docs/tutorials/TUTORIAL_16_metrics_costs_and_alerts.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#observability).
- **`GET /metrics`** in the Prometheus text format, written by SAJHA (no `prometheus_client`): HTTP requests by route template/status with a latency histogram; MCP requests by era, method and outcome; tool calls by tool, group and outcome with latency, cache hits and breaker state; LLM calls, tokens and cost by provider and model; ask runs by `stopped_by`; auth failures and lockouts; sandbox runs; federated upstream health (when federation runs); process and Python metrics. Protected by `observability.metrics.auth` (`admin` default, `token` with `SAJHA_OBSERVABILITY_METRICS_TOKEN`, `none`); optional separate listener (`observability.metrics.port`); label cardinality controls (`tool_label`, `max_series`). With several workers and a shared `state.backend`, every scrape merges all workers under a `worker` label.
- **OpenTelemetry** (opt-in, `observability.otel.*`, standard `OTEL_*` honoured): OTLP traces and metrics; spans HTTP → MCP → tool → LLM, continuing `traceparent` from the HTTP header and from MCP `params._meta`. The SDK no longer installs a tracer provider with no exporter when tracing is off.
- **Usage & cost page** (`/monitoring/usage`, Tools → Monitor): tokens and cost by user, API key, role, provider, model and day; tool calls, error rates and p50/p95/p99 latency by tool; budgets against today's usage; date range, filters, CSV export. Administrators see everyone, others their own calls. Backed by a new usage ledger table `obs_usage_events` (a schema migration; `observability.usage.*`), written in batches off the request path. API: `/api/observability/usage`, `/api/observability/usage.csv`, `/api/observability/alerts`, `/api/observability/status`.
- **Alerts.** `observability.alerts[]` rules (metric, threshold, window, cooldown; log, webhook or email) evaluated in the process; webhooks only to `observability.alerts_webhook.allowed_urls` through the shared SSRF guard. `deployment/observability/` ships a Prometheus scrape job, alerting rules and a Grafana dashboard.
- **Fixed:** `/api/metrics` and `/api/metrics/tools` were always empty (nothing fed the collector); `execute_with_tracking` now does. The collector's two built-in log-only alert rules are replaced by the configurable rules.

### Sandboxed user code (behaviour change)
Details: [Sandbox](docs/architecture/Sandbox.md), [Tutorial 14](docs/tutorials/TUTORIAL_14_sandboxed_studio_tools.md).
- **Studio Python code tools and script tools no longer run in the server.** The registry loads them as sandboxed stand-ins (`sajha/sandbox/tools.py`): a Python tool's module is parsed for its schemas but never imported, a script runs per call in a fresh sandbox. No server environment (secrets only by name through `sandbox.secrets_allowlist`, never `SAJHA_*`), a temp work dir, CPU/memory/file/process/output/time limits, no network unless the tool's `sandbox` block allowlists hosts. Callers (MCP, REST, A2A, Ask SAJHA) see the same contract; a sandboxed Python tool cannot import `sajha`, read files outside its work dir or use the network by default, and a script's `working_directory` is ignored. `sandbox.enforce_for_generated_tools: false` restores in-process loading. Built-in tools and Studio's template creators (REST, DB query, Power BI, LiveLink, SharePoint, OLAP) stay in-process.
- **Backends** (`sandbox.default_backend`): `subprocess` (default; on Linux the runner adds user/PID/network namespaces, rlimits, Landlock and seccomp, each reported), `bwrap`, `nsjail`, `docker` (`--network none`, read-only root, limits, `runtime: runsc` for gVisor), or `auto`. The JSON runner protocol is `sajha/sandbox/runner.py`.
- **The admin shell** (`/api/shell/python`, `/api/shell/bash`) runs through the same sandbox after its filters; `shell.python.memory_limit_mb` is now applied and `tier` reads `sandbox:<backend>`.
- **Status:** `GET /api/sandbox/status` (admin, live probe of what is enforced), `sandbox` in `GET /health`, the backend in `/api/shell/capabilities`; the Python and script creator pages show the policy a new tool gets. Studio writes a `sandbox` block into the configs it generates.
- New `sandbox.*` keys ([Configuration Reference](docs/getting-started/Configuration%20Reference.md#sandbox)); escape tests per installed backend in `tests/test_sandbox.py`.

### Several workers and hosts: shared state (`state.backend`)
Details: [Scaling and State](docs/architecture/Scaling%20and%20State.md), [Tutorial 13](docs/tutorials/TUTORIAL_13_run_sajha_on_several_workers.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#state).
- **State store** (`sajha/core/state/`): one interface with three backends. `memory` is the default, and with it a single process behaves as before. `redis` uses the optional `redis` package and Redis pub/sub. `database` uses SAJHA's database or `state.database.url`, in the tables `sajha_state` and `sajha_state_events`, with polled pub/sub. New keys: `state.backend`, `state.key_prefix`, `state.redis.url` (`SAJHA_STATE_REDIS_URL`), `state.database.url`, `state.database.poll_interval_ms`, `state.tasks.durable`.
- **Moved into it:** OAuth pending consents, authorization codes (redemption is atomic and fixes the refresh family), refresh tokens and revoked families, DCR clients; 2025-11-25 sessions (a client's answer to a server request is relayed to the worker holding the stream); legacy HTTP+SSE queues (relayed); 2026-07-28 task records; rate limits and the sign-in IP throttle; LLM token usage and daily budgets; async-executor task records. Change-bus events reach `subscriptions/listen`, legacy SSE and WebSocket subscribers on every worker. Caches, circuit breakers, metrics and WebSocket sessions stay per worker on purpose: the inventory and the reasons are in the design document.
- **Durable tasks.** With a shared backend (`state.tasks.durable: auto`), MCP task records are kept in the database. They survive a restart and any worker reads, cancels or answers them. `tasks/update` on another worker rebuilds the runner from the stored call spec. A `working` task whose worker stopped heart-beating is reported `failed` and never re-run.
- **Operations.** `GET /health` has a `state` object (backend, reachable, tasks, worker ID). Start-up stops when a shared backend does not answer, and warns when several workers (`WEB_CONCURRENCY`, `UVICORN_WORKERS`, `SAJHA_WORKERS`, `--workers`) run on `memory`. `run_server.py --workers N` now starts N uvicorn workers through the `sajha.app:create_app` factory. New `mcp.auth.builtin.signing_key_pem` (env `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`) gives hosts that do not share a data directory the same OAuth signing key.
- **Deployment.** The Hetzner and local AWS compose files have an optional `scale` profile with Redis. The AWS CDK stack sets `SAJHA_STATE_BACKEND=database` for its several Fargate tasks, and the image installs `redis`.
- **Tests.** `tests/test_state_store.py` runs the store contract and the migrated components against memory, fakeredis, a real Redis (`SAJHA_TEST_REDIS_URL`) and SQLite. `tests/test_state_multiworker.py` starts two server processes that share a backend: an OAuth code issued on A is redeemed on B, a task created on A is read and cancelled on B, sign-in failures are counted across both, and a change on A reaches a listen stream on B. It also starts `--workers 2`. The conformance server suites are unchanged (43/43 for 2025-11-25 with 0.1.16, 152/152 for 2026-07-28 with 0.2.0-alpha.12) on the memory, redis and database backends.

### Kubernetes: production image, Helm chart, Kustomize manifests
Details: [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md), [Tutorial 17](docs/tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md).
- **`Dockerfile`** (repository root) and `.dockerignore`: multi-stage, venv copied into a slim runtime, UID 10001 under `tini`, `HEALTHCHECK` on `/health`, read-only-root ready (writes only `data`, `logs`, `temp`, `config`, `sajha/tools/impl`, `/tmp`). Build args `EXTRAS` (`redis` by default; `s3`, `azure`, `gcs`, `otel`), `WITH_OPENBB` (off), `PLAYGROUND_ASSETS` (vendors Pyodide). Secrets, `data/`, tests and the SDK are kept out of the image.
- **Helm chart `charts/sajha`** with `values.schema.json`: Deployment with a seed init container (seeds writable config volumes, deep-merges `config.overrides` into `application.yml`, waits for Redis and PostgreSQL), Service, two Ingress objects (streaming paths `/mcp`, `/api/mcp`, `/api/ai/ask` unbuffered with one-hour timeouts), HPA, PodDisruptionBudget, optional single-node Redis, NetworkPolicies with an egress allowlist hook, ServiceMonitor with bearer-token auth, `helm test`. One Secret (generated once and kept, or `secrets.existingSecret`) gives every pod the same JWT secret, session secret, OAuth signing key and metrics token. The chart refuses multi-pod settings that would split state (SQLite, `state.backend: memory`, `ReadWriteOnce` volumes).
- **Kustomize** `deployment/k8s/` (base, dev and prod overlays) rendered from the chart by `deployment/k8s/render.py`; `tests/test_k8s_deployment.py` checks the chart version against `app.version`, the values against the schema, the seed step, and (with Helm installed) that the manifests are up to date.
- **Verified** on kind (Kubernetes 1.33, ingress-nginx, kindnet NetworkPolicy): `helm lint`, kubeconform on default and full-feature renders and both overlays; three pods on Redis and PostgreSQL behind the streams Ingress without session affinity passed the 2025-11-25 suite (`@modelcontextprotocol/conformance` 0.1.16, 43 passed, 0 failed), the 2026-07-28 suite (0.2.0-alpha.12, 152 passed, 0 failed) and the ten tasks-extension scenarios (44 passed, 0 failed); all pods served one OAuth key id.
- **AWS:** the CDK stack now creates generated `sajha/<env>/jwt` and `sajha/<env>/session` secrets and passes them to every Fargate task (`SAJHA_JWT_SECRET`, `SAJHA_SECRET_KEY`; it previously referenced a `jwt_secret` key nobody created and passed no session secret), and `-c oauth_signing_key_secret=<name>` passes a stored PEM as `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`. The stack synthesizes again (an output reused the `LogGroup` construct id). `deployment/aws/Dockerfile` and the AWS compose file build from the repository root (the old paths did not resolve).

### OAuth 2.1 for `/mcp` (off by default)
- `mcp.auth.mode`: `off` (default) | `optional` | `required`.
- Resource server: RFC 9728 protected-resource metadata, `WWW-Authenticate` with `resource_metadata` and `scope`, audience-bound RS256 access tokens, scopes `mcp:read` / `mcp:tools`.
- Authorization server: built in (backed by SAJHA users; authorization code + PKCE S256, RFC 9207 `iss`, Client ID Metadata Documents with SSRF guards, rotating refresh tokens with reuse detection, CSRF-protected consent), or an external issuer validated through its JWKS (`mcp.auth.authorization_server`).
- API keys and SAJHA JWTs keep working in every mode. The signing key is generated under `data/oauth/` (git-ignored).
- Conformance `authorization` suite 3/3 for both spec versions; the server suites are unchanged (43/43 and 152/152); the official SDK completes the OAuth flow end to end.

### MCP Apps (`io.modelcontextprotocol/ui`)
- Tools bind `ui://` views, served by `resources/read` as `text/html;profile=mcp-app` (`mcp.apps.enabled`, default on). Example view for `calc_loan_amortization`.

### `x-mcp-header`
- Validated when a tool schema is loaded (invalid annotations are dropped with a warning); `Mcp-Param-Symbol` on the quote tools.

### The `sajha` command line and MCP over stdio
- **stdio transport** (`sajha/cli/stdio.py`; `sajha serve --stdio`, `python run_server.py --stdio`): desktop clients (Claude Desktop, Claude Code, IDEs) launch SAJHA as a subprocess. Both eras on one connection (a client in auto mode probes `server/discover` and falls back to `initialize`), newline-delimited JSON-RPC, nothing but protocol on stdout (fd 1 is pointed at stderr), `notifications/cancelled` honoured on both paths, `list_changed` pushed after `initialize`. One caller per process: `--user` / `SAJHA_STDIO_USER`, `--api-key` / `SAJHA_API_KEY`, else anonymous; mapped through the usual tool access. Loads only what MCP needs (no web UI; the LLM gateway with `--with-ai`). Tested with the official SDK client (`StdioServerParameters`) in `legacy` and `auto` modes; the conformance suite's server runner takes only `--url`, so it does not run over stdio.
- **`sajha` CLI** (`clientsdk/sajhaclient/cli/`, console script from `pip install 'sajhaclient[cli]'`): `login` (token stored 0600 in `~/.config/sajha`), profiles, `tools list|show|call` (schema-typed `--arg`, `--json`), `prompts list|get`, a streamed `ask`, `studio deploy|delete`, `federation list|add|refresh|remove`, `health`, `config show`, `completion bash|zsh|fish`, `serve`; `--server`/`--api-key`, `SAJHA_URL`/`SAJHA_API_KEY`; exit codes 0-6. Details: [Command Line](docs/clients/Command%20Line.md), [Tutorial 15](docs/tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md).

### Python Playground
- **`/playground`** (signed-in users; **Tools → Python Playground**, a dashboard quick action): a small notebook running Python in the browser with Pyodide (WebAssembly) in a Web Worker. Cells with a vendored CodeMirror 6 editor (Python highlighting, line numbers, Ctrl/Cmd+Enter), Run / Run all / Stop / Reset, stdout, stderr in red, REPL-style last-expression display, pandas DataFrames as tables, matplotlib figures inline, `display()`, examples (numpy, pandas, matplotlib, SciPy, scikit-learn, SAJHA tools, Ask SAJHA), save/load in browser storage, `.py` download, `.py`/`.ipynb` upload. Packages load on first import (`loadPackagesFromImports`); micropip installs pure-Python wheels from PyPI (`playground.allow_pypi`).
- **`import sajha`** in the playground: `sajha.tools()`, `sajha.schema()`, `sajha.call(name, **args)` (through `POST /api/tools/execute`) and `sajha.ask()` (through `POST /api/ai/ask`), with the user's session, so access control and limits are the server's usual ones. New `GET /api/playground/tools`. MCP Studio's Python code creator has **Open in playground**.
- **Assets.** `scripts/fetch_pyodide.py` vendors a pinned Pyodide release (core archive checked against GitHub's published SHA-256, every wheel against `pyodide-lock.json`) into `sajha/web/static/vendor/pyodide/` (git-ignored); `playground.assets: cdn` loads it from cdn.jsdelivr.net instead. Missing assets show an administrator hint. New keys `playground.enabled`, `playground.assets`, `playground.pyodide_version`, `playground.allow_pypi`.
- **Headers, playground only.** `/playground` sends COOP `same-origin` and COEP `require-corp` (cross-origin isolation, so Stop interrupts Python through a `SharedArrayBuffer`); its worker's CSP alone allows `'wasm-unsafe-eval'` (and the CDN or PyPI origins when configured). Every other route keeps the self-only policy. Code runs only in the browser. Details: [Python Playground](docs/getting-started/Python%20Playground.md), [Tutorial 12](docs/tutorials/TUTORIAL_12_python_playground.md).

### Ask SAJHA
- **Ask SAJHA** (`/ask`, AI menu and dashboard): a chat over `POST /api/ai/ask` that streams each step (shortlist, tool calls and results, answer, confidence), shows the tool chain as expandable chips with sources and caveats, asks before a destructive call, and draws the chain live on the tool sky. Model picker, a *Mock model active* pill, Stop, per-tab history. Details: [Intelligence Layer](docs/architecture/Intelligence%20Layer.md#using-ask-sajha), [Tutorial 10](docs/tutorials/TUTORIAL_10_ask_sajha.md).
- The landing page's constellation drawing moved to `sajha/web/static/js/constellation.js`, shared by both pages; the landing page is unchanged.

### Federation (off by default)
SAJHA can front other MCP servers ("upstreams") and re-expose their tools, and optionally prompts and resources, as its own. Details: [Federation](docs/architecture/Federation.md), [Tutorial 11](docs/tutorials/TUTORIAL_11_federate_an_mcp_server.md).
- A federated tool is a registry tool named `<prefix>__<tool>` (`sajha/federation/`, `FederatedTool`): listed by `tools/list` on both eras, on the Tools page, in Ask SAJHA's tool search, composites and A2A; calls pass through the same access policy, cache, circuit breaker (one per upstream), metrics and usage events as native tools, plus an optional per-upstream rate limit.
- Upstreams over Streamable HTTP (2026-07-28 or 2025-11-25, through the official `mcp` SDK v2 client), legacy SSE, or stdio (`federation.allow_stdio`, off). Credentials by secret reference: bearer, API-key header, OAuth client credentials.
- Discovery at start-up (bounded wait), periodically, on the upstream's `subscriptions/listen` or `list_changed` notifications, and on demand. Results, schemas, progress and cancellation pass through; an upstream's MRTR `InputRequiredResult` reaches 2026-07-28 callers.
- Security: approval before exposure (`federation.require_approval`, on), re-approval when an approved definition changes, screening of upstream text for injection markers, the SSRF guard on upstream and token URLs (`federation.allow_localhost`, `allow_private_networks`, `allowed_hosts`), no secrets in config or logs, admin-only routes with audit.
- Admin page **Admin → Federation** (`/admin/federation`) and its API under `/api/federation/`; admin-added upstreams and approvals persist through the storage backend (`federation.state_path`). Example upstream: `sajha/examples/federation/units_server.py`. Tests: `tests/test_federation.py`.

### How SAJHA compares
- **`/comparison`** (Help menu, help catalog under Reference, linked from About): SAJHA next to FastMCP, IBM ContextForge, Docker MCP Gateway, Microsoft MCP Gateway, Kong AI Gateway, Cloudflare, Composio, Zapier MCP and Smithery on protocol, security, tools, operations and deployment. Every competitor cell is a verdict (Yes, Partial, No or Unknown) with a note, a source and an as-of date; SAJHA's column follows its code, with its numbers read from the running registries. The data has one home, `sajha/web/competitive.py`, and `tests/test_competitive.py` checks it.

### Fixes
- `/login?next=` open redirect.
- Path traversal in `sajha://data` resources.
- WebSocket authentication called a method that did not exist.
- Security headers no longer overwrite stricter per-route values.
- **FBI tools rewritten for the current Crime Data Explorer API** (every call returned 404). All nine `fbi_` tools keep their names and now call the documented `api.usa.gov/crime/fbi/cde` paths (`/summarized/...`, `/agency/byStateAbbr/{state}`, `/pe/{state}/{ori}`, `/nibrs/...`); input and output schemas changed to match (config `version` 3.0.0). `fbi_search_agencies` now needs `state` (the API lists agencies per state; there is no free-text search); `fbi_get_offense_data` returns NIBRS victim/offender/weapon/location breakdowns and accepts only offenses with a NIBRS code; `fbi_get_participation_rate` reports population coverage (agency counts are no longer published); `fbi_get_crime_trend` makes one request for the whole range. Key errors (403) and rate limits (429, including the shared `DEMO_KEY`) name `FBI_API_KEY` / `fbi.api.key`; timeouts are configurable per tool (`timeout`, default 30 s). Details: [FBI Tool Reference Guide](docs/tools/public-data/FBI%20Tool%20Reference%20Guide.md).
- **OLAP `customer_analytics` and `inventory_analysis` datasets now work.** The sample data adds the `customer_data` view (one row per customer and order; customers gain `city`, `state` and `tier`) and the `inventory_data` table (stock snapshot per product and distribution centre), created with the rest of the sample schema and, when `sales_data` already exists, added only if missing. `customer_analytics` no longer declares a join to `sales_data` (its `ON` clause referenced a table it had aliased away). Details: [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md).

### Documentation
- Documentation reorganised under `docs/` by topic, with one owning document per topic, a root `GLOSSARY.md` and `CLAUDE.md` documentation conventions. Internal point-in-time reports moved to `docs/archive/`.
- [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md): writing a provider, a model and a real planner, with tested examples in `sajha/examples/intelligence/` (`tests/ai/test_extension_examples.py`) and a proposed `Planner` extension point.


## v6.0.0 (October 2026) — MCP 2026-07-28, dual-era

SAJHA now serves the stateless **MCP 2026-07-28** protocol and the session-based **2025-11-25**
protocol on the same `/mcp` endpoint. The request's `_meta` decides which: a protocol version
there means stateless, `initialize` means a 2025-11-25 session. Both are verified in CI by the
official conformance suite (`.github/workflows/mcp-conformance.yml`):
- **2026-07-28:** 40/40 scenarios, 152/152 checks; tasks extension 44/44.
- **2025-11-25:** 32/32 scenarios, 43/43 checks.

### 2026-07-28 (new)
- `server/discover`.
- Version, capabilities and log level read from `_meta` on every request.
- Required `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers (-32020); version errors are -32022.
- `resultType` and `ttlMs`/`cacheScope` on results.
- `GET`/`DELETE /mcp` return 405 for these clients.
- Streamed `tools/call` with progress and log notifications. Closing the stream cancels the call.
- `subscriptions/listen`, fed by a change bus over the tool and prompt registries. The legacy `/mcp/sse` and `/mcp/ws` streams receive the same events.
- Multi Round-Trip Requests with an HMAC-signed `requestState`, and elicitation through them. Optional confirmation for destructive tools: `mcp.confirm_destructive_tools`.
- Tasks extension `io.modelcontextprotocol/tasks`. Tools opt in with `execution.taskSupport`.
- Tool context API (`report_progress`, `report_log`, `is_cancelled`) for long-running tools.

### Client SDK
- `SajhaMCPClient` / `SajhaMCPSyncClient` (from 5.4.0) negotiate 2026-07-28 automatically through the official SDK (`pip install sajhaclient[mcp]`).

### Compatibility
- 2025-11-25 clients are unaffected.
- `v5.4.0` (also tagged `mcp-2025-11-25`) remains the last 2025-only release.

## v5.4.0 (October 2026) — MCP 2025-11-25, verified

This release makes SAJHA's MCP 2025-11-25 support match what it claims, proven by the official
MCP conformance suite 0.1.16: **32/32 server scenarios, 43 checks passed, 0 failed**, plus the
official Python SDK 2.3.0 client. It is tagged `v5.4.0` and `mcp-2025-11-25`.

### Protocol and transport
- `initialize` negotiates the version (2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05) instead of ignoring the client's.
- Streamable HTTP on `/mcp`:
  - `Mcp-Session-Id` sessions; `DELETE /mcp` ends a session.
  - The `MCP-Protocol-Version` header is validated.
  - Notifications get 202 with no body; JSON-RPC batches get 400.
  - `GET /mcp` returns 405 to Streamable HTTP clients.
- `Origin` allow-list (`mcp.allowed_origins`, env `SAJHA_MCP_ALLOWED_ORIGINS`) with 403 for other origins.
- The legacy 2024-11-05 HTTP+SSE flow now delivers responses over its stream.
- MCP tool calls run off the event loop. They now use the same path as the REST API: disabled tools are refused, and arguments, cache, circuit breaker and metrics all apply.

### Tools, prompts, resources
- `tools/list` emits `title`, `outputSchema`, `annotations` and `icons[]`.
- `tools/call` returns JSON text plus `structuredContent`. Turn this off with `mcp.tools.advertise_output_schema: false`.
- `prompts/list` includes arguments, and prompts responses carry their `id`.
- `prompts/get` returns real messages.
- Errors are proper JSON-RPC errors, not error objects inside `result`.

### Honesty fixes (breaking)
- Server capabilities no longer advertise client-only `elicitation`/`sampling`, or a `tasks` shape that never ran. `listChanged` and `subscribe` are `false` until notifications exist. Custom keys moved under `experimental.sajha`.
- Removed `/.well-known/openid-configuration`, `/.well-known/oauth-protected-resource` and `/.well-known/oauth-client/{id}`. They advertised OAuth endpoints that did not exist.
- `ping` returns `{}`. Unknown resources return `-32002`. Tool icons are `icons[]`.

### Also
- Opt-in conformance fixtures: `mcp.conformance_fixtures` / `SAJHA_MCP_CONFORMANCE_FIXTURES=true`.
- Client SDK: `SajhaMCPClient`, a wrapper over the official `mcp` SDK v2 (`pip install sajhaclient[mcp]`), with SAJHA's REST, A2A and WebSocket extras.
- Fixed: `POST /api/auth/login` 500; prompt pages' Save/Delete/Test endpoints; prompt detail 500.
- WCAG AA contrast pass across all screens and themes.

### Design: MAYA design language and themes

SAJHA now uses MAYA's look and MAYA's four themes, with the same names and the same colour values.

- **Themes:** Crimson (stored as `light`), Dark, Blue and Green replace Light / Dark / Wall Street / Ubuntu.
  - The palette menu matches MAYA's: a swatch and a name for each theme.
  - With nothing stored, the page follows the system's light/dark setting.
  - A stored Light or Dark choice carries over; a stored Wall Street or Ubuntu choice resets to the default.
- **Tokens:** `static/css/tokens.css` is MAYA's token set, renamed from `--maya-*` to `--sajha-*`. It is the only place colours are defined.
  - `style.css` maps its `--t-*` roles onto these tokens once and re-points Bootstrap's variables at them.
- **Chrome:**
  - A fixed gradient top bar with mega-menu panels (`common/_nav.html`).
  - Gradient `h1`s, soft-shadow 14px cards, alerts with a left rule, gradient primary buttons.
  - Hero banners and MAYA's footer.
  - The system-ui font at 14px.
- **Pages:**
  - Sign-in stands on the theme gradient.
  - The landing page is laid out with MAYA's `lp2-*` sections.
  - The Studio pages share `_studio_theme.html`.
  - Help and About use MAYA's hero, card and box classes.
  - Charts read their colours from the tokens (`window.SajhaChartTheme`) and re-colour when the theme changes.

## v5.3.0 (June 2026) — Storage-Backed Registries, Studio & Cloud Hot-Reload

Builds on the v5.2.0 multi-cloud storage abstraction by routing the live subsystems
through it: tool configs, prompts, and Studio output can now live on local disk, S3,
Azure Blob, or GCS, with cloud hot-reload. Default backend remains **local**.

### Tool registry → storage backend
- **`tools_registry` reads migrated.** `load_all_tools()` enumerates via
  `get_storage().list_files('config/tools', '*.json')` and reads each config through
  `get_storage().read_json()`. The loader (`load_tool_from_config`) now accepts a logical
  path (storage-relative string, `Path`, or filename) instead of a filesystem `Path`, and
  is normalized internally — so **tool configs can live in S3/Azure/GCS**. Verified end to
  end: real tool configs uploaded to a mocked S3 bucket load and instantiate correctly.
- **`register_tool_from_dict(config, source)` extracted** as the shared register path for
  the file loader and the plugin loader. This fixes a latent bug where `plugins.py` called
  `load_tool_from_config(name, config)` with two arguments against a one-arg method.
- **Implementation classes stay package-local.** Tool `.py` implementations are resolved by
  dotted module path via `importlib` and ship with the package, so they import locally
  regardless of where the JSON config lives.
- **Config writes migrated** (`_save_tool_config`) to `get_storage().write_json()`; the
  admin reload route (`api_routes`) uses the storage-backed path.

### Prompts registry → storage backend
- **Reads and writes migrated.** `_load_all_prompts_internal` lists/reads through storage;
  `create_prompt` / `update_prompt` write via `write_json()`; `delete_prompt` via
  `delete()`. Time-based auto-refresh now reloads from whichever backend is active.

### MCP Studio → storage backend
- **All eight tool generators** (code, REST, DB-query, script, SharePoint, LiveLink,
  PowerBI, PowerBI-DAX) write their JSON config through a shared
  `write_tool_config()` storage helper. Generated `.py` implementations are still written
  locally because `importlib` needs a real module on the path — on multi-instance cloud
  deployments, place that directory on shared EFS.

### Cloud hot-reload (no inotify on object stores)
- **`S3SyncManager` activated for cloud backends** at startup: it polls the bucket every
  `sync_interval` seconds, mirrors changed objects into the local cache, and fires the same
  reload paths (`tools_registry.reload_all_tools`, `prompts_registry.reload`). On the
  `local` backend the registry's filesystem poller is used and the sync manager is skipped,
  so exactly one mechanism runs per deployment. Verified via mocked S3: initial sync
  materializes the cache and a new object triggers the reload callback.

### Semantic tool search (pluggable embedder)
- **Natural-language tool discovery** at `/api/ai/resolve-tool`: a query like "discount future
  cash flows to today" returns the top-k matching tools by vector similarity. The index
  embeds each tool's name + description + parameter names + tags + an optional `literature`
  field.
- **Configurable ranking** via `ai.tool_search.embedder`:
  - `bm25` (default) — a dependency-free lexical BM25/TF-IDF ranker (no model, no key, no
    network), built over the same rich text (name + description + parameters + tags + literature).
  - `gateway` — optional API-driven vector similarity via the LLM gateway's embedding provider
    (e.g. OpenAI) for paraphrase matching. Switch with one config value; no code change.
  - Decoupled from the LLM gateway — semantic search needs no provider in the default mode.
- **Accurate on change.** The index does incremental, content-hash-based sync: only tools
  whose embedding text changed are re-embedded, removed tools are dropped, unchanged tools
  keep their vectors. It hooks the registry's reload path (`add_reload_listener`), so adds /
  edits / deletes — local or via the cloud sync manager — keep embeddings current.
- **Persisted via the storage backend** (local | s3 | azure | gcs) with a header recording the
  embedder + dimension; a restart reloads vectors (no re-embedding) and a changed embedder
  forces a clean rebuild (vectors from different models aren't comparable).
- **Non-blocking + graceful.** The initial index builds in a background thread so startup is
  never blocked; until it's ready (or if no embedder is available) search falls back to
  keyword matching. In-memory numpy cosine search — a `VectorIndex` seam is left for FAISS /
  Chroma if scale ever demands it.

### Database scripts cleanup
- **Fixed a critical regression where the file monitor unloaded all tools every 5s.** The
  storage migration changed `load_tool_from_config` to key `_file_timestamps` by
  storage-relative paths (`config/tools/foo.json`), but the registry's `_monitor_files`
  poller still compared against absolute paths — so every tool looked simultaneously "new"
  and "deleted" each cycle and the delete branch unregistered them all, leaving the registry
  empty. The monitor now keys on the same relative paths (`_config_rel`), so new/modified/
  deleted detection works correctly and legitimate hot-reload is preserved. Semantic tool
  search was also made fully non-blocking on reload, so the optional feature can never affect
  core tool loading.
- **Fixed SharePoint tools failing to load.** `SharePointBaseTool` never implemented the
  `get_input_schema` / `get_output_schema` abstract methods from `BaseMCPTool`, so all three
  SharePoint tools (documents, lists, search) raised "Can't instantiate abstract class …" at
  load. Added both getters to the base (returning the config's `inputSchema` / `outputSchema`,
  matching every other tool), making all four SharePoint classes concrete. Tool count
  496 → 499.
- **Removed obsolete top-level `db/scripts/001_schema.sql` + `002_seed.sql`.** The engine runs
  the dialect-specific `db/scripts/<db.type>/` directory; the top-level scripts were bypassed
  for SQLite and only reached as a buggy fallback (below).
- **Renamed `db/scripts/postgres/` → `db/scripts/postgresql/`** to match `db.type: postgresql`.
  Previously the engine looked for `db/scripts/postgresql/` (the `db.type` value), didn't find
  it, and silently fell back to the top-level scripts — so a Postgres deployment never used its
  own schema. Now `db/scripts/sqlite/` and `db/scripts/postgresql/` are the single source of
  truth per dialect.
- **Reconciled schema drift:** `llm_usage` and `user_ai_preferences` (previously only in the
  top-level file) are now defined in **both** dialect schemas alongside `rate_limit_log` and
  `tenant_users`, so SQLite and Postgres create an identical table set. Verified: SQLite boot
  creates all tables; both `db.type` values select the correct script directory.

### Documentation
- **New Storage Management help page** (`/help/storage`) with sections on local, EFS, S3,
  Azure Blob, and GCS — backend selection, auth, the read-mostly-vs-mutable-state rule, and
  how hot-reload works. Linked from the Help index.
- **README, ARCHITECTURE, and STORAGE_ROADMAP updated** to describe the storage-backed
  registries and cloud hot-reload. Version bumped to **5.3.0**.

## v5.2.0 (June 2026) — Offline Assets, Self-Only CSP & UI Polish

### Front-End Vendoring (offline-capable, no CDNs)

- **All third-party assets vendored** to `sajha/web/static/vendor/`: jQuery 3.7.1, Bootstrap 5.3.0 (CSS + bundle JS), Bootstrap Icons 1.10.0 (+ fonts), Socket.IO 4.5.4, marked 4.3.0 (pinned — preserves the `marked.setOptions({highlight})` API the docs viewer relies on), highlight.js 11.9.0 (+ 7 language packs + github-dark theme), Chart.js 4.4.0, jsoneditor 9.10.4 (+ icons), and three webfonts (Ubuntu, Plus Jakarta Sans, JetBrains Mono).
- **Zero external resource loads** remain across all 52 templates — the app renders fully offline / air-gapped.

### Security — Content-Security-Policy

- **Docs viewer fixed**: the markdown viewer previously spun forever because jQuery and Socket.IO were loaded from CDNs that the CSP `script-src` did not whitelist, so `$` was undefined and `$(document).ready()` threw before the render path. With everything vendored, this class of failure is gone.
- **CSP tightened to self-only**: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:`. No third-party origins to drift out of sync with.
- **CORS** default aligned with the `0.0.0.0` bind: localhost / 127.0.0.1 / 0.0.0.0 on :3002 (override via `SAJHA_CORS_ORIGINS`).

### Config Substitution Fix

- **`${data.duckdb.dir}` / `${data.sqlselect.dir}` now resolve correctly.** Root cause: `tools_registry` constructed `PropertiesConfigurator()` with no `yaml_file`, so it loaded nothing and every `${key}` fell through to its literal text — which created directories literally named `${data.duckdb.dir}`. The registry now loads the same config the app uses (respecting `SAJHA_CONFIG_FILE` / `--config`).
- `app.py` PropertiesConfigurator load also respects `SAJHA_CONFIG_FILE` instead of hardcoding the path.
- All 15 affected tool configs given `:default` fallbacks (e.g. `${data.duckdb.dir:./data/duckdb}`) as defense-in-depth.

### Storage Abstraction (on-prem ↔ cloud)

- **Pluggable storage backend** wired into startup: `storage:` config block (`backend: local|s3|azure|gcs`), `init_storage()` called before tools/prompts load, `get_storage()` available app-wide. Default `local` is a transparent filesystem wrapper — no behaviour change on-prem, and it needs none of the cloud SDKs.
- **Four backends behind one `StorageBackend` interface**: `LocalStorageBackend` (default) plus three object stores — **S3** (boto3, now with `endpoint_url` for MinIO/R2/Wasabi), **Azure Blob** (azure-storage-blob; connection-string or managed-identity auth), and **GCS** (google-cloud-storage; ADC/workload-identity auth). The three object stores share an `_ObjectStorageBackend` base (app-prefix namespacing, local read-through cache, recursive listing, `get_local_path` materialization); each implements only six small primitives. Cloud SDKs are lazy-imported, so only the selected backend's SDK is required.
- **Docs viewer migrated** to read through the backend (listing + content), so docs can be served from any backend; added a path-traversal guard.
- **`list_files` contract aligned** across local and object backends (recursive listing, filename-pattern match).
- Validated: S3 against a `moto`-mocked bucket; Azure + GCS against the real SDK surfaces (API-method introspection) plus injected-client logic tests; and the local default proven to boot with all cloud SDKs blocked. Remaining adoption (tools/prompts/studio, mutable-state placement, cloud hot-reload) tracked in `docs/STORAGE_ROADMAP.md`.

### Config-Driven UI Metadata

- Version, author, copyright, email, and GitHub URL/repo-name are all surfaced on the UI from `application.yml` via Jinja globals. Closed the two remaining hardcoded spots (About-page email, an Enterprise help version literal) and added a GitHub link to the About page.

### UI / Theming

- **About page rewritten**: 1384 → 314 lines. The old page duplicated its marketing cards 7–14× with malformed closing tags (causing visual overlap); the rewrite renders each section exactly once, is structurally valid, and is fully theme-driven via `var(--t-*)` surfaces and `card-header-*` helpers.
- **Theme sweep**: 113 `card-header` elements using fixed `bg-*`/`text-white` across 28 templates converted to the theme-aware `card-header-*` helpers (no more colour bleed in Dark / Wall Street / Ubuntu themes). Intentional fixed colours (code-editor surfaces, provider/brand accents, status badges, landing-page gradients) deliberately preserved.
- **Landing page**: added a `<canvas>` "living intelligence mesh" behind the hero — a pulsing SAJHA hub routing animated data packets between AI-agent nodes (Claude, GPT-4o, Bedrock, Together, Ollama, Azure) and data-provider nodes (FMP, OpenBB, FRED, Yahoo, SEC EDGAR, CoinGecko). Vanilla JS, theme-matched, DPR/resize-aware, pointer-interactive, and respects `prefers-reduced-motion` (renders a single static frame).
- Dead duplicate templates removed: `help/docs_list.html`, `help/docs_view.html` (the live versions live under `docs/`).

### Dependencies

- **`requirements.txt` pinned** with next-major ceilings on all dependencies (0 unbounded) to keep fresh installs reproducible. A `pip freeze` lockfile from a tested environment remains the gold standard for full reproducibility.

---

## v5.1.0 (May 2026) — Security hardening, System Monitor, Composition Framework, MCP 2025-11-25

Three bodies of work were released under 5.1.0. Several MCP claims below were later found to be inaccurate and were corrected in v5.4.0 (see its "Honesty fixes").

### Security hardening and System Monitor

#### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

#### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

#### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

#### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

#### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

#### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

#### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

#### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

#### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

#### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

### Composition Framework and UX overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

#### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

#### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

#### UX Overhaul (22 recommendations implemented)

- **4 UI Themes**: Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal amber-on-black, Consolas font), Ubuntu (aubergine + orange, Ubuntu font). Variable-driven CSS — 545 lines replaces 4,441.
- **CSS rewrite**: Clean architecture — design tokens → theme definitions (var(--t-*)) → components. Zero hardcoded colors. Every Bootstrap color class overridden for all themes. WCAG AA contrast verified.
- **Landing page**: Standalone dark-navy theme, gradient hero, 9 feature cards, code snippet, stats bar.
- **Login page**: Standalone dark theme matching landing page. Glass-morphism card.
- **Dashboard**: Welcome bar with transport badges, 4 metric cards, quick actions panel, platform stats, status panel, onboarding wizard.
- **Tools list**: Card-grid view toggle, category filter chips (auto-generated from tool data).
- **AI → LLM**: 5 Bootstrap tabs (Providers, Models, Preferences, Semantic Search, Usage). Add Provider form with type-specific fields (Bedrock: region+AWS keys, Azure: deployment+endpoint, Ollama: host+model, Custom: class+JSON).
- **Composite Builder**: Visual SVG flow diagram (updates live), drag-and-drop step reorder.
- **Studio sub-navigation**: Horizontal chip bar across all 10 studio pages.
- **Help page**: Search-within-help, 6 tutorial cards, 5 v4 feature sections.
- **Active nav highlighting**, button press feedback, loading skeletons, keyboard shortcuts (/ = search, Shift+? = help), skip-to-content link, focus-visible outlines, empty state CTAs with action buttons.
- **0 modals** — all replaced with inline forms/banners.
- **table-enhance.js**: Reusable component — search, pagination, rows-per-page for any table via `data-enhance="true"`.
- **Custom SVG icon set**: 8 icons (sajha, mcp, tool, composite, provider, transport, plugin, agent) as inline sprite.

#### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

#### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

### MCP 2025-11-25 upgrade

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

#### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

#### Updated Capabilities Declaration

```json
{
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "tools": {"listChanged": true},
    "prompts": {"listChanged": true},
    "resources": {"subscribe": true, "listChanged": true},
    "logging": {},
    "completions": {},
    "elicitation": {"form": {}, "url": {}},
    "sampling": {"tools": true},
    "tasks": {"experimental": true}
  }
}
```

#### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

#### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
