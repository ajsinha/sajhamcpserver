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
`--log-level`, and `--stdio`, which serves MCP on stdin/stdout instead of HTTP; see
section 11). Everything a client can reach over HTTP comes through one of four doors:

```
 MCP clients ──► /mcp, /api/mcp (Streamable HTTP, both eras)
                 /mcp/sse + /mcp/message (legacy HTTP+SSE) · /mcp/ws (WebSocket)
 OAuth clients ─► /.well-known/oauth-* · /oauth/*      (only when mcp.auth.mode ≠ off)
 Programs ─────► /api/...  REST (JWT or API key) · /api/ai/ask · /a2a, /.well-known/agent.json
                 /metrics, /health, /ready
 People ───────► HTML pages (Jinja2, cookie session): landing, dashboard, tools, prompts,
                 Studio, composite builder, Ask SAJHA, Python Playground, admin
                 (incl. federation, AI settings), monitoring, help, /glossary, /comparison
                                   │
   middleware, outermost first: observability → request-size limit → security headers → CORS
                   (sajha/observability/middleware.py, sajha/security.py; added in sajha/app.py)
                                   │
                    route modules: sajha/routes/*_routes.py
                                   │
   ┌───────────────────────────────┼───────────────────────────────────────────┐
   │ MCPHandler + MCPModern        │ ToolsRegistry ◄── tool JSON configs       │
   │ (sajha/core/mcp_*.py)         │   + composites (DB), federated tools,     │
   │ sessions · MRTR · tasks ·     │   Studio tools (sandboxed stand-ins)      │
   │ apps · change bus             │ PromptsRegistry ◄── prompt configs        │
   │                               │ connectors · workflows · plugins ·        │
   │                               │ tool versions · policy engine             │
   │ IntelligenceService → LLMFactory → GovernedModel → providers (sajha/ai/)  │
   └───────────────┬───────────────┴───────────────┬───────────────────────────┘
                   │ execution: cache → circuit breaker → tool.execute() → metrics, usage
                   │ (user code runs out of process, in the sajha/sandbox/ runner)
                   ▼                               ▼
   storage backend (local | s3 | azure | gcs)   database (SQLite | PostgreSQL)
   configs, prompts, Studio output, guides,     users, roles, keys, audit, LLM config,
   federation store                             usage ledger, ...
                                   │
              state store (memory | redis | database): sessions, tasks, OAuth, counters
```

The default is one process. Cross-request state (MCP sessions, MCP tasks, OAuth codes
and refresh tokens, rate limits, change notifications) goes through the state store,
which is process memory by default and Redis or the database when several workers run;
see section 9 and [Scaling and State](Scaling%20and%20State.md).

---

## 2. Startup

`SajhaMCPServerWebApp` in `sajha/app.py` builds the app: middleware, static files at
`/static`, every router in `sajha/routes/`, error handlers. Its lifespan then runs, in
order:

1. **Database.** `sajha/db/engine.py::init_db` connects to the database (`db.type`). On
   SQLite it runs `db/scripts/sqlite/schema.sql`; on PostgreSQL it runs no DDL and checks
   that every table and column the code uses exists, refusing to start while one is
   missing (`db.schema_check`; [Database Setup](../getting-started/Database%20Setup.md)).
2. **State store.** `sajha/core/state/` builds the store named by `state.backend`; a
   shared store that does not answer stops start-up
   ([Scaling and State](Scaling%20and%20State.md)).
3. **Configuration and storage.** `PropertiesConfigurator` loads
   `config/application.yml` (so tool configs can use `${...}` placeholders), and
   `init_storage()` selects the storage backend. The policy files are then loaded and
   this process's audit hash chain and SIEM sinks opened
   ([Policy and Audit](Policy%20and%20Audit.md)).
4. **Registries.** `ToolsRegistry` loads every tool config; `PromptsRegistry` loads
   prompts. On a cloud backend an `S3SyncManager` polls the bucket and reloads them;
   locally the registries' own pollers do.
5. **Handlers.** `MCPHandler` is created over the registries with `SessionToolAccess`
   (per-caller tool access); the hot-reload manager (`sajha/core/hot_reload_manager.py`)
   starts.
