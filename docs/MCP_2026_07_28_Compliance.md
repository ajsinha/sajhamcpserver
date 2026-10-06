# SAJHA MCP Server — MCP 2026-07-28 Compliance Report (Waves 1–4)

**Protocol versions supported:** 2026-07-28 (stateless, "modern") **plus** 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05 (handshake-era, "legacy"). SAJHA is a *dual-era* server.
**Transport:** Streamable HTTP on `/mcp`. Legacy HTTP+SSE (`GET /mcp/sse`) and the WebSocket extension (`/mcp/ws`) are legacy-era only.
**Verified with:** `@modelcontextprotocol/conformance` 0.2.0-alpha.12 (the first release with 2026-07-28 scenarios; 0.1.16 does not know this version) including the `io.modelcontextprotocol/tasks` extension scenarios, 0.1.16 for 2025-11-25, and the official Python SDK client (`mcp` 2.3.0).

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## 1. Wave 1: the stateless envelope

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
| `server/discover` | `supportedVersions` (all five versions, newest first), `capabilities` (see §2.4), `instructions` |
| `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` | cacheable |
| `tools/call`, `prompts/get`, `completion/complete` | `tools/call`, `prompts/get` and `resources/read` may answer `input_required` (§3.1) |
| `subscriptions/listen` | SSE stream (§2.2) |
| `tasks/get`, `tasks/update`, `tasks/cancel` | tasks extension (§3.3) |

These rules apply to every modern result:

- **`resultType`.** Every result carries `resultType`: `"complete"`, `"input_required"` (MRTR) or `"task"` (CreateTaskResult).
- **Server identity.** Every result carries `_meta["io.modelcontextprotocol/serverInfo"]`.
- **Cacheable results.** `server/discover` and the five cacheable methods above also carry `ttlMs` and `cacheScope`.

**Not on the modern path (`404` / `-32601`):**

- **Removed in 2026-07-28.** `initialize`, `ping`, `logging/setLevel`, `resources/subscribe`, `resources/unsubscribe` and the initialize-era notifications sent as requests.
- **`tasks/list` and `tasks/result`.** Not part of the tasks extension (the result is inlined on `tasks/get`). The legacy 2025-11-25 core `tasks/*` are untouched on the legacy path.
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
| missing client capability (`data.requiredCapabilities` is a ClientCapabilities object), incl. input the client cannot provide and the tasks extension | -32021 | 400 |
| `requestState` tampered, expired or replayed against another request; invalid `inputResponses`; unknown `taskId` | -32602 | 400 |
| client closed the connection of a JSON `tools/call` (nobody reads it) | -32603 | 499 |
| unsupported protocol version | -32022 | 400 |
| unknown / removed method | -32601 | 404 |
| access denied to a tool | -32010 (SAJHA, in the implementation-defined range -32000..-32019; -32002 is not emitted) | 200 |
| internal error | -32603 | 200 |

Any handler error in -32020..-32099 that the spec does not define is mapped to -32603. Tool execution failures remain `isError: true` results.

### 1.7 Logging

See §2.1: `notifications/message` is sent only on a streamed `tools/call` and only at or above the request's `_meta["io.modelcontextprotocol/logLevel"]`; without a `logLevel` nothing is ever sent. The `logging` capability is advertised on the modern path.

### 1.8 Conformance fixtures (Wave 1)

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

## 2. Wave 2: streaming, cancellation, subscriptions

### 2.1 Streamed `tools/call` responses

A modern `tools/call` is answered as `text/event-stream` when the client accepts SSE **and** asked for something to stream: `_meta.progressToken` and/or `_meta["io.modelcontextprotocol/logLevel"]`. Everything else stays plain JSON (a JSON-only client always gets JSON). The stream carries:

- `notifications/progress` with the request's `progressToken`;
- `notifications/message`, only at or above the requested level (RFC 5424 order);
- the final JSON-RPC response (result or error), then the stream ends.

It never carries a JSON-RPC *request*: a stateless server asks the client for input through MRTR (§3.1). There are no SSE event ids, no priming event and no `Last-Event-ID` handling: the modern path has **no resumability**; a dropped stream is a cancelled request.

Who can report: the async conformance fixtures, through their `ctx`; and **every regular SAJHA tool** from its (thread-pool) `execute`, through `sajha.core.mcp_tool_context`:

