# SAJHA MCP Server — MCP 2026-07-28 Compliance Report (Wave 1)

**Protocol versions supported:** 2026-07-28 (stateless, "modern") **plus** 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05 (handshake-era, "legacy"). SAJHA is a *dual-era* server.
**Transport:** Streamable HTTP on `/mcp`. Legacy HTTP+SSE (`GET /mcp/sse`) and the WebSocket extension (`/mcp/ws`) are legacy-era only.
**Verified with:** `@modelcontextprotocol/conformance` 0.2.0-alpha.12 (the first release with 2026-07-28 scenarios; 0.1.16 does not know this version), 0.1.16 for 2025-11-25, and the official Python SDK client (`mcp` 2.3.0).

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## 1. What Wave 1 implements

The modern path lives in `sajha/core/mcp_modern.py`. It reuses `MCPHandler`'s tools, prompts, resources and completion logic, and owns only the 2026-07-28 envelope.

### 1.1 Era detection (POST /mcp)

| Request | Era |
|---|---|
| `params._meta` carries `io.modelcontextprotocol/protocolVersion` | modern. This applies even to `initialize`, which then gets `404` / `-32601`. |
| `initialize` without that `_meta` key | legacy handshake, unchanged |
| no `_meta` key, but `MCP-Protocol-Version` names a non-handshake version (`2026-07-28` or an unknown one) | modern, so the validation ladder answers `-32602`, `-32020` or `-32022` |
| everything else | legacy, unchanged (sessions, `Mcp-Session-Id`, SSE streaming, server→client requests) |

`GET /mcp` and `DELETE /mcp` with a modern `MCP-Protocol-Version` header get **405** (`Allow: POST`). Legacy GET and DELETE behaviour is unchanged.

### 1.2 Stateless requests

- **Per-request context.** Each request's context comes from its `_meta` alone: `protocolVersion`, `clientCapabilities` (both required, else `-32602` and HTTP 400), `clientInfo` (optional), `logLevel`, `progressToken`, `traceparent`, `tracestate` and `baggage`.
- **No session state.** On this path the server ignores `Mcp-Session-Id` and `Last-Event-ID`, and never mints or echoes a session id.
- **Notifications.** A notification POST is answered `202` and dropped. An unsupported version gets `-32022`.

### 1.3 Validation ladder (first failure wins)

1. **Routing headers.** A duplicated routing header gets `-32020` (HTTP 400).
2. **Required `_meta` fields.** A missing `_meta`, `protocolVersion` or `clientCapabilities` gets `-32602` (HTTP 400).
3. **Header and body agreement.** The server compares each header with the body. Any mismatch or missing header gets `-32020` (HTTP 400). Header names are matched case-insensitively. Header values are case-sensitive, with surrounding whitespace trimmed.
   - `MCP-Protocol-Version` must equal `_meta.protocolVersion`.
   - `Mcp-Method` must equal `method`.
   - `Mcp-Name` must equal `params.name` (for `tools/call` and `prompts/get`) or `params.uri` (for `resources/read`). It may be `=?base64?…?=`-encoded.
4. **Protocol version.** An unsupported version gets `-32022` (HTTP 400), with `data: {supported: [...], requested}`.
5. **`Mcp-Param-{Name}` headers.** For `tools/call`, these headers are checked against arguments the tool's `inputSchema` marks with `x-mcp-header`. A value that is missing, extra, mismatched or carries malformed base64 (bad padding or alphabet, or non-canonical) gets `-32020`.

### 1.4 Methods

| Served on the modern path | Result extras |
|---|---|
| `server/discover` | `supportedVersions` (all five versions, newest first), `capabilities` (`tools`, `prompts`, `resources`, `completions`, `extensions: {}` and `experimental.sajha` without the legacy WebSocket entry), `instructions` |
| `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` | cacheable |
| `tools/call`, `prompts/get`, `completion/complete` | — |

These rules apply to every modern result:

- **`resultType`.** Every result carries `resultType: "complete"`.
- **Server identity.** Every result carries `_meta["io.modelcontextprotocol/serverInfo"]`.
- **Cacheable results.** `server/discover` and the five cacheable methods above also carry `ttlMs` and `cacheScope`.

**Not on the modern path (`404` / `-32601`):**

- **Removed in 2026-07-28.** `initialize`, `ping`, `logging/setLevel`, `resources/subscribe`, `resources/unsubscribe` and the initialize-era notifications sent as requests.
- **Core `tasks/*`.** These return with the tasks extension in Wave 3.
- **SAJHA legacy aliases.** For example `api/tools/list` and `tool/schema`.
- **Unknown methods.**

`tools/list` order is deterministic on **both** paths. Conformance fixtures (when enabled) come first, sorted by name, then registry tools, sorted by name.

### 1.5 Caching hints (SEP-2549), `config/application.yml`

```yaml
mcp:
  cache:
    discover_ttl_ms: 300000   # server/discover
    list_ttl_ms: 60000        # tools/prompts/resources/templates lists
    read_ttl_ms: 30000        # resources/read
    scope: auto               # auto | public | private
```

With `scope: auto`, `cacheScope` is `"private"` when a result depends on the caller (per-user `tools/list` filtering through `MCPHandler.auth_manager`) and `"public"` otherwise. Environment overrides follow the usual pattern, for example `SAJHA_MCP_CACHE_LIST_TTL_MS`.

### 1.6 Error codes on the modern path

