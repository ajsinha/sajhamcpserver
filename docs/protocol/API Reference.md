# SAJHA MCP Server: API Reference

This page lists every HTTP and WebSocket route the server registers, grouped by the module in `sajha/routes/` that defines it. All modules are included in `sajha/app.py` without an extra prefix, so the paths below are the full paths. These modules set a router prefix: `admin_routes.py` (`/admin`), `studio_routes.py` (`/studio` for pages, `/admin/studio` for actions), `api_import_routes.py` (`/studio`, `/admin/studio/api-import`, `/api/studio/api-import`) and `describe_routes.py` (`/studio`, `/admin/studio/describe`, `/api/studio/describe`); their paths are shown with the prefix applied. `tests/test_documentation_rot.py` fails when a registered route is missing from this page.

The examples assume the default address `http://localhost:3002` (`server.port`, env `SERVER_PORT`).

FastAPI also serves its generated docs: `GET /api/docs` (Swagger UI, with its OAuth helper page `GET /docs/oauth2-redirect`), `GET /api/redoc` and `GET /openapi.json`, all without authentication. Static assets are mounted at `/static`.

**Auth column legend** used throughout:

| Value | Meaning |
|---|---|
| none | No credential checked. |
| optional | Credentials are read if present (they change what is shown) but not required. |
| user | Any valid credential (`require_auth`): SAJHA JWT, `sja_` API key or the `sajha_token` cookie. |
| admin | A user with the admin role (`require_admin`). API keys never qualify: they authenticate with the `api_consumer` role and `is_admin = false`. |
| studio | MCP Studio access (`require_studio`): a user with the admin role, or whose role has the `studio` permission (resource type `studio`, actions `*` or `use`; the seeded `developer` role has it). API keys never qualify. |
| MCP | MCP transport rules: see [MCP endpoints](#2-mcp-endpoints). |

---

## 1. Authentication

### 1.1 Credentials for REST calls

`AuthManager.authenticate_request` (`sajha/auth/__init__.py`) tries these in order and uses the first that validates:

1. `Authorization: Bearer <jwt>`: a SAJHA login JWT (HS256, from `POST /api/auth/login`).
2. `X-API-Key: sja_...`: an API key (from `/account/apikeys` or `/admin/apikeys`).
3. `Authorization: sja_...`: the same API key sent bare in the `Authorization` header.
4. Cookie `sajha_token`: the JWT the web UI stores at login (`POST /login`).

An API key with an owner authenticates as that user, with the user's roles, and its `tool_access_mode` and tool list narrow what it may see and run; a key without an owner authenticates as `apikey:<key name>` with the single role `api_consumer`, and its mode and list alone decide, on REST, MCP and A2A alike ([API keys](../security/Security%20Model.md#api-keys)). SAJHA JWTs carry the user's roles and can be revoked ([Revocable sign-in](../security/Security%20Model.md#revocable-sign-in)). JWT lifetime is `auth.jwt.expiry_minutes` (env `JWT_EXPIRY`, default 60); the web cookie has a one-hour `max_age`.

**OAuth access tokens are not accepted on the REST API.** They are minted for the MCP resource and are validated only on the MCP endpoints (`sajha/auth/oauth/resource_server.py`); see [OAuth Guide](OAuth%20Guide.md).

```bash
# Bearer JWT
TOKEN=$(curl -s -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"admin","password":"admin123"}' | jq -r '.token')
curl -H "Authorization: Bearer $TOKEN" http://localhost:3002/api/metrics

# API key
curl -H "X-API-Key: sja_your_key_here" http://localhost:3002/api/metrics
```

(`admin`/`admin123` is the seeded account from `db/scripts/<dialect>/seed.sql`; change it.)

### 1.2 Auth routes (`auth_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | JSON login; returns a JWT and `password_change_required`. Too many failed sign-ins from one IP: 429; a locked account: 423 ([Security Model](../security/Security%20Model.md#web-login-and-passwords)). |
| GET | `/account/password` | user | Change-password page (also in the user menu). |
| POST | `/account/password` | user | Change-password form (`current_password`, `new_password`, `confirm_password`); sets a fresh cookie. |
| POST | `/api/auth/change-password` | user | `{"current_password", "new_password"}`; returns `{"success": true, "token": <new JWT>}`. Every other session of the user ends. Not for API keys. |
| POST | `/api/admin/users/{uid}/password` | admin | Reset a password: `{"password", "must_change_password": true}`; also unlocks the account and ends the user's sessions. |
| POST | `/api/auth/logout` | none | Revoke the presented SAJHA JWT (`Authorization: Bearer` or the cookie) until it expires; clears the cookie. `{"success": true, "revoked": true}`. |
| POST | `/api/auth/sessions/revoke` | user (not an API key; cookie callers send `X-CSRF-Token`) | Sign out everywhere: every SAJHA JWT and built-in OAuth token of the caller stops working, this one included. |
| POST | `/account/sessions/revoke` | user (form, CSRF) | The "Sign out everywhere" button on `/account/apikeys`; then redirects to `/login`. |
| POST | `/api/admin/users/{uid}/sessions/revoke` | admin (not an API key) | End every session of a user; returns the new `token_version`. |
| GET | `/login` | none | Login page (HTML). |
| POST | `/login` | none | Login form (`user_id`, `password`); sets the `sajha_token` cookie and redirects to `?next=` (local paths only) or `/dashboard`. Same throttle (429) and lockout (423) as the JSON login. |
| GET | `/logout` | none | Revokes the session token, clears the cookie, redirects to `/`. |
| GET | `/` | optional | Landing page, or redirect to `/dashboard` when signed in. |

`POST /api/auth/login` accepts the user id as `user_id`, `username` or `uid`:

```bash
curl -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"admin","password":"admin123"}'
```

```json
{"token": "eyJhbGciOiJIUzI1NiIs...", "user": {"user_id": "admin", "user_name": "Administrator", "roles": ["admin"]}}
```

Errors: 400 `{"error": "Missing credentials"}` (or a missing/non-object JSON body), 401 `{"error": "Invalid credentials"}`, 423 for a locked account, 429 when the caller's address is throttled.

---

## 2. MCP endpoints

Defined in `mcp_routes.py` and `ws_routes.py`. The protocol semantics (methods, capabilities, streaming, tasks, MRTR, subscriptions) are covered in [MCP Protocol Guide](MCP%20Protocol%20Guide.md); conformance detail is in [MCP 2026-07-28 Compliance](MCP%202026-07-28%20Compliance.md) and [MCP 2025-11-25 Compliance](MCP%202025-11-25%20Compliance.md). Header-level features (`x-mcp-header`, MCP Apps) are in [MCP Apps and Headers Guide](MCP%20Apps%20and%20Headers%20Guide.md).

**Authentication on MCP endpoints** (`authorize_mcp`): the REST credentials of section 1 always work. What happens without one depends on `mcp.auth.mode`:

| `mcp.auth.mode` | Anonymous request | OAuth bearer token |
|---|---|---|
| `off` (default) | allowed | not validated (only SAJHA JWTs are recognised) |
| `optional` | allowed | validated; invalid token gets 401 `invalid_token` |
| `required` | 401 with `WWW-Authenticate: Bearer resource_metadata="...", scope="..."` | validated; missing scope gets 403 `insufficient_scope` |

Every HTTP MCP route also rejects a disallowed browser `Origin` with 403 (`mcp.allowed_origins`).

| Method | Path | Purpose |
|---|---|---|
| POST | `/mcp`, `/api/mcp` | Streamable HTTP, both eras (below). |
| GET | `/mcp` | 405 for Streamable HTTP clients (no standalone server stream); legacy HTTP+SSE stream for clients that send neither `Mcp-Session-Id` nor `MCP-Protocol-Version`. |
| DELETE | `/mcp`, `/api/mcp` | End a 2025-11-25 session (`Mcp-Session-Id` required): 204, or 404 unknown session, 400 no header. A 2026-07-28 `MCP-Protocol-Version` header gets 405. |
| GET | `/mcp/sse` | Legacy 2024-11-05 HTTP+SSE stream. |
| POST | `/mcp/message` | Legacy 2024-11-05 message endpoint; returns the JSON-RPC response directly. |
| WebSocket | `/mcp/ws` | JSON-RPC over WebSocket text frames. |

`GET /api/mcp` is not registered (404).

### 2.1 `POST /mcp`: 2026-07-28 (stateless)

A request whose `params._meta` carries `io.modelcontextprotocol/protocolVersion` is served statelessly: no `initialize`, no session, `Mcp-Session-Id` ignored. `_meta` must also carry `io.modelcontextprotocol/clientCapabilities`, and the `MCP-Protocol-Version`, `Mcp-Method` and (for `tools/call`, `prompts/get`, `resources/read`, ...) `Mcp-Name` headers must match the body.

```bash
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -H "MCP-Protocol-Version: 2026-07-28" -H "Mcp-Method: tools/call" -H "Mcp-Name: calc_loan_amortization" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"calc_loan_amortization",
       "arguments":{"principal":250000,"annual_rate":6.5,"months":360},
       "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

### 2.2 `POST /mcp`: 2025-11-25 and earlier (sessions)

Everything else follows the handshake era: `initialize` returns an `Mcp-Session-Id` response header, which the client sends on later requests (unknown id: 404). Notifications and client responses get 202 with no body; JSON-RPC batches get 400 / `-32600`.

```bash
# initialize: note the Mcp-Session-Id response header
curl -i -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"my-agent","version":"1.0"}}}'