6. **Optional subsystems**, in this order, each failing soft (logged, server still
   starts): federation (upstream tools registered before anything indexes the catalog;
   waits at most `federation.startup_wait_seconds`), data connectors' generated tools (no
   database is opened), composite tools from the database, workflows (scheduler,
   triggers, run recovery), observability (metrics, OpenTelemetry, the usage ledger,
   alert rules), plugins, the LLM gateway, the tool-search index, the
   intelligence service (with the optional `sajha_ask` MCP tool), the document index
   behind `sajha_search_docs`, and the tool-quality health probes.
7. **Template globals** (version, theme, navigation, help) are registered.

On shutdown, in order: observability flushes the usage ledger and stops its threads,
federation closes upstream connections, the change bus is closed (ending listen streams
cleanly), the state store stops its heartbeat and pub/sub threads, and the reload
manager and registry pollers stop.

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
| `sajha/core/mcp_sessions.py` | `Mcp-Session-Id` sessions (in the state store) and server→client request correlation |
| `sajha/core/mcp_modern.py` | The 2026-07-28 envelope: `_meta` validation, header ladder, `server/discover`, `resultType`, caching hints, streamed `tools/call`, `subscriptions/listen`, `x-mcp-header` validation |
| `sajha/core/mcp_tool_context.py` | Per-call context a tool uses to report progress and logs and to see cancellation |
| `sajha/core/mcp_mrtr.py` | Multi Round-Trip Requests: `InputRequired`, HMAC-signed `requestState` |
| `sajha/core/state/` | The state store (`state.backend`: memory, Redis, database): key/value with TTLs, atomic updates and counters, sliding windows, pub/sub; worker heartbeats |
| `sajha/core/mcp_tasks.py` | The tasks extension store (`TaskStore`): per user, records in the task record store, TTL and cap, orphan detection |
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
In mode `off` it only resolves SAJHA credentials (API key, JWT, cookie) if present, and
answers 401 when a sent `Authorization` or `X-API-Key` does not authenticate; in
`optional` / `required` it also validates OAuth bearer tokens and produces the 401/403
challenges. The resolved caller travels in the MCP session dict, and `MCPHandler`'s
`SessionToolAccess` (`sajha/auth/access.py`) filters `tools/list` and checks `tools/call`
on every transport. See the [OAuth Guide](../protocol/OAuth%20Guide.md) and the
[Security Model](../security/Security%20Model.md#tool-access).

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
- **Execution path** (`execute_with_tracking`, shared by MCP, REST, async execution, A2A,
  Ask SAJHA and federated calls; composite steps call `execute()` through
  `sajha/core/composition.py`): enabled check → argument validation → output cache (`sajha/core/cache.py`,
  per-tool `cache_ttl`) → per-provider circuit breaker (`sajha/core/circuit_breaker.py`)
  → `execute()` in a worker thread → metrics, usage ledger, trace span and
  recent-execution history ([Observability](Observability.md)).
- **Around it:** tool versions with canary routing and rollback (`sajha/quality/versions.py`, called first
  in `execute_with_tracking`; [Tool Quality](Tool%20Quality.md)), plugins (`plugins.py`),
  provider health (`tool_health.py`), webhooks
  (`webhooks.py`), async background execution with webhook/Kafka/file delivery
  (`async_executor.py`), and the sandboxed shell tools (`shell_executor.py`, disabled
  by default).
- **User code** (Studio Python code and script tools, the shell) runs outside the
  process through `sajha/sandbox/`: the registry loads such tools as sandboxed stand-ins
  that never import their code. See [Sandbox](Sandbox.md).
- **Federated tools** are `FederatedTool` instances (`sajha/federation/tool.py`) that
  `FederationManager` registers as `<prefix>__<name>` and routes to an upstream MCP server
  on its own background event loop. See [Federation](Federation.md).

## 6. Composition

Composite tools chain registered tools into one tool. They are defined in the
database (`composite_tools`, `composite_tool_steps`), built by `CompositeToolEngine`
(`sajha/tools/composite_tool.py`) at startup and on save, and registered like any
other tool, so a saved composite is callable over MCP at once (and re-registered after a
registry reload). Each step's result is a `StepResult` envelope; `ParamLens` projects
parameters between steps; `EntropyGuard` tracks cumulative confidence
(`sajha/core/composition.py`). Design and theory:
[Composition Framework](Composition%20Framework.md).

## 7. Prompts, Studio, AI, Playground

- **Prompts.** `PromptsRegistry` (`sajha/core/prompts_registry.py`) loads prompt
  configs, serves `prompts/list` / `prompts/get`, and publishes changes to the bus.
  Guide: [Prompts Management Guide](../tools/prompts/Prompts%20Management%20Guide.md).
- **MCP Studio.** Generators in `sajha/studio/` turn a description (Python function,
  REST call, SQL query, script, Power BI, DAX, LiveLink, SharePoint, OLAP) into a tool
  config, written through the storage backend, and an implementation module, written
  locally; the registry then hot-loads the config. `sajha/routes/studio_routes.py` serves
  the pages (`/studio/*`) and the actions their forms post to
  (`/admin/studio/*`: analyze, preview, deploy, delete), all behind `require_studio`
  (an admin, or a role with the `studio` permission such as `developer`). Guide:
  [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md). Two Studio pages
  build tools differently: Import an API (`sajha/api_import/`) turns an OpenAPI, Swagger
  or GraphQL description into configs run by one generic executor
  ([API Import](API%20Import.md)), and Describe a tool (`sajha/studio/describe.py`) has a
  model propose a tool that is checked, tested and deployed only on approval
  ([Tool Generation](Tool%20Generation.md)).
- **Governed data access.** Data connectors (`sajha/connectors/`) generate read-only tools
  over databases, warehouses and vector stores ([Data Connectors](Data%20Connectors.md));
  connected accounts (`sajha/accounts/`) let a tool act as its caller at another service
  ([Connected Accounts](Connected%20Accounts.md)).
- **Workflows and quality.** `sajha/workflows/` runs DAGs of tool, composite and ask steps
  on schedules and triggers ([Workflows](Workflows.md)); `sajha/quality/` holds the test
  harness, linter, probes, evals and tool versions ([Tool Quality](Tool%20Quality.md)).
- **AI.** `sajha/ai/llm/` is the one LLM package and its boundary: the public API
  (`sajha.ai.llm`: the canonical OpenAI-style types, the abstract `LLMProvider` and
  `LLMModel`, `llm_factory()`, the errors), the provider SPI (`spi.py`), one module per
  provider in `providers/`, and the factory (`factory.py`, `LLMFactory`) whose
  `model(alias)` returns a `GovernedModel` proxy (`governed.py`) that resolves aliases to
  models with policy, budgets, retries, fallback, caching, audit and tracing. Nothing outside
  the package imports a vendor SDK or a private module of it (`tests/test_llm_boundary.py`);
  `sajha/ai/intelligence.py` (`IntelligenceService`) is the ask loop behind
  `POST /api/ai/ask`, the Ask SAJHA page (`/ask`) and the optional `sajha_ask` MCP tool,
  with pluggable planners (planner files in `config/planners/` run by `sajha/ai/planners_engine/`,
  and the Python `Planner` protocol in `sajha/ai/planners.py`), per-user conversation memory
  (`sajha/ai/memory.py`) and the document index behind `sajha_search_docs`
  (`sajha/ai/rag/`).
  `sajha/ai/tool_resolver.py` answers natural-language tool searches: a lexical BM25 index
  by default (`sajha/ai/lexical.py`), optionally an embedding index
  (`sajha/ai/embedders.py`), re-synced in the background whenever tools reload. Design:
  [Intelligence Layer](Intelligence%20Layer.md); extension points:
  [Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md).
- **Python Playground.** `/playground` (`sajha/routes/playground_routes.py`) serves a
  Pyodide notebook that runs in the browser; its `sajha` module calls tools through the
  REST API with the user's session, so nothing of the user's code runs on the server.
  Guide: [Python Playground](../getting-started/Python%20Playground.md).

## 8. Persistence

| Store | What lives there | Code |
|---|---|---|
| Database (SQLite default, PostgreSQL) | Users, roles, permissions, API keys, audit log and its hash chain and anchors, prompts metadata, composite tools, tool usage, LLM providers, models and usage, the observability usage ledger (`obs_usage_events`), connected-account tokens, workflows and their runs, quality runs, conversations; every table is in the schema files | `sajha/db/`, `db/scripts/<type>/`, `sajha/observability/usage.py` |
| Storage backend (local, S3, Azure Blob, GCS) | Tool and prompt configs, Studio output, the federation store (upstreams and approvals), guides served at `/help/guides` | `sajha/core/storage.py`; [Storage Guide](../getting-started/Storage%20Guide.md) |
| Local disk (`data/`) | Tool output cache, async results, shell scratch, DuckDB/SQL data files, the OAuth signing key | config keys under `cache`, `async`, `shell`, `data`, `mcp.auth.builtin` |
| State store (`state.backend`: memory, Redis or the database) | MCP sessions, MCP task records, OAuth pending consents, codes, refresh tokens and DCR clients, rate-limit windows, LLM budgets, change-bus relay | `sajha/core/state/`; [Scaling and State](Scaling%20and%20State.md) |
| Process memory | Listen streams and other open connections, upstream connections, caches, circuit breakers, metrics | see the inventory in [Scaling and State](Scaling%20and%20State.md#3-inventory-of-process-state) |

Mutable state (the SQLite file, audit log, cache) does not belong on an object store;
keep it on a real filesystem or a managed database.

## 9. Security layers

Credential checks (`sajha/auth/`: `AuthManager`, `AuthContext`, the JWT handler and
password policy), per-caller tool access (`sajha/auth/access.py`, shared by REST, MCP, A2A and async), generated server secrets (`sajha/core/server_secrets.py`), OAuth on MCP endpoints, the
Origin allow-list on `/mcp`, security headers and CSP (`sajha/security.py`), request
size limits, rate limiting, the sandbox for user code (`sajha/sandbox/`), the policy
engine on every tool call (`sajha/policy/`) and the audit log (`sajha/core/audit.py`)
with its tamper-evident hash chain (`sajha/audit/`;
[Policy and Audit](Policy%20and%20Audit.md)). The model, the defaults and the deployment checklist are in
the [Security Model](../security/Security%20Model.md).

**Scaling out.** Several workers or hosts need a shared `state.backend` and shared
secrets; what is shared, what stays per process and why is
[Scaling and State](Scaling%20and%20State.md). Container images, the Helm chart
(`charts/sajha`) and the Kustomize manifests (`deployment/k8s/`) are
[Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md).

## 10. Web UI

Server-rendered Jinja2 templates in `sajha/web/templates/` with Bootstrap and
vendored assets (no CDN), one design-token file
(`sajha/web/static/css/tokens.css`) and four themes: Crimson, Dark, Blue and Green.
`render()` in `sajha/app.py` supplies common context.

The in-app help is data-driven. `sajha/web/help_catalog.py` is the registry of help
topics (rendered at `/help` and `/help/c/{cid}`); `sajha/web/guides.py` finds each guide
under `docs/` by its unique file name and renders it server-side at
`/help/guides/{name}` (`docs/archive/` is never served); `/glossary` is rendered from
`GLOSSARY.md`; `/help/tools` is derived from the tools registry. Every console page ends
with an "About this page" panel from `sajha/web/page_help.py`, whose terms are looked up
in `GLOSSARY.md`. These pages need no login. The old `/docs` URLs redirect to
`/help/guides`. `/comparison` is rendered from `sajha/web/competitive.py`, its only copy.

**Scripts under the CSP.** The console's Content-Security-Policy runs only scripts from this
origin or carrying the response's nonce, and no inline event handlers ([Security
Model](../security/Security%20Model.md#security-headers-and-csp)). So a template writes each inline
script as `<script nonce="{{ csp_nonce() }}">`, and a handler as `data-onclick="fn(this, 'x')"`
(or `data-onchange`, `data-onsubmit`, ...), never `onclick=`; HTML built in script follows the same
rule. `static/js/csp-actions.js` runs those handlers: calls to functions the page declares
globally, with literal, `this` or `event` arguments, and `return false`. `tests/test_csp_handlers.py`
enforces this.

**Small screens.** The rules for phones and tablets are one block, "Mobile", at the end of
`style.css`: below 992px the top menu collapses behind the hamburger and its mega-menu
panels become a scrollable accordion; below 768px controls are at least 40px tall and
inputs use 16px text (so iOS does not zoom); below 576px a table with class
`sajha-stack` shows one card per row. `main.js` puts every other data table in a
horizontal-scroll box (`.sajha-xscroll`), labels `sajha-stack` cells from their column
headings, and on touch screens shows a `title` on tap. To check a change, run
`scripts/check_mobile.py` (Playwright and Chromium) against a running server, preferably
on a scratch database (`SAJHA_DB_PATH`):

```
python scripts/check_mobile.py --base http://127.0.0.1:3002 --password '<admin password>' \
    --shots /tmp/sajha-mobile --warnings
```

It opens each page in its `ROUTES` list at 375, 390 and 768px wide and fails on a
horizontally scrolling page, on elements outside the viewport, on a phone menu that
does not open, fit and close, and on a CSP violation, an inline event handler, a `data-on*`
handler that would not run or a script error. It warns about tap targets under 40px, text under 12px
and tall fixed elements. `tests/test_mobile_layout.py` checks that its routes still
render and that every page has a viewport meta; it runs the browser check only when
`SAJHA_CHECK_BASE` names a running server.

**Flows and accessibility.** `scripts/check_console.py` drives the console end to end in
Chromium: sign in, Ask SAJHA answers an example question, the LLM tool creator builds, tries,
deploys and deletes a tool, the planner editor dry-runs a planner, and the Conversations page
lists the conversation. It then scans its `PAGES` (or, with `--all`, every route of
`check_mobile.py`) for accessibility: with axe-core (`--axe <axe.min.js>` or `SAJHA_AXE_JS`) the
WCAG 2.x A and AA rules, failing on serious or critical violations; without it, a documented
subset of those rules (`RULES` in the script). Run it against a scratch server, in each theme
with `--theme`:

```
python scripts/check_console.py --base http://127.0.0.1:3087 --axe /path/to/axe.min.js --theme dark
```

`tests/test_console_checks.py` checks that its pages render and runs it only when
`SAJHA_CHECK_BASE` names a running server.

**Who sees which page.** The MCP Studio menu and its sub-navigation list only the creators the
caller's Studio permissions open (`studio_creators` in `render()`'s context; the
[MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md#permissions)); the planner editor
(`/studio/planners`) is for administrators. The Conversations page (`/conversations`, under
**AI → Ask**) shows each user only their own conversation memory; administrators also see counts
per scope. The **SAJHA Net** menu shows every signed-in user the Instances page (`/net/instances`) and
the Net access page (`/net/access`: every remote tool, its hosts in resolution order and which of them
the user may call); administrators also get the Net overview (`/admin/sajhanet/overview`: one net's
topology map with a table equivalent, members, admission, notices, conflicts, blocks and recent
forwarded calls), Remote tools (`/admin/sajhanet/tools`) and the SAJHA Net admin page, where the
admission panel (first-use keys, pins or the CA) and runtime seeds are managed. The map and the
admission panel are drawn by `static/js/sajhanet.js` in plain SVG on the theme tokens. Beside
the wordmark, the navbar badge `Net · <instance name>` names the instance a user is on and links to
Instances ([SAJHA Net](SAJHA%20Net.md) §17).

## 11. Clients, the CLI and stdio

`clientsdk/sajhaclient` is a separate package: a zero-dependency core (REST, MCP over
HTTP/SSE/WebSocket, A2A) and, with the `mcp` extra, `SajhaMCPClient` /
`SajhaMCPSyncClient` built on the official MCP SDK. Guide:
[Client SDK Guide](../clients/Client%20SDK%20Guide.md). The package also installs the
`sajha` command (`clientsdk/sajhaclient/cli/`; the `cli` extra brings its dependencies).

The stdio transport is in the server package: `sajha/cli/stdio.py` (started by
`python run_server.py --stdio` or `sajha serve --stdio`) builds the registries and an
`MCPHandler` without the web app and serves both protocol eras on stdin/stdout, with one
caller per process fixed at start-up (`--user`, `--api-key`, or the anonymous policy).
Guide: [Command Line](../clients/Command%20Line.md).

## 12. Tests and CI

`tests/` (pytest with FastAPI's `TestClient`): unit and integration suites, one suite
per protocol area (`test_mcp_2025_11_25.py`, `test_mcp_2026_07_28.py`,
`test_mcp_auth.py`, `test_mcp_apps.py`) and per subsystem (for example
`test_state_store.py`, `test_sandbox.py`, `test_federation.py`, `tests/ai/`; each
subsystem's guide describes its tests). `clientsdk/tests/` tests the client package.
`.github/workflows/mcp-conformance.yml` runs the official MCP conformance suite against
a live server for both protocol versions.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
