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
| `Secure` | `auth.cookie.secure`: `auto` (default: when the request scheme is `https`; behind a TLS proxy set `server.trusted_proxies` so the scheme is seen), `true` or `false` |
| `Path` | `/` |
| `Max-Age` | `auth.jwt.expiry_minutes` × 60 seconds |

- **Session rotation.** Every sign-in (password form, single sign-on) first signs out the session the browser already held, if any, and then sets a new token (`start_session` in `sajha/routes/auth_routes.py`), so a token planted in or left on a browser never outlives a sign-in. Tokens are only ever issued after authentication, so there is no pre-login session to fix.
- **CSRF.** Two layers protect cookie-authenticated changes: SameSite=Lax, and the cross-site check that refuses any state-changing request carrying the cookie from another site ([Cross-site requests](#cross-site-requests-csrf)). Many console forms and APIs also carry a CSRF token bound to the session (API keys, credential files, policies, notices, quality, connected accounts, the OAuth consent form).

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

### Credential storage and files

> **Warning: owner decision for intranet use.** `auth.credential_storage` defaults to `plain`:
> passwords and API keys are stored as given (no hashing), so anyone who obtains a copy of the
> database, a backup or the credential files can sign in as any user. A warning System Notice shows
> while it is on. To harden: set `auth.credential_storage: hashed` and run
> `python -m sajha.auth rehash` (passwords become bcrypt, raw API key values are removed; values
> stored either way keep working across the switch).

Three files sit beside the database, all git-ignored and readable only by the server's user:

| File | Written by | Holds | Precedence |
|---|---|---|---|
| `config/users.json` | administrators (Admin > Users > Users file, or by hand) | users: ID, name, email, password, roles, enabled, `test_admin` | Wins: applied to the users table at start-up and whenever the file changes; edits to those users elsewhere are overwritten. Never written from the database. |
| `config/apikeys.json` | administrators (Admin > API keys > Keys file, or by hand) | API keys as raw `key` values (older records may hold a `sha256`), owner, roles, enabled, expiry, tool access, `test_admin` | Wins: checked before the database for every key. |
| `config/apikeys_db.json` | SAJHA, every `auth.api_keys.db_dump_interval_minutes` (default 10) | every database key (raw under plain storage, else its hash) | Last: used only when the database does not know a key or cannot be reached. |

**Test admin (development and testing only).** Records marked `"test_admin": true` in
`config/apikeys.json` and `config/users.json` sign in as an administrator while
`sajhanet.test_admin_key.enabled` is on (default on for now; a critical notice shows on every page).
The shipped development key is `sja_test_admin_dev_key_0001` and the account `testadmin` /
`testadmin-dev-1` (see the `.example` files). While it is on, SAJHA Net calls from this server carry
the test admin key; a host accepts it only if its own `config/apikeys.json` has the same record and
its own switch is on. Every use is audited. Disable it before production.

**Keys toward particular members.** `sajhanet.peer_keys` (local to each server, never shared) maps
`<net>/<instance>` or `<instance>` to a key that member issued; calls to that member carry it in
place of the caller's key or the test admin key.

### Console single sign-on

The console can sign people in with an OpenID Connect identity provider (`sajha/auth/sso.py`, routes in `sajha/routes/sso_routes.py`). It is **off** unless `auth.sso.enabled` is true and `auth.sso.issuer` and `auth.sso.client_id` are set, and it works **alongside** the other sign-ins: the users file, database users, password login and API keys are unchanged. The login page then shows "Sign in with `auth.sso.label`" above the password form.

- **Flow.** `GET /auth/sso/login?next=/path` reads the provider's OpenID Connect discovery document (under `<issuer>/.well-known/`; its `issuer` must match), keeps a random `state`, `nonce` and PKCE verifier in the [state store](../architecture/Scaling%20and%20State.md) for ten minutes, sets the `sajha_sso` cookie (HttpOnly, SameSite=Lax, path `/auth/sso`) that binds them to this browser, and redirects to the authorization endpoint with `response_type=code`, `code_challenge_method=S256` and `auth.sso.scopes` (always including `openid`). `GET /auth/sso/callback` takes the state (once; another browser, a replay or an expired state is refused), exchanges the code at the token endpoint with the verifier and the client secret (`client_secret_basic`, or `auth.sso.token_auth: client_secret_post`; a public client without a secret sends PKCE only), and validates the ID token: an asymmetric signature (RS, PS or ES family; `none` and HMAC are refused) by a key of the provider's JWKS, `iss`, `aud` (and `azp` when there are several audiences), `exp`, `iat` (`auth.sso.clock_skew_seconds` leeway, default 60), `sub`, `nonce`, and `at_hash` when present. The provider's endpoints must be `https` (plain `http` only on localhost). Failed callbacks count toward the per-IP failed sign-in limit and are audited as `user.login_failed`.
- **Which SAJHA user.** First the account linked to this provider and subject (`users.oauth_provider` = `auth.sso.provider_name`, default `oidc`, and `users.oauth_subject` = `sub`). Otherwise the user ID named by the claim `auth.sso.user_claim` (default `preferred_username`; with `email`, an `email_verified: false` address is refused): an existing account is linked on first sign-in when `auth.sso.link_existing` is true (the default; audited `user.sso_linked`), unless it is already linked to another subject. Without an account, `auth.sso.auto_provision` (default false) creates one with an unusable random password and a default API key (audited `user.create`); else the sign-in is refused. A disabled account is refused.
- **Roles.** `auth.sso.roles_claim` names a claim (a list or a space-separated string; dotted names reach nested claims such as `realm_access.roles`), and `auth.sso.role_map` maps its values to SAJHA roles (`["sajha-admins=admin", "staff=user"]`; only existing roles are granted). A created user gets the mapped roles, or `auth.sso.default_roles` (default `user`) when none apply. `auth.sso.sync_roles` (default false) replaces an existing user's roles with the mapped ones at each sign-in, except for users defined in `config/users.json`, whose file always wins. `auth.sso.require_role` refuses a sign-in that maps to no role.
- **Session.** A successful callback starts the same session as a password sign-in: a SAJHA JWT in the `sajha_token` cookie (with `amr: ["sso"]`), audited as `user.login` with the method. Everything after that (tool access, revocation, sign out everywhere) is as described on this page.
- **Sign-out.** `GET /logout` (and `POST /api/auth/logout`, which returns the URL as `idp_logout_url`) revokes the SAJHA token and, for a session single sign-on started, redirects to the provider's `end_session_endpoint` with `id_token_hint`, `client_id` and `post_logout_redirect_uri=<this server>/login` (`auth.sso.idp_logout`, default true). A password session signs out locally only.
- **Several instances, one sign-in.** Instances of a SAJHA Net that are clients of the **same** provider share one sign-in: a person who signed in at the provider for one instance is signed in to the next instance's console without a password prompt, and with `auth.sso.auto_redirect` that instance's `/login` goes straight to the provider (`/login?local=1` still shows the password form). Each instance still maps the person to **its own** user, as SAJHA Net keeps users per instance ([SAJHA Net](../architecture/SAJHA%20Net.md#113-users-across-instances)). This design was chosen over one SAJHA instance acting as the identity provider for the others: the shared provider needs no new trust between instances and no SAJHA OpenID Provider (ID tokens, consent, key rotation, its own availability), and it keeps each instance's console usable when any other instance is down.
- **Redirect URI.** `auth.sso.redirect_uri`, default `<mcp.auth.public_url or the request's origin>/auth/sso/callback`; register it with the provider for each instance. The client secret comes from the environment (`SAJHA_AUTH_SSO_CLIENT_SECRET`), never from `config/application.yml`.
- `GET /api/auth/sso` (public) answers whether single sign-on is on, its label and its login URL.

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

The OpenAI-compatible routes (`/v1/*`) use their own order (`authenticate` in `sajha/ai/openai_api.py`):
`Authorization: Bearer sja_...` as an API key, any other bearer as a SAJHA JWT, then `X-API-Key`;
the cookie only when `ai.openai_api.cookie_auth` is on, since an OpenAI-style POST carries no CSRF token.

### Roles and permissions

The seed data in `db/scripts/<type>/seed.sql` creates these roles and permission rows:

| Role | Permission rows (`resource_type`, `resource_name`, `actions`) |
|---|---|
| `admin` | `*`, `*`, `*` |
| `user` | `tool`, `*`, `execute,read` |
| `viewer` | `tool`, `*`, `read` |
| `developer` | `studio`, `*`, `*` and `tool`, `*`, `execute,read,create` |
| `llm_author` | `studio`, `llm`, `use` and `tool`, `*`, `execute,read` |

How these rows are used:

- **Matching.** `PermissionDAO.check_access` (`sajha/db/dao/__init__.py`) matches `resource_name` with fnmatch wildcards.
- **Admin check.** `User.is_admin` is true when the user has the `admin` role. Admin-only routes use `require_admin`.
- **Other resource types.** Async execution needs the admin role or a permission row (`async`, `*`, `execute`); the shell endpoints need the admin role or (`shell`, `*`, `execute`); each MCP Studio creator needs the admin role or (`studio`, `<creator>` or `*`, `*` or `use`): `studio:*` (the seeded `developer` role) opens every creator, `studio:llm` (the seeded `llm_author` role) only the LLM tool creator (`require_creator`; [MCP Studio](#mcp-studio) below).

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

The WebSocket endpoint `/mcp/ws` applies the same check before it accepts the upgrade and closes a disallowed Origin with 1008 (`sajha/routes/ws_routes.py`).

### Security headers and CSP

`SecurityHeadersMiddleware` (`sajha/security.py`, registered in `sajha/app.py`) adds these headers to every response:

| Header | Value | Overridable by a route |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | no |
| `X-Frame-Options` | `SAMEORIGIN` | yes |
| `X-XSS-Protection` | `0` (the legacy XSS auditor is off; the CSP protects) | no |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | yes |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | yes |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'nonce-<per response>'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'` | yes |
| `Strict-Transport-Security` | `max-age=<security.hsts.max_age>` (default 31536000) plus `; includeSubDomains` (`security.hsts.include_subdomains`, default true), only when the request scheme is `https`; `max_age: 0` sends none | no |

- **Nonces.** Every response gets a fresh random nonce (`csp_nonce` in `sajha/security.py`, a Jinja global). Each inline `<script>` in the templates carries `nonce="{{ csp_nonce() }}"`; any other inline script, injected or not, is refused by the browser. Data blocks (`<script type="application/json">`) are never run and carry none.
- **No inline event handlers.** `script-src-attr 'none'` refuses `onclick=` and its kind. Console pages write handlers as `data-onclick`, `data-onchange`, `data-onsubmit` (and `dblclick`, `input`, `keydown`, `keyup`), run by `sajha/web/static/js/csp-actions.js`. It does not evaluate script: a handler is a short program of calls to functions the page itself declares (never a browser built-in such as `eval`, except `confirm`) with literal, `this` or `event` arguments, and `return false` cancels the default action. So an attribute injected into a page can only call the page's own functions. `tests/test_csp_handlers.py` keeps the templates free of inline handlers and un-nonced scripts and checks every handler against the grammar; `scripts/check_mobile.py` fails a page that reports a CSP violation, keeps an inline handler, has a handler that would not run or throws a script error.
- **Styles** keep `'unsafe-inline'`: style attributes are used throughout the templates and by the vendored libraries, and CSS cannot run script.
- The overridable headers are applied with `setdefault`, so a stricter value set by a route is kept: the OAuth consent page sends `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and the same CSP with `frame-ancestors 'none'`. All JS, CSS and fonts are vendored under `/static/vendor`.

One route family sets its own policy: the Python Playground. `/playground` adds `worker-src 'self'`
and sends `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`
(cross-origin isolation, for the Stop button's `SharedArrayBuffer`); its worker script,
`/api/playground/worker.js`, is the only response whose CSP allows `'wasm-unsafe-eval'`, plus the
Pyodide CDN when `playground.assets` is `cdn` and PyPI when `playground.allow_pypi` is true. The page
itself uses the console policy above (nonces, no inline handlers) with `blob:` images.
User code runs only in the browser; its tool calls are ordinary API requests under the user's
session. Details: [Python Playground](../getting-started/Python%20Playground.md#security).

### CORS

`CORSMiddleware` (`sajha/app.py`) allows the origins in `SAJHA_CORS_ORIGINS` (comma-separated). The default is `http://localhost:3002`, `http://127.0.0.1:3002` and `http://0.0.0.0:3002`. It sets `allow_credentials=True` with all methods and headers allowed, and exposes `Mcp-Session-Id`. Set `SAJHA_CORS_ORIGINS` to your real UI origins in production.

### Cross-site requests (CSRF)

`CrossSiteRequestMiddleware` (`sajha/security.py`) refuses with 403 every `POST`, `PUT`, `PATCH` or `DELETE` that carries the `sajha_token` cookie and was sent from another site: the browser's `Origin` (or, without one, the `Referer`'s origin) must be the host the request was sent to, the origin of `mcp.auth.public_url`, an origin in `SAJHA_CORS_ORIGINS` or one in `security.csrf.trusted_origins`. `Origin: null` is refused. A request without either header passes, since browsers always send `Origin` on a cross-site POST; requests without the cookie (API keys, bearer tokens, SAJHA Net) are not affected. It runs before `/sajhanet/` loses its `Origin` header. The MCP endpoints (`/mcp`, `/api/mcp`) keep their own [Origin allow-list](#origin-allow-list-for-mcp). Behind a proxy that rewrites `Host`, set `mcp.auth.public_url` (or `security.csrf.trusted_origins`) to the public origin. `tests/test_browser_hardening.py` enumerates every state-changing route of the app and checks that each refuses a cross-site cookie request.

### Request size

`RequestSizeLimitMiddleware` (`sajha/security.py`) answers 413 when a request body exceeds `server.max_request_bytes` (default 10 MB): at once when the `Content-Length` says so, and while the body is read when it is streamed without one (chunked).

### Hosts, proxies and TLS

- **Allowed hosts.** `security.allowed_hosts` (exact names or `*.example.com`; empty, the default, allows any) makes `AllowedHostsMiddleware` answer 400 to any other `Host` header (and close a WebSocket with 1008), a defence against DNS rebinding and host-header poisoning. `localhost`, `127.0.0.1` and `[::1]` always pass, so local tools and health checks keep working.
- **Trusted proxies.** `server.trusted_proxies` is passed to uvicorn as `forwarded_allow_ips`: only those proxies' `X-Forwarded-For` and `X-Forwarded-Proto` are believed (empty: uvicorn's default, `FORWARDED_ALLOW_IPS` or `127.0.0.1`). It decides the client address of the per-IP limits and whether a request counts as `https` (HSTS, `Secure` cookies).
- **TLS.** SAJHA can serve https itself with `server.tls.certfile` and `server.tls.keyfile` (`sajha/core/transport.py`, used by `run_server.py`); the floor is `server.tls.min_version` (`TLSv1.2`, the default, or `TLSv1.3`) with TLS compression off. With `--workers` or `--reload` the floor is TLS 1.2 whatever the setting. Most deployments terminate TLS at a proxy instead.
- **Outbound timeouts.** Every outbound HTTP call (`urlopen`, `requests`, `httpx`) outside `sajha/net/` passes a timeout; `tests/test_browser_hardening.py` checks the source.

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

Behind a reverse proxy the per-IP limits need the real client address: uvicorn takes it from `X-Forwarded-For` only when the proxy is in `server.trusted_proxies` (or `FORWARDED_ALLOW_IPS`; default `127.0.0.1`).

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

Studio access is per creator (Roadmap X2; `require_creator`, `can_use_creator` in `sajha/auth/__init__.py`). A role permission with resource type `studio` names the creator it opens: `studio:python`, `studio:rest`, `studio:api_import`, `studio:dbquery`, `studio:script`, `studio:powerbi`, `studio:powerbidax`, `studio:livelink`, `studio:sharepoint`, `studio:olap`, `studio:composite`, `studio:describe` or `studio:llm`; `studio:*` opens all of them and is what the single `studio` permission always meant, so existing roles keep their access (permissions are data: no migration). Each creator's page, its `/admin/studio/<creator>/…` actions and its `/api/studio/<creator>/…` reads check its permission; a Describe a tool deploy also needs the permission of the kind deployed, so `studio:describe` cannot be used to reach a creator the role lacks. The planner editor is admin only for every role, because a planner decides how much every tool that uses it may spend. API keys never have Studio access.

**Ownership.** A deploy records its creator: `metadata.created_by` in the tool config (with `metadata.studio_creator`), `created_by` on a composite and in an API import record, `created_by_user` on an OLAP dataset (`sajha/studio/ownership.py`). A non-admin may change or delete only what records them; a tool with no recorded creator (shipped tools, tools made before this) is the administrators'. Delete still refuses, for everyone, tools Studio did not create. A deploy writes the generated files and loads the tool into the live registry. A developer can deploy Describe a tool proposals through the same policy-engine gate as an administrator (a `studio.deploy` rule can deny or `require_approval`) and sees only their own Describe drafts. Admin only: the planner editor, deploying a Python code or script tool while `sandbox.enforce_for_generated_tools` is `false` (the code would run in-process), sandbox configuration, and everything outside Studio (federation, connectors, policies, approvals, audit, users, API keys).

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
- **SAJHA Net.** Off by default (`sajhanet.enabled`); off, every `/sajhanet/` path answers a bare 404. On, the `/sajhanet/v1/` endpoints share the normal port but take no session, cookie or API key: every request and response between participants is signed (RFC 9421, Ed25519 or ECDSA P-256, with an RFC 9530 body digest) by a key whose certificate must chain to the net's CA, name the net in its `O` and the sender in its `CN`, and not be on the CA-signed revocation list; the request must be at most `sajhanet.signature_max_age_seconds` old (never more than 300 s), addressed to this server, and carry a nonce not seen before (kept in the state store for the window, so a replay to another worker fails too). A request for a net this server is not in, without a net header, or from a browser navigation gets the same bare 404 as a server with SAJHA Net off, and the responses carry no CORS headers. A name belongs to its certificate lineage: a different key claiming a held name is refused with `409 name_conflict` and the refused server stops joining until its configuration or certificate changes. Member records are signed by their subjects, whose certificate must name the record's URL host, so no relay can redirect a member; ping-req targets are member names, never URLs. Keys are files with owner-only permissions (`sajhanet.data_dir`, git-ignored); the CA key never leaves the CA instance; enrollment tokens are single use, short-lived, bound to one name, stored as hashes, accepted only over HTTPS and rate-limited per address, and every refusal looks the same. Adding a peer by address is admin-only, passes the SSRF rules (`sajhanet.allowed_networks`; loopback and link-local never), is rate-limited and audited, and stores nothing on failure. Mutual TLS is not used. **Users across instances** (identity `api_key`, `sajhanet.user_identity`): a forwarded call carries the caller's own API key in `Sajha-Net-Api-Key` (the key presented on this request, or a console user's default key decrypted from the vault), only to the host of the call and only over HTTPS (`require_https`). The raw key lives only in memory for the request (`sajha/auth/presented_key.py`): it is never logged, stored, traced or audited, which records the key id and prefix instead. The host hashes it and looks it up in its net key directory (`sajhanet_api_keys`: each home's signed key records, synced by version and digest; hashes only), and refuses it unless it is enabled, unexpired, not revoked, from a home still in the net, and sent by that home (`key_not_from_home`), so a key enters the net only through the instance that issued it and a key disabled or deleted there stops working everywhere at once. A record arriving from anyone but its home, or not signed by the home's current certificate, is ignored; records signed by a revoked certificate are discarded. A net request that also carries `Authorization` or `X-API-Key` is refused. The host never trusts the home's view of the user: it maps the user itself (an explicit link, then the same login name, else refused, or with `users.unknown: map_roles` a guest identity with mapped roles), applies its own roles, export rules, the key's tool access as a ceiling, its own access rules and policy engine (source `sajhanet`), and records the call in its own audit chain under the shared trace id. Remote administrators act as administrators only with `users.remote_admin: admin` (the default, for a trusted net); blocks, links, role maps and name matching are changed only by an administrator signed in to the instance (the admin API refuses a caller that arrived through the net). Blocks (an instance entirely, inbound, outbound, a tool, a remote user) take effect on the next request, are audited, may expire, and are published signed so other consoles can show them; only the instance that set a block enforces it. A compromised member sees the keys forwarded to it, so the `api_key` identity is for nets whose members are trusted (design §10.2). **Without a key in transit** (`user_identity: assertion` or `token_exchange`, per net): with `assertion` the home sends a user assertion signed with its net certificate that names the user, the id of one of their keys in the net key directory, the audience host and the trace id, valid at most 60 seconds; the host verifies the signature against the issuer's certificate, the audience, the time, the trace id and the key record, and accepts each assertion once (`jti` kept in the state store), so a captured assertion cannot be replayed or used at another host. With `token_exchange` the home trades such an assertion at the host for an opaque host-scoped token bound to that home, which the host keeps only hashed and checks against the key record, blocks and mapping on every call; a token is never logged, stored on disk or forwarded. Neither carries per-member keys or the test admin key, which remain features of `api_key`. **Re-export** (off by default; on per net with `reexport` and only for tools a `reexport_rules` entry names): a re-exported call always carries an assertion addressed to the tool's origin, never a raw key; the intermediary verifies it and applies its own blocks, mapping, rules and access before relaying it unchanged; hop limits, the visited list (loops) and the combined call chain budget hold end to end, and a tool never comes back to its origin. A bridge between two nets calls into the other net only as one of its own local users, so nothing signed in one net is trusted in the other. Design and threats: [SAJHA Net](../architecture/SAJHA%20Net.md#18-threats-and-mitigations); the wire rules: [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md#19-security-considerations).
- **Intelligence layer.** Ask SAJHA (`POST /api/ai/ask`) runs tools only from a shortlist the caller may run, through the same tool-access check as `POST /api/tools/execute`; destructive tools need confirmation; tool output is passed to the model as data. Role policy and daily token budgets limit model use (`ai.policy.*`, `ai.budgets.*`). Provider keys are referenced (`env:`, `file:`, `db:`), never stored in `config/application.yml`, and redacted from the effective configuration. The `sajha_ask` MCP tool (off by default) runs its inner calls as the MCP caller, limited to the caller's tool access and, when set, to `ai.ask.mcp_allowed_tools`; composite steps likewise run as the caller, so a tool never gives a caller more than the caller has ([Inner calls](#inner-calls)). Details: [Intelligence Layer](../architecture/Intelligence%20Layer.md).
- **OpenAI-compatible endpoint.** `/v1/chat/completions`, `/v1/models` and `/v1/embeddings` (`sajha/routes/openai_routes.py`) are off unless `ai.openai_api.enabled` is true; turned off they answer 404. Every request needs a credential (no anonymous access), and the request's own `sajha` field can carry a conversation id or tool arguments but never an identity: the RequestContext is built from the AuthContext alone. Model use goes through the gateway as the caller, so role policy (`ai.policy`), budgets and the usage ledger apply; an unknown model and one the caller's role may not use both answer 404, so the endpoint does not reveal what exists. An LLM tool is a model (`sajha:<tool>`) only for callers who may execute that tool, and it runs through `execute_with_tracking` as the caller (tool access, policy, its own limits, audit). The policy engine sees each request as the pseudo-tool `openai_api.chat_completions` or `openai_api.embeddings` with source `openai_api`, so rules can deny or rate-limit the surface. Bodies over `ai.openai_api.max_body_bytes` are refused; each request writes an `openai_api.request` audit record. Details: [LLM Tools](../architecture/LLM%20Tools.md#134-sajha-as-an-openai-compatible-endpoint).
- **Planner files.** A planner (`config/planners/*.yaml`, [Planner Reference](../architecture/Planner%20Reference.md)) only proposes: every tool call it asks for goes through the same service path as a model's (the caller's shortlist, refusal of tools not offered, confirmation, policy, limits, audit), and every model call through the gateway bound to the caller. Files load with `yaml.safe_load`; `when` expressions are parsed into a tree over a fixed set of pure functions (no attribute access beyond data, no imports, no code); a planner cannot raise a limit above its ceiling, and every loop must cross a bounded edge. Planner files, `kind: python` planners and custom stage types are deployment configuration or code, so only administrators add them; a caller may choose a planner only among an LLM tool's `planner_choices`, enforced as an enum by argument validation. An `ask_user` pause is saved in the state store bound to the user and the planner version, behind the signed MRTR `requestState`. The dry run (`POST /api/ai/planners/dry-run`) is admin-only and runs only read-only tools unless the admin names others.
- **MCP sampling by LLM tools.** An LLM tool with `llm.sampling: prefer` or `require` sends its model call to the calling client (`sajha/ai/llm_tools/sampling.py`); only the MCP call's own tool does, never an inner call. The prompt it sends is the tool's own rendered prompt, so what the client's model sees is what SAJHA's would have seen; the client's answer is validated like a model's (schema, enum, rubric) and is treated as untrusted model output. On 2026-07-28 the answer comes back in `inputResponses` under the signed `requestState` (above). Details: [LLM Tools](../architecture/LLM%20Tools.md#12-models-sampling-budgets-and-limits).
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
| **HTTPS** | Terminate TLS at a reverse proxy (or set `server.tls.*`). The cookie `Secure` flag and HSTS depend on the request scheme. Uvicorn trusts `X-Forwarded-Proto` only from `server.trusted_proxies` (or `FORWARDED_ALLOW_IPS`; default `127.0.0.1`), so set that if the proxy is on another host, or set `auth.cookie.secure: true`. |
| **Origins** | Set `SAJHA_CORS_ORIGINS` and `mcp.allowed_origins` to the real browser origins. |
| **Hosts** | Set `security.allowed_hosts` to the names the server is reached by. |
| **Single sign-on** | When `auth.sso` is on, keep its client secret in `SAJHA_AUTH_SSO_CLIENT_SECRET`, register one redirect URI per instance, and decide `link_existing` and `auto_provision` for your provider ([Console single sign-on](#console-single-sign-on)). |
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
- **Studio template creators run with the server's credentials.** Per-creator permissions (`studio:<creator>`) and ownership narrow who builds what, but the template creators (REST, DB query, Power BI, LiveLink, SharePoint, OLAP) still run in-process with the server's configured credentials; generated Python code and scripts are sandboxed.

**Brute force and sessions**

- **Account lockout can be triggered by anyone who knows a user ID** (a deliberate trade-off against password guessing); the lock expires after `auth.login.lockout_minutes`, and an admin password reset clears it.
- **Sign-out reaches other workers only through a shared state store.** With `state.backend: memory`, a signed-out token is refused only by the process that handled the sign-out until it expires; sign out everywhere (the token version) works on every worker. A state-store outage skips the signed-out check.

**Single sign-on**

- **No back-channel sign-out.** Signing out at the identity provider or on one instance does not end SAJHA sessions other instances already issued; they last until they expire (`auth.jwt.expiry_minutes`) or are revoked there.
- **Linking by name trusts the provider.** With `auth.sso.link_existing` on, whoever the provider says is `alice` signs in as the local `alice`; turn it off, or link accounts deliberately, when the provider lets people choose their user names.

**Process-local state**

- **Rate limits and OAuth state are per process with `state.backend: memory`** (the default); use `redis` or `database` to share them.
- **MCP sessions** record the user but are not re-checked against the caller on later requests. The session ID (a random UUID) acts as a bearer capability.

**Sandboxing**

- **Sandbox strength depends on the host.** Studio code and script tools and the shell run in the sandbox; on Linux it confines files, network and processes, on macOS and Windows it does not (only a clean environment and limits). The `subprocess` and namespace backends share the host kernel; use the `docker` backend with gVisor where kernel exploits are in scope. Host-name allowlisting is library-level (see [Sandbox](../architecture/Sandbox.md)).

**Headers and transport**

- **Styles keep `'unsafe-inline'`** in the CSP; scripts do not.
- **`server.tls.min_version: TLSv1.3`** applies only in single-process mode.

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