```python
from sajha.core.mcp_tool_context import report_progress, report_log, is_cancelled
report_progress(10, 100, "fetched page 1")     # no-op unless the caller sent a progressToken
report_log("info", {"rows": 120})               # no-op unless the caller's logLevel <= info
if is_cancelled(): return partial_result        # the client went away
```

### 2.2 Cancellation

- **Streamed call:** when the client closes the response stream, the producer task is cancelled, the tool's context is flagged (`is_cancelled()`), and an in-flight thread-pool call is *abandoned* (`anyio.to_thread.run_sync(..., abandon_on_cancel=True)`): the server stops waiting and frees the request; Python cannot kill the worker thread, so a blocking tool runs to its end unless it polls `is_cancelled()`.
- **JSON call:** a watcher on the ASGI `receive` channel sees `http.disconnect` and cancels the call the same way (polling `Request.is_disconnected()` does not work behind SAJHA's `BaseHTTPMiddleware` stack).
- `notifications/cancelled` stays a legacy/WebSocket mechanism; on the modern path it is a dropped notification.

### 2.3 `subscriptions/listen` and the change bus

`subscriptions/listen` is a long-lived POST answered with SSE (a client that does not accept `text/event-stream` gets 406 / `-32600`). `params.notifications` is the opt-in filter: `toolsListChanged`, `promptsListChanged`, `resourcesListChanged`, `resourceSubscriptions: [uri, ...]`.

1. The first message is `notifications/subscriptions/acknowledged` with the honored subset of the filter.
2. Only opted-in notification types follow: `notifications/tools/list_changed`, `notifications/prompts/list_changed`, `notifications/resources/list_changed`, `notifications/resources/updated {uri}`.
3. Every message carries `params._meta["io.modelcontextprotocol/subscriptionId"]` = the listen request's id.
4. On server shutdown the stream ends with a `SubscriptionsListenResult` (`resultType: "complete"`, `_meta` with `subscriptionId` and `serverInfo`); if the client disconnects the subscription is dropped.

The events come from `sajha/core/change_bus.py`, a thread-safe, coalescing fan-out (while an event is queued for a subscriber, identical events are dropped, so a reload of 200 tools is one notification):

| Producer | Events |
|---|---|
| `ToolsRegistry` register / unregister / enable / disable / `reload_all_tools` (hot-reload, admin enable/disable, composite-tool save) | tools list_changed, resources list_changed, `resources/updated` for `sajha://tools/catalog` |
| `PromptsRegistry` create / update / delete, and reloads that actually change the prompt set | prompts list_changed, resources list_changed, `resources/updated` for `sajha://prompts/catalog` |

Consumers: `subscriptions/listen` streams; the legacy 2024-11-05 HTTP+SSE stream (`GET /mcp/sse`); the WebSocket transport (`/mcp/ws`). The old ad-hoc "push list_changed after a method name containing enable/disable/reload" code in `/mcp/message` and `/mcp/ws` is gone; the bus covers every change, whoever made it. `mcp.subscriptions.max_streams` (default 1000) caps concurrent listen streams.

### 2.4 Capabilities (advertised truthfully)

| | modern (`server/discover`) | legacy streamable HTTP `initialize` | legacy `/mcp/sse` and `/mcp/ws` `initialize` |
|---|---|---|---|
| `tools.listChanged`, `prompts.listChanged`, `resources.listChanged` | `true` | `false` (no push channel: GET /mcp is 405) | `true` |
| `resources.subscribe` | `true` (catalog URIs are really updated) | `false` | `false` |
| `logging` | `{}` | `{}` | `{}` |
| `extensions["io.modelcontextprotocol/tasks"]` | `{}` (when `mcp.tasks.enabled`) | — | — |
| `extensions["io.modelcontextprotocol/ui"]` | `{}` (when `mcp.apps.enabled`, default true) | — | — |

`resources.listChanged` fires on tool/prompt changes (the catalog entries change); new files dropped into `data/duckdb` or `data/sqlselect` are not watched.

## 3. Wave 3: MRTR, elicitation, tasks

### 3.1 Multi Round-Trip Requests (SEP-2322)

`tools/call`, `prompts/get` and `resources/read` may answer

```json
{"resultType": "input_required",
 "inputRequests": {"user_name": {"method": "elicitation/create", "params": {...}}},
 "requestState": "<base64url(payload)>.<base64url(HMAC-SHA256)>"}
```

The client retries the same request with `inputResponses` (same keys) and the echoed `requestState`. A handler signals the need for input by raising `sajha.core.mcp_mrtr.InputRequired(requests, state=...)` (fixtures: `ctx.require_input(...)`) and is simply run again on the retry with `ctx.input_responses`.

`requestState` (`sajha/core/mcp_mrtr.py`) is signed with `mcp.mrtr.state_secret` (env `SAJHA_MCP_MRTR_STATE_SECRET`; if empty, derived from `auth.session.secret_key`, which is random per process when unset). The payload binds it to the method, tool/prompt/URI, a digest of the arguments and the calling user, expires after `mcp.mrtr.state_ttl_seconds` (900), carries optional handler state, and **accumulates the answers of earlier rounds**, so multi-round flows need no server memory. It is signed, not encrypted: it only holds what the client sent. Rules:

- a `requestState` that fails verification (tampered, expired, other tool/arguments/user) → `-32602`, HTTP 400;
- `inputResponses: null`, or a non-object response value → `-32602`; unknown keys are ignored; missing keys are re-requested with a new `InputRequiredResult`;
- input requests are checked against the declared client capabilities (`elicitation`, `sampling`, `roots`): a handler that needs one the client did not declare → `-32021`;
- list methods never return `input_required`; nothing is ever sent as a JSON-RPC request on a response stream.

### 3.2 Confirmation for destructive tools (elicitation, form mode)

`mcp.confirm_destructive_tools: true` (default **false**) makes a modern `tools/call` of a registry tool whose config has `"annotations": {"destructiveHint": true}` ask first — only when the client declares form-mode elicitation (`elicitation: {}` or `{form: {}}`); otherwise the call runs exactly as before. The `InputRequiredResult` carries one `elicitation/create` (`mode: "form"`, a boolean `confirm`) under the key `sajha_confirm_destructive`. `accept` with `confirm: true` runs the tool; decline, cancel or `false` returns `isError: true` ("not run: the user did not confirm") without running it. It composes with tasks (the task parks in `input_required`).

### 3.3 Tasks extension `io.modelcontextprotocol/tasks` (SEP-2663)

Advertised under `capabilities.extensions` (never a v1 `capabilities.tasks`). A tool opts in with `"execution": {"taskSupport": "optional" | "required"}` in its config (shown in modern `tools/list`; legacy `tools/list` is unchanged). The client opts in per request with `_meta["io.modelcontextprotocol/clientCapabilities"].extensions["io.modelcontextprotocol/tasks"]`.

| Situation | Answer |
|---|---|
| task-supporting tool, client declared the extension | flat `CreateTaskResult`: `resultType: "task"`, `taskId`, `status: "working"`, `createdAt`, `lastUpdatedAt`, `ttlMs`, `pollIntervalMs`; no `requestState`, no nested `task` |
| `optional` tool, extension not declared | synchronous `CallToolResult` |
| `required` tool, extension not declared | `-32021`, `data.requiredCapabilities.extensions["io.modelcontextprotocol/tasks"]` |
| legacy `task: {ttl, pollInterval}` param | tolerated, ignored (never promotes a sync tool) |
| `tasks/get` | DetailedTask + `resultType: "complete"`: `result` inlined when `completed` (a tool error is `completed` + `result.isError`), `error` when `failed` (protocol-level), `inputRequests` when `input_required` |
| `tasks/update {taskId, inputResponses}` | `{resultType: "complete"}` ack; answered keys leave `inputRequests`; when none is left the tool resumes with every answer so far |
| `tasks/cancel` | `{resultType: "complete"}` ack, idempotent on terminal tasks; the task settles to `cancelled` |
| `tasks/*` without the extension declared | `-32021`; unknown / other user's `taskId` → `-32602` |
| `tasks/list`, `tasks/result` | `-32601` / 404 |

`tasks/get|update|cancel` require `Mcp-Name: <taskId>` like other name-bearing methods. MRTR composes with tasks: a tool can gather input synchronously (`input_required`) and create the task on the final round (fixture `test_tool_with_task`).

**Store.** `sajha/core/mcp_tasks.py` keeps tasks in memory, in the server's event loop, scoped to the calling user, for `mcp.tasks.ttl_ms` (1 h) after their last update, at most `mcp.tasks.max_tasks` (1000; oldest terminal tasks are evicted first). It is deliberately **not** the `/admin/async-tasks` executor (`sajha/core/async_executor.py`): that is a fire-and-forget worker pool that delivers results to webhooks/Kafka/files, cannot park a job for client input, and cannot cancel a running job — the three things SEP-2663 needs. Being per process, tasks need a single worker or sticky routing. `notifications/tasks` on listen streams (optional in SEP-2663) is not sent.

### 3.4 Fixtures added for Waves 2–3 (modern only, opt-in)

- streaming / subscriptions: `test_streaming_elicitation` (MRTR elicitation, needs `elicitation`), `test_trigger_tool_change`, `test_trigger_prompt_change` (publish on the change bus);
- MRTR: `test_input_required_result_elicitation | _sampling | _list_roots | _request_state | _multiple_inputs | _multi_round | _tampered_state | _capabilities`, and the prompt `test_input_required_result_prompt`;
- tasks: `greet` (sync), `slow_compute` (optional), `failing_job` (required, tool error), `protocol_error_job` (optional, protocol error), `confirm_delete` and `multi_input` (optional, park for input), `test_tool_with_task` (required, MRTR then task).

---

## 4. Wave 4: authorization, MCP Apps, `x-mcp-header`

### 4.1 OAuth 2.1 authorization (basic/authorization, both eras)

The same rules apply to the 2026-07-28 and 2025-11-25 paths of `POST /mcp` (and `/api/mcp`, `GET /mcp/sse`, `POST /mcp/message`, `DELETE /mcp`). Keys live under `mcp.auth` in `config/application.yml`; every key has a `SAJHA_` env override (`SAJHA_MCP_AUTH_MODE=required`).

| `mcp.auth.mode` | Behaviour |
|---|---|
| `off` (default) | Unchanged from 6.0.0: anonymous calls allowed; no discovery documents (`/.well-known/oauth-*` are 404, so clients see "no OAuth"). |
| `optional` | OAuth bearer tokens are validated and accepted; anonymous calls still allowed; an *invalid* bearer gets 401 `error="invalid_token"`. |
| `required` | No valid credential → **401** with `WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource/mcp", scope="mcp:read mcp:tools"`. |

Existing SAJHA credentials (`X-API-Key` / `sja_` keys, SAJHA login JWTs, the `sajha_token` cookie) keep working in every mode and are not scope-checked (their roles govern tool access as before). OAuth access tokens are accepted **only** on the MCP endpoints, never on the REST API.

**Resource server (RFC 9728, RFC 8707, RFC 6750).**
- Protected Resource Metadata at `/.well-known/oauth-protected-resource`, `/.well-known/oauth-protected-resource/mcp` and `.../api/mcp`: `resource` (= `<public_url>/mcp`), `authorization_servers`, `scopes_supported` (`mcp:read mcp:tools`, never `offline_access`), `bearer_methods_supported: ["header"]`.
- Token validation: asymmetric signature only (RS/PS/ES; `none` and `HS*` refused), `iss` = the configured authorization server, `aud` contains this server's resource URI (or a value in `mcp.auth.accepted_audiences`), `exp`/`nbf` with `clock_skew_seconds` leeway; built-in tokens must also carry `typ: at+jwt` and the current `kid`.
- Scopes: `tools/call` needs `mcp:tools`, every other method `mcp:read`; `mcp` implies both. A token lacking the scope gets **403** `error="insufficient_scope", scope="mcp:tools", resource_metadata=...` (one challenge with all needed scopes).
- `mcp.auth.authorization_server`: `builtin` or an external issuer URL (Keycloak, Okta, Entra ID, ...). External: SAJHA only validates, discovering `jwks_uri` via RFC 8414 then OIDC discovery (metadata `issuer` must equal the configured string), caching the JWKS (`jwks_cache_seconds`, forced refetch on unknown `kid` at most every 30 s). The `sub` (or `mcp.auth.external.user_claim`) is matched to a SAJHA user ID; unmatched identities get the least-privilege `api_consumer` role. JWT access tokens only (no introspection).

**Built-in authorization server** (`authorization_server: builtin`, active while mode ≠ off), backed by SAJHA users:
- RFC 8414 metadata at `/.well-known/oauth-authorization-server`: `code` + `S256` only, `authorization_code` and `refresh_token` grants, `token_endpoint_auth_methods_supported: none, client_secret_basic, client_secret_post`, `client_id_metadata_document_supported: true`, `authorization_response_iss_parameter_supported: true`, `registration_endpoint` only when DCR is on. No OpenID Connect discovery (no ID tokens are issued).
- `/oauth/authorize`: consent page (`auth/oauth_consent.html`); the user is taken from the SAJHA session cookie or signs in on the page. PKCE `S256` mandatory, `resource` must name this server (else `invalid_target`), unknown scopes dropped. Responses carry `code`, `state` and `iss` (RFC 9207), errors too.
- `/oauth/token`: RS256 JWT access tokens (`aud` = MCP resource URI, `scope`, `client_id`, 15 min default), refresh tokens only when `offline_access` is granted (`refresh_tokens` policy), rotated on every use with reuse detection. `Cache-Control: no-store`.
- `/oauth/jwks`: the public key; the private key is generated on first use at `data/oauth/signing_key.pem` (0600, git-ignored).
- Clients: Client ID Metadata Documents (https URL `client_id`, fetched and validated, public clients only), pre-registered `mcp.auth.builtin.clients`, and RFC 7591 DCR behind `dynamic_client_registration: true` (deprecated in 2026-07-28; in-memory).

**Security decisions.** Unknown client / redirect-URI mismatch render an error page and never redirect (no open redirect; redirect URIs match exactly, https or loopback http or a reverse-domain native scheme). PKCE cannot be downgraded (`plain` and missing challenges rejected). Codes are single-use, 60 s, hashed at rest; replaying one revokes the refresh tokens it minted. Tokens are audience-bound and SAJHA's own HS256 JWTs and OAuth tokens can never be confused (different algorithms, `typ`, `aud`). Consent is CSRF-proof: an HMAC form token bound to a `SameSite=Strict` per-browser transaction cookie, single-use pending requests, and `X-Frame-Options: DENY` / `frame-ancestors 'none'`. CIMD fetches are SSRF-guarded: https only (http://localhost only with `cimd.allow_localhost`), no credentials/fragments/dot-segments, DNS resolved once and every address vetted (loopback, private, link-local, reserved and IPv4-embedded IPv6 refused unless `allow_private_networks`), connection pinned to the vetted IP with SNI, no redirects, no proxies, 5 s timeouts and a 16 KiB cap; `client_id` in the document must equal the URL and shared secrets are refused. Consent sign-in is rate limited (5/min/IP).

### 4.2 MCP Apps `io.modelcontextprotocol/ui` (2026-07-28 path)

With `mcp.apps.enabled` (default `true`) `server/discover` advertises the extension; a tool config with `"_meta": {"ui": {"resourceUri": "ui://sajha/<view>.html"}}` (optional `visibility: ["model","app"]`) carries that `_meta.ui` in modern `tools/list`; `resources/list` lists the views and `resources/read` returns them as `text/html;profile=mcp-app`. Views: bundled `sajha/core/mcp_app_views/*.html` plus `*.html` in `mcp.apps.dir` (default `config/apps`), each published as `ui://sajha/<file-name-with-dashes>`. Invalid `_meta.ui` (non-`ui://`, unknown view, bad visibility) is ignored with a warning. Legacy-era responses are unchanged.

Example: `calc_loan_amortization` now also returns `yearly_schedule` (principal, interest, closing balance per year) and binds `ui://sajha/loan-amortization.html` — a self-contained view (no external scripts or network) that speaks the MCP Apps postMessage protocol (`ui/initialize`, `ui/notifications/tool-result`, `host-context-changed`, `size-changed`) and draws a stacked principal/interest bar chart with tooltips and a schedule table. Clients without Apps still get the normal text + `structuredContent` result.

### 4.3 `x-mcp-header` annotations on tool configs

Tool configs may annotate a top-level (or nested, through `properties` only) `string`/`integer`/`boolean` input property with `"x-mcp-header": "<Token>"`; 2026-07-28 clients then mirror the argument as `Mcp-Param-<Token>`, and SAJHA rejects a missing, extra or different header with `-32020` (§1.3). Because clients must drop a whole tool whose annotations are invalid, SAJHA removes invalid annotations when the schema is loaded (not reachable via `properties`, not an RFC 9110 token, on a `number`/object/array property, or a case-insensitive duplicate) and logs one warning per tool. Annotated: `symbol` → `Mcp-Param-Symbol` on `yahoo_get_quote`, `av_stock_quote` and `fmp_stock_quote`.

---

## 5. Conformance results

```bash
SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_server.py --host 127.0.0.1 --port 3092
npx -y @modelcontextprotocol/conformance@0.1.16        server --url http://127.0.0.1:3092/mcp --spec-version 2025-11-25 --suite all
npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server --url http://127.0.0.1:3092/mcp --spec-version 2026-07-28 --suite all
# extension scenarios are not on the spec timeline; run them by name with --force:
for s in tasks-lifecycle tasks-capability-negotiation tasks-wire-fields tasks-request-state-removal \
         tasks-mrtr-input tasks-request-headers tasks-dispatch-and-envelope tasks-status-notifications \
         tasks-required-task-error tasks-mrtr-composition; do
  npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server --url http://127.0.0.1:3092/mcp \
      --spec-version 2026-07-28 --scenario $s --force
done
```

| Suite | Scenarios | Checks |
|---|---|---|
| 2025-11-25 (legacy path, 0.1.16) | 32/32 | **43 passed, 0 failed** (unchanged) |
| 2026-07-28 `--suite all` (0.2.0-alpha.12) | 40/40 | **152 passed, 0 failed** (Wave 1: 125/137; before Wave 1: 11/119) |
| tasks extension scenarios (`--force`) | 10/10 | **44 passed, 0 failed** |
| `authorization` (built-in AS, `--spec-version 2026-07-28` and `2025-11-25`) | 2/2 | **3 passed, 0 failed** |

Both server suites were also run with `mcp.auth.mode=optional` (same results). The authorization suite runs against the built-in AS with a pre-registered public client; the browser step of `authorization-code-grant` (sign in, approve) was driven by a script:

```bash
SAJHA_MCP_AUTH_MODE=required SAJHA_MCP_AUTH_BUILTIN_CLIENTS='[{"client_id":"conformance","redirect_uris":["http://127.0.0.1:3000/callback"]}]' \
  python run_server.py --host 127.0.0.1 --port 3092
npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 authorization --url http://127.0.0.1:3092 \
    --client-id conformance --resource http://127.0.0.1:3092/mcp --spec-version 2026-07-28
```

The `auth/*` scenarios in the suite test *clients*, not servers.

`server-stateless` now runs all 30 checks, including the five `subscriptions/listen` checks (ack first, `subscriptionId` tagging, filter honored, tools and prompts list_changed) that were skipped while nothing advertised `listChanged`. `tasks-status-notifications` is a placeholder in this harness release (0 checks: "pending subscriptions/listen rewrite").

## 6. Official SDK client (`mcp` 2.3.0)

`mcp.Client("http://127.0.0.1:3092/mcp", mode=...)` was run in three modes:

- **`mode="2026-07-28"`:** negotiates `2026-07-28`.
- **`mode="auto"`:** runs `server/discover`, adopts `2026-07-28` and reports `serverInfo`.
- **`mode="legacy"`:** uses the initialize handshake and negotiates `2025-11-25`.

Each mode lists tools (`ttl_ms=60000`, `cache_scope="public"` on modern), calls `calc_percentage_change` (80 → 100 gives 25.0), lists 10 prompts, gets `bug_diagnosis` with its required arguments, lists resources and reads `sajha://tools/catalog`. `SajhaMCPClient` (default `mode="auto"`) negotiates `2026-07-28`, and `clientsdk/tests` covers this.

OAuth (Wave 4), `mcp.auth.mode=required`, built-in AS: `OAuthClientProvider` over `httpx2` with a pre-registered public client and, separately, with DCR enabled. Anonymous POST → 401 with `resource_metadata` + `scope`; the SDK discovered PRM and AS metadata, ran code + PKCE with `resource`, validated `iss`, received access + refresh tokens (`mcp:read mcp:tools offline_access`) and then listed tools and called `calc_loan_amortization` in both `mode="auto"` (2026-07-28) and `mode="legacy"`.

Waves 2–3 with the same SDK (auto mode, elicitation / sampling / roots callbacks):

- `call_tool(..., progress_callback=...)` receives progress 0 → 50 → 100 over the streamed response;
- `client.listen(tools_list_changed=True, prompts_list_changed=True, resource_subscriptions=["sajha://tools/catalog"])` is acknowledged with that filter and yields `ToolsListChanged` and `ResourceUpdated` after `test_trigger_tool_change`;
- `call_tool` drives MRTR automatically through the callbacks (single, multi-round, elicitation + sampling + roots at once, requestState round trip), as does `get_prompt` for the MRTR prompt;
- driving it by hand (`session.call_tool(..., allow_input_required=True)`, then `call_tool(..., input_responses=..., request_state=...)`) works, and a tampered `request_state` is rejected with `MCPError("requestState failed integrity verification")`.

## 7. Tests

`tests/test_mcp_auth.py` (OAuth: modes, PRM, challenges, API keys and SAJHA JWTs in `required` mode, wrong audience / issuer / key / expiry / HS256, insufficient scope, AS metadata, code flow with `iss`, consent sign-in, single-use codes, PKCE, no open redirect, `invalid_target`, deny, consent CSRF, refresh rotation and reuse detection, confidential clients, DCR, CIMD validation and SSRF guards) and `tests/test_mcp_apps.py` (Apps capability, `_meta.ui`, `ui://` list/read, disabled flag, `x-mcp-header` sanitising and enforcement on a real tool) were added.


`tests/test_mcp_2026_07_28.py` covers, besides the Wave 1 items (era routing, `server/discover`, `_meta` validation, every `-32020` header rule, `-32022`, `resultType`/`serverInfo`, caching fields, resource-not-found `-32602`, `-32021`, removed/unknown methods, GET/DELETE 405, error-code mapping):

- streaming: progress and log notifications over SSE, level filtering, JSON when nothing to stream, `report_progress` / `report_log` from a registry tool;
- cancellation: closing the stream cancels the producer and runs the cancel hooks; a disconnect cancels a JSON call; `is_cancelled()`;
- change bus: filtering, coalescing, cross-thread publish, shutdown, registry hooks;
- `subscriptions/listen`: ack first, `subscriptionId` tagging, filter honored, resource subscriptions, prompt-registry changes, graceful end on shutdown, validation; WebSocket push and `listChanged` per transport;
- MRTR: round trip, tampered / foreign / expired `requestState` rejected, state bound to tool and arguments, multi-round accumulation, invalid `inputResponses`, capability checks, `prompts/get`, no requests on the stream;
- destructive-tool confirmation: off by default, accept / decline, no elicitation capability, non-destructive tools;
- tasks: create / get / complete, sync fallback, `required` → `-32021`, gating, unknown task, `Mcp-Name`, cancel (idempotent), tool error vs protocol error, partial `tasks/update`, MRTR → task, registry tool `execution.taskSupport`, per-user scoping.

`tests/test_mcp_2025_11_25.py` still passes unchanged.

## 8. Known limits

- **No resumability** on the modern path (by design of 2026-07-28); legacy streams keep SEP-1699 resumption.
- **Thread-pool tools are abandoned, not killed** on cancel; they stop early only if they poll `is_cancelled()`.
- **Tasks and listen streams are per process**: run one worker or sticky routing (the HMAC `requestState` is process-independent once `mcp.mrtr.state_secret` is set).
- **Legacy streamable-HTTP sessions get no `list_changed`** (SAJHA has no GET stream; capability says `false`); 2024-11-05 SSE and WebSocket sessions do.
- **`notifications/tasks`** (optional) is not emitted.
- **OAuth state is per process**: pending consents, codes, refresh tokens and DCR registrations live in memory (a restart signs OAuth clients out; access tokens stay valid until expiry since the key is persisted). Access tokens are not revocable before `exp` (15 min default).
- **External authorization servers**: JWT access tokens only (no RFC 7662 introspection); no CORS on `/oauth/*` for browser-based clients; set `mcp.auth.public_url` in production (without it, issuer and audience follow the request `Host`).
- **The WebSocket transport** accepts SAJHA JWTs / API keys only (`?token=` / `?api_key=`); in `required` mode an unauthenticated socket is closed (1008).
