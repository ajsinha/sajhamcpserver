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

`$TOKEN` is a SAJHA login JWT (`POST /api/auth/login`); an `X-API-Key` header works too.
Without credentials the anonymous tool policy applies, which by default allows no registry
tools ([Security Model](../security/Security%20Model.md#tool-access)).

```bash
curl -s http://localhost:3002/mcp \
  -H "Authorization: Bearer $TOKEN" \
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
`destructiveHint: true` (`mcp.confirm_destructive_tools`, off by default), and sampling by
LLM tools (below).

### Sampling by LLM tools

An LLM tool whose config sets `llm.sampling: prefer` or `require` (modes `complete`,
`extract`, `classify`, `judge`) sends its model call to the client when the client declared
the `sampling` capability and the tool is the call's own target:

- **2026-07-28:** the first `tools/call` answers `input_required` with one
  `sampling/createMessage` request keyed `sajha_sample_1`; the retry carrying the answer
  runs the tool again from the start and uses it. A structured mode whose first reply does
  not validate asks once more (`sajha_sample_2`).
- **2025-11-25:** with an `Accept` that includes `text/event-stream`, the `tools/call`
  response is an SSE stream that carries the `sampling/createMessage` request; the client
  POSTs its JSON-RPC response to `/mcp` and the result follows on the stream.

The request has the tool's rendered prompt as `messages`, its system text as `systemPrompt`
(with the JSON Schema spelled out for structured modes), `maxTokens` from the tool's limits
and `metadata.sajha_llm_tool`. Without a capable client `prefer` uses SAJHA's own model and
`require` returns a tool error (`code: sampling_required`). Configuration and the rules:
[LLM Tools](../architecture/LLM%20Tools.md#12-models-sampling-budgets-and-limits) section 12.

### The tasks extension

`io.modelcontextprotocol/tasks` lets a long tool call return a task handle
(`resultType: "task"`) that the client polls with `tasks/get`, answers with
`tasks/update` and stops with `tasks/cancel`. A tool opts in with
`"execution": {"taskSupport": "optional" | "required"}` in its JSON config; the
client opts in per request. Task records are scoped to the calling user (`mcp.tasks.*`)
and kept in the state store: per process by default, shared and durable with a shared
backend ([Scaling and State](../architecture/Scaling%20and%20State.md)).

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
- Sessions are in the state store (`sajha/core/mcp_sessions.py`), process memory by
  default. After a restart a client then gets 404 and re-initializes. `DELETE /mcp` ends a session.
- Requests without a session header are still accepted, which keeps simple scripts
  working.
- Tools that talk to the client while running (sampling, elicitation; LLM tools with
  `llm.sampling`, section 2) answer with an SSE stream on the POST; the client POSTs its
  JSON-RPC responses back.
- `ping`, `logging/setLevel`, `resources/subscribe` are available here.

---

## 4. Transports

| Transport | Endpoint | Era | Use it for |
|---|---|---|---|
| Streamable HTTP | `POST /mcp` (`/api/mcp`), `DELETE /mcp` | both | Every current MCP client. The default. |
| HTTP+SSE (2024-11-05) | `GET /mcp/sse` + `POST /mcp/message` | legacy | Older clients that predate Streamable HTTP. |
| WebSocket (SAJHA extension) | `/mcp/ws` | legacy | Full-duplex clients; accepts JSON-RPC batches; authenticates with `?token=` or `?api_key=`. |
| stdio | the server's stdin/stdout (`sajha serve --stdio`, `python run_server.py --stdio`) | both | Desktop clients (Claude Desktop, Claude Code, IDEs) that launch the server as a subprocess. |

The legacy SSE and WebSocket streams receive the same change-bus notifications as
`subscriptions/listen`, and therefore advertise `listChanged: true`. Streamable HTTP
sessions have no push channel (`GET /mcp` is 405), so they advertise `false`.

### stdio

`sajha/cli/stdio.py` serves MCP over a subprocess's stdin/stdout, following the spec's
stdio rules: newline-delimited JSON-RPC (one object per line, UTF-8), nothing but
protocol messages on stdout (file descriptor 1 is pointed at stderr at start-up, so a
stray `print` cannot corrupt the stream), logs on stderr only, and exit when stdin
closes. Both eras are served by the same handlers as `POST /mcp`:

- A request carrying the 2026-07-28 `_meta` envelope goes to the modern path. A client
  in `auto` mode probes with `server/discover` and stays modern; one that gets an error
  falls back to `initialize`. stdio has no headers, so the routing headers the HTTP
  ladder cross-checks (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*`)
  are derived from the body; every body-level check still applies. Streamed responses
  (`subscriptions/listen`, a `tools/call` with a `progressToken` or `logLevel`) arrive as
  notification lines followed by the response line.
- `initialize` selects the legacy path; the connection is the session. stdio is a push
  channel, so the initialize result advertises `listChanged: true` and list changes
  arrive as notifications. Server-to-client requests (sampling, elicitation) work as on
  a streamed HTTP call.
- `notifications/cancelled` cancels the named in-flight request on either path, and no
  response is sent for it.

There is one caller per process, fixed at start-up and mapped through the same access
control as every other transport: `--api-key` (or `SAJHA_API_KEY`) uses that key's tool
access list, `--user` (or `SAJHA_STDIO_USER`) a SAJHA user's roles, and with neither the
caller is anonymous (`mcp.anonymous.*`, no registry tools by default). The process opens
the server's database and configuration directly, so whoever can launch it can already
read them; no password is asked for. Client configuration snippets are in
[Command Line](../clients/Command%20Line.md#4-desktop-clients-stdio).

---

## 5. What every client sees

These behave the same on both paths:

- **`tools/list`** returns `name`, `title`, `description`, `inputSchema` (passed
  through untouched, JSON Schema 2020-12), `outputSchema`, `annotations` and
  `icons[]`, paginated with `nextCursor`. Order is deterministic (sorted by name).
  It lists only the tools the caller may see (see §6).
- **`tools/call`** returns content blocks plus `structuredContent` when the tool has an
  object `outputSchema` (`mcp.tools.advertise_output_schema`). Tool failures are
  results with `isError: true`, not protocol errors.
- **Argument validation.** Before a registry tool runs, its arguments are validated
  against its advertised `inputSchema` with `jsonschema` (`required`, `type`, `enum`,
  `pattern`, `minimum`/`maximum`, `additionalProperties`, ...), in one place
  (`BaseMCPTool.validate_arguments`, called by `execute_with_tracking`), so MCP, REST,
  A2A and Ask SAJHA all apply it. A mismatch never reaches the tool. **The answer
  differs by era on purpose**, because the two revisions prescribe different things:

  | Path | Arguments that fail the `inputSchema` | Why |
  |---|---|---|
  | 2026-07-28 | JSON-RPC error `-32602` (Invalid params), no `result` | that revision's `InvalidParamsError` covers invalid tool arguments |
  | 2025-11-25 (and earlier) | a `tools/call` **result** with `isError: true` and the message as text content | SEP-1303: input validation is a tool execution error, so the model sees it and can correct the call |
  | `POST /api/tools/execute` | HTTP 400 | REST |

  The message names the tool and the first offending argument. An *unknown tool* is
  `-32602` on both paths; a tool that fails while running is `isError: true` on both.
  A tool whose schema is not itself valid JSON Schema logs a warning and is checked for
  `required` only. (`sajha/core/mcp_handler.py`, the `ToolArgumentError` branch of
  `tools/call`.)
- **Prompts** list their arguments; `prompts/get` returns messages. Anonymous callers
  see only the prompts in `mcp.anonymous.prompts` (none by default; see §6).
- **Resources** include the tool and prompt catalogs (`sajha://tools/catalog`,
  `sajha://prompts/catalog`) and resource templates; `completion/complete` completes
  prompt arguments and tool enum values. The catalogs and completions cover only the
  tools and prompts the caller may see.
- **Origin check.** A browser `Origin` that is not loopback and not listed in
  `mcp.allowed_origins` gets 403 (DNS-rebinding protection). Requests without an
  `Origin` header are allowed.

The live tool, prompt and resource catalog is whatever the server has loaded: ask
`tools/list`, or open the Tools page in the web UI. No document lists it. Approved
items from federated upstream MCP servers appear in it under namespaced names and
behave like local ones on both paths ([Federation](../architecture/Federation.md#4-namespacing)).

---

## 6. Authentication on MCP endpoints

Out of the box (`mcp.auth.mode: "off"`) `/mcp` accepts anonymous calls (limited to the anonymous tool policy), and also
accepts SAJHA credentials (an `X-API-Key`, a SAJHA JWT, or the session cookie) when
sent. With `optional` or `required`, the endpoints also
validate OAuth 2.1 bearer tokens and, in `required` mode, answer anonymous calls with
a 401 challenge that points clients at the protected-resource metadata. Setup, the
built-in authorization server and external identity providers are in the
[OAuth Guide](OAuth%20Guide.md); the wider picture is in the
[Security Model](../security/Security%20Model.md).

`tools/list` and `tools/call` apply the caller's tool access on both eras and every transport (`sajha/auth/access.py`): users by their roles, API keys by their tool access mode, anonymous callers by `mcp.anonymous.*` (no registry tools by default; `mcp.anonymous.enabled: false` demands credentials). A refused call is `-32002` on 2025-11-25 and `-32010` on 2026-07-28, and an authenticated caller's `tools/list` is `cacheScope: private`. The conformance fixtures are callable by anyone when enabled. The same policy covers the rest of the catalog: the `sajha://tools/catalog` resource, tool completions and the `tool/schema`-style methods show only visible tools; signed-in callers see every prompt and anonymous callers only `mcp.anonymous.prompts` (`prompts/list`, `prompts/get`, prompt completions, `sajha://prompts/catalog`; a hidden prompt is `-32602` Unknown prompt). See [Tool access](../security/Security%20Model.md#tool-access).

---

## 7. Clients

- **Official SDKs** work unchanged. The Python SDK's `mcp.Client(url, mode="auto")`
  runs `server/discover` and adopts 2026-07-28; `mode="legacy"` uses the handshake.
- **SAJHA's client SDK** wraps the official SDK as `SajhaMCPClient` /
  `SajhaMCPSyncClient` (`pip install sajhaclient[mcp]`), plus SAJHA's REST and A2A
  extras. See the [Client SDK Guide](../clients/Client%20SDK%20Guide.md).
- **The `sajha` command line** lists, shows and calls tools over MCP, streams `ask`,
  and launches the stdio server. See [Command Line](../clients/Command%20Line.md).

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
