# SAJHA MCP Server — Architecture

How the server is built inside: the process, the request paths, the main components
and where their code lives. It describes structure, not usage. Usage belongs to the
guides named in [How SAJHA Fits Together](../getting-started/How%20SAJHA%20Fits%20Together.md),
protocol behaviour to the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md),
and every configuration key to the [Configuration Reference](../getting-started/Configuration%20Reference.md).

---

## 1. Shape of the system

SAJHA is one FastAPI (ASGI) application served by Uvicorn, started by
`run_server.py` (`--config`, `--host`, `--port`, `--reload`, `--workers`,
`--log-level`). Everything a client can reach comes through one of four doors:

```
 MCP clients ──► /mcp, /api/mcp (Streamable HTTP, both eras)
                 /mcp/sse + /mcp/message (legacy HTTP+SSE) · /mcp/ws (WebSocket)
 OAuth clients ─► /.well-known/oauth-* · /oauth/*      (only when mcp.auth.mode ≠ off)
 Programs ─────► /api/...  REST (JWT or API key)        · /a2a, /.well-known/agent.json
 People ───────► HTML pages (Jinja2, cookie session): dashboard, tools, prompts,
                 Studio, composite builder, admin, monitoring, help, /docs
                                   │
      CORS → security headers → request-size limit (middleware, sajha/app.py, sajha/security.py)
                                   │
                    route modules: sajha/routes/*_routes.py
                                   │
   ┌───────────────────────────────┼────────────────────────────────────┐
   │ MCPHandler + MCPModern        │ ToolsRegistry ◄── tool JSON configs │
   │ (sajha/core/mcp_*.py)         │ PromptsRegistry ◄── prompt configs   │
   │ sessions · MRTR · tasks ·     │ CompositeToolEngine (DB-defined)     │
   │ apps · change bus             │ plugins · tool versioning · tenancy  │
   └───────────────┬───────────────┴───────────────┬────────────────────┘
                   │ execution: cache → circuit breaker → tool.execute() → metrics
                   ▼                               ▼
   storage backend (local | s3 | azure | gcs)   database (SQLite | PostgreSQL)
   configs, prompts, Studio output, docs        users, roles, keys, audit, LLM config, ...
```

The default is one process. Several components keep state in process memory
(MCP sessions, MCP tasks, `subscriptions/listen` streams, OAuth codes and refresh
tokens), so more than one worker needs sticky routing; see section 9.

---

## 2. Startup

`SajhaMCPServerWebApp` in `sajha/app.py` builds the app: middleware, static files at
`/static`, every router in `sajha/routes/`, error handlers. Its lifespan then runs, in
order:

1. **Database.** `sajha/db/engine.py::init_db` runs the dialect's SQL scripts in
   `db/scripts/<db.type>/` (schema, then seed). There is no ORM auto-create and no
   migration tool; the scripts are idempotent.
2. **Configuration and storage.** `PropertiesConfigurator` loads
   `config/application.yml` (so tool configs can use `${...}` placeholders), and
   `init_storage()` selects the storage backend.
3. **Registries.** `ToolsRegistry` loads every tool config; `PromptsRegistry` loads
   prompts. On a cloud backend an `S3SyncManager` polls the bucket and reloads them;
   locally the registries' own pollers do.
4. **Handlers.** `MCPHandler` is created over the registries; the hot-reload manager
   (`sajha/core/hot_reload_manager.py`) starts.
5. **Optional subsystems**, each failing soft (logged, server still starts):
   composite tools from the database, observability (metrics, health probes),
   tenancy, plugins, the LLM gateway, and the semantic tool index.
6. **Template globals** (version, theme, navigation) are registered.

On shutdown the change bus is closed (ending listen streams cleanly) and the
registry pollers stop.

---

## 3. Configuration

One YAML file, `config/application.yml`, with `${ENV:default}` substitution, flattened
to dotted keys. `sajha/core/config.py::_get(key)` resolves a key as: environment
variable `SAJHA_<KEY_WITH_UNDERSCORES>` → YAML → code default. `--config` or
`SAJHA_CONFIG_FILE` choose another file; a `.env` file is loaded if present. The
version shown everywhere is `app.version`. Details:
[Configuration Reference](../getting-started/Configuration%20Reference.md).

---

## 4. The MCP layer

