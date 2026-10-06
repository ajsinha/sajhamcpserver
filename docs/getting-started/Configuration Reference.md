# Configuration Reference

Every key in `config/application.yml`, the keys the code reads that the file leaves out,
and the environment variables that override them. Each entry names the file that reads the
key; a key marked **not used** is loaded but has no effect in this release.

## How a value is resolved

### The config file

- The file is `config/application.yml`, relative to the working directory (`run_server.py`
  changes into the project root first).
- `SAJHA_CONFIG_FILE` selects a different file. `python run_server.py --config <path>`
  sets that variable before any config is loaded.
- Nested YAML is flattened to dotted keys (`mcp.auth.mode`). A key whose value is null
  (`key:` with nothing after it) is treated as absent, so the built-in default applies. An
  empty string (`key: ""`) is a real value.
- `${VAR:default}` inside a YAML value is replaced with environment variable `VAR`, or with
  `default` when `VAR` is unset. This happens when the file is loaded.
- A `.env` file in the working directory is loaded into the environment when
  `sajha/core/config.py` is imported. It never replaces a variable that is already set.

### Three readers

The code reads configuration in three ways, and each one resolves overrides differently.
The **Reader** column in the tables below says which one applies to each key.

| Reader | Used for | Resolution (highest wins) |
|--------|----------|---------------------------|
| **Settings**: `get_settings()` in `sajha/core/config.py` | app, server, db, auth, config, hot_reload, logging, data, cache | 1. env var named after the Settings field, `SAJHA_<FIELD_NAME>` (pydantic-settings, `env_prefix='SAJHA_'`) → 2. `SAJHA_` + the dotted key in upper case with dots changed to underscores → 3. YAML (after `${VAR}` substitution) → 4. built-in default. It is evaluated once per process (`lru_cache`). |
| **Live `_get`**: `_get` / `_bool` / `_int` in `sajha/core/config.py`, called on each use | all `mcp.*` keys | 1. `SAJHA_<DOTTED_KEY>` (for example `SAJHA_MCP_AUTH_MODE`) → 2. YAML → 3. code default. Env vars are read on every call, but the YAML is a snapshot taken at import, so a YAML edit needs a restart. |
| **Raw YAML / PropertiesConfigurator**: `sajha.core.config._CFG` and `sajha/core/properties_configurator.py` | `ai.*`, `storage.*`, `${key}` references inside tool JSON configs | YAML only (after `${VAR}` substitution); `SAJHA_` env overrides **do not apply**. The fallback env vars that `storage.py` and `gateway.py` pass as defaults are used only when the key is **missing** from the YAML. To override one of these keys, edit the YAML, or put a `${VAR:default}` placeholder in the value and set `VAR`. |

For Settings keys, the field name and the dotted key often give the same env var name
(`server.port` → `SAJHA_SERVER_PORT`). Where they differ, both names work, and the field
name wins:

| Key | Field-name env var | Dotted-key env var |
|-----|--------------------|--------------------|
| `auth.jwt.secret` | `SAJHA_JWT_SECRET` | `SAJHA_AUTH_JWT_SECRET` |
| `auth.jwt.algorithm` | `SAJHA_JWT_ALGORITHM` | `SAJHA_AUTH_JWT_ALGORITHM` |
| `auth.jwt.expiry_minutes` | `SAJHA_JWT_EXPIRY_MINUTES` | `SAJHA_AUTH_JWT_EXPIRY_MINUTES` |
| `auth.session.secret_key` | `SAJHA_SECRET_KEY` | `SAJHA_AUTH_SESSION_SECRET_KEY` |
| `hot_reload.interval_seconds` | `SAJHA_HOT_RELOAD_INTERVAL` | `SAJHA_HOT_RELOAD_INTERVAL_SECONDS` |

> **`.env` caveat.** `Settings` also reads `.env` through pydantic-settings, with
> `extra='forbid'`. If `.env` contains any name that is not a Settings field (with or
> without the `SAJHA_` prefix, for example `FMP_API_KEY=...` or `SAJHA_MCP_AUTH_MODE=...`),
> `get_settings()` raises `extra_forbidden` and the server does not start. Until that is
> fixed, put such variables in the real process environment, not in `.env`.

## app

Reader: Settings. These values feed the FastAPI metadata, page templates, the A2A agent card
and the MCP `implementation` (`websiteUrl` = `app.github.repo`). Readers are
`sajha/app.py`, `sajha/routes/a2a_routes.py` and `sajha/core/mcp_handler.py`.

