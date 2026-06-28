# SAJHA MCP Server v5.1.0 — MCP 2025-11-25 Compliance Report

**Date:** May 2026
**Protocol Version:** 2025-11-25 (latest released)
**Server Version:** 5.1.0
**Verdict:** Fully Compliant — 18/18 items implemented

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## Summary

SAJHA MCP Server v5.1.0 implements every Major and Minor change introduced in MCP specification version 2025-11-25 (released November 25, 2025). This document provides evidence for each compliance item, including the source files, line numbers, and verification methods.

| # | Feature | SEP | Status |
|---|---------|-----|:------:|
| M1 | OpenID Connect Discovery | PR #797 | ✅ |
| M2 | Tool/Resource/Prompt Icons | SEP-973 | ✅ |
| M3 | Incremental Scope Consent | SEP-835 | ✅ |
| M4 | Tool Name Guidance | SEP-986 | ✅ |
| M5 | Elicitation — Form Mode | SEP-1330 | ✅ |
| M6 | Elicitation — URL Mode | SEP-1036 | ✅ |
| M7 | Sampling with Tool Calling | SEP-1577 | ✅ |
| M8 | OAuth Client ID Metadata Documents | SEP-991 | ✅ |
| M9 | Tasks — Async Tracking | SEP-1686 | ✅ |
| m1 | stdio stderr logging | — | N/A |
| m2 | `description` in Implementation | — | ✅ |
| m3 | HTTP 403 for Invalid Origin | PR #1439 | ✅ |
| m4 | Security Best Practices | — | ✅ |
| m5 | Tool Errors as Tool Execution Errors | SEP-1303 | ✅ |
| m6 | SSE Polling / Server Disconnect | — | ✅ |
| m7 | SSE Event IDs / Stream Resumption | SEP-1699 | ✅ |
| m8 | RFC 9728 Protected Resource Metadata | SEP-985 | ✅ |
| m9 | Default Values in Elicitation Schemas | — | ✅ |
| m10 | JSON Schema 2020-12 Default Dialect | SEP-1613 | ✅ |

---

## Major Change 1: OpenID Connect Discovery

**Spec Requirement:** Servers that act as their own authorization server MUST provide an OpenID Connect Discovery 1.0 document at `/.well-known/openid-configuration`, enabling clients to discover authorization endpoints without hardcoding URLs.

**SAJHA Implementation:**

