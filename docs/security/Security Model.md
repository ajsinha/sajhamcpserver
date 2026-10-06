# Security Model

This page describes how SAJHA MCP Server authenticates callers, authorizes them, protects its transports and sandboxes risky features. It also lists what you must configure before a production deployment and the limitations that remain open. It describes the code as built. Every statement names the file that implements it, so you can check it yourself.

For the OAuth 2.1 details of the MCP endpoint, see the [OAuth Guide](../protocol/OAuth%20Guide.md) and the [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md) page. This page only summarizes them.

The older point-in-time assessment is kept in `docs/archive/Cybersecurity_Assessment.md`, but it is no longer maintained. Several of its claims no longer match the code (see [What changed from the archived assessment](#what-changed-from-the-archived-assessment)).

---

## 1. Identities and credentials

### Where identities live

Users, roles, permissions, API keys and the audit log are stored in the SAJHA database. The schema is in `db/scripts/sqlite/001_schema.sql` (and the PostgreSQL equivalent), and the models are in `sajha/db/models/__init__.py`. The live authentication code is `sajha/auth/__init__.py` (`AuthManager`, `AuthContext`, `get_current_user`, `require_auth`, `require_admin`).

> `sajha/core/auth_manager.py` and `sajha/core/apikey_manager.py` are older managers. They are not wired into the running application: `sajha/app.py` passes `auth_manager=None` and `apikey_manager=None`. Their account lockout, DB-persisted sessions and JSON key store are **not** in effect. See [Known limitations](#8-known-limitations).

### Web login and passwords

- **Hashing.** Passwords are hashed with bcrypt at cost 12 (`sajha/auth/password.py`, `hash_password` / `verify_password`). Only `users.password_hash` is stored.
- **Login endpoints.** `POST /login` handles the HTML form and `POST /api/auth/login` returns a JSON token (`sajha/routes/auth_routes.py`). Both call `AuthManager.authenticate_local`, which rejects unknown or disabled users and verifies the bcrypt hash.
- **No server-side sessions.** A successful login returns a SAJHA JWT (see below). The web form puts it in a cookie. Logging out (`GET /logout`) only deletes the cookie, so the token stays valid until it expires.

### Session cookie `sajha_token`

The cookie is set in `sajha/routes/auth_routes.py`. Its value is the SAJHA JWT itself, with these attributes:

| Attribute | Value |
|---|---|
| `HttpOnly` | yes |
| `SameSite` | `Lax` |
| `Secure` | only when the request scheme is `https` |
| `Max-Age` | 3600 seconds |

SameSite=Lax is the only CSRF defence for cookie-authenticated web and admin requests. The web forms do not use CSRF tokens; only the OAuth consent form does.

### SAJHA JWT (REST and web)

Tokens are created and verified in `sajha/auth/jwt_handler.py` and configured under `auth.jwt.*` in `config/application.yml`.

- **Algorithm and secret.** The algorithm is `auth.jwt.algorithm` (default `HS256`), signed with the shared secret `auth.jwt.secret`.
- **Claims.** `sub` (user ID), `roles`, `iat`, `exp` and `iss: sajha-mcp-server`.
- **Expiry.** `auth.jwt.expiry_minutes`, default 60.
- **Verification.** Decoding checks the signature, the allowed algorithm and `exp`. The user is then reloaded from the database on every request, so disabling a user takes effect immediately.

Callers send the token as `Authorization: Bearer <jwt>`.

### API keys

API keys are created by an admin at `POST /admin/apikeys/create` (`sajha/routes/apikeys_routes.py`).

- **Format.** `sja_` followed by `secrets.token_hex(24)`. The raw key is shown once.
- **Storage.** Only the SHA-256 hash (`ApiKeyDAO.hash_key` in `sajha/db/dao/__init__.py`) and the first 8 characters, used as a display prefix, are stored.
- **Validation.** `ApiKeyDAO.validate_key` rejects unknown, disabled and expired keys and records usage.
- **How to send a key.** `X-API-Key: sja_...`, or a bare `Authorization: sja_...` header. On the WebSocket transport only, use `?api_key=`.
- **Resulting identity.** An authenticated key becomes the identity `apikey:<name>` with the role `api_consumer`. It is never an admin.

### Order of authentication

`AuthManager.authenticate_request` tries these in order and stops at the first that succeeds:

1. `Authorization: Bearer <SAJHA JWT>`
2. `X-API-Key`
3. `Authorization: sja_...`
4. The `sajha_token` cookie

OAuth access tokens are not tried here. They only count on the MCP endpoints (see section 2).

### Roles and permissions

The seed data in `db/scripts/sqlite/002_seed.sql` creates these roles and permission rows:

| Role | Permission rows (`resource_type`, `resource_name`, `actions`) |
|---|---|
| `admin` | `*`, `*`, `*` |
| `user` | `tool`, `*`, `execute,read` |
| `viewer` | `tool`, `*`, `read` |
| `developer` | `studio`, `*`, `*` and `tool`, `*`, `execute,read,create` |

How these rows are used:

- **Matching.** `PermissionDAO.check_access` (`sajha/db/dao/__init__.py`) matches `resource_name` with fnmatch wildcards.
- **Admin check.** `User.is_admin` is true when the user has the `admin` role. Admin-only routes use `require_admin`.
- **Where per-tool access is enforced.** `AuthContext.has_tool_access` is checked only on `POST /api/tools/execute` (`sajha/routes/api_routes.py`).
- **Where it is not enforced.** It is not checked on the MCP endpoints, the WebSocket, `/a2a` or `POST /api/tools/{tool}/execute-async`.
- **API keys.** The per-key `tool_access_mode` / `tool_access_list` (`ApiKeyDAO.check_tool_access`) is stored but never consulted.

See [Known limitations](#8-known-limitations) for the consequences.

### Default admin account

The seed script creates the user `admin` with the role `admin`. Its bcrypt hash corresponds to the well-known password `admin123`, which is also used by `sajha/apiclient/demo.py`.

The application has **no change-password endpoint**. Before you expose the server:

1. Create a new admin with `POST /api/admin/users/create` (body includes `"roles": ["admin"]` and a strong `password`).
2. Disable or delete `admin` with `POST /api/admin/users/admin/disable` or `DELETE /api/admin/users/admin/delete`.

Alternatively, replace `users.password_hash` for `admin` directly in the database with a bcrypt hash you generate yourself.

`POST /api/admin/users/create` defaults the password to `changeme` when none is supplied, so always pass one.

`config/users.json` and `config/apikeys.json` (tracked in git) contain demo credentials. The importer for them, `sajha/db/seed.py` (`run_legacy_import`), is not called at startup, so they do not create accounts or keys.

---

## 2. MCP endpoint authorization

The MCP endpoints (`POST/GET/DELETE /mcp`, `POST/DELETE /api/mcp`, `GET /mcp/sse`, `POST /mcp/message`) are in `sajha/routes/mcp_routes.py`. They authenticate through `authorize_mcp` in `sajha/auth/oauth/resource_server.py`, which is controlled by `mcp.auth.mode`:

| Mode | Behaviour |
|---|---|
| `off` (default) | SAJHA credentials are recognised. Anonymous calls are allowed. OAuth endpoints and discovery documents answer 404. |
| `optional` | SAJHA credentials, or an OAuth bearer token that is validated (an invalid token gets 401 `invalid_token`). Anonymous calls are still allowed. |
| `required` | A credential is mandatory. Without one, the response is 401 with `WWW-Authenticate: Bearer resource_metadata="...", scope="..."`. |

In every mode, API keys, SAJHA JWTs and the session cookie keep working on `/mcp`.

OAuth access tokens are accepted **only** on the MCP endpoints. They are RS256 (or another asymmetric algorithm) and audience-bound to the MCP resource, so the REST API's HS256 check rejects them.

**With the default `off`, `/mcp` is open to anonymous callers.** Set `required` for any deployment reachable by untrusted clients.

### Resource server

`sajha/auth/oauth/resource_server.py` implements the resource-server side:

- **Discovery.** It serves RFC 9728 protected-resource metadata at `/.well-known/oauth-protected-resource[/mcp|/api/mcp]`.
- **Algorithms.** Only asymmetric algorithms are accepted. `none` and `HS*` are filtered out (`allowed_algorithms` in `sajha/auth/oauth/settings.py`).
- **Claims.** It requires `iss` and `exp` and honours `nbf` with a configurable clock skew (`mcp.auth.clock_skew_seconds`).
- **Audience.** `aud` must be one of this server's MCP resource URIs, or a value in `mcp.auth.accepted_audiences`.
- **Built-in issuer.** The key ID must match the local signing key and `typ` must be `at+jwt`.
- **External issuer.** The JWKS is found through RFC 8414 / OIDC discovery, with the issuer value checked against the metadata. It is fetched without following redirects, with a size cap, and cached for `mcp.auth.jwks_cache_seconds`. If a key ID is unknown, the JWKS is re-fetched at most every 30 seconds.
- **Identity mapping.** The token subject (or `mcp.auth.external.user_claim` for an external issuer) is matched to a SAJHA user and gets that user's roles. A missing or disabled built-in user is rejected. An external identity with no SAJHA account becomes the least-privilege `api_consumer` identity.
- **Scopes.** `tools/call` needs `mcp:tools`, every other method needs `mcp:read`, and `mcp` implies both (`mcp.auth.scopes`). A missing scope returns 403 `insufficient_scope`.

### Authorization server

There are two choices, set with `mcp.auth.authorization_server`:

- **`builtin`.** SAJHA's own authorization server, backed by SAJHA users. It is implemented in `sajha/auth/oauth/authorization_server.py`, `sajha/auth/oauth/clients.py`, `sajha/auth/oauth/keys.py` and `sajha/routes/oauth_routes.py`.
- **An external issuer URL** (Keycloak, Okta, Entra ID, ...). SAJHA then only validates the issuer's JWT access tokens. Opaque tokens and introspection are not supported.

The built-in server makes these security decisions (see the [OAuth Guide](../protocol/OAuth%20Guide.md) for detail):

- **PKCE.** S256 is mandatory and `plain` is rejected. The verifier is compared in constant time.
- **Redirect URIs.** They must match a registered URI exactly. An unknown client or a non-matching `redirect_uri` shows an error page instead of redirecting, which prevents open redirects. Plain `http` is allowed only for loopback hosts.
- **Authorization codes.** Codes are single-use and stored as SHA-256 hashes. A second redemption revokes the tokens the first one produced. Codes are bound to the client, `redirect_uri`, PKCE challenge, resource and issuer, and live for `mcp.auth.builtin.code_ttl_seconds` (default 60).
- **Refresh tokens.** They rotate on every use and are stored hashed. If a rotated-out token comes back, the whole grant family is revoked. A refresh token is issued only when `offline_access` is granted (default policy).
- **Access tokens.** RS256 JWTs (`typ: at+jwt`, RFC 9068) with `aud` set to the MCP resource and a lifetime of `mcp.auth.builtin.access_token_ttl_seconds` (default 900). The signing key is RSA-2048, generated on first use with mode 0600.
- **Consent page.** It is protected against CSRF by an HMAC token bound to the request ID and a browser-binding cookie (`HttpOnly`, `SameSite=Strict`, path `/oauth`). It is served with `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`. Pending requests are single-use.
- **Client ID Metadata Documents** (`https` client IDs). The fetch is guarded against SSRF: `https` only, the DNS answer is resolved and pinned, non-public addresses are refused unless `allow_localhost` / `allow_private_networks` are set, redirects are not followed, and size and timeout limits apply.
- **Client secrets.** Stored as SHA-256 hashes and compared in constant time. Public clients must not send one.
- **Dynamic Client Registration.** Off by default (`mcp.auth.builtin.dynamic_client_registration`).
- **Issuer identification.** The authorization response includes `iss` (RFC 9207).

---

## 3. Transport protections

### Origin allow-list for `/mcp`

The `/mcp`, `/api/mcp`, `/mcp/sse` and `/mcp/message` handlers call `validate_origin` (`sajha/core/mcp_2025_11_25.py`) and answer 403 for a disallowed `Origin`, as a DNS-rebinding defence:

- Requests without an `Origin` header are allowed.
- `localhost`, `127.0.0.1` and `[::1]` on any port are always allowed.
- Other origins must be listed exactly in `mcp.allowed_origins` (env `SAJHA_MCP_ALLOWED_ORIGINS`). `"*"` disables the check.

The WebSocket endpoint `/mcp/ws` does **not** check `Origin`.

### Security headers and CSP

`SecurityHeadersMiddleware` (`sajha/security.py`, registered in `sajha/app.py`) adds these headers to every response:

| Header | Value | Overridable by a route |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | no |
| `X-Frame-Options` | `SAMEORIGIN` | yes |
| `X-XSS-Protection` | `1; mode=block` | no |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | yes |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | no |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:` | yes |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains`, only when the request scheme is `https` | no |

The overridable headers are applied with `setdefault`, so a stricter value set by a route (for example the OAuth consent page) is no longer overwritten. All JS, CSS and fonts are vendored under `/static/vendor`. The CSP still allows `'unsafe-inline'` for inline template scripts and styles.

### CORS

`CORSMiddleware` (`sajha/app.py`) allows the origins in `SAJHA_CORS_ORIGINS` (comma-separated). The default is `http://localhost:3002`, `http://127.0.0.1:3002` and `http://0.0.0.0:3002`. It sets `allow_credentials=True` with all methods and headers allowed, and exposes `Mcp-Session-Id`. Set `SAJHA_CORS_ORIGINS` to your real UI origins in production.

### Request size

`RequestSizeLimitMiddleware` (`sajha/security.py`) rejects requests whose `Content-Length` exceeds 10 MB with 413. Bodies sent without a `Content-Length` (chunked) are not measured.

### Rate limiting and lockout

All limiters are in-memory sliding windows in `sajha/security.py`, keyed by client IP and kept per process:

| Where | Limit |
|---|---|
| `POST /api/auth/login` | 5 per minute per IP |
| OAuth consent sign-in (`POST /oauth/authorize`) and `POST /oauth/register` | the same 5 per minute per IP bucket |
| `GET /oauth/authorize` | 100 per minute per IP |
| `POST /login` (HTML form) | **none** |
| `/mcp`, REST tool execution, WebSocket | **none** |

Limits that are defined but not applied:

- **Per-user and per-key limits.** `check_user_rate_limit` (100/min) and `check_key_rate_limit` (200/min) exist but are not called anywhere.
- **Account lockout.** `check_account_locked`, with 5 failures and a 15-minute lock, is only used by the unused `sajha/core/auth_manager.py`. The live login path does not lock accounts.

### WebSocket authentication

`/mcp/ws` (`sajha/routes/ws_routes.py`) authenticates from `?token=<SAJHA JWT>` with `AuthManager.authenticate_jwt`, or from `?api_key=<key>` with `AuthManager.authenticate_apikey`:

- Under `mcp.auth.mode: required`, a connection without a valid credential is closed with code 1008.
- In `off` and `optional`, a missing or invalid credential leaves the connection anonymous.
- OAuth tokens are not accepted on this transport.

Credentials in the query string can end up in proxy and access logs.

---

## 4. Fixes since 6.0.0

Each fix below is present in the code:

| Issue | Fix | Where |
|---|---|---|
| Open redirect via `/login?next=` | `next` must be a local path. Values that don't start with `/`, start with `//` or `/\`, or contain a backslash fall back to `/dashboard`. | `sajha/routes/auth_routes.py` |
| Path traversal in `sajha://data/...` resources | The file name must equal its own basename and must not be `.`, `..` or contain `\`. Otherwise the result is "Resource not found". Reads are limited to `data/duckdb` and `data/sqlselect`. | `sajha/core/mcp_handler.py` (`_handle_resources_read`) |
| WebSocket authentication called a method that did not exist | Now calls `AuthManager.authenticate_jwt` / `authenticate_apikey` and honours `mcp.auth.mode: required`. | `sajha/routes/ws_routes.py` |
| Security headers overwrote stricter per-route values | `X-Frame-Options`, `Referrer-Policy` and `Content-Security-Policy` use `setdefault`. | `sajha/security.py` |

---

## 5. Sandboxing and risky features

### Shell execution

Shell execution is off by default: `shell.enabled: ${SHELL_ENABLED:false}` in `config/application.yml`, read by `get_shell_executor` in `sajha/core/shell_executor.py`. Python additionally needs `shell.python.enabled` (default true once the shell is on). Bash needs `shell.bash.enabled: true`. The endpoints `POST /api/shell/python` and `POST /api/shell/bash` (`sajha/routes/ops_routes.py`) require **any authenticated caller**, not an admin. History (`/api/shell/history`) is admin-only.

The controls are:

- **Python.** A regex rejects a blocklist of imports (such as `os`, `sys`, `subprocess`, `socket`, `urllib`, `ctypes`, `pickle`, `importlib`, `pathlib`) and a list of builtin call strings (`exec(`, `eval(`, `open(`, `getattr(` ...). The code runs in `python3` as a subprocess with a minimal environment (`PATH=/usr/bin:/bin`, empty `PYTHONPATH`, `HOME` set to the scratch directory), a working directory of `shell.scratch_dir`, and a timeout (default 30 s). The "allowed imports" set is only reported by `/api/shell/capabilities` and is **not enforced**. `shell.python.memory_limit_mb` is **not applied**.
- **Bash.** The first command and every pipe target must be in an allowlist (for example `cat`, `grep`, `awk`, `sed`, `find`, `jq`, `ls`). Regex patterns block `rm`, `mv`, `cp`, `sudo`, network tools, interpreters, command substitution, `;`, `&&`, `||` and pipe-to-shell. Commands run through `bash -c` with a minimal environment, a timeout (default 15 s) and an output cap.
- **Audit.** Every execution, including blocked ones, is written to the audit log as `shell_execute_python` / `shell_execute_bash`.

These are string filters on a process that runs as the server user. They are **not a security boundary**: allowlisted tools such as `find -exec`, `awk system()` and `sed`, or pandas/numpy file readers in Python, can reach the filesystem. Enable the shell only for fully trusted users, preferably inside a container with no secrets mounted.

### MCP Studio

The Studio pages under `/studio/*` (`sajha/routes/studio_routes.py`) need any authenticated user. The `developer` role's `studio` permission is not checked.

The deploy and preview calls the Studio templates make (`/admin/studio/...`, under `sajha/web/templates/admin/studio/`) have no route in the current application. Studio cannot deploy tools over HTTP in this build.

Tools are installed by admins instead:

- `POST /api/admin/tools/{name}/config` and `POST /api/composite-tools` require an admin.
- A tool config's `implementation` is any importable dotted class path (`sajha/tools/tools_registry.py`).

Treat admin rights and write access to `config/tools` as equivalent to code execution.

### Plugins

Plugins under `config.plugins.dir` (default `config/plugins`) are discovered and loaded at startup (`sajha/core/plugins.py`, called from `sajha/app.py`). They can also be loaded through the admin-only `/api/plugins/*` endpoints. Loading executes the plugin's Python modules.

If `plugin.json` has a `checksum: "sha256:..."`, the plugin files are hashed and a mismatch blocks loading. The checksum is optional and sits in the same directory as the code, so it detects accidental corruption, not tampering. Only put trusted code in the plugins directory.

### Conformance fixtures

The official conformance-suite test tools, prompts and resources are exposed only when `mcp.conformance_fixtures: true` (env `SAJHA_MCP_CONFORMANCE_FIXTURES`). The default is `false` (`sajha/core/mcp_conformance_fixtures.py`). Leave it off in production.

### MRTR `requestState`

For MCP 2026-07-28 multi-round-trip requests, the opaque `requestState` is `base64url(payload).base64url(HMAC-SHA256)` (`sajha/core/mcp_mrtr.py`). It is bound to the method, the target, a digest of the arguments and the caller. It expires after `mcp.mrtr.state_ttl_seconds` (default 900) and is verified in constant time. It is signed, not encrypted, and only carries what the client itself sent.

### Other features that need care

- **Async execution.** `POST /api/tools/{tool}/execute-async` (`sajha/routes/ops_routes.py`, `sajha/core/async_executor.py`) needs any authenticated caller and does no per-tool check. It delivers results to a caller-chosen webhook URL (no SSRF guard), Kafka topic, or **file path, including absolute paths**. Restrict this endpoint at the proxy if non-admin users exist.
- **A2A.** `POST /a2a` (`sajha/routes/a2a_routes.py`) accepts anonymous callers and runs the first tool whose name appears in the message text, with empty arguments.
- **DuckDB SQL.** The DuckDB OLAP tool (`sajha/tools/impl/duckdb_olap_advanced.py`) allows statements starting with `SELECT`, `WITH`, `EXPLAIN`, `DESCRIBE`, `SHOW` or `PRAGMA` after stripping comments. DuckDB's external access (file and URL table functions) is not disabled.

---

## 6. Secrets and deployment checklist

Configuration is resolved from a `SAJHA_<KEY>` environment variable first, then `config/application.yml` (which itself supports `${VAR:default}`), then the code default (`sajha/core/config.py`). A `.env` file is loaded if present and is git-ignored.

| Item | What to do |
|---|---|
| **JWT secret** `auth.jwt.secret` (`JWT_SECRET` or `SAJHA_AUTH_JWT_SECRET`) | **Must be set.** The shipped default `sajha-jwt-secret-change-in-production` is public, so anyone could mint an admin token. Use a long random value, identical on all instances. |
| **Session secret** `auth.session.secret_key` (`SESSION_SECRET` or `SAJHA_AUTH_SESSION_SECRET_KEY`) | **Must be set.** It keys the OAuth consent CSRF HMAC and, when `mcp.mrtr.state_secret` is empty, the MRTR signing key. The shipped default is public. |
| **MRTR secret** `mcp.mrtr.state_secret` (`SAJHA_MCP_MRTR_STATE_SECRET`) | Set a stable random value when running more than one process, or to keep states valid across restarts. |
| **Default admin** | Replace the `admin` / `admin123` account (see [Default admin account](#default-admin-account)). |
| **MCP authorization** `mcp.auth.mode` | Use `required` for anything reachable by untrusted clients. |
| **Public URL** `mcp.auth.public_url` | Set it to the external origin (e.g. `https://mcp.example.com`). If it is empty, the issuer and token audience come from the request's `Host` header, which is for local development only. |
| **OAuth signing key** | Generated at `data/oauth/signing_key.pem` (or `mcp.auth.builtin.signing_key_path`) with mode 0600. `data/oauth/` is in `.gitignore`. Back it up, keep it out of images, and share it between instances. |
| **External issuer user claim** | `mcp.auth.external.user_claim` is matched to SAJHA user IDs, so a token whose claim equals `admin` maps to the SAJHA admin. Use only a claim the IdP controls. |
| **HTTPS** | Terminate TLS at a reverse proxy. The cookie `Secure` flag and HSTS depend on the request scheme. Uvicorn trusts `X-Forwarded-Proto` only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`), so set that if the proxy is on another host. |
| **Origins** | Set `SAJHA_CORS_ORIGINS` and `mcp.allowed_origins` to the real browser origins. |
| **Bind address** | `server.host` defaults to `0.0.0.0`. Bind to loopback behind a proxy. |
| **Risky features** | Keep `shell.enabled`, `mcp.conformance_fixtures` and `mcp.auth.builtin.dynamic_client_registration` off unless needed. Review `config/plugins`. |
| **More than one process** | All of these are per-process memory: OAuth pending requests, codes, refresh tokens and DCR registrations; MCP sessions; tasks; WebSocket sessions; rate-limit counters. Run one process, or use sticky routing per client. Rate limits multiply by the number of processes, and a restart signs out every OAuth client (access tokens stay valid until expiry because the key is persisted). |
| **Logs** | WebSocket credentials travel in the query string. Make sure proxy access logs do not keep them. |

---

## 7. Audit logging

Audit entries go to the `audit_log` table, through `AuditDAO.log` (`sajha/db/dao/__init__.py`) and `AuditLogger.log` (`sajha/core/audit.py`). Admins can read them with `GET /api/audit` (`sajha/routes/ops_routes.py`) and `GET /api/reports/audit` (`sajha/routes/reporting_routes.py`).

These events are written today:

| Event | Source |
|---|---|
| `user.login` (successful local login only) | `sajha/auth/__init__.py` |
| `user.create`, `user.enable`, `user.disable`, `user.delete` | `sajha/routes/api_routes.py` |
| `tool.enable`, `tool.disable`, `tool.config_update` | `sajha/routes/api_routes.py` |
| `apikey.create`, `apikey.toggle`, `apikey.delete` | `sajha/routes/apikeys_routes.py` |
| `shell_execute_python`, `shell_execute_bash` (with outcome and a code preview) | `sajha/core/shell_executor.py` |

These go elsewhere:

- **Tool runs** through `POST /api/tools/execute` go to the tool-usage table (`ToolUsageDAO.log_execution`), with the user, auth type, duration, client IP and an argument hash.
- **Failed logins and OAuth code issuance** go only to the application log.

The convenience methods in `sajha/core/audit.py` for `login_failed`, `logout`, `account_locked`, `permission_change` and `config_change` exist but are not called. The table records the IP address only when a caller supplies it, and the current callers don't.

---

## 8. Known limitations

These describe the code as it stands. They are listed so you can compensate for them in deployment.

**Authorization gaps**

- **No per-tool authorization on MCP.** `MCPHandler` is built with `auth_manager=None` (`sajha/app.py`), so `tools/list` is not filtered and `tools/call` is not checked against roles on `/mcp`, `/api/mcp`, SSE or WebSocket. Any authenticated caller, including a `viewer` or an API key, can call any enabled tool. In modes `off` and `optional`, anonymous callers can too. OAuth scopes (`mcp:read` / `mcp:tools`) are the only per-method gate.
- **API keys on REST.** The per-key tool allowlist and denylist are never enforced. On `POST /api/tools/execute`, API keys are refused for every tool, because the role check needs a user record.
- **Unauthenticated endpoints.** These need no authentication:
  - `GET /api/tools/list`, `GET /api/tools/{tool}/schema` and the tool-group endpoints
  - `GET /api/prompts/list` and `GET /api/prompts/{name}`
  - `POST /api/resources/list`, `POST /api/resources/read` (tool catalog) and `POST /api/completion/complete`
  - `GET /api/ws/sessions`, which lists connected user IDs
  - `POST /api/logging/setLevel`, which changes the server's root log level
  - `POST /a2a`, which can run tools (see section 5)
- **Async execution** lets any authenticated caller write result files to arbitrary paths and send webhooks to arbitrary URLs (see section 5).

**Brute force and sessions**

- **No account lockout and no rate limit on the HTML login form.** The lockout code exists only in the unused `sajha/core/auth_manager.py`.
- **JWTs cannot be revoked.** Logout only clears the cookie, and a stolen token is valid until it expires.

**Missing account features**

- **No change-password or forced first-login change.** The seeded admin password is public.
- **No SSO for the web UI.** The `oauth.*` block in `config/application.yml` (Azure, Okta, ...) and the `oauth_provider` / `oauth_subject` columns are not used by any login path. OAuth 2.1 applies only to the MCP endpoints.

**Process-local state**

- **Rate limits and OAuth state are in memory and per process.**
- **MCP sessions** record the user but are not re-checked against the caller on later requests. The session ID (a random UUID) acts as a bearer capability.

**Sandboxing**

- **Shell sandboxing is a string filter, not isolation.** The Python memory limit and import allowlist are not enforced (see section 5).

**Headers and transport**

- **CSP allows `'unsafe-inline'`** for scripts and styles.
- **The request size limit** relies on `Content-Length`.
- **The WebSocket transport** does not check `Origin`, and in `optional` mode an invalid credential falls back to anonymous instead of being rejected.

**Hygiene**

- **No startup warning** is printed when the default JWT or session secret, or the default admin password, is still in use.
- **Demo credentials are tracked in git.** `config/users.json` (plaintext `admin123`) and `config/apikeys.json` (demo `sja_` keys) are not imported, but should not be reused anywhere.

---

## What changed from the archived assessment

These statements in `docs/archive/Cybersecurity_Assessment.md` do not match the current code:

| Archived claim | Current code |
|---|---|
| DB-persisted, hashed session tokens with expiry | The cookie holds a stateless JWT. `UserSession` handling lives in the unused `sajha/core/auth_manager.py`. |
| Account lockout after 5 failures | Not on the live login path. |
| Web login is rate-limited | Only `POST /api/auth/login` and the OAuth sign-in are. |
| `?api_key=` works on HTTP | It works on the WebSocket only. |
| OAuth SSO for Azure, Okta, Auth0 and Keycloak | Not implemented for web login. OAuth 2.1 is implemented for `/mcp`. |
| Per-user and per-key API rate limits | The functions exist but are never called. |
| Audit events such as `login_failed` and `account_locked` | Not emitted (see section 7). |
| Python import allowlist and 256 MB memory limit enforced | Neither is enforced. |
| `admin123` appears nowhere in Python source | It appears in `sajha/apiclient/demo.py`. |
| CORS default is `http://localhost:3002` | Now three loopback forms on port 3002. |
| API key display prefix is 12 characters | It is 8. |

These still hold, as described above: bcrypt password hashing, SHA-256 API key hashing, cookie attributes, the security headers, the 10 MB body limit, the auth rate limit on the API login, the DuckDB statement allowlist and shell execution being off by default.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