| Key | Default (YAML / code) | Env | Purpose |
|-----|-----------------------|-----|---------|
| `app.name` | `SAJHA MCP Server` | `SAJHA_APP_NAME` | Display name. |
| `app.version` | `6.0.0` / code `5.3.0` | `SAJHA_APP_VERSION` | **The version authority.** It is shown in the UI and API metadata. The code default is stale; keep the key in YAML. |
| `app.description` | `Model Context Protocol Server` | `SAJHA_APP_DESCRIPTION` | FastAPI description and A2A card. |
| `app.author` | `Ashutosh Sinha` | `SAJHA_APP_AUTHOR` | Template context. |
| `app.email` | `ajsinha@gmail.com` | `SAJHA_APP_EMAIL` | Template context. |
| `app.copyright_years` | `2025-2030` | `SAJHA_APP_COPYRIGHT_YEARS` | Template context. |
| `app.github.repo` | `https://github.com/ajsinha/sajhamcpserver` | `SAJHA_APP_GITHUB_REPO` | Templates, and the MCP `websiteUrl`. |
| `app.github.repo_name` | `ajsinha/sajhamcpserver` | `SAJHA_APP_GITHUB_REPO_NAME` | Template context. |

## server

Reader: Settings. The command-line options `--host` and `--port` of `run_server.py` override
both keys.

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `server.host` | `0.0.0.0` (YAML `${SERVER_HOST:0.0.0.0}`) | `SERVER_HOST`, `SAJHA_SERVER_HOST` | Bind address (`run_server.py`). Also used in the startup log and the A2A card URL. |
| `server.port` | `3002` (YAML `${SERVER_PORT:3002}`) | `SERVER_PORT`, `SAJHA_SERVER_PORT` | Listen port (`run_server.py`, `sajha/routes/a2a_routes.py`). |
| `server.debug` | `false` | `SAJHA_SERVER_DEBUG` | **Not used.** It is loaded into Settings, but nothing reads it. |

Env-only:

| Env var | Default | Purpose |
|---------|---------|---------|
| `SAJHA_CORS_ORIGINS` | `http://localhost:3002,http://127.0.0.1:3002,http://0.0.0.0:3002` | Comma-separated CORS allow-list (`sajha/app.py`). It has no YAML key. The default is fixed to port 3002 whatever `server.port` is. This is separate from `mcp.allowed_origins`. |

## db

Reader: Settings, which is used by `sajha/db/engine.py`. The YAML enables SQLite. The
PostgreSQL keys appear only as comments, so their code defaults apply until you uncomment
them.

| Key | Default (YAML / code) | Env | Purpose |
|-----|-----------------------|-----|---------|
| `db.type` | `sqlite` | `SAJHA_DB_TYPE` | `sqlite` or `postgresql`. It also selects the `db/scripts/<type>/` folder. |
| `db.path` | `data/sajha.db` | `SAJHA_DB_PATH` | SQLite file. The parent directory is created if missing. |
| `db.url` | not in YAML / empty | `SAJHA_DB_URL` | A full SQLAlchemy URL. When set, it replaces every other connection key. |
| `db.host` | commented / `localhost` | `SAJHA_DB_HOST` | PostgreSQL host. |
| `db.port` | commented / `5432` | `SAJHA_DB_PORT` | PostgreSQL port. |
| `db.name` | commented `sajha` / code `sajha_mcp` | `SAJHA_DB_NAME` | PostgreSQL database. **The defaults differ.** |
| `db.user` | commented / `sajha` | `SAJHA_DB_USER` | PostgreSQL user. |
| `db.password` | commented / `sajha` | `SAJHA_DB_PASSWORD` | PostgreSQL password. Set it through the env var. |
| `db.driver` | commented / `psycopg2` | `SAJHA_DB_DRIVER` | `psycopg2`. If psycopg2 is not installed, the engine falls back to `psycopg` (v3). |
| `db.ssl` | commented only | — | **Not read.** Nothing reads this key. To configure SSL, put `sslmode` in `db.url`. |
| `db.pool.size` | `10` (YAML `${DB_POOL_SIZE:10}`) | `DB_POOL_SIZE`, `SAJHA_DB_POOL_SIZE` | PostgreSQL `pool_size` and `max_overflow`. |
| `db.echo` | `false` | `SAJHA_DB_ECHO` | Logs every SQL statement. |
| `db.scripts_dir` | `db/scripts` | `SAJHA_DB_SCRIPTS_DIR` | Root of the SQL scripts that run at start-up. |

