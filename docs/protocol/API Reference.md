# SAJHA MCP Server: API Reference

This page lists every HTTP and WebSocket route the server registers, grouped by the module in `sajha/routes/` that defines it. All modules are included in `sajha/app.py` without an extra prefix, so the paths below are the full paths. Three modules set a router prefix: `admin_routes.py` (`/admin`), `apikeys_routes.py` (`/admin/apikeys`) and `studio_routes.py` (`/studio`); their paths are shown with the prefix applied.

The examples assume the default address `http://localhost:3002` (`server.port`, env `SERVER_PORT`).

FastAPI also serves its generated docs: `GET /api/docs` (Swagger UI), `GET /api/redoc` and `GET /openapi.json`, all without authentication. Static assets are mounted at `/static`.

**Auth column legend** used throughout:

| Value | Meaning |
|---|---|
| none | No credential checked. |
| optional | Credentials are read if present (they change what is shown) but not required. |
| user | Any valid credential (`require_auth`): SAJHA JWT, `sja_` API key or the `sajha_token` cookie. |
| admin | A user with the admin role (`require_admin`). API keys never qualify: they authenticate with the `api_consumer` role and `is_admin = false`. |
| MCP | MCP transport rules: see [MCP endpoints](#2-mcp-endpoints). |

---

## 1. Authentication

### 1.1 Credentials for REST calls

`AuthManager.authenticate_request` (`sajha/auth/__init__.py`) tries these in order and uses the first that validates:

1. `Authorization: Bearer <jwt>`: a SAJHA login JWT (HS256, from `POST /api/auth/login`).
2. `X-API-Key: sja_...`: an API key created under `/admin/apikeys`.
3. `Authorization: sja_...`: the same API key sent bare in the `Authorization` header.
4. Cookie `sajha_token`: the JWT the web UI stores at login (`POST /login`).

API keys authenticate as `apikey:<key name>` with the single role `api_consumer`; the key's `tool_access_mode`/tool list is stored but not enforced in this release (see the [Security Model](../security/Security%20Model.md)). SAJHA JWTs carry the user's roles. JWT lifetime is `auth.jwt.expiry_minutes` (env `JWT_EXPIRY`, default 60); the web cookie has a one-hour `max_age`.

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

(`admin`/`admin123` is the seeded account from `config/users.json`; change it.)

### 1.2 Auth routes (`auth_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | JSON login; returns a JWT and `password_change_required`. Too many failed sign-ins from one IP: 429; a locked account: 423 ([Security Model](../security/Security%20Model.md#web-login-and-passwords)). |
| GET | `/account/password` | user | Change-password page (also in the user menu). |
| POST | `/account/password` | user | Change-password form (`current_password`, `new_password`, `confirm_password`); sets a fresh cookie. |
| POST | `/api/auth/change-password` | user | `{"current_password", "new_password"}`; returns `{"success": true, "token": <new JWT>}`. Not for API keys. |
| POST | `/api/admin/users/{uid}/password` | admin | Reset a password: `{"password", "must_change_password": true}`; also unlocks the account. |
| GET | `/login` | none | Login page (HTML). |
| POST | `/login` | none | Login form (`user_id`, `password`); sets the `sajha_token` cookie and redirects to `?next=` (local paths only) or `/dashboard`. Same throttle (429) and lockout (423) as the JSON login. |
| GET | `/logout` | none | Clears the cookie, redirects to `/`. |
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

Errors: 400 `{"error": "Missing credentials"}`, 401 `{"error": "Invalid credentials"}`, 429 on rate limit.

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

The client POSTs JSON-RPC to the announced `/mcp?session=<id>`; the server answers 202 and delivers the response as an `event: message` on the stream. The stream also carries `notifications/*/list_changed` and supports `Last-Event-ID` replay.

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

These take a JSON-RPC-like body (`{"params": {...}}`) and return a JSON-RPC-shaped result. They are separate from the MCP transports above and **check no credentials**.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/resources/list` | none | Tool catalog resource plus files in `data/duckdb`. |
| POST | `/api/resources/read` | none | Reads `sajha://tools/catalog` (`params.uri`). |
| POST | `/api/completion/complete` | none | Enum completion for a tool argument (`params.ref`, `params.argument`). |
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
| GET | `/.well-known/agent.json` | none | A2A agent card (skills from the first 50 registered tools). |
| POST | `/a2a` | optional | A2A JSON-RPC: `tasks/send`, `tasks/get`, `tasks/cancel`. Without credentials the anonymous policy applies (`mcp.anonymous.*`, 401 when disabled); a tool runs only with execute access; tasks are visible to their creator (and admins). |

---

## 4. REST API by module

JSON API routes first; HTML pages are collected in [section 4.14](#414-html-pages).

### 4.1 Health and operations probes (`health_routes.py`, `ops_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Status, version, tool and prompt counts, DB type, hot-reload status. |
| GET | `/ready` | none | Readiness: `{"status": "ok" \| "degraded", "checks": {...}, "timestamp": ...}`. |

Both `health_routes.py` and `ops_routes.py` declare `GET /health`; `health_routes.py` is registered first, so its handler is the one that answers.

```bash
curl http://localhost:3002/health
curl http://localhost:3002/ready
```

### 4.2 Tools (`api_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/tools/execute` | user | Run a tool: body `{"tool": "...", "arguments": {...}}`. 403 if the caller lacks access to the tool. Logged to tool usage. |
| GET | `/api/tools/list` | none | All registered tools. |
| GET | `/api/tools/{tool_name}/schema` | none | One tool in MCP format (name, description, input schema). |
| GET | `/api/tool-groups/search?q=` | none | Search tools by name/description (at least 2 characters; first 50 results). |
| GET | `/api/tool-groups/{group_name}` | none | Tools whose name prefix (before the first `_`) is `group_name`. |
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

### 4.4 API keys (`apikeys_routes.py`, prefix `/admin/apikeys`)

Keys are managed under `/admin/apikeys`, not `/api/...`. Because these paths do not start with `/api/`, an unauthenticated call gets a 302 redirect to `/` rather than a JSON 401.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/admin/apikeys/create` | admin | Create a key: `name`, `description`, `tool_access_mode` (default `all`), `tool_list`. The raw `sja_` key is returned once. |
| POST | `/admin/apikeys/{key_id}/toggle` | admin | Enable/disable a key. |
| DELETE | `/admin/apikeys/{key_id}/delete` | admin | Delete a key. |

The GET routes under this prefix are HTML pages (section 4.14).

```bash
curl -X POST http://localhost:3002/admin/apikeys/create \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "reporting-bot", "tool_access_mode": "all"}'
# {"success": true, "key": "sja_...", "name": "reporting-bot"}
```

### 4.5 Prompts (`prompts_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/prompts/list` | none | All prompts. |
| GET | `/api/prompts/{prompt_name}` | none | One prompt. |
| POST | `/api/prompts/create` | admin | Create: `name` (letters, digits, `_`, `-`; max 100), `prompt_template` (or `template`), `description`, `arguments`, `metadata`. |
| POST | `/api/prompts/{prompt_name}/update` | admin | Update the same fields. |
| POST | `/api/prompts/{prompt_name}/delete` | admin | Delete. |
| POST | `/api/prompts/{prompt_name}/render` | user | Render with `{"arguments": {...}}`; returns `{"success": true, "rendered": ...}`. |

### 4.6 Composite tools (`composite_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/composite-tools` | user | List composite definitions. |
| GET | `/api/composite-tools/{name}` | user | One definition, with live input/output schemas when registered. |
| POST | `/api/composite-tools` | admin | Create and register. Required: `name`, `master_tool`. Optional: `arrangement` (default `sibling`), `description`, `master_output_key`, `record_path`, `steps`. 409 if the name exists. |
| PUT | `/api/composite-tools/{name}` | admin | Update and rebuild. |
| DELETE | `/api/composite-tools/{name}` | admin | Delete and unregister. |
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
| POST | `/api/ai/ask` | user | Answer a question with SAJHA's tools: `question` (required), `model`, `confirm`. JSON `AskResult`, or an SSE step stream with `Accept: text/event-stream` or `?stream=1`. Event schema: [Intelligence Layer](../architecture/Intelligence%20Layer.md#post-apiaiask). |
| GET | `/api/ai/config` | admin | Effective `ai.*` configuration, each value with its source; secrets redacted. |

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

### 4.9 Operations (`ops_routes.py`)

**Metrics, versions, contract tests**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/metrics` | user | Metrics summary. |
| GET | `/api/metrics/tools` | user | Metrics for all tools. |
| GET | `/api/metrics/tools/{tool_name}` | user | Metrics for one tool. |
| GET | `/api/tool-versions` | user | Placeholder: always returns `{"versions": []}`. |
| POST | `/api/tool-versions/{tool_name}/deprecate` | admin | Placeholder: returns success without changing anything. |
| POST | `/api/contract-test/{tool_name}` | admin | Contract-test one tool (optional body `{"arguments": {...}}`). |
| POST | `/api/contract-test` | admin | Contract-test every tool; returns totals and per-tool results. |

**Tenants and plugins**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/tenants` | admin | List tenants. |
| POST | `/api/tenants` | admin | Create: `id`, `name` (required), `tool_patterns` (default `["*"]`), `blocked_tools`, `quota`. |
| GET | `/api/tenants/{tenant_id}` | admin | One tenant. |
| PUT | `/api/tenants/{tenant_id}` | admin | Update a tenant. |
| DELETE | `/api/tenants/{tenant_id}` | admin | Delete (the default tenant cannot be deleted). |
| GET | `/api/plugins` | admin | Plugins and status. |
| POST | `/api/plugins/discover` | admin | Scan for plugin manifests. |
| POST | `/api/plugins/{name}/load` | admin | Load a plugin. |
| POST | `/api/plugins/{name}/unload` | admin | Unload a plugin. |

```bash
curl -X POST http://localhost:3002/api/tenants \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"id": "research", "name": "Research team", "tool_patterns": ["fred_*", "calc_*"]}'
```

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

**System monitor**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/system-monitor` | admin | CPU, memory, disk, network and process data (psutil when installed). |

### 4.10 WebSocket sessions (`ws_routes.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/ws/sessions` | admin | Active `/mcp/ws` sessions and count. |

### 4.11 Studio (`studio_routes.py`, prefix `/studio`)

Only HTML pages are registered (section 4.14). There are no Studio JSON API routes.

### 4.12 Misc and docs (`misc_routes.py`)

Only HTML pages (section 4.14).

### 4.13 Dashboard (`dashboard_routes.py`)

Only the HTML page `GET /dashboard` (user).

### 4.14 HTML pages

These render templates; they are not JSON APIs. Unauthenticated requests to `user`/`admin` pages are redirected to `/`.

| Auth | Paths |
|---|---|
| none / optional | `/`, `/login`, `/help`, `/help/c/{cid}`, `/help/guides`, `/help/guides/{name}`, `/glossary`, `/help/tools`, `/about`, `/oauth/authorize`; and the 301 redirects `/help/ai`, `/help/enterprise`, `/help/tutorials`, `/help/glossary`, `/help/storage`, `/docs`, `/docs/view/{doc_path}` |
| user | `/dashboard`, `/tools`, `/tools/{tool_name}/execute`, `/tools/{tool_name}/schema`, `/tools/{tool_name}/config`, `/prompts`, `/prompts/{prompt_name}`, `/prompts/{prompt_name}/test`, `/prompts/category/{category}`, `/prompts/tag/{tag}`, `/reports`, `/composite/builder`, `/ai/settings`, `/ask`, `/studio`, `/studio/rest`, `/studio/dbquery`, `/studio/script`, `/studio/livelink`, `/studio/olap`, `/studio/powerbi`, `/studio/powerbidax`, `/studio/sharepoint`, `/studio/examples` |
| admin | `/admin/users`, `/admin/users/create`, `/admin/tools`, `/admin/system-monitor`, `/admin/prompts`, `/admin/async-tasks`, `/admin/apikeys`, `/admin/apikeys/create`, `/admin/apikeys/{key_id}/view`, `/prompts/create`, `/monitoring/tools`, `/monitoring/users` |

---

## 5. Error format

**REST (JSON) routes.** Handlers return an HTTP status with a JSON body of the form `{"error": "message"}`; prompt and some admin routes use `{"success": false, "error": "message"}`. Successful writes usually return `{"success": true, ...}`.

Framework-level responses (`sajha/app.py`, `sajha/security.py`):

| Status | When | Body |
|---|---|---|
| 401 | `user`/`admin` route without a valid credential, path starting with `/api/` or `/mcp` | `{"error": "Authentication required"}` |
| 302 | Same, any other path (pages, `/admin/apikeys/*`) | Redirect to `/` |
| 403 | `admin` route called by a non-admin | HTML error page (also for `/api/...` paths) |
| 404 | No such route | HTML error page. Route handlers' own 404s (unknown tool, user, prompt...) are JSON. |
| 413 | `Content-Length` over 10 MB | `{"error": "Request body too large. Maximum: 10485760 bytes"}` |
| 422 | Query/path parameter of the wrong type (e.g. `days=abc`) | FastAPI's `{"detail": [...]}` |
| 429 | Login rate limit | `{"error": "Too many login attempts. Try again in 60 seconds."}` |
| 500 | Unhandled exception | HTML error page |

**MCP endpoints.** JSON-RPC 2.0 error objects: `{"jsonrpc": "2.0", "id": ..., "error": {"code": ..., "message": ...}}`. HTTP statuses used by the transport: 400 (parse error `-32700`, invalid request or batch `-32600`, missing `Mcp-Session-Id` on DELETE, unsupported `MCP-Protocol-Version`), 403 (disallowed `Origin`, `-32000`), 404 (unknown session, `-32001`), 405 (GET/DELETE where no stream or session exists). The 2026-07-28 path adds `-32020` (header/body mismatch) and `-32022` (unsupported protocol version). Authorization failures are OAuth challenges, not JSON-RPC errors: `{"error": "invalid_token" | "insufficient_scope" | "unauthorized", "error_description": "..."}` with a `WWW-Authenticate: Bearer resource_metadata="...", scope="..."` header.

**OAuth endpoints.** RFC 6749 style `{"error": "...", "error_description": "..."}` with `Cache-Control: no-store`; `{"error": "not_found"}` with 404 when OAuth is off. Authorization errors that cannot safely redirect (unknown client, redirect URI mismatch) render an HTML error page.

See also: [Security Model](../security/Security%20Model.md), [Configuration Reference](../getting-started/Configuration%20Reference.md), [Client SDK Guide](../clients/Client%20SDK%20Guide.md).

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
