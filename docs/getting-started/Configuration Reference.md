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

The code reads configuration in the ways below, and each one resolves overrides differently.
The **Reader** column in the tables below says which one applies to each key.

| Reader | Used for | Resolution (highest wins) |
|--------|----------|---------------------------|
| **Settings**: `get_settings()` in `sajha/core/config.py` | app, server, db, auth (secrets, JWT), config, hot_reload, logging, data, cache, async, shell | 1. env var named after the Settings field, `SAJHA_<FIELD_NAME>` (pydantic-settings, `env_prefix='SAJHA_'`) → 2. `SAJHA_` + the dotted key in upper case with dots changed to underscores → 3. YAML (after `${VAR}` substitution) → 4. built-in default. It is evaluated once per process (`lru_cache`). |
| **Live `_get`**: `_get` / `_bool` / `_int` / `_list` in `sajha/core/config.py`, called on each use | all `mcp.*` keys, `state.*`, `auth.login.*`, `auth.password.min_length`, `auth.secrets_file`, `async.delivery.webhook.allowed_urls`, `playground.*`, `sandbox.*`, `workflows.*`, `quality.*` | 1. `SAJHA_<DOTTED_KEY>` (for example `SAJHA_MCP_AUTH_MODE`) → 2. YAML → 3. code default. Env vars are read on every call, but the YAML is a snapshot taken at import, so a YAML edit needs a restart. |
| **Raw YAML / PropertiesConfigurator**: `sajha.core.config._CFG` and `sajha/core/properties_configurator.py` | `ai.tool_search.*`, `ai.embedding_model`, `${key}` references inside tool JSON configs (`storage.*` is read this way too, but with env overrides first: see [storage](#storage)) | YAML only (after `${VAR}` substitution); `SAJHA_` env overrides **do not apply**. To override one of these keys, edit the YAML, or put a `${VAR:default}` placeholder in the value and set `VAR`. |
| **AI settings**: `sajha/ai/llm/settings.py` | the rest of `ai.*` (providers, aliases, policy, budgets, cache, retry, breaker, gateway, ask) | 1. `SAJHA_AI_<SECTION>_<FIELD>` → 2. the vendor's own variable (providers only) → 3. YAML → 4. the `llm_providers` / `llm_models` tables (providers only) → 5. default. See [ai](#ai). |

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
| `app.version` | the YAML value / a code fallback in `sajha/core/config.py` | `SAJHA_APP_VERSION` | **The version authority.** It is shown in the UI and API metadata. The code fallback is a copy that can rot; keep the key in YAML. |
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
| `db.type` | `sqlite` | `SAJHA_DB_TYPE` | `sqlite` or `postgresql`. It also selects the schema file `db/scripts/<type>/schema.sql`. SQLite runs it at start-up; on PostgreSQL SAJHA never runs DDL and an operator runs it (see [Database Setup](Database%20Setup.md)). |
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
| `db.scripts_dir` | `db/scripts` | `SAJHA_DB_SCRIPTS_DIR` | Root of the schema files (`<scripts_dir>/<dialect>/schema.sql` and `seed.sql`, dialect `sqlite` or `postgresql`). A relative path is tried from the working directory, then from the checkout. |
| `db.schema_check` | `strict` | `SAJHA_DB_SCHEMA_CHECK` | `strict`: refuse to start while a table or column the code uses is missing, naming them and the `psql` command. `warn`: log that and start. Any other value stops start-up. Checked on PostgreSQL, and on SQLite after its schema file has run. [Database Setup](Database%20Setup.md) |

## state

Reader: live `_get`, in `sajha/core/state/__init__.py`, read once when the process builds its
state store. Where OAuth codes, MCP sessions and tasks, rate-limit windows, LLM budgets and
change notifications live. The design, and the inventory of what is shared and what stays
per process, is in [Scaling and State](../architecture/Scaling%20and%20State.md).

| Key | Default | Env | Purpose |
|-----|---------|-----|---------|
| `state.backend` | `memory` | `SAJHA_STATE_BACKEND` | `memory` (this process only), `redis` or `database`. Any other value stops start-up. With more than one worker, use `redis` or `database`; start-up logs a warning when it detects several workers (`WEB_CONCURRENCY`, `UVICORN_WORKERS`, `SAJHA_WORKERS` or `--workers`) on `memory`. A shared backend that does not answer at start-up stops start-up. |
| `state.key_prefix` | `sajha:` | `SAJHA_STATE_KEY_PREFIX` | Prefix of every key and pub/sub channel, so several deployments can share one Redis or database. |
| `state.redis.url` | `redis://localhost:6379/0` | `SAJHA_STATE_REDIS_URL` | Redis URL (`redis://`, `rediss://` for TLS, with `user:password@` when needed). Put a password in the env var, not in the YAML. Needs the optional `redis` package (`pip install "redis>=5"`). |
| `state.database.url` | `""` | `SAJHA_STATE_DATABASE_URL` | SQLAlchemy URL for the `database` backend and the durable task store. Empty uses SAJHA's own database (`db.*`). The tables `sajha_state` and `sajha_state_events` are in the schema file; SAJHA creates them on first use on SQLite only, and on PostgreSQL a missing table stops start-up ([Database Setup](Database%20Setup.md)). |
| `state.database.poll_interval_ms` | `500` (min 50) | `SAJHA_STATE_DATABASE_POLL_INTERVAL_MS` | How often the `database` backend polls for pub/sub events, which bounds how late a change notification reaches another worker. |
| `state.tasks.durable` | `auto` | `SAJHA_STATE_TASKS_DURABLE` | `auto`, `true` or `false`. Durable MCP task records are kept in the database (`state.database.url`, or SAJHA's own), so they survive a restart and every worker sees them. `auto` turns it on for the `redis` and `database` backends. |

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
| `auth.credential_storage` | `plain` | `SAJHA_AUTH_CREDENTIAL_STORAGE` | `plain` (passwords and API keys stored as given; owner decision for intranet use) or `hashed` (bcrypt / SHA-256). Run `python -m sajha.auth rehash` after switching to `hashed`. Security Model, "Credential storage and files". |
| `auth.credential_files.reload_check_seconds` | `300` (min 1) | `SAJHA_AUTH_CREDENTIAL_FILES_RELOAD_CHECK_SECONDS` | `config/users.json` and `config/apikeys.json` are held in memory by one object each; lookups never read the file. A hand edit is noticed at the next check, at most this many seconds later; changes made on the admin pages apply at once. |
| `auth.users_file.path` | `config/users.json` | `SAJHA_AUTH_USERS_FILE_PATH` | The administrators' users file; wins over the database (`sajha/auth/users_file.py`). |
| `auth.api_keys.db_dump_path` | `config/apikeys_db.json` | `SAJHA_AUTH_API_KEYS_DB_DUMP_PATH` | Where the database's keys are dumped (last fallback for key lookup). |
| `auth.api_keys.db_dump_interval_minutes` | `10` (min 1) | `SAJHA_AUTH_API_KEYS_DB_DUMP_INTERVAL_MINUTES` | How often the dump is written (one worker per interval). |
| `auth.login.max_failed_attempts` | `5` (min 1) | `SAJHA_AUTH_LOGIN_MAX_FAILED_ATTEMPTS` | Consecutive failed sign-ins that lock an account (`sajha/auth/__init__.py`, `AuthManager.sign_in`). |
| `auth.login.lockout_minutes` | `15` (min 1) | `SAJHA_AUTH_LOGIN_LOCKOUT_MINUTES` | How long a locked account stays locked. |
| `auth.login.ip_max_failures` | `20` (min 1) | `SAJHA_AUTH_LOGIN_IP_MAX_FAILURES` | Failed sign-ins per client IP within the window before 429 (`sajha/security.py`). |
| `auth.login.ip_window_seconds` | `300` (min 1) | `SAJHA_AUTH_LOGIN_IP_WINDOW_SECONDS` | The window for `ip_max_failures`. |
| `auth.password.min_length` | not in YAML / `8` (never below 8) | `SAJHA_AUTH_PASSWORD_MIN_LENGTH` | Minimum length of a new password (`sajha/auth/password.py`). |
| `auth.api_keys.max_per_user` | not in YAML / `25` (min 1) | `SAJHA_AUTH_API_KEYS_MAX_PER_USER` | API keys a user may hold besides their default key (live `_get`, `sajha/auth/apikeys.py`). |

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
| `tools.max_call_depth` | not in YAML / `8` (min 1) | How deep tools may call tools (a composite step, `sajha_ask`'s inner calls); a deeper call, or a tool already running in the chain, is refused ([Inner calls](../security/Security%20Model.md#inner-calls)). | `sajha/core/inner_calls.py` |
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
| `mcp.anonymous.prompts` | `[]` | Prompts anonymous callers may see and get (fnmatch patterns, comma-separated in `SAJHA_MCP_ANONYMOUS_PROMPTS`): `prompts/list`, `prompts/get`, prompt completion, the prompt catalog resource and `GET /api/prompts/*`. Signed-in callers see every prompt. The conformance fixture prompts are visible regardless. |
| `mcp.anonymous.resources` | `[]` | Data-file resources (`sajha://data/<file>`) anonymous callers may list and read: fnmatch patterns over the URI (`["sajha://data/products.csv"]`, `["sajha://data/*"]`), comma-separated in `SAJHA_MCP_ANONYMOUS_RESOURCES`. Applies to `resources/list` and `resources/read` on both eras; a hidden file is "Resource not found". Signed-in callers read every data file. The tool and prompt catalog resources follow `tools` / `prompts`; the conformance fixture resources are visible regardless. |

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
| `mcp.tasks.max_tasks` | `1000` (min 1) | Maximum number of task records held. When the limit is reached, the oldest finished ones are dropped first. With `state.backend: redis` and non-durable tasks it is a per-worker limit on the tasks that worker runs. | `sajha/core/mcp_tasks.py` |
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
| `mcp.auth.builtin.signing_key_pem` | not in YAML / `""` | The signing key as PEM text, usually from env `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`. A literal `\n` is read as a newline. When set, it replaces the file. This is how hosts that do not share a data directory sign with the same key (`sajha/auth/oauth/keys.py`). |
| `mcp.auth.builtin.cimd.enabled` | `true` | Accepts Client ID Metadata Document client IDs (https URLs). |
| `mcp.auth.builtin.cimd.allow_localhost` | `false` | Development only: accepts `http://localhost` client IDs. |
| `mcp.auth.builtin.cimd.allow_private_networks` | `false` | Allows fetching metadata documents from private addresses. |
| `mcp.auth.builtin.cimd.timeout_seconds` | `5` (1–30) | Timeout for fetching a metadata document. |
| `mcp.auth.builtin.cimd.max_bytes` | `16384` (1024–1048576) | Size limit for a metadata document. |
| `mcp.auth.builtin.dynamic_client_registration` | `false` | RFC 7591 registration. Registrations are kept in the state store (`state.backend`), so they are in memory with the default backend. |
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
| `config.apikeys.path` | `config/apikeys.json` | `SAJHA_CONFIG_APIKEYS_PATH` | The persistent API key file: hashed records of the keys an administrator marks persistent, read after the database and re-read when it changes; written atomically, mode 0600, git-ignored; format in `config/apikeys.json.example` (`sajha/auth/persistent_keys.py`; [API keys](../security/Security%20Model.md#api-keys)). The older plaintext format is not read. |
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
| `fred.api.key` | `${FRED_API_KEY:}` | `FRED_API_KEY` | `config/tools/fred_*.json`, and the Bank of Japan (`boj_*`) and People's Bank of China (`pboc_*`) configs |
| `fbi.api.key` | `${FBI_API_KEY:}` | `FBI_API_KEY` (the tool also falls back to `DATA_GOV_API_KEY`, then `DEMO_KEY`) | `config/tools/fbi_*.json` |
| `google.api.key` | `${GOOGLE_API_KEY:}` | `GOOGLE_API_KEY` | `config/tools/google_search.json` |
| `google.search.engine.id` | `${GOOGLE_SEARCH_ENGINE_ID:}` | `GOOGLE_SEARCH_ENGINE_ID` | `config/tools/google_search.json` |
| `tavily.api.key` | `${TAVILY_API_KEY:}` | `TAVILY_API_KEY` | `config/tools/tavily_*.json` |
| `alpha_vantage.api.key` | `${ALPHA_VANTAGE_API_KEY:}` | `ALPHA_VANTAGE_API_KEY` | `config/tools/av_*.json` |
| `sharepoint.site.url` | `${SHAREPOINT_SITE_URL:}` | `SHAREPOINT_SITE_URL` | `config/tools/sharepoint_*.json` (the site, e.g. `https://contoso.sharepoint.com/sites/team`) |
| `sharepoint.client.id` | `${SHAREPOINT_CLIENT_ID:}` | `SHAREPOINT_CLIENT_ID` | `config/tools/sharepoint_*.json` (the Entra ID app registration) |
| `sharepoint.client.secret` | `${SHAREPOINT_CLIENT_SECRET:}` | `SHAREPOINT_CLIENT_SECRET` | `config/tools/sharepoint_*.json` |
| `azure.tenant.id` | `${AZURE_TENANT_ID:}` | `AZURE_TENANT_ID` | `config/tools/sharepoint_*.json` (the app's tenant) |

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
| `models` | `[]` | Add or override models: `{id, kind, display_name, enabled, tools, structured_output, vision, streaming, temperature, forced_tool_choice, context_window, max_output_tokens, input_cost_per_mtok, output_cost_per_mtok, dimensions, tags, deployment}`, and the canonical-format features `json_mode`, `strict_tools`, `named_tool_choice`, `parallel_tool_control`, `seed`, `stop_sequences`, `reasoning_effort`, `native_n`, `variable_dimensions` (unset: the provider's default; meanings in [Extending the Intelligence Layer §3.2](../architecture/Extending%20the%20Intelligence%20Layer.md#32-capabilities-and-how-the-gateway-uses-them)). |

| Provider | Extra fields | Vendor variables honoured |
|---|---|---|
| `anthropic` | `api_version` (`2023-06-01`), `beta_headers`, `auth` (`api_key`/`bearer`), `structured_output_param`, `messages_path`, `extra_body`; Vertex AI: `platform` (`anthropic`/`vertex`), `vertex_project`, `vertex_location` (`global`), `credentials_file` (a Google service-account or authorized-user JSON; empty: workload identity through the metadata server) | `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`; `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `openai` | `organization`, `project`, `max_tokens_param`, `strict_schema` (default for requests that do not set `strict`), `stream_usage`, `parallel_tool_calls` (default for requests that do not set it), `tool_choice_required`, `seed_param` (`seed`), `chat_path`, `embeddings_path`, `extra_body` | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` |
| `azure_openai` | the `openai` fields plus `api_style` (`v1`/`deployments`), `api_version` (`2024-10-21`), `deployments` (model id → deployment), `auth` (`api_key`/`bearer`/`entra`); Entra ID (`auth: entra`): `entra_mode` (`auto`/`client_secret`/`workload_identity`/`managed_identity`; `auto` picks the first configured), `tenant_id`, `client_id`, `client_secret` (redacted), `federated_token_file`, `entra_scope` (`https://cognitiveservices.azure.com/.default`), `entra_authority` (`https://login.microsoftonline.com`) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION`; `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_FEDERATED_TOKEN_FILE` |
| `gemini` | `api_version` (`v1beta`), `schema_mode` (`json_schema`/`openapi`), `safety_settings`, `generation_config`, `embedding_task_type` (used when a request names no purpose); Vertex AI: `platform` (`ai_studio`/`vertex`), `vertex_project`, `vertex_location` (`global`), `vertex_api_version` (`v1`), `credentials_file` (as for `anthropic`) | `GEMINI_API_KEY`, `GOOGLE_API_KEY`; `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `bedrock` | `region`, `profile`, `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`, `embedding_input_type`, `guardrail_identifier`, `guardrail_version`, `additional_model_request_fields` | `AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` |
| `mistral` | the `openai` fields (`tool_choice_required: any`, `seed_param: random_seed`) | `MISTRAL_API_KEY` |
| `cohere` | `tool_result_format`, `embedding_input_type` (used when a request names no purpose), `chat_path`, `embed_path` | `COHERE_API_KEY`, `CO_API_KEY` |
| `ollama` | `keep_alive`, `num_ctx`, `think`, `options`, `detect_capabilities`, `live_models`, `health_ttl_s` | `OLLAMA_HOST`, `OLLAMA_BASE_URL` |
| `groq`, `together`, `fireworks`, `deepseek`, `xai`, `openrouter`, `perplexity`, `vllm`, `lmstudio`, `openai_compatible` | the `openai` fields plus `live_models`, `models_path` | `GROQ_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY`, `PERPLEXITY_API_KEY` |
| `mock` | `latency_ms` (`[0, 0]`), `fail_every` (`0`), `fail_with`, `retry_after_s`, `seed` (`42`), `scripts_dir` (`config/ai/mock_scripts`), `embed_dimensions` (`256`), `max_planner_tools` (`2`) | — |

### Gateway and ask sections

| Key | Default | Purpose |
|---|---|---|
| `ai.aliases.<name>` | `default`, `fast`, `reasoning` → `[mock/mock-planner]`; `embedding` → `[mock/mock-embed]`; `toolsmith` → `[mock/mock-toolsmith]` (set in `config/application.yml`, used by Studio's Describe a tool) | Ordered candidates: `provider/model` or a bare provider. Env: `SAJHA_AI_ALIASES_<NAME>`. |
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
| `ai.gateway.max_samples` | `8` | Largest `n` (choices per request) the gateway accepts. |
| `ai.ask.enabled` | `true` | Serve `POST /api/ai/ask`. |
| `ai.ask.model` | `default` | Alias or `provider/model` used by ask. |
| `ai.ask.max_steps` / `max_tool_calls` / `max_tokens` / `timeout_s` | `6` / `10` / `50000` / `60` | Limits of one ask. |
| `ai.ask.shortlist` | `12` | Tools offered to the model. |
| `ai.ask.max_result_chars` | `4000` | Cap on each tool result returned to the model. |
| `ai.ask.temperature` | `0` | Sampling temperature of ask calls. |
| `ai.ask.confirm_destructive` | `true` | Hold destructive tools for confirmation. |
| `ai.ask.synthesize` | `true` | Final structured-output call. |
| `ai.ask.audit` | `true` | Write an `ai_ask` audit entry per ask. |
| `ai.ask.mcp_tool_enabled` | `false` | Turns the `sajha_ask` MCP tool on (an LLM tool defined in `config/tools/sajha_ask.json`, which stays disabled there); applied at start-up and after every reload of the catalog. |
| `ai.ask.mcp_allowed_tools` | `[]` | fnmatch patterns that narrow what `sajha_ask` may run; its inner calls run as the MCP caller, so it never runs a tool the caller may not. Empty: the caller's access alone. Only where no caller was recorded (code calling the tool directly) are they added to the anonymous MCP policy. |
| `ai.ask.planner` | `react` | The Ask SAJHA page's planner, resolved by the planner registry ([Planner Reference](../architecture/Planner%20Reference.md) §2): a planner file in `ai.planners.dir` (the shipped ones are `react`, `plan_execute`, `rewoo`, `reflect`, `verify_then_answer`, `self_consistency`, `branch_and_judge`, `map_reduce`, `router`, `recipes`, `human_in_the_loop`, `auto`), `name@version`, a Python planner registered with `@register_planner`, or `package.module:Class` (`model` is an alias of `react`). Unknown names fail at startup. |
| `ai.ask.locality` | `any` | Where the tools offered to a planner may run: `any`, `local` (this server's own tools), or `net:<name>` (this server's tools and that SAJHA Net net's). An ask's `locality` and a planner's `settings.locality` take precedence. Local tools rank before remote ones whatever the setting ([SAJHA Net](../architecture/SAJHA%20Net.md) §13). Env `SAJHA_AI_ASK_LOCALITY`. |
| `ai.ask.planner_config.<planner>` | `{}` | Per planner: an overlay on a planner file's `settings` (only keys the file declares; anything else fails at startup), or a Python planner's settings validated by its `config_model`. The shipped files declare the same keys and defaults as the Python classes did. `plan_execute`: `max_replans` (`1`), `max_parallel` (`4`), `max_plan_steps` (`8`), `fallback` (`react`), `model` (alias of the planning call; `null` = the ask's). `recipes`: `recipes: [{name, tool, match (regex, named groups), keywords, arguments, answer}]`, `fallback` (`react`). `router`: `rules: [{match, planner}]`, `use_recipes` (`true`), `multi_step` (`plan_execute`), `default` (`react`), `multi_step_pattern`. The overlay applies wherever that planner runs, including as a sub-planner. Env: `SAJHA_AI_ASK_PLANNER_CONFIG` as JSON. |
| `ai.planners.dir` | `config/planners` | Planner files ([Planner Reference](../architecture/Planner%20Reference.md)), read with plain `yaml.safe_load` through the storage backend and reloaded on change; a file that fails validation keeps its last good version in use. Env `SAJHA_AI_PLANNERS_<FIELD>` (likewise for the keys below). |
| `ai.planners.default` | `react` | The planner of an LLM tool that names none (`llm.planner`). |
| `ai.planners.reload_interval_s` | `2` | How often a lookup checks the planner files for changes. |
| `ai.planners.python_builtins` | `false` | `true`: the names `react`, `plan_execute`, `recipes` and `router` run the Python classes in `sajha/ai/planners.py` instead of the shipped files (a rollback switch). |
| `ai.planners.resume_ttl_s` | `900` | How long a run paused at an `ask_user` stage (MRTR, 2026-07-28) is kept in the state store for the client's retry. |
| `ai.planners.dry_run_model` | `mock/mock-planner` | The model every call of a dry run (`POST /api/ai/planners/dry-run`, the planner editor's Dry run) and of the LLM tool creator's test run (`POST /admin/studio/llm/test`) goes to. |
| `ai.planners.max_input_chars` | `20000` | Text a `match` stage or the `matches()` function searches is clipped to this. |
| `ai.planners.menu_min_pass_rate` | `0.5` | Automatic selection (`classify` with `menu: planners`): a candidate whose latest recorded eval run, on an eval set for the tool, passed fewer questions than this is left off the menu. |
| `ai.planners.limits.max_stages_run` | `40` | Ceiling of a run's stage executions, sub-runs included (`stopped_by: stage_limit`). The `ai.planners.limits` values are ceilings a planner file may lower, never raise (a higher value is clamped with lint warning P060). Env `SAJHA_AI_PLANNERS_LIMITS_<FIELD>`. |
| `ai.planners.limits.max_visits_per_edge` | `10` | Ceiling of every integer `max_visits` (clamped at load, P023). |
| `ai.planners.limits.max_subplanner_depth` | `2` | Nesting of `planner` stages, `sample` of a planner and `foreach` (deeper is refused at load, P035). |
| `ai.planners.limits.max_parallel` / `max_samples` / `max_foreach_items` | `4` / `5` / `50` | Ceilings of `execute.max_parallel`, `sample.concurrency` and `foreach.concurrency`; `sample.n`; `foreach.max_items` (further items are dropped and the outcome is `partial`). |
| `ai.memory.enabled` | `true` | Conversation memory for asks that send a `conversation_id` (`sajha/ai/memory.py`). |
| `ai.memory.history_turns` | `6` | Most recent turns sent to the planner verbatim. |
| `ai.memory.max_turn_chars` | `2000` | Each stored question and answer is clipped to this. |
| `ai.memory.summarize` / `summary_max_chars` | `true` / `2000` | Summarise turns older than the verbatim window through the gateway, and the summary's length cap. |
| `ai.memory.condense` | `true` | Rewrite a follow-up into a standalone question before the shortlist. |
| `ai.memory.model` | `fast` | Alias of the summary and rewrite calls. |
| `ai.memory.retention_days` | `30` | Conversations idle longer are deleted by the purge. `0` keeps them. Also the ceiling of an LLM tool's `memory.ttl_minutes`. |
| `ai.memory.max_conversations_per_user` | `200` | A user's oldest conversations beyond this are deleted. `0` = no cap. |
| `ai.llm_tools.enabled` | `true` | The LLM-tool type ([LLM Tools](../architecture/LLM%20Tools.md)); each LLM tool still has its own `enabled`. Every `ai.llm_tools` value is a ceiling a tool's `llm` block may only lower. Env `SAJHA_AI_LLM_TOOLS_<FIELD>`; nested sections `SAJHA_AI_LLM_TOOLS_<SECTION>_<FIELD>` (for example `SAJHA_AI_LLM_TOOLS_RUNTIME_MAX_CONCURRENT_RUNS`). |
| `ai.llm_tools.default_model` | `default` | Alias of an LLM tool that names no `model`. |
| `ai.llm_tools.max_depth` | `2` | LLM tools nested in one call chain (a tool calls another only with `nesting.allow`). |
| `ai.llm_tools.limits.max_steps` / `max_tool_calls` / `timeout_s` | `8` / `16` / `120` | Ceilings of one run's planner steps, inner tool calls and wall time. |
| `ai.llm_tools.limits.max_input_chars` / `max_output_tokens` / `max_cost_usd` | `20000` / `4000` / `1.00` | Ceilings of the rendered input, each model call's output tokens and one run's model cost (nested runs spend from the outer run's remainder). |
| `ai.llm_tools.anonymous.enabled` | `false` | May anonymous callers run LLM tools at all. When on, `max_steps` (`3`) and `max_cost_usd` (`0.02`) cap their runs, and they never get stored memory. |
| `ai.llm_tools.memory.working_set_max_kb` | `2048` | Bytes of tool results one running call keeps in memory; past it the oldest results spill to the spool. |
| `ai.llm_tools.memory.spill_threshold_kb` | `256` | A tool result larger than this is written to the spool at once; the run keeps a preview of `ai.ask.max_result_chars` characters. |
| `ai.llm_tools.memory.cache.enabled` / `max_mb` / `ttl_s` | `false` / `64` / `300` | Optional write-through hot cache of conversation rows and turn windows, bounded by measured bytes; emptied under memory pressure. |
| `ai.llm_tools.memory.spool.dir` | `data/spool/llm_tools` | Per-run folders for spilled payloads (local disk), deleted when the run ends. |
| `ai.llm_tools.memory.spool.max_mb` / `per_run_mb` | `1024` / `128` | Caps of the spool in total (this process) and per run; past a cap a payload is truncated with a marker and the `llm_tools.spool_full` notice is raised. |
| `ai.llm_tools.memory.spool.orphan_minutes` | `60` | The janitor (at start-up and every minute while runs happen) deletes run folders older than this that no live run owns. |
| `ai.llm_tools.runtime.max_concurrent_runs` / `max_queued` / `queue_timeout_s` | `8` / `32` / `30` | Runs executing at once per process, runs waiting, and how long one waits before `stopped_by: busy`. |
| `ai.llm_tools.runtime.retry_after_s` | `5` | The `Retry-After` of a REST 503 for a busy run. |
| `ai.llm_tools.runtime.memory_guard.soft_pct` / `hard_pct` | `70` / `85` | Soft and hard limits as percentages of the cgroup memory limit (else physical memory). Soft: caches emptied, working sets spilled, queued runs wait. Hard: new runs refused (`busy`), running ones end at their next step (`memory_pressure`). |
| `ai.llm_tools.runtime.memory_guard.soft_mb` / `hard_mb` | `0` / `0` | Absolute limits in MB instead of the percentages (both must be set). |
| `ai.llm_tools.runtime.memory_guard.interval_s` / `enabled` | `2` / `true` | How often the guard samples resident memory, and whether it runs. |
| `ai.llm_tools.result_cache.max_entries` / `ttl_s` | `1000` / `3600` | Results of `complete`, `extract`, `classify` and `judge` tools that set `cache: true`, keyed by tool, version, model, caller and arguments. |
| `ai.llm_tools.memory.max_turns` | `50` | Ceiling of an LLM tool conversation's stored turns; older turns are folded into the summary and their rows deleted. Env `SAJHA_AI_LLM_TOOLS_MEMORY_MAX_TURNS` (likewise for the keys below). |
| `ai.llm_tools.memory.max_conversations_per_tool` | `50` | A user's oldest conversations of one LLM tool beyond this are deleted. `0` = no cap. |
| `ai.llm_tools.memory.purge_interval_minutes` | `15` | The purge of expired and over-cap conversations runs this often, on one worker (a slot claimed in the state store). `0`: no schedule; at most hourly when a turn is written. |
| `ai.llm_tools.memory.sqlite_vacuum` | `false` | `VACUUM` the SQLite file after a purge that deleted rows. |
| `ai.openai_api.enabled` | `false` | Serve SAJHA as an OpenAI-compatible endpoint: `POST /v1/chat/completions`, `GET /v1/models`, `POST /v1/embeddings` ([LLM Tools](../architecture/LLM%20Tools.md#134-sajha-as-an-openai-compatible-endpoint) section 13.4; routes in the [API Reference](../protocol/API%20Reference.md#423-openai-compatible-endpoint-openai_routespy)). Off: every `/v1` route is 404. Env `SAJHA_AI_OPENAI_API_ENABLED` (likewise for the keys below). |
| `ai.openai_api.llm_tools` | `true` | List each enabled LLM tool the caller may execute as the model `sajha:<tool>`, and run it when a completion names it. |
| `ai.openai_api.cookie_auth` | `false` | Also accept the web console's session cookie on `/v1` (otherwise an API key or a JWT as the bearer only). |
| `ai.openai_api.max_body_bytes` | `4000000` | Larger `/v1` request bodies are refused with 413. |
| `ai.rag.enabled` | `true` | Build the document index behind `sajha_search_docs` and *Ask the docs* (`sajha/ai/rag/`). |
| `ai.rag.index_sajha_docs` | `true` | Index SAJHA's own guides (`docs/`, archive and READMEs excluded). |
| `ai.rag.sources` | `[]` | Admin document sources: `[{name, path, pattern, title}]`; `path` is a folder in the storage backend, `pattern` a glob (default `*.md`). Files: `.md`, `.markdown`, `.txt`, `.rst`, `.html`, `.htm`; `.pdf` with the optional package `pypdf` and `.docx` with `python-docx` (without it such files are skipped and the build names the package). Env: JSON. |
| `ai.rag.uploads_dir` | `data/rag/uploads` | Where uploaded documents are kept (storage backend). |
| `ai.rag.embedding_model` | `embedding` | Gateway alias for passage embeddings; `none` = BM25 only. |
| `ai.rag.store` | `auto` | Where the passages live ([Intelligence Layer](../architecture/Intelligence%20Layer.md#stores)): `auto` (`sqlite_vec` when the sqlite-vec extension loads, else `memory`, with the System Notice `rag.store_fallback` saying why), `sqlite_vec`, `memory`, `pgvector`, a store registered through the `sajha.rag.stores` entry-point group, or `package.module:Class`. A store that cannot run falls back to `memory` with the same notice. |
| `ai.rag.stores` | `{}` | Per-store settings, `{<store>: {<key>: value}}`, over each store's defaults. Env: the whole map as JSON in `SAJHA_AI_RAG_STORES`, or one key at a time as `SAJHA_AI_RAG_STORES_<STORE>_<KEY>` (which wins). |
| `ai.rag.stores.sqlite_vec.path` | `data/rag/vectors.db` | The sqlite_vec store's own SQLite file (never SAJHA's database; a local file whatever the storage backend). Needs the `sqlite-vec` package and a Python whose `sqlite3` can load extensions. |
| `ai.rag.stores.pgvector.dsn` | `""` | SQLAlchemy URL of the PostgreSQL database holding `rag_chunks`; empty uses SAJHA's database. Set it in the environment (`SAJHA_AI_RAG_STORES_PGVECTOR_DSN`), not in the file. |
| `ai.rag.stores.pgvector.batch_size` / `text_search_config` | `256` / `english` | Rows per insert; the PostgreSQL text-search configuration for keyword search. |
| `ai.rag.persist` / `index_path` | `true` / `data/rag/index.json` | Keep the index across restarts, so a restart re-embeds only changed documents. `index_path` is the memory store's file in the storage backend. With `false` the memory store is not saved and sqlite_vec uses a temporary file. |
| `ai.rag.embed_batch_size` | `64` | Passages per embedding call while indexing; each document's passages stream to the store batch by batch. |
| `ai.rag.chunk_chars` / `chunk_overlap` | `1200` / `150` | Passage size and overlap, in characters. |
| `ai.rag.top_k` | `5` | Passages returned when a search gives no `top_k`. |
| `ai.rag.vector_weight` | `0.5` | Weight of the vector ranking in the fusion with BM25 (whose weight is 1). |
| `ai.rag.max_upload_bytes` | `2000000` | Largest upload accepted. |
| `ai.rag.build_on_start` | `true` | Build the index in a background thread at startup; otherwise on the first search. |

### Tool search

Reader: the flattened config (`_CFG`), in `sajha/app.py` and `sajha/ai/embedders.py`.

| Key | Default | Env | Purpose / reader |
|-----|---------|-----|------------------|
| `ai.tool_search.enabled` | `true` | — | Builds the tool-search index (`sajha/app.py`). |
| `ai.tool_search.embedder` | `bm25` | `AI_TOOL_SEARCH_EMBEDDER` | `bm25` (lexical) or `gateway` (embeddings through the `embedding` alias) (`embedders.py`). |
| `ai.tool_search.persist` | `true` | — | Persists the vector index (`sajha/app.py`). |
| `ai.tool_search.top_k` | `5` | — | **Not used.** `top_k` is a parameter of each call. |
| `ai.embedding_model` | not in YAML / `""` | — | A label recorded in the `gateway` embedder's name (which keys the persisted index); the vectors always come from the gateway's `embedding` alias (`embedders.py`). |

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
| `cache.per_user_federated` | `true` | `SAJHA_CACHE_PER_USER_FEDERATED` | Read live (`_bool`) on each cached call. Federated tools without their own `cache_per_user` keep a cached result per caller. |

A tool's JSON config may also set `"cache_per_user": true` (or `false`): the caller's user id
becomes part of the cache key, so one user's cached result is never served to another (all
anonymous callers share one key). Tools bound to a connected account are never cached.
Design: [Scaling and State](../architecture/Scaling%20and%20State.md#48-per-user-cache-keys).

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
| `shell.scratch_dir` | `data/shell_scratch` | Created at start-up; executions now run in a per-call sandbox work dir (see [sandbox](#sandbox)). |
| `shell.python.enabled` | `true` | Python, once the shell is enabled. |
| `shell.python.timeout_seconds` | `30` | Python timeout. |
| `shell.python.memory_limit_mb` | `256` | Memory limit of the sandbox Python runs in (`RLIMIT_AS`, or the container limit). |
| `shell.bash.enabled` | `false` | Bash needs this as well as `shell.enabled`. |
| `shell.bash.timeout_seconds` | `15` | Bash timeout. |
| `shell.bash.max_output_bytes` | `1048576` | Bash output cap. |

Both run through the [sandbox](#sandbox) backend after their filters.

## sandbox

Reader: live `_get` (`sajha/sandbox/settings.py::load_settings`), on every call, so
`SAJHA_SANDBOX_*` environment variables override the YAML (for example
`SAJHA_SANDBOX_DEFAULT_BACKEND=bwrap`, `SAJHA_SANDBOX_DEFAULTS_MEMORY_MB=256`). Lists
are YAML lists, or comma-separated in an environment variable. The design, the threat
model and what each backend guarantees are in [Sandbox](../architecture/Sandbox.md); a
tool's own `sandbox` block is described there too.

| Key | Default | Purpose |
|-----|---------|---------|
| `sandbox.default_backend` | `subprocess` | `subprocess`, `bwrap`, `nsjail`, `docker`, or `auto` (the first available of bwrap, nsjail, subprocess). An unavailable backend falls back to `subprocess` with a warning. |
| `sandbox.enforce_for_generated_tools` | `true` | Studio Python code and script tools always run in the sandbox. `false`: they load in-process unless their config says `"sandbox": {"enabled": true}`, and only an administrator may deploy them (a developer with Studio access gets 403). |
| `sandbox.strict` | `false` | `true`: refuse to run when the chosen backend, or a confinement step the runner tries (namespaces, Landlock, seccomp), is unavailable, instead of falling back. |
| `sandbox.work_dir` | `''` | Parent of the per-call temp directories (`''` = the system temp directory). |
| `sandbox.python` | `''` | Interpreter for the subprocess, bwrap and nsjail backends (`''` = the server's own). |
| `sandbox.extra_read_paths` | `[]` | Extra read-only paths a sandbox may read (for example a shared data directory). |
| `sandbox.secrets_allowlist` | `[]` | Environment variable names a tool may request with `sandbox.secrets`. `SAJHA_*` names are always refused. |
| `sandbox.defaults.timeout_seconds` | `30` | Wall-clock limit per call. |
| `sandbox.defaults.cpu_seconds` | `30` | CPU time (`RLIMIT_CPU`); a tool that sets only `timeout_seconds` gets the same value. |
| `sandbox.defaults.memory_mb` | `512` | Address-space limit, or the container memory limit. |
| `sandbox.defaults.max_output_bytes` | `1048576` | Per stream; the run is killed when it is exceeded. |
| `sandbox.defaults.max_processes` | `64` | Processes in the sandbox (`RLIMIT_NPROC` in its user namespace, `--pids-limit` for docker). |
| `sandbox.defaults.max_file_mb` | `64` | Largest file the code may write (`RLIMIT_FSIZE`). |
| `sandbox.defaults.network` | `none` | `none` or `allowlist` (a tool must then list `allow_hosts`). |
| `sandbox.max.*` | `timeout_seconds` 300, `cpu_seconds` 300, `memory_mb` 4096, `max_output_bytes` 16777216, `max_processes` 512, `max_file_mb` 1024 | Caps on what a tool's `sandbox` block may ask for. |
| `sandbox.docker.binary` | `docker` | `podman` works too. |
| `sandbox.docker.image` | `python:3.13-slim` | Image each call runs in; it must be pulled already (the backend reports unavailable otherwise). |
| `sandbox.docker.runtime` | `''` | Container runtime, for example `runsc` for gVisor. |
| `sandbox.docker.cpus` | `1` | `--cpus` per container. |

## playground

Reader: live `_get` (`sajha/web/playground.py`, `load_settings()`), on every request to the
playground's routes, so `SAJHA_PLAYGROUND_*` environment variables override the YAML. A
value that does not validate falls back to its default; the error is logged and shown to
administrators on `/playground`. The guide is [Python Playground](Python%20Playground.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `playground.enabled` | `true` | `false`: `/playground` and its worker answer 404 (a friendly page), and the menu entry, dashboard action and Studio's "Open in playground" button disappear. |
| `playground.assets` | `vendored` | Where the browser loads Pyodide from. `vendored`: `/static/vendor/pyodide/<version>/`, filled by `python scripts/fetch_pyodide.py`; without those files the page shows an administrator hint. `cdn`: `https://cdn.jsdelivr.net/pyodide/v<version>/full/`, and that origin is added to the playground worker's CSP only. |
| `playground.pyodide_version` | `314.0.7` | The Pyodide release (`N.N.N`; a leading `v` is accepted). With `vendored`, the folder `scripts/fetch_pyodide.py` fills; with `cdn`, the CDN path. |
| `playground.allow_pypi` | `true` | Let `micropip` fetch pure-Python wheels from PyPI: adds `https://pypi.org` and `https://files.pythonhosted.org` to the playground worker's `connect-src`. `false` keeps the worker to this origin (and the CDN in `cdn` mode). |

## federation

Reader: live `_get` for the scalar keys (`sajha/federation/config.py`,
`FederationSettings.load()`), read once when the manager starts, so `SAJHA_FEDERATION_*`
environment variables override the YAML; restart to apply a change. The upstream list is
read from the YAML as nested data, or from `SAJHA_FEDERATION_UPSTREAMS` (a JSON list), which
replaces it. Upstreams added on `/admin/federation` are stored at `federation.state_path`,
not in this file. Design, the upstream fields and operation:
[Federation](../architecture/Federation.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `federation.enabled` | `false` | Master switch. Off: no upstream is contacted and no federated item is exposed. |
| `federation.require_approval` | `true` | A newly discovered (or changed) upstream tool, prompt or resource waits for an administrator before it is exposed. An upstream's own `auto_approve: true` overrides it; text that trips the injection screen always waits. |
| `federation.allow_stdio` | `false` | Allow `transport: stdio` upstreams, which run as subprocesses of SAJHA with its privileges. |
| `federation.allow_localhost` | `false` | SSRF guard: allow loopback upstream URLs (for a localhost host name). |
| `federation.allow_private_networks` | `false` | SSRF guard: allow RFC 1918 and unique-local addresses (never link-local). |
| `federation.allowed_hosts` | `[]` | fnmatch host patterns an upstream URL must match; empty allows any host the guard allows. |
| `federation.refresh_interval_seconds` | `300` | Periodic re-discovery and health check; `0` refreshes only on list changes and on demand. Per upstream: `refresh_interval_seconds`. |
| `federation.startup_wait_seconds` | `5` | How long start-up waits for the first discovery of every enabled upstream. Start-up never fails because an upstream is down. |
| `federation.default_timeout_seconds` | `30` | One upstream call's deadline. Per upstream: `timeout_seconds`. |
| `federation.max_description_chars` | `1024` | Cap on an upstream tool's, prompt's or resource's description. |
| `federation.state_path` | `config/federation/federation.json` | Storage-backend path of the store: upstreams added on the admin page, and every item's approval. |
| `federation.upstreams` | `[]` | The upstreams defined in configuration; each entry's fields are in [Federation](../architecture/Federation.md#2-the-upstream-model). |

## SAJHA Net

Reader: live `_get` for the scalar keys, so `SAJHA_SAJHANET_*` environment variables
override the YAML; `sajhanet.nets` is read from the YAML as nested data, or from
`SAJHA_SAJHANET_NETS` (a JSON list), which replaces it. SAJHA Net is being built; the keys
below are the ones the code reads today (membership, names, the CA, signed requests, identity, the
key directory, users across instances, rules and blocks). The
whole design, with every planned key, is
[SAJHA Net](../architecture/SAJHA%20Net.md#19-configuration). On Kubernetes the chart's
`sajhanet` values write these keys
([Kubernetes Deployment](Kubernetes%20Deployment.md#sajha-net)).

| Key | Default | Purpose |
|-----|---------|---------|
| `sajhanet.enabled` | `false` | Master switch, read at start-up. On: the configured nets are joined, `/sajhanet/` serves the protocol (off: a bare 404), and the `io.sajha/net` extension is advertised on both MCP eras (`capabilities.extensions` in `server/discover`, `capabilities.experimental` in `initialize`; [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md)). |
| `sajhanet.ca_auto_init` | `true` | `SAJHA_SAJHANET_CA_AUTO_INIT` | Default for every net's `ca.auto_init` (owner decision): a net of one creates its CA at first start, so peers can enroll without `sajha net ca init`. |
| `sajhanet.test_admin_key.enabled` | `true` (for now) | `SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED` | Honour `"test_admin": true` records in `config/apikeys.json` and `config/users.json` (administrator), and carry the test admin key on SAJHA Net calls. Development and testing only; critical notice while active. |
| `sajhanet.peer_keys` | sample entry | `SAJHA_SAJHANET_PEER_KEYS` (JSON) | Keys this server uses toward particular members: `"<net>/<instance>"` or `"<instance>"` → key (or `${ENV}`); local only, never shared. |
| `sajhanet.nets` | `[]` | The nets this server is in, in order of preference; an entry without `name` is the net `default` (an info notice suggests naming it). The fields of an entry are in the table below. |
| `sajhanet.allowed_networks` | `[]` | CIDRs (`10.20.0.0/16`, `fd00:1::/32`) a SAJHA Net peer's URL may resolve into. Public addresses are always allowed; private, carrier-grade NAT and unique-local addresses only inside a listed network; loopback, link-local, unspecified and multicast never, whatever the list says. Separate from `federation.allow_private_networks`. A CIDR that does not parse is skipped with a warning. |
| `sajhanet.base_url` | `""` | The base URL peers reach this server on (its member record's `url`; the host must be in its certificate). Required with a configured `instance_name`; with an address name it defaults to `https://<ip>:<port>`. A net entry may set its own. |
| `sajhanet.region` | `""` | Region shown in the member record; a net entry may override it. `sajhanet.labels` (a map, YAML only) likewise. |
| `sajhanet.signature_max_age_seconds` | `30` | A signed request or response older than this is refused, and the replay window of seen nonces (state store); at most 300. |
| `sajhanet.require_https` | `true` | `false` only for a lab: enrollment and peer URLs may then be plain HTTP, and a warning notice stays up while it is off. |
| `sajhanet.min_protocol_version` | `1` | The lowest SAJHA Net protocol version accepted from a peer. |
| `sajhanet.data_dir` | `data/sajhanet` | Default home of each net's files: `<net>/instance.key`, `instance.crt`, `ca.pem`, `revoked.json`, `ca.key` (CA instance), `peers.json`; and, in the storage backend under the same path, the CA's `ca-state.json` (tokens as hashes, issued certificates, the signed revocation list), `runtime_seeds.json` and `pins.json`. Git-ignored. |
| `sajhanet.max_injections_per_minute` | `6` | Peers an administrator may add by address per net and minute (429 beyond). |
| `sajhanet.agent_lease_seconds` | `15` | TTL of the state-store lease `sajhanet:agent:<net>`: one worker per instance runs each net's gossip agent and renews it; when it dies another takes over within one TTL. Several workers need `state.backend: redis` or `database`. |
| `sajhanet.plugins.membership` | `gossip` | `gossip` (SWIM) or `static` (the net entry's `static_peers`, synced every full-sync interval), or `package.module:Class`; third parties register in the entry-point group `sajha.net.plugins`. |
| `sajhanet.plugins.admission` | `builtin_ca` (shipped config: `open`) | `open` (no CA, owner decision for now: each server makes a self-signed certificate; a peer is accepted the first time its name is seen and then held to that key, so another server claiming the name is refused with `name_conflict`; the remembered keys are on disk, listed and forgotten with `/api/sajhanet/nets/{net}/first-use`), `builtin_ca` (the net's CA, run by SAJHA; switch to it when needed) or `manual` (self-signed certificates whose thumbprints each administrator pins: the net entry's `identity.pins` plus pins added with `sajha net pin`). |
| `sajhanet.plugins.connector` | `sajha_native` | How requests reach peers: signed HTTP on their normal port. |
| `sajhanet.peer_cache.interval_minutes` | `10` | The saved peer list is written on every membership change and at least this often. |
| `sajhanet.peer_cache.max_age_days` | `7` | On restart, saved peers not seen for longer than this are skipped. |
| `sajhanet.gossip.gossip_interval_ms` | `1000` | One protocol period: one member pinged. |
| `sajhanet.gossip.ping_timeout_ms` | `500` | Wait for an ack before asking others to probe. |
| `sajhanet.gossip.indirect_probes` | `3` | Members asked to ping a silent member (`ping-req`). |
| `sajhanet.gossip.suspect_timeout_seconds` | `10` | A suspect that does not refute within this becomes dead. |
| `sajhanet.gossip.full_sync_interval_seconds` | `30` | Anti-entropy: a full membership exchange with one random member. |
| `sajhanet.gossip.dead_retention_minutes` | `60` | Dead and left members are kept (and dead ones probed) this long, then dropped. |
| `sajhanet.gossip.dead_probe_interval_seconds` | `30` | How often a dead member's last address is probed, so a restarted server is found. |
| `sajhanet.user_identity` | `api_key` | How users travel with a forwarded call: `api_key` (the user's own API key, verified by the host against the net key directory; per-member keys and the test admin key are features of this resolver), `assertion` (a user assertion signed by the home with its net certificate; only a key id crosses), `token_exchange` (the home trades an assertion at the host's `/sajhanet/v1/token` for a host-scoped token, cached until shortly before it expires), `none` (service identity only), or `package.module:Class`. A list (comma separated, or YAML) names several: as a home this server sends the first that the host's member record also lists, as a host it accepts all of them; a call to a re-exported tool and a bridge's call always use `assertion`, and a host accepts an assertion on such a call whatever this says. A net entry's `user_identity` overrides it for its net. Advertised in the member record and the `io.sajha/net` extension. |
| `sajhanet.assertion.ttl_seconds` | `30` | Lifetime of the user assertions this server signs (1 to 60). |
| `sajhanet.token_exchange.ttl_seconds` | `300` | Lifetime of the tokens this server issues as a host under `token_exchange` (1 to 3600); kept hashed in the state store. |
| `sajhanet.plugins.key_directory_store` | `database` | Where synced key records live: `database` (the `sajhanet_api_keys` table, [Database Setup](Database%20Setup.md)), `memory`, or `package.module:Class`. |
| `sajhanet.key_directory.sync` | `true` | Pull other members' key records when their `digests.keys` passes the version held. Off: this server verifies only keys it already holds. |
| `sajhanet.key_directory.full_sync_interval_seconds` | `300` | Every this many seconds each member's key digest is compared with the records held, and a difference re-pulled from version 0 (minimum 5). |
| `sajhanet.users.match_by_name` | `true` | A remote user with no explicit link runs as the local account with the same login name (`users.user_id`), with that account's local roles. A net entry's `users` overrides each of these keys for its net. |
| `sajhanet.users.unknown` | `refuse` | A remote user with no local account: `refuse` ("you have no account here") or `map_roles` (a guest identity `alice@risk-eu` with the roles of the role map for the user's instance; with no mapped role, refused). |
| `sajhanet.users.remote_admin` | `admin` | A remote user with the `admin` role at their home: `admin` (calls tools as an administrator here), `user` (like any linked or matched user; a name match gives no `admin` role), `refuse`. Net settings are changed only by an administrator signed in to this server, whatever this says. |
| `sajhanet.users.exclude_names`, `sajhanet.users.no_name_match` | `[]` | Login names never matched by name, and instances whose users are never matched by name (more can be added at runtime on the SAJHA Net page). |
| `sajhanet.role_maps` | `{}` | `{instance: {remote role: [local roles]}}` used by `users.unknown: map_roles` (`*` for every instance); a net entry's `role_maps` adds to it, and maps set on the SAJHA Net page add to both. |
| `sajhanet.service_calls` | `false` | Accept forwarded calls that carry no user (service identity). |
| `sajhanet.anonymous_may_call_remote` | `false` | Let anonymous callers use remote tools (no key travels; most hosts refuse such calls). |
| `sajhanet.preferences` | `{}` | Per-tool resolution preferences, server-wide: `{tool: ["<net>/<instance>", "<net>", ...]}`. A call by plain name tries the local tool, then these entries in order (a bare net: its hosts by the routing strategy), then the nets in `sajhanet.nets` order. Entries naming a net, host or tool that is not there are skipped. Server-wide only. |
| `sajhanet.max_fallbacks` | `3` | Hosts tried after the first for a call by plain name, only after a failure that was certainly not executed, or one that may have been for read-only or idempotent non-destructive tools. `0` turns fallback off. Server-wide only. |
| `sajhanet.bare_aliases` | `on` | Plain names for remote tools: `on` (every remote tool whose name no local tool has), `preferences_only` (only names with a preference list), `off` (qualified names only). |
| `sajhanet.default_trust` | `auto` | Trust in peers' tools: `auto` (imported at once after screening), `review` (each tool waits for an administrator's approval; a changed one is held at its approved version), `pinned` (only tools an administrator listed). Per peer it is set on the SAJHA Net page or with the admin API (kept in `<data_dir>/<net>/trust.json`). |
| `sajhanet.refresh_interval_seconds` | `300` | A peer's catalog is pulled when its digest or incarnation changes and at least this often (minimum 5). |
| `sajhanet.default_timeout_seconds` | `30` | A forwarded call's timeout, and the shared deadline of all its fallback attempts. |
| `sajhanet.max_hops` | `1` | Forwarded calls are refused (`hop_limit`) past this many hops from their home (at most 8). |
| `sajhanet.max_call_chain` | `8` | One budget for a whole call chain across the net: hops plus tools running one inside another (planners' tools, LLM tools, composites) on every instance passed (at most 32). Over it, the home refuses before sending and the host on receipt (`-32016 chain_limit`), and a tool entered inside a forwarded call is refused. Server-wide only. |
| `sajhanet.allow_remote_llm_tools` | `true` | Export this server's LLM tools to the net like plain tools (they run here, on this server's models and budgets, and report their spend back); `false` keeps them home. Server-wide only. |
| `sajhanet.reexport` | `false` | Offer tools this server imported onward, into the net concerned (a net entry overrides it; it is the net offered into that decides). Within one net such a tool carries its `origin` and calls to it are relayed with the caller's assertion; from another net it is offered as this server's own (a bridge) and called as the local user the caller maps to. Advertised as the feature `reexport`. Every instance on the chain must accept the extra hop: raise `max_hops` (to 2 for one intermediary) on the intermediary and the origin. |
| `sajhanet.reexport_rules` | `[]` | YAML only. With `reexport` on, what goes onward: a list of `{tools, from_nets, from_instances, to_instances, for_roles}` (globs; `tools` is the host's tool name; omitted lists match everything except `tools`). Nothing is re-exported unless a rule names it; a rule with `to_instances: []` re-exports its tools to nobody. A tool is never offered back to its host or origin, never under the name of a local tool, and the caller's key tool access is a ceiling as for exports. |
| `sajhanet.plugins.routing` | `local_first` | Order of the hosts of one tool within a net: `local_first` (by instance name), `lowest_latency` (measured median first), `pinned` (only hosts named in the preferences), or `package.module:Class`. |
| `sajhanet.limits.max_tools_per_peer`, `limits.max_catalog_bytes`, `limits.max_description_chars` | `2000`, `5242880`, `1024` | Caps on what is imported from one peer; a peer that exceeds them is flagged (a warning notice) and the excess ignored. |
| `sajhanet.peer.breaker_threshold`, `peer.breaker_reset_seconds` | `5`, `30` | Per-peer circuit breaker at the home: after this many consecutive availability failures calls to the peer pause for this long (a call by plain name moves to the next host). |
| `sajhanet.peer.calls_per_minute`, `peer.inbound_calls_per_minute` | `600`, `600` | Per-peer rate limits: this home's calls to one peer, and forwarded calls accepted from one peer (`-32019 rate_limited` beyond). |
| `sajhanet.residency.enabled` | `true` | Residency checks on forwarded calls (residency rules on arguments at the home, on results at the host and on arrival, residency-aware shortlists). Residency rules are policy rules, so `policy.enabled: false` also turns them off. Server-wide only. |
| `sajhanet.residency.default_effect` | `allow` | `deny`: arguments or results that carry any data class cross to another instance only when a residency rule `allow`s it ([Policy and Audit](../architecture/Policy%20and%20Audit.md) 3.5). Read on every decision. |
| `sajhanet.data_classes.tools` | `{}` | YAML only. Classify tools without editing them: `{<tool name or glob>: {arguments: {<field path>: <class or list>}, results: {...}}}`; a path is dotted property names, `[]` for every array item (`rows.[].email`), `*` for the whole value. Adds to the tools' own `x-sajha-data-class` marks and `data_classes`; at a home it applies to remote tools by their host tool name or qualified name. Server-wide only. |
| `sajhanet.memory.remote_results` | `store` | What conversation memory keeps of an answer that used results from other instances: `store` (as written), `summary` (every figure replaced by `[remote figure]`) or `none` (a placeholder). Server-wide only. |
| `sajhanet.memory.by_class` | `{}` | YAML only. `{<data class or glob>: store\|summary\|none}`: the mode for answers that used remote results of that class; the strictest mode of the classes involved wins, `remote_results` for the rest. |

Fields of a `sajhanet.nets` entry (YAML or `SAJHA_SAJHANET_NETS`). An entry may also set `base_url`,
`region`, `labels`, `signature_max_age_seconds`, `require_https`, `min_protocol_version`, `gossip`
(key by key) and `peer_cache` for its own net; the other keys above are server-wide.

| Field | Default | Purpose |
|-------|---------|---------|
| `name` | `default` | The net name (lowercase letters, digits, `-`, `_`; starts with a letter; at most 16; never `__`; not ending in `_`). |
| `instance_name` | the address | This server's name in the net (`risk-eu`: lowercase letters, digits and single hyphens, 2 to 32). Unset: `advertise_address`, else the bind address, else the default-route interface, as `<ip>:<port>`; never unspecified, loopback, `localhost` or link-local, and with none acceptable the net is not joined and an error notice says why. |
| `advertise_address` | `""` | `ip:port` peers should use behind NAT or a container network. |
| `founder` | `false` | Start alone when every seed is down instead of retrying (the net's first server when it also lists seeds). A net with no seeds needs no `founder`: it is a net of one. |
| `seeds` | `[]` | Base URLs tried first to join. None: the net is a **net of one** (owner decision): this server is its founder and only member, joined at once with no error notice, no join retries and no gossip, and it grows into an ordinary net when a peer joins through it or is added by address, without a restart. Until it has a certificate an info notice says how to give it one (`sajha net ca init`, allowed on a net of one without `ca.enabled`, or enrollment). With seeds that are all down (and not `founder`) the net is not joined and an error notice says so; the other nets are unaffected. |
| `identity.cert_ref`, `identity.key_ref`, `identity.ca_ref`, `identity.revocation_list_ref` | `file:<data_dir>/<net>/instance.crt`, `instance.key`, `ca.pem`, `revoked.json` | This server's certificate and key in the net, the net's CA certificate, and the revocation list it starts with. `file:` references (written by enrollment and renewal; the key owner-only) or `env:NAME` to read only. |
| `identity.pins` | `[]` | Manual mode: thumbprints of approved peers' certificates. |
| `ca.enabled` | `false` | This server is the net's CA instance (one per net). On a net of one, a CA key already at `ca.key_ref` makes it the CA instance too. |
| `ca.key_ref`, `ca.cert_ref` | `file:<data_dir>/<net>/ca.key`, `ca.pem` | The CA key (owner-only, never leaves this server; back it up) and certificate, created by `sajha net ca init`, or at first start on a net of one (`ca.auto_init`). |
| `ca.auto_init` | `sajhanet.ca_auto_init` | A net of one (no seeds) with no CA key and no certificate creates its CA at first start: audited, with a warning notice to back up the key. |
| `ca.cert_validity_days` | `30` | Lifetime of issued certificates; participants renew when a third remains. |
| `ca.enrollment_token_minutes` | `30` | Lifetime of an enrollment token. |
| `ca.enrollments_per_minute` | `10` | Enrollment requests accepted per source address and minute (429 beyond). |
| `peer_cache.path` | `<data_dir>/<net>/peers.json` | The saved peer list (local disk, written atomically, owner-only). |
| `static_peers` | `[]` | With `plugins.membership: static`: the peers to sync with. |
| `export` | `[]` | What this server offers in the net: a list of `{tools, to_instances, for_roles, require_approval}`. `tools` and `to_instances` are globs; `for_roles` are the caller's local roles after mapping. Nothing is exported unless a rule allows it; a rule with `to_instances: []` never exports its tools, whatever other rules say. |
| `import` | `[]` | What this server's users may use from the net: a list of `{instances, tools, for_roles}` (`for_roles`: the local caller's roles). Nothing is imported unless a rule allows it; `instances: []` never imports the tools. |
| `users`, `role_maps`, `service_calls`, `anonymous_may_call_remote`, `user_identity` | shared defaults | Per-net overrides of the shared keys above. |
| `default_trust`, `max_hops`, `refresh_interval_seconds`, `reexport`, `reexport_rules` | shared defaults | Per-net overrides of the catalog and routing keys. |

Blocks, user links, runtime role maps and name-matching exceptions are not configuration: an
administrator sets them on the SAJHA Net page or through the admin API
([API Reference](../protocol/API%20Reference.md#424-sajha-net-sajhanet_routespy)); they are kept per net in the
storage backend (`<data_dir>/<net>/blocks.json`, `users.json`).

## api_import

Reader: live `_get` (`sajha/api_import/settings.py`), read on every use, so
`SAJHA_API_IMPORT_*` environment variables override the YAML without a restart. Credentials
are not configured here: each import stores secret references (`env:NAME`, `file:/path`,
`db:llm_providers/<type>`) in its tool configs. Design: [API Import](../architecture/API%20Import.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `api_import.allow_localhost` | `false` | SSRF guard: allow loopback spec, `$ref`, GraphQL, token and API URLs (for a localhost host name). |
| `api_import.allow_private_networks` | `false` | SSRF guard: allow RFC 1918 and unique-local addresses (never link-local, so never cloud metadata). |
| `api_import.allowed_hosts` | `[]` | fnmatch host patterns every URL must match; empty allows any host the guard allows. |
| `api_import.max_tools` | `200` | The most tools one imported API may have; the preview marks the excess and a deploy beyond it is refused. |
| `api_import.max_spec_bytes` | `10485760` | Largest spec or introspection result read (also the cap on each remote `$ref` document). |
| `api_import.max_ref_documents` | `20` | Remote documents one spec's `$ref`s may pull in. |
| `api_import.timeout_seconds` | `30` | One call's deadline (spec fetch, introspection, tool call); an import can set its own. |
| `api_import.max_response_bytes` | `5242880` | Largest API answer an imported tool reads. |
| `api_import.graphql_depth` | `2` | Depth of the selection sets generated for GraphQL tools (1 to 5); an import can set its own. |
| `api_import.records_dir` | `config/api_imports` | Storage-backend folder of the import records (one JSON document per imported API). |

## Data connectors

Reader: live `_get` (`sajha/connectors/settings.py`), read on every use, so
`SAJHA_CONNECTORS_*` environment variables override the YAML without a restart. Connections
themselves are not configured here: each is a record at `config/connectors/<id>.json` (written
by the Data Connectors page, `/admin/connectors`) holding only secret references (`env:NAME`,
`file:/path`, `db:llm_providers/<type>`). A connection's own `limits` default to the
`default_*` keys and are capped by the `max_*` ones. Design:
[Data Connectors](../architecture/Data%20Connectors.md); per-kind setup:
[Data Connectors Reference Guide](../tools/enterprise/Data%20Connectors%20Reference%20Guide.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `connectors.enabled` | `true` | Off: connections and their tools stay, and every call is refused with the reason. |
| `connectors.records_dir` | `config/connectors` | Storage-backend folder of the connection records. |
| `connectors.default_max_rows` | `500` | Rows a query or view returns when the connection sets none. |
| `connectors.max_rows_limit` | `10000` | The most rows any connection may allow. |
| `connectors.default_max_bytes` | `2097152` | JSON size of a result when the connection sets none; fetching stops there. |
| `connectors.max_bytes_limit` | `16777216` | The most bytes any connection may allow. |
| `connectors.default_timeout_seconds` | `30` | Statement time limit when the connection sets none. |
| `connectors.max_timeout_seconds` | `300` | The longest time limit any connection may set. |
| `connectors.sample_rows` | `3` | Sample rows `describe_table` shows (0 to 20); a caller can ask for fewer or more within that range. |
| `connectors.catalog_ttl_seconds` | `600` | How long a connection's catalog (tables, described columns) is cached per process; 0 re-reads every time. |
| `connectors.catalog_max_tables` | `2000` | The most tables a catalog lists. |
| `connectors.pool_size` | `4` | Idle connections kept per connection and process (never for per-user connections). |
| `connectors.pool_max_age_seconds` | `300` | An idle connection older than this is closed instead of reused. |
| `connectors.record_refresh_seconds` | `5` | How often a running tool checks its connection record for changes. |
| `connectors.require_sqlglot` | `false` | Refuse caller SQL when sqlglot is not installed, instead of using the conservative scanner. |
| `connectors.audit_sql` | `false` | Put the SQL text (up to 4000 characters) in `connector.query` audit records; otherwise only its SHA-256. |
| `connectors.sync_on_startup` | `true` | Regenerate every connection's tools at start-up (no database is opened). |

## Studio: Describe a tool

Reader: live `_get` (`sajha/studio/describe.py`), read on every use, so
`SAJHA_STUDIO_DESCRIBE_*` environment variables override the YAML without a restart. None
of these keys is in the shipped `config/application.yml`; the defaults apply. Design:
[Tool Generation](../architecture/Tool%20Generation.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `studio.describe.enabled` | `true` | The Describe a tool page and its endpoints; off, they refuse with 403. |
| `studio.describe.model` | `toolsmith` | The gateway alias (or `provider/model`) that designs the tool. When the alias is not configured, `mock/mock-toolsmith` is used. |
| `studio.describe.max_description_chars` | `4000` | Longer descriptions are cut before the model sees them. |
| `studio.describe.draft_ttl_seconds` | `86400` | How long a draft (proposal, files, test results) stays in the state store. |
| `studio.describe.max_tests` | `8` | Test cases kept from a proposal (1 to 20). |
| `studio.describe.context_tools` | `40` | Existing tools offered to the model as context for composites (0 to 200). |

## Studio: permissions, the LLM tool creator and the planner editor

These have no configuration keys. Who may use each Studio creator is data, not configuration:
rows in the `permissions` table with resource type `studio` (`studio:<creator>` or `studio:*`;
the seeded roles are in `db/scripts/<dialect>/seed.sql`), described in the
[MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md#permissions). The LLM tool
creator's limits are bounded by `ai.llm_tools.limits.*` and its test runs, like the planner
editor's dry runs, use `ai.planners.dry_run_model`; the planner editor writes to `ai.planners.dir`.

## accounts

Connected accounts: users link third-party services; tools act as them. Reader: live
`_get` (`sajha/accounts/settings.py`, `AccountsSettings.load()`), read once on first use,
so `SAJHA_ACCOUNTS_*` environment variables override the YAML; restart to apply a change.
The provider block is read from the YAML as nested data, or from `SAJHA_ACCOUNTS_PROVIDERS`
(a JSON object), which replaces it; each provider field can also be set with
`SAJHA_ACCOUNTS_PROVIDERS_<ID>_<FIELD>`. Design and the provider fields:
[Connected Accounts](../architecture/Connected%20Accounts.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `accounts.enabled` | `true` | Master switch. Off: no linking, and tools that need a connected account fail. |
| `accounts.public_url` | `""` | Origin used in redirect URIs and connect URLs. Empty: `mcp.auth.public_url`, else the request's host (development only). |
| `accounts.flow_ttl_seconds` | `600` | How long a started Connect may take before its state expires. |
| `accounts.refresh_skew_seconds` | `120` | Refresh an access token this long before it expires. |
| `accounts.http_timeout_seconds` | `20` | Token endpoint, revocation, user-info and provider API calls. |
| `accounts.max_response_bytes` | `2000000` | Largest provider API answer a tool reads. |
| `accounts.vault.key` | `""` | The vault key (env `SAJHA_ACCOUNTS_VAULT_KEY`): 32 bytes base64url or a passphrase. Empty: generated once into the server secrets file. Several hosts must share it. |
| `accounts.vault.previous_keys` | `[]` | Old vault keys, still used to decrypt during a rotation. |
| `accounts.vault.key_provider` | `""` | `package.module:factory` returning a key provider (a KMS hook); replaces `key`. |
| `accounts.providers` | `{}` | Providers by id: a built-in template (`github`, `slack`, `google`, `microsoft`, `atlassian`, `notion`) is enabled by `client_id` and `client_secret_ref`; any other id is a custom provider. |

## observability

Reader: live `_get` for the scalar keys (`sajha/observability/settings.py`), so
`SAJHA_OBSERVABILITY_*` environment variables override the YAML; the metric, usage and
alert keys are read when used, the OpenTelemetry keys once at start-up. The rule list
`observability.alerts` is read from the YAML as nested data, or from
`SAJHA_OBSERVABILITY_ALERTS` (a JSON list), which replaces it. For OpenTelemetry the
standard `OTEL_*` variables win over these keys. Design, the metric families and the
rule fields: [Observability](../architecture/Observability.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `observability.metrics.enabled` | `true` | Serve `/metrics` and record the metric families; `false` answers 404 (the usage ledger is separate). |
| `observability.metrics.auth` | `admin` | Who may read `/metrics`: `admin` (a signed-in administrator), `token` (`Authorization: Bearer` equal to `SAJHA_OBSERVABILITY_METRICS_TOKEN`, or an administrator) or `none`. |
| `observability.metrics.port` | `0` | Above 0, also serve `/metrics` on a separate listener (same `auth` rule). |
| `observability.metrics.host` | `0.0.0.0` | That listener's bind address (all interfaces, like `server.host`). |
| `observability.metrics.tool_label` | `name` | The `tool` label: `name` (one series per tool), `group` (per tool group) or `none`. |
| `observability.metrics.max_series` | `2000` | Label sets per family; a new one beyond the cap is recorded with every label `_other`. |
| `observability.metrics.multiworker` | `auto` | With a shared `state.backend`, merge every worker's snapshot into each scrape under a `worker` label; `off` serves this worker only. |
| `observability.metrics.publish_interval_seconds` | `15` | How often each worker publishes its snapshot (TTL three intervals). |
| `observability.otel.enabled` | `false` | Export traces and metrics over OTLP (needs `opentelemetry-sdk` and an OTLP exporter package). |
| `observability.otel.endpoint` | `''` | Collector URL, e.g. `http://otel-collector:4318`; `OTEL_EXPORTER_OTLP_ENDPOINT` wins. |
| `observability.otel.protocol` | `http/protobuf` | `http/protobuf` or `grpc`; `OTEL_EXPORTER_OTLP_PROTOCOL` wins. |
| `observability.otel.headers` | (none) | `k=v,k2=v2` exporter headers; prefer `OTEL_EXPORTER_OTLP_HEADERS` for credentials. |
| `observability.otel.service_name` | `sajha-mcp-server` | `service.name`; `OTEL_SERVICE_NAME` wins. |
| `observability.otel.sample_ratio` | `1.0` | Parent-based trace sampling ratio; `OTEL_TRACES_SAMPLER_ARG` wins. |
| `observability.otel.traces` | `true` | Export traces (`OTEL_TRACES_EXPORTER=none` also turns them off). |
| `observability.otel.metrics` | `true` | Export metrics (`OTEL_METRICS_EXPORTER=none` also turns them off). |
| `observability.usage.enabled` | `true` | Record the usage ledger behind `/monitoring/usage`. |
| `observability.usage.retention_days` | `90` | Ledger rows older than this are deleted once a day; `0` keeps them. |
| `observability.usage.queue_size` | `10000` | Rows waiting to be written; beyond it rows are dropped and counted. |
| `observability.usage.max_rows_for_percentiles` | `200000` | Most rows one dashboard query reads; beyond it the figures are from the most recent rows. |
| `observability.alerts_interval_seconds` | `30` | How often the in-process alert rules are evaluated. |
| `observability.alerts_max_events` | `200000` | Size of the in-memory event window the rules read. |
| `observability.alerts_webhook.allowed_urls` | `[]` | URL prefixes an alert webhook may post to; any other URL makes its rule invalid. |
| `observability.alerts_webhook.allow_private_networks` | `false` | SSRF guard: allow loopback and RFC 1918 webhook hosts (never link-local). |
| `observability.alerts` | `[]` | The alert rules (fields in [Observability](../architecture/Observability.md#5-alerts)). |
| `observability.alerts_email.smtp_host` | `''` | SMTP server for `channel: {type: email}`. |
| `observability.alerts_email.smtp_port` | `587` | SMTP port. |
| `observability.alerts_email.from` | `sajha@localhost` | Sender address. |
| `observability.alerts_email.starttls` | `true` | Use STARTTLS. |
| `observability.alerts_email.username` | `''` | SMTP user; the password is `SAJHA_OBSERVABILITY_ALERTS_EMAIL_PASSWORD`. |

## System notices

Reader: live `_get` (`sajha/notices/__init__.py`), read when used, so `SAJHA_NOTICES_*`
environment variables override the YAML without a restart, except `check_interval_seconds`
(read when the watcher starts). The list `notices.forward` is read from the YAML as nested
data once per process, or from `SAJHA_NOTICES_FORWARD` (a JSON list), which replaces it.
Notices are kept in the state store (`state.backend`). Design and behaviour:
[System Notices](../architecture/System%20Notices.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `notices.enabled` | `true` | Master switch: off, sources raise nothing and the banner, badge and panel are not shown. |
| `notices.max_active` | `500` | Open notices kept at most; a new one beyond it clears the oldest open notice of the lowest severity (or is dropped when every open notice is more severe). |
| `notices.default_ttl_minutes` | `30` | A notice whose source has not refreshed it for this long is cleared; a source may set its own ttl (`0` = never). |
| `notices.banner_min_severity` | `error` | `error` or `critical`: the lowest severity that takes the banner. |
| `notices.cleared_retention_minutes` | `1440` | How long a cleared notice stays listed under "Show recently cleared" and `state=cleared`. |
| `notices.check_interval_seconds` | `30` | How often the watcher re-checks the polled sources (circuit breakers, LLM providers and aliases, federation) and clears expired notices. |
| `notices.workflow_failures` | `3` | Scheduled runs of one workflow that must fail in a row before it raises a notice. |
| `notices.forward` | `[]` | Also send each newly raised or escalated notice through an alert channel: entries `{min_severity, channel}`, where `channel` is `{type: log}`, `{type: webhook, url}` (the URL must be in `observability.alerts_webhook.allowed_urls`) or `{type: email, to}`. An invalid entry is logged and ignored. |

## workflows

Reader: live `_get` (`sajha/workflows/service.py`, `WorkflowService`), read once when the
service starts, so `SAJHA_WORKFLOWS_*` environment variables override the YAML; restart to
apply a change. A definition's own `concurrency`, `max_parallel`, `timeout_seconds` and each
step's `timeout_seconds` and `max_items` override the defaults below. Design, the definition
format and operation: [Workflows](../architecture/Workflows.md). Delivery uses
[`async.delivery`](#async-and-shell) (the webhook allow-list and the file directory).

| Key | Default | Purpose |
|-----|---------|---------|
| `workflows.enabled` | `true` | Master switch for the scheduler, triggers and the API (off: the API answers 503). |
| `workflows.tick_seconds` | `5` | Scheduler period: cron slots, file polls, resuming orphaned runs, waking parked runs, starting queued runs. |
| `workflows.max_concurrent_runs` | `8` | Runs executing at once in one worker. |
| `workflows.default_concurrency` | `4` | Runs of one workflow `running` or `waiting` at once, across all workers. |
| `workflows.max_parallel_steps` | `4` | Steps of one run executing at once. |
| `workflows.step_timeout_seconds` | `300` | Timeout of a call step that sets none. |
| `workflows.loop_max_items` | `100` | `foreach` cap when the step sets no `max_items`. |
| `workflows.loop_hard_max_items` | `10000` | `foreach` cap no step can exceed. |
| `workflows.inline_wait_seconds` | `5` | Waits up to this long run in the worker; longer ones park the run (status `waiting`) and free the worker. |
| `workflows.heartbeat_seconds` | `5` | How often a worker refreshes the heartbeat of a run it executes. |
| `workflows.stale_seconds` | `60` | A `running` run whose heartbeat is older (and whose worker is gone from the state store) is resumed by another worker. |
| `workflows.step_output_max_chars` | `262144` | A larger step or run output is stored as a truncated preview. |
| `workflows.step_input_max_chars` | `16384` | The same for the stored resolved input of a step. |
| `workflows.run_retention_days` | `30` | Finished runs older than this are deleted; `0` keeps every run. |

## Policy and audit

Reader: live `_get` for every scalar key (`sajha/policy/`, `sajha/audit/`), so
`SAJHA_POLICY_*` and `SAJHA_AUDIT_*` environment variables override the YAML and a change
applies on the next call (the chain's anchor cadence is read when the process's chain
opens). The sink list `audit.export.sinks` is read from the YAML as nested data, or from
`SAJHA_AUDIT_EXPORT_SINKS` (a JSON list), which replaces it, when the process starts.
The rule language, the sink fields and the design:
[Policy and Audit](../architecture/Policy%20and%20Audit.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `policy.enabled` | `true` | Evaluate policy rules before every tool call; `false` turns the engine off. |
| `policy.dir` | `config/policies` | Where policy files (`*.yaml`, `*.yml`, `*.json`) are read through the storage backend; an absolute path is read from local disk. |
| `policy.reload_seconds` | `5` | Recheck the directory at most this often (on the next call) and reload changed files. |
| `policy.default_effect` | `allow` | `deny`: a call that no rule explicitly allows is denied (allowlist mode). |
| `policy.on_error` | `ignore` | A policy file that does not parse: `ignore` (that file is not enforced) or `deny` (every call is denied until it is fixed). |
| `policy.fail_closed` | `true` | An error inside evaluation denies the call; `false` lets it run. |
| `policy.audit_allow` | `false` | Also write an audit record for each plain allow (decisions are always counted). |
| `policy.audit_arguments` | `false` | Put argument values, not only their names, in policy audit records. |
| `policy.approvals.ttl_seconds` | `86400` | How long a pending approval waits before it expires. |
| `policy.approvals.grant_ttl_seconds` | `3600` | How long an approved call may be made (once) after approval. |
| `policy.approvals.allow_self_approval` | `false` | Whether an administrator may approve a call they made. |
| `policy.approvals.notify_url` | `''` | Post each new approval here (must be in `observability.alerts_webhook.allowed_urls`; same SSRF guard). |
| `policy.approvals.notify_format` | `generic` | `generic` (JSON event) or `slack` (`{"text": ...}` for an incoming webhook). |
| `audit.chain.enabled` | `true` | Store the hash chain in `audit_chain` and `audit_anchors` (records are hashed and exported either way). |
| `audit.chain.anchor_every` | `100` | Sign the chain head after this many records. |
| `audit.chain.anchor_interval_seconds` | `300` | Also sign it at least this often while records arrive; `0` turns the timer off. |
| `audit.chain.flush_interval_ms` | `200` | Deferred records (tool calls) are stored by a background flusher this often; read when the chain opens. |
| `audit.chain.flush_batch` | `200` | ... or as soon as this many deferred records are waiting; read when the chain opens. |
| `audit.tool_calls.enabled` | `true` | Write a `tool.call` record for every tool call (settings reread every 5 seconds). |
| `audit.tool_calls.success_sample_rate` | `1.0` | Share (0 to 1) of successful calls recorded; failures, policy outcomes and destructive tools are always recorded. |
| `audit.tool_calls.sample_rates` | `[]` | Per-tool rates, `"glob=rate"`, first match wins (`["fred_*=0.1", "calc_*=0"]`); overrides `success_sample_rate`. |
| `audit.tool_calls.include_tools` | `[]` | Globs; when set, successful calls to other tools are not recorded. |
| `audit.tool_calls.exclude_tools` | `[]` | Globs whose successful calls are not recorded. |
| `audit.tool_calls.arguments` | `hash` | `hash` (SHA-256 of the canonical arguments, no values), `redacted` (values, secret-named keys and personal data masked) or `none`. |
| `audit.tool_calls.max_argument_bytes` | `4096` | Redacted arguments longer than this (canonical JSON) are cut. |
| `audit.export.allowed_urls` | `[]` | URL prefixes HTTP sinks may post to; empty allows any public host. |
| `audit.export.sinks` | `[]` | The SIEM sinks: `type` `syslog`, `http` or `file`, `format` `json`, `cef` or `ocsf` (fields in [Policy and Audit](../architecture/Policy%20and%20Audit.md#8-siem-export)). Tokens are secret references (`env:NAME`, `file:/path`). |

### snapshots

Reader: `_get` when the server starts (`sajha/snapshots/`), so `SAJHA_SNAPSHOTS_*` environment
variables override the YAML; `python -m sajha.snapshots` reads `snapshots.dir` the same way.
What a snapshot holds, the chain and the command line:
[Policy and Audit](../architecture/Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools).

| Key | Default | Purpose |
|-----|---------|---------|
| `snapshots.enabled` | `true` | Write a signed, chained snapshot of users, API keys and tools every interval. |
| `snapshots.interval_minutes` | `10` | Minutes between snapshots (at least 1); one worker writes per interval. |
| `snapshots.keep` | `20` | Snapshots kept; the oldest beyond this are deleted after each write (audited). |
| `snapshots.dir` | `data/snapshots` | Where the files go (mode 0700, files 0600); local disk. |
| `snapshots.compress` | `false` | Write gzip files (`.json.gz`). |

## Quality

Reader: live `_get` for every key (`sajha/quality/`), so `SAJHA_QUALITY_*` environment
variables override the YAML. Directories are read on use (tests, evals) or rechecked every
`quality.versions.reload_seconds` (versions files); the probe scheduler starts with the
process when `quality.probes.enabled` is true. The file formats, the routing rules and the
design: [Tool Quality](../architecture/Tool%20Quality.md).

| Key | Default | Purpose |
|-----|---------|---------|
| `quality.tests_dir` | `config/tool_tests` | Test-case files (`*.yaml`, `*.yml`, `*.json`); a tool config may also carry `tests` and `probe`. |
| `quality.cassettes_dir` | `config/tool_tests/cassettes` | Recorded HTTP fixtures, `<tool>/<case>.json`. |
| `quality.evals_dir` | `config/evals` | Ask SAJHA eval sets. |
| `quality.versions_dir` | `config/tool_versions` | One versions file per tool (`<tool>.yaml`); a version's whole config (`config:`) lives here too. |
| `quality.lint.min_description` | `40` | A tool description shorter than this many characters is a lint warning. |
| `quality.probes.enabled` | `false` | Run the `probe:` blocks of test files on their schedules (one worker per slot through the state store). |
| `quality.probes.tick_seconds` | `15` | How often the probe scheduler looks for due probes. |
| `quality.probes.default_every_seconds` | `300` | The interval of a probe that sets neither `every` nor `cron`. |
| `quality.probes.history` | `20` | Results kept per tool in the state store. |
| `quality.versions.enabled` | `true` | `false`: versions files are ignored and every call runs the registered tool. |
| `quality.versions.reload_seconds` | `5` | Recheck the versions directory at most this often (on the next call). |

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
| SIEM sink tokens | `audit.export.sinks[].token` as a secret reference (`env:SPLUNK_HEC_TOKEN`, `file:/run/secrets/hec`) | Never a literal token in the YAML. |
| Metrics scrape token, OTLP headers, alert SMTP password | `SAJHA_OBSERVABILITY_METRICS_TOKEN`, `OTEL_EXPORTER_OTLP_HEADERS`, `SAJHA_OBSERVABILITY_ALERTS_EMAIL_PASSWORD` | Environment only; there is no YAML key for them. |

On Kubernetes the Helm chart passes the JWT secret, session secret, OAuth signing key and
metrics token to every pod from one Secret, and sets the database, state and storage
variables from chart values; see [Kubernetes Deployment](Kubernetes%20Deployment.md#3-secrets).

See also the [Security Model](../security/Security%20Model.md) and the
[Architecture](../architecture/Architecture.md) overview.

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