## auth

Reader: Settings.

| Key | Default (YAML / code) | Env | Purpose / reader |
|-----|-----------------------|-----|------------------|
| `auth.jwt.secret` | YAML `${JWT_SECRET:sajha-jwt-secret-change-in-production}` / code `sajha-jwt-secret-change-me` | `JWT_SECRET`, `SAJHA_JWT_SECRET`, `SAJHA_AUTH_JWT_SECRET` | HMAC key for SAJHA login JWTs (`sajha/auth/jwt_handler.py`). **The defaults differ.** |
| `auth.jwt.algorithm` | `HS256` | `SAJHA_JWT_ALGORITHM`, `SAJHA_AUTH_JWT_ALGORITHM` | JWT algorithm (`jwt_handler.py`). |
| `auth.jwt.expiry_minutes` | `60` (YAML `${JWT_EXPIRY:60}`) | `JWT_EXPIRY`, `SAJHA_JWT_EXPIRY_MINUTES`, `SAJHA_AUTH_JWT_EXPIRY_MINUTES` | Token lifetime (`jwt_handler.py`). The browser cookie `sajha_token` has a fixed `max_age` of 3600 s (`sajha/routes/auth_routes.py`). |
| `auth.session.secret_key` | YAML `${SESSION_SECRET:sajha-session-secret-change-in-production}` / code: a random value per process | `SESSION_SECRET`, `SAJHA_SECRET_KEY`, `SAJHA_AUTH_SESSION_SECRET_KEY` | Keys the OAuth consent-form CSRF tokens (`sajha/auth/oauth/authorization_server.py`). It is also the seed for the MRTR state secret when `mcp.mrtr.state_secret` is empty (`sajha/core/mcp_mrtr.py`, which reads the dotted key directly, so `SAJHA_SECRET_KEY` does not affect it). **The defaults differ.** |
| `auth.session.timeout_minutes` | `60` | — | **Not used.** Nothing reads this key. |

## oauth (legacy)

| Key | Default | Env | Status |
|-----|---------|-----|--------|
| `oauth.mode` | `none` | `SAJHA_OAUTH_MODE` | **Not used by 6.0.0.** MCP authorization is configured under `mcp.auth`; see the [OAuth Guide](../protocol/OAuth%20Guide.md). |
| `oauth.provider` | `""` | `SAJHA_OAUTH_PROVIDER` | **Not used by 6.0.0.** Loaded into Settings (`oauth_provider`), but no code reads it. The `oauth_provider` matches elsewhere are a database column of the same name. |
| `oauth.azure.tenant_id` | `${AZURE_TENANT_ID:}` | `AZURE_TENANT_ID` | **Not used by 6.0.0.** |
| `oauth.azure.client_id` | `${AZURE_CLIENT_ID:}` | `AZURE_CLIENT_ID` | **Not used by 6.0.0.** |
| `oauth.azure.client_secret` | `${AZURE_CLIENT_SECRET:}` | `AZURE_CLIENT_SECRET` | **Not used by 6.0.0.** |

## mcp

Reader: live `_get`, read on each use. The env override is `SAJHA_` plus the dotted key in
upper case with dots changed to underscores (for example `mcp.tasks.max_tasks` →
`SAJHA_MCP_TASKS_MAX_TASKS`). The YAML and code defaults match unless the table notes
otherwise. Clamps are applied in code. Protocol behaviour is covered in the
[MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md), the
[OAuth Guide](../protocol/OAuth%20Guide.md) and the
[MCP Apps and Headers Guide](../protocol/MCP%20Apps%20and%20Headers%20Guide.md).

### Transport and tools

| Key | Default | Meaning | Reader |
|-----|---------|---------|--------|
| `mcp.allowed_origins` | `[]` | The browser `Origin` values allowed on `/mcp`. Other origins get 403. Localhost and requests without an `Origin` header are always allowed, and `"*"` disables the check. The env form is a comma-separated list. | `sajha/core/mcp_2025_11_25.py` |
| `mcp.tools.advertise_output_schema` | `true` | Sends `outputSchema` in tools/list and `structuredContent` from tools/call. | `sajha/core/mcp_handler.py` |
| `mcp.conformance_fixtures` | `false` | Exposes the official conformance-suite test tools, prompts and resources. Use it for protocol testing only. | `sajha/core/mcp_conformance_fixtures.py` |
| `mcp.confirm_destructive_tools` | `false` | Asks the user to confirm, through MRTR elicitation, before running a tool annotated `destructiveHint: true`. This happens only when the client supports elicitation. Applies to 2026-07-28 requests. | `sajha/core/mcp_modern.py` |

