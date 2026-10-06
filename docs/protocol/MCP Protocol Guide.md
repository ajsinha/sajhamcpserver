# MCP Protocol Guide

How SAJHA speaks the [Model Context Protocol](https://modelcontextprotocol.io): which
protocol versions it serves, how it decides which one a request uses, what each
transport is for, and where the details live. This guide owns the *how it works*
picture. The evidence (requirement-by-requirement tables, conformance results,
known limits) lives in the two compliance reports:

- [MCP 2026-07-28 Compliance](MCP%202026-07-28%20Compliance.md): the stateless path,
  streaming, `subscriptions/listen`, MRTR, the tasks extension, authorization, MCP Apps.
- [MCP 2025-11-25 Compliance](MCP%202025-11-25%20Compliance.md): the session path and
  the legacy transports.

Authorization has its own guide ([OAuth Guide](OAuth%20Guide.md)), and so do the two
2026-07-28 extensions to tool metadata ([MCP Apps and Headers Guide](MCP%20Apps%20and%20Headers%20Guide.md)).
The REST mirror of these methods is in the [API Reference](API%20Reference.md).

---

## 1. One endpoint, two eras

SAJHA is a **dual-era** server. The same `POST /mcp` endpoint (also answered at
`/api/mcp`) serves:

| Era | Protocol versions | Shape |
|---|---|---|
| **Modern** | 2026-07-28 | Stateless. Every request carries its own context in `params._meta`. No handshake, no session. |
| **Legacy** | 2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05 | `initialize` handshake, then an `Mcp-Session-Id` session. |

The authoritative version lists are code constants: `MODERN_PROTOCOL_VERSIONS` in
`sajha/core/mcp_modern.py` and `SUPPORTED_PROTOCOL_VERSIONS` in
`sajha/core/mcp_2025_11_25.py`. A modern client can also ask: `server/discover`
returns `supportedVersions`, newest first.

### How a request is routed

`sajha/routes/mcp_routes.py::mcp_post` calls `mcp_modern.is_modern_request()`:

1. `params._meta` carries `io.modelcontextprotocol/protocolVersion` → **modern**
   (even for `initialize`, which the modern path does not serve).
2. No such key, but an `MCP-Protocol-Version` header names a non-handshake version
   → **modern**, so the modern validation ladder can reject it properly.
3. Everything else → **legacy**, exactly as a 2025-11-25 server behaves.

Both paths share one implementation of tools, prompts, resources and completion
(`MCPHandler` in `sajha/core/mcp_handler.py`); the modern path
(`sajha/core/mcp_modern.py`) owns only the 2026-07-28 envelope. A tool therefore
behaves the same whichever era calls it, and every call goes through the same
execution path as the REST API (enabled check, argument validation, output cache,
circuit breaker, metrics).

```
                  POST /mcp  (Origin check → authorization → era detection)
                        │
        ┌───────────────┴────────────────┐
        ▼                                ▼
  modern (2026-07-28)               legacy (2025-11-25 …)
  mcp_modern.py                     MCPHandler + mcp_sessions.py
  _meta envelope, header checks,    initialize, Mcp-Session-Id,
  resultType, caching hints,        SSE for server→client requests
  SSE streams, MRTR, tasks
        └───────────────┬────────────────┘
                        ▼
        MCPHandler: tools · prompts · resources · completion
                        ▼
        ToolsRegistry / PromptsRegistry  ──► change bus ──► listen streams
```

---

## 2. The modern path (2026-07-28)

### A request

```bash
curl -s http://localhost:3002/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' \
  -H 'Mcp-Name: calc_percentage_change' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"calc_percentage_change","arguments":{"old_value":80,"new_value":100},
        "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                 "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

The result carries `content`, `structuredContent`, `resultType: "complete"` and
`_meta["io.modelcontextprotocol/serverInfo"]`.

What makes it different from a 2025-11-25 request:

- **Context per request.** Protocol version and client capabilities are required in
  `_meta`; optional entries are `clientInfo`, `logLevel`, `progressToken` and trace
  context. Session headers are ignored.
- **Routing headers must agree with the body.** `MCP-Protocol-Version`, `Mcp-Method`
  and, for name-bearing methods, `Mcp-Name`. A mismatch is `-32020`; an unsupported
  version is `-32022`. Tools may also declare `Mcp-Param-*` headers (see the
  [MCP Apps and Headers Guide](MCP%20Apps%20and%20Headers%20Guide.md)).
- **`server/discover`** replaces `initialize`: supported versions, capabilities and
  instructions in one cacheable result.
- **Every result has a `resultType`**: `complete`, `input_required` (MRTR) or `task`.
- **Caching hints.** List results, `resources/read` and `server/discover` carry
  `ttlMs` and `cacheScope` (`mcp.cache.*`).
- **Removed methods** (`initialize`, `ping`, `logging/setLevel`,
  `resources/subscribe`/`unsubscribe`) answer `-32601` with HTTP 404.
- `GET` and `DELETE /mcp` with a modern version header answer 405.

### Streaming, cancellation and progress

A `tools/call` that sends `progressToken` or a `logLevel` in `_meta`, from a client
that accepts `text/event-stream`, is answered as an SSE stream: progress and log
notifications, then the result. Any tool can report through
`sajha.core.mcp_tool_context` (`report_progress`, `report_log`, `is_cancelled`).
Closing the stream (or the connection, for a JSON call) cancels the call. There is
no resumption on this path: a dropped stream is a cancelled request.

### `subscriptions/listen`

A long-lived POST answered with SSE. The client opts in to `toolsListChanged`,
`promptsListChanged`, `resourcesListChanged` and `resourceSubscriptions`. Events
come from the **change bus** (`sajha/core/change_bus.py`), which the tool and prompt
registries publish to on every change, however it was made (hot reload, admin
enable/disable). The bus coalesces bursts, so reloading
many tools is one notification. `mcp.subscriptions.max_streams` caps concurrent
streams.

### Multi Round-Trip Requests (MRTR)

A stateless server cannot send the client a request mid-call. Instead, `tools/call`,
`prompts/get` or `resources/read` may return `resultType: "input_required"` with
`inputRequests` (elicitation, sampling or roots) and an opaque `requestState`. The
client retries the same request with `inputResponses` and the echoed state.
SAJHA signs `requestState` with HMAC-SHA256 (`mcp.mrtr.*`) and binds it to the method,
target, arguments and caller, so no server memory is needed between rounds.

Built on MRTR: optional confirmation before running a tool annotated
`destructiveHint: true` (`mcp.confirm_destructive_tools`, off by default).

### The tasks extension

`io.modelcontextprotocol/tasks` lets a long tool call return a task handle
(`resultType: "task"`) that the client polls with `tasks/get`, answers with
`tasks/update` and stops with `tasks/cancel`. A tool opts in with
`"execution": {"taskSupport": "optional" | "required"}` in its JSON config; the
client opts in per request. Tasks live in memory per process, scoped to the calling
user (`mcp.tasks.*`).

MCP tasks are not the same thing as SAJHA's **async execution** (`/admin/async-tasks`,
`async.*` config), a fire-and-forget worker pool that delivers results to a webhook,
Kafka or a file.

### Extensions advertised by `server/discover`

| Extension | When | Owning guide |
|---|---|---|
| `io.modelcontextprotocol/tasks` | `mcp.tasks.enabled` | this section, and the 2026-07-28 report §3.3 |
| `io.modelcontextprotocol/ui` (MCP Apps) | `mcp.apps.enabled` | [MCP Apps and Headers Guide](MCP%20Apps%20and%20Headers%20Guide.md) |

---

## 3. The legacy path (2025-11-25 and earlier)

```bash
# 1. handshake: the response carries an Mcp-Session-Id header
curl -si http://localhost:3002/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25",
       "capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# 2. confirm, then call (202 for the notification)
curl -s http://localhost:3002/mcp -H 'Content-Type: application/json' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl -s http://localhost:3002/mcp -H 'Content-Type: application/json' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

- `initialize` negotiates the version: the client's if supported, else the newest
  handshake version.
- Sessions are in process memory (`sajha/core/mcp_sessions.py`). After a restart a
  client gets 404 and re-initializes. `DELETE /mcp` ends a session.
- Requests without a session header are still accepted, which keeps simple scripts
  working.
- Tools that talk to the client while running (sampling, elicitation) answer with an
  SSE stream on the POST; the client POSTs its JSON-RPC responses back.
- `ping`, `logging/setLevel`, `resources/subscribe` are available here.

---

## 4. Transports

| Transport | Endpoint | Era | Use it for |
|---|---|---|---|
| Streamable HTTP | `POST /mcp` (`/api/mcp`), `DELETE /mcp` | both | Every current MCP client. The default. |
| HTTP+SSE (2024-11-05) | `GET /mcp/sse` + `POST /mcp/message` | legacy | Older clients that predate Streamable HTTP. |
| WebSocket (SAJHA extension) | `/mcp/ws` | legacy | Full-duplex clients; accepts JSON-RPC batches; authenticates with `?token=` or `?api_key=`. |

The legacy SSE and WebSocket streams receive the same change-bus notifications as
`subscriptions/listen`, and therefore advertise `listChanged: true`. Streamable HTTP
sessions have no push channel (`GET /mcp` is 405), so they advertise `false`.

---

## 5. What every client sees

These behave the same on both paths:

- **`tools/list`** returns `name`, `title`, `description`, `inputSchema` (passed
  through untouched, JSON Schema 2020-12), `outputSchema`, `annotations` and
  `icons[]`, paginated with `nextCursor`. Order is deterministic (sorted by name).
  It is not filtered by role (see §6).
- **`tools/call`** returns content blocks plus `structuredContent` when the tool has an
  object `outputSchema` (`mcp.tools.advertise_output_schema`). Tool failures are
  results with `isError: true`, not protocol errors.
- **Prompts** list their arguments; `prompts/get` returns messages.
- **Resources** include the tool and prompt catalogs (`sajha://tools/catalog`,
  `sajha://prompts/catalog`) and resource templates; `completion/complete` completes
  prompt arguments and tool enum values.
- **Origin check.** A browser `Origin` that is not loopback and not listed in
  `mcp.allowed_origins` gets 403 (DNS-rebinding protection). Requests without an
  `Origin` header are allowed.

The live tool, prompt and resource catalog is whatever the server has loaded: ask
`tools/list`, or open the Tools page in the web UI. No document lists it.

---

## 6. Authentication on MCP endpoints

Out of the box (`mcp.auth.mode: "off"`) `/mcp` accepts anonymous calls, and also
accepts SAJHA credentials (an `X-API-Key`, a SAJHA JWT, or the session cookie) when
sent. With `optional` or `required`, the endpoints also
validate OAuth 2.1 bearer tokens and, in `required` mode, answer anonymous calls with
a 401 challenge that points clients at the protected-resource metadata. Setup, the
built-in authorization server and external identity providers are in the
[OAuth Guide](OAuth%20Guide.md); the wider picture is in the
[Security Model](../security/Security%20Model.md).

Role-based tool filtering is not active on the MCP endpoints in this release: `MCPHandler` is created without an auth manager (`sajha/app.py`), so every authenticated or anonymous caller sees and can call every enabled tool. See the [Security Model](../security/Security%20Model.md).

---

## 7. Clients

- **Official SDKs** work unchanged. The Python SDK's `mcp.Client(url, mode="auto")`
  runs `server/discover` and adopts 2026-07-28; `mode="legacy"` uses the handshake.
- **SAJHA's client SDK** wraps the official SDK as `SajhaMCPClient` /
  `SajhaMCPSyncClient` (`pip install sajhaclient[mcp]`), plus SAJHA's REST and A2A
  extras. See the [Client SDK Guide](../clients/Client%20SDK%20Guide.md).

---

## 8. Testing protocol behaviour

The official conformance suite needs fixture tools, prompts and resources that a
production server should not expose. They are off by default:

```bash
SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_server.py --host 127.0.0.1 --port 3092
npx -y @modelcontextprotocol/conformance@0.1.16        server --url http://127.0.0.1:3092/mcp --spec-version 2025-11-25 --suite all
npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server --url http://127.0.0.1:3092/mcp --spec-version 2026-07-28 --suite all
```

CI runs both on every push (`.github/workflows/mcp-conformance.yml`). The current
results, the extension and authorization scenarios, and the unit tests
(`tests/test_mcp_2025_11_25.py`, `tests/test_mcp_2026_07_28.py`,
`tests/test_mcp_auth.py`, `tests/test_mcp_apps.py`) are described in the compliance
reports.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