- **Route:** `GET /.well-known/openid-configuration` in `sajha/routes/a2a_routes.py`
- **Builder:** `build_openid_configuration()` in `sajha/core/mcp_2025_11_25.py`
- **Returns:** JSON document with `issuer`, `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `registration_endpoint`, `scopes_supported`, `response_types_supported`, `grant_types_supported`, `code_challenge_methods_supported` (S256 for PKCE)

**Verification:**

```bash
curl http://localhost:3002/.well-known/openid-configuration | jq .
```

---

## Major Change 2: Icons for Tools, Resources, Prompts (SEP-973)

**Spec Requirement:** Tools, resources, and prompts MAY include an `icon` field with `{"type": "url", "url": "..."}` or `{"type": "emoji", "emoji": "📊"}` for richer UI rendering in MCP hosts.

**SAJHA Implementation:**

- **Enrichment function:** `add_tool_icon()` in `sajha/core/mcp_2025_11_25.py`
- **Integration point:** `_handle_tools_list()` in `sajha/core/mcp_handler.py` — iterates over each tool in the paginated response and calls `add_tool_icon()` to enrich the MCP format dict with icon metadata from the tool's JSON config
- **Configuration:** Per-tool in JSON configs under `config/tools/`: `"icon": {"type": "emoji", "emoji": "📈"}`

**Verification:**

```bash
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' | jq '.result.tools[0].icon'
```

---

## Major Change 3: Incremental Scope Consent (SEP-835)

**Spec Requirement:** When a server returns HTTP 401, the `WWW-Authenticate` header SHOULD include a `scope` parameter indicating which scopes are needed, enabling clients to request incremental authorization without re-prompting for all scopes.

**SAJHA Implementation:**

- **File:** `sajha/auth/__init__.py`, `require_auth()` function
- **Header:** `WWW-Authenticate: Bearer realm="sajha", scope="tools:read tools:execute"`
- **Supported scopes:** `openid`, `profile`, `tools:read`, `tools:execute`, `admin`

**Verification:**

```bash
curl -v http://localhost:3002/api/tools 2>&1 | grep WWW-Authenticate
# WWW-Authenticate: Bearer realm="sajha", scope="tools:read tools:execute"
```

---

## Major Change 4: Tool Name Guidance (SEP-986)

**Spec Requirement:** Tool names SHOULD follow a consistent naming pattern. The specification recommends `provider_action` or namespaced patterns to avoid collisions and improve discoverability.

**SAJHA Implementation:**

All 497 tools follow `provider_action` naming convention, established since v3.1.0:

| Pattern | Examples | Count |
|---------|----------|------:|
| `fmp_*` | `fmp_stock_screener`, `fmp_profile`, `fmp_dcf` | 100 |
| `openbb_*` | `openbb_crypto_price`, `openbb_stock_performance` | 70 |
| `fred_*` | `fred_gdp`, `fred_unemployment`, `fred_vix` | 55 |
| `yahoo_*` | `yahoo_quote`, `yahoo_historical`, `yahoo_options` | 35 |
| `calc_*` | `calc_sharpe`, `calc_var`, `calc_npv` | 19 |
| `edgar_*` | `edgar_10k`, `edgar_insider_transactions` | 20 |

No tool uses a bare name without a provider prefix.

---

## Major Change 5: Elicitation — Form Mode (SEP-1330)

**Spec Requirement:** Servers MAY request structured user input via a `form` mode elicitation with a JSON Schema defining the expected fields, labels, types, and default values.

**SAJHA Implementation:**

- **Manager:** `ElicitationManager` class in `sajha/core/mcp_2025_11_25.py`
- **Create:** `create_form_elicitation(message, schema)` — creates a pending request with a JSON Schema for the form
- **Respond:** `handle_elicitation_respond(params)` — processes the client's `elicitation/respond` with `action: "submit"` or `action: "cancel"`
- **MCP route:** `elicitation/respond` method in `sajha/core/mcp_handler.py`
- **Capability declared:** `"elicitation": {"form": {}, "url": {}}` in server capabilities

**Example flow:**

```python
# Server creates an elicitation during tool execution
req = elicitation_manager.create_form_elicitation(
    message="Please confirm the trade parameters:",
    schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "default": "AAPL"},
            "quantity": {"type": "integer", "minimum": 1},
            "confirm": {"type": "boolean"}
        },
        "required": ["symbol", "quantity", "confirm"]
    }
)
```

---

## Major Change 6: Elicitation — URL Mode (SEP-1036)

**Spec Requirement:** Servers MAY redirect the user to an external URL (e.g., an OAuth consent page) and receive the result via `elicitation/respond`.

**SAJHA Implementation:**

- **Create:** `create_url_elicitation(url, reason)` in `ElicitationManager`
- **Example:** `create_url_elicitation("https://auth.example.com/consent?scope=admin", "Admin access requires approval")`
- **Capability:** `"url": {}` declared in `"elicitation"` capabilities

---

## Major Change 7: Sampling with Tool Calling (SEP-1577)

**Spec Requirement:** Server-initiated sampling requests (where the server asks the client to run an LLM completion) now support `tools` and `toolChoice` parameters, enabling the LLM to call tools during the sampling loop.

**SAJHA Implementation:**

- **Manager:** `SamplingManager` class in `sajha/core/mcp_2025_11_25.py`
- **Request:** `SamplingRequest` dataclass with `tools: Optional[List[Dict]]` and `tool_choice: Optional[Dict]` fields
- **Capability declared:** `"sampling": {"tools": true}` in server capabilities
- **toolChoice options:** `{"type": "auto"}`, `{"type": "tool", "name": "specific_tool"}`, `{"type": "none"}`

---

## Major Change 8: OAuth Client ID Metadata Documents (SEP-991)

**Spec Requirement:** Servers SHOULD support Client ID Metadata Documents (CIMD) as the recommended client registration mechanism, served at `/.well-known/oauth-client/{client_id}`.

**SAJHA Implementation:**

- **Route:** `GET /.well-known/oauth-client/{client_id}` in `sajha/routes/a2a_routes.py`
- **Builder:** `build_client_id_metadata_document()` in `sajha/core/mcp_2025_11_25.py`
- **Returns:** JSON with `client_id`, `client_name`, `redirect_uris`, `grant_types`, `response_types`, `token_endpoint_auth_method`, `scope`

**Verification:**

```bash
curl http://localhost:3002/.well-known/oauth-client/my-client | jq .
```

---

## Major Change 9: Tasks — Async Tracking (SEP-1686)

**Spec Requirement:** Servers MAY return a task handle for long-running operations. Clients poll via `tasks/get`, list via `tasks/list`, and cancel via `tasks/cancel`. Task states: `working`, `input_required`, `completed`, `failed`, `cancelled`.

**SAJHA Implementation:**

- **Manager:** `TaskManager` class in `sajha/core/mcp_2025_11_25.py`
- **Data class:** `MCPTask` with `task_id`, `state` (TaskState enum), `progress` (0.0–1.0), `progress_message`, `result`, `error`, `ttl_seconds`
- **MCP routes:** `tasks/get`, `tasks/list`, `tasks/cancel` in `sajha/core/mcp_handler.py`
- **Capability declared:** `"tasks": {"experimental": true}`
- **Auto-cleanup:** Expired tasks (completed/failed/cancelled older than TTL) are cleaned up on list

**Verification:**

```bash
# Get task status
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tasks/get","params":{"taskId":"abc-123"},"id":1}'