### Caching hints (2026-07-28)

| Key | Default | Meaning | Reader |
|-----|---------|---------|--------|
| `mcp.cache.discover_ttl_ms` | `300000` | `ttlMs` on server/discover. | `sajha/core/mcp_modern.py` |
| `mcp.cache.list_ttl_ms` | `60000` | `ttlMs` on tools/list, prompts/list, resources/list and resources/templates/list. | `sajha/core/mcp_modern.py` |
| `mcp.cache.read_ttl_ms` | `30000` | `ttlMs` on resources/read. | `sajha/core/mcp_modern.py` |
| `mcp.cache.scope` | `auto` | `public`, `private` or `auto`. `auto` gives `private` when the result depends on the caller. | `sajha/core/mcp_modern.py` |

### Multi round-trip requests (MRTR), tasks and subscriptions (2026-07-28)

| Key | Default | Meaning | Reader |
|-----|---------|---------|--------|
| `mcp.mrtr.state_secret` | `""` | HMAC key for the signed `requestState`. When empty, it is derived from `auth.session.secret_key`, or is random per process if that is empty too. Set it when running more than one worker. | `sajha/core/mcp_mrtr.py` |
| `mcp.mrtr.state_ttl_seconds` | `900` (min 1) | Lifetime of a `requestState`. | `sajha/core/mcp_mrtr.py` |
| `mcp.tasks.enabled` | `true` | Advertises and serves the `io.modelcontextprotocol/tasks` extension. | `sajha/core/mcp_modern.py` |
| `mcp.tasks.ttl_ms` | `3600000` (min 1000) | How long a task stays readable. | `sajha/core/mcp_tasks.py` |
| `mcp.tasks.poll_interval_ms` | `500` (min 1) | The `pollIntervalMs` hint sent to clients. | `sajha/core/mcp_tasks.py` |
| `mcp.tasks.max_tasks` | `1000` (min 1) | Maximum number of tasks held in memory. | `sajha/core/mcp_tasks.py` |
| `mcp.subscriptions.max_streams` | `1000` (min 1) | Maximum number of concurrent `subscriptions/listen` streams. | `sajha/core/mcp_modern.py` |

### Authorization (`mcp.auth`)

The reader is `sajha/auth/oauth/settings.py` unless the table says otherwise. See the
[OAuth Guide](../protocol/OAuth%20Guide.md).

| Key | Default | Meaning |
|-----|---------|---------|
| `mcp.auth.mode` | `off` | `off`, `optional` or `required`. Any other value is treated as `off`. Keep it quoted in YAML, because a bare `off` is a boolean. |
| `mcp.auth.authorization_server` | `builtin` | `builtin`, or the issuer URL of an external authorization server. |
| `mcp.auth.public_url` | `""` | The externally visible origin. The token audience and the built-in issuer derive from it. When empty, it is taken from the request `Host`. It also sets the caching of discovery documents (`sajha/routes/oauth_routes.py`). |
| `mcp.auth.scopes` | `mcp:read mcp:tools` | Scopes advertised in the protected-resource metadata and in 401 challenges. |
| `mcp.auth.accepted_audiences` | `""` | Extra accepted `aud` values, comma-separated. |
| `mcp.auth.algorithms` | not in YAML / all RS, PS and ES algorithms | Comma-separated JWT algorithms to accept. `none` and `HS*` are always removed. |
| `mcp.auth.clock_skew_seconds` | `60` (min 0) | Leeway for `exp` and `nbf`. |
| `mcp.auth.jwks_cache_seconds` | `3600` (min 60) | How long fetched JWKS are cached. |
| `mcp.auth.external.user_claim` | `sub` | The claim matched against SAJHA user IDs when an external issuer is used. |
| `mcp.auth.builtin.access_token_ttl_seconds` | `900` (min 60) | Access-token lifetime. |
| `mcp.auth.builtin.refresh_token_ttl_seconds` | `2592000` (min 300) | Refresh-token lifetime. |
| `mcp.auth.builtin.code_ttl_seconds` | `60` (30–600) | Authorization-code lifetime. |
| `mcp.auth.builtin.refresh_tokens` | `offline_access` | `offline_access`, `always` or `never`. |
| `mcp.auth.builtin.signing_key_path` | `""` → `<data.dir>/oauth/signing_key.pem` | Where the RSA-2048 signing key is stored. It is created on first use with mode 0600 (`sajha/auth/oauth/keys.py`). |
| `mcp.auth.builtin.cimd.enabled` | `true` | Accepts Client ID Metadata Document client IDs (https URLs). |
| `mcp.auth.builtin.cimd.allow_localhost` | `false` | Development only: accepts `http://localhost` client IDs. |
| `mcp.auth.builtin.cimd.allow_private_networks` | `false` | Allows fetching metadata documents from private addresses. |
| `mcp.auth.builtin.cimd.timeout_seconds` | `5` (1–30) | Timeout for fetching a metadata document. |
| `mcp.auth.builtin.cimd.max_bytes` | `16384` (1024–1048576) | Size limit for a metadata document. |
| `mcp.auth.builtin.dynamic_client_registration` | `false` | RFC 7591 registration. Registrations are kept in memory. |
| `mcp.auth.builtin.clients` | `[]` | Pre-registered clients. This key is read straight from the YAML file named by `SAJHA_CONFIG_FILE`, not from the flattened config. Its env override is `SAJHA_MCP_AUTH_BUILTIN_CLIENTS`, holding the list as JSON. `${VAR}` placeholders are substituted only in `client_secret`. |