# call a tool in that session
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -H "Mcp-Session-Id: <id from above>" -H "MCP-Protocol-Version: 2025-11-25" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"calc_loan_amortization","arguments":{"principal":250000,"annual_rate":6.5,"months":360}}}'
```

### 2.3 Legacy HTTP+SSE (2024-11-05)

```bash
curl -N -H "X-API-Key: sja_key" http://localhost:3002/mcp/sse
# event: endpoint
# data: /mcp?session=<id>
```

The client POSTs JSON-RPC to the announced `/mcp?session=<id>`; the server answers 202 and delivers the response as an `event: message` on the stream. The stream also carries `notifications/*/list_changed`. Events have IDs, but a reconnect with `Last-Event-ID` does not replay missed events (the tracker is per connection).

### 2.4 WebSocket `/mcp/ws`

Authenticate with a query parameter: `?token=<SAJHA JWT>` or `?api_key=<sja_ key>` (OAuth access tokens are not accepted here). An invalid credential, or no credential while `mcp.auth.mode` is `required` or `mcp.anonymous.enabled` is false, closes the connection with code 1008. `tools/list` and `tools/call` apply the caller's tool access. Batches are accepted on this transport, and the server pushes `list_changed` notifications.

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:3002/mcp/ws?api_key=sja_key") as ws:
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
        print(await ws.recv())

asyncio.run(main())
```

### 2.5 MCP-shaped REST helpers

These take a JSON-RPC-like body (`{"params": {...}}`) and return a JSON-RPC-shaped result. They are separate from the MCP transports above, need a signed-in caller (401 otherwise), and show only the tools that caller may see (the `tools/list` policy).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/resources/list` | user | Tool catalog resource (counting the caller's visible tools) plus files in `data/duckdb`. |
| POST | `/api/resources/read` | user | Reads `sajha://tools/catalog` (`params.uri`): the caller's visible tools. |
| POST | `/api/completion/complete` | user | Enum completion for an argument of a tool the caller may see (`params.ref`, `params.argument`). |
| POST | `/api/logging/setLevel` | admin | Sets the server's root log level (`params.level`). |

---

## 3. OAuth and discovery endpoints

Defined in `oauth_routes.py`. Full flow, configuration and client setup: [OAuth Guide](OAuth%20Guide.md).

All of these return **404 `{"error": "not_found"}` while `mcp.auth.mode` is `off`** (the default). The authorization-server endpoints (`/.well-known/oauth-authorization-server`, `/oauth/*`) also return 404 when `mcp.auth.authorization_server` names an external issuer rather than `builtin`; only the protected-resource metadata is served then.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/.well-known/oauth-protected-resource` | none | RFC 9728 metadata for `/mcp`. |
| GET | `/.well-known/oauth-protected-resource/mcp` | none | Same, path-specific form for `/mcp`. |
| GET | `/.well-known/oauth-protected-resource/api/mcp` | none | Metadata for the `/api/mcp` resource. |
| GET | `/.well-known/oauth-authorization-server` | none | RFC 8414 metadata of the built-in authorization server. |
| GET | `/oauth/authorize` | none (cookie used if present) | Consent page (HTML). PKCE `S256` required. Rate limited. |
| POST | `/oauth/authorize` | none (form sign-in or cookie) | Consent decision; redirects to the client with `code`, `state`, `iss`. Sign-in attempts rate limited. |
| POST | `/oauth/token` | client auth (`none`, `client_secret_basic`, `client_secret_post`) | `authorization_code` and `refresh_token` grants; body must be `application/x-www-form-urlencoded`. |
| GET | `/oauth/jwks` | none | Public signing key (JWKS). |
| POST | `/oauth/register` | none | RFC 7591 dynamic client registration. 404 unless `mcp.auth.builtin.dynamic_client_registration: true`. Rate limited. |

```bash
curl http://localhost:3002/.well-known/oauth-protected-resource/mcp
curl http://localhost:3002/.well-known/oauth-authorization-server
```

### A2A discovery (`a2a_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/.well-known/agent.json` | optional | A2A agent card. Skills are the first 50 tools the caller may see; an anonymous caller gets the anonymous policy (`mcp.anonymous.*`), so by default a generic card with no skills. |
| POST | `/a2a` | optional | A2A JSON-RPC: `tasks/send`, `tasks/get`, `tasks/cancel`. Without credentials the anonymous policy applies (`mcp.anonymous.*`, 401 when disabled); a tool runs only with execute access; tasks are visible to their creator (and admins). |

---

## 4. REST API by module

JSON API routes first; HTML pages are collected in [section 4.14](#414-html-pages).

### 4.1 Health and operations probes (`health_routes.py`, `ops_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Status, version, tool and prompt counts, DB type, hot-reload status, state store, sandbox backend. |
| GET | `/ready` | none | Readiness: `{"status": "ok" \| "degraded", "checks": {...}, "timestamp": ...}`. |

`GET /health` is served by `sajha/routes/health_routes.py`.

```bash
curl http://localhost:3002/health
curl http://localhost:3002/ready
```

### 4.2 Tools (`api_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/tools/execute` | user | Run a tool: body `{"tool": "...", "arguments": {...}}`. 403 if the caller lacks access to the tool; 400 if the arguments do not satisfy its input schema; 428 with `error_code: connected_account_required` and `connect_url` when the tool acts through a connected account the caller has not linked ([Connected Accounts](../architecture/Connected%20Accounts.md)). For a versioned tool the body also has `_meta` naming the version that ran and any deprecation ([Tool Quality §6](../architecture/Tool%20Quality.md#6-tool-versions-and-canary)). Logged to tool usage. |
| GET | `/api/tools/list` | as MCP | The tools the caller may see. |
| GET | `/api/tools/{tool_name}/schema` | as MCP | One tool in MCP format (name, description, input schema); 404 for a tool the caller may not see. |
| GET | `/api/tool-groups/search?q=` | as MCP | Search the caller's visible tools by name/description (at least 2 characters; first 50 results). |
| GET | `/api/tool-groups/{group_name}` | as MCP | The caller's visible tools whose name prefix (before the first `_`) is `group_name`. |

"As MCP": the catalog follows the MCP `tools/list` rules ([Security Model, Tool access](../security/Security%20Model.md#tool-access)).
A signed-in user sees their roles' tools, an API key its allowlist, a caller without
credentials the `mcp.anonymous` policy (no tools by default). The endpoints answer 401 where
`/mcp` would: credentials that do not authenticate, `mcp.auth.mode: required`, or
`mcp.anonymous.enabled: false`.
| POST | `/api/admin/tools/{tool_name}/enable` | admin | Enable a tool. |
| POST | `/api/admin/tools/{tool_name}/disable` | admin | Disable a tool. |
| GET | `/api/admin/tools/{tool_name}/config` | admin | The tool's JSON config. |
| POST | `/api/admin/tools/{tool_name}/config` | admin | Replace the config and reload the tool. |
| POST | `/api/admin/tools/reload` | admin | Reload all tools. |
| GET | `/api/admin/tools/metrics/export` | admin | Tool metrics as CSV. |

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"tool": "calc_loan_amortization", "arguments": {"principal": 250000, "annual_rate": 6.5, "months": 360}}'
# {"success": true, "result": {...}}

curl http://localhost:3002/api/tools/calc_loan_amortization/schema
```

### 4.3 Users (`api_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/users` | admin | List users. |
| POST | `/api/admin/users/create` | admin | Create a user: `user_id` (required), `user_name`, `email`, `password`, `roles`, `enabled`. 409 if it exists. |
| POST | `/api/admin/users/{uid}/enable` | admin | Enable a user. |
| POST | `/api/admin/users/{uid}/disable` | admin | Disable a user (not `admin`). |
| DELETE | `/api/admin/users/{uid}/delete` | admin | Delete a user (not `admin`). |

```bash
curl -X POST http://localhost:3002/api/admin/users/create \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"user_id": "analyst1", "user_name": "Analyst One", "password": "s3cret!", "roles": ["user"]}'
```

### 4.4 API keys (`apikeys_routes.py`)

Every route here needs a signed-in user (a console session or a SAJHA JWT); an API key gets 403, so a key cannot mint more. Requests that change something from the browser (cookie) send the page's CSRF token in `X-CSRF-Token`. Bodies are JSON. A response that carries `key` is the only time that raw key is shown. Key objects never contain the key, its hash or its ciphertext ([API keys](../security/Security%20Model.md#api-keys)).

Your own keys:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/account/apikeys` | user | The My API keys page (user menu): your keys, a new-key form, "Sign out everywhere". |
| GET | `/api/account/apikeys` | user | `{"apikeys": [...]}`: your keys, the default key included. |
| POST | `/api/account/apikeys` | user | Create a key that signs in as you: `name`, `description`, `tool_access_mode` (`all`, `allowlist`, `denylist`, `regex`), `tool_list`, `expires_in_days`. At most `auth.api_keys.max_per_user` besides the default key. |
| POST | `/api/account/apikeys/{key_id}/rotate` | user | New value for your key (the old one stops working); returned once. |
| POST | `/api/account/apikeys/{key_id}/revoke` | user | Revoke your key for good (not the default key: 400). |

Every key (administrators):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/apikeys` | admin | The API keys page (`?owner=<user ID>`, `?owner=-` for keys without an owner, `?status=`). |
| GET | `/admin/apikeys/create` | admin | The new-key page. |
| GET | `/admin/apikeys/{key_id}/view` | admin | One key, with its actions. |
| GET | `/api/admin/apikeys` | admin | `{"apikeys": [...]}`; `?owner=<user ID>` or `?owner=-` (no owner). |
| POST | `/api/admin/apikeys` | admin | Create a key: `name`, `description`, `owner` (a user ID; empty for a key without an owner), `tool_access_mode`, `tool_list`, `expires_in_days`, `persistent`. |
| POST | `/admin/apikeys/create` | admin | The older path of `POST /api/admin/apikeys`. |
| POST | `/api/admin/apikeys/{key_id}/rotate` | admin | New value for any key; returned once. |
| POST | `/api/admin/apikeys/{key_id}/revoke` | admin | Revoke for good (`revoked_at`, `revoked_by`); not a default key. |
| POST | `/api/admin/apikeys/{key_id}/enabled` | admin | `{"enabled": true}` or `false`; a revoked key cannot be enabled. |
| POST | `/admin/apikeys/{key_id}/toggle` | admin | The older enable/disable switch (flips `enabled`). |
| POST | `/api/admin/apikeys/{key_id}/owner` | admin | `{"owner": "<user ID>"}`: give a key without an owner one; it then signs in as that user. |
| POST | `/api/admin/apikeys/{key_id}/persistent` | admin | `{"persistent": true}` or `false`: keep (or stop keeping) the key's hashed record in `config.apikeys.path`. |
| POST | `/api/admin/apikeys/{key_id}/access` | admin | `{"tool_access_mode", "tool_list"}`: the key's own tool access. |
| DELETE | `/api/admin/apikeys/{key_id}` | admin | Delete a key and its record (not a default key; prefer revoke). |
| DELETE | `/admin/apikeys/{key_id}/delete` | admin | The older path of the delete. |

```bash
curl -X POST http://localhost:3002/api/account/apikeys \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "reporting-bot", "tool_access_mode": "allowlist", "tool_list": ["wiki_*"]}'
# {"success": true, "key": "sja_...", "apikey": {"id": "...", "owner": "admin", "status": "active", ...}, "note": "..."}
```

### 4.5 Prompts (`prompts_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/prompts/list` | optional | The prompts the caller may see: all for a signed-in caller, `mcp.anonymous.prompts` for an anonymous one; 401 where `/mcp` would answer one. |
| GET | `/api/prompts/{prompt_name}` | optional | One prompt, under the same rule (404 when hidden or unknown). |
| POST | `/api/prompts/create` | admin | Create: `name` (letters, digits, `_`, `-`; max 100), `prompt_template` (or `template`), `description`, `arguments`, `metadata`. |
| POST | `/api/prompts/{prompt_name}/update` | admin | Update the same fields. |
| POST | `/api/prompts/{prompt_name}/delete` | admin | Delete. |
| POST | `/api/prompts/{prompt_name}/render` | user | Render with `{"arguments": {...}}`; returns `{"success": true, "rendered": ...}`. |

### 4.6 Composite tools (`composite_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/composite-tools` | user | List composite definitions. |
| GET | `/api/composite-tools/{name}` | user | One definition, with live input/output schemas when registered. |
| POST | `/api/composite-tools` | studio | Create and register. Required: `name`, `master_tool`. Optional: `arrangement` (default `sibling`), `description`, `master_output_key`, `record_path`, `steps`. 409 if the name exists. |
| PUT | `/api/composite-tools/{name}` | studio | Update and rebuild. A non-admin may change only composites they created (403 otherwise). |
| DELETE | `/api/composite-tools/{name}` | studio | Delete and unregister. A non-admin may delete only composites they created (403 otherwise). |
| GET | `/api/composite-tools/{name}/preview-schema` | user | Generated input/output schemas. |

```bash
curl -X POST http://localhost:3002/api/composite-tools \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"rates_snapshot","arrangement":"sibling","master_tool":"fred_10yr_treasury","master_output_key":"ten_year",
       "steps":[{"tool_name":"fred_2yr_treasury","output_key":"two_year","execution_mode":"parallel","param_mapping":{},"static_params":{}}]}'
```

### 4.7 AI gateway (`ai_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/ai/providers` | user | Providers with health. |
| POST | `/api/ai/providers/{provider_type}/config` | admin | Update `api_key`, `base_url`, `region`, `enabled`. |
| POST | `/api/ai/providers/{provider_type}/health` | admin | Run a provider health check. |
| POST | `/api/ai/defaults` | admin | Set default `provider` / `model`. |
| GET | `/api/ai/models` | user | All models. |
| POST | `/api/ai/models` | admin | Create a model (`provider_type`, `model_id` required). |
| PUT | `/api/ai/models/{model_id}` | admin | Update a model. |
| DELETE | `/api/ai/models/{model_id}` | admin | Delete a model. |
| GET | `/api/ai/preferences` | user | The caller's provider/model preferences. |
| POST | `/api/ai/preferences` | user | Set `provider`, `model`, `temperature`, `max_tokens`. |
| DELETE | `/api/ai/preferences` | user | Clear them. |
| GET | `/api/ai/usage` | user | The caller's token usage and cost. |
| GET | `/api/ai/usage/all` | admin | Usage for all users, plus cache stats. |
| POST | `/api/ai/resolve-tool` | user | Natural-language tool search: `query`, `top_k` (default 5), `extract_params`. |
| POST | `/api/ai/resolve-tool/rebuild` | admin | Rebuild the tool search index. |
| POST | `/api/ai/complete` | user | LLM completion: `prompt` (required), `provider`, `model`, `system`, `temperature`, `max_tokens`. |
| GET | `/api/ai/stats` | admin | Gateway and resolver statistics. |
| GET | `/api/ai/registry` | admin | Registered provider classes. |
| POST | `/api/ai/ask` | user | Answer a question with SAJHA's tools: `question` (required), `model`, `confirm`, `conversation_id` (`"new"` or an id of the caller's; another user's or an expired id is 404), `planner` (admins; 403 otherwise). JSON `AskResult`, or an SSE step stream with `Accept: text/event-stream` or `?stream=1`. Event schema: [Intelligence Layer](../architecture/Intelligence%20Layer.md#post-apiaiask). |
| GET | `/api/ai/config` | admin | Effective `ai.*` configuration, each value with its source; secrets redacted. |
| GET | `/api/ai/planners` | user | Registered planners and the configured default (`ai.ask.planner`). |
| GET | `/api/ai/conversations` | user | The caller's conversations, most recent first. |
| GET | `/api/ai/conversations/{conversation_id}` | user | One of the caller's conversations with its turns and summary; 404 for anyone else's. |
| DELETE | `/api/ai/conversations/{conversation_id}` | user | Delete one of the caller's conversations. |
| DELETE | `/api/ai/conversations` | user | Delete all of the caller's conversations (`{"deleted": n}`). |
| POST | `/api/ai/docs/search` | user | Search the document index: `query` (required), `top_k`, `source`. Passages with citations. Callers who may not run `sajha_search_docs` search SAJHA's guides only. |
| GET | `/api/ai/docs/status` | admin | The document index: store, embedder, documents, sources, uploads, last build. |
| POST | `/api/ai/docs/reindex` | admin | Re-sync the index now; `{"force": true}` re-embeds everything. |
| POST | `/api/ai/docs/uploads` | admin | Add a document: `{"filename", "content"}` (UTF-8 `.md`, `.markdown`, `.txt`, `.rst`, `.html`, `.htm`); 201. |
| DELETE | `/api/ai/docs/uploads/{filename}` | admin | Remove an uploaded document from storage and the index. |

```bash
curl -X POST http://localhost:3002/api/ai/resolve-tool \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"query": "monthly payment on a mortgage", "top_k": 5}'

curl -X POST http://localhost:3002/api/ai/complete \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"prompt": "Explain the Sharpe ratio in one paragraph", "max_tokens": 200}'
```

### 4.8 Reporting (`reporting_routes.py`)

`period` takes `<n>h` or `<n>d`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/reports/overview?period=24h` | user | Platform usage summary. |
| GET | `/api/reports/tools/usage?period=7d` | user | Per-tool usage. |
| GET | `/api/reports/tools/{tool_name}/detail?period=30d` | user | One tool's usage detail. |
| GET | `/api/reports/users/activity?period=30d` | admin | Per-user usage. |
| GET | `/api/reports/heatmap?days=30&tool=` | user | Hour-of-day usage heatmap. |
| GET | `/api/reports/audit?limit=100&action=` | admin | Recent audit entries. |

### 4.9 Operations (`ops_routes.py`, `observability_routes.py`, `sandbox_routes.py`)

**Metrics, versions, contract tests**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/metrics` | user | Metrics summary. |
| GET | `/api/metrics/tools` | user | Metrics for all tools. |
| GET | `/api/metrics/tools/{tool_name}` | user | Metrics for one tool. |
| GET | `/metrics` | `observability.metrics.auth` (default admin) | Prometheus text format ([Observability](../architecture/Observability.md)); 404 when `observability.metrics.enabled` is false. |
| GET | `/monitoring/usage` | user | The Usage & cost page (administrators see everyone, others their own calls). |
| GET | `/api/observability/usage?since=&until=&user=&api_key=&role=&provider=&model=&tool=` | user | Every figure the Usage & cost page shows (non-administrators: own calls only). |
| GET | `/api/observability/usage.csv?dimension=user\|api_key\|role\|model\|tool\|day` | user | One usage table as CSV. |
| GET | `/api/observability/alerts` | admin | Alert rules and their state. |
| GET | `/api/observability/status` | admin | Effective observability settings and the OpenTelemetry state. |
| GET | `/api/tool-versions` | user | Every version of every versioned tool (`config/tool_versions/`; [Tool Quality §6](../architecture/Tool%20Quality.md#6-tool-versions-and-canary)). |
| POST | `/api/tool-versions/{tool_name}/deprecate` | admin | Deprecate one version in the tool's versions file: `{"version", "sunset_date"?, "successor"?}`. |
| POST | `/api/contract-test/{tool_name}` | admin | Contract-test one tool (optional body `{"arguments": {...}}`). |
| POST | `/api/contract-test` | admin | Contract-test every tool; returns totals and per-tool results. |

**Plugins**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/plugins` | admin | Plugins and status. |
| POST | `/api/plugins/discover` | admin | Scan for plugin manifests. |
| POST | `/api/plugins/{name}/load` | admin | Load a plugin. |
| POST | `/api/plugins/{name}/unload` | admin | Unload a plugin. |

**Entropy guard, cache, circuits, providers, replay**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/entropy/tool/{tool_name}` | user | Confidence and entropy for one tool. |
| POST | `/api/entropy/pipeline` | user | Pre-execution check for `{"tools": [...], "threshold": 3.0}`. |
| GET | `/api/cache/stats` | user | Tool cache statistics. |
| POST | `/api/cache/invalidate` | admin | Invalidate one tool (`{"tool_name": "..."}`) or everything (`{}`). |
| GET | `/api/circuits` | user | Circuit breaker states. |
| GET | `/api/providers/health` | user | Provider health. |
| GET | `/api/providers/graph` | user | Tool to provider to endpoint dependency graph. |
| GET | `/api/replay/recent` | admin | Last 50 executions. |
| GET | `/api/replay/tool/{tool_name}` | admin | Execution history for one tool. |
| GET | `/api/replay/stats` | user | Replay store statistics. |

```bash
curl -X POST http://localhost:3002/api/entropy/pipeline \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"tools": ["fred_10yr_treasury", "calc_loan_amortization"], "threshold": 2.0}'

curl -X POST http://localhost:3002/api/cache/invalidate \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"tool_name": "fred_10yr_treasury"}'
```

**Webhooks and audit**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/webhooks` | admin | Subscriptions and delivery stats. |
| POST | `/api/webhooks/subscribe` | admin | `{"event": "...", "url": "..."}` (both required). |
| DELETE | `/api/webhooks/unsubscribe` | admin | Same body. |
| GET | `/api/audit?action=&user_id=&limit=` | admin | Audit log, newest first (`limit` default 100, max 500). |

Audit actions written by the server include `user.login`, `user.create`, `user.enable`, `user.disable`, `user.delete`, `tool.enable`, `tool.disable`, `tool.config_update`, `apikey.create`, `apikey.toggle` and `apikey.delete`.

**Async execution**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/tools/{tool_name}/execute-async` | admin or `async:execute` | Queue a run (also needs execute access to the tool). The body is the tool arguments plus an `async` object: `delivery` (`webhook`, `kafka` or `file`) and `destination` (required): a URL under `async.delivery.webhook.allowed_urls`, a Kafka topic, or a relative path inside `async.delivery.file.base_dir`. 400 for a refused destination, 503 when the queue is full or `async.enabled` is false. |
| GET | `/api/async/tasks?status=&limit=` | user | List your tasks (admins: all) plus executor stats. |
| GET | `/api/async/tasks/{task_id}` | user | Task status and result (your own tasks; admins: any). |
| POST | `/api/async/tasks/{task_id}/cancel` | user | Cancel one of your queued tasks. |
| POST | `/api/async/tasks/{task_id}/retry` | user | Retry one of your failed tasks. |
| GET | `/api/async/stats` | user | Executor statistics. |

```bash
curl -X POST http://localhost:3002/api/tools/calc_loan_amortization/execute-async \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"principal": 250000, "annual_rate": 6.5, "months": 360,
       "async": {"delivery": "webhook", "destination": "https://my-app.example.com/results"}}'
# {"task_id": "...", "status": "queued", "tool_name": "calc_loan_amortization", "delivery": "webhook",
#  "destination": "https://my-app.example.com/results", "poll_url": "/api/async/tasks/..."}
```

**Shell execution** (disabled unless `shell.enabled: true`; bash additionally needs `shell.bash.enabled: true`; otherwise 403)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/shell/python` | admin or `shell:execute` | Run `{"code": "..."}` in the sandbox. |
| POST | `/api/shell/bash` | admin or `shell:execute` | Run `{"command": "..."}` in the sandbox. |
| GET | `/api/shell/capabilities` | user | What is enabled and the security policy. |
| GET | `/api/shell/history` | admin | Last 50 executions. |
| GET | `/api/sandbox/status` | admin | Active [sandbox](../architecture/Sandbox.md) backend, every backend's availability on this host, and the active one's guarantees from a live probe. |

**System monitor**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/system-monitor` | admin | CPU, memory, disk, network and process data (psutil when installed). |

### 4.10 WebSocket sessions (`ws_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/ws/sessions` | admin | Active `/mcp/ws` sessions and count. |

### 4.11 Studio (`studio_routes.py`, prefixes `/studio` and `/admin/studio`)

The pages under `/studio` are in section 4.14. The creators post to these JSON actions;
every one needs Studio access (`studio`) and answers JSON (a 401 or 403 too). A non-admin gets 403 from `/admin/studio/deploy` and `/admin/studio/script/deploy` while `sandbox.enforce_for_generated_tools` is `false`. Errors are
`{"success": false, "error": "..."}`.
What each creator's fields mean is in the [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/admin/studio/analyze` | studio | Python code creator: parse `{"code", "tool_name"}` and return the generated JSON config and Python module without writing anything. |
| POST | `/admin/studio/deploy` | studio | Python code creator: write the files and load the tool into the running server; if it fails to load, the files are removed (500). |
| POST | `/admin/studio/validate-name` | studio | `{"tool_name"}` → `{"valid", "error"}`. |
| POST | `/admin/studio/delete` | studio | `{"tool_name"}`: unload a Studio-generated tool and remove its files. |
| POST | `/admin/studio/rest/preview`, `/admin/studio/dbquery/preview`, `/admin/studio/script/preview`, `/admin/studio/powerbi/preview`, `/admin/studio/powerbidax/preview`, `/admin/studio/livelink/preview`, `/admin/studio/sharepoint/preview` | studio | One per creator: the generated config and code, without writing anything. |
| POST | `/admin/studio/rest/deploy`, `/admin/studio/dbquery/deploy`, `/admin/studio/script/deploy`, `/admin/studio/powerbi/deploy`, `/admin/studio/powerbidax/deploy`, `/admin/studio/livelink/deploy`, `/admin/studio/sharepoint/deploy` | studio | One per creator: write the files and load the tool, as above. |
| POST | `/admin/studio/olap/deploy` | studio | Add an OLAP dataset (`name`, `dimensions`, `measures`, ...) and reload the OLAP tools. |
| POST | `/admin/studio/olap/delete` | studio | `{"name"}`: remove a dataset that Studio created (403 for any other). |

API Import (`api_import_routes.py`, prefixes `/studio`, `/admin/studio/api-import` and `/api/studio/api-import`; design
in [API Import](../architecture/API%20Import.md)). Every body is the import request
(`kind`, `url` or `text`, `prefix`, `server_index`, `server_variables`, `base_url`, `auth`,
`filters`, `timeout_seconds`, `rate_limit_per_minute`, `graphql_depth`, `names`); errors are
400 with `{"success": false, "error"}`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/admin/studio/api-import/parse` | studio | The preview: API facts, one entry per operation (proposed name, schemas, annotations, flags, `new`/`changed`/`unchanged`), operations gone from the spec. Writes nothing. |
| POST | `/admin/studio/api-import/test` | studio | Plus `operation` and `arguments`: call one operation once without deploying it. |
| POST | `/admin/studio/api-import/deploy` | studio | Plus `selected` (operation keys) and `remove`: write and hot-load the tools, delete the removed ones, save the import record. |
| GET | `/api/studio/api-import/apis` | studio | Every import: id, kind, title, server, tools, how many are loaded. |
| GET | `/api/studio/api-import/apis/{api_id}` | studio | An import's saved request, to re-import it. |
| POST | `/admin/studio/api-import/delete` | studio | `{"api_id"}`: remove the import's tools and its record. |

Describe a tool (`describe_routes.py`, served through `studio_routes.py`'s router; prefixes
`/studio`, `/admin/studio/describe` and `/api/studio/describe`; design in
[Tool Generation](../architecture/Tool%20Generation.md)). Each answer is the draft
(`id`, `proposal`, `hash`, `errors`, `warnings`, `files`, `policy`, `tests_run`, `deployed`)
with `"success": true`; a refusal is `{"success": false, "error"}` with 400, 403, 404, 409
(a deploy precondition; `approval_id` when a policy holds it) or 503 (no model).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/admin/studio/describe/propose` | studio | `{"description", "kind"?}`: the model's proposal, checked, with the files a deploy would write and the policy preview. Writes no tool. |
| POST | `/admin/studio/describe/revise` | studio | `{"draft_id", "proposal"}`: an edited proposal, checked again (new hash, tests cleared). |
| POST | `/admin/studio/describe/test` | studio | `{"draft_id", "live"?}`: run the test cases (Python in the sandbox, REST against fixtures). |
| POST | `/admin/studio/describe/deploy` | studio | `{"draft_id", "hash", "approve": true, "accept_failures"?}`: deploy the reviewed version. |
| GET | `/api/studio/describe/drafts/{draft_id}` | studio | A draft (a non-admin sees only their own; 404 otherwise). |

### 4.12 Misc, help and docs (`misc_routes.py`, `help_routes.py`)

Only HTML pages and redirects (section 4.14). The help pages are rendered from `sajha/web/help_catalog.py`; the superseded help URLs in its `REDIRECTS` answer 301.

### 4.13 Dashboard (`dashboard_routes.py`)

Only the HTML page `GET /dashboard` (user).

### 4.14 HTML pages

These render templates; they are not JSON APIs. Unauthenticated requests to `user`/`studio`/`admin` pages are redirected to `/`.

| Auth | Paths |
|---|---|
| none / optional | `/`, `/login`, `/help`, `/help/c/{cid}`, `/help/guides`, `/help/guides/{name}`, `/glossary`, `/help/tools`, `/about`, `/comparison`, `/oauth/authorize`; and the 301 redirects `/help/ai`, `/help/enterprise`, `/help/tutorials`, `/help/glossary`, `/help/storage`, `/docs`, `/docs/view/{doc_path}` |
| user | `/dashboard`, `/account/password`, `/account/apikeys`, `/tools`, `/tools/{tool_name}/execute`, `/tools/{tool_name}/schema`, `/prompts`, `/prompts/{prompt_name}`, `/prompts/{prompt_name}/test`, `/prompts/category/{category}`, `/prompts/tag/{tag}`, `/reports`, `/composite/builder`, `/ai/settings`, `/ask`, `/playground`, `/monitoring/usage` |
| admin | `/admin/users`, `/admin/users/create`, `/admin/tools`, `/admin/system-monitor`, `/admin/prompts`, `/admin/async-tasks`, `/admin/apikeys`, `/admin/apikeys/create`, `/admin/apikeys/{key_id}/view`, `/admin/federation`, `/admin/connectors`, `/prompts/create`, `/tools/{tool_name}/config`, `/monitoring/tools`, `/monitoring/users` |
| studio | `/studio`, `/studio/rest`, `/studio/dbquery`, `/studio/script`, `/studio/livelink`, `/studio/olap`, `/studio/powerbi`, `/studio/powerbidax`, `/studio/sharepoint`, `/studio/examples`, `/studio/api-import`, `/studio/describe` |

### 4.15 Python Playground (`playground_routes.py`)

The playground runs Python in the browser; none of these routes executes code. Its tool
calls use `POST /api/tools/execute` and `POST /api/ai/ask` above, with the user's session.
Headers and settings: [Python Playground](../getting-started/Python%20Playground.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/playground` | user | The page. Sends COOP `same-origin`, COEP `require-corp` and its own CSP; 404 when `playground.enabled` is false. |
| GET | `/api/playground/worker.js` | user | The Web Worker script (an ES module); the only response whose CSP allows `'wasm-unsafe-eval'`. |
| GET | `/api/playground/sajha.py` | user | Source of the `sajha` module installed into Pyodide (`text/x-python`). |
| GET | `/api/playground/runtime.py` | user | Source of the cell runner installed into Pyodide. |
| GET | `/api/playground/tools` | user | `{tools: [{name, description, category}], count}`: the enabled tools this caller may execute (what `sajha.tools()` returns). |

### 4.16 Federation (`federation_routes.py`)

Upstream MCP servers behind SAJHA. Every route is admin only and every change is written to
the audit log. Errors are `{"error": "message"}` (400 invalid or unsafe definition, 404 no
such upstream or item, 502 the upstream failed). Behaviour: [Federation](../architecture/Federation.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/federation` | admin | The Federation page. |
| GET | `/api/federation/upstreams` | admin | `{summary, upstreams: [...]}`: every upstream with its state, protocol version, server info, last error, counts, breaker and discovered items. |
| GET | `/api/federation/upstreams/{upstream_id}` | admin | One upstream's status. |
| POST | `/api/federation/upstreams` | admin | Add an upstream (body: the upstream fields; secrets as references). 201. |
| PUT | `/api/federation/upstreams/{upstream_id}` | admin | Replace an upstream added on the page (not one from configuration). |
| DELETE | `/api/federation/upstreams/{upstream_id}` | admin | Remove an upstream added on the page; its tools leave the registry. |
| POST | `/api/federation/upstreams/{upstream_id}/refresh` | admin | Reconnect if needed and re-discover now. |
| POST | `/api/federation/upstreams/{upstream_id}/items` | admin | `{"kind": "tool" \| "prompt" \| "resource", "name", "action"}`; actions `approve`, `reject`, `disable`, `enable`, `reset`, `approve_all`. Returns `{ok, changed}`. |
| POST | `/api/federation/test` | admin | Connect to an unsaved upstream definition: `{ok, protocol_version, server_info, tools, prompts, resources}` or `{ok: false, error}`. |

### 4.17 Connected accounts (`accounts_routes.py`)

Users' links to third-party services. Pages and forms use the session cookie; every form
that changes state carries the page's CSRF token. No route ever returns a token.
Behaviour: [Connected Accounts](../architecture/Connected%20Accounts.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/account/connections` | user | The Connected accounts page (`?connect=<id>&scope=...` highlights one service). |
| POST | `/account/connections/{provider}/connect` | user (form, CSRF) | Start linking: 303 to the provider's authorize URL; sets the `sajha_acct_flow` cookie. |
| GET | `/account/connections/{provider}/callback` | user | The provider's redirect back: 303 to the page on success, 400 with the reason otherwise. |
| POST | `/account/connections/{provider}/disconnect` | user (form, CSRF) | Revoke at the provider where possible and delete the link. |
| GET | `/api/accounts/connections` | user | `{providers, connections, connect_url}`: configured providers and the caller's links (metadata). |
| DELETE | `/api/accounts/connections/{provider}` | user | Disconnect; a cookie session needs `X-CSRF-Token`. 404 when there was no link. |
| GET | `/admin/connections` | admin | Every user's links, providers, vault keys; unlink and re-encrypt. |
| POST | `/admin/connections/revoke` | admin (form, CSRF) | Unlink `provider` for `user_id`. |
| POST | `/admin/connections/rotate` | admin (form, CSRF) | Re-encrypt every link with the current vault key. |
| GET | `/api/admin/accounts/connections` | admin | Every link's metadata (`?user=`, `?provider=`). |

### 4.18 Policies, approvals and audit (`policy_routes.py`)

The policy engine and the tamper-evident audit. Every route is admin only; a cookie session
sends the page's CSRF token (form field `csrf`, or header `X-CSRF-Token`) on state changes.
Behaviour: [Policy and Audit](../architecture/Policy%20and%20Audit.md). How a tool call
answers a policy outcome (403, 202 with `approval_id`, 429 with `Retry-After` on
`POST /api/tools/execute`) is in its section 5.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/policies` | admin | The Policies page: files, rules, parse errors, test bench. |
| GET | `/api/policy/policies` | admin | Every policy file with its rules, errors and the engine's settings. |
| POST | `/api/policy/reload` | admin (CSRF) | Reload the policy directory now. |
| POST | `/api/policy/test` | admin | The test bench: `{tool, arguments, user, roles, api_key, anonymous, auth_type, source, time, include_disabled, output}` → `{decision, would_run, output?}`. Nothing runs. |
| GET | `/admin/approvals` | admin | The Approvals page. |
| POST | `/admin/approvals/{aid}/decide` | admin (form, CSRF) | `decision=approve` or `deny`, optional `note`. |
| GET | `/api/policy/approvals` | admin | `{approvals: [...]}` (`?status=pending` and so on). |
| POST | `/api/policy/approvals/{aid}/approve` | admin (CSRF) | Approve (`{"note"}` optional); 409 when already decided, expired or your own call. |
| POST | `/api/policy/approvals/{aid}/deny` | admin (CSRF) | Deny. |
| GET | `/admin/audit` | admin | The Audit page (`?event=policy.*`, `?actor=`). |
| GET | `/api/audit/records` | admin | Recent hash-chained records, merged across chains (`?limit`, `?event`, `?actor`, `?chain`). |
| GET | `/api/audit/verify` | admin | Verify every chain (`?chain=` one): `{ok, chains: [{chain_id, ok, problems, warnings, ...}]}`. |
| POST | `/api/audit/anchor` | admin (CSRF) | Sign this worker's chain head now. |
| GET | `/api/audit/sinks` | admin | This worker's chain writer and SIEM sink status. |

### 4.19 Tool quality (`quality_routes.py`)

Probes, saved test runs, the linter, evals and tool versions. Every route is admin only; a
cookie session sends the page's CSRF token (form field `csrf`, or header `X-CSRF-Token`) on
state changes. Behaviour: [Tool Quality](../architecture/Tool%20Quality.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/tool-health` | admin | The Tool Health page (`?run=<id>` a saved test run, `?lint=1&level=` the linter). |
| POST | `/admin/tool-health/probes/{tool}/run` | admin (form, CSRF) | Run the tool's probe now. |
| POST | `/admin/tool-health/tests/run` | admin (form, CSRF) | Run the test harness: `tool` (glob), `mode` (`replay`, `auto`, `live`); saves the run. |
| GET | `/api/quality/probes` | admin | `{enabled, probes: [...]}`: every probe with its schedule, last result and history. |
| POST | `/api/quality/probes/{tool}/run` | admin (CSRF) | Run one probe now; 404 when the tool has none. |
| GET | `/api/quality/lint` | admin | `{summary, findings}` (`?tool=` glob). |
| POST | `/api/quality/tests/run` | admin (CSRF) | `{"tool", "mode"}` → `{id, summary, results}`. |
| GET | `/api/quality/runs` | admin | Saved runs (`?kind=test|eval`). |
| GET | `/api/quality/runs/{id}` | admin | One saved run with its detail. |
| GET | `/admin/evals` | admin | The Evals page (`?run=<id>`, `?a=<id>&b=<id>` compares). |
| POST | `/admin/evals/run` | admin (form, CSRF) | Start a run: `set_name`, `model`, `planner`. |
| GET | `/api/quality/evals` | admin | `{sets, runs}`. |
| POST | `/api/quality/evals/run` | admin (CSRF) | `{"set", "model"?, "planner"?}` → 202 `{id, status: "running"}`. |
| GET | `/api/quality/evals/compare` | admin | `?a=<id>&b=<id>` → metric deltas, regressed and improved questions. |
| GET | `/admin/tool-versions` | admin | The Tool Versions page (`?new=<tool>` starts a versions file). |
| POST | `/admin/tool-versions/{tool}/{action}` | admin (form, CSRF) | `save` (`text`), `canary` (`version`, `percent`), `promote` (`version`), `clear` (`version`: clear a rollback). |
| GET | `/api/quality/versions` | admin | Every versioned tool: versions, routing, window statistics, rollbacks, file errors. |
| PUT | `/api/quality/versions/{tool}` | admin (CSRF) | The versions file as the YAML body; validated before it is written (400 with the reason). |
| POST | `/api/quality/versions/{tool}/canary` | admin (CSRF) | `{"version", "percent"}`. |
| POST | `/api/quality/versions/{tool}/promote` | admin (CSRF) | `{"version"}`: make it stable and clear its rollback. |
| DELETE | `/api/quality/versions/{tool}/rollback/{version}` | admin (CSRF) | Clear an automatic rollback. |

### 4.20 Workflows (`workflow_routes.py`)

Workflow definitions, runs and inbound webhooks. Signed-in users manage their own
workflows; administrators see and manage all; only administrators may publish one as a
tool. Behaviour, the definition format and the webhook signature:
[Workflows](../architecture/Workflows.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/workflows` | user | The Workflows page. |
| GET | `/api/workflows` | user | `{workflows: [...], status}`. |
| POST | `/api/workflows` | user | Create or update: a JSON definition, a YAML body (`Content-Type: application/yaml`), or `{"text": "..."}`. 400 with the reason when invalid, 403 when not yours. |
| POST | `/api/workflows/validate` | user | `{valid, definition, yaml, order}`; nothing is saved. |
| GET | `/api/workflows/{name}` | owner, admin | One workflow (`?format=yaml`; `?reveal=1` shows webhook secrets). |
| PUT | `/api/workflows/{name}` | owner, admin | Update (version + 1). |
| DELETE | `/api/workflows/{name}` | owner, admin | Delete it and its run history (active runs are cancelled). |
| POST | `/api/workflows/{name}/enable`, `/api/workflows/{name}/disable` | owner, admin | Switch its triggers and published tool on or off. |
| POST | `/api/workflows/{name}/runs` | owner, admin | `{"input", "wait"?, "idempotency_key"?}` (or an `Idempotency-Key` header) → `{run}`; 200 when finished within `wait`, else 202. |
| GET | `/api/workflows/{name}/runs` | owner, admin | `{runs}` (`?status`, `?limit`). |
| GET | `/api/workflows/runs/{id}` | owner, admin | `{run}` with its `steps`. |
| POST | `/api/workflows/runs/{id}/cancel` | owner, admin | Cancel. |
| POST | `/api/workflows/runs/{id}/rerun` | owner, admin | `{"from_step"?, "latest_definition"?}` → 202 `{run}`. |
| POST | `/api/workflows/{name}/hooks/{trigger}` | HMAC signature | Inbound webhook: `X-Sajha-Timestamp`, `X-Sajha-Signature`, optional `X-Sajha-Delivery`; 202 `{run_id}`, 401 bad signature or stale timestamp, 409 replay, 404 unknown trigger. |

### 4.21 Data connectors (`connectors_routes.py`)

Connections to databases, warehouses, vector stores and search clusters, and the tools generated
for them. Every route is admin only; changes are audited. Behaviour:
[Data Connectors](../architecture/Data%20Connectors.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/admin/connectors` | admin | The Data Connectors page. |
| GET | `/api/connectors` | admin | `{connections: [...]}`: each record's summary, its tools (loaded or not), idle pooled connections. |
| GET | `/api/connectors/kinds` | admin | `{kinds: [...]}`: each kind, its family, Python package, whether it is installed, per-user support. |
| POST | `/api/connectors` | admin | Create or replace a connection (the record; `"create": true` refuses an existing id); writes it and syncs its tools. 400 with the field at fault. |
| POST | `/api/connectors/test` | admin | Connect with an unsaved definition: `{success, server_version, tables}` or `{success: false, error}`. |
| POST | `/api/connectors/sync` | admin | Regenerate every connection's tools and remove orphans (no database is opened). |
| POST | `/api/connectors/view-preview` | admin | `{"connection": <record>}`: the input schema its last view would get. |
| GET | `/api/connectors/{cid}` | admin | `{connection}`: the stored record (secret references, never values). |
| DELETE | `/api/connectors/{cid}` | admin | Remove the connection and its tools. |
| POST | `/api/connectors/{cid}/refresh` | admin | Re-read the catalog: `{tables, truncated}`. |
| GET | `/api/connectors/{cid}/tables` | admin | The allowed tables (or collections). |
| GET | `/api/connectors/{cid}/describe` | admin | `?table=`: what `<id>__describe_table` (or `__describe_collection`) returns. |

### 4.22 System notices (`notices_routes.py`)

What needs attention, as the console's banner, navbar badge and dashboard panel show it. A
signed-in user sees notices with audience `everyone`; an administrator sees all. Fields,
lifecycle and sources: [System Notices](../architecture/System%20Notices.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/notices` | user | The caller's view: `{enabled, notices, banner, others, badge, is_admin, version}`; `?cleared=1` adds `cleared` (recently cleared); an administrator signed in by cookie also gets `csrf`. |
| GET | `/api/notices/stream` | user | Server-sent events: `event: notices` with the same view, at once and after every change (`?cleared=1` as above). |
| GET | `/api/admin/notices` | admin | `{enabled, notices}`: `?state=open` (default), `cleared` or `all`; `?source=`. 400 for another state. |
| POST | `/api/admin/notices/{id}/acknowledge` | admin (CSRF) | Acknowledge an active notice → `{notice}`; 404 unknown id. |
| POST | `/api/admin/notices/{id}/clear` | admin (CSRF) | Clear it now (reason `admin`) → `{notice}`; a source whose condition still holds raises it again. 404 unknown id. |

---

## 5. Error format

**REST (JSON) routes.** Handlers return an HTTP status with a JSON body of the form `{"error": "message"}`; prompt and some admin routes use `{"success": false, "error": "message"}`. Successful writes usually return `{"success": true, ...}`.

Framework-level responses (`sajha/app.py`, `sajha/security.py`):

| Status | When | Body |
|---|---|---|
| 401 | `user`/`studio`/`admin` route without a valid credential, from an API caller: a path starting with `/api/`, `/mcp`, `/a2a`, `/admin/studio/` or `/oauth/`, any method other than GET/HEAD, or an `Accept` that asks for JSON and not HTML (`_wants_json` in `sajha/app.py`) | `{"error": "Authentication required"}` with `WWW-Authenticate` |
| 302 | Same, from a browser page navigation (any other GET) | Redirect to `/` |
| 403 | `admin` route called by a non-admin, or `studio` route called by someone without Studio access | `{"error": "..."}` for an API caller (as above); otherwise an HTML error page |
| 404 | No such route | HTML error page. Route handlers' own 404s (unknown tool, user, prompt...) are JSON. |
| 413 | `Content-Length` over 10 MB | `{"error": "Request body too large. Maximum: 10485760 bytes"}` |
| 422 | Query/path parameter of the wrong type (e.g. `days=abc`) | FastAPI's `{"detail": [...]}` |
| 429 | Sign-in throttle (per address) on `POST /api/auth/login`; other rate limits ([Security Model](../security/Security%20Model.md#rate-limiting-and-lockout)) | `{"error": "..."}` |
| 500 | Unhandled exception | HTML error page |

**MCP endpoints.** JSON-RPC 2.0 error objects: `{"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}`. HTTP statuses used by the transport: 400 (parse error `-32700`, invalid request or batch `-32600`, missing `Mcp-Session-Id` on DELETE, unsupported `MCP-Protocol-Version`), 403 (disallowed `Origin`, `-32000`), 404 (unknown session, `-32001`), 405 (GET/DELETE where no stream or session exists). The 2026-07-28 path adds `-32020` (header/body mismatch) and `-32022` (unsupported protocol version). Authorization failures are OAuth challenges, not JSON-RPC errors: `{"error": "invalid_token" | "insufficient_scope" | "unauthorized", "error_description": "..."}` with a `WWW-Authenticate: Bearer resource_metadata="...", scope="..."` header.

**OAuth endpoints.** RFC 6749 style `{"error": "...", "error_description": "..."}` with `Cache-Control: no-store`; `{"error": "not_found"}` with 404 when OAuth is off. Authorization errors that cannot safely redirect (unknown client, redirect URI mismatch) render an HTML error page.

See also: [Security Model](../security/Security%20Model.md), [Configuration Reference](../getting-started/Configuration%20Reference.md), [Client SDK Guide](../clients/Client%20SDK%20Guide.md).

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