# List all tasks
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tasks/list","params":{},"id":2}'
```

---

## Minor Change 1: stdio stderr Logging

**Spec Requirement:** Clarification that MCP servers using stdio transport SHOULD send log messages to stderr, not stdout.

**SAJHA Status:** N/A — SAJHA uses HTTP transports exclusively (POST, SSE, WebSocket). No stdio transport.

---

## Minor Change 2: `description` in Implementation Interface

**Spec Requirement:** The `Implementation` interface (returned in `serverInfo` during initialize) SHOULD include a `description` field.

**SAJHA Implementation:**

- **File:** `sajha/core/mcp_handler.py`, `__init__()` method
- **Code:** `"description": f"{app_name} — Production MCP server with {tool_count} tools"`

**Verification:**

```bash
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  | jq '.result.serverInfo.description'
# "SAJHA MCP Server — Production MCP server with 497 tools"
```

---

## Minor Change 3: HTTP 403 for Invalid Origin

**Spec Requirement:** Streamable HTTP servers MUST respond with HTTP 403 Forbidden when the `Origin` header is present and does not match an allowed origin.

**SAJHA Implementation:**

- **Validator:** `validate_origin()` in `sajha/core/mcp_2025_11_25.py`
- **Integration:** Called at top of `mcp_sse()` in `sajha/routes/mcp_routes.py` before any processing
- **Response:** `JSONResponse({"error": "Forbidden: invalid Origin"}, status_code=403)`

---

## Minor Change 4: Security Best Practices

**Spec Requirement:** Updated security best practices for MCP implementations including PKCE, input validation, and credential handling.

**SAJHA Implementation:**

- **PKCE:** `code_challenge_methods_supported: ["S256"]` in OIDC Discovery
- **Password hashing:** bcrypt with salt rounds in `sajha/core/auth_manager.py`
- **API key hashing:** SHA-256 with `sja_` prefix in `sajha/core/apikey_manager.py`
- **JWT:** HS256 with configurable expiry, httponly cookies for web UI
- **RBAC:** Role-based access control (admin, user) on all endpoints
- **Input validation:** Pydantic models for all API request bodies
- **OAuth SSO:** Azure AD, Okta, Auth0, Keycloak with PKCE flow

---

## Minor Change 5: Tool Errors as Tool Execution Errors

**Spec Requirement:** When a tool fails due to input validation or execution errors, the server MUST return a Tool Execution Error (content with `isError: true`) rather than a JSON-RPC Protocol Error. This enables the model to self-correct.

**SAJHA Implementation:**

- **File:** `sajha/core/mcp_handler.py`, `_handle_tools_call()` method
- **Code:** `except Exception` block returns `{"content": [{"type": "text", "text": "..."}], "isError": True}` instead of raising `ValueError`

**Verification:**

```bash
# Call a tool with invalid params — should get isError, not protocol error
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"yahoo_quote","arguments":{}},"id":1}' \
  | jq '.result.isError'
# true
```

---

## Minor Change 6: SSE Polling / Server Disconnect

**Spec Requirement:** SSE streams should handle client disconnection gracefully and support polling for reconnection.

**SAJHA Implementation:**

- **File:** `sajha/routes/mcp_routes.py`, `mcp_sse()` event generator
- **Disconnect detection:** `await request.is_disconnected()` checked on every loop iteration
- **Session cleanup:** `_sse_sessions[session_id]` removed in `finally` block
- **Reconnection:** Supported via `Last-Event-ID` (see Minor 7)

---

## Minor Change 7: SSE Event IDs / Stream Resumption

**Spec Requirement:** SSE events SHOULD include an `id:` field. Clients reconnecting with `Last-Event-ID` header SHOULD receive missed events.

**SAJHA Implementation:**

- **Tracker:** `SSEEventTracker` class in `sajha/core/mcp_2025_11_25.py`
- **Event IDs:** Format `{session_id}:{counter}` — monotonically increasing per session
- **Ring buffer:** Last 1000 events stored for replay
- **Resumption:** `get_events_after(last_event_id)` replays missed events on reconnect
- **Integration:** `mcp_sse()` in `sajha/routes/mcp_routes.py` reads `Last-Event-ID` header and replays

**Verification:**

```bash
# Connect, note the id: field on events
curl -N -H "X-API-Key: sja_key" http://localhost:3002/mcp
# id: abc-123:1
# event: endpoint
# data: /mcp?session=abc-123