### MCP Apps

| Key | Default | Meaning | Reader |
|-----|---------|---------|--------|
| `mcp.apps.enabled` | `true` | Enables the `io.modelcontextprotocol/ui` extension on 2026-07-28 requests. | `sajha/core/mcp_apps.py`, `sajha/core/mcp_modern.py` |
| `mcp.apps.dir` | not in YAML / `config/apps` | Extra `*.html` views, served alongside the bundled views. | `sajha/core/mcp_apps.py` |

## config

Reader: Settings.

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `config.tools.dir` | `config/tools` | `SAJHA_CONFIG_TOOLS_DIR` | Tool JSON configs (`sajha/app.py` → tools registry). |
| `config.prompts.dir` | `config/prompts` | `SAJHA_CONFIG_PROMPTS_DIR` | Prompt configs (`sajha/app.py` → prompts registry). |
| `config.plugins.dir` | `config/plugins` | `SAJHA_CONFIG_PLUGINS_DIR` | Plugins (`sajha/core/plugins.py`). |
| `config.users.path` | `config/users.json` | `SAJHA_CONFIG_USERS_PATH` | Legacy users imported at seed time (`sajha/db/seed.py`). |
| `config.apikeys.path` | `config/apikeys.json` | `SAJHA_CONFIG_APIKEYS_PATH` | Legacy API keys imported at seed time (`sajha/db/seed.py`). |
| `config.ir.dir` | `config/ir` | `SAJHA_CONFIG_IR_DIR` | **Not used.** It is loaded into Settings, but nothing reads it. |

## hot_reload

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `hot_reload.enabled` | `true` | `SAJHA_HOT_RELOAD_ENABLED` | **Not used.** The config reloader always starts (`sajha/app.py`). |
| `hot_reload.interval_seconds` | `300` | `SAJHA_HOT_RELOAD_INTERVAL`, `SAJHA_HOT_RELOAD_INTERVAL_SECONDS` | Poll interval of the config reloader (`sajha/app.py`). `sajha/core/reload_manager.py` also reads this key, with a `SAJHA_RELOAD_INTERVAL` fallback, but its `init_reload_manager()` is never called. |

## features

| Key | Default | Env | Status |
|-----|---------|-----|--------|
| `features.websocket.enabled` | `true` | `SAJHA_FEATURES_WEBSOCKET_ENABLED` | **Not used.** It is loaded into Settings, but nothing reads it. |
| `features.monitoring.enabled` | `true` | `SAJHA_FEATURES_MONITORING_ENABLED` | **Not used.** |
| `features.admin.panel.enabled` | `true` | `SAJHA_FEATURES_ADMIN_PANEL_ENABLED` | **Not used.** |

## logging

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `logging.level` | `INFO` (YAML `${LOG_LEVEL:INFO}`) | `LOG_LEVEL`, `SAJHA_LOGGING_LEVEL` | Root log level (`run_server.py`). The command-line option `--log-level` overrides it. |
| `logging.dir` | `./logs` | `SAJHA_LOGGING_DIR` | **Not used.** `run_server.py` always writes to `logs/server.log`. |
| `logging.file` | `""` | `SAJHA_LOGGING_FILE` | **Not used.** |