| Module | Responsibility |
|---|---|
| `sajha/routes/mcp_routes.py` | HTTP endpoints; Origin check; authorization; era detection; session lookup; SSE responses |
| `sajha/core/mcp_handler.py` (`MCPHandler`) | The shared method implementations: tools, prompts, resources, completion, logging; the legacy (handshake) JSON-RPC dispatcher |
| `sajha/core/mcp_2025_11_25.py` | Version negotiation, `MCPError`, Origin validation, icon building, the legacy task/elicitation/sampling managers, SSE event tracking |
| `sajha/core/mcp_sessions.py` | In-memory `Mcp-Session-Id` sessions and server→client request correlation |
| `sajha/core/mcp_modern.py` | The 2026-07-28 envelope: `_meta` validation, header ladder, `server/discover`, `resultType`, caching hints, streamed `tools/call`, `subscriptions/listen`, `x-mcp-header` validation |
| `sajha/core/mcp_tool_context.py` | Per-call context a tool uses to report progress and logs and to see cancellation |
| `sajha/core/mcp_mrtr.py` | Multi Round-Trip Requests: `InputRequired`, HMAC-signed `requestState` |
| `sajha/core/mcp_tasks.py` | The tasks extension store (`TaskStore`): per user, in memory, TTL and cap |
| `sajha/core/mcp_apps.py`, `mcp_app_views/` | MCP Apps: `ui://` views and `_meta.ui` validation |
| `sajha/core/change_bus.py` | Thread-safe, coalescing fan-out of list-changed and resource-updated events |
| `sajha/core/mcp_conformance_fixtures.py` | Conformance-suite fixtures, off by default |
| `sajha/routes/ws_routes.py` | The WebSocket transport `/mcp/ws` |
| `sajha/auth/oauth/` | OAuth 2.1: settings, resource server (token validation, challenges), built-in authorization server, clients (CIMD, static, DCR), signing keys |
| `sajha/routes/oauth_routes.py` | Discovery documents and `/oauth/*` endpoints |

**Dual era.** A POST is classified once (`mcp_modern.is_modern_request`). The modern
path owns the envelope and delegates the method itself to `MCPHandler`, so tools,
prompts and resources have one implementation. The modern path holds no session
state: everything it needs between rounds travels in the signed `requestState`.

**Change bus.** The registries publish on register, unregister, enable, disable and
reload; the bus delivers to `subscriptions/listen` streams, the legacy SSE stream and
WebSocket sessions. While an event is queued for a subscriber, identical events are
dropped, so a bulk reload is one notification.

**Authorization.** `authorize_mcp` runs before era detection on every MCP endpoint.
In mode `off` it only resolves SAJHA credentials (API key, JWT, cookie) if present; in
`optional` / `required` it also validates OAuth bearer tokens and produces the 401/403
challenges. `MCPHandler` has hooks for per-user tool filtering, but it is created
without an auth manager, so the hooks are inactive in this release. See the
[OAuth Guide](../protocol/OAuth%20Guide.md).

---

## 5. Tools

- **Definition.** Each tool is a JSON file in `config/tools/` (through the storage
  backend): `name`, `implementation` (a Python class path), `description`,
  `inputSchema`, optional `outputSchema`, `title`, `annotations`, `icons`,
  `execution.taskSupport`, `_meta.ui`, `cache_ttl`, `enabled`, `version`.
- **Implementation.** Classes derive from `BaseMCPTool` (`sajha/tools/base_mcp_tool.py`);
  provider implementations live in `sajha/tools/impl/`.
- **Registry.** `ToolsRegistry` (`sajha/tools/tools_registry.py`) loads, enables and
  disables tools, polls for config changes, notifies reload listeners and publishes to
  the change bus.
- **Execution path** (shared by MCP and REST): enabled check → argument validation →
  output cache (`sajha/core/cache.py`, per-tool `cache_ttl`) → per-provider circuit
  breaker (`sajha/core/circuit_breaker.py`) → `execute()` in a worker thread →
  metrics and recent-execution history.
- **Around it:** tool versioning (`tool_versioning.py`), plugins (`plugins.py`),
  tenancy (`tenancy.py`), provider health (`tool_health.py`), webhooks
  (`webhooks.py`), async background execution with webhook/Kafka/file delivery
  (`async_executor.py`), and the sandboxed shell tools (`shell_executor.py`, disabled
  by default).

## 6. Composition

