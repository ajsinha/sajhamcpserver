# Glossary

Every acronym, term of art and SAJHA-specific word you are likely to meet in this repository,
the in-app Help, the user guides and the protocol compliance reports, defined in one place.
The web console renders its glossary pages from this file, so this is the only copy to keep current.

Written for someone who does *not* already know the field. Where a term has a general meaning
**and** a specific meaning inside SAJHA, both are given; the second is usually the one that matters.

**Jump to:** [Platform](#1-sajha-and-the-platform) · [MCP core](#2-mcp-protocol-core) ·
[MCP 2026-07-28](#3-mcp-2026-07-28-stateless-features) · [Transports](#4-transports-and-sessions) ·
[Security](#5-authorization-and-security) · [Tools and prompts](#6-tools-prompts-and-resources) ·
[Studio and composition](#7-studio-and-composition) · [Operations](#8-operations-and-infrastructure) ·
[AI](#9-ai-integration) · [User interface](#10-user-interface) · [Data sources](#11-data-sources-and-domain)

---

## 1. SAJHA and the platform

| Term | Meaning |
|---|---|
| **SAJHA** (*साझा*) | Hindi/Urdu for "shared", "common" or "collaborative". The name reflects the server's purpose: one shared bridge between AI systems and enterprise data sources. |
| **SAJHA MCP Server** | A Python MCP server that exposes a large catalogue of data and analytics tools, prompts and resources to AI clients, with a web console for administration, monitoring and tool creation (MCP Studio). It speaks both MCP eras (see **dual-era**). |
| **SajhaMCPServerWebApp** | The main application class in `sajha/app.py`. Creates the FastAPI app, initialises every subsystem and manages the lifecycle. |
| **FastAPI** | The ASGI web framework SAJHA runs on (it replaced Flask). Provides async request handling, dependency injection and generated OpenAPI docs. |
| **Uvicorn** | The ASGI server that runs the FastAPI application. |
| **Lifespan** | The FastAPI async context manager (`_lifespan()` in `app.py`) that runs initialisation on startup and cleanup on shutdown. |
| **Route module** | An `APIRouter` in `sajha/routes/` (MCP, OAuth, admin, studio, API, A2A, WebSocket, …) registered with the app at startup. |
| **application.yml** | The single configuration file, `config/application.yml`. Drives paths, database, logging, storage, MCP, OAuth, AI and plugin settings. Supports `${ENV_VAR:default}` substitution, and every key can be overridden with a `SAJHA_`-prefixed environment variable (e.g. `SAJHA_MCP_AUTH_MODE`). |
| **Settings** | A dataclass in `sajha/core/config.py` exposing typed configuration values derived from `application.yml`. |
| **PropertiesConfigurator** | A singleton (`sajha/core/properties_configurator.py`) that resolves `${variable}` references in tool JSON configs from the flattened YAML configuration. |
| **DAO** (*Data Access Object*) | The classes in `sajha/db/dao/` that encapsulate database queries (users, roles, permissions, API keys, executions, errors, sessions). |
| **DeclarativeBase** | SQLAlchemy's base class for the ORM models, in `sajha/db/base.py`. |
| **url_for** | A custom template function in `app.py` that maps endpoint names to URL paths, giving Flask-style URL resolution in the Jinja2 templates. |
| **Jinja2** | The template engine behind the web console pages and behind prompt templates, supporting variable substitution, conditions and loops. |
| **Client SDK** | The Python package in `clientsdk/` (`sajhaclient`). `SajhaMCPClient` wraps the official MCP SDK and by default (`mode="auto"`) probes `server/discover` and adopts 2026-07-28; it also has REST, A2A and transport-level clients. |
| **Plugin** | An extension package in `config/plugins/` (setting `plugins.dir`) with a `plugin.json` manifest, containing tool configs and optionally Python classes. Flow: `discover()`, `validate()` (checksum), `load_plugin()` (install dependencies, register tools). |
| **Tenant** | An isolated customer or team in multi-tenant mode (`sajha/core/tenancy.py`): tenant-scoped tool configs, its own API key pool, usage quotas (tool calls per day/month, sessions, LLM tokens) and allowed providers. |
| **A2A** (*Agent-to-Agent*) | A protocol for inter-agent communication. SAJHA publishes an agent card at `/.well-known/agent.json` and serves the task lifecycle (`tasks/send`, `tasks/get`, `tasks/cancel`) as JSON-RPC on `POST /a2a`. These A2A tasks are unrelated to MCP tasks. |
| **Agent card** | The A2A discovery document at `/.well-known/agent.json` describing the agent's name, skills and endpoint. |

---

## 2. MCP protocol core

| Term | Meaning |
|---|---|
| **MCP** (*Model Context Protocol*) | An open standard that lets AI applications discover and invoke external **tools**, read **resources** and fetch **prompts** from servers, over JSON-RPC 2.0. SAJHA implements the stateless 2026-07-28 revision alongside the handshake-era revisions 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05. |
| **JSON-RPC 2.0** | The wire protocol of MCP. A request carries `jsonrpc: "2.0"`, `id`, `method` and optionally `params`; the reply carries the same `id` and either `result` or `error` (code, message, data). A message without `id` is a notification. |
| **Protocol version** | The MCP revision a request speaks, a date such as `2026-07-28` or `2025-11-25`. Legacy clients negotiate it in `initialize`; modern clients send it on every request in `_meta` and the `MCP-Protocol-Version` header. |
| **Dual-era** | SAJHA serves both MCP eras on the same `/mcp` endpoint: the stateless 2026-07-28 "modern" protocol and the handshake-based 2025-11-25-and-earlier "legacy" protocol. Each request is routed by era detection. |
| **Era detection** | How `POST /mcp` picks a path: `_meta["io.modelcontextprotocol/protocolVersion"]` (or a non-handshake `MCP-Protocol-Version` header) means modern; `initialize` without it, and everything else, means legacy. |
| **Modern path** | The 2026-07-28 code path (`sajha/core/mcp_modern.py`): stateless, every request self-describing through `_meta` and routing headers, no `initialize`, no sessions. Reuses `MCPHandler`'s tool, prompt, resource and completion logic. |
| **Legacy path** | The handshake-era code path (`MCPHandler`, `sajha/core/mcp_2025_11_25.py`): `initialize` / `notifications/initialized`, `Mcp-Session-Id` sessions, server-to-client requests on SSE streams. Unchanged by the 2026-07-28 work. |
| **initialize** | The legacy handshake: the client sends its protocol version, capabilities and info; the server answers with the negotiated version, its capabilities, `serverInfo` and `instructions`. Removed in 2026-07-28 (answered `-32601` on the modern path). |
| **Capabilities** | The features each side declares. Server: `tools`, `prompts`, `resources` (with `listChanged`, `subscribe`), `logging`, `completions` and, on the modern path, `extensions`. Client: `elicitation`, `sampling`, `roots`. SAJHA advertises them truthfully per era and transport. |
| **Extensions** | Optional protocol add-ons advertised under `capabilities.extensions` by a reverse-DNS id, e.g. `io.modelcontextprotocol/tasks` and `io.modelcontextprotocol/ui`. |
| **_meta** | The reserved metadata object in `params` and results. On the modern path it carries the per-request context (`io.modelcontextprotocol/protocolVersion`, `clientCapabilities`, `clientInfo`, `logLevel`, `progressToken`, trace context) and results carry `io.modelcontextprotocol/serverInfo`. |
| **Tool** | A callable function exposed over MCP: a `name`, `description`, `inputSchema` and optional `title`, `outputSchema`, `annotations`, `icons`. Listed by `tools/list`, invoked by `tools/call`. |
| **Resource** | Read-only content addressed by a URI (e.g. `sajha://tools/catalog`, `ui://sajha/…`), listed by `resources/list` and fetched by `resources/read`. |
| **Prompt** (*MCP*) | A server-provided message template with named arguments, listed by `prompts/list` and rendered by `prompts/get`. |
| **inputSchema** | The JSON Schema (2020-12 dialect) describing a tool's arguments. SAJHA passes it through untouched, so `$schema`, `$defs` and `additionalProperties` survive. |
| **outputSchema** | An optional JSON Schema for a tool's result object. When advertised, the result is also returned as `structuredContent` and validated (mismatches are logged). Switch off with `mcp.tools.advertise_output_schema: false`. |
| **structuredContent** | The machine-readable JSON object in a `tools/call` result, alongside the human-readable `content` blocks; clients validate it against the tool's `outputSchema`. |
| **isError** | The flag on a `tools/call` result that marks a tool-level failure. Tool failures are results with `isError: true`, not JSON-RPC errors; protocol failures are JSON-RPC errors. |
| **Annotations** | Behaviour hints on a tool (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`), set in the tool config's `annotations` block and shown in `tools/list`. |
| **destructiveHint** | The annotation marking a tool that changes or deletes things. With `mcp.confirm_destructive_tools: true`, a modern `tools/call` of such a tool first asks the user to confirm through form-mode elicitation. |
| **Icons** | The spec `icons` array `[{src, mimeType?, sizes?}]` on tools, built from a tool config's `icons` list or legacy `icon` setting (emoji become SVG data URIs). |
| **Cursor-based pagination** | List methods (`tools/list`, `resources/list`, …) return a `nextCursor`; the client passes it back as `cursor` to get the next page. |
| **Completion** | `completion/complete`: argument autocompletion for prompt arguments (`ref/prompt`) and tool enum values (`ref/tool`). |
| **Logging** (*MCP*) | Server log messages sent as `notifications/message` at RFC 5424 levels. Legacy clients set the level with `logging/setLevel`; modern clients send `_meta["io.modelcontextprotocol/logLevel"]` per request. |
| **Progress** | `notifications/progress` messages tied to the request's `progressToken`, reporting how far a long tool call has got. |
| **Cancellation** | Stopping an in-flight request. Legacy and WebSocket clients send `notifications/cancelled`; on the modern path the client simply closes the connection. |
| **Elicitation** | A server asking the user, through the client, for input: **form** mode (a JSON Schema form) or **URL** mode (send the user to a page). It is a client capability. Legacy servers send `elicitation/create` as a server-to-client request; the modern path asks through MRTR. |
| **Sampling** | A server asking the client's LLM for a completion (`sampling/createMessage`), optionally with tools. A client capability, used on the legacy path by server-to-client request and on the modern path through MRTR. |
| **Roots** | The filesystem or URI roots a client exposes (`roots/list`). A client capability, requested through MRTR on the modern path. |
| **list_changed** | Notifications (`notifications/tools/list_changed`, `prompts/…`, `resources/…`) telling a client that a list has changed and should be fetched again. SAJHA sends them on `subscriptions/listen` streams, the legacy HTTP+SSE stream and WebSocket, fed by the change bus; legacy Streamable HTTP sessions advertise `listChanged: false`. |
| **resources/subscribe** | The legacy per-URI subscription method (accepted, returns `{}`). Removed in 2026-07-28 in favour of `resourceSubscriptions` on `subscriptions/listen`. |
| **MCPHandler** | The core legacy-era handler (`sajha/core/mcp_handler.py`) that routes every MCP JSON-RPC method. It has hooks for role-based tool access, inactive in this release because it is created without an auth manager. Shared by the Streamable HTTP, HTTP+SSE and WebSocket transports, and reused by the modern path for business logic. |
| **SEP** (*Specification Enhancement Proposal*) | A numbered proposal that changes the MCP spec, e.g. SEP-2322 (MRTR), SEP-2549 (caching hints), SEP-2663 (tasks extension). |
| **Conformance suite** | The official `@modelcontextprotocol/conformance` test harness. SAJHA passes it for 2025-11-25 (legacy path), for 2026-07-28 including the tasks-extension scenarios, and for the `authorization` scenarios; it runs in CI. |
| **Conformance fixtures** | The test tools, prompts and resources the suite expects (`test_simple_text`, `test://static-text`, …), in `sajha/core/mcp_conformance_fixtures.py`. Off by default; enabled with `mcp.conformance_fixtures` or `SAJHA_MCP_CONFORMANCE_FIXTURES=true`. For protocol testing only. |

---

## 3. MCP 2026-07-28 (stateless) features

| Term | Meaning |
|---|---|
| **Stateless request** | A 2026-07-28 request that carries everything the server needs (version, client capabilities, client info, log level) in its own `_meta`. The server keeps no session and ignores `Mcp-Session-Id` and `Last-Event-ID`. |
| **server/discover** | The 2026-07-28 replacement for `initialize`: returns `supportedVersions` (newest first), `capabilities` and `instructions`, with caching hints. Clients in auto mode call it to choose an era. |
| **MCP-Protocol-Version** (*header*) | The HTTP header naming the request's protocol version. On the modern path it must equal `_meta.protocolVersion`; an unsupported value gets `-32022`. Legacy clients send it after `initialize`. |
| **Mcp-Method** (*header*) | A 2026-07-28 routing header that must equal the JSON-RPC `method`, so gateways can route without parsing the body. Mismatch or absence gets `-32020`. |
| **Mcp-Name** (*header*) | A 2026-07-28 routing header that must equal `params.name` (`tools/call`, `prompts/get`), `params.uri` (`resources/read`) or the `taskId` (`tasks/*`). May be `=?base64?…?=`-encoded. |
| **Validation ladder** | The order in which the modern path checks a request, first failure wins: duplicated routing headers, required `_meta` fields, header/body agreement, protocol version, then `Mcp-Param-*` headers. |
| **-32020 / -32021 / -32022** | 2026-07-28 error codes: header mismatch or missing header; missing client capability (`data.requiredCapabilities`); unsupported protocol version (`data.supported`). All with HTTP 400. |
| **resultType** | The field every modern result carries: `"complete"`, `"input_required"` (MRTR) or `"task"` (a created task). |
| **ttlMs / cacheScope** | Caching hints (SEP-2549) on `server/discover` and the list and read results: how long the result may be reused, and whether it is `public` or `private` (per caller). Set under `mcp.cache`; `scope: auto` marks per-user filtered lists private. |
| **MRTR** (*Multi Round-Trip Requests*) | The 2026-07-28 way for a stateless server to get input mid-request (SEP-2322): instead of sending the client a request, `tools/call`, `prompts/get` or `resources/read` answers `resultType: "input_required"` with `inputRequests` and a `requestState`; the client retries the same request with `inputResponses`. |
| **InputRequiredResult** | The MRTR result shape: `resultType: "input_required"`, `inputRequests` and `requestState`. A handler triggers it by raising `sajha.core.mcp_mrtr.InputRequired`. |
| **inputRequests / inputResponses** | The keyed maps of an MRTR round: the server's embedded requests (`elicitation/create`, `sampling/createMessage`, `roots/list`) and the client's answers under the same keys. Missing keys are asked again; requests the client has no capability for get `-32021`. |
| **requestState** | The opaque MRTR token echoed back by the client: an HMAC-SHA256 signed (not encrypted) payload bound to the method, tool/prompt/URI, an argument digest and the caller, expiring after `mcp.mrtr.state_ttl_seconds`, accumulating earlier rounds' answers so multi-round flows need no server memory. Tampered, expired or foreign states get `-32602`. |
| **subscriptions/listen** | The 2026-07-28 long-lived POST answered as an SSE stream. The client opts in to `toolsListChanged`, `promptsListChanged`, `resourcesListChanged` and `resourceSubscriptions`; the first message is `notifications/subscriptions/acknowledged`, and every message carries the `subscriptionId`. Capped by `mcp.subscriptions.max_streams`. |
| **Change bus** | `sajha/core/change_bus.py`: a thread-safe, coalescing fan-out of list-changed and resource-updated events from `ToolsRegistry` and `PromptsRegistry` to listen streams, the legacy SSE stream and WebSocket. Identical queued events are dropped, so reloading many tools is one notification. |
| **Tasks extension** (*io.modelcontextprotocol/tasks*) | The 2026-07-28 extension (SEP-2663) for long-running tool calls: a task-capable `tools/call` returns `resultType: "task"` with a `taskId`, and the client uses `tasks/get` (status, inlined result), `tasks/update` (answer input) and `tasks/cancel`. Advertised under `capabilities.extensions` when `mcp.tasks.enabled`; stored in memory per process and per user (`sajha/core/mcp_tasks.py`). |
| **taskSupport** | A tool's opt-in to the tasks extension, `"execution": {"taskSupport": "optional"}` or `"required"` in its config. Optional tools run synchronously for clients without the extension; required tools refuse them with `-32021`. |
| **CreateTaskResult** | The flat result of a task-creating call: `resultType: "task"`, `taskId`, `status: "working"`, timestamps, `ttlMs`, `pollIntervalMs`. |
| **Task status** | A task's state: `working`, `input_required` (parked for client input), `completed` (result inlined; a tool error is `completed` with `isError`), `failed` (protocol-level error) or `cancelled`. |
| **MCP Apps** (*io.modelcontextprotocol/ui*) | The extension that lets a tool ship an interactive HTML view the host renders beside the result. A tool binds a view with `"_meta": {"ui": {"resourceUri": "ui://sajha/<view>.html"}}`; enabled by `mcp.apps.enabled` (default true), modern path only. |
| **ui:// resource** | An MCP Apps view, listed by `resources/list` and served by `resources/read` as `text/html;profile=mcp-app`. Bundled views live in `sajha/core/mcp_app_views/`, extra ones in `mcp.apps.dir` (default `config/apps`). Views are self-contained and talk to the host by postMessage. |
| **text/html;profile=mcp-app** | The MIME type that marks a resource as an MCP Apps view rather than ordinary HTML. |
| **x-mcp-header** | A JSON Schema annotation on a string, integer or boolean tool input property (`"x-mcp-header": "Symbol"`) asking 2026-07-28 clients to mirror that argument in an HTTP header so gateways can route on it. SAJHA strips invalid annotations at load time. |
| **Mcp-Param-{Name}** (*header*) | The header carrying an `x-mcp-header` argument, e.g. `Mcp-Param-Symbol`. SAJHA rejects a missing, extra, different or malformed-base64 value with `-32020`. |
| **Destructive-tool confirmation** | With `mcp.confirm_destructive_tools: true` (default false), a modern call of a `destructiveHint` tool returns an MRTR form elicitation with a `confirm` boolean; decline or cancel returns `isError: true` without running the tool. |
| **mcp_tool_context** | `sajha/core/mcp_tool_context.py`: lets any SAJHA tool call `report_progress()`, `report_log()` and `is_cancelled()` from its thread-pool `execute`; no-ops unless the caller asked for progress or logs. |
| **Resumability** | Reconnecting to a dropped SSE stream with `Last-Event-ID`. The modern path has none by design (a dropped stream is a cancelled request); SAJHA's legacy streams do not replay either. |

---

## 4. Transports and sessions

| Term | Meaning |
|---|---|
| **Streamable HTTP** | The standard MCP transport, on `POST /mcp`: a JSON-RPC message in, an `application/json` or `text/event-stream` (SSE) response out. Used by both eras; notifications get `202`, JSON arrays (batches) `400`, and a streaming-client `GET /mcp` gets `405`. |
| **Mcp-Session-Id** | The legacy session header: set on the `initialize` response and sent by the client on every later request. An unknown id gets `404` (re-initialize); `DELETE /mcp` ends the session. Sessions live in process memory (`sajha/core/mcp_sessions.py`). Ignored on the modern path. |
| **HTTP+SSE** (*legacy*) | The 2024-11-05 transport: `GET /mcp/sse` opens an event stream (an `endpoint` event, then messages) and the client POSTs to `/mcp/message`. Legacy era only. |
| **SSE** (*Server-Sent Events*) | A one-way HTTP streaming format (`text/event-stream`). In MCP it carries streamed responses, notifications and, on the legacy path, server-to-client requests. |
| **WebSocket extension** | SAJHA's full-duplex transport at `/mcp/ws`, outside the MCP spec and legacy era only. Authenticates with `?token=` (SAJHA JWT) or `?api_key=`; accepts JSON-RPC batches; receives change-bus `list_changed` pushes. Advertised under `experimental.sajha.websocket`. |
| **Last-Event-ID** | The SSE reconnect header naming the last event received. SAJHA's legacy streams carry event ids but do not replay; the modern path ignores it. |
| **Origin allow-list** | `mcp.allowed_origins` (env `SAJHA_MCP_ALLOWED_ORIGINS`): browser `Origin`s allowed to call `/mcp`; others get `403`. Requests without `Origin` and localhost/127.0.0.1/[::1] on any port are always allowed; `"*"` disables the check. |
| **DNS rebinding** | An attack where a malicious web page re-points its own hostname at `127.0.0.1` to reach a local server from the victim's browser. The Origin allow-list blocks it. |
| **CORS** (*Cross-Origin Resource Sharing*) | Browser rules for cross-site requests. SAJHA exposes `Mcp-Session-Id` via `Access-Control-Expose-Headers`; `/oauth/*` has no CORS. |
| **Batching** | Sending a JSON array of JSON-RPC messages. Removed from MCP in 2025-06-18: `POST /mcp` answers `400`; the WebSocket transport still accepts batches. |
| **Legacy MCP tasks** (*MCPTask*) | The 2025-11-25 core `tasks/get`, `tasks/list`, `tasks/cancel` methods, still present on the legacy path but not advertised (tool calls are never task-augmented there). Distinct from the 2026-07-28 tasks extension. |
| **elicitation/respond** | A SAJHA-only extension method kept for older clients. It is not an MCP method: in MCP a client answers `elicitation/create` with a JSON-RPC response. |
| **Experimental capabilities** | `capabilities.experimental.sajha`: SAJHA-specific settings (WebSocket endpoint and auth methods, JSON Schema dialect) advertised on legacy `initialize`. |

---

## 5. Authorization and security

| Term | Meaning |
|---|---|
| **OAuth 2.1** | The authorization framework the MCP spec uses: short-lived bearer access tokens, authorization code with mandatory PKCE, no implicit grant. SAJHA implements it for `/mcp` on both eras, with a built-in authorization server or an external issuer. |
| **mcp.auth.mode** | Turns OAuth on `/mcp`: `off` (default; anonymous allowed, `/.well-known/oauth-*` are 404), `optional` (bearer tokens validated and accepted, anonymous still allowed, an invalid token gets 401) or `required` (no valid credential gets 401 with a `WWW-Authenticate` challenge). API keys and SAJHA JWTs work in every mode. |
| **Authorization server** (*AS*) | The service that signs users in and issues tokens. `mcp.auth.authorization_server` is `builtin` or an external issuer URL. |
| **Built-in authorization server** | SAJHA's own AS, backed by SAJHA users and active while the mode is not `off`: `/oauth/authorize` (consent page), `/oauth/token` (RS256 JWT access tokens, 15 min default), `/oauth/jwks`, and `/oauth/register` only when DCR is on. Issues no ID tokens. |
| **External issuer** | An outside IdP (Keycloak, Okta, Entra ID, …) named by URL. SAJHA only validates its JWT access tokens, discovering `jwks_uri` via RFC 8414 then OIDC discovery; the `sub` claim (or `mcp.auth.external.user_claim`) is matched to a SAJHA user, unmatched identities get the `api_consumer` role. No token introspection. |
| **Resource server** | The API that accepts tokens; here the MCP endpoints. OAuth access tokens are accepted only on MCP endpoints, never on the REST API. |
| **PRM** (*Protected Resource Metadata, RFC 9728*) | The discovery document at `/.well-known/oauth-protected-resource` (and `…/mcp`) naming the resource URI, its authorization servers, `scopes_supported` and bearer methods. Served only when OAuth is on. |
| **AS metadata** (*RFC 8414*) | The authorization server's discovery document at `/.well-known/oauth-authorization-server`: endpoints, `code` + `S256` only, grants, client auth methods and `client_id_metadata_document_supported: true`. |
| **PKCE** (*Proof Key for Code Exchange*) | Binds an authorization code to the client that asked for it (a hashed `code_challenge`, then the `code_verifier`). SAJHA requires method **S256**; `plain` and missing challenges are refused. |
| **CIMD** (*Client ID Metadata Document*) | A client registration scheme where the `client_id` is an https URL of a JSON document the client hosts. SAJHA's built-in AS fetches and validates it, with SSRF guards (https only, vetted and pinned IPs, no redirects, size and time limits). SAJHA does not host such documents. |
| **DCR** (*Dynamic Client Registration, RFC 7591*) | Clients registering themselves at `/oauth/register`. Off by default (`dynamic_client_registration`), deprecated in 2026-07-28, kept in memory. |
| **Pre-registered client** | An OAuth client listed in `mcp.auth.builtin.clients` (env `SAJHA_MCP_AUTH_BUILTIN_CLIENTS`); public (PKCE only) unless given a `client_secret`. |
| **Resource indicator** (*RFC 8707*) | The `resource` parameter naming the API a token is for. It must be this server's `/mcp` URI (else `invalid_target`), and becomes the token's audience. |
| **Audience** (*aud*) | The token claim naming who may accept it. SAJHA requires its own resource URI (`<public_url>/mcp`) or a value in `mcp.auth.accepted_audiences`, so tokens minted for other APIs are refused. |
| **public_url** | `mcp.auth.public_url`: the externally visible origin from which the resource URI, audience and built-in issuer derive. Set it in production; empty means "use the request's Host". |
| **Scope** | A permission named in a token. `tools/call` needs `mcp:tools`, every other MCP method `mcp:read`; `mcp` implies both. `offline_access` asks for a refresh token. |
| **WWW-Authenticate challenge** | The header on 401/403 responses telling a client how to authenticate: `Bearer resource_metadata="<PRM URL>", scope="mcp:read mcp:tools"`, or `error="insufficient_scope"` (403) and `error="invalid_token"` (401). |
| **JWKS** (*JSON Web Key Set*) | The public keys that verify token signatures. The built-in AS serves its key at `/oauth/jwks` (private key generated on first use at `data/oauth/signing_key.pem`); external JWKS are cached for `jwks_cache_seconds` and refetched on an unknown `kid`. |
| **Refresh-token rotation** | Each use of a refresh token returns a new one and invalidates the old; reusing an old token is detected and revokes the chain. Issued only when `offline_access` is granted (`refresh_tokens` policy). |
| **iss parameter** (*RFC 9207*) | The issuer returned with every authorization response so clients can detect mix-up attacks. |
| **JWT** (*JSON Web Token*) | A signed JSON token. SAJHA's own login/session tokens are HS256 JWTs (python-jose, `sajha_token` cookie or `Authorization: Bearer`); OAuth access tokens are RS256 with `typ: at+jwt`. The two can never be confused (different algorithm, type and audience). |
| **Bearer token** | A token sent as `Authorization: Bearer <token>`; whoever holds it is authenticated. Used for SAJHA JWTs and OAuth access tokens. |
| **Session token** | The SAJHA JWT issued after a successful web login, stored in the `sajha_token` cookie. |
| **API key** | A long-lived credential for programs, prefixed `sja_`, sent in the `X-API-Key` header (or `?api_key=` on WebSocket). Stored as a SHA-256 hash; carries a tool access mode, optional rate limits and an expiry. Works in every `mcp.auth.mode` and is not scope-checked. |
| **X-API-Key header** | The HTTP header that carries a SAJHA API key, e.g. `curl -H "X-API-Key: sja_…"`. |
| **Tool access** | Which tools a user or API key may run. Intended to follow a user's roles, or an API key's tool access mode (`*` means all tools); disallowed calls get `-32010`. In this release it is enforced on the REST execute route for users only, not on MCP endpoints and not for API key lists (see the Security Model). |
| **Tool access mode** | How an API key's tool permissions are decided: `all`, `allowlist`, `denylist` or `regex`. |
| **Allowlist** | API key tool access mode where only the selected tools are permitted. |
| **Denylist** | API key tool access mode where every tool except the selected ones is permitted. |
| **Regex pattern** | API key tool access mode where tool names matching a regular expression are permitted. |
| **Expiration** | The date after which an API key stops working. |
| **Rate limiting** | Capping requests per period. API keys can carry per-minute and per-hour limits (`rate_limit_rpm`, `rate_limit_rph`). |
| **Key rotation** | Replacing an API key periodically with a new one and retiring the old, limiting the damage of a leak. |
| **Key revocation** | Invalidating an API key so it can no longer be used, by disabling or deleting it. |
| **API key deletion** | Permanently removing an API key; every application using it loses access immediately. Delete unused keys to minimise the attack surface. |
| **RBAC** (*Role-Based Access Control*) | Authorization where permissions are attached to roles and roles to users (`user_roles`, `role_permissions` tables). |
| **Role** | A named set of permissions. Seeded roles: `admin` (full access), `user` (standard tool access), `viewer` (read-only), `developer` (MCP Studio). `api_consumer` is the least-privilege identity given to unmatched external OAuth users. |
| **User ID** | The unique login name of a user account; cannot be changed after creation. External OAuth identities are matched to it. |
| **Account status** | Whether a user account is enabled or disabled for login. |
| **Password hash** | The stored form of a password: bcrypt (cost 12), used directly rather than through passlib. Passwords are never stored in plain text. |
| **AuthContext** | The dataclass the auth dependencies return to routes: `user_id`, `user_name`, `roles`, `is_admin`, auth type. |
| **AuthManager** | The authentication orchestrator (`sajha/auth/__init__.py`, with `sajha/core/auth_manager.py`) that resolves cookies, bearer tokens, API keys and OAuth tokens into an `AuthContext`. |
| **Consent page** | The built-in AS's approval page (`/oauth/authorize`): CSRF-protected, frame-blocked, sign-in rate-limited, never redirecting to an unregistered URI. |
| **AuditLogger** | Structured security event logging (`sajha/core/audit.py`) to the `audit_log` table: logins, logouts, user and API key changes, tool executions, config and permission changes, account locks. |
| **Audit log** | The record of user and security actions kept for security and compliance review. |
| **SSRF** (*Server-Side Request Forgery*) | Tricking a server into fetching internal URLs. CIMD fetches are guarded against it. |

---

## 6. Tools, prompts and resources

| Term | Meaning |
|---|---|
| **BaseMCPTool** | The abstract base class (`sajha/tools/base_mcp_tool.py`) every tool extends, implementing `get_input_schema()`, `get_output_schema()` and `execute()`. |
| **Tool configuration** | A JSON file in `config/tools/` defining a tool's name, implementation class, description, schemas and metadata (`annotations`, `cache_ttl`, `execution.taskSupport`, `_meta.ui`, literature). |
| **JSON Configuration** | The underlying JSON document that defines a tool or prompt, editable in the console. |
| **JSON Schema** | A vocabulary for describing and validating the structure of JSON documents; SAJHA uses the 2020-12 dialect for tool schemas. |
| **Input Schema** | The JSON Schema of the parameters a tool accepts (MCP `inputSchema`). |
| **Output Schema** | The JSON Schema of a tool's result (MCP `outputSchema`). |
| **Properties** | The named fields defined in a JSON Schema object. |
| **Required** | The fields that must be supplied when calling a tool. |
| **Type** | A schema field's data type: `string`, `number`, `integer`, `boolean`, `object`, `array`. |
| **Arguments** (*tool*) | The parameter values passed to a tool when it is executed. |
| **Execute** | Running a tool with arguments to produce a result. |
| **Execution Result** | The output a tool returns after processing. |
| **Execution History** | The list of a tool's previous executions in the current browser session. |
| **Enabled** / **Tool Status** | Whether a tool is active and offered to clients (enabled) or hidden (disabled). Enabling or disabling publishes a `list_changed`. |
| **ToolsRegistry** | The singleton (`sajha/tools/tools_registry.py`, `get_tools_registry()`) that loads, instantiates and manages every tool from its JSON config, supports hot-reload and publishes changes to the change bus. |
| **Tool group** | A UI grouping taken from the text before the first `_` in a tool name (`yahoo_get_quote` is in group `yahoo`). |
| **Generic tool pattern** | One Python class serving many tools by deriving the API endpoint from the tool name (`FMPGenericTool`, `OpenBBGenericTool`, `FREDCustomSeriesTool`); a new tool needs only a JSON config. |
| **Tool versioning** | Running v1 and v2 of a tool side by side with a lifecycle `active`, `deprecated`, `sunset` (still registered, returns a warning), `retired` (removed from `tools/list`), plus contract testing (`sajha/core/tool_versioning.py`). |
| **Literature** | Contextual documentation attached to a tool to help an AI understand when and how to use it; also indexed by semantic tool search. |
| **Catalog resources** | `sajha://tools/catalog` and `sajha://prompts/catalog`: resources listing the tools and prompts, updated (with `resources/updated`) whenever they change. |
| **Prompt** | A text instruction or template given to an AI system. SAJHA manages reusable prompt templates and serves them over MCP. |
| **Prompt template** / **Template** | A prompt's raw text with `{{variable}}` placeholders that are filled in at runtime. |
| **Variable substitution** | Replacing placeholders like `{{variable}}` with actual values when a prompt is rendered. |
| **Arguments** (*prompt*) | The named variables a prompt template accepts, each with a description and a required flag. |
| **Category** | A grouping for organising related prompts. |
| **Description** | Human-readable explanation of a prompt's or tool's purpose. |
| **Render** | Processing a template with the supplied arguments to produce the final text. |
| **Output** (*prompt*) | The final rendered text after substitution. |
| **Test** (*prompt*) | Trying a prompt with sample arguments to see its rendered output. |
| **Prompts Registry** | The singleton (`PromptsRegistry`) that manages prompt definitions in `config/prompts/` and renders them; changes publish to the change bus. |
| **Prompt management** | The admin functions for creating, editing and deleting prompt templates. |
| **Tool management** | The admin functions for enabling, disabling, reloading and monitoring tools. |

---

## 7. Studio and composition

| Term | Meaning |
|---|---|
| **MCP Studio** | The visual tool-creation console at `/studio` (signed-in users; the seeded `developer` role is meant for it). Generates a tool's Python class and JSON config without hand-coding. |
| **Creator** | One of Studio's tool builders: Python Code, REST Service, DB Query, Script, Power BI Report, Power BI DAX, LiveLink, SharePoint and OLAP. |
| **@sajhamcptool decorator** | A Python decorator that marks a function for conversion into an MCP tool by the Python Code creator. |
| **AST** (*Abstract Syntax Tree*) | The parsed structure of code. Studio analyses a function's AST to find its name, parameters, type hints and docstring. |
| **Type hints** | Python parameter annotations Studio turns into the tool's JSON input schema. |
| **Docstring** | The function documentation string Studio extracts as the tool description. |
| **Code generation** | Studio's automatic production of the tool class and its JSON configuration. |
| **Template** (*Studio*) | A pre-built example in the Studio examples page that can be customised into a new tool. |
| **REST** (*Representational State Transfer*) | An architectural style for HTTP APIs built on resources and HTTP methods; the REST creator wraps such an API as a tool. |
| **HTTP method** | A request's action: `GET` (retrieve), `POST` (create), `PUT` (update), `DELETE` (remove). |
| **Endpoint** | The URL where an API receives requests. |
| **Path parameter** | A variable part of a URL path, e.g. `/users/{id}`. |
| **Content-Type** | The HTTP header naming the request or response body format, e.g. `application/json`. |
| **Basic authentication** | HTTP authentication with a username and password in the `Authorization` header. |
| **API key** (*REST creator*) | A token for the external API being wrapped, passed in a header the creator configures. Not a SAJHA `sja_` key. |
| **Query template** | A DB Query tool's SQL with parameter placeholders filled in at call time. |
| **Parameter escaping** | Automatic quoting and escaping of parameter values to prevent SQL injection. |
| **Connection string** | The database connection details: host, port, credentials and database name. |
| **DuckDB** | An in-process analytical (OLAP) database that queries local files such as CSV and Parquet. |
| **SQLite** | A lightweight file-based relational database; SAJHA's default store. |
| **PostgreSQL** | An open-source relational database for production workloads; supported as SAJHA's store and as a DB Query target. |
| **MySQL** | A popular open-source relational database, supported as a DB Query target. |
| **Composite tool** | A tool that orchestrates several tools in one call, defined declaratively in the database with schemas built at load time (`sajha/tools/composite_tool.py`). Arrangements: sibling and parent-child. |
| **Sibling** (*composite*) | A parallel composite: all steps run concurrently on shared or mapped inputs and their outputs are merged. |
| **Parent-child** (*composite*) | A fan-out composite: the parent runs first, then the child runs once per record of the parent's output. |
| **Kleisli composition** | From category theory: composing functions that return wrapped (monadic) values. In SAJHA every tool is a Kleisli arrow `Dict → StepResult`, composed with `bind()`: errors short-circuit, traces accumulate, confidence compounds. |
| **StepResult** | The monadic result envelope (`sajha/core/composition.py`): value, error, trace, duration, confidence, step name. `pure()` lifts a value (confidence 1.0), `fail()` an error (0.0), `bind()` chains. |
| **PipelineResult** | The final output of a composite pipeline: merged tool outputs plus a `_composition` block (confidence, entropy bits, trace, guard result, steps executed). |
| **ParamLens** | A lens (view/set pair) that projects parent output into child parameters: `$.field` (from the current record), `$input.field` (from the original input) or a literal; `set()` merges the child result back. |
| **EntropyGuard** | Tracks per-step confidence through a pipeline and its cumulative Shannon entropy; refuses a pipeline above `max_entropy_bits`. Sequential steps multiply confidence, parallel steps take the minimum. |
| **Shannon entropy** | An information-theoretic measure of uncertainty in bits, `H = -p·log2(p) - (1-p)·log2(1-p)`: 0 bits for a certain result, 1 bit for a 50/50 one. |
| **Confidence score** | A 0.0–1.0 estimate of a tool's reliability: 1.0 deterministic (calculators), about 0.95 a stable API (FRED), about 0.80 a web crawl. Composites compound it. |
| **Weakest-link model** | The confidence rule for parallel steps: `min` of the steps' scores, since the composite is only as reliable as its least reliable independent part. |
| **ClientPipeline** | Client-side composition in the SDK (`clientsdk/sajhaclient/mcp_client.py`): chains `add_step()` calls with the same `$.` / `$input.` mapping and tracks confidence and entropy, without a server-side composite. |
| **TransportCoalgebra** | The SDK's abstract transport interface, `step(method, params) → (result, new_state)`, implemented by `HTTPTransport`, `SSETransport` and `WSTransport`. |
| **Bisimilar** / **Bisimulation** | Behavioural equivalence: two transports are bisimilar if they give the same outputs for the same inputs, so they can be swapped. The SDK's `bisimilar()` tests it. |

---

## 8. Operations and infrastructure

| Term | Meaning |
|---|---|
| **Hot-reload** | Applying configuration changes without a restart. `HotReloadManager` (`sajha/core/hot_reload_manager.py`) watches tool configs, tool modules, prompts, users and API keys; changes reach clients through the change bus. |
| **Force reload** | An admin action that reloads every tool configuration immediately instead of waiting for the watcher. |
| **Storage backend** | The file-access abstraction (`sajha/core/storage.py`) all SAJHA IO goes through: `storage.backend` is `local` (default), `s3`, `azure` (Blob) or `gcs`. |
| **S3SyncManager** | The object-store equivalent of hot-reload: periodically lists watched prefixes in S3, Azure Blob or GCS, downloads changed files to the local cache and fires the reload callbacks. |
| **Tool cache** / **cache_ttl** | Per-tool result caching (`ToolCache`, `sajha/core/cache.py`): off by default, enabled per tool with `cache_ttl` (seconds) in its config. Entries are JSON files under `data/cache/<tool>/`, survive restarts and are evicted oldest-first above `cache.max_files`. |
| **Circuit breaker** | Per-provider failure protection (`sajha/core/circuit_breaker.py`): `CLOSED` (normal), `OPEN` after 5 consecutive failures (calls fail fast for 60 s), then `HALF_OPEN` (one probe). Stops a failing upstream API from cascading. |
| **ProviderHealth** | Combines circuit-breaker states with the tool-to-provider map (`sajha/core/tool_health.py`): each provider is healthy (closed), degraded (half-open) or down (open). |
| **ExecutionReplayStore** | Keeps the last executions per tool (default 20): arguments, result preview, duration, user, success, for replay during debugging and regression testing. |
| **WebhookManager** | Event notifications (`sajha/core/webhooks.py`): subscribers register callback URLs for events such as `tool.completed` or `circuit.opened`; delivery retries with exponential backoff in background threads. |
| **Async execution** | SAJHA's fire-and-forget background tool runs (`AsyncExecutor`, `/admin/async-tasks`): a bounded queue and worker pool that deliver results to a webhook, Kafka or a file. It is **not** the MCP tasks extension: it cannot park a job for client input or cancel a running job. |
| **AsyncTask** | One background execution: `queued`, `running`, `completed`/`failed`, `delivered`, with its tool, arguments, delivery target and result. |
| **DeliveryRouter** | Sends a finished async task's result to its destination: webhook (POST with retry), Kafka topic or file (atomic write). |
| **Backpressure** | Refusing new work when a queue is full; the async executor answers HTTP 503. |
| **Shell tools** / **ShellExecutor** | Sandboxed script execution (`sajha/core/shell_executor.py`), disabled by default: tier 1 Python sandbox, tier 2 allowlisted shell commands, tier 3 unrestricted shell (admin only). Every run is audit-logged. |
| **PythonSandbox** | Tier-1 execution: Python in a subprocess with restricted imports, environment, time and memory, from a temporary file deleted afterwards. |
| **SecurityValidator** | Pre-execution checks for shell tools: blocks dangerous Python imports and builtins (`os`, `subprocess`, `eval`, …) and non-allowlisted or chained shell commands. |
| **Monitoring** | Observing tool and user activity and health in the console's monitoring pages, refreshed periodically. |
| **Execution count** | The number of times a tool has been called since the server started. |
| **Average execution time** | The mean time a tool takes to complete. |
| **Error rate** | The percentage of a tool's executions that ended in an error. |
| **Latency** | The delay between a request and its response. |
| **Real-time updates** | Monitoring figures refreshed automatically while the page is open (periodic polling). |
| **User activity** | The tracked actions and sessions of users. |
| **Session** (*web*) | A signed-in period of interaction between a user and the console, backed by the session token. Not an MCP session. |
| **Active users** | Users currently signed in with a valid session. |
| **Request count** | The number of API requests a user has made. |
| **Last activity** | The time of a user's most recent action. |
| **Error** | An unexpected condition that prevents normal operation, shown on the console's error page. |
| **HTTP status code** | The numeric outcome of an HTTP request, e.g. 200 OK, 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Internal Server Error. |
| **Exception** | A runtime error raised in application code. |

---

## 9. AI integration

| Term | Meaning |
|---|---|
| **LLM gateway** | The multi-provider inference layer (`sajha/ai/`): Anthropic, OpenAI, AWS Bedrock, Together.ai, Ollama and Azure OpenAI through their official SDKs, with providers and models managed in the database and model resolution explicit, then user preference, then system default. |
| **Semantic tool search** | Natural-language tool discovery (`sajha/ai/tool_resolver.py`, `POST /api/ai/resolve-tool`): ranks tools by a query over their name, description, parameters, tags and literature. The embedder is set by `ai.tool_search.embedder`. |
| **bm25** (*embedder*) | The default tool-search ranker: a dependency-free lexical BM25 index (`sajha/ai/lexical.py`) with IDF weighting, needing no model and no network. |
| **gateway** (*embedder*) | Tool-search mode that embeds tool text and queries through the LLM gateway's embedding provider and ranks by cosine similarity; the vector index can be persisted via storage. |
| **Embedding** | A vector of numbers representing a text's meaning, so similar texts have nearby vectors. |

---

## 10. User interface

| Term | Meaning |
|---|---|
| **Theme** | One of four colour schemes over one design, shared with MAYA: **Crimson** (the default, stored as `light`), **Dark**, **Blue** and **Green**. Chosen from the palette menu and stored per browser (`sajha.theme`); applied as `data-theme` on `<html>`. With no choice stored the page follows the system light/dark preference. |
| **Design tokens** | The `--sajha-*` CSS custom properties in `static/css/tokens.css`, the only place colours are defined; `style.css` maps its `--t-*` roles onto them. |
| **Page glossary** | The collapsible list of terms at the foot of a console page, linking to this full glossary. |
| **JSON editor** | The console's visual editor for JSON configuration data. |
| **User configuration** | The settings and preferences of a user account, viewable and editable as JSON. |
| **Copy** | Copying rendered output to the clipboard for use elsewhere. |
| **curl** | A command-line tool for making HTTP requests, used in the console's example calls. |
| **Created at** | The timestamp when an item such as an API key was generated. |

---

## 11. Data sources and domain

| Term | Meaning |
|---|---|
| **FMP** (*Financial Modeling Prep*) | A market and fundamentals data API. `FMPGenericTool` maps tool names onto FMP endpoints, so a new FMP tool needs only a JSON config. |
| **OpenBB** | An open-source financial data platform. `OpenBBGenericTool` maps tool names onto OpenBB SDK commands. |
| **FRED** (*Federal Reserve Economic Data*) | The St. Louis Fed's economic time-series database, served by the FRED tools including `FREDCustomSeriesTool`. |
| **OLAP** (*Online Analytical Processing*) | Multi-dimensional analysis (pivots, time series, cohorts, statistics); the OLAP creator builds such tools over SAJHA's data. |
| **Power BI** | Microsoft's business intelligence service. The Power BI creator builds tools that query reports and refresh datasets. |
| **DAX** (*Data Analysis Expressions*) | Power BI's query and formula language; the Power BI DAX creator builds tools that run DAX queries against datasets. |
| **LiveLink** | OpenText Content Server (formerly Livelink), an enterprise content management system; the LiveLink creator builds document search, browse and retrieval tools. |
| **SharePoint** | Microsoft's document and list platform in Microsoft 365; the SharePoint creator builds document, list and search tools over it. |
