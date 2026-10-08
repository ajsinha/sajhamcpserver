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
[AI](#9-ai-integration) · [User interface](#10-user-interface) · [Data sources](#11-data-sources-and-domain) ·
[SAJHA Net](#12-sajha-net)

---

## 1. SAJHA and the platform

| Term | Meaning |
|---|---|
| **SAJHA** (*साझा*) | Hindi/Urdu for "shared", "common" or "collaborative". The name is the idea: one governed catalog of tools that every MCP client and agent shares, composed on demand. |
| **SAJHA MCP Server** | A Python MCP server that exposes a large catalogue of data and analytics tools, prompts and resources to AI clients, with a web console for administration, monitoring and tool creation (MCP Studio). It speaks both MCP eras (see **dual-era**). |
| **SajhaMCPServerWebApp** | The main application class in `sajha/app.py`. Creates the FastAPI app, initialises every subsystem and manages the lifecycle. |
| **FastAPI** | The ASGI web framework SAJHA runs on (it replaced Flask). Provides async request handling, dependency injection and generated OpenAPI docs. |
| **Uvicorn** | The ASGI server that runs the FastAPI application. |
| **Lifespan** | The FastAPI async context manager (`_lifespan()` in `app.py`) that runs initialisation on startup and cleanup on shutdown. |
| **Route module** | An `APIRouter` in `sajha/routes/` (MCP, OAuth, admin, studio, API, A2A, WebSocket, …) registered with the app at startup. |
| **application.yml** | The single configuration file, `config/application.yml`. Drives paths, database, logging, storage, MCP, OAuth, AI and plugin settings. Supports `${ENV_VAR:default}` substitution, and keys read through `sajha/core/config.py` can be overridden with a `SAJHA_`-prefixed environment variable (e.g. `SAJHA_MCP_AUTH_MODE`); the Configuration Reference says which subsystems read differently. |
| **Settings** | A dataclass in `sajha/core/config.py` exposing typed configuration values derived from `application.yml`. |
| **PropertiesConfigurator** | A singleton (`sajha/core/properties_configurator.py`) that resolves `${variable}` references in tool JSON configs from the flattened YAML configuration. |
| **DAO** (*Data Access Object*) | The classes in `sajha/db/dao/` that encapsulate database queries (users, roles, permissions, API keys, executions, errors, sessions). |
| **DeclarativeBase** | SQLAlchemy's base class for the ORM models, in `sajha/db/base.py`. |
| **url_for** | A custom template function in `app.py` that maps endpoint names to URL paths, giving Flask-style URL resolution in the Jinja2 templates. |
| **Jinja2** | The template engine behind the web console pages and behind prompt templates, supporting variable substitution, conditions and loops. |
| **Client SDK** | The Python package in `clientsdk/` (`sajhaclient`). `SajhaMCPClient` wraps the official MCP SDK and by default (`mode="auto"`) probes `server/discover` and adopts 2026-07-28; it also has REST, A2A and transport-level clients. |
| **sajha CLI** | The `sajha` command (`clientsdk/sajhaclient/cli/`): login and profiles, tools and prompts over MCP, a streamed `ask`, Studio deploy, federation, shell completion, and `serve --stdio`. Exit codes say what failed. |
| **CLI profile** | A named server URL and its stored credentials for the `sajha` command (`sajha profile add`, `use`, `list`, `remove`), kept in the CLI's `config.json`; chosen by `--profile` or `SAJHA_PROFILE`. |
| **Plugin** | An extension package in `config/plugins/` (setting `plugins.dir`) with a `plugin.json` manifest, containing tool configs and optionally Python classes. Flow: `discover()`, `validate()` (checksum), `load_plugin()` (install dependencies, register tools). |
| **Plugin manifest** | A plugin's `plugin.json`: its name, version, the tools it provides, an optional `sha256:` checksum over its files (a mismatch fails loading) and informational fields; read by `discover()`, checked by `validate()`. |
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
| **Prompt** | A reusable message template with named arguments that SAJHA keeps in `config/prompts/` and serves over MCP: listed by `prompts/list`, rendered by `prompts/get`. |
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
| **Cancellation** | Stopping an in-flight request. Legacy and WebSocket clients, and stdio clients of either era, send `notifications/cancelled`; on the modern HTTP path the client simply closes the connection. |
| **Elicitation** | A server asking the user, through the client, for input: **form** mode (a JSON Schema form) or **URL** mode (send the user to a page). It is a client capability. Legacy servers send `elicitation/create` as a server-to-client request; the modern path asks through MRTR. |
| **Sampling** | A server asking the client's LLM for a completion (`sampling/createMessage`), optionally with tools. A client capability, used on the legacy path by server-to-client request and on the modern path through MRTR. |
| **Roots** | The filesystem or URI roots a client exposes (`roots/list`). A client capability, requested through MRTR on the modern path. |
| **list_changed** | Notifications (`notifications/tools/list_changed`, `prompts/…`, `resources/…`) telling a client that a list has changed and should be fetched again. SAJHA sends them on `subscriptions/listen` streams, the legacy HTTP+SSE stream and WebSocket, fed by the change bus; legacy Streamable HTTP sessions advertise `listChanged: false`. |
| **resources/subscribe** | The legacy per-URI subscription method (accepted, returns `{}`). Removed in 2026-07-28 in favour of `resourceSubscriptions` on `subscriptions/listen`. |
| **MCPHandler** | The core legacy-era handler (`sajha/core/mcp_handler.py`) that routes every MCP JSON-RPC method. It is created with `SessionToolAccess` (`sajha/auth/access.py`), so every transport lists and runs only the tools the caller may use. Shared by the Streamable HTTP, HTTP+SSE and WebSocket transports, and reused by the modern path for business logic. |
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
| **Tasks extension** (*io.modelcontextprotocol/tasks*) | The 2026-07-28 extension (SEP-2663) for long-running tool calls: a task-capable `tools/call` returns `resultType: "task"` with a `taskId`, and the client uses `tasks/get` (status, inlined result), `tasks/update` (answer input) and `tasks/cancel`. Advertised under `capabilities.extensions` when `mcp.tasks.enabled`; records are scoped per user and kept in the task record store, which is process memory by default and the database for a **Durable task** (`sajha/core/mcp_tasks.py`). |
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
| **Mcp-Session-Id** | The legacy session header: set on the `initialize` response and sent by the client on every later request. An unknown id gets `404` (re-initialize); `DELETE /mcp` ends the session. Sessions live in the **State store** (process memory by default; `sajha/core/mcp_sessions.py`). Ignored on the modern path. |
| **HTTP+SSE** (*legacy*) | The 2024-11-05 transport: `GET /mcp/sse` opens an event stream (an `endpoint` event, then messages) and the client POSTs to `/mcp/message`. Legacy era only. |
| **SSE** (*Server-Sent Events*) | A one-way HTTP streaming format (`text/event-stream`). In MCP it carries streamed responses, notifications and, on the legacy path, server-to-client requests. |
| **WebSocket extension** | SAJHA's full-duplex transport at `/mcp/ws`, outside the MCP spec and legacy era only. Authenticates with `?token=` (SAJHA JWT) or `?api_key=`; accepts JSON-RPC batches; receives change-bus `list_changed` pushes. Advertised under `experimental.sajha.websocket`. |
| **stdio transport** | MCP over a subprocess's stdin and stdout, newline-delimited JSON-RPC, logs on stderr only (`sajha/cli/stdio.py`; `sajha serve --stdio` or `run_server.py --stdio`). Serves both eras for desktop clients; one caller per process, set by `--user` or `--api-key`, anonymous otherwise. |
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
| **API key** | A long-lived credential for programs, prefixed `sja_`, sent in the `X-API-Key` header (or `?api_key=` on WebSocket). Stored as a SHA-256 hash; carries an owner, a tool access mode and an optional expiry. A key with an owner signs in as that user; one without keeps the service identity `apikey:<name>` (role `api_consumer`). Works in every `mcp.auth.mode` and is not scope-checked. |
| **Key owner** | The user an API key belongs to (`api_keys.owner_id`). The key signs in as the owner, with the owner's roles; its own tool access mode can only narrow that. Older keys without an owner keep `api_consumer` until an administrator assigns one. |
| **Default API key** | The one API key every user has, created with the account (and at start-up for accounts without one). It can be rotated or disabled, never revoked or deleted; its value is kept encrypted with the token vault's key so the server can act for the user. |
| **Persistent API key** | A key an administrator marks persistent: its hashed record is also kept in the file at `config.apikeys.path` (default `config/apikeys.json`, git-ignored, mode 0600), so it works when the database is lost or down. The database still wins for a key it knows. |
| **X-API-Key header** | The HTTP header that carries a SAJHA API key, e.g. `curl -H "X-API-Key: sja_…"`. |
| **Tool access** | Which tools a caller may run (`sajha/auth/access.py`), enforced on the REST API, every MCP transport, A2A and async execution, and which it sees in MCP `tools/list` (the REST catalog routes are not filtered): users by their roles' tool permissions (`execute` to run, `read` to see), API keys by their owner's permissions capped by the key's tool access mode (a key without an owner by its mode alone), anonymous callers by `mcp.anonymous.*`. Disallowed calls get 403 (REST), `-32002` (2025-11-25) or `-32010` (2026-07-28). |
| **Anonymous access** | MCP or A2A calls with no credentials, possible while `mcp.auth.mode` is `off` or `optional` and `mcp.anonymous.enabled` is true. Anonymous callers see and run only the tools matched by `mcp.anonymous.tools` (default: none) plus the tool permissions of `mcp.anonymous.role`. |
| **Tool access mode** | How an API key's tool permissions are decided: `all`, `allowlist`, `denylist` or `regex`. |
| **Allowlist** | API key tool access mode where only the selected tools are permitted. |
| **Denylist** | API key tool access mode where every tool except the selected ones is permitted. |
| **Regex pattern** | API key tool access mode where tool names matching a regular expression are permitted. |
| **Expiration** | The date after which an API key stops working. |
| **Rate limiting** | Capping requests per period. API keys can carry per-minute and per-hour limits (`rate_limit_rpm`, `rate_limit_rph`). |
| **Key rotation** | Giving an API key a new secret value (same key, owner and access); the old value stops working at once and the new one is shown once. |
| **Key revocation** | Ending an API key for good: it is disabled and `revoked_at` / `revoked_by` are recorded, so the record survives. A revoked key cannot be enabled again; a default key cannot be revoked. |
| **Token version** | A counter on each user (`users.token_version`) copied into every SAJHA JWT and built-in OAuth token as the claim `tv`. Raising it ends every session of the user at once. |
| **Sign out everywhere** | Ending every console session and OAuth token of a user by raising their token version; done by the user, by a password change or reset, or by an administrator. API keys are not affected. |
| **API key deletion** | Permanently removing an API key; every application using it loses access immediately. Delete unused keys to minimise the attack surface. |
| **RBAC** (*Role-Based Access Control*) | Authorization where permissions are attached to roles and roles to users (`user_roles`, `role_permissions` tables). |
| **Role** | A named set of permissions. Seeded roles: `admin` (full access), `user` (standard tool access), `viewer` (read-only), `developer` (every MCP Studio creator, `studio:*`), `llm_author` (the LLM tool creator only, `studio:llm`). `api_consumer` is the least-privilege identity given to unmatched external OAuth users. |
| **User ID** | The unique login name of a user account; cannot be changed after creation. External OAuth identities are matched to it. |
| **Account status** | Whether a user account is enabled or disabled for login. |
| **Account lockout** | After `auth.login.max_failed_attempts` consecutive failed sign-ins (default 5) the account is locked for `auth.login.lockout_minutes` (default 15); a client IP with too many failed sign-ins gets 429. Applies to the web form, `POST /api/auth/login` and the OAuth consent sign-in. |
| **Must change password** | The per-user flag `users.must_change_password`, set for the seed admin, passwords an admin sets and well-known passwords. A banner links to `/account/password` until the password is changed. |
| **Server secrets file** | `<data.dir>/secrets/server_secrets.json` (mode 0600, git-ignored): the JWT secret and session secret SAJHA generates once when none is configured. Publicly known placeholder secrets are refused at start-up. |
| **Password hash** | The stored form of a password: bcrypt (cost 12), used directly rather than through passlib. Passwords are never stored in plain text. |
| **AuthContext** | The dataclass the auth dependencies return to routes: `user_id`, `user_name`, `roles`, `is_admin`, auth type. |
| **AuthManager** | The authentication orchestrator (`sajha/auth/__init__.py`) that resolves cookies, bearer tokens, API keys and OAuth tokens into an `AuthContext`. |
| **Consent page** | The built-in AS's approval page (`/oauth/authorize`): CSRF-protected, frame-blocked, sign-in rate-limited, never redirecting to an unregistered URI. |
| **AuditLogger** | Structured security event logging (`sajha/core/audit.py`) to the `audit_log` table: logins, logouts, user and API key changes, tool executions, config and permission changes, account locks. |
| **Audit log** | The record of user and security actions kept for security and compliance review. |
| **SSRF** (*Server-Side Request Forgery*) | Tricking a server into fetching internal URLs. CIMD fetches, async webhook deliveries, federation upstreams and API Import (specs, `$ref` documents and every imported call) are guarded against it (vetted, pinned public IPs; no redirects). |
| **Sandbox** | Where SAJHA runs code it did not ship (Studio Python code and script tools, the admin shell): a separate process per call with no server environment, a temp work dir, limits, and per backend no access to the server's files, processes or network (`sajha/sandbox/`). |
| **Sandbox backend** | How a sandbox is launched: `subprocess` (default; on Linux with namespaces, Landlock and seccomp), `bwrap`, `nsjail` or `docker`. Chosen by `sandbox.default_backend` or a tool's `sandbox.backend`; `GET /api/sandbox/status` reports what each enforces on the host. |
| **Sandbox policy** | A tool's `sandbox` block (network, allowed hosts, time, memory, processes, output, packages, secrets, env) over the administrator's `sandbox.defaults`, capped by `sandbox.max`. |
| **Connected account** | A user's link to their own account at a third-party service (GitHub, Slack, Google, Microsoft 365, Atlassian, Notion, or any configured OAuth 2.0 service), made once on `/account/connections`. Tools that declare `"auth": {"connected_account": "<provider>"}` then call that service as the user (`sajha/accounts/`). |
| **Connected-account provider** | A third-party service users can link: a built-in template (endpoints, default scopes, PKCE, `api_hosts`) switched on with a client id and a `client_secret_ref` under `accounts.providers.<id>`, or a custom OAuth 2.0 service described there in full. |
| **Token vault** | The `connected_accounts` table (in the schema files under `db/scripts/`): one row per user and provider holding the tokens as AES-256-GCM ciphertext bound to that user and provider, beside clear metadata (account, scopes, expiry, status). Administrators see the metadata, never a token. |
| **Vault key** | The data key that encrypts the token vault: `accounts.vault.key` (env `SAJHA_ACCOUNTS_VAULT_KEY`), else one generated into the server secrets file, or one from a key-provider hook (KMS). Old keys stay readable from `accounts.vault.previous_keys` until rows are re-encrypted. |
| **URLElicitationRequiredError** | The MCP 2025-11-25 JSON-RPC error `-32042` whose `data.elicitations` asks the client to send the user to a URL. SAJHA returns it when a connected-accounts tool runs for a caller with no usable link and the client declared URL-mode elicitation; on 2026-07-28 the same request travels as an MRTR input request. |
| **Token passthrough** | A federated upstream with `auth.type: connected_account` receives the calling user's own token for that provider on every tool call (a short-lived connection per call), so the upstream acts as that user; discovery uses a separate service credential or none. |
| **Policy engine** | The declarative rules SAJHA evaluates before every tool call on every path, at `BaseMCPTool.execute_with_tracking` (`sajha/policy/`): allow, deny, require approval, argument constraints, rate limits, quotas, output redaction and injection screening. Rules live in `config/policies/` and reload on change; the shipped policy has no rules. |
| **Policy rule** | One entry in a policy file: a `match` (tool globs, groups, annotations, callers, sources, time window, argument conditions), an optional `effect` and obligations (`constraints`, `rate_limit`, `quota`, `redact`, `screen_output`). |
| **Policy effect** | What a rule decides about access: `allow`, `deny` (with a reason) or `require_approval`. Effects of all matching rules combine deny-overrides; with `policy.default_effect: deny` a call needs an explicit `allow`. |
| **Argument constraint** | A condition a call's arguments must meet under a policy rule (`enum`, `min`/`max`, `pattern`, `not_pattern`, `max_length`, `type`, `required`); a violation denies the call, naming the argument. |
| **Quota** | A cap on calls per UTC calendar period (hour, day, week, month) under a policy rule, counted in the state store per tool, user, API key or caller. |
| **Output redaction** | A policy obligation that replaces or masks personal data in a tool result before the caller sees it: emails, phone numbers, card numbers that pass the Luhn check, national IDs and custom regexes. |
| **Output screening** | A policy obligation that looks for prompt-injection markers in a tool result: `flag` (audit only), `strip` (replace them) or `block` (withhold the result). |
| **Require approval** | The policy effect that holds a call for a human: the caller confirms it (MRTR or Ask SAJHA, `approver: caller`) or an administrator approves it on the Approvals page (`approver: admin`). |
| **Approval grant** | What approving a held call creates: the same caller making the same call (same fingerprint) within `policy.approvals.grant_ttl_seconds` runs it, once. |
| **Call fingerprint** | SHA-256 of a tool name and its canonical arguments; ties an approval to exactly the call that was approved. |
| **Policy test bench** | The form on the Policies page that evaluates a described call (tool, arguments, caller, source, time) and shows the decision, matching rules and obligations without running the tool. |
| **Audit hash chain** | The tamper-evident form of the audit log: each record carries the SHA-256 hash of the one before, so editing, removing or reordering any record breaks every hash after it. One chain per SAJHA process, in the `audit_chain` table. |
| **Audit anchor** | A checkpoint of an audit hash chain: its head hash and sequence number signed (RS256) with the server's OAuth signing key, stored in `audit_anchors` and in the chain, so a rewritten chain cannot reproduce it. |
| **Tool-call audit record** (*tool.call*) | The audit-chain record of one tool call: caller, API key, tool, outcome, duration, trace id, source surface and a SHA-256 of the arguments (not their values). Failures, denials and destructive tools are always recorded; successes can be filtered and sampled (`audit.tool_calls`). |
| **Snapshot** | A periodic JSON record of an instance's users (no password hashes), roles, API key records (hashes only for persistent keys) and local tools, chained to the one before by SHA-256 and signed with the server key (`snapshots.*`; `python -m sajha.snapshots verify`). |
| **Upgrade SQL** | The DDL that brings an existing database up to its dialect's schema file (`CREATE TABLE`, `ALTER TABLE ... ADD COLUMN`, `CREATE INDEX`), printed by the start-up schema check and `python -m sajha.db upgrade-sql` for an operator to run; SAJHA never runs it. |
| **SIEM export** | Streaming audit records to a security information and event management system: syslog (RFC 5424 over TCP or TLS), HTTP (Splunk HEC, Datadog, generic) or a rotated JSON Lines file (`audit.export.sinks`). |
| **CEF** (*Common Event Format*) | ArcSight's one-line event format: a `CEF:0` header of vendor, product, version, event id, name and severity, then key=value extensions; one of the SIEM export formats. |
| **HTTP Message Signature** | A signature over chosen parts of an HTTP request or response (method, path, headers, a body digest, a creation time and nonce), defined by RFC 9421. SAJHA Net signs every request and response between participants this way (label `sajhanet`, Ed25519 or ECDSA P-256) instead of relying on mutual TLS. |
| **Content-Digest** | An HTTP header carrying a hash of the message body (RFC 9530), for example `sha-256=:...:`; covering it in an HTTP Message Signature makes the body tamper-evident. |
| **JCS** (*JSON Canonicalization Scheme*) | RFC 8785: one exact byte form of a JSON value (sorted member names, fixed number and string formatting), so a signature over JSON verifies however the JSON was re-serialized on the way. |
| **OCSF** (*Open Cybersecurity Schema Framework*) | A vendor-neutral JSON schema for security events; SAJHA's `ocsf` export format maps audit records to its API Activity, Authentication and Account Change classes. |
| **OIDC** (*OpenID Connect*) | An identity layer on OAuth 2.0: the provider signs an ID token that says who signed in. SAJHA is an OIDC client of an identity provider for console single sign-on; it is not an OIDC provider. |
| **ID token** | The signed JWT an OpenID Connect provider returns at the token endpoint, naming the person (`sub` and other claims) for one client (`aud`) and one sign-in (`nonce`). SAJHA checks its signature against the provider's JWKS before trusting any claim. |
| **Console single sign-on** (*SSO*) | Signing in to the console with an organisation's OpenID Connect identity provider (authorization code with PKCE) instead of a SAJHA password; off unless `auth.sso.enabled`, and password sign-in keeps working. Instances of a net that trust the same provider share one sign-in, each mapping the person to its own user. |
| **Claim-to-role mapping** | `auth.sso.role_map`: values of the ID token claim named by `auth.sso.roles_claim` (groups, roles) turned into SAJHA roles at sign-in, for a created user and, with `auth.sso.sync_roles`, at every sign-in. |
| **CSP** (*Content Security Policy*) | A response header that tells the browser which scripts, styles, frames and connections a page may use. SAJHA's console policy allows scripts only from its own origin or carrying the response's nonce, and no inline event handlers. |
| **CSP nonce** | A random value created for each response, named in its `Content-Security-Policy` and carried by each inline script the page means to run (`nonce="{{ csp_nonce() }}"`); a script without it, such as an injected one, does not run. |
| **data-on handler** | A console event handler written as a `data-onclick` (or `data-onchange`, `data-onsubmit`, ...) attribute instead of `onclick`: `csp-actions.js` runs it as calls to the page's own functions with literal arguments, without evaluating script, so the CSP can refuse inline handlers. |
| **CSRF** (*Cross-Site Request Forgery*) | Another site making a signed-in browser send a request that changes something. SAJHA refuses any cookie-authenticated `POST`, `PUT`, `PATCH` or `DELETE` whose `Origin` (or `Referer`) is another site, on top of SameSite cookies and page CSRF tokens. |
| **Session rotation** | Signing out the session a browser already held whenever someone signs in on it, so a planted or left-over session token never outlives a sign-in (session fixation). |
| **HSTS** (*HTTP Strict Transport Security*) | The `Strict-Transport-Security` header: the browser uses only https for the site for `max-age` seconds. SAJHA sends it on https responses (`security.hsts.*`). |
| **Allowed hosts** | `security.allowed_hosts`: the `Host` header names SAJHA answers to (others get 400), against DNS rebinding and host-header poisoning; empty allows any, and loopback names always pass. |

---

## 6. Tools, prompts and resources

| Term | Meaning |
|---|---|
| **BaseMCPTool** | The abstract base class (`sajha/tools/base_mcp_tool.py`) every tool extends, implementing `get_input_schema()`, `get_output_schema()` and `execute()`. |
| **Tool configuration** | A JSON file in `config/tools/` defining a tool's name, implementation class, description, schemas and metadata (`annotations`, `cache_ttl`, `execution.taskSupport`, `_meta.ui`, literature). |
| **JSON Configuration** | The underlying JSON document that defines a tool or prompt, editable in the console. |
| **JSON Schema** | A vocabulary for describing and validating the structure of JSON documents; SAJHA uses the 2020-12 dialect for tool schemas. |
| **Input Schema** | The console's label for a tool's **inputSchema**. |
| **Output Schema** | The console's label for a tool's **outputSchema**. |
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
| **Tool versioning** | Several versions of one tool behind its one MCP name, declared in `config/tool_versions/<tool>.yaml` and routed per call (`sajha/quality/versions.py`); the result's `_meta["io.sajha/tool-version"]` names the version that ran. See **Tool version**, **Canary**, **Version pin**, **Automatic rollback**, **Sunset date**. |
| **Literature** | Contextual documentation attached to a tool to help an AI understand when and how to use it; also indexed by semantic tool search. |
| **Catalog resources** | `sajha://tools/catalog` and `sajha://prompts/catalog`: resources listing the tools and prompts, updated (with `resources/updated`) whenever they change. |
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
| **Federation** | SAJHA fronting other MCP servers and re-exposing their tools (and optionally prompts and resources) as registry tools under its own access control, audit, cache, circuit breakers and rate limits (`sajha/federation/`); off by default (`federation.enabled`). |
| **Upstream** | An MCP server SAJHA federates: an id, a transport (Streamable HTTP, legacy SSE or stdio), credentials by secret reference, and the approval state of everything it offers. |
| **Namespaced tool** | A federated tool's name in SAJHA, `<prefix>__<upstream tool name>` (for example `weather__get_forecast`), so upstream names never collide with each other or with native tools. |
| **Approval** (*federation*) | The review gate for federated items (`federation.require_approval`, on by default): a discovered tool, prompt or resource is `pending` until an administrator approves it; one whose definition later changes goes back to `changed` and is hidden again. |
| **Tool poisoning** | Instructions hidden in a tool's name, description or schema to steer the LLM that reads them. SAJHA strips control characters, caps and screens federated text, and flagged items always wait for a person's approval. |
| **Federation store** | `FederationStore` (`sajha/federation/store.py`): one JSON document at `federation.state_path` holding the upstreams added on the admin page and every approval, read and written through the storage backend. |

---

## 7. Studio and composition

| Term | Meaning |
|---|---|
| **MCP Studio** | The visual tool-creation console at `/studio`, open to administrators and to roles with a Studio permission (the seeded `developer` role has `studio:*`). Generates a tool's Python class and JSON config without hand-coding. |
| **Studio permission** | A role permission with resource type `studio` that opens one creator: `studio:<creator>` (`python`, `rest`, `api_import`, `dbquery`, `script`, `powerbi`, `powerbidax`, `livelink`, `sharepoint`, `olap`, `composite`, `describe`, `llm`) or `studio:*` for all of them. The planner editor needs the admin role. |
| **Tool creator** (*ownership*) | The user a Studio-made tool records as its maker (`metadata.created_by` in the tool config; the row's `created_by` for a composite; the import record for API Import). A non-admin may change or delete only what records them. |
| **Creator** | One of Studio's tool builders: Python Code, REST Service, Import an API, DB Query, Script, Power BI Report, Power BI DAX, LiveLink, SharePoint, OLAP, Composite, Describe a tool and LLM tool. |
| **LLM tool creator** | The Studio page (`/studio/llm`, permission `studio:llm`) that writes an LLM tool's config from a form: mode, model alias, instructions, allowed tools with live matching, limits within the ceilings, memory, planner, sampling; it checks the config with the loader's own rules, runs it once on the mock model and deploys or edits the file. |
| **Planner editor** | The Studio page (`/studio/planners`, administrators only) for planner files: the registry's load problems, the file with schema and P-rule findings, a graph of stages and transitions, a dry run, and saving a new version (the replaced one kept as `name@version`). |
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
| **API Import** | The Studio page (`/studio/api-import`, Studio access) that turns an OpenAPI 3.x or Swagger 2.0 description, or a GraphQL schema read by introspection, into one tool per selected operation. Every imported tool runs on one generic executor configured by its JSON config; no code is generated. |
| **OpenAPI** | A machine-readable description of an HTTP API (servers, paths, operations, parameters, schemas, security schemes), version 3.x. API Import reads it. |
| **Swagger 2.0** | The predecessor of OpenAPI 3; API Import converts a Swagger 2.0 document to the 3.0 shape before reading it. |
| **GraphQL introspection** | The standard query a GraphQL server answers with its own schema (types, queries, mutations); API Import builds one tool per query and mutation from it. |
| **$ref** | A JSON reference from one part of an API description to another, or into another document. API Import inlines every one (remote documents through the SSRF guard) so each tool schema stands alone. |
| **Import record** | The JSON document `config/api_imports/<api_id>.json` that remembers an import's source, server, credential references and a fingerprint per deployed operation, so importing again shows what was added, changed or removed. |
| **Secret reference** | A pointer to a secret instead of the secret: `env:NAME`, `file:/path` or `db:llm_providers/<type>`. Resolved when used, never written to a config or logged. Used by LLM providers, federation upstreams, API Import credentials and data connectors. |
| **Describe a tool** | The Studio page (`/studio/describe`, Studio access) and the `sajha studio describe` command: a plain-language description goes to the model behind the `toolsmith` alias, which proposes a tool; the requester reads the generated files, runs the tests and approves the deploy. |
| **Tool proposal** | What Describe a tool's model returns: a kind (`python`, `rest`, `dbquery`, `composite`, `openapi` or `llm`), name, description, input and output schemas, implementation and test cases. SAJHA checks every field as untrusted input. |
| **Draft** (*Describe a tool*) | A tool proposal kept in the state store with its generated files, policy preview and test results, until `studio.describe.draft_ttl_seconds` passes or it is deployed. |
| **Proposal hash** | The SHA-256 of a checked tool proposal. A deploy names the hash the administrator reviewed; it must be the draft's current hash, and the tests must have run on it. |
| **Live test** | A Describe a tool test case that needs the network or a real service; it runs only when the administrator asks. Offline Python cases run in the sandbox with no network at all. |
| **Test fixture** | A canned HTTP reply (status, and JSON or text) that a generated REST tool's test case answers from, so the tool is tested without calling its endpoint. |
| **toolsmith** (*model alias*) | The gateway alias Describe a tool asks (`studio.describe.model`); out of the box it maps to `mock/mock-toolsmith`. Point it at a real model with `SAJHA_AI_ALIASES_TOOLSMITH`. |
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
| **Master tool** / **Master output key** | The tool a composite runs first, with the composite's own arguments; its result is stored under the master output key (default `master`) for the steps to read. |
| **Record path** | In a parent-child composite, the dot path (`rows`, `result.data`) to the array in the master's output; the child runs once per record. |
| **Kleisli composition** | From category theory: composing functions that return wrapped (monadic) values. In SAJHA every tool is a Kleisli arrow `Dict → StepResult`, composed with `bind()`: errors short-circuit, traces accumulate, confidence compounds. |
| **StepResult** | The monadic result envelope (`sajha/core/composition.py`): value, error, trace, duration, confidence, step name. `pure()` lifts a value (confidence 1.0), `fail()` an error (0.0), `bind()` chains. |
| **PipelineResult** | The final output of a composite pipeline: merged tool outputs plus a `_composition` block (confidence, entropy bits, trace, guard result, steps executed). |
| **ParamLens** | A lens (view/set pair) that projects parent output into child parameters: `$.field` (from the current record), `$input.field` (from the original input) or a literal; `set()` merges the child result back. |
| **EntropyGuard** | Tracks per-step confidence through a pipeline and its cumulative Shannon entropy; refuses a pipeline above `max_entropy_bits`. Sequential steps multiply confidence, parallel steps take the minimum. |
| **Shannon entropy** | An information-theoretic measure of uncertainty in bits, `H = -p·log2(p) - (1-p)·log2(1-p)`: 0 bits for a certain result, 1 bit for a 50/50 one. |
| **Confidence score** | A 0.0–1.0 estimate of a tool's reliability: 1.0 deterministic (calculators), about 0.95 a stable API (FRED), about 0.80 a web crawl. Composites compound it. |
| **Weakest-link model** | The confidence rule for parallel steps: `min` of the steps' scores, since the composite is only as reliable as its least reliable independent part. |
| **Workflow** | A saved DAG of steps (tool, composite, Ask SAJHA, condition, foreach, wait, approval) with parameter mapping, retries and timeouts, run by hand or by triggers and recorded run by run (`sajha/workflows/`, the Workflows page). |
| **Workflow step** | One node of a workflow: an `id`, a `kind`, its `depends_on` (plus every `$steps.<id>` it reads), and per-kind fields; it runs when its dependencies are done and its `join` rule and `when` condition allow. |
| **DAG** (*Directed Acyclic Graph*) | Nodes joined by one-way edges with no cycles; a workflow's steps and dependencies form one, so every step has a run order. |
| **Join rule** | When a workflow step with several dependencies runs: `all_success` (default), `any_success` (after branches) or `all_done`. A step whose rule fails is skipped. |
| **Foreach step** | A workflow step that runs one tool, composite or Ask SAJHA call per element of a list (`$item`, `$index`), capped by `max_items`, optionally in parallel. |
| **Workflow trigger** | What starts a workflow run besides a manual run: a cron schedule, a signed webhook, a file arriving on the storage backend, or a change-bus event. |
| **Cron schedule** | A five-field time pattern (minute hour day month weekday) evaluated in an IANA timezone; each due slot is claimed in the state store so one worker fires it. |
| **Signed webhook** | An inbound HTTP trigger authenticated by `X-Sajha-Signature: sha256=HMAC(secret, timestamp.body)` and `X-Sajha-Timestamp`; old timestamps and repeated signatures are refused (replay protection). |
| **HMAC** (*Hash-based Message Authentication Code*) | A keyed hash (here SHA-256) that proves a message came from someone holding the shared secret and was not altered. |
| **Run as** | The identity a workflow's steps run under: its owner, re-read from the database at each run, so the owner's current roles, tool access and policies apply. |
| **Workflow run** | One execution of a workflow, stored durably with its status, trigger, input, output and a record per step (inputs and outputs truncated, durations, attempts, errors). |
| **Idempotency key** | A caller-chosen key that makes a request safe to repeat: a second workflow run with the same key returns the first. Steps also get one per call, and a step marked idempotent is the only kind re-run after a crash. |
| **Run resume** | A worker taking over a run whose worker stopped (its heartbeat went stale): finished steps keep their outputs, interrupted idempotent steps run again, others are marked failed. |
| **Re-run from a step** | A new run of the same definition and input that reuses the outputs of the steps before the chosen (default: first failed) step and runs it and everything after it. |
| **Published workflow** | A workflow registered as an ordinary MCP tool (`publish.enabled`, administrators only): calling it starts a run and returns its output; it is listed, governed and federated like any tool. |
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
| **Per-user cache key** (*cache_per_user*) | A tool cache setting that adds the caller's user id to the cache key, so one user's cached result is never served to another; the default for federated tools. |
| **Circuit breaker** | Per-provider failure protection (`sajha/core/circuit_breaker.py`): `CLOSED` (normal), `OPEN` after 5 consecutive failures (calls fail fast for 60 s), then `HALF_OPEN` (one probe). Stops a failing upstream API from cascading. |
| **ProviderHealth** | Combines circuit-breaker states with the tool-to-provider map (`sajha/core/tool_health.py`): each provider is healthy (closed), degraded (half-open) or down (open). |
| **ExecutionReplayStore** | Keeps the last executions per tool (default 20): arguments, result preview, duration, user, success, for replay during debugging and regression testing. |
| **WebhookManager** | Event notifications (`sajha/core/webhooks.py`): subscribers register callback URLs for events such as `tool.completed` or `circuit.opened`; delivery retries with exponential backoff in background threads. |
| **Async execution** | SAJHA's fire-and-forget background tool runs (`AsyncExecutor`, `/admin/async-tasks`): a bounded queue and worker pool that deliver results to a webhook, Kafka or a file. It is **not** the MCP tasks extension: it cannot park a job for client input or cancel a running job. |
| **AsyncTask** | One background execution: `queued`, `running`, `completed`/`failed`, `delivered`, with its tool, arguments, delivery target and result. |
| **DeliveryRouter** | Sends a finished async task's result to its destination: webhook (POST with retry), Kafka topic or file (atomic write). |
| **Backpressure** | Refusing new work when a queue is full; the async executor answers HTTP 503. |
| **State store** | Where SAJHA keeps state that every worker must see: OAuth codes and refresh tokens, MCP sessions, task records, rate-limit windows, LLM budgets, and the pub/sub channel for change notifications (`sajha/core/state/`). `state.backend` is `memory` (one process, the default), `redis` or `database`. |
| **Durable task** | An MCP 2026-07-28 task whose record is kept in the database (`state.tasks.durable`, on by default with a shared state backend): it survives a restart, any worker can read, cancel or resume it, and a task whose worker died is failed rather than re-run. |
| **Orphaned task** | A `working` task, or a queued or running async job, whose worker no longer heart-beats in the state store. It is reported `failed` when it is read. |
| **Worker ID** / **Heartbeat** | Each process's identity (`host:pid:random`) and, with a shared state backend, the `worker:<id>` key it refreshes every few seconds; a task whose worker has no heartbeat is orphaned. |
| **Lease** | A state-store key held by one worker at a time and renewed by its holder while it works (`lease_claim`, `lease_renew`, `lease_release`); a holder that stops renewing loses it after one TTL, so another worker can take over. |
| **Shell tools** / **ShellExecutor** | Admin Python and Bash execution (`sajha/core/shell_executor.py`), disabled by default: an import and command filter, then the **Sandbox**. Every run is audit-logged. |
| **PythonSandbox** | The admin shell's Python executor (`sajha/core/shell_executor.py`): `SecurityValidator` filters the code first, then it runs through the **Sandbox** backend like any other user code. |
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
| **Prometheus** | An open-source metrics system that scrapes HTTP endpoints for time series. SAJHA serves its metrics in the Prometheus text format on `/metrics` (`sajha/observability/metrics.py`), protected by `observability.metrics.auth`. |
| **OpenTelemetry** (*OTel*) | The vendor-neutral standard for traces, metrics and logs. SAJHA exports traces and metrics with it when `observability.otel.enabled` and the SDK is installed (`sajha/observability/tracing.py`). |
| **OTLP** (*OpenTelemetry Protocol*) | The wire protocol OpenTelemetry exporters use (`http/protobuf` or `grpc`) to send telemetry to a collector or backend. |
| **Span** | One timed operation in a trace, with a name, attributes and a parent. SAJHA nests HTTP, MCP, tool and LLM spans. |
| **traceparent** | The W3C Trace Context value naming a trace and its parent span. SAJHA continues it from the HTTP header and from an MCP request's `params._meta`, starts one when there is none, and sends it on its own outbound calls. |
| **Label cardinality** | The number of distinct label sets a metric has; each is a separate time series. SAJHA caps it per family (`observability.metrics.max_series`) and never labels by user. |
| **Latency percentile** | The latency below which a given share of calls finished: p50 (median), p95, p99. |
| **Usage ledger** | The `obs_usage_events` table: one row per tool call and per LLM call with caller, outcome, latency, tokens and cost, behind the Usage & cost page (`sajha/observability/usage.py`). |
| **Usage & cost** | The console page over the usage ledger (`/monitoring/usage`): tokens, LLM spend, tool calls, errors and latency by user, key, role, model and tool, with today's budgets and the alert rules. |
| **Token budget** | A daily cap on LLM tokens per user or per role (`ai.budgets`), enforced by the LLM factory's token tracker; a call over it fails with `BudgetExceeded`. |
| **Alert rule** | A condition on a metric over a window (`observability.alerts`) that, when it holds, sends one message to a log, an allow-listed webhook or email, or raises a system notice; or a Prometheus alerting rule. |
| **System notice** | SAJHA telling the people who run it that something needs attention (`sajha/notices/`): a condition raised by a subsystem under a stable id, with a severity (info, warning, error, critical) and an audience, shown in the console's banner, navbar badge and dashboard System status panel until its source clears it or its ttl passes; administrators acknowledge it, and every transition is audited. |
| **Helm chart** | The Kubernetes package in `charts/sajha`: a Deployment with a seed init container, Service, Ingress pair, HPA, PodDisruptionBudget, optional Redis, NetworkPolicies and ServiceMonitor, configured by `values.yaml` and checked by `values.schema.json`. See the Kubernetes Deployment guide. |
| **Seed init container** | The first container of each SAJHA pod in the Helm chart: copies the image's `config/` and `sajha/tools/impl/` into writable volumes, merges `config.overrides` into `application.yml`, and waits for Redis and PostgreSQL. |
| **Streams Ingress** | The second Ingress object of the Helm chart, carrying only the long-lived paths (`/mcp`, `/api/mcp`, `/api/ai/ask`) with proxy buffering off and one-hour timeouts. |
| **Kustomize overlay** | A directory of `deployment/k8s/overlays/` (dev, prod) that `kubectl apply -k` builds on `deployment/k8s/base`; SAJHA's are rendered from the Helm chart by `deployment/k8s/render.py`. |
| **Schema file** | `db/scripts/<dialect>/schema.sql` (dialect `sqlite` or `postgresql`): every table, column, key and index SAJHA uses, as idempotent `CREATE ... IF NOT EXISTS` statements, with `seed.sql` beside it for the default roles and admin. There are no migrations: SQLite runs it at start-up; on PostgreSQL an operator runs it with `psql` and SAJHA only checks the result (`db.schema_check`). |
| **Tool test case** | One call of a tool with arguments and the assertions its result must meet, in `config/tool_tests/*.yaml` (or `tests` in the tool's config); run by `python -m sajha.quality test` (`sajha/quality/`). |
| **Test assertion** | A check on a test case's result: JSON Schema match (`schema: output`), a JSONPath with `equals` (optional numeric `tolerance`), `contains`, `regex`, `type`, `min`/`max` or `length`, or a `latency_ms` budget. |
| **HTTP cassette** | A recorded set of a test case's HTTP exchanges (`config/tool_tests/cassettes/<tool>/<case>.json`) that `--replay` serves instead of the network; intercepts `urllib.request`, `requests` and `httpx`, never stores request headers and redacts secret query parameters. |
| **Health probe** | A tool test case run on a schedule against the live service (`probe:` in a test file; `quality.probes.enabled`); one worker runs each slot (a state-store claim), results feed `sajha_tool_probe_*` metrics and the Tool Health page. |
| **Schema lint** | Static checks of every tool's definition: MCP tool-name rule, description length, valid JSON Schema 2020-12 input and output schemas, property descriptions, examples and defaults that validate, sensible annotations (`python -m sajha.quality lint`). |
| **JUnit XML** | The test-report format CI systems read; `--junit FILE` on `test`, `lint` and `eval` writes one. |
| **Tool version** | One implementation of a tool: the registered config (its own `version`) or one declared in the tool's versions file as overrides of that config or a whole config; never listed separately. |
| **Canary** | Routing a percentage of a tool's callers to a new version (`routing.canary`); sticky per caller (a hash of the API key or user id). |
| **Version pin** | A routing rule that sends one API key (by name), user or role to a given version of a tool, ahead of the canary. |
| **Automatic rollback** | Taking a canary version out of routing on every worker when its error rate or slow-call rate over a sliding window passes the file's `rollback` thresholds; recorded in the state store until an administrator clears it. |
| **Sunset date** | The date after which a deprecated version is no longer routed to, or (for the whole tool) the tool is hidden from `tools/list` and refuses calls; before it, results carry `_meta["io.sajha/deprecation"]`. |
| **Eval set** | A list of golden questions for Ask SAJHA with expected tools, answer checks and limits (`config/evals/*.yaml`), run per model and planner by `python -m sajha.quality eval` or the Evals page. |
| **Tool-selection accuracy** | The share of an eval run's questions where every expected tool was called and no forbidden one was. |
| **Answer check** | A lexical check on an eval answer: `contains`, `not_contains`, `regex`, `equals`, or `number` with `tolerance`. |

---

## 9. AI integration

| Term | Meaning |
|---|---|
| **LLM gateway** | The governance every LLM call passes through, now the engine of the governed model (`sajha/ai/llm/governed.py`): it resolves an alias (`default`, `fast`, `reasoning`, `embedding`) to a provider/model, applies role policy and budgets, retries, falls back, caches, audits and records usage. Providers talk to vendor APIs directly over HTTP; out of the box only the mock provider is enabled. See the Intelligence Layer guide. |
| **LLM factory** | `LLMFactory` (`sajha/ai/llm/factory.py`, reached as `llm_factory()` from `sajha.ai.llm`): the one way code reaches a model. It builds every LLM provider from `ai.providers`, `ai.aliases` and the provider registry, resolves secrets, keeps the instances, and hands out governed models by alias or `provider/model`. |
| **Governed model** | `GovernedModel`: what `llm_factory().model(name)` returns. A proxy with the OpenAI-style model interface (`chat_completions_create`, `embeddings_create`, ...) that applies the LLM gateway's governance and then delegates to a provider's model, so the caller never knows which provider answered until it reads `sajha.provider` on the response. |
| **LLM package boundary** | The rule that every LLM is reached through `sajha.ai.llm`: provider and model specifics live only in `sajha/ai/llm/`, one module per provider implementing the abstract `LLMProvider` and `LLMModel`; nothing outside imports a vendor SDK or a private module, or constructs a provider or model (`tests/test_llm_boundary.py`). |
| **Model alias** | A name the gateway resolves to an ordered list of `provider/model` candidates (`ai.aliases`: `default`, `fast`, `reasoning`, `embedding`); on errors that allow fallback the next candidate is tried. Out of the box every alias points at the mock provider. |
| **Intelligence layer** | The part of SAJHA that answers a question itself (`sajha/ai/intelligence.py`): it shortlists tools from the catalog, lets a model call them under the caller's permissions, and returns the answer with the tool calls it rests on and a confidence score. Served at `POST /api/ai/ask`. |
| **Ask SAJHA** | The console's chat page (`/ask`) over the intelligence layer: it streams each step of an answer (the shortlist, every tool call and result, the answer and its confidence) and draws the tool chain on the live tool catalog. |
| **sajha_ask** | The optional MCP tool (`ai.ask.mcp_tool_enabled`, off by default) that exposes the intelligence layer to MCP clients. It is an LLM tool in mode `answer` (`config/tools/sajha_ask.json`); its inner tool calls run as the MCP caller, limited to the caller's tool access and, when set, `ai.ask.mcp_allowed_tools`. |
| **LLM tool** | A tool whose work is done by a language model: a config file in `config/tools/` with `implementation` `sajha.ai.llm_tools.LLMTool` and an `llm` block (mode, model, prompt or template, allowed tools, limits, memory). Governed like any tool: access rules, policy, audit, tests, evals and versions. |
| **Mode** (*LLM tool*) | The kind of model interaction an LLM tool performs: `answer` (plan and call tools), `complete` (fill a template), `extract` (validated JSON), `classify` (one enum label), `grounded` (answer only from document passages), `narrate` (prose over a composite's or workflow's result) or `judge` (rubric scores). |
| **Conversation handle** | The `conversation_id` an LLM tool with conversation memory returns and accepts. It names stored context owned by one user and one tool; any id that is not the caller's for that tool gets the same answer, "conversation not found". |
| **Client history** | Earlier turns a caller sends in an LLM tool's `messages` argument instead of a conversation handle (`memory.mode: client`); nothing is stored on the server. |
| **Depth** (*LLM tools*) | How many LLM tools are nested in the current call chain; an LLM tool may call another only with `nesting.allow`, never one already in the chain, and no deeper than `ai.llm_tools.max_depth`. Nested runs spend from the outer run's remaining time and cost. |
| **Working set** (*LLM tools*) | What one running LLM-tool call holds in memory (tool results, previews); measured as items are added and bounded by `ai.llm_tools.memory.working_set_max_kb`, with larger items moved to the spool. |
| **Spool** | Per-run files on local disk (`ai.llm_tools.memory.spool.dir`, one folder per run) that hold large in-flight tool results instead of process memory; deleted when the run ends, swept by a janitor after a crash, and capped in total and per run. |
| **Memory guard** | The watchdog that samples the process's resident memory against soft and hard limits (percentages of the container's memory limit, or absolute): at soft it empties LLM-tool caches, spills working sets and admits no queued run; at hard it refuses new runs (`busy`) and ends running ones at their next step (`memory_pressure`). |
| **Inner call** | A tool call made by another tool (an LLM tool such as `sajha_ask`, a composite step). It runs as the original caller, with no more than the caller's tool access, and is refused when it would repeat a tool already in the call chain or nest deeper than `tools.max_call_depth`. |
| **Constellation** | The tool catalog drawn as a night sky, one star per loaded tool clustered by tool group (`static/js/constellation.js`): the landing page plays scripted questions on it, and Ask SAJHA draws each live answer's tool calls across it. |
| **LLM provider** | A module in `sajha/ai/llm/providers/` (or a plug-in) whose class implements the abstract `LLMProvider`, usually by subclassing `ProviderBase` (`sajha/ai/llm/provider.py`), for one vendor or service: it owns the key, the HTTP client and the model list, and creates the models a governed model delegates to. Its settings are a pydantic `config_model`, each field overridable as `SAJHA_AI_<PROVIDER>_<FIELD>`. |
| **Model capabilities** | What a model declares it can do (`ModelCapabilities`): tools, structured output, vision, streaming, forced tool choice, JSON mode, seed and the other canonical-format features, context window, prices and tags. A request a model does not declare is refused with UnsupportedFeature and goes to the next candidate, never sent with the feature dropped. |
| **Canonical format** | The one request and response shape every model call in SAJHA uses: the OpenAI Chat Completions format as typed models (`sajha/ai/llm/canonical.py`), with SAJHA-only data in a `sajha` field. Provider adapters translate it to each vendor at the edge. |
| **OpenAI-compatible endpoint** | SAJHA's gateway offered in the OpenAI wire format (`/v1/chat/completions`, `/v1/models`, `/v1/embeddings`; opt-in `ai.openai_api.enabled`), authenticated with a SAJHA API key as the bearer, so an OpenAI SDK gets SAJHA's model policy, budgets, cache, fallback and audit by changing only its base URL and key; enabled LLM tools appear as models `sajha:<tool>`. |
| **Sampling** (*LLM tools*) | An LLM tool's `llm.sampling: prefer` or `require`: its model call goes to the calling MCP client's model (an MRTR input request on 2026-07-28, a server request on the session stream on 2025-11-25) when the client declared sampling; otherwise `prefer` uses SAJHA's model and `require` refuses. |
| **Provider adapter** | The part of an LLM provider that translates the canonical format to its vendor's API and back (request, reply, stream events); a pass-through for OpenAI-compatible servers. |
| **Planner** | The strategy that decides each step of an ask or an `answer`-mode LLM tool (answer now, call which offered tools, check, loop or stop) while the service enforces everything. Most planners are planner files (`config/planners/<name>.yaml`): a versioned, bounded graph of stages; a few are Python classes. Chosen by `ai.ask.planner`, an LLM tool's `llm.planner`, or `ai.planners.default`. See the Planner Reference. |
| **Planner file** | One YAML document describing one planner at one version (`config/planners/<name>.yaml`, older versions kept as `<name>@<version>.yaml`), read with plain `yaml.safe_load` and validated at load (rules P001 to P071); a file that fails keeps its last good version in use. |
| **Stage** (*planner*) | One unit of work in a planner file, from a fixed library (`act`, `plan`, `execute`, `call`, `match`, `classify`, `draft`, `critique`, `revise`, `verify`, `sample`, `vote`, `foreach`, `planner`, `ask_user`, `condense`, `answer`, `fail`) or a custom type registered in code. It reads and writes named state slots and ends with an outcome. |
| **Outcome** (*planner*) | The word a stage ends with (`called`, `pass`, a rule name, a label); the stage's `outcomes` map sends each outcome to the next stage. |
| **Bounded edge** | A planner transition with `max_visits`: once taken that many times, the run goes to its `on_exhausted` stage instead. Every cycle in a planner file must cross one, so every loop ends. |
| **Guard** (*planner*) | A `when` condition with an `else` transition on a stage: when it is false the stage does not run and `else` is followed. |
| **Sub-run** | A planner run inside another run (a `planner` stage, or a `sample` or `foreach` fork); it spends from the parent's limits and may have a smaller sub-budget. |
| **Overlay** (*planner*) | Settings and model roles that replace a planner file's own for one tool or for the Ask page (`llm.planner: {use, settings, models}`, `ai.ask.planner_config.<name>`); an overlay cannot add stages or raise limits. |
| **Dry run** (*planner*) | Running a planner against the mock model with read-only tools only, to see the stage path it takes (`POST /api/ai/planners/dry-run`). |
| **Last good version** (*planner*) | The version of a `name@version` the planner registry keeps in use when the file is edited and no longer validates: running tools keep working, the error is logged, counted (`sajha_planner_load_errors_total`) and listed in the planner editor. |
| **P-rule** | One of the planner file checks, numbered `P001`-`P071` (schema, names, stage types, transitions, bounds, expressions, models, prompts, sub-planners); every finding names its rule, location and message. |
| **ReAct** (*Reason + Act*) | The default planner (`react`): one model call per step, which either answers or calls offered tools; the results feed the next step. |
| **Plan-and-execute** | The `plan_execute` planner: one structured-output call returns a plan of tool steps with dependencies; independent steps run in parallel, and a failed step triggers one re-plan. |
| **Recipe** (*planner*) | A configured rule of the `recipes` planner: a regular expression or keywords over the question, the tool to call, its arguments and optionally an answer template, so a known question shape is answered with no planning call. |
| **Router** (*planner*) | The `router` planner: picks a strategy per question from configured rules, a matching recipe, or the question's shape (several parts go to `plan_execute`, others to `react`). |
| **Plan event** | The optional `plan` event of the ask stream: the steps a planner intends to run, with dependencies; Ask SAJHA shows it as a collapsible list. |
| **Conversation memory** | Per-user multi-turn context for asks (`sajha/ai/memory.py`): recent turns are sent verbatim, older ones as a gateway-written summary, and a follow-up is rewritten as a standalone question. Never shared between users; deleted after `ai.memory.retention_days`. |
| **Conversations page** | The console page (`/conversations`) where a signed-in user lists, opens, continues in Ask SAJHA and deletes their own conversations, with Ask SAJHA and each LLM tool as a scope; administrators also see how many are stored per scope, never their content. |
| **Standalone question** | A follow-up rewritten so it can be understood without the conversation ("and from 100 to 150?" becomes "What is the percentage change from 100 to 150?"); the shortlist and planner use it. |
| **RAG** (*Retrieval-augmented generation*) | Answering from retrieved passages of documents rather than from model recall; in SAJHA, the `sajha_search_docs` tool over the document index (`sajha/ai/rag/`). |
| **sajha_search_docs** | The tool that searches SAJHA's guides and admin-configured document sources and returns passages with citations (document, section, link); also behind the help page's Ask the docs box. |
| **Vector store** | Where the document index keeps passages and their embeddings: in process by default (persisted through storage), or a pgvector table in PostgreSQL. |
| **pgvector** | A PostgreSQL extension that adds a `vector` column type and similarity search; SAJHA uses it for the document index when the extension and the optional `rag_chunks` table exist. |
| **Reciprocal rank fusion** | Combining rankings by summing 1/(k + rank) per item; the document search fuses its vector and BM25 rankings this way. |
| **Mock provider** | The built-in LLM provider that needs no network or key (`sajha/ai/llm/mock.py`). Its `mock-planner` model picks tools from keywords and numbers in the question; it serves every model alias until a real provider is enabled. |
| **mock-toolsmith** | The mock provider's offline tool designer: it answers Describe a tool deterministically from the description and the context SAJHA sends (a URL, a table, named tools, a few recipes, else a skeleton to edit). |
| **Semantic tool search** | Natural-language tool discovery (`sajha/ai/tool_resolver.py`, `POST /api/ai/resolve-tool`): ranks tools by a query over their name, description, parameters, tags and literature. The embedder is set by `ai.tool_search.embedder`. |
| **bm25** (*embedder*) | The default tool-search ranker: a dependency-free lexical BM25 index (`sajha/ai/lexical.py`) with IDF weighting, needing no model and no network. |
| **gateway** (*embedder*) | Tool-search mode that embeds tool text and queries through the LLM factory's `embedding` alias and ranks by cosine similarity; the vector index can be persisted via storage. |
| **Embedding** | A vector of numbers representing a text's meaning, so similar texts have nearby vectors. |

---

## 10. User interface

| Term | Meaning |
|---|---|
| **Theme** | One of four colour schemes over one design, shared with MAYA: **Crimson** (the default, stored as `light`), **Dark**, **Blue** and **Green**. Chosen from the palette menu and stored per browser (`sajha.theme`); applied as `data-theme` on `<html>`. With no choice stored the page follows the system light/dark preference. |
| **Design tokens** | The `--sajha-*` CSS custom properties in `static/css/tokens.css`, the only place colours are defined; `style.css` maps its `--t-*` roles onto them. |
| **About this page** | The panel at the foot of every console page (`sajha/web/page_help.py`): what the page is for, the terms it uses (defined only here), the guide that owns its topic, and related help from the help catalog. |
| **JSON editor** | The console's visual editor for JSON configuration data. |
| **User configuration** | The settings and preferences of a user account, viewable and editable as JSON. |
| **Copy** | Copying rendered output to the clipboard for use elsewhere. |
| **curl** | A command-line tool for making HTTP requests, used in the console's example calls. |
| **Created at** | The timestamp when an item such as an API key was generated. |
| **Playground** | The Python Playground (`/playground`): a small notebook that runs Python in the visitor's browser with Pyodide in a Web Worker; `import sajha` calls this server's tools and Ask SAJHA with the user's own session. Nothing runs on the server. |
| **Pyodide** | CPython compiled to WebAssembly, with numpy, pandas, matplotlib and other packages built for it; the Playground's Python. Vendored by `scripts/fetch_pyodide.py` or loaded from a CDN (`playground.assets`). |
| **WebAssembly** (*Wasm*) | A portable binary instruction format browsers run in a sandbox at near-native speed. Compiling it needs the CSP source `'wasm-unsafe-eval'`, which SAJHA grants only to the Playground's worker. |
| **Cross-origin isolation** | A page state (`crossOriginIsolated`) a browser grants when the page sends `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`; it enables `SharedArrayBuffer`, which the Playground's Stop button uses to interrupt Python. Only `/playground` sends these headers. |

---

## 11. Data sources and domain

| Term | Meaning |
|---|---|
| **FMP** (*Financial Modeling Prep*) | A market and fundamentals data API. `FMPGenericTool` maps tool names onto FMP endpoints, so a new FMP tool needs only a JSON config. |
| **OpenBB** | An open-source financial data platform. `OpenBBGenericTool` maps tool names onto OpenBB SDK commands. |
| **FRED** (*Federal Reserve Economic Data*) | The St. Louis Fed's economic time-series database and its web API. The FRED tools (including `FREDCustomSeriesTool`), the Federal Reserve tools and the `boj_` and `pboc_` tools fetch their series from it; it needs a free API key. |
| **OLAP** (*Online Analytical Processing*) | Multi-dimensional analysis (pivots, time series, cohorts, statistics); the OLAP creator builds such tools over SAJHA's data. |
| **Power BI** | Microsoft's business intelligence service. The Power BI creator builds tools that query reports and refresh datasets. |
| **DAX** (*Data Analysis Expressions*) | Power BI's query and formula language; the Power BI DAX creator builds tools that run DAX queries against datasets. |
| **LiveLink** | OpenText Content Server (formerly Livelink), an enterprise content management system; the LiveLink creator builds document search, browse and retrieval tools. |
| **SharePoint** | Microsoft's document and list platform in Microsoft 365; the SharePoint creator builds document, list and search tools over it. |
| **Data connector** | A configured connection to an enterprise data store (a SQL database or warehouse, a vector database or a search cluster) that SAJHA turns into governed, read-only tools named `<id>__...`; managed on the Data Connectors page (`/admin/connectors`). |
| **Connection record** | The JSON document `config/connectors/<id>.json` that defines one data connector: its kind, options, secret references, limits, table allowlist, masking rules and curated views. |
| **Statement guard** | The check every caller-written query passes before it reaches a data connector: exactly one read-only SELECT, no denied function, only allowed tables, masking rules respected. It uses sqlglot when installed, else a conservative scanner. |
| **Read-only session** | A database session that refuses writes by itself (PostgreSQL `default_transaction_read_only`, MySQL `TRANSACTION READ ONLY`, SQLite `mode=ro`, DuckDB `read_only`); the wall under the statement guard. |
| **Schema catalog** | A data connector's allowed tables and their described columns, cached per process for `connectors.catalog_ttl_seconds`. |
| **Table allowlist** | A data connector's `allow` block: the schemas and table patterns a query may read, and the ones it may not. |
| **Column masking** | Rewriting a column's values in a data connector's results (hide, null, redact, hash, partial or PII redaction) by rules on `column`, `table.column` or `schema.table.column`. |
| **Curated view** | An administrator-defined tool over one table: chosen columns and typed filter arguments, its SQL built by SAJHA with every value bound. Named `<id>__<view name>`. |
| **sqlglot** | A Python SQL parser for many dialects; when installed, the statement guard checks queries on its syntax tree. |
| **Qdrant** | A vector database with a REST API; a data-connector kind searched by nearest neighbour. |
| **Elasticsearch** / **OpenSearch** | Search engines with a REST API (OpenSearch is the open-source fork); data-connector kinds searched by full text, or by k-NN when a vector field is configured. |
| **Time series** | A sequence of data points indexed by time (GDP by quarter, a yield by day). FRED, the World Bank and the other data tools return them. |
| **Economic indicator** | A statistic about economic activity, such as GDP, unemployment or inflation. |
| **Indicator** | A specific measurable value tracked over time (literacy rate, life expectancy); UN and World Bank tools look data up by indicator. |
| **Indicator code** | The identifier of one data series, such as the World Bank's `NY.GDP.MKTP.CD` (GDP in current US dollars). |
| **Country code** | An ISO 3166 code identifying a country (`USA`, `CHN`, `IND`), required by the UN and World Bank queries. |
| **GDP** (*Gross Domestic Product*) | The total value of goods and services a country produces in a period. |
| **Exchange rate** | The price of one currency in terms of another. |
| **Federal funds rate** | The rate at which US banks lend reserves to each other overnight; the Federal Reserve's policy rate target. |
| **Treasury yield** | The return on US government debt, quoted by maturity (3-month, 2-year, 10-year, 30-year). |
| **Quantitative easing** (*QE*) | A central bank buying securities on a large scale to add money to the financial system. |
| **M2 / M3** | Broad measures of money supply: cash and checking deposits plus savings and other easily converted deposits (M2), plus larger and longer-term deposits (M3). |
| **BoC** (*Bank of Canada*) | Canada's central bank, responsible for monetary policy, issuing currency and financial-system stability. |
| **Policy interest rate** | The Bank of Canada's target for the overnight rate, its main monetary-policy tool. |
| **Overnight rate** | The rate at which major financial institutions borrow and lend one-day funds among themselves. |
| **Inflation target** | The Bank of Canada's 2% inflation target, the midpoint of a 1-3% control range. |
| **Government of Canada bonds** | Debt securities issued by the Canadian federal government; their yields are available through the BoC tools. |
| **CEER** (*Canadian-dollar Effective Exchange Rate*) | A trade-weighted average of the Canadian dollar's bilateral exchange rates. |
| **CAD** (*Canadian dollar*) | The currency of Canada. |
| **BoJ** (*Bank of Japan*) | Japan's central bank. |
| **JGB** (*Japanese Government Bond*) | Debt securities issued by the Japanese government. |
| **Call money rate** | Japan's uncollateralized overnight interbank rate, the Bank of Japan's main operating target. |
| **Banque de France** | France's central bank, part of the Eurosystem that implements ECB monetary policy. |
| **Eurosystem** | The ECB together with the national central banks of the euro-area countries. |
| **Eurozone** | The European Union countries that have adopted the euro. |
| **EUR** (*euro*) | The currency of France and the rest of the Eurozone. |
| **OAT** (*Obligations Assimilables du Trésor*) | French government bonds. |
| **INSEE** | France's National Institute of Statistics and Economic Studies. |
| **HICP** (*Harmonised Index of Consumer Prices*) | The euro-area inflation measure the ECB targets. |
| **ECB** (*European Central Bank*) | The central bank of the Eurozone, responsible for monetary policy for the euro. |
| **Main refinancing rate** / **Refinancing rate** | The ECB's main policy rate, at which it lends to banks for one week. |
| **Deposit facility rate** | The rate euro-area banks receive for depositing money with the Eurosystem overnight. |
| **TARGET2** | The Eurosystem's real-time gross settlement system for euro payments (now T2). |
| **PBoC** (*People's Bank of China*) | China's central bank, responsible for monetary policy and financial regulation. |
| **CNY** / **RMB** (*Chinese yuan, renminbi*) | China's currency: renminbi is its name, yuan its unit, CNY its ISO code. |
| **LPR** (*Loan Prime Rate*) | China's benchmark lending rate, published monthly. |
| **CGB** (*Chinese Government Bond*) | Debt securities issued by the Chinese government. |
| **RBI** (*Reserve Bank of India*) | India's central bank, responsible for monetary policy and banking regulation. |
| **INR** (*Indian rupee*) | The currency of India. |
| **Repo rate** | The rate at which the RBI lends to commercial banks; its key policy rate. |
| **Reverse repo rate** | The rate at which the RBI borrows from commercial banks. |
| **CRR** (*Cash Reserve Ratio*) | The share of deposits Indian banks must hold with the RBI. |
| **SLR** (*Statutory Liquidity Ratio*) | The share of deposits Indian banks must hold in liquid assets such as government securities. |
| **G-Sec** (*Government Security*) | A debt instrument issued by the Indian government. |
| **EDGAR** | The SEC's Electronic Data Gathering, Analysis, and Retrieval system, where US public companies file. |
| **CIK** (*Central Index Key*) | The SEC's 10-digit company identifier. |
| **Accession number** | The unique ID of one SEC filing (`0000320193-23-000077`). |
| **XBRL** (*eXtensible Business Reporting Language*) | The structured financial data attached to filings. |
| **Concept** / **XBRL tag** | One XBRL line item, such as `Assets`. |
| **Frame** (*XBRL*) | One XBRL concept across all filers for a calendar period (`CY2023`, `CY2023Q1`). |
| **SIC code** (*Standard Industrial Classification*) | A four-digit industry code the SEC assigns to each filer. |
| **Form type** | The category of an SEC filing: 10-K, 10-Q, 8-K, DEF 14A and so on. |
| **10-K** / **10-Q** | The SEC annual and quarterly reports. |
| **Investor relations page** (*IR page*) | The part of a company website that publishes reports, presentations and filings for investors. |
| **Earnings presentation** | The slide deck that accompanies a quarterly earnings call. |
| **SEC fallback** | When the investor relations tools find nothing by scraping, they retrieve matching filings from SEC EDGAR by CIK. |
| **Ticker symbol** | A short code identifying a traded security (`AAPL` for Apple). |
| **Stock quote** | A security's current price and trading information; Yahoo Finance quotes may be delayed. |
| **Historical data** (*prices*) | Past price and volume data for a security, at daily, weekly or monthly intervals. |
| **Market capitalization** | A company's share price times its shares outstanding. |
| **P/E ratio** (*price-to-earnings*) | Share price divided by earnings per share, a common valuation measure. |
| **Dividend yield** | Annual dividends per share divided by the share price, as a percentage. |
| **Options chain** | All listed options on a security: calls and puts across strikes and expiry dates. |
| **ETF** (*Exchange-Traded Fund*) | A fund whose shares trade on an exchange like a stock. |
| **FBI** (*Federal Bureau of Investigation*) | The US federal law-enforcement and intelligence agency; its Crime Data Explorer API backs the FBI tools. |
| **UCR** (*Uniform Crime Reporting*) | The FBI programme that collects crime statistics from US law-enforcement agencies. |
| **NIBRS** (*National Incident-Based Reporting System*) | The incident-level crime data collection that replaced UCR summary reporting in 2021. |
| **ORI** (*Originating Agency Identifier*) | The code identifying a law-enforcement agency in FBI data. |
| **Crime statistics** | Counts of criminal offences, nationally, by state or by agency. |
| **Violent crime** | Offences involving force or its threat: murder, rape, robbery, aggravated assault. |
| **Property crime** | Taking property without force: burglary, larceny-theft, motor-vehicle theft, arson. |
| **Crime rate** | Offences per 100,000 people, so areas of different size can be compared. |
| **IMF** (*International Monetary Fund*) | The international organization for monetary cooperation and financial stability. |
| **Balance of payments** | The record of all economic transactions between a country's residents and the rest of the world. |
| **Current account** | The part of the balance of payments covering trade in goods and services, income and current transfers. |
| **SDR** (*Special Drawing Rights*) | The IMF's international reserve asset, supplementing members' official reserves. |
| **WEO** (*World Economic Outlook*) | The IMF's twice-yearly analysis and projections of the global economy. |
| **Financial Soundness Indicators** | IMF statistics on the health of a country's financial institutions and markets. |
| **UN** (*United Nations*) | The international organization for peace, security and cooperation among nations. |
| **UNSD** (*United Nations Statistics Division*) | The UN body that compiles and publishes global statistics. |
| **UNdata** | The UNSD's portal (`data.un.org`) to the UN statistical databases. |
| **SDG** (*Sustainable Development Goals*) | The UN's 17 global development goals for 2030. |
| **HDI** (*Human Development Index*) | A composite index of health, education and income. |
| **Treaty** | A formal agreement between states; the UN Treaty Collection records them. |
| **World Bank** | The international financial institution that lends and grants for development and publishes development data. |
| **WDI** (*World Development Indicators*) | The World Bank's main database of development indicators: economy, health, education and more. |
| **Poverty rate** | The share of a population living below a poverty line, such as the World Bank's international line in dollars a day at purchasing-power parity. |

## 12. SAJHA Net

| Term | Meaning |
|---|---|
| **SAJHA Net** | SAJHA servers (and other MCP servers) joined into a net: they find each other by gossip, prove who they are with net certificates and sign every request between them. Off by default (`sajhanet.enabled`). Membership, names, the CA, signed requests, catalogs, proxies, routing, identity, blocks, the Instances and Remote tools pages and the navbar badge are built. |
| **Net** | One SAJHA Net: its own CA, certificates, members and revocation list. A server may be in several nets at once; nothing learned in one is used in another. |
| **Net name** | The name of a net (`acme-net`): lowercase letters, digits, `-` and `_`, starting with a letter, at most 16 characters, never `__` and not ending in `_`. A net entry without a name is the net `default`. |
| **Participant** | Anything that holds a net certificate and speaks the SAJHA Net protocol: a SAJHA instance, an agent in front of an MCP server, or a server built on the reference library. |
| **Instance name** | A participant's name in one net, unique there: configured (`risk-eu`) or, when none is configured, its address (`10.20.4.17:3002`). It is the CN of the participant's certificate. |
| **Address name** | An instance name made from the address peers reach the server on, `<ip>:<port>` or `[<ipv6>]:<port>`; never unspecified, loopback, `localhost` or link-local. |
| **Safe prefix** | The instance part of a qualified tool name: a configured name as is, an address with every `.` and `:` replaced by `_`, IPv6 written out in full. |
| **Qualified tool name** | `<net>__<safe prefix>__<tool>`: one tool on one host in one net, split at the first two `__`. |
| **Seed** | An address a server contacts first to join a net. A net entry without seeds is a net of one. |
| **Founder** | The first server of a net, which starts without seeds (or with `founder: true` when its seeds may all be down) and waits to be contacted; usually the CA instance. |
| **Net of one** | A net whose only member is this server: a net entry with no seeds and no known peers, or every server while SAJHA Net is off. Nothing to join, no gossip and no error; it grows into an ordinary net when a peer joins through it or is added by address, without a restart. |
| **Gossip** (*SWIM*) | How participants keep one membership list without a leader: each pings a random member every interval, asks others to ping one that does not answer, marks it suspect and then dead, and piggybacks changes on the messages. |
| **Member record** | A participant's own signed statement in a net: name, URL, features, incarnation, sequence and digests. Relays can repeat it but not change it. |
| **Incarnation** | A participant's own counter in a net, milliseconds since the epoch chosen at start as max(now, last + 1); a higher incarnation overrides any older claim that it is suspect or dead. |
| **Member state** | `alive`, `suspect` (did not answer a direct or indirect probe), `dead` (suspect past the timeout) or `left` (departed cleanly, signed by itself). |
| **Saved peer list** | Each net's known members on local disk (`peers.json`), written on change and every ten minutes; tried after the seeds when a server restarts. |
| **SAJHA Net CA** | The certificate authority of one net, run by its CA instance (`ca.enabled`): issues certificates for enrollment tokens, renews them, and signs the revocation list. |
| **Enrollment token** | A single-use, short-lived secret bound to one net and one instance name, with which a new server obtains its certificate from the CA; refused for a name already held. |
| **Revocation list** | The CA-signed list of revoked instance names and certificate serials of a net, spread by gossip and checked on every request. |
| **Certificate lineage** | The certificate that first held a name in a net and every certificate the CA issued by renewing it; the name belongs to the lineage, so a restart or renewal is not a conflict. |
| **Name conflict** | A participant claiming a name held by a different, unrevoked key: refused with `409 name_conflict` naming the holder; the refused server does not join and raises an error notice until its configuration or certificate changes. |
| **Manual mode** | A net without a CA: self-signed certificates whose thumbprints each administrator pins. |
| **Open mode** | A net without a CA: self-signed certificates accepted the first time a name is seen, then each name held to that key. |
| **Gossip agent** | The worker that runs a net's membership protocol for an instance: the holder of the renewing state-store lease `sajhanet:agent:<net>`. |
| **Catalog exchange** | How a participant learns another's tools: when the peer's catalog digest or incarnation changes (and every refresh interval) it pulls the peer's signed catalog, answered with `unchanged` when its hash matches. A peer's tools are listed only after it answered in the current run. |
| **Contract hash** | The SHA-256 of a tool's input schema, output schema and annotations in canonical JSON; two hosts offer the same tool in a net only when their contract hashes are equal. Descriptions and versions are not part of it. |
| **Contract conflict** | Two hosts in one net offering a tool name with different contract hashes. The name is quarantined on every member, the local copy included, until every host offers one contract again; the report names the differing host and the first differing JSON Pointer. |
| **Quarantine** | The state of a tool name with a contract conflict: no copy is listed, resolvable, callable or a fallback target in that net. It lifts by itself when the conflict ends. |
| **Conflicts document** | A participant's signed list of the contract conflicts it observes itself, versioned by `digests.conflicts`, so that members that cannot see every offer still quarantine the name. |
| **Proxy tool** | A remote tool in this server's registry: called like a local tool, run by its host through a signed forwarded call. Listed under its qualified name and, while a bare alias is offered, under its plain name. |
| **Bare alias** | The plain name (`var_calc`) of a remote tool, resolved in the resolution order; offered when no local tool has the name (`sajhanet.bare_aliases`). |
| **Resolution order** | Where a call by plain name goes: the local tool, else the tool's preference list (`sajhanet.preferences`), else the nets in configured order, each ordered by the routing strategy; hosts that are suspect, blocked, quarantined, refused by import rules or of another contract are skipped, with the reason recorded. |
| **Host and tool table** | Every instance's live record of which host in which net offers which tool, with state, hashes, trust and each row's place in the resolution order; the source of proxies, aliases and the Remote tools view. |
| **Trust level** | How a peer's tools are imported: `auto` (at once after screening), `review` (after an administrator approves each one) or `pinned` (only tools an administrator named). |
| **Waterfall fallback** | A call by plain name moving to the next host offering the same tool, at most `sajhanet.max_fallbacks` times, only when the first host certainly did not run it, or when the tool is read-only or idempotent and not destructive. |
| **Not executed** | A forwarded call the host certainly did not run: never sent, or refused with `executed: false` in a signed answer. Only such a failure lets a destructive tool fall back. |
| **Home instance** | The instance that issued a user's API key and the only one through which that key enters a net; in a forwarded call, the instance the caller used. |
| **Host instance** | The instance that runs a forwarded call to one of its tools, after verifying the user and applying its own rules. |
| **Net user** | A user at an instance, in a net, written `alice@risk-eu`: the owner of a forwarded key as the host sees them, before it maps them to a local identity. |
| **Net key directory** | Each net's synced copy of every instance's signed API key records (hashes, owner, state, tool access; never a key), kept in the `sajhanet_api_keys` table and used by a host to verify forwarded keys. |
| **Key record** | One API key's entry in the net key directory, signed by its home and versioned by the home's single counter; a deleted key stays as a tombstone with `revoked_at`. |
| **User link** | An administrator's mapping of a net user (`alice@risk-eu`) to a local account, tried before name matching. |
| **Name matching** | Running a net user as the local account with the same login name (`users.user_id`), with that account's local roles; on by default, and can be turned off per instance. |
| **Role map** | The local roles a host gives users of another instance who have no local account, by their roles at home, when `sajhanet.users.unknown` is `map_roles`. |
| **Export rule** | A rule in a net entry naming which tools this instance offers to which instances and roles; nothing is exported unless a rule allows it. |
| **Import rule** | A rule in a net entry naming which instances' tools this instance's users may use, and for which roles; nothing is imported unless a rule allows it. |
| **Instances page** | The console page every signed-in user has (`/net/instances`): each participant of this server's nets with kind, region, labels, state and last seen, and the tools it offers that user, each with the Tools page's Try it form. |
| **Net badge** | The navbar badge beside the SAJHA wordmark, `Net · <instance name>` with a health dot (and `+N` for further nets), naming the instance a user is on and linking to the Instances page. |
| **Net overview** | The administrators' console page for one net (`/admin/sajhanet/overview`): members and their states, the topology map, admission, gossip health, open notices, contract conflicts and held tools, blocks, recent forwarded calls with their trace ids, call-chain refusals and residency decisions. |
| **Topology map** | The Net overview's drawing of one net: a node per instance (this server in the centre) showing its member state in colour and words, and links for tools offered, re-exported and called; a table beside it says the same for screen readers. |
| **Net access page** | The console page every signed-in user has (`/net/access`): each remote tool by name, its hosts in resolution order, and which of those this server lets that user call. |
| **Admission mode** | How a net admits a participant (`admission` in its net entry): `builtin_ca` (certificates from the net's SAJHA Net CA), `manual` (pinned thumbprints), `open` (first-use keys) or a plug-in class. |
| **First-use key** | In open mode, the key thumbprint first seen for an instance name, remembered on disk; a later server presenting that name with another key is refused until an administrator forgets the remembered one. |
| **Forwarded call** | A call to a remote tool, sent signed by the home instance to its host with the user's identity and a trace id; both sides record it in their audit chains under that trace id. |
| **Net block** | A local decision of one instance in one net to stop traffic: an instance entirely, inbound, outbound, a tool or a remote user; audited, may expire, enforced only by the instance that set it and published in its signed blocks document. |
| **Data class** | A label on data (`eu-personal`, `confidential`, `public`) that residency rules decide on: marked on schema fields with `x-sajha-data-class`, declared for a whole tool (`data_classes`), or added by configuration (`sajhanet.data_classes.tools`). |
| **Residency** | Where data may flow between instances: residency rules decide, by data class and destination, whether arguments may leave the home and results may leave the host, and refuse (`-32012`) or redact. |
| **Residency rule** | A policy rule whose match names data classes, a flow (`arguments` or `results`) or a destination (net, instance, region, labels, here, `differs_from_here`); evaluated where data crosses to another instance. |
| **Field redaction** | Replacing the values of the fields of a data class with `[REDACTED:<class>]` (`redact: {data_classes: [...]}`), in arguments before they leave and in results before they leave or as they arrive. |
| **Residency-aware shortlist** | A shortlist or `tools/list` that leaves out a remote tool whose host may not receive the data every call of it sends. |
| **Locality** | Where an offered tool runs, as a planner's shortlist records it: local (this server's own), remote (a SAJHA Net host) or federated. Local tools rank first, then nearer, healthier and preferred hosts, and each entry says why. |
| **Locality restriction** | Keeps the tools offered to a planner to this server's own (`local`) or to this server's and one net's (`net:<name>`); set by the ask, the planner's `settings.locality` or `ai.ask.locality`. |
| **Remote LLM tool** | An LLM tool another instance offers: called through its proxy as the user, it runs on its host's models and budgets and reports its model spend back, which the home records but does not charge again. |
| **Call chain budget** | The one limit on a call chain across SAJHA Net: hops plus tools nested in one another on every instance passed (`sajhanet.max_call_chain`). Over it a call is refused with `chain_limit`, at the home before sending or at the host on receipt. |
| **Identity resolver** | How the user travels with a forwarded call and is verified at the host, chosen per net (`user_identity`): `api_key`, `assertion`, `token_exchange` or `none`. The first the host also lists is sent; all listed are accepted. |
| **User assertion** | A short-lived record the home signs with its net certificate naming the user, a key id of theirs in the net key directory, the audience host and the trace id; used by the `assertion` resolver, by re-exported calls and by bridges. Only a key id crosses, never a key. |
| **Token exchange** | The `token_exchange` resolver: the home trades a user assertion at the host's token endpoint for a host-scoped token, caches it until shortly before it expires, and sends the token with each call. |
| **Host-scoped token** | An opaque token a host issues to one home for one user in one net; the host keeps only its hash and re-checks the key, blocks and mapping on every call. |
| **Re-export** | Offering onward a tool imported from another participant (`reexport` on for the net offered into, and a re-export rule naming the tool); a call to it is relayed with hop count, visited list and the caller's identity carried end to end. Off by default. |
| **Re-export rule** | A rule (`reexport_rules`) naming which imported tools go onward, from which nets and hosts, to which instances and for which roles; with re-export on, nothing goes onward unless a rule names it. |
| **Re-export origin** | The participant that really hosts a tool re-exported within one net, named `origin` in its catalog entry; a call to it carries a user assertion addressed to the origin, and a tool never comes back to its origin. |
| **Bridge** | A server in two nets that re-exports a tool of one net into the other as its own: it authorizes the caller like any host, then calls into the other net as the local user it mapped them to, with an assertion it signs there. |
| **Sponsored MCP server** | An MCP server that knows nothing of SAJHA Net, connected to a SAJHA server as a federation upstream and represented by it in a net under an instance name of its own (kind `sponsored`, its member record naming the sponsor). The sponsor holds its certificate and governs every call to it with its own export rules, access, policy, residency and audit (`sajhanet.sponsored`). |
| **SAJHA Net agent** | A small program (`python -m sajhanet_agent`) that runs next to any MCP server, reached over stdio or HTTP, and makes it a participant of kind `agent`: certificate, gossip, catalog, forwarded-key verification, an export policy and signed calls. Built on the reference library; it never loads the SAJHA server. |
| **Reference library** | `sajha.net.library`: a complete SAJHA Net participant built from the protocol core alone (`NetParticipant`), for a Python MCP server that joins a net itself; the SAJHA Net agent is built on it. |
| **SAJHA Net conformance suite** | The cases of the SAJHA Net protocol's §20, run by `python -m sajha.net.conformance` against a SAJHA instance, an agent or a sponsored participant over HTTP, or against the protocol core (`--target library`); every case is reported pass, fail or skip with its reason. |
| **SAJHA Net plug-in** | A third-party implementation of one of SAJHA Net's plug-in interfaces (membership, admission, connector, identity, catalog source, key directory store, rules, snapshot sink, routing), loaded at start from `sajhanet.plugins.modules` or the entry-point group `sajha.net.plugins`, and selectable only after it passes its contract check. |