## data

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `data.dir` | `./data` | `SAJHA_DATA_DIR` | Base of the default OAuth signing-key path (`sajha/auth/oauth/settings.py`). |
| `data.duckdb.dir` | `./data/duckdb` | YAML only | Not read by Python. Tool JSON configs (DuckDB tools) and `config/olap/datasets.json` reference it as `${data.duckdb.dir}`, and the tools registry resolves those references through PropertiesConfigurator. |
| `data.sqlselect.dir` | `./data/sqlselect` | YAML only | Referenced as `${data.sqlselect.dir}` by the sqlselect tool configs. |

## storage

Reader: PropertiesConfigurator, through `init_storage()` in `sajha/core/storage.py`, which
is called from `sajha/app.py`. As described under
[Three readers](#three-readers), the env names in the YAML comments (`SAJHA_STORAGE_BACKEND`,
`SAJHA_S3_BUCKET`, `AWS_DEFAULT_REGION` and so on) are only fallbacks for a key that is
**missing** from the YAML. To switch backend through the environment, write the value as
`${SAJHA_STORAGE_BACKEND:local}` in the YAML. See the [Storage Guide](Storage%20Guide.md).

| Key | Default (YAML / code fallback) | Fallback env var | Purpose |
|-----|--------------------------------|------------------|---------|
| `storage.backend` | `local` | `SAJHA_STORAGE_BACKEND` | `local`, `s3`, `azure` or `gcs`. |
| `storage.base_dir` | `.` | `SAJHA_BASE_DIR` | Root directory of the local backend. |
| `storage.s3.bucket` | `""` | `SAJHA_S3_BUCKET` | S3 bucket. |
| `storage.s3.prefix` | `sajha/` / code `""` | `SAJHA_S3_PREFIX` | Key prefix. **The defaults differ.** |
| `storage.s3.region` | `us-east-1` | `AWS_DEFAULT_REGION` | Region. |
| `storage.s3.endpoint_url` | `""` | `SAJHA_S3_ENDPOINT_URL` | S3-compatible endpoint (MinIO, R2, Wasabi). |
| `storage.s3.cache_dir` | `/tmp/sajha-cache` | `SAJHA_S3_CACHE_DIR` | Local read-through cache. |
| `storage.s3.sync_interval` | `60` | — | Poll interval of the object-store sync manager, for any cloud backend (`sajha/app.py`). |
| `storage.azure.container` | `""` | `SAJHA_AZURE_CONTAINER` | Blob container. |
| `storage.azure.account_url` | `""` | `SAJHA_AZURE_ACCOUNT_URL` | Account URL, used with managed identity. |
| `storage.azure.connection_string` | `""` | `AZURE_STORAGE_CONNECTION_STRING` | Connection-string authentication. Keep it out of the YAML. |
| `storage.azure.prefix` | `sajha/` / code `""` | `SAJHA_AZURE_PREFIX` | Blob prefix. **The defaults differ.** |
| `storage.azure.cache_dir` | `/tmp/sajha-cache` | `SAJHA_AZURE_CACHE_DIR` | Local cache. |
| `storage.gcs.bucket` | `""` | `SAJHA_GCS_BUCKET` | GCS bucket. |
| `storage.gcs.project` | `""` | `GOOGLE_CLOUD_PROJECT` | GCP project. |
| `storage.gcs.prefix` | `sajha/` / code `""` | `SAJHA_GCS_PREFIX` | Object prefix. **The defaults differ.** |
| `storage.gcs.cache_dir` | `/tmp/sajha-cache` | `SAJHA_GCS_CACHE_DIR` | Local cache. |

`sajha/app.py` calls `init_storage()` twice. The first call reads `storage_*` attributes
that `Settings` does not define, so it always builds a local backend. The second call, in
`_init_managers()`, reads the YAML and builds the backend that is actually used.

## External API keys

These keys are not read by Python. Tool JSON configs reference them as `${key}`, and the
tools registry resolves them through PropertiesConfigurator. Set the env var named in the
YAML placeholder.

| Key | YAML value | Env | Used by |
|-----|-----------|-----|---------|
| `fmp.api.key` | `${FMP_API_KEY:}` | `FMP_API_KEY` | `config/tools/fmp_*.json` |
| `fred.api.key` | `${FRED_API_KEY:}` | `FRED_API_KEY` | `config/tools/fred_*.json` |
| `google.api.key` | `${GOOGLE_API_KEY:}` | `GOOGLE_API_KEY` | `config/tools/google_search.json` |
| `google.search.engine.id` | `${GOOGLE_SEARCH_ENGINE_ID:}` | `GOOGLE_SEARCH_ENGINE_ID` | `config/tools/google_search.json` |
| `tavily.api.key` | `${TAVILY_API_KEY:}` | `TAVILY_API_KEY` | `config/tools/tavily_*.json` |
| `alpha_vantage.api.key` | **not in YAML** | an env var literally named `alpha_vantage.api.key` | `config/tools/av_*.json`. With no YAML key, the `${alpha_vantage.api.key}` placeholder stays unresolved. Add `alpha_vantage: {api: {key: ${ALPHA_VANTAGE_API_KEY:}}}` to the YAML to supply it. |