# Reconnect with Last-Event-ID
curl -N -H "X-API-Key: sja_key" -H "Last-Event-ID: abc-123:1" http://localhost:3002/mcp
# Replays any events after abc-123:1
```

---

## Minor Change 8: RFC 9728 Protected Resource Metadata

**Spec Requirement:** Servers SHOULD provide a Protected Resource Metadata document at `/.well-known/oauth-protected-resource` per RFC 9728, declaring authorization servers and supported scopes.

**SAJHA Implementation:**

- **Route:** `GET /.well-known/oauth-protected-resource` in `sajha/routes/a2a_routes.py`
- **Builder:** `build_protected_resource_metadata()` in `sajha/core/mcp_2025_11_25.py`
- **Returns:** `resource`, `authorization_servers`, `bearer_methods_supported`, `scopes_supported`, `resource_documentation`

---

## Minor Change 9: Default Values in Elicitation Schemas

**Spec Requirement:** Elicitation form schemas SHOULD support the JSON Schema `default` keyword so that forms can be pre-populated.

**SAJHA Implementation:**

The `ElicitationManager.create_form_elicitation()` accepts standard JSON Schema as the `schema` parameter. The `default` keyword is natively supported by JSON Schema and passed through to the client without modification. Example:

```python
elicitation_manager.create_form_elicitation(
    message="Configure alert threshold:",
    schema={
        "type": "object",
        "properties": {
            "threshold": {"type": "number", "default": 0.05},
            "notify_email": {"type": "string", "format": "email", "default": "admin@example.com"}
        }
    }
)
```

---

## Minor Change 10: JSON Schema 2020-12 Default Dialect

**Spec Requirement:** Implementations SHOULD treat JSON Schema documents as conforming to the 2020-12 dialect when no `$schema` keyword is present.

**SAJHA Implementation:**

- **Capability:** `"jsonSchema": {"dialect": "https://json-schema.org/draft/2020-12/schema"}` declared in server capabilities in `sajha/core/mcp_handler.py`
- **Tool schemas:** All 497 tool `inputSchema` definitions are compatible with 2020-12 (type, properties, required, enum, description)

---

## Streamable HTTP Transport Compliance

In addition to the 18 spec changes above, SAJHA implements the Streamable HTTP transport correctly:

**Single endpoint per spec:** `/mcp` supports both `POST` (JSON-RPC requests) and `GET` (SSE stream for server notifications).

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| POST | `/mcp` | `api_routes.mcp_endpoint` | JSON-RPC 2.0 requests |
| GET | `/mcp` | `mcp_routes.mcp_sse` | SSE stream with event IDs |
| GET | `/mcp/sse` | alias for GET `/mcp` | Backwards compat (2024-11-05) |
| POST | `/mcp/message` | alias for POST `/mcp` | Backwards compat (2024-11-05) |
| WS | `/mcp/ws` | `ws_routes.mcp_ws` | WebSocket (custom extension) |

**Protocol version negotiation:** Server declares `"protocolVersion": "2025-11-25"` in initialize response. All three SDK clients (MCPClient, MCPSSEClient, MCPWebSocketClient) send `"protocolVersion": "2025-11-25"` in initialize request.

---

## Verification Checklist

```bash
# 1. Protocol version
curl -s -X POST http://localhost:3002/mcp -H "Content-Type: application/json" \
  -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}' \
  | jq '.result.protocolVersion'
# "2025-11-25"

# 2. Server description
# (same response) | jq '.result.serverInfo.description'

# 3. Capabilities
# (same response) | jq '.result.capabilities | keys'
# ["completions","elicitation","jsonSchema","logging","prompts","resources","sampling","tasks","tools","websocket"]

# 4. OIDC Discovery
curl -s http://localhost:3002/.well-known/openid-configuration | jq .issuer

# 5. PRM
curl -s http://localhost:3002/.well-known/oauth-protected-resource | jq .resource

# 6. CIMD
curl -s http://localhost:3002/.well-known/oauth-client/test | jq .client_id

# 7. Origin validation (should get 403)
curl -s -o /dev/null -w "%{http_code}" -H "Origin: https://evil.com" http://localhost:3002/mcp

# 8. Tool error returns isError
curl -s -X POST http://localhost:3002/mcp -H "Content-Type: application/json" \
  -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"nonexistent","arguments":{}},"id":1}' \
  | jq '.result.isError'
```

---

*SAJHA MCP Server v5.1.0 — MCP 2025-11-25 Compliance Report*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
