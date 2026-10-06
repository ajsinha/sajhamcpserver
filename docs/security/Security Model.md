# Security Model

This page describes how SAJHA MCP Server authenticates callers, authorizes them, protects its transports and sandboxes risky features. It also lists what you must configure before a production deployment and the limitations that remain open. It describes the code as built. Every statement names the file that implements it, so you can check it yourself.

For the OAuth 2.1 details of the MCP endpoint, see the [OAuth Guide](../protocol/OAuth%20Guide.md) and the [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md) page. This page only summarizes them.

The older point-in-time assessment is kept in `docs/archive/Cybersecurity_Assessment.md`, but it is no longer maintained. Several of its claims no longer match the code (see [What changed from the archived assessment](#what-changed-from-the-archived-assessment)).

---

## 1. Identities and credentials

### Where identities live

Users, roles, permissions, API keys and the audit log are stored in the SAJHA database. The schema is in `db/scripts/sqlite/001_schema.sql` (and the PostgreSQL equivalent), and the models are in `sajha/db/models/__init__.py`. The live authentication code is `sajha/auth/__init__.py` (`AuthManager`, `AuthContext`, `get_current_user`, `require_auth`, `require_admin`).

> `sajha/core/auth_manager.py` and `sajha/core/apikey_manager.py` are older managers. They are not wired into the running application (`sajha/app.py` passes `auth_manager=None` and `apikey_manager=None` to the config reloader), so their DB-persisted sessions and JSON key store are **not** in effect. Account lockout lives in `AuthManager.sign_in` (`sajha/auth/__init__.py`) and per-tool access in `sajha/auth/access.py`.

### Web login and passwords

- **Hashing.** Passwords are hashed with bcrypt at cost 12 (`sajha/auth/password.py`, `hash_password` / `verify_password`). Only `users.password_hash` is stored.
- **Login endpoints.** `POST /login` handles the HTML form and `POST /api/auth/login` returns a JSON token (`sajha/routes/auth_routes.py`). Both call `AuthManager.sign_in`, which rejects unknown or disabled users, verifies the bcrypt hash and applies the lockout below. The OAuth consent sign-in uses the same path.
- **Account lockout.** `auth.login.max_failed_attempts` (default 5) consecutive failed sign-ins lock the account for `auth.login.lockout_minutes` (default 15), using `users.failed_attempts` and `users.locked_until`. A locked account is refused even with the right password (HTTP 423 from both login endpoints); a successful sign-in resets the counter. Failures are audited as `user.login_failed`.
- **Failed sign-ins per IP.** A client IP with `auth.login.ip_max_failures` (default 20) failed sign-ins within `auth.login.ip_window_seconds` (default 300) gets 429 on both login endpoints and the OAuth consent sign-in (`login_blocked` / `record_login_failure` in `sajha/security.py`). Successful sign-ins are not counted, so many users behind one NAT are not throttled by each other.
- **Password policy.** New passwords (`password_problem` in `sajha/auth/password.py`) need at least 8 characters (`auth.password.min_length`, never below 8), at most 72 bytes (the bcrypt limit), must not be a well-known default (`admin123`, `changeme`, ...) and must not equal the user ID.
- **Changing a password.** A signed-in user changes their own password at `/account/password` (page, also in the user menu) or `POST /api/auth/change-password` (`{"current_password", "new_password"}`, returns a fresh JWT). Both need the current password; API keys have no password to change. An admin resets anyone's password with `POST /api/admin/users/{uid}/password` (`{"password", "must_change_password": true}`), which also unlocks the account. Changes are audited as `user.password_change` and `user.password_reset`.
- **Must change password.** `users.must_change_password` (added by `db/scripts/<type>/003_password_policy.sql`) is set for the seed admin while its seed hash is unchanged, for passwords an admin sets (create or reset), and whenever someone signs in with a well-known default password. While it is set, the session JWT carries `pwc: true`, `POST /api/auth/login` returns `"password_change_required": true`, and every console page shows a banner linking to `/account/password`.
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

- **Algorithm and secret.** The algorithm is `auth.jwt.algorithm` (default `HS256`), signed with the shared secret `auth.jwt.secret`. When no secret is configured, SAJHA generates one and persists it (see [Secrets](#6-secrets-and-deployment-checklist)); a publicly known placeholder value stops start-up.
- **Claims.** `sub` (user ID), `roles`, `iat`, `exp`, `iss: sajha-mcp-server`, and `pwc: true` while the password must be changed.
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
- **Tool access.** The key's `tool_access_mode` decides which tools it may list and run, everywhere tools run (REST, MCP, A2A): `all`, `allowlist` (the fnmatch patterns in `tool_access_list`), `denylist` (everything except them) or `regex` (tool names that fully match one of the listed regular expressions). An unknown mode grants nothing. See [Tool access](#tool-access).

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
- **Other resource types.** Async execution needs the admin role or a permission row (`async`, `*`, `execute`); the shell endpoints need the admin role or (`shell`, `*`, `execute`).

### Tool access

`sajha/auth/access.py` gives one answer to "may this caller see / run this tool?" for `POST /api/tools/execute`, `POST /api/tools/{tool}/execute-async`, every MCP transport (both protocol eras on `/mcp` and `/api/mcp`, the legacy SSE transport and `/mcp/ws`) and `POST /a2a`:

| Caller | Tools it may run | Tools it sees in `tools/list` |
|---|---|---|
| `admin` role | all | all |
| User (SAJHA JWT, session cookie, OAuth token for a SAJHA user) | patterns of its roles' `tool` (or `*`) permission rows with action `execute` or `*` | the same, plus rows with `read` |
| API key | its tool access mode (see [API keys](#api-keys)) | the same |
| External OAuth identity with no SAJHA account (`api_consumer`) | the tool permissions of a SAJHA role named `api_consumer`, if an operator creates one; otherwise none | the same |
| Anonymous (no credentials) | `mcp.anonymous.tools` (fnmatch allowlist, default empty) plus the tool permissions of the role in `mcp.anonymous.role` | the same |

- A refused call gets 403 on REST, `-32002` on 2025-11-25 MCP and `-32010` on 2026-07-28 MCP. An unknown tool is still reported as unknown (`-32602`).
- The policy travels inside the MCP session dict (`AuthContext.to_legacy_session`), and `MCPHandler` is constructed with `SessionToolAccess` (`sajha/app.py`), so `tools/list` is filtered and `tools/call` checked on every transport. With `mcp.cache.scope: auto`, an authenticated caller's `tools/list` is marked `cacheScope: private`; the anonymous list is `public`.
- The conformance fixtures (`test_*`, present only when `mcp.conformance_fixtures` is on) are not registry tools and stay callable by anyone.
- MCP `logging/setLevel` is accepted from anyone but changes the server's root log level only for an admin.

### Default admin account

The seed script creates the user `admin` with the role `admin`. Its bcrypt hash corresponds to the well-known password `admin123`, which is also used by `sajha/apiclient/demo.py`. The account is flagged [must change password](#web-login-and-passwords) until that seed hash is replaced, so every page shows a banner until you change it at `/account/password` (or `POST /api/auth/change-password`). Change it before you expose the server.

`POST /api/admin/users/create` requires a `password` that passes the password policy, and flags the new account to change it at first sign-in (unless the body says `"must_change_password": false`).

`config/users.json` and `config/apikeys.json` (tracked in git) contain demo credentials. The importer for them, `sajha/db/seed.py` (`run_legacy_import`), is not called at startup, so they do not create accounts or keys.

---

## 2. MCP endpoint authorization

The MCP endpoints (`POST/GET/DELETE /mcp`, `POST/DELETE /api/mcp`, `GET /mcp/sse`, `POST /mcp/message`) are in `sajha/routes/mcp_routes.py`. They authenticate through `authorize_mcp` in `sajha/auth/oauth/resource_server.py`, which is controlled by `mcp.auth.mode`:

| Mode | Behaviour |
|---|---|
| `off` (default) | SAJHA credentials are recognised. Anonymous calls are allowed when `mcp.anonymous.enabled` is true (else 401). OAuth endpoints and discovery documents answer 404. |
| `optional` | SAJHA credentials, or an OAuth bearer token that is validated (an invalid token gets 401 `invalid_token`). Anonymous calls are allowed when `mcp.anonymous.enabled` is true (else the 401 challenge). |
| `required` | A credential is mandatory. Without one, the response is 401 with `WWW-Authenticate: Bearer resource_metadata="...", scope="..."`. |

In every mode, API keys, SAJHA JWTs and the session cookie keep working on `/mcp`.

OAuth access tokens are accepted **only** on the MCP endpoints. They are RS256 (or another asymmetric algorithm) and audience-bound to the MCP resource, so the REST API's HS256 check rejects them.

**With the default `off`, `/mcp` accepts anonymous callers, but they see and run only the tools in `mcp.anonymous.tools` (none by default)**; see [Tool access](#tool-access). Set `mcp.anonymous.enabled: false` or `mcp.auth.mode: required` to demand credentials. Whoever authenticates is then limited by their own tool access.

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

One route family sets its own policy: the Python Playground. `/playground` adds `worker-src 'self'`
and sends `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`
(cross-origin isolation, for the Stop button's `SharedArrayBuffer`); its worker script,
`/api/playground/worker.js`, is the only response whose CSP allows `'wasm-unsafe-eval'`, plus the
Pyodide CDN when `playground.assets` is `cdn` and PyPI when `playground.allow_pypi` is true.
User code runs only in the browser; its tool calls are ordinary API requests under the user's
session. Details: [Python Playground](../getting-started/Python%20Playground.md#security).

### CORS

`CORSMiddleware` (`sajha/app.py`) allows the origins in `SAJHA_CORS_ORIGINS` (comma-separated). The default is `http://localhost:3002`, `http://127.0.0.1:3002` and `http://0.0.0.0:3002`. It sets `allow_credentials=True` with all methods and headers allowed, and exposes `Mcp-Session-Id`. Set `SAJHA_CORS_ORIGINS` to your real UI origins in production.

### Request size

`RequestSizeLimitMiddleware` (`sajha/security.py`) rejects requests whose `Content-Length` exceeds 10 MB with 413. Bodies sent without a `Content-Length` (chunked) are not measured.

### Rate limiting and lockout

All limiters are sliding windows in `sajha/security.py`, keyed by client IP and kept in the state store: per process with the default `state.backend: memory`, shared by every worker with `redis` or `database` ([Scaling and State](../architecture/Scaling%20and%20State.md)). Account lockout is stored in the database, so it holds across processes:

| Where | Limit |
|---|---|
| `POST /login`, `POST /api/auth/login`, OAuth consent sign-in | `auth.login.ip_max_failures` **failed** sign-ins per IP per `auth.login.ip_window_seconds` (default 20 per 300 s), then 429 |
| Every password sign-in (same three) | account lockout: `auth.login.max_failed_attempts` consecutive failures (default 5) lock the account for `auth.login.lockout_minutes` (default 15), then 423 |
| OAuth consent sign-in (`POST /oauth/authorize`) and `POST /oauth/register` | also 5 attempts per minute per IP (`check_auth_rate_limit`) |
| `GET /oauth/authorize` | 100 per minute per IP |
| `/mcp`, REST tool execution, WebSocket | **none** |

Limits that are defined but not applied: the per-user and per-key limits `check_user_rate_limit` (100/min) and `check_key_rate_limit` (200/min) exist but are not called anywhere.

Behind a reverse proxy the per-IP limits need the real client address: uvicorn takes it from `X-Forwarded-For` only when the proxy is in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`).

### WebSocket authentication

`/mcp/ws` (`sajha/routes/ws_routes.py`) authenticates from `?token=<SAJHA JWT>` with `AuthManager.authenticate_jwt`, or from `?api_key=<key>` with `AuthManager.authenticate_apikey`:

- An invalid `token` or `api_key` closes the connection with code 1008, in every mode.
- Without credentials, the connection is anonymous (the anonymous tool policy) unless `mcp.auth.mode` is `required` or `mcp.anonymous.enabled` is false; then it is closed with 1008.
- `tools/list` and `tools/call` apply the caller's [tool access](#tool-access).
- OAuth tokens are not accepted on this transport.
- `GET /api/ws/sessions` (connected user IDs) is admin-only.

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
| Public JWT and session secrets in `config/application.yml` | The YAML ships no secret. Empty secrets are generated once and persisted (mode 0600); known placeholder values stop start-up. | `sajha/core/server_secrets.py`, `sajha/core/config.py` |
| No per-tool authorization on MCP; anonymous callers could run every tool | One tool-access policy for REST, MCP (both eras, SSE, WebSocket), A2A and async; anonymous callers get `mcp.anonymous.*` (no tools by default). | `sajha/auth/access.py`, `sajha/core/mcp_handler.py`, `sajha/app.py` |
| API key tool lists ignored; API keys got 403 on `POST /api/tools/execute` | Enforced through the same policy. | `sajha/auth/access.py`, `sajha/auth/__init__.py` |
| `POST /a2a` ran tools anonymously | Anonymous policy or 401; tool access checked; tasks visible only to their creator. | `sajha/routes/a2a_routes.py` |
| Async execution wrote to any path and posted to any URL | Files only inside `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls`, with the CIMD SSRF guard; admin or `async:execute` permission and tool access required; tasks scoped to their owner. | `sajha/core/async_executor.py`, `sajha/routes/ops_routes.py` |
| Open admin endpoints | `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`, `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity` and the tool configuration page need an admin; the shell endpoints need admin or `shell:execute`. | `sajha/routes/` |
| No lockout or rate limit on the HTML login; no password change | Account lockout, failed-sign-in throttle, password policy, change-password page and API, admin reset, forced change for default passwords. | `sajha/auth/__init__.py`, `sajha/routes/auth_routes.py`, `sajha/security.py` |

---

## 5. Sandboxing and risky features

### Shell execution

Shell execution is off by default: `shell.enabled: ${SHELL_ENABLED:false}` in `config/application.yml`, read by `get_shell_executor` in `sajha/core/shell_executor.py`. Python additionally needs `shell.python.enabled` (default true once the shell is on). Bash needs `shell.bash.enabled: true`. The endpoints `POST /api/shell/python` and `POST /api/shell/bash` (`sajha/routes/ops_routes.py`) require the admin role or a permission row (`shell`, `*`, `execute`). History (`/api/shell/history`) is admin-only.

The controls are:

- **Python.** A regex rejects a blocklist of imports (such as `os`, `sys`, `subprocess`, `socket`, `urllib`, `ctypes`, `pickle`, `importlib`, `pathlib`) and a list of builtin call strings (`exec(`, `eval(`, `open(`, `getattr(` ...). The "allowed imports" set is only reported by `/api/shell/capabilities` and is not enforced.
- **Bash.** The first command and every pipe target must be in an allowlist (for example `cat`, `grep`, `awk`, `sed`, `find`, `jq`, `ls`). Regex patterns block `rm`, `mv`, `cp`, `sudo`, network tools, interpreters, command substitution, `;`, `&&`, `||` and pipe-to-shell.
- **The sandbox.** Code that passes the filters runs in the [sandbox](../architecture/Sandbox.md) backend (`sandbox.default_backend`), with the shell's timeout, `shell.python.memory_limit_mb` and `shell.bash.max_output_bytes`. The filters are string checks and can be bypassed (`find -exec`, `awk system()`, pandas file readers); the sandbox is the boundary.
- **Audit.** Every execution, including blocked ones, is written to the audit log as `shell_execute_python` / `shell_execute_bash`.

How strong the boundary is depends on the backend and the host: on Linux the default `subprocess` backend confines the code with Landlock, seccomp, user/PID/network namespaces and rlimits; on macOS and Windows it gives process separation, a clean environment and the limits only. `GET /api/sandbox/status` reports what is enforced on the running host.

### MCP Studio

The Studio pages (`/studio/*`) and the actions they post to (`/admin/studio/*`: analyze, preview, deploy, delete) are admin-only (`sajha/routes/studio_routes.py`). A deploy writes the generated files and loads the tool into the live registry.

Code a user supplies runs in the [sandbox](../architecture/Sandbox.md), not in the server: a Python code tool's module is never imported into the server, and a script tool's script runs in a fresh sandbox per call, with no server environment, no view of the server's files, and no network unless its `sandbox` policy allowlists hosts (`sandbox.enforce_for_generated_tools`, default `true`). Secrets reach a sandbox only by name through `sandbox.secrets_allowlist`, never a `SAJHA_*` variable. Studio's template creators (REST, DB query, Power BI, LiveLink, SharePoint, OLAP) take configuration, not code, and run in-process.

Tools are also installed by admins directly:

- `POST /api/admin/tools/{name}/config` and `POST /api/composite-tools` require an admin.
- A tool config's `implementation` is any importable dotted class path (`sajha/tools/tools_registry.py`); such a module is imported into the server unless the config sets `"sandbox": {"enabled": true}`.

Treat admin rights and write access to `config/tools` or `sajha/tools/impl` as equivalent to code execution in the server.

### Plugins

Plugins under `config.plugins.dir` (default `config/plugins`) are discovered and loaded at startup (`sajha/core/plugins.py`, called from `sajha/app.py`). They can also be loaded through the admin-only `/api/plugins/*` endpoints. Loading executes the plugin's Python modules.

If `plugin.json` has a `checksum: "sha256:..."`, the plugin files are hashed and a mismatch blocks loading. The checksum is optional and sits in the same directory as the code, so it detects accidental corruption, not tampering. Only put trusted code in the plugins directory.

### Conformance fixtures

The official conformance-suite test tools, prompts and resources are exposed only when `mcp.conformance_fixtures: true` (env `SAJHA_MCP_CONFORMANCE_FIXTURES`). The default is `false` (`sajha/core/mcp_conformance_fixtures.py`). Leave it off in production.

### MRTR `requestState`

For MCP 2026-07-28 multi-round-trip requests, the opaque `requestState` is `base64url(payload).base64url(HMAC-SHA256)` (`sajha/core/mcp_mrtr.py`). It is bound to the method, the target, a digest of the arguments and the caller. It expires after `mcp.mrtr.state_ttl_seconds` (default 900) and is verified in constant time. It is signed, not encrypted, and only carries what the client itself sent.

### Other features that need care

- **Async execution.** `POST /api/tools/{tool}/execute-async` (`sajha/routes/ops_routes.py`, `sajha/core/async_executor.py`) needs the admin role or a permission row (`async`, `*`, `execute`), plus execute access to the tool. Destinations are checked when the task is submitted (400 when refused) and again at delivery:
  - **file**: a relative path inside `async.delivery.file.base_dir` (no absolute paths, no `..`, no symlink target); written atomically.
  - **webhook**: the URL must match an entry of `async.delivery.webhook.allowed_urls` (same scheme, host and port, path at or under the entry's path; no credentials in the URL). Empty list (the default) refuses webhooks. The host is resolved once per attempt and every address vetted with the CIMD SSRF guard (`address_allowed` in `sajha/auth/oauth/clients.py`): public addresses only unless `async.delivery.webhook.allow_private_networks` is true (link-local such as cloud metadata stays refused). The request goes to the vetted IP, with no redirects and no proxy environment. Custom headers cannot set `Host` or framing headers.
  - **kafka**: a topic name (`[A-Za-z0-9._-]`, at most 249 characters).
  - Non-admins list, read, cancel and retry only their own tasks.
- **A2A.** `POST /a2a` (`sajha/routes/a2a_routes.py`) authenticates like the REST API; without credentials it applies the anonymous policy, or answers 401 when `mcp.anonymous.enabled` is false. It runs the first tool whose name appears in the message text, with empty arguments, only if the caller may execute it; otherwise the task fails with "Access denied". `tasks/get` and `tasks/cancel` see only the caller's own tasks (admins see all).
- **DuckDB SQL.** The DuckDB OLAP tool (`sajha/tools/impl/duckdb_olap_advanced.py`) allows statements starting with `SELECT`, `WITH`, `EXPLAIN`, `DESCRIBE`, `SHOW` or `PRAGMA` after stripping comments. DuckDB's external access (file and URL table functions) is not disabled.

---

## 6. Secrets and deployment checklist

Configuration is resolved from a `SAJHA_<KEY>` environment variable first, then `config/application.yml` (which itself supports `${VAR:default}`), then the code default (`sajha/core/config.py`). A `.env` file is loaded if present and is git-ignored.

| Item | What to do |
|---|---|
| **JWT secret** `auth.jwt.secret` (`JWT_SECRET`, `SAJHA_JWT_SECRET` or `SAJHA_AUTH_JWT_SECRET`) | Leave it empty and SAJHA generates a 256-bit value once into `auth.secrets_file` (default `<data.dir>/secrets/server_secrets.json`, mode 0600, directory 0700, `data/secrets/` is git-ignored), or set your own long random value. Every instance must see the same value (shared data directory or the env var). A value equal to a placeholder SAJHA ever shipped (`sajha/core/server_secrets.py`, `KNOWN_SHIPPED_SECRETS`) stops start-up with `InsecureSecretError`. Secret values are never logged. |
| **Session secret** `auth.session.secret_key` (`SESSION_SECRET`, `SAJHA_SECRET_KEY` or `SAJHA_AUTH_SESSION_SECRET_KEY`) | Same rules and the same file. It keys the OAuth consent CSRF HMAC and, when `mcp.mrtr.state_secret` is empty, the MRTR signing key, which is therefore stable across restarts and processes. |
| **MRTR secret** `mcp.mrtr.state_secret` (`SAJHA_MCP_MRTR_STATE_SECRET`) | Optional: by default it derives from the persisted session secret. A known placeholder value stops start-up. |
| **Default admin** | Change the `admin` / `admin123` password (see [Default admin account](#default-admin-account)). |
| **MCP authorization** `mcp.auth.mode`, `mcp.anonymous.*` | Use `required` (or `mcp.anonymous.enabled: false`) for anything reachable by untrusted clients. Keep `mcp.anonymous.tools` empty unless anonymous callers really need a tool. |
| **Async delivery** `async.delivery.*` | List webhook receivers in `async.delivery.webhook.allowed_urls`; keep `allow_private_networks` off. |
| **Public URL** `mcp.auth.public_url` | Set it to the external origin (e.g. `https://mcp.example.com`). If it is empty, the issuer and token audience come from the request's `Host` header, which is for local development only. |
| **OAuth signing key** | Generated at `data/oauth/signing_key.pem` (or `mcp.auth.builtin.signing_key_path`) with mode 0600. `data/oauth/` is in `.gitignore`. Back it up, keep it out of images, and share it between instances. |
| **External issuer user claim** | `mcp.auth.external.user_claim` is matched to SAJHA user IDs, so a token whose claim equals `admin` maps to the SAJHA admin. Use only a claim the IdP controls. |
| **HTTPS** | Terminate TLS at a reverse proxy. The cookie `Secure` flag and HSTS depend on the request scheme. Uvicorn trusts `X-Forwarded-Proto` only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`), so set that if the proxy is on another host. |
| **Origins** | Set `SAJHA_CORS_ORIGINS` and `mcp.allowed_origins` to the real browser origins. |
| **Bind address** | `server.host` defaults to `0.0.0.0`. Bind to loopback behind a proxy. |
| **Risky features** | Keep `shell.enabled`, `mcp.conformance_fixtures` and `mcp.auth.builtin.dynamic_client_registration` off unless needed. Review `config/plugins`. |
| **More than one process** | Set `state.backend` to `redis` or `database`. With the default `memory`, OAuth pending requests, codes, refresh tokens and DCR registrations, MCP sessions, tasks and rate-limit counters are per process: rate limits multiply by the number of processes, and a restart signs out every OAuth client. Every process must share the JWT secret, the session secret and the OAuth signing key ([Scaling and State](../architecture/Scaling%20and%20State.md)). WebSocket sessions are always per connection. |
| **Logs** | WebSocket credentials travel in the query string. Make sure proxy access logs do not keep them. |

---

## 7. Audit logging

Audit entries go to the `audit_log` table, through `AuditDAO.log` (`sajha/db/dao/__init__.py`) and `AuditLogger.log` (`sajha/core/audit.py`). Admins can read them with `GET /api/audit` (`sajha/routes/ops_routes.py`) and `GET /api/reports/audit` (`sajha/routes/reporting_routes.py`).

These events are written today:

| Event | Source |
|---|---|
| `user.login`, `user.login_failed` | `sajha/auth/__init__.py` |
| `user.password_change`, `user.password_reset` | `sajha/routes/auth_routes.py` |
| `user.create`, `user.enable`, `user.disable`, `user.delete` | `sajha/routes/api_routes.py` |
| `tool.enable`, `tool.disable`, `tool.config_update` | `sajha/routes/api_routes.py` |
| `apikey.create`, `apikey.toggle`, `apikey.delete` | `sajha/routes/apikeys_routes.py` |
| `shell_execute_python`, `shell_execute_bash` (with outcome and a code preview) | `sajha/core/shell_executor.py` |

These go elsewhere:

- **Tool runs** through `POST /api/tools/execute` go to the tool-usage table (`ToolUsageDAO.log_execution`), with the user, auth type, duration, client IP and an argument hash.
- **Account locks and OAuth code issuance** go only to the application log.

The convenience methods in `sajha/core/audit.py` for `login_failed`, `logout`, `account_locked`, `permission_change` and `config_change` exist but are not called. The table records the IP address only when a caller supplies it, and the current callers don't.

---

## 8. Known limitations

These describe the code as it stands. They are listed so you can compensate for them in deployment.

**Authorization gaps**

- **The catalog is public.** These need no authentication and describe every tool, whatever the caller may run: `GET /api/tools/list`, `GET /api/tools/{tool}/schema`, the tool-group endpoints, `GET /api/prompts/list`, `GET /api/prompts/{name}`, `POST /api/resources/list`, `POST /api/resources/read` (tool catalog), `POST /api/completion/complete`, `GET /.well-known/agent.json` and the MCP `tool/schema`-style extension methods.
- **Only tools are permission-checked on MCP.** Prompts and resources are not filtered per caller.
- **OAuth scopes** (`mcp:read` / `mcp:tools`) gate methods, not individual tools; tool access then applies on top.

**Brute force and sessions**

- **Account lockout can be triggered by anyone who knows a user ID** (a deliberate trade-off against password guessing); the lock expires after `auth.login.lockout_minutes`, and an admin password reset clears it.
- **JWTs cannot be revoked.** Logout only clears the cookie, and a stolen token is valid until it expires. Changing a password does not invalidate tokens already issued.

**Missing account features**

- **No SSO for the web UI.** The `oauth.*` block in `config/application.yml` (Azure, Okta, ...) and the `oauth_provider` / `oauth_subject` columns are not used by any login path. OAuth 2.1 applies only to the MCP endpoints.

**Process-local state**

- **Rate limits and OAuth state are per process with `state.backend: memory`** (the default); use `redis` or `database` to share them.
- **MCP sessions** record the user but are not re-checked against the caller on later requests. The session ID (a random UUID) acts as a bearer capability.

**Sandboxing**

- **Sandbox strength depends on the host.** Studio code and script tools and the shell run in the sandbox; on Linux it confines files, network and processes, on macOS and Windows it does not (only a clean environment and limits). The `subprocess` and namespace backends share the host kernel; use the `docker` backend with gVisor where kernel exploits are in scope. Host-name allowlisting is library-level (see [Sandbox](../architecture/Sandbox.md)).

**Headers and transport**

- **CSP allows `'unsafe-inline'`** for scripts and styles.
- **The request size limit** relies on `Content-Length`.
- **The WebSocket transport** does not check `Origin`.

**Hygiene**

- **Demo credentials are tracked in git.** `config/users.json` (plaintext `admin123`) and `config/apikeys.json` (demo `sja_` keys) are not imported, but should not be reused anywhere.

---

## What changed from the archived assessment

These statements in `docs/archive/Cybersecurity_Assessment.md` do not match the current code:

| Archived claim | Current code |
|---|---|
| DB-persisted, hashed session tokens with expiry | The cookie holds a stateless JWT. `UserSession` handling lives in the unused `sajha/core/auth_manager.py`. |
| Account lockout after 5 failures | Now true again, on the live path (`AuthManager.sign_in`, `auth.login.*`). |
| Web login is rate-limited | Failed sign-ins are throttled per IP on the HTML form, `POST /api/auth/login` and the OAuth sign-in; successes are not counted. |
| `?api_key=` works on HTTP | It works on the WebSocket only. |
| OAuth SSO for Azure, Okta, Auth0 and Keycloak | Not implemented for web login. OAuth 2.1 is implemented for `/mcp`. |
| Per-user and per-key API rate limits | The functions exist but are never called. |
| Audit events such as `login_failed` and `account_locked` | `user.login_failed` is emitted; account locks go to the application log only (see section 7). |
| Python import allowlist and 256 MB memory limit enforced | Neither is enforced. |
| `admin123` appears nowhere in Python source | It appears in `sajha/apiclient/demo.py`. |
| CORS default is `http://localhost:3002` | Now three loopback forms on port 3002. |
| API key display prefix is 12 characters | It is 8. |

These still hold, as described above: bcrypt password hashing, SHA-256 API key hashing, cookie attributes, the security headers, the 10 MB body limit, the DuckDB statement allowlist and shell execution being off by default.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