`Settings` also defines `google_api_key`, `google_search_engine_id`, `fred_api_key` and
`tavily_api_key` fields, but no code reads those fields.

## ai

Reader: raw YAML (`_CFG`), passed to `sajha/ai/gateway.py` and `sajha/ai/embedders.py` from
`sajha/app.py`. `SAJHA_` overrides do not apply; set the env var named in the `${...}`
placeholder. If the database has `llm_providers` rows, the gateway takes its providers and
its default provider and model from the database. The per-provider keys below are used only
as the env fallback, when there is no database session or loading from it fails. For
database-registered providers, a missing API key falls back to `SAJHA_<PROVIDER>_API_KEY`,
then `<PROVIDER>_API_KEY`.

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `ai.default_provider` | `anthropic` | `AI_DEFAULT_PROVIDER` | Gateway default provider (`gateway.py`). |
| `ai.default_model` | `claude-sonnet-4-20250514` | `AI_DEFAULT_MODEL` | Gateway default model (`gateway.py`). |
| `ai.embedding_provider` | `openai` | `AI_EMBEDDING_PROVIDER` | Gateway embedding provider (`gateway.py`). |
| `ai.embedding_model` | `text-embedding-3-small` | `AI_EMBEDDING_MODEL` | Embedding model (`gateway.py`, `embedders.py`). |
| `ai.tool_search.enabled` | `true` | — | Builds the semantic tool-search index (`sajha/app.py`). **Caveat:** the value is used as a string, so `false` is truthy and does not turn the feature off. |
| `ai.tool_search.embedder` | `bm25` | `AI_TOOL_SEARCH_EMBEDDER` | `bm25`, which is lexical, or `gateway`, which uses API embeddings (`embedders.py`). |
| `ai.tool_search.persist` | `true` | — | Persists the vector index (`sajha/app.py`). It has the same string-truthiness caveat. |
| `ai.tool_search.top_k` | `5` | — | **Not used.** `top_k` is a parameter of each call. |
| `ai.cache.enabled` | `true` | — | Response cache of the gateway (`gateway.py`). It has the same string-truthiness caveat. |
| `ai.cache.ttl_seconds` | `3600` | — | TTL of the gateway cache (`gateway.py`). |
| `ai.anthropic.api_key` | `${ANTHROPIC_API_KEY:}` | `ANTHROPIC_API_KEY` | Env fallback provider registration (`gateway.py`). |
| `ai.openai.api_key` | `${OPENAI_API_KEY:}` | `OPENAI_API_KEY` | Same as above. |
| `ai.bedrock.region` | `${AWS_DEFAULT_REGION:us-east-1}` | `AWS_DEFAULT_REGION` | Same as above. |
| `ai.together.api_key` | `${TOGETHER_API_KEY:}` | `TOGETHER_API_KEY` | Same as above. |
| `ai.ollama.base_url` | `${OLLAMA_BASE_URL:http://localhost:11434}` | `OLLAMA_BASE_URL` | Same as above. |
| `ai.azure_openai.api_key` | `${AZURE_OPENAI_API_KEY:}` | — | **Not used.** The env fallback does not include Azure OpenAI. |
| `ai.azure_openai.endpoint` | `${AZURE_OPENAI_ENDPOINT:}` | — | **Not used.** |

## cache (tool output cache)

Reader: Settings, used by `get_tool_cache()` in `sajha/core/cache.py`. The cache time per
tool is set by `cache_ttl` in each tool's JSON config.