| Situation | Code | HTTP |
|---|---|---|
| parse error, invalid request, batch | -32700 / -32600 | 400 |
| missing `_meta` fields, bad params, unknown tool/prompt, **resource not found** (was -32002) | -32602 (`data.uri` for resources) | 400 |
| header mismatch / missing header | -32020 | 400 |
| missing client capability (`data.requiredCapabilities` is a ClientCapabilities object) | -32021 | 400 |
| unsupported protocol version | -32022 | 400 |
| unknown / removed method | -32601 | 404 |
| access denied to a tool | -32003 (SAJHA, in the legacy sub-range -32000..-32019; -32002 is not emitted) | 200 |
| internal error | -32603 | 200 |

Any handler error in -32020..-32099 that the spec does not define is mapped to -32603. Tool execution failures remain `isError: true` results.

### 1.7 Logging

The server stores the per-request `logLevel` and logs it at debug level. Wave 1 never opens a response stream, so it never sends `notifications/message`. That satisfies the MUST NOT without a `logLevel`, and the `logging` capability is not advertised on the modern path.

### 1.8 Conformance fixtures added for 2026-07-28

Fixtures stay off by default (`SAJHA_MCP_CONFORMANCE_FIXTURES=true` turns them on). Each fixture tool is tagged with an era:

- **Modern only:**
  - `test_logging_tool`.
  - `test_missing_capability`, which needs the client's `sampling` capability and otherwise returns `-32021`.
  - `test_custom_header`, whose `region` argument carries `x-mcp-header: Region`.
- **Legacy only** (these need server→client requests):
  - `test_sampling`.
  - The three `test_elicitation*` tools.

`json_schema_2020_12_tool` now carries the SEP-2106 vocabulary (`$anchor`, `allOf`/`anyOf`, `if`/`then`/`else`).

---

## 2. Conformance results

```bash
SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_server.py --host 127.0.0.1 --port 3092
npx -y @modelcontextprotocol/conformance@0.1.16        server --url http://127.0.0.1:3092/mcp --spec-version 2025-11-25 --suite all
npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server --url http://127.0.0.1:3092/mcp --spec-version 2026-07-28 --suite all
```

**2025-11-25 (legacy path):** 32/32 scenarios pass, with 43 checks passed and 0 failed. This is unchanged from 5.4.0.

**2026-07-28 (modern path):** 28 of 40 scenarios pass, with 125 checks passed and 12 failed. The baseline before Wave 1 was 1 scenario passing, with 11 checks passed and 108 failed. Every remaining failure belongs to a later wave.

| Scenario | Result | Wave |
|---|:-:|:-:|
| completion-complete, tools-list, tools-call-simple-text / image / audio / embedded-resource / mixed-content / error | ✅ | 1 |
| json-schema-2020-12 (incl. SEP-2106 keywords) | ✅ | 1 |
| resources-list, resources-read-text, resources-read-binary, resources-templates-read, sep-2164-resource-not-found | ✅ | 1 |
| prompts-list, prompts-get-simple / with-args / embedded-resource / with-image | ✅ | 1 |
| caching, http-header-validation, http-custom-header-server-validation, dns-rebinding-protection | ✅ | 1 |
| server-sse-multiple-streams | ✅ | 1 |
| input-required-result-missing-input-response, -unsupported-methods, -ignore-extra-params, -validate-input | ✅ | (3) |
| server-stateless | 24/25 checks | 1 ✅ / 3 |
| ↳ `sep-2575-http-server-no-independent-requests-on-stream` (needs the MRTR fixture `test_streaming_elicitation`) | ❌ | 3 |
| ↳ subscriptions/listen checks | skipped: no listChanged/subscribe advertised | 2 |
| tools-call-with-progress: no `notifications/progress` without a response stream | ❌ | 2 |
| input-required-result-basic-elicitation / basic-sampling / basic-list-roots / request-state / multiple-input-requests / multi-round / non-tool-request / result-type / tampered-state / capability-check | ❌ | 3 |

## 3. Official SDK client (`mcp` 2.3.0)

`mcp.Client("http://127.0.0.1:3092/mcp", mode=...)` was run in three modes:

- **`mode="2026-07-28"`:** negotiates `2026-07-28`.
- **`mode="auto"`:** runs `server/discover`, adopts `2026-07-28` and reports `serverInfo`.
- **`mode="legacy"`:** uses the initialize handshake and negotiates `2025-11-25`.

Each mode lists tools (`ttl_ms=60000`, `cache_scope="public"` on modern), calls `calc_percentage_change` (80 → 100 gives 25.0), lists 10 prompts, gets `bug_diagnosis` with its required arguments, lists resources and reads `sajha://tools/catalog`. `SajhaMCPClient` (default `mode="auto"`) now negotiates `2026-07-28`, and `clientsdk/tests` covers this.

## 4. Tests

`tests/test_mcp_2026_07_28.py` covers:

- era routing
- `server/discover`
- `_meta` validation
- `-32020` for every header rule, including `Mcp-Param-*` and base64
- `-32022`
- `resultType` and `serverInfo` stamping
- caching fields
- resource-not-found `-32602`
- `-32021`
- removed and unknown methods (404 / `-32601`)
- GET/DELETE 405
- error-code mapping

`tests/test_mcp_2025_11_25.py` still passes unchanged.

## 5. Pending

**Wave 2: streaming and subscriptions.**
- Per-request SSE response streams on the modern path: `notifications/progress`, and `notifications/message` gated by `logLevel`.
- `subscriptions/listen` with `notifications/subscriptions/acknowledged`, `subscriptionId` tagging and filtering.
- `listChanged` support.

**Wave 3: MRTR and tasks.**
- `InputRequiredResult` (`resultType: "input_required"`) with `inputRequests` / `inputResponses` / `requestState` for sampling, elicitation and roots.
- The `io.modelcontextprotocol/tasks` extension in `capabilities.extensions`.
