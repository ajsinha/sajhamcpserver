# SAJHA MCP Server — MCP 2025-11-25 Compliance Report

**Scope:** the handshake-era ("legacy") path of SAJHA's dual-era `/mcp` endpoint: protocol versions 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05 (legacy HTTP+SSE). The stateless 2026-07-28 path is covered by [MCP 2026-07-28 Compliance](MCP%202026-07-28%20Compliance.md); how the two fit together is in the [MCP Protocol Guide](MCP%20Protocol%20Guide.md).
**Transport:** Streamable HTTP on `/mcp` (plus legacy HTTP+SSE and a WebSocket extension); stdio for desktop clients ([MCP Protocol Guide §4](MCP%20Protocol%20Guide.md#stdio))
**Verified with:** the official conformance suite, `@modelcontextprotocol/conformance` 0.1.16, and the official Python SDK client (`mcp` 2.3.0)

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## 1. How compliance is verified

Earlier versions of this document claimed "18/18 items implemented" based on code
inspection alone. Several of those claims were wrong (see §6). Every claim below
is now checked by automated tests.

### 1.1 Official conformance suite

The suite acts as an MCP client against a running server. Many of its scenarios
call fixed test fixtures (`test_simple_text`, `test_simple_prompt`,
`test://static-text`, ...). SAJHA ships those fixtures in
`sajha/core/mcp_conformance_fixtures.py`. They are **off by default**, and you turn
them on only for protocol testing:

```bash
# 1. start the server with the conformance fixtures enabled
SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_server.py --host 127.0.0.1 --port 3092

# 2. run every server scenario for spec 2025-11-25
npx -y @modelcontextprotocol/conformance@0.1.16 server \
    --url http://127.0.0.1:3092/mcp --spec-version 2025-11-25 --suite all
```

**Result: 32/32 scenarios pass, with 43 checks passed and 0 failed.**

| Scenario | Result |
|---|:-:|
| server-initialize, ping, logging-set-level, completion-complete | ✅ |
| tools-list, json-schema-2020-12 | ✅ |
| tools-call-simple-text / image / audio / embedded-resource / mixed-content / error | ✅ |
| tools-call-with-logging, tools-call-with-progress (notifications streamed over SSE) | ✅ |
| tools-call-sampling, tools-call-elicitation (server→client requests over SSE) | ✅ |
| elicitation-sep1034-defaults, elicitation-sep1330-enums | ✅ |
| server-sse-multiple-streams, server-sse-polling | ✅ (see note) |
| resources-list, resources-read-text, resources-read-binary, resources-templates-read | ✅ |
| resources-subscribe, resources-unsubscribe | ✅ |
| prompts-list, prompts-get-simple / with-args / embedded-resource / with-image | ✅ |
| dns-rebinding-protection | ✅ |

Notes:
- **server-sse-polling.** This scenario reports only informational checks. SAJHA does not
  implement the optional `test_reconnection` tool, which closes a stream mid-call and
  resumes it on a GET with `Last-Event-ID`.
- **Without the fixtures (production default).** 12 of the 32 scenarios pass and 20 fail.
  Every one of the 20 fails only because the named test tool, prompt or resource does
  not exist (for example `Tool not found: test_simple_text`). None of them is a protocol
  failure.

### 1.2 Official SDK client

The official Python SDK (`mcp` 2.3.0, `streamable_http_client` + `ClientSession`) was
run against the server with its default configuration. These operations all succeeded:
- `initialize`
- `tools/list` (paginated)
- `ping`
- `tools/call` (the SDK validated `structuredContent` against the tool's `outputSchema`)
- `prompts/list`
- `resources/list`
- `logging/setLevel`

### 1.3 Unit and integration tests

`tests/test_mcp_2025_11_25.py` (FastAPI TestClient) covers:
- version negotiation
- session lifecycle
- 202 responses for notifications
- batch rejection
- the Origin and `MCP-Protocol-Version` headers
- DELETE and GET semantics
- JSON-RPC error shapes
- prompts `id` and arguments
- `structuredContent`, icons and capabilities
- the removed OAuth documents

```bash
python -m pytest -q tests/test_mcp_2025_11_25.py
```

---

## 2. Lifecycle and protocol

| Requirement | Status | Implementation |
|---|:-:|---|
| Version negotiation: echo the client's `protocolVersion` if supported, else offer the latest | ✅ | `negotiate_protocol_version()` in `sajha/core/mcp_2025_11_25.py`; `_handle_initialize()` in `sajha/core/mcp_handler.py` |
| `notifications/initialized` accepted (the legacy bare `initialized` is still accepted) | ✅ | `MCPHandler.handle_request` |
| `ping` result is `{}` | ✅ | `_handle_ping` |
| Every response carries the request `id`; errors carry `"id": null` when the id is unknown | ✅ | `_create_success_response` / `_create_error_response` |
| `initialize` result has `serverInfo` (`name`, `title`, `version`, `description`, `websiteUrl`) and `instructions` | ✅ | `MCPHandler.__init__` |
| Errors are JSON-RPC errors, never `{"error": ...}` inside a result | ✅ | `MCPError`; used by tasks, elicitation, logging, prompts and resources |
| Unknown tool / unknown prompt → `-32602`; unknown resource → `-32002` | ✅ | `_handle_tools_call`, `handle_prompts_get`, `_handle_resources_read` |
| Tool failures are returned as results with `isError: true` | ✅ | `_handle_tools_call` |

### Server capabilities (as advertised on Streamable HTTP `initialize`)

```json
{
  "tools":     {"listChanged": false},
  "prompts":   {"listChanged": false},
  "resources": {"subscribe": false, "listChanged": false},
  "logging": {},
  "completions": {},
  "experimental": {"sajha": {"websocket": {"endpoint": "/mcp/ws", "authMethods": ["token", "api_key"]},
                             "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema"}}
}
```

- `elicitation` and `sampling` are **client** capabilities and are no longer advertised
  by the server.
- `tasks` is not advertised. The `tasks/get|list|cancel` methods exist, but tool calls
  are never task-augmented, and the task object does not follow the 2025-11-25 shape.
- `listChanged` and `subscribe` are `false` on Streamable HTTP sessions because
  there is no push channel (`GET /mcp` is 405). `initialize` over the legacy
  `/mcp/sse` and `/mcp/ws` streams advertises `listChanged: true`, and those streams
  receive the change-bus notifications. `resources/subscribe` and
  `resources/unsubscribe` are still accepted and return `{}`.
- SAJHA-specific settings now live under `experimental`.

## 3. Streamable HTTP transport (`/mcp`)

| Behaviour | Status |
|---|:-:|
| `POST /mcp` request → `application/json` response | ✅ |
| `POST /mcp` notification or client response (no `id` / no `method`) → **202 Accepted**, empty body | ✅ |
| `POST /mcp` JSON array → **400**, `-32600` (batching was removed in 2025-06-18; the WebSocket transport still accepts batches as a SAJHA extension) | ✅ |
| `initialize` response sets the **`Mcp-Session-Id`** header | ✅ |
| Request with an unknown `Mcp-Session-Id` → **404** (the client should re-initialize) | ✅ |
| `DELETE /mcp` → **204**, or **404** for an unknown session, or 400 without the header | ✅ |
| `MCP-Protocol-Version` header with an unsupported value → **400** | ✅ |
| Origin validation → **403** for a disallowed `Origin` (POST, GET and DELETE `/mcp`, plus `/mcp/message`) | ✅ |
| Tools that talk to the client while running stream an SSE response: a priming event, then notifications and server→client requests, then the result. Clients answer by POSTing JSON-RPC responses. | ✅ (used by the conformance fixtures) |
| `Access-Control-Expose-Headers: Mcp-Session-Id` (CORS) | ✅ |

**GET `/mcp`.** SAJHA has no unsolicited server→client messages to push. A GET that
carries `Mcp-Session-Id` or `MCP-Protocol-Version` (a Streamable HTTP client) therefore
gets **405 Method Not Allowed**, which the spec allows. A GET without those headers,
and every `GET /mcp/sse`, still opens the legacy 2024-11-05 HTTP+SSE stream (an
`endpoint` event, then messages). Legacy clients POSTing to `/mcp?session=<id>` get 202,
and their response is delivered on that SSE stream.

**Sessions** are kept in the state store (`sajha/core/mcp_sessions.py`): process memory by
default, so a restart invalidates them and clients get 404 and re-initialize. With a shared
backend every worker knows them ([Scaling and State](../architecture/Scaling%20and%20State.md)). Requests without a session
header are still accepted, which keeps simple `curl` clients working. Whether `/mcp`
demands credentials depends on `mcp.auth.mode` (§8). `tools/list` and `tools/call` apply
the caller's tool access (`sajha/auth/access.py`; a refused call is `-32002`): users by
their roles, API keys by their access mode, anonymous callers by `mcp.anonymous.*`. See
[Tool access](../security/Security%20Model.md#tool-access).

**Origin policy** is set by `mcp.allowed_origins` in `config/application.yml`, or the
`SAJHA_MCP_ALLOWED_ORIGINS` environment variable (comma-separated):
- Requests with no `Origin` header (non-browser clients) are always allowed.
- `http(s)://localhost`, `127.0.0.1` and `[::1]` on any port are always allowed.
- Any other origin must be listed exactly. Use `"*"` to disable the check.

## 4. Tools

`tools/list` entries contain:
- `name`, `description` and `inputSchema`. The schema is passed through untouched, so
  2020-12 keywords such as `$schema`, `$defs` and `additionalProperties` are preserved.
- `title`, when configured.
- `outputSchema`, when it is an object schema.
- `annotations`, when configured.
- `icons`, the spec array `[{src, mimeType?, sizes?}]`. It is built from a tool
  config's `icons` list or its legacy `icon` setting; emoji icons become SVG data URIs.

`tools/call`:
- A string result is returned as a text block.
- A list of content blocks is returned as-is.
- Any other JSON value is serialised as JSON text.
- When the tool advertises an `outputSchema` and returns a JSON object, the object is
  also returned as **`structuredContent`**. The server validates it with `jsonschema`
  and logs a warning on mismatch.
- Advertising can be switched off with `mcp.tools.advertise_output_schema: false` if a
  tool's schema does not match its real output.

## 5. Prompts, resources, completion, logging

- **`prompts/list`** returns each prompt's `arguments` (`name`, `description`, `required`).
- **`prompts/get`** returns `messages`, plus `description` when present. A missing
  required argument or an unknown prompt returns `-32602`.
- **`resources/read`** returns `-32002` for an unknown URI, instead of a fake text body.
- **`completion/complete`**:
  - Works for `ref/prompt`. A crash caused by the `Prompt` object was fixed.
  - Works for `ref/tool` enum values.
- **`logging/setLevel`**:
  - Accepts the RFC 5424 levels (`debug` … `emergency`).
  - Returns `-32602` for anything else.

## 6. Corrections to earlier claims

| Earlier claim | Reality and resolution |
|---|---|
| OIDC Discovery at `/.well-known/openid-configuration` | SAJHA is not an OAuth/OIDC provider, and the document advertised `/oauth/authorize`, `/oauth/token`, `/oauth/jwks` and `/oauth/register`, none of which exist. **Removed (404).** |
| RFC 9728 PRM at `/.well-known/oauth-protected-resource` | It pointed at the same non-existent authorization server. **Removed (404).** MCP clients read a 404 as "no OAuth". |
| CIMD at `/.well-known/oauth-client/{id}` | Client ID Metadata Documents are hosted by *clients*, not servers. **Removed (404).** |
| Server capability `elicitation`, `sampling: {tools: true}` | These are client capabilities. **Removed.** Server→client sampling and elicitation are demonstrated by the conformance fixtures, which check the *client's* capabilities. |
| `tasks: {experimental: true}` | Not the 2025-11-25 shape, and tool calls never create tasks. **Removed from capabilities.** |
| `elicitation/respond` method | This is not an MCP method. In MCP the client answers `elicitation/create` with a JSON-RPC response. It is kept as a SAJHA extension and now returns proper JSON-RPC errors. |
| Icons as `icon: {type, url/emoji}` | Non-spec shape. **Replaced** by the `icons` array. |
| Origin validation (HTTP 403) | It used to be a no-op (no allow-list, and it was never called on POST). **Now enforced** on POST, GET and DELETE `/mcp`. |
| Incremental scope consent (`WWW-Authenticate … scope=`) | Was informational only in 5.4.0. **Now real** on `/mcp` when `mcp.auth.mode` is `optional`/`required` (§8): 401 challenges carry `resource_metadata` and `scope`, and a token lacking a scope gets 403 `insufficient_scope`. |
| "Security best practices: PKCE, OAuth SSO (Azure/Okta/…)" | **Now real** (§8): a built-in OAuth 2.1 authorization server with mandatory PKCE S256, or validation of tokens from an external IdP. Password hashing (bcrypt), API-key hashing (SHA-256), JWT and RBAC are unchanged. |
| SSE event IDs and resumption (`Last-Event-ID`) | Event IDs exist on the legacy stream and on SSE tool-call streams. Replay on reconnect is **not** implemented: a stream belongs to one connection, and `Last-Event-ID` is ignored. |
| `ping` returned `{status, timestamp}`; prompts responses had no `id`; JSON array bodies returned 500; `notifications/initialized` returned `-32601` | **Fixed** (§2, §3). |

## 7. Not implemented on this path

- A task-augmented `tools/call` and the 2025-11-25 `tasks/*` shapes, including `tasks/result`.
- `notifications/*/list_changed` and `resources/updated` delivery on Streamable HTTP sessions (a GET stream would be needed). The legacy `/mcp/sse` and `/mcp/ws` streams do receive them from the change bus, and advertise `listChanged: true`.
- SSE stream resumption (`Last-Event-ID` replay) and the `test_reconnection` behaviour (SEP-1699 polling).
- Progress and logging notifications from regular SAJHA tools on this path. Today only the
  conformance fixtures stream them here; on the 2026-07-28 path every tool can (`sajha.core.mcp_tool_context`).

## 8. Authorization

The 2025-11-25 authorization spec is implemented on the legacy path exactly as on the 2026-07-28 path; the full description (modes, token validation, built-in authorization server, CIMD/DCR, security decisions) is in [MCP 2026-07-28 Compliance §4.1](MCP%202026-07-28%20Compliance.md) and the [OAuth Guide](OAuth%20Guide.md). In short:

- `mcp.auth.mode`: `off` (default, behaviour of 5.4.0/6.0.0: the `/.well-known/oauth-*` documents stay 404), `optional`, `required`.
- With OAuth on, the PRM document (RFC 9728) is served again — now pointing at an authorization server that exists: SAJHA's built-in one (`/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`, `/oauth/jwks`, `/oauth/register` only with DCR enabled) or the external issuer in `mcp.auth.authorization_server`. OIDC discovery stays 404 (no ID tokens), and CIMD documents are still client-hosted: SAJHA *fetches* them (`client_id_metadata_document_supported: true`).
- Bearer tokens on `POST /mcp` (including `initialize`), `GET /mcp/sse`, `POST /mcp/message` and `DELETE /mcp` are validated for signature, issuer, audience (RFC 8707: this server's `/mcp` resource URI), expiry and scope. API keys and SAJHA JWTs keep working in every mode.
- Verified with the conformance `authorization` scenarios (3/3 checks, `--spec-version 2025-11-25`) and the official SDK's `OAuthClientProvider` in `mode="legacy"`. `tests/test_mcp_auth.py` covers it.

---

*SAJHA MCP Server — MCP 2025-11-25 Compliance Report*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