Composite tools chain registered tools into one tool. They are defined in the
database (`composite_tools`, `composite_tool_steps`), built by `CompositeToolEngine`
(`sajha/tools/composite_tool.py`) at startup and on save, and are meant to be
registered like any other tool. In this release that registration fails
(`CompositeToolEngine` calls `ToolsRegistry.register_tool` with two arguments; it takes
one), so saved composites are stored and previewable but not callable. Each step's result is a `StepResult` envelope; `ParamLens` projects
parameters between steps; `EntropyGuard` tracks cumulative confidence
(`sajha/core/composition.py`). Design and theory:
[Composition Framework](Composition%20Framework.md).

## 7. Prompts, Studio, AI

- **Prompts.** `PromptsRegistry` (`sajha/core/prompts_registry.py`) loads prompt
  configs, serves `prompts/list` / `prompts/get`, and publishes changes to the bus.
  Guide: [Prompts Management Guide](../tools/prompts/Prompts%20Management%20Guide.md).
- **MCP Studio.** Generators in `sajha/studio/` turn a description (Python function,
  REST call, SQL query, script, Power BI, DAX, LiveLink, SharePoint) into a tool config,
  written through the storage backend, and an implementation module, written locally;
  the registry then hot-loads the config. The Studio pages are served by
  `sajha/routes/studio_routes.py` (GET only); the action endpoints their forms post to
  are not registered in this release. Guide:
  [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md).
- **AI.** `sajha/ai/gateway.py` fronts the LLM providers in `sajha/ai/providers/`,
  with providers and models managed in the database. `sajha/ai/tool_resolver.py`
  answers natural-language tool searches: a lexical BM25 index by default
  (`sajha/ai/lexical.py`), optionally an embedding index (`sajha/ai/embedders.py`),
  re-synced in the background whenever tools reload.

## 8. Persistence

| Store | What lives there | Code |
|---|---|---|
| Database (SQLite default, PostgreSQL) | Users, roles, permissions, API keys, sessions, audit log, rate-limit log, tenants, prompts metadata, composite tools, tool versions and usage, LLM providers, models and usage | `sajha/db/`, `db/scripts/<type>/` |
| Storage backend (local, S3, Azure Blob, GCS) | Tool and prompt configs, Studio output, documents served at `/docs` | `sajha/core/storage.py`; [Storage Guide](../getting-started/Storage%20Guide.md) |
| Local disk (`data/`) | Tool output cache, async results, shell scratch, DuckDB/SQL data files, the OAuth signing key | config keys under `cache`, `async`, `shell`, `data`, `mcp.auth.builtin` |
| Process memory | MCP sessions, MCP tasks, listen streams, OAuth pending consents, codes, refresh tokens and DCR clients | `mcp_sessions.py`, `mcp_tasks.py`, `sajha/auth/oauth/` |

Mutable state (the SQLite file, audit log, cache) does not belong on an object store;
keep it on a real filesystem or a managed database.

## 9. Security layers

Credential checks (`sajha/auth/`, `sajha/core/auth_manager.py`,
`sajha/core/apikey_manager.py`), role-based tool access, OAuth on MCP endpoints, the
Origin allow-list on `/mcp`, security headers and CSP (`sajha/security.py`), request
size limits, rate limiting and the audit log (`sajha/core/audit.py`). The model, the
defaults and the deployment checklist are in the
[Security Model](../security/Security%20Model.md).

**Scaling out.** Because of the in-memory state in section 8, run one worker per
instance or route each client to the same worker. Set `mcp.mrtr.state_secret` and
share the OAuth signing key so that any instance can verify what another issued.

## 10. Web UI

Server-rendered Jinja2 templates in `sajha/web/templates/` with Bootstrap and
vendored assets (no CDN), one design-token file
(`sajha/web/static/css/tokens.css`) and four themes: Crimson, Dark, Blue and Green.
`render()` in `sajha/app.py` supplies common context. Help pages live under
`sajha/web/templates/help/`; the markdown documentation is browsable at `/docs`.

## 11. Client SDK

`clientsdk/sajhaclient` is a separate package: a zero-dependency core (REST, MCP over
HTTP/SSE/WebSocket, A2A) and, with the `mcp` extra, `SajhaMCPClient` /
`SajhaMCPSyncClient` built on the official MCP SDK. Guide:
[Client SDK Guide](../clients/Client%20SDK%20Guide.md).

## 12. Tests and CI

`tests/` (pytest with FastAPI's `TestClient`): unit and integration suites, plus one
suite per protocol area (`test_mcp_2025_11_25.py`, `test_mcp_2026_07_28.py`,
`test_mcp_auth.py`, `test_mcp_apps.py`). `.github/workflows/mcp-conformance.yml` runs
the official MCP conformance suite against a live server for both protocol versions.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
