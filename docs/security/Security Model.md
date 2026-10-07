# Security Model

This page describes how SAJHA MCP Server authenticates callers, authorizes them, protects its transports and sandboxes risky features. It also lists what you must configure before a production deployment and the limitations that remain open. It describes the code as built. Every statement names the file that implements it, so you can check it yourself.

For the OAuth 2.1 details of the MCP endpoint, see the [OAuth Guide](../protocol/OAuth%20Guide.md) and the [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md) page. This page only summarizes them.

This page supersedes the older point-in-time assessment in `docs/archive/` (not maintained; see the [archive index](../archive/README.md)).

---

## 1. Identities and credentials

### Where identities live

Users, roles, permissions, API keys and the audit log are stored in the SAJHA database. The schema is `db/scripts/<sqlite|postgresql>/schema.sql` ([Database Setup](../getting-started/Database%20Setup.md)), and the models are in `sajha/db/models/__init__.py`. The live authentication code is `sajha/auth/__init__.py` (`AuthManager`, `AuthContext`, `get_current_user`, `require_auth`, `require_admin`).

> Authentication is `AuthManager` in `sajha/auth/__init__.py` (sign-in, account lockout, JWTs, API keys); per-tool access is `sajha/auth/access.py`.

### Web login and passwords

- **Hashing.** Passwords are hashed with bcrypt at cost 12 (`sajha/auth/password.py`, `hash_password` / `verify_password`). Only `users.password_hash` is stored.
- **Login endpoints.** `POST /login` handles the HTML form and `POST /api/auth/login` returns a JSON token (`sajha/routes/auth_routes.py`). Both call `AuthManager.sign_in`, which rejects unknown or disabled users, verifies the bcrypt hash and applies the lockout below. The OAuth consent sign-in uses the same path.
- **Account lockout.** `auth.login.max_failed_attempts` (default 5) consecutive failed sign-ins lock the account for `auth.login.lockout_minutes` (default 15), using `users.failed_attempts` and `users.locked_until`. A locked account is refused even with the right password (HTTP 423 from both login endpoints); a successful sign-in resets the counter. Failures are audited as `user.login_failed`.
- **Failed sign-ins per IP.** A client IP with `auth.login.ip_max_failures` (default 20) failed sign-ins within `auth.login.ip_window_seconds` (default 300) gets 429 on both login endpoints and the OAuth consent sign-in (`login_blocked` / `record_login_failure` in `sajha/security.py`). Successful sign-ins are not counted, so many users behind one NAT are not throttled by each other.
- **Password policy.** New passwords (`password_problem` in `sajha/auth/password.py`) need at least 8 characters (`auth.password.min_length`, never below 8), at most 72 bytes (the bcrypt limit), must not be a well-known default (`admin123`, `changeme`, ...) and must not equal the user ID.
- **Changing a password.** A signed-in user changes their own password at `/account/password` (page, also in the user menu) or `POST /api/auth/change-password` (`{"current_password", "new_password"}`, returns a fresh JWT). Both need the current password; API keys have no password to change. An admin resets anyone's password with `POST /api/admin/users/{uid}/password` (`{"password", "must_change_password": true}`), which also unlocks the account. Changes are audited as `user.password_change` and `user.password_reset`.
- **Must change password.** `users.must_change_password` (in `db/scripts/<type>/schema.sql`) is set for the seed admin while its seed hash is unchanged, for passwords an admin sets (create or reset), and whenever someone signs in with a well-known default password. While it is set, the session JWT carries `pwc: true`, `POST /api/auth/login` returns `"password_change_required": true`, and every console page shows a banner linking to `/account/password`.
- **No server-side sessions, but revocable sign-in.** A successful login returns a SAJHA JWT (see below). The web form puts it in a cookie. Logging out revokes that token and deletes the cookie; a user (or an administrator) can also end every session at once. See [Revocable sign-in](#revocable-sign-in).

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
- **Claims.** `sub` (user ID), `roles`, `iat`, `exp`, `iss: sajha-mcp-server`, `jti` (a random token id), `tv` (the user's token version), and `pwc: true` while the password must be changed.
- **Expiry.** `auth.jwt.expiry_minutes`, default 60.
- **Verification.** Decoding checks the signature, the allowed algorithm and `exp`. The user is then reloaded from the database on every request, so disabling a user takes effect immediately; a token whose `tv` is not the user's current token version, or whose `jti` was signed out, is refused ([Revocable sign-in](#revocable-sign-in)).

Callers send the token as `Authorization: Bearer <jwt>`.

### API keys

API keys are managed by administrators at `/admin/apikeys` and by every signed-in user, for their own keys, at `/account/apikeys` (user menu, "My API keys"); the routes are in `sajha/routes/apikeys_routes.py` and the rules in `sajha/auth/apikeys.py`.

- **Format.** `sja_` followed by `secrets.token_hex(24)`. The raw key is shown once: when it is created and after each rotation.
- **Storage.** Only the SHA-256 hash (`ApiKeyDAO.hash_key` in `sajha/db/dao/__init__.py`) and the first 8 characters, used as a display prefix, are stored. The one exception is each user's default key (below), whose value is also kept encrypted.
- **Validation.** `ApiKeyDAO.validate_key` rejects unknown, revoked, disabled and expired keys; usage is recorded. The key row is read on every request, so disabling or revoking a key takes effect on the next request.
- **How to send a key.** `X-API-Key: sja_...`, or a bare `Authorization: sja_...` header. On the WebSocket transport only, use `?api_key=`.
- **Owner and resulting identity.** A key belongs to a user (`api_keys.owner_id`, set when it is created). An owned key signs in **as its owner**, with the owner's roles: it can reach what the owner can (an administrator's key is an administrator), and it stops working when the owner is disabled or deleted. Keys without an owner (keys created before owners existed, or by an administrator choosing "no owner") keep the older service identity `apikey:<name>` with the role `api_consumer`, and are never an admin, until an administrator assigns an owner on the API keys page (`POST /api/admin/apikeys/{key_id}/owner`); the page counts and filters them.
- **Tool access.** The key's `tool_access_mode` is `all`, `allowlist` (the fnmatch patterns in `tool_access_list`), `denylist` (everything except them) or `regex` (tool names that fully match one of the listed regular expressions); an unknown mode grants nothing. For an owned key it is a **ceiling** on the owner's tool access: a tool must be allowed by both. For a key without an owner it is the whole of the key's access. It applies everywhere tools run (REST, MCP, A2A). See [Tool access](#tool-access).
- **Who manages keys.** Users create keys for themselves (`POST /api/account/apikeys`), rotate and revoke them; administrators do the same for any key, create keys for any user or without an owner, disable and re-enable keys, assign owners, mark keys persistent and delete keys. Key management needs a signed-in user (console session or SAJHA JWT), never an API key, so a stolen key cannot mint more; browser requests carry the page's CSRF token. A user may hold `auth.api_keys.max_per_user` keys (default 25) besides the default key.
- **Revocation.** Revoking sets `revoked_at` and `revoked_by` and disables the key for good: it cannot be enabled again, and the row stays as a record. Deleting (administrators only) removes the row; prefer revoking.
- **Default key.** Every user has exactly one default key, created with the account (and, at start-up, for every account that has none). It cannot be revoked or deleted, only rotated (by its owner or an administrator) or disabled (by an administrator). Its raw value is kept encrypted in `api_keys.secret_ciphertext` with the connected-accounts vault's AES-256-GCM data key (`accounts.vault.key`, `SAJHA_ACCOUNTS_VAULT_KEY`, a `key_provider`, or the key generated into the server secrets file; [Connected Accounts](../architecture/Connected%20Accounts.md)), bound to the owner and the key id, so the server can later act for the user with it. A default key created at start-up has never been shown: its owner rotates it to get a value.
- **Persistent keys.** An administrator can mark a key persistent (when creating it, or later). Its record (id, prefix, name, SHA-256 hash, owner's user ID, name and roles, enabled, expiry, tool access, created, revoked) is then also kept in the file at `config.apikeys.path` (default `config/apikeys.json`; `sajha/auth/persistent_keys.py`), so the key keeps working when the database does not know it or does not answer. The database is checked first and decides for every key it knows (disabled or revoked there wins); a file key whose owner is not an enabled user in a database that answers is refused. SAJHA rewrites the file atomically (temporary file, then rename) on every change and re-reads it when it changes on disk, so an operator can revoke a key by editing it during an outage. The file is written with mode 0600 and is git-ignored; `config/apikeys.json.example` documents the format. It holds no keys, but it names users and their access, so treat it as sensitive. The older plaintext format (a top-level `apikeys` list) is never read and is replaced on the first write.
- **Audit.** Every change is audited (`apikey.*` events below), with the key's id and prefix, never the key.

### Revocable sign-in

Signing in issues tokens that are checked on every request, so they can be withdrawn before they expire (`sajha/auth/revocation.py`):

- **One session: sign out.** Every SAJHA JWT carries a `jti`. `GET /logout` and `POST /api/auth/logout` record the presented token's `jti` in the [state store](../architecture/Scaling%20and%20State.md) (`auth:revoked:<jti>`) until the token would have expired; the token is then refused everywhere. With `state.backend: memory` only the process that handled the sign-out knows; several workers need `redis` or `database`. If the state store does not answer, the check is skipped (logged) rather than signing everyone out.
- **Every session of a user: the token version.** Each user has `users.token_version`, copied into every SAJHA JWT and every access token of SAJHA's own OAuth authorization server as the claim `tv` (a token without `tv`, issued before this existed, counts as 0). The user row is reloaded on every request anyway, so a token whose `tv` differs is refused. The version is raised by "Sign out everywhere" (`POST /api/auth/sessions/revoke`, or the button on My API keys), by a password change (the session that changed it gets a fresh token; every other session ends), by an administrator's password reset and by an administrator's `POST /api/admin/users/{uid}/sessions/revoke` (the Users page). Each raise is audited as `user.sessions_revoked` with the reason.
- **OAuth refresh tokens.** Refresh tokens of SAJHA's authorization server remember the token version they were issued under; once it changes, refreshing fails with `invalid_grant` and the grant's refresh-token family is revoked.
- **API keys are not sessions.** Ending sessions does not touch API keys; revoke or rotate those ([API keys](#api-keys)). Key revocation takes effect on the next request.
- **Not covered.** Access tokens from an external issuer are that issuer's to revoke; SAJHA only stops accepting them when the user is disabled. An MCP session ID is not a credential on its own: each request on it is authenticated again.

### Order of authentication

`AuthManager.authenticate_request` tries these in order and stops at the first that succeeds:

1. `Authorization: Bearer <SAJHA JWT>`
2. `X-API-Key`
3. `Authorization: sja_...`
4. The `sajha_token` cookie

OAuth access tokens are not tried here. They only count on the MCP endpoints (see section 2).

### Roles and permissions

The seed data in `db/scripts/<type>/seed.sql` creates these roles and permission rows:

| Role | Permission rows (`resource_type`, `resource_name`, `actions`) |
|---|---|
| `admin` | `*`, `*`, `*` |
| `user` | `tool`, `*`, `execute,read` |
| `viewer` | `tool`, `*`, `read` |
| `developer` | `studio`, `*`, `*` and `tool`, `*`, `execute,read,create` |

How these rows are used:

- **Matching.** `PermissionDAO.check_access` (`sajha/db/dao/__init__.py`) matches `resource_name` with fnmatch wildcards.
- **Admin check.** `User.is_admin` is true when the user has the `admin` role. Admin-only routes use `require_admin`.
- **Other resource types.** Async execution needs the admin role or a permission row (`async`, `*`, `execute`); the shell endpoints need the admin role or (`shell`, `*`, `execute`); MCP Studio needs the admin role or (`studio`, `*`, `*` or `use`), which the seeded `developer` role has (`require_studio`).

### Tool access

`sajha/auth/access.py` gives one answer to "may this caller see / run this tool?" for `POST /api/tools/execute`, `POST /api/tools/{tool}/execute-async`, every MCP transport (both protocol eras on `/mcp` and `/api/mcp`, the legacy SSE transport and `/mcp/ws`), `POST /a2a`, the REST catalog (`GET /api/tools/list`, `/api/tools/{tool}/schema`, `/api/tool-groups/*`, which also answer 401 where `/mcp` would), the console's tool pages (`/tools`, `/tools/{tool}/schema`, `/tools/{tool}/execute`) and the tool names the landing page, `/help/tools`, `/about` and Ask SAJHA show (counts stay whole-catalog):

| Caller | Tools it may run | Tools it sees in `tools/list` |
|---|---|---|
| `admin` role | all | all |
| User (SAJHA JWT, session cookie, OAuth token for a SAJHA user) | patterns of its roles' `tool` (or `*`) permission rows with action `execute` or `*` | the same, plus rows with `read` |
| API key with an owner | the owner's access (as a user above; everything for an admin), capped by the key's tool access mode | the same |
| API key without an owner | its tool access mode (see [API keys](#api-keys)) | the same |
| External OAuth identity with no SAJHA account (`api_consumer`) | the tool permissions of a SAJHA role named `api_consumer`, if an operator creates one; otherwise none | the same |
| Anonymous (no credentials) | `mcp.anonymous.tools` (fnmatch allowlist, default empty) plus the tool permissions of the role in `mcp.anonymous.role` | the same |

- A refused call gets 403 on REST, `-32002` on 2025-11-25 MCP and `-32010` on 2026-07-28 MCP. An unknown tool is still reported as unknown (`-32602`).
- The policy travels inside the MCP session dict (`AuthContext.to_legacy_session`), and `MCPHandler` is constructed with `SessionToolAccess` (`sajha/app.py`), so `tools/list` is filtered and `tools/call` checked on every transport. With `mcp.cache.scope: auto`, an authenticated caller's `tools/list` is marked `cacheScope: private`; the anonymous list is `public`.
- **There is no tenant layer.** Teams are separated by roles, API-key tool access and [policy rules](../architecture/Policy%20and%20Audit.md) (which can also meter quotas); there are no tenant records.
- The conformance fixtures (`test_*`, present only when `mcp.conformance_fixtures` is on) are not registry tools and stay callable by anyone.
- **The rest of the catalog follows the same policy.** The `sajha://tools/catalog` resource (MCP `resources/read` and `POST /api/resources/read`), its count in `resources/list`, `completion/complete` for a `ref/tool`, the MCP `tool/schema`, `tool/description`, `tool/input_schema` and `tool/output_schema` extension methods, and the skills in `GET /.well-known/agent.json` show only the tools the caller may see. An anonymous caller with the default empty `mcp.anonymous.tools` gets a generic agent card with no skills.
- **Data resources.** `sajha://data/<file>` (the data files in `data/duckdb` and `data/sqlselect`) is listed and readable by every signed-in caller; anonymous callers see only URIs matching `mcp.anonymous.resources` (fnmatch over the URI, default empty), in `resources/list` and `resources/read` on both eras. A file the caller may not read is reported as not found. `/api/resources/list` and `/api/resources/read` require credentials and use the same reader. `sajha/auth/access.py` (`can_read_resource`), `sajha/core/data_resources.py`.
- **Prompts.** There are no per-prompt permissions for signed-in callers: they see every prompt. Anonymous callers see only prompts matching `mcp.anonymous.prompts` (fnmatch allowlist, default empty) in `prompts/list`, `prompts/get`, `completion/complete` for a `ref/prompt`, the `sajha://prompts/catalog` resource and `GET /api/prompts/list` / `GET /api/prompts/{name}` (which also answer 401 where `/mcp` would). A hidden prompt is reported as unknown (`-32602`, or 404 on REST). `sajha/auth/access.py` (`can_see_prompt`). With `mcp.cache.scope: auto`, `prompts/list`, `resources/list` and `resources/read` are `private` for an authenticated caller and `public` for anonymous ones, as for `tools/list`.
- MCP `logging/setLevel` is accepted from anyone but changes the server's root log level only for an admin.

### Inner calls

A tool that calls other tools runs each of them **as the original caller** (`sajha/core/inner_calls.py`). Every entry point that sets the caller (both MCP eras on every transport, `POST /api/tools/execute`, async execution, A2A, Ask SAJHA, workflow runs) records the caller's tool access with it (`sajha/observability/caller.py`), and the context follows the call into worker threads:

- **Composite steps.** Each step (master and children) is checked against the caller's access; a step the caller may not execute fails with "access denied" instead of running. Policy rules, the usage ledger and connected accounts see the caller.
- **`sajha_ask` and other LLM tools.** Every [LLM tool](../architecture/LLM%20Tools.md) runs as its caller: the tools its model may call are the tool's `tools.allow` minus `tools.deny`, intersected with what the caller may execute, and each inner call goes through the normal tool path (policy, audit). Anonymous callers may not run LLM tools unless `ai.llm_tools.anonymous.enabled`, and never get stored conversations. For `sajha_ask`: the ask runs with the caller's user ID and roles; it may run only tools the caller may execute, narrowed further to `ai.ask.mcp_allowed_tools` when that list is set (it no longer widens what an anonymous caller may run). Only when no entry point recorded a caller (code that runs the tool directly) does the older rule apply: the anonymous policy plus `ai.ask.mcp_allowed_tools`.
- **Workflows** keep their own rule: steps run as the workflow's owner (the run-as identity, [Workflows](../architecture/Workflows.md)), which is why only administrators publish a workflow as a tool.
- **Cycles and depth.** The tools currently running one inside another form a call chain (a context variable). A tool already in the chain is not called again, and a chain deeper than `tools.max_call_depth` (default 8) is refused.

### Default admin account

The seed script creates the user `admin` with the role `admin`. Its bcrypt hash corresponds to the well-known password `admin123`, which is also used by `sajha/apiclient/demo.py`. The account is flagged [must change password](#web-login-and-passwords) until that seed hash is replaced, so every page shows a banner until you change it at `/account/password` (or `POST /api/auth/change-password`). Change it before you expose the server.

`POST /api/admin/users/create` requires a `password` that passes the password policy, and flags the new account to change it at first sign-in (unless the body says `"must_change_password": false`).

Users live only in the database. The old demo users file (config/users.json, with a plaintext `admin123`) is removed: nothing reads or watches that path, and it is git-ignored so a local copy is not committed again. `config/apikeys.json` is no longer a demo file: it is the git-ignored [persistent key file](#api-keys), holding SHA-256 hashes only; the four plaintext demo keys it used to ship were never imported and are gone.

Users, roles and API key records are also kept in signed, chained [snapshots](../architecture/Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools) (no password hashes; key hashes only for persistent keys), from which an administrator can re-create missing users after losing the database (`python -m sajha.snapshots restore`, with confirmation). Restored users get an unusable password and must change it. The snapshot files name users and their access: they are written owner-only (directory 0700, files 0600) and git-ignored.

---

## 2. MCP endpoint authorization

The MCP endpoints (`POST/GET/DELETE /mcp`, `POST/DELETE /api/mcp`, `GET /mcp/sse`, `POST /mcp/message`) are in `sajha/routes/mcp_routes.py`. They authenticate through `authorize_mcp` in `sajha/auth/oauth/resource_server.py`, which is controlled by `mcp.auth.mode`:

| Mode | Behaviour |
|---|---|
| `off` (default) | SAJHA credentials are recognised. Credentials that are sent (`Authorization` or `X-API-Key`) but do not authenticate get 401 `invalid_token`; they are never downgraded to anonymous (a stale web cookie alone is). Anonymous calls are allowed when `mcp.anonymous.enabled` is true (else 401). OAuth endpoints and discovery documents answer 404. |
| `optional` | SAJHA credentials, or an OAuth bearer token that is validated (an invalid token gets 401 `invalid_token`). Anonymous calls are allowed when `mcp.anonymous.enabled` is true (else the 401 challenge). |
| `required` | A credential is mandatory. Without one, the response is 401 with `WWW-Authenticate: Bearer resource_metadata="...", scope="..."`. |

In every mode, API keys, SAJHA JWTs and the session cookie keep working on `/mcp`.

**stdio.** `python run_server.py --stdio` (`sajha/cli/stdio.py`) has no HTTP layer, so no
`authorize_mcp`, Origin check or OAuth: its one caller is fixed at start-up. `--api-key`
(or `SAJHA_API_KEY`) uses that key's tool access; `--user` (or `SAJHA_STDIO_USER`) takes
that SAJHA user's roles **without a password**, on the grounds that whoever can start the
process can already read the database it opens; with neither, the anonymous policy applies.
Treat the right to launch it as the right to act as any user. See
[Command Line](../clients/Command%20Line.md).

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
| `/mcp`, REST tool execution, WebSocket | a policy `rate_limit` rule (per `tool`, `user`, `api_key`, `caller` or `global`), the one limiter for tool calls, applied on every path ([Policy and Audit](../architecture/Policy%20and%20Audit.md)); the shipped default policy has no rules, and `config/policies/00-default.yaml` carries a commented per-user and per-API-key example to enable |

There is no other per-user or per-key limiter: the unused `check_user_rate_limit` and `check_key_rate_limit` were removed, so a policy rule is the only place such a limit can come from.

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
| Path traversal in `sajha://data/...` resources | The file name must equal its own basename and must not be `.`, `..` or contain `\`. Otherwise the result is "Resource not found". Reads are limited to `.csv`, `.parquet`, `.json` and `.xlsx` files in `data/duckdb` and `data/sqlselect`. | `sajha/core/data_resources.py` |
| WebSocket authentication called a method that did not exist | Now calls `AuthManager.authenticate_jwt` / `authenticate_apikey` and honours `mcp.auth.mode: required`. | `sajha/routes/ws_routes.py` |
| Security headers overwrote stricter per-route values | `X-Frame-Options`, `Referrer-Policy` and `Content-Security-Policy` use `setdefault`. | `sajha/security.py` |
| Public JWT and session secrets in `config/application.yml` | The YAML ships no secret. Empty secrets are generated once and persisted (mode 0600); known placeholder values stop start-up. | `sajha/core/server_secrets.py`, `sajha/core/config.py` |
| No per-tool authorization on MCP; anonymous callers could run every tool | One tool-access policy for REST, MCP (both eras, SSE, WebSocket), A2A and async; anonymous callers get `mcp.anonymous.*` (no tools by default). | `sajha/auth/access.py`, `sajha/core/mcp_handler.py`, `sajha/app.py` |
| API key tool lists ignored; API keys got 403 on `POST /api/tools/execute` | Enforced through the same policy. | `sajha/auth/access.py`, `sajha/auth/__init__.py` |
| `POST /a2a` ran tools anonymously | Anonymous policy or 401; tool access checked; tasks visible only to their creator. | `sajha/routes/a2a_routes.py` |
| Async execution wrote to any path and posted to any URL | Files only inside `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls`, with the CIMD SSRF guard; admin or `async:execute` permission and tool access required; tasks scoped to their owner. | `sajha/core/async_executor.py`, `sajha/routes/ops_routes.py` |
| Open admin endpoints | `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`, `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity` and the tool configuration page need an admin; the shell endpoints need admin or `shell:execute`. | `sajha/routes/` |
| No lockout or rate limit on the HTML login; no password change | Account lockout, failed-sign-in throttle, password policy, change-password page and API, admin reset, forced change for default passwords. | `sajha/auth/__init__.py`, `sajha/routes/auth_routes.py`, `sajha/security.py` |
| Any OLAP tool ran any OLAP operation (a caller-supplied `_tool_name`), including the unadvertised `olap_generate_sample_data`, which writes files | An OLAP tool runs only the operation it is registered as; `_tool_name` is refused. | `sajha/tools/impl/duckdb_olap_advanced.py` |
| The REST tool catalog listed every tool to anyone | `/api/tools/list`, `/api/tools/{tool}/schema` and `/api/tool-groups/*` apply the `tools/list` policy and answer 401 where `/mcp` would; the console tool pages and the tool names on public pages follow the same policy. | `sajha/routes/api_routes.py`, `sajha/routes/tools_routes.py`, `sajha/web/help_catalog.py` |
| A tool's schema page showed its resolved configuration (API keys included) to every signed-in user | Shown to administrators only, as on the configuration page. | `sajha/routes/tools_routes.py` |
| Enabling or disabling a tool wrote its resolved configuration, secrets included, back to the config file | Only `enabled` is changed in the stored file; `${...}` references stay. | `sajha/tools/tools_registry.py` |
| Tool arguments were checked only for presence | Validated against the tool's JSON Schema before it runs (`pattern`, `enum`, bounds, types, `additionalProperties`). | `sajha/tools/base_mcp_tool.py` |
| Prompts, the tool and prompt catalog resources, `completion/complete`, the `tool/schema`-style MCP methods and the A2A agent card described every tool and prompt to anonymous callers | All follow the tool-access policy; anonymous callers see only `mcp.anonymous.tools` / `mcp.anonymous.prompts` (nothing by default). See [Tool access](#tool-access). | `sajha/auth/access.py`, `sajha/core/mcp_handler.py`, `sajha/routes/prompts_routes.py`, `sajha/routes/mcp_routes.py`, `sajha/routes/a2a_routes.py` |
| SQL injection in the OLAP tools: filter values, dimension and measure names, operators, aggregations, sort directions and limits were pasted into SQL | Filter values (and date ranges) are DuckDB named parameters; dimension and measure names must be declared by the dataset in `config/olap/datasets.json` and resolve to their configured expressions; operators, aggregations, directions, time grains and numbers are allowlisted or coerced. | `sajha/olap/sql_safety.py`, `sajha/olap/*_engine.py`, `sajha/tools/impl/duckdb_olap_advanced.py` |
| `duckdb_sql` accepted any statement after a `SELECT` (`SELECT 1; DROP TABLE orders`) and could read any local file or URL (`read_text('/etc/passwd')`) | Exactly one statement of type `SELECT` or `EXPLAIN`, checked by DuckDB's parser on the exact text that runs; the CSV files are loaded into tables at start-up, then `enable_external_access` is switched off and the configuration locked. | `sajha/tools/impl/duckdb_olap_advanced.py` (`DuckDBSQLTool`) |
| The other `duckdb_*` tools put caller table and column names (and `duckdb_aggregate`'s `having`) straight into SQL (`DESCRIBE {table_name}`), `duckdb_query` blocked writes only by keyword substring, and every one could read any file or URL through DuckDB's table functions | Table and column names are looked up in the catalog (`information_schema`) and double-quoted; `having` is parsed into `<name> <op> <value>` conditions with bound values; `order_by` and directions are allowlisted; `duckdb_query` runs one parser-checked `SELECT`/`EXPLAIN` statement; the data files are copied into an in-memory sandbox whose external access is disabled and configuration locked. | `sajha/tools/impl/duckdb_olap_tools_refactored.py`, `sajha/olap/sql_safety.py` |
| Invalid credentials on `/mcp`, `/mcp/ws` and `POST /a2a` were treated as no credentials, so a mistyped or expired key ran with the anonymous policy | Credentials that are sent but do not authenticate get 401 (`invalid_token`; on A2A a JSON-RPC `-32001` error; on WebSocket close code 1008), in every `mcp.auth.mode`. | `sajha/auth/oauth/resource_server.py` (`presented_credentials`), `sajha/routes/a2a_routes.py`, `sajha/routes/ws_routes.py` |
| The REST mirrors of MCP methods (`POST /api/resources/list`, `/api/resources/read`, `/api/completion/complete`) needed no credentials | They require sign-in and apply the caller's tool and resource access. | `sajha/routes/mcp_routes.py` |
| An API key with an expiry date failed on SQLite (naive and aware datetimes compared) | Naive expiry times are read as UTC. | `sajha/db/dao/__init__.py` |
| `sajha://data/*` resources (the server's data files) were listed and readable by anonymous callers | Anonymous callers see and read only URIs matching `mcp.anonymous.resources` (default none) in `resources/list` and `resources/read` (both eras); a hidden file is "Resource not found". `/api/resources/*` use the same reader and policy. | `sajha/auth/access.py` (`can_read_resource`), `sajha/core/data_resources.py` |

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

The Studio pages (`/studio/*`), the actions they post to (`/admin/studio/*`: analyze, preview, deploy, delete, Describe a tool, Import an API), the `/api/studio/*` reads and creating composites need Studio access: the admin role or a role with the `studio` permission, such as the seeded `developer` (`require_studio` in `sajha/auth/__init__.py`). API keys never have it. A deploy writes the generated files and loads the tool into the live registry. A developer can deploy and delete Studio tools (Describe a tool proposals included, through the same policy-engine gate as an administrator, so a `studio.deploy` rule can deny or `require_approval`), sees only their own Describe drafts, and changes or deletes only the composites they created. Admin only: deploying a Python code or script tool while `sandbox.enforce_for_generated_tools` is `false` (the code would run in-process), sandbox configuration, and everything outside Studio (federation, connectors, policies, approvals, audit, users, API keys). Delete refuses tools Studio did not create, for everyone.

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

### Connected accounts

Users' tokens for third-party services (GitHub, Slack, Google, Microsoft 365, ...) are
AES-256-GCM ciphertext in `connected_accounts`, keyed outside the database
(`SAJHA_ACCOUNTS_VAULT_KEY` or the secrets file), bound to their user and provider, sent
only to the provider's `api_hosts`, never logged or shown, not even to administrators. The
flow uses a single-use `state` bound to the user and the browser, PKCE where the service
supports it and an exact redirect URI; Connect and Disconnect are CSRF-protected POSTs.
Threat table and audit events: [Connected Accounts §10](../architecture/Connected%20Accounts.md#10-security).

### Other features that need care

- **Async execution.** `POST /api/tools/{tool}/execute-async` (`sajha/routes/ops_routes.py`, `sajha/core/async_executor.py`) needs the admin role or a permission row (`async`, `*`, `execute`), plus execute access to the tool. Destinations are checked when the task is submitted (400 when refused) and again at delivery:
  - **file**: a relative path inside `async.delivery.file.base_dir` (no absolute paths, no `..`, no symlink target); written atomically.
  - **webhook**: the URL must match an entry of `async.delivery.webhook.allowed_urls` (same scheme, host and port, path at or under the entry's path; no credentials in the URL). Empty list (the default) refuses webhooks. The host is resolved once per attempt and every address vetted with the CIMD SSRF guard (`address_allowed` in `sajha/auth/oauth/clients.py`): public addresses only unless `async.delivery.webhook.allow_private_networks` is true (link-local such as cloud metadata stays refused). The request goes to the vetted IP, with no redirects and no proxy environment. Custom headers cannot set `Host` or framing headers.
  - **kafka**: a topic name (`[A-Za-z0-9._-]`, at most 249 characters).
  - Non-admins list, read, cancel and retry only their own tasks.
- **A2A.** `POST /a2a` (`sajha/routes/a2a_routes.py`) authenticates like the REST API; without credentials it applies the anonymous policy, or answers 401 when `mcp.anonymous.enabled` is false. It runs the first tool whose name appears in the message text, with empty arguments, only if the caller may execute it; otherwise the task fails with "Access denied". `tasks/get` and `tasks/cancel` see only the caller's own tasks (admins see all).
- **Federation.** Upstream MCP servers' tools are registry tools under the same tool access. Upstream URLs pass an SSRF guard, upstream descriptions are screened for prompt injection, new and changed tools wait for an admin's approval by default, stdio upstreams are off unless `federation.allow_stdio` is on, and every federation route is admin-only and audited. Details: [Federation](../architecture/Federation.md#9-security).
- **Intelligence layer.** Ask SAJHA (`POST /api/ai/ask`) runs tools only from a shortlist the caller may run, through the same tool-access check as `POST /api/tools/execute`; destructive tools need confirmation; tool output is passed to the model as data. Role policy and daily token budgets limit model use (`ai.policy.*`, `ai.budgets.*`). Provider keys are referenced (`env:`, `file:`, `db:`), never stored in `config/application.yml`, and redacted from the effective configuration. The `sajha_ask` MCP tool (off by default) runs its inner calls as the MCP caller, limited to the caller's tool access and, when set, to `ai.ask.mcp_allowed_tools`; composite steps likewise run as the caller, so a tool never gives a caller more than the caller has ([Inner calls](#inner-calls)). Details: [Intelligence Layer](../architecture/Intelligence%20Layer.md).
- **Metrics.** `GET /metrics` is admin-only by default (`observability.metrics.auth`: `admin`, `token` or `none`), and user IDs and key names are never metric labels. Alert webhooks pass the same SSRF guard as async webhooks. Details: [Observability](../architecture/Observability.md).
- **DuckDB SQL.** `duckdb_sql` (`DuckDBSQLTool` in `sajha/tools/impl/duckdb_olap_advanced.py`) runs exactly one statement, which DuckDB's parser must classify as `SELECT` (including `WITH`, `FROM`-first, `DESCRIBE`, `SHOW`, `SUMMARIZE` and `PRAGMA` queries) or `EXPLAIN`. Its connection is in-memory, holds copies of the three CSV files, and has external access disabled and its configuration locked, so a query cannot read or write files or URLs, `ATTACH`, `COPY` or `INSTALL`. The other `duckdb_*` tools (`duckdb_olap_tools_refactored.py`) share one sandbox of the same kind per data directory (`DuckDbSandbox`: every data file copied in, then external access disabled and locked; a reload builds a new one). `duckdb_query` applies the same one-statement check (`read_only_sql` in `sajha/olap/sql_safety.py`); `duckdb_describe_table`, `duckdb_get_stats`, `duckdb_aggregate` and `duckdb_refresh_views` accept only table and column names found in the catalog, which they quote, and bind values.
- **OLAP tools.** The semantic-layer tools (`olap_*`, `customer_olap_pivot`) never put caller text into SQL: values are bound parameters and names must be declared in `config/olap/` (`sajha/olap/sql_safety.py`). The dataset, dimension and measure expressions in `config/olap/*.json` are SQL and are trusted as configuration.

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
| **Risky features** | Keep `shell.enabled`, `mcp.conformance_fixtures`, `mcp.auth.builtin.dynamic_client_registration` and `federation.allow_stdio` off unless needed. Review `config/plugins`. |
| **Metrics** | Keep `observability.metrics.auth` at `admin` or `token` (token in `SAJHA_OBSERVABILITY_METRICS_TOKEN`), or serve `/metrics` on a private `observability.metrics.port`. |
| **User code** | Run on Linux (or in a container) where Studio code and script tools matter, and check `GET /api/sandbox/status` for what the host enforces; set `sandbox.strict` to refuse to run without full confinement. |
| **More than one process** | Set `state.backend` to `redis` or `database`. With the default `memory`, OAuth pending requests, codes, refresh tokens and DCR registrations, MCP sessions, tasks and rate-limit counters are per process: rate limits multiply by the number of processes, and a restart signs out every OAuth client. Every process must share the JWT secret, the session secret and the OAuth signing key ([Scaling and State](../architecture/Scaling%20and%20State.md)). WebSocket sessions are always per connection. |
| **Logs** | WebSocket credentials travel in the query string. Make sure proxy access logs do not keep them. |

---

## 7. Audit logging

Audit entries go to the `audit_log` table, through `AuditDAO.log` (`sajha/db/dao/__init__.py`) and `AuditLogger.log` (`sajha/core/audit.py`). Admins can read them with `GET /api/audit` (`sajha/routes/ops_routes.py`) and `GET /api/reports/audit` (`sajha/routes/reporting_routes.py`).

Every `AuditLogger.log` event, and every policy decision other than a plain allow, is also a record in the tamper-evident hash chain (`audit_chain`, with RS256-signed anchors in `audit_anchors`), which `python -m sajha.audit verify` and the Audit page (`/admin/audit`) check, and which can be streamed to a SIEM. Declarative policy rules on tool calls (deny, approval, argument constraints, rate limits, quotas, redaction, injection screening) sit on top of the tool access rules above. Both: [Policy and Audit](../architecture/Policy%20and%20Audit.md).

These events are written today:

| Event | Source |
|---|---|
| `user.login`, `user.login_failed` | `sajha/auth/__init__.py` |
| `user.password_change`, `user.password_reset` | `sajha/routes/auth_routes.py` |
| `user.create`, `user.enable`, `user.disable`, `user.delete` | `sajha/routes/api_routes.py` |
| `tool.enable`, `tool.disable`, `tool.config_update` | `sajha/routes/api_routes.py` |
| `apikey.create`, `apikey.rotate`, `apikey.revoke`, `apikey.enable`, `apikey.disable`, `apikey.access`, `apikey.persistent`, `apikey.assign_owner`, `apikey.delete` | `sajha/auth/apikeys.py` |
| `user.sessions_revoked` (with the reason) | `sajha/auth/revocation.py` |
| `shell_execute_python`, `shell_execute_bash` (with outcome and a code preview) | `sajha/core/shell_executor.py` |
| `config_change` with resource `federation.<change>` (add, edit, remove, approve, ...) | `sajha/routes/federation_routes.py` |
| `ai_ask` (question, tools, models, tokens, outcome, confidence; off with `ai.ask.audit: false`) | `sajha/ai/intelligence.py` |
| `snapshot.written`, `snapshot.rotated`, `snapshot.failed`, `snapshot.restored` | `sajha/snapshots/` |

These go elsewhere:

- **Tool runs** through `POST /api/tools/execute` go to the tool-usage table (`ToolUsageDAO.log_execution`), with the user, auth type, duration, client IP and an argument hash.
- **Account locks and OAuth code issuance** go only to the application log.

The convenience methods in `sajha/core/audit.py` for `login_failed`, `logout`, `account_locked` and `permission_change` exist but are not called; `config_change` is used only by federation. The table records the IP address only when a caller supplies it, and the current callers don't.

---

## 8. Known limitations

These describe the code as it stands. They are listed so you can compensate for them in deployment. Limits that belong to one feature are in its owner's limits section: [Policy and Audit](../architecture/Policy%20and%20Audit.md#11-limits), [Sandbox](../architecture/Sandbox.md#9-limits-and-future-work), [Data Connectors](../architecture/Data%20Connectors.md#14-limits-of-this-design), [Federation](../architecture/Federation.md#12-limits), [Connected Accounts](../architecture/Connected%20Accounts.md#10-security), [Tool Generation](../architecture/Tool%20Generation.md#8-limits).

**Authorization gaps**

- **Prompts have no per-user permissions.** Every signed-in caller sees every prompt; only anonymous callers are filtered (`mcp.anonymous.prompts`).
- **Data file resources have no per-user permissions.** `sajha://data/{file}` is readable by every signed-in caller, whatever their tool access (an API key limited to `calc_*` can still read the CSVs); only anonymous callers are filtered (`mcp.anonymous.resources`). Resources of federated upstream servers are not filtered by this policy.
- **OAuth scopes** (`mcp:read` / `mcp:tools`) gate methods, not individual tools; tool access then applies on top.
- **Studio access is all-or-nothing.** The `studio` permission opens every creator (code, script, REST, DB query, enterprise sources, Describe a tool, Import an API); it cannot be narrowed to some of them, and a developer can delete any Studio-generated tool, not only their own. Generated Python code and scripts are sandboxed; the template creators run in-process with the server's configured credentials.

**Brute force and sessions**

- **Account lockout can be triggered by anyone who knows a user ID** (a deliberate trade-off against password guessing); the lock expires after `auth.login.lockout_minutes`, and an admin password reset clears it.
- **Sign-out reaches other workers only through a shared state store.** With `state.backend: memory`, a signed-out token is refused only by the process that handled the sign-out until it expires; sign out everywhere (the token version) works on every worker. A state-store outage skips the signed-out check.

**Missing account features**

- **No SSO for the web UI.** No login path uses an external identity provider; the `oauth_provider` / `oauth_subject` user columns are unused. OAuth 2.1 applies only to the MCP endpoints.

**Process-local state**

- **Rate limits and OAuth state are per process with `state.backend: memory`** (the default); use `redis` or `database` to share them.
- **MCP sessions** record the user but are not re-checked against the caller on later requests. The session ID (a random UUID) acts as a bearer capability.

**Sandboxing**

- **Sandbox strength depends on the host.** Studio code and script tools and the shell run in the sandbox; on Linux it confines files, network and processes, on macOS and Windows it does not (only a clean environment and limits). The `subprocess` and namespace backends share the host kernel; use the `docker` backend with gVisor where kernel exploits are in scope. Host-name allowlisting is library-level (see [Sandbox](../architecture/Sandbox.md)).

**Headers and transport**

- **CSP allows `'unsafe-inline'`** for scripts and styles.
- **The request size limit** relies on `Content-Length`.
- **The WebSocket transport** does not check `Origin`.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
