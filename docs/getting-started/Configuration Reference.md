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
| **Settings**: `get_settings()` in `sajha/core/config.py` | app, server, db, auth (secrets, JWT), config, hot_reload, logging, data, cache, async, shell | 1. env var named after the Settings field, `SAJHA_<FIELD_NAME>` (pydantic-settings, `env_prefix='SAJHA_'`) → 2. `SAJHA_` + the dotted key in upper case with dots changed to underscores → 3. YAML (after `${VAR}` substitution) → 4. built-in default. It is evaluated once per process (`lru_cache`). |
| **Live `_get`**: `_get` / `_bool` / `_int` / `_list` in `sajha/core/config.py`, called on each use | all `mcp.*` keys, `auth.login.*`, `auth.password.min_length`, `auth.secrets_file`, `async.delivery.webhook.allowed_urls` | 1. `SAJHA_<DOTTED_KEY>` (for example `SAJHA_MCP_AUTH_MODE`) → 2. YAML → 3. code default. Env vars are read on every call, but the YAML is a snapshot taken at import, so a YAML edit needs a restart. |
| **Raw YAML / PropertiesConfigurator**: `sajha.core.config._CFG` and `sajha/core/properties_configurator.py` | `ai.*`, `${key}` references inside tool JSON configs (`storage.*` is read this way too, but with env overrides first: see [storage](#storage)) | YAML only (after `${VAR}` substitution); `SAJHA_` env overrides **do not apply**. The fallback env vars that `storage.py` and `gateway.py` pass as defaults are used only when the key is **missing** from the YAML. To override one of these keys, edit the YAML, or put a `${VAR:default}` placeholder in the value and set `VAR`. |

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

> **`.env`.** `Settings` also reads `.env` through pydantic-settings, with `extra='ignore'`:
> names that are not Settings fields (`FMP_API_KEY=...`, `SAJHA_MCP_AUTH_MODE=...`) do not
> stop start-up, and they still reach the code through the process environment. A
> `SAJHA_*` name that matches no Settings field, no YAML key and no known env-only name is
> logged as a warning (`.env: <NAME> is not a SAJHA setting; ignored`).

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
| `auth.jwt.secret` | YAML `${JWT_SECRET:}` / code `""`: empty means generated once (256 bits) and persisted in `auth.secrets_file` | `JWT_SECRET`, `SAJHA_JWT_SECRET`, `SAJHA_AUTH_JWT_SECRET` | HMAC key for SAJHA login JWTs (`sajha/auth/jwt_handler.py`). A value equal to a placeholder SAJHA ever shipped stops start-up (`sajha/core/server_secrets.py`); a value shorter than 32 characters logs a warning. |
| `auth.jwt.algorithm` | `HS256` | `SAJHA_JWT_ALGORITHM`, `SAJHA_AUTH_JWT_ALGORITHM` | JWT algorithm (`jwt_handler.py`). |
| `auth.jwt.expiry_minutes` | `60` (YAML `${JWT_EXPIRY:60}`) | `JWT_EXPIRY`, `SAJHA_JWT_EXPIRY_MINUTES`, `SAJHA_AUTH_JWT_EXPIRY_MINUTES` | Token lifetime (`jwt_handler.py`). The browser cookie `sajha_token` has a fixed `max_age` of 3600 s (`sajha/routes/auth_routes.py`). |
| `auth.session.secret_key` | YAML `${SESSION_SECRET:}` / code `""`: empty means generated and persisted, like `auth.jwt.secret` | `SESSION_SECRET`, `SAJHA_SECRET_KEY`, `SAJHA_AUTH_SESSION_SECRET_KEY` | Keys the OAuth consent-form CSRF tokens (`sajha/auth/oauth/authorization_server.py`). It is also the seed for the MRTR state secret when `mcp.mrtr.state_secret` is empty (`sajha/core/mcp_mrtr.py` uses the resolved Settings value). Placeholder values stop start-up. |
| `auth.session.timeout_minutes` | `60` | — | **Not used.** Nothing reads this key. |
| `auth.secrets_file` | `""` → `<data.dir>/secrets/server_secrets.json` | `SAJHA_AUTH_SECRETS_FILE` | Where generated secrets are kept: JSON, mode 0600 in a 0700 directory, created on first start (`sajha/core/server_secrets.py`). `data/secrets/` is git-ignored. Workers that share it share the secrets. Deleting it signs everyone out. |
| `auth.login.max_failed_attempts` | `5` (min 1) | `SAJHA_AUTH_LOGIN_MAX_FAILED_ATTEMPTS` | Consecutive failed sign-ins that lock an account (`sajha/auth/__init__.py`, `AuthManager.sign_in`). |
| `auth.login.lockout_minutes` | `15` (min 1) | `SAJHA_AUTH_LOGIN_LOCKOUT_MINUTES` | How long a locked account stays locked. |
| `auth.login.ip_max_failures` | `20` (min 1) | `SAJHA_AUTH_LOGIN_IP_MAX_FAILURES` | Failed sign-ins per client IP within the window before 429 (`sajha/security.py`). |
| `auth.login.ip_window_seconds` | `300` (min 1) | `SAJHA_AUTH_LOGIN_IP_WINDOW_SECONDS` | The window for `ip_max_failures`. |
| `auth.password.min_length` | not in YAML / `8` (never below 8) | `SAJHA_AUTH_PASSWORD_MIN_LENGTH` | Minimum length of a new password (`sajha/auth/password.py`). |

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

### Anonymous access (`mcp.anonymous`)

Callers with no credentials on `/mcp`, `/api/mcp`, `/mcp/sse`, `/mcp/message`, `/mcp/ws`
and `/a2a`, possible while `mcp.auth.mode` is `off` or `optional`. Reader:
`sajha/auth/access.py`. See [Tool access](../security/Security%20Model.md#tool-access).

| Key | Default | Meaning |
|-----|---------|---------|
| `mcp.anonymous.enabled` | `true` | `false`: every MCP transport and `/a2a` need credentials (401, or WebSocket close 1008). |
| `mcp.anonymous.tools` | `[]` | Tools anonymous callers may see and run: fnmatch patterns (`["calc_*", "wikipedia_search"]`); `["*"]` means every tool. The env form is comma-separated (`SAJHA_MCP_ANONYMOUS_TOOLS="calc_*,wiki_*"`). The conformance fixtures are callable regardless. |
| `mcp.anonymous.role` | `""` | Also grant anonymous callers the tool permissions of this SAJHA role. |

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
| `mcp.mrtr.state_secret` | `""` | HMAC key for the signed `requestState`. When empty, it is derived from the resolved `auth.session.secret_key` (persisted in `auth.secrets_file` when not configured), so states stay valid across restarts and workers sharing the data directory. A placeholder value stops start-up. | `sajha/core/mcp_mrtr.py` |
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
is called from `sajha/app.py`. Each key resolves (`storage_setting`) as: 1. the env var in the
table below (`STORAGE_ENV_OVERRIDES`) → 2. `SAJHA_` + the dotted key (for example
`SAJHA_STORAGE_S3_BUCKET`) → 3. the YAML → 4. the code default. An env var set to an empty
string is ignored. See the [Storage Guide](Storage%20Guide.md).

| Key | Default (YAML / code fallback) | Env override | Purpose |
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
| `alpha_vantage.api.key` | `${ALPHA_VANTAGE_API_KEY:}` | `ALPHA_VANTAGE_API_KEY` | `config/tools/av_*.json` |

`Settings` also defines `google_api_key`, `google_search_engine_id`, `fred_api_key` and
`tavily_api_key` fields, but no code reads those fields.

## ai

Reader: the raw nested YAML (`sajha/ai/llm/settings.py`), validated by pydantic models;
unknown keys fail at startup. How the layer behaves is described in the
[Intelligence Layer](../architecture/Intelligence%20Layer.md); this section lists the keys.
Precedence, highest first: `SAJHA_AI_<SECTION>_<FIELD>` → the vendor's own variable
(providers only) → `config/application.yml` → the `llm_providers` / `llm_models` tables
(providers only) → the default. `<SECTION>` is a provider's name upper-cased with
non-alphanumerics as `_` (`SAJHA_AI_AZURE_OPENAI_API_VERSION`) or a section name below
(`SAJHA_AI_ASK_MAX_STEPS`). Lists accept JSON or a comma list; dictionaries and lists of
objects take JSON. The effective values and their sources are `GET /api/ai/config` (admin).

Out of the box only the `mock` provider is enabled and every alias resolves to it. A real
provider is used only after `enabled: true` (or `SAJHA_AI_<PROVIDER>_ENABLED=true`); a key
in the environment does not enable it.

### `ai.providers[]`

A list of `{name, class?, type?, config}`. `name` is the provider's registry name (or a new
name with `class: package.module:Class` or `type: <registered name>`); `config` holds the
fields below. Built-in providers not listed still exist, disabled.

| Field (all providers) | Default | Purpose |
|---|---|---|
| `enabled` | `false` (`mock`: `true`) | `true`, `false`, or `auto` (enabled when it has a key; keyless local servers when `base_url` is configured; Ollama when reachable). |
| `api_key` | — | The key. Prefer the environment; never commit it. |
| `api_key_ref` | — | `env:NAME`, `file:/path` or `db:llm_providers/<type>`. |
| `base_url` | per provider | Endpoint (Azure: the resource endpoint). |
| `extra_headers` | `{}` | Added to every request. |
| `proxy` | — | HTTP(S) proxy URL. |
| `verify_tls` / `ca_bundle` | `true` / — | TLS verification and an optional CA bundle path. |
| `connect_timeout_s` / `read_timeout_s` | `5` / `120` (Ollama `300`) | Timeouts. |
| `max_retries`, `backoff_base_s`, `backoff_max_s` | from `ai.retry` | Per-provider retry overrides. |
| `max_concurrency` | `8` | Concurrent calls to this provider. |
| `default_model` / `default_embedding_model` | per provider | Used when an alias names only the provider. |
| `embedding_dimensions` | — | Requested embedding size, where the vendor supports it. |
| `default_temperature` / `default_max_output_tokens` | — / `4096` | Request defaults. |
| `streaming` | `true` | `false` makes `stream()` fall back to one response. |
| `health_timeout_s` | `2` (Ollama `1`) | Timeout of a health probe. |
| `catalog` | `true` | Include the curated model list (`sajha/ai/llm/catalog.py`). |
| `models` | `[]` | Add or override models: `{id, kind, display_name, enabled, tools, structured_output, vision, streaming, temperature, forced_tool_choice, context_window, max_output_tokens, input_cost_per_mtok, output_cost_per_mtok, dimensions, tags, deployment}`. |

| Provider | Extra fields | Vendor variables honoured |
|---|---|---|
| `anthropic` | `api_version` (`2023-06-01`), `beta_headers`, `auth` (`api_key`/`bearer`), `structured_output_param`, `messages_path`, `extra_body` | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` |
| `openai` | `organization`, `project`, `max_tokens_param`, `strict_schema`, `stream_usage`, `parallel_tool_calls`, `tool_choice_required`, `chat_path`, `embeddings_path`, `extra_body` | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` |
| `azure_openai` | the `openai` fields plus `api_style` (`v1`/`deployments`), `api_version` (`2024-10-21`), `deployments` (model id → deployment), `auth` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION` |
| `gemini` | `api_version` (`v1beta`), `schema_mode` (`json_schema`/`openapi`), `safety_settings`, `generation_config`, `embedding_task_type` | `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| `bedrock` | `region`, `profile`, `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`, `embedding_input_type`, `guardrail_identifier`, `guardrail_version`, `additional_model_request_fields` | `AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` |
| `mistral` | the `openai` fields (`tool_choice_required: any`) | `MISTRAL_API_KEY` |
| `cohere` | `tool_result_format`, `embedding_input_type`, `chat_path`, `embed_path` | `COHERE_API_KEY`, `CO_API_KEY` |
| `ollama` | `keep_alive`, `num_ctx`, `think`, `options`, `detect_capabilities`, `live_models`, `health_ttl_s` | `OLLAMA_HOST`, `OLLAMA_BASE_URL` |
| `groq`, `together`, `fireworks`, `deepseek`, `xai`, `openrouter`, `perplexity`, `vllm`, `lmstudio`, `openai_compatible` | the `openai` fields plus `live_models`, `models_path` | `GROQ_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY`, `PERPLEXITY_API_KEY` |
| `mock` | `latency_ms` (`[0, 0]`), `fail_every` (`0`), `fail_with`, `retry_after_s`, `seed` (`42`), `scripts_dir` (`config/ai/mock_scripts`), `embed_dimensions` (`256`), `max_planner_tools` (`2`) | — |

### Gateway and ask sections

| Key | Default | Purpose |
|---|---|---|
| `ai.aliases.<name>` | `default`, `fast`, `reasoning` → `[mock/mock-planner]`; `embedding` → `[mock/mock-embed]` | Ordered candidates: `provider/model` or a bare provider. Env: `SAJHA_AI_ALIASES_<NAME>`. |
| `ai.policy.enabled` | `true` | Apply role policy. |
| `ai.policy.roles.<role>` | shipped: `viewer: {allowed: [mock/*], tools: false}` | `{allowed: [globs], tools, max_output_tokens, daily_tokens}`. |
| `ai.policy.default` | — | Policy for roles not listed; unset means unrestricted. |
| `ai.budgets.enabled` | `true` | Enforce budgets. |
| `ai.budgets.per_user_daily_tokens` | — | Tokens per user per UTC day. YAML placeholder `AI_PER_USER_DAILY_TOKENS`. |
| `ai.budgets.per_role_daily_tokens` | `{}` | Tokens per role per UTC day. |
| `ai.cache.enabled` / `ttl_seconds` / `max_entries` | `true` / `3600` / `500` | Gateway response cache. |
| `ai.cache.cache_nonzero_temperature` | `false` | Also cache sampled responses. |
| `ai.retry.max_retries` / `backoff_base_s` / `backoff_max_s` | `2` / `0.5` / `20` | Retries of RateLimited / ProviderUnavailable. |
| `ai.retry.jitter` / `max_retry_after_s` | `0.5` / `30` | Backoff jitter (fraction) and the longest Retry-After honoured. |
| `ai.breaker.enabled` / `failure_threshold` / `recovery_timeout_s` | `true` / `5` / `60` | Per-provider circuit breaker. |
| `ai.gateway.health_ttl_s` | `30` | How long a provider's health is cached. |
| `ai.gateway.trace_prompts` | `false` | Put prompts on OpenTelemetry spans (debug only). |
| `ai.gateway.load_entry_points` | `true` | Load `sajha.llm_providers` plug-ins. |
| `ai.gateway.use_db_providers` | `true` | Read keys and models from the `llm_providers` / `llm_models` tables. |
| `ai.ask.enabled` | `true` | Serve `POST /api/ai/ask`. |
| `ai.ask.model` | `default` | Alias or `provider/model` used by ask. |
| `ai.ask.max_steps` / `max_tool_calls` / `max_tokens` / `timeout_s` | `6` / `10` / `50000` / `60` | Limits of one ask. |
| `ai.ask.shortlist` | `12` | Tools offered to the model. |
| `ai.ask.max_result_chars` | `4000` | Cap on each tool result returned to the model. |
| `ai.ask.temperature` | `0` | Sampling temperature of ask calls. |
| `ai.ask.confirm_destructive` | `true` | Hold destructive tools for confirmation. |
| `ai.ask.synthesize` | `true` | Final structured-output call. |
| `ai.ask.audit` | `true` | Write an `ai_ask` audit entry per ask. |
| `ai.ask.mcp_tool_enabled` | `false` | Register the `sajha_ask` MCP tool. |
| `ai.ask.mcp_allowed_tools` | `[]` | Extra fnmatch patterns `sajha_ask` may run beyond the anonymous MCP policy. |

### Tool search

Reader: the flattened config (`_CFG`), in `sajha/app.py` and `sajha/ai/embedders.py`.

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `ai.tool_search.enabled` | `true` | — | Builds the tool-search index (`sajha/app.py`). |
| `ai.tool_search.embedder` | `bm25` | `AI_TOOL_SEARCH_EMBEDDER` | `bm25` (lexical) or `gateway` (embeddings through the `embedding` alias) (`embedders.py`). |
| `ai.tool_search.persist` | `true` | — | Persists the vector index (`sajha/app.py`). |
| `ai.tool_search.top_k` | `5` | — | **Not used.** `top_k` is a parameter of each call. |

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

Reader: Settings (`sajha/core/config.py`), used by `get_async_executor()`
(`sajha/core/async_executor.py`) and `get_shell_executor()` (`sajha/core/shell_executor.py`)
when each is first used. Env overrides follow the Settings rules: the field-name form
(`SAJHA_ASYNC_WORKERS`, `SAJHA_SHELL_ENABLED`) or the dotted form
(`SAJHA_SHELL_PYTHON_TIMEOUT_SECONDS`). Who may call the endpoints is in the
[Security Model](../security/Security%20Model.md) (async: admin or `async:execute`; shell:
admin or `shell:execute`).

| Key | Default | Purpose |
|-----|---------|---------|
| `async.enabled` | `true` (YAML `${ASYNC_ENABLED:true}`) | `false`: `POST /api/tools/{tool}/execute-async` answers 503. |
| `async.workers` | `8` (YAML `${ASYNC_WORKERS:8}`) | Worker threads. |
| `async.queue_size` | `1000` (YAML `${ASYNC_QUEUE_SIZE:1000}`) | Pending tasks before 503. |
| `async.task_ttl_hours` | `24` (YAML `${ASYNC_TASK_TTL:24}`) | How long finished tasks stay listed. |
| `async.delivery.webhook.timeout` | `10` | Seconds per webhook attempt. |
| `async.delivery.webhook.max_retries` | `3` | Webhook attempts. |
| `async.delivery.webhook.allowed_urls` | `[]` | URL prefixes a webhook may target (same scheme, host and port; path at or under the prefix's path). Empty refuses every webhook. Live reader; env `SAJHA_ASYNC_DELIVERY_WEBHOOK_ALLOWED_URLS`, comma-separated. |
| `async.delivery.webhook.allow_private_networks` | `false` | Allow targets that resolve to loopback or private addresses (never link-local). |
| `async.delivery.kafka.bootstrap_servers` | `localhost:9092` (YAML `${KAFKA_BROKERS:localhost:9092}`) | Kafka brokers. |
| `async.delivery.file.base_dir` | `data/async_results` (YAML `${ASYNC_FILE_DIR:data/async_results}`) | The only directory file delivery may write in; destinations are relative paths inside it. |
| `async.delivery.file.max_size_mb` | `50` | Results larger than this are not written. |
| `shell.enabled` | `false` (YAML `${SHELL_ENABLED:false}`) | Master switch for `/api/shell/*`. |
| `shell.mode` | `sandbox` | Passed to the executor. |
| `shell.scratch_dir` | `data/shell_scratch` | Working directory for scripts. |
| `shell.python.enabled` | `true` | Python, once the shell is enabled. |
| `shell.python.timeout_seconds` | `30` | Python timeout. |
| `shell.python.memory_limit_mb` | `256` | Passed to the executor but **not applied** (see the Security Model). |
| `shell.bash.enabled` | `false` | Bash needs this as well as `shell.enabled`. |
| `shell.bash.timeout_seconds` | `15` | Bash timeout. |
| `shell.bash.max_output_bytes` | `1048576` | Bash output cap. |

## Secrets

Supply secrets through the environment, and never commit them to `application.yml`.

| Secret | Where it comes from | Recommendation |
|--------|---------------------|----------------|
| JWT signing secret | `auth.jwt.secret` | Leave it empty to have it generated into `auth.secrets_file`, or set `JWT_SECRET` (or `SAJHA_JWT_SECRET`) to a long random value, the same on every instance. Known placeholder values stop start-up. |
| Session secret | `auth.session.secret_key` | As above, with `SESSION_SECRET` (or `SAJHA_SECRET_KEY`). It keys the OAuth consent CSRF tokens and seeds the MRTR secret. |
| Generated secrets | `auth.secrets_file` (default `<data.dir>/secrets/server_secrets.json`) | Created with mode 0600. Keep it out of images and version control (`data/secrets/` is git-ignored); share or mount it across workers. |
| MRTR state secret | `mcp.mrtr.state_secret` | Optional; it derives from the session secret. |
| OAuth signing key | the file at `mcp.auth.builtin.signing_key_path`, by default `<data.dir>/oauth/signing_key.pem` | It is generated on first use with mode 0600. Keep it out of version control, and share or mount the same file across workers. |
| Pre-registered client secrets | `mcp.auth.builtin.clients[].client_secret` | Use `${ENV_VAR}` placeholders, or set `SAJHA_MCP_AUTH_BUILTIN_CLIENTS`. |
| Database password | `db.password` / `db.url` | Set `SAJHA_DB_PASSWORD` or `SAJHA_DB_URL`. |
| Provider and data-API keys | `ai.*.api_key`, `fmp`, `fred`, `google`, `tavily` | Set the env var named in the YAML placeholder. |

See also the [Security Model](../security/Security%20Model.md) and the
[Architecture](../architecture/Architecture.md) overview.

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