| Key | Default | Env | Purpose |
|-----|---------|-----|---------|
| `cache.enabled` | `true` (YAML `${CACHE_ENABLED:true}`) | `CACHE_ENABLED`, `SAJHA_CACHE_ENABLED` | Master switch for the cache. |
| `cache.dir` | `data/cache` (YAML `${CACHE_DIR:data/cache}`) | `CACHE_DIR`, `SAJHA_CACHE_DIR` | Directory for cache files. |
| `cache.max_files` | `50000` (YAML `${CACHE_MAX_FILES:50000}`) | `CACHE_MAX_FILES`, `SAJHA_CACHE_MAX_FILES` | Number of files before eviction. |
| `cache.max_file_size_kb` | `512` (YAML `${CACHE_MAX_FILE_KB:512}`) | `CACHE_MAX_FILE_KB`, `SAJHA_CACHE_MAX_FILE_SIZE_KB` | Results larger than this are not cached. |
| `cache.cleanup_interval_seconds` | `300` | `SAJHA_CACHE_CLEANUP_INTERVAL_SECONDS` | **Not used.** It is loaded into Settings, but nothing reads it. |

## async and shell

In `sajha/core/config.py`, the `async_*` and `shell_*` `Field(...)` lines come after
`return Settings()` inside `get_settings()`. They are unreachable statements in the
function, not class attributes, so `Settings` has no such fields. `get_async_executor()`
(`sajha/core/async_executor.py`) and `get_shell_executor()` (`sajha/core/shell_executor.py`)
read them with `getattr(settings, '<name>', <default>)`, so they always get the code
default. **No `async.*` or `shell.*` key in the YAML, and no env var, has any effect.**
Because `shell.enabled` stays `false`, `/api/shell/python` and `/api/shell/bash` always
return 403.

| Key | Effective value (code) | YAML value |
|-----|------------------------|------------|
| `async.enabled` | not consulted | `${ASYNC_ENABLED:true}` |
| `async.workers` | `8` | `${ASYNC_WORKERS:8}` |
| `async.queue_size` | `1000` | `${ASYNC_QUEUE_SIZE:1000}` |
| `async.task_ttl_hours` | `24` | `${ASYNC_TASK_TTL:24}` |
| `async.delivery.webhook.timeout` | `10` (the factory always passes `delivery_config={}`) | `10` |
| `async.delivery.webhook.max_retries` | `3` | `3` |
| `async.delivery.kafka.bootstrap_servers` | `localhost:9092` | `${KAFKA_BROKERS:localhost:9092}` |
| `async.delivery.file.base_dir` | `data/async_results` | `${ASYNC_FILE_DIR:data/async_results}` |
| `async.delivery.file.max_size_mb` | `50` | `50` |
| `shell.enabled` | `false` | `${SHELL_ENABLED:false}` |
| `shell.mode` | `sandbox` | `sandbox` |
| `shell.scratch_dir` | `data/shell_scratch` | `data/shell_scratch` |
| `shell.python.enabled` | `true` (has no effect while the shell is disabled) | `true` |
| `shell.python.timeout_seconds` | `30` | `30` |
| `shell.python.memory_limit_mb` | `256` | `256` |
| `shell.bash.enabled` | `false` | `false` |
| `shell.bash.timeout_seconds` | `15` | `15` |
| `shell.bash.max_output_bytes` | `1048576` (not passed by the factory) | `1048576` |

## Secrets

Supply secrets through the environment, and never commit them to `application.yml`.

| Secret | Where it comes from | Recommendation |
|--------|---------------------|----------------|
| JWT signing secret | `auth.jwt.secret` | Set `JWT_SECRET` (or `SAJHA_JWT_SECRET`). The YAML fallback is a public placeholder string. |
| Session secret | `auth.session.secret_key` | Set `SESSION_SECRET` (or `SAJHA_SECRET_KEY`). It keys the OAuth consent CSRF tokens and seeds the MRTR secret. |
| MRTR state secret | `mcp.mrtr.state_secret` | Set `SAJHA_MCP_MRTR_STATE_SECRET` when running more than one worker, or when request states must stay valid across restarts. |
| OAuth signing key | the file at `mcp.auth.builtin.signing_key_path`, by default `<data.dir>/oauth/signing_key.pem` | It is generated on first use with mode 0600. Keep it out of version control, and share or mount the same file across workers. |
| Pre-registered client secrets | `mcp.auth.builtin.clients[].client_secret` | Use `${ENV_VAR}` placeholders, or set `SAJHA_MCP_AUTH_BUILTIN_CLIENTS`. |
| Database password | `db.password` / `db.url` | Set `SAJHA_DB_PASSWORD` or `SAJHA_DB_URL`. |
| Provider and data-API keys | `ai.*.api_key`, `fmp`, `fred`, `google`, `tavily` | Set the env var named in the YAML placeholder. |

See also the [Security Model](../security/Security%20Model.md) and the
[Architecture](../architecture/Architecture.md) overview.

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
