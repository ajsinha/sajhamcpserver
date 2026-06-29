# SAJHA MCP Server — System Architecture

**Version:** 5.3.0
**Last Updated:** May 2026
**Author:** Ashutosh Sinha (ajsinha@gmail.com)
**Classification:** Technical Reference

---

## 1. Executive Summary

SAJHA MCP Server v5.3.0 is a production-grade Python implementation of the Model Context Protocol built on FastAPI. It serves 497 tools across financial, government, search, and enterprise data sources through a standards-compliant MCP interface (protocol version 2025-11-25 (latest)), a REST API, and SSE transport. The system includes a full web UI, role-based access control, visual tool creation (MCP Studio), A2A agent interoperability, live reporting, and a zero-dependency Python client SDK.

| Aspect | Detail |
|--------|--------|
| Framework | FastAPI (ASGI, Uvicorn) |
| Language | Python 3.9+ |
| Protocol | MCP 2025-11-25 (latest), JSON-RPC 2.0 |
| Tools | 497 loaded from 501 JSON configs |
| Transports | HTTP POST, SSE |
| Database | SQLite (default), PostgreSQL |
| Config | YAML (`config/application.yml`) |
| Auth | JWT, API Key, Session Cookie, OAuth (optional) |
| UI | Jinja2 templates, Bootstrap 5, Chart.js |

---

## 2. High-Level Architecture

```
                          ┌──────────────────────────────────────────┐
                          │            SAJHA MCP Server              │
                          │              (FastAPI/ASGI)               │
                          ├──────────────────────────────────────────┤
  Clients                 │                                          │
  ───────                 │  ┌──────────┐  ┌──────────┐  ┌────────┐ │
  MCP Client ──HTTP POST──│→ │ MCP Route │→ │MCPHandler│→ │ Tools  │ │
             ──SSE────────│→ │          │  │(JSON-RPC)│  │Registry│ │
                          │  └──────────┘  └──────────┘  └────────┘ │
  Browser    ──HTTP───────│→ ┌──────────────────────────┐           │
                          │  │ 13 Route Modules (79+ ep) │           │
                          │  └──────────────────────────┘           │
  A2A Agent  ──HTTP POST──│→ ┌──────────┐                          │
                          │  │ A2A Route │                          │
                          │  └──────────┘                          │
                          │                                          │
                          │  ┌──────────┐  ┌──────────┐  ┌────────┐ │
                          │  │AuthManager│  │ Database │  │ Config │ │
                          │  │(JWT/Key)  │  │(SQLite/PG)│  │ (YAML) │ │
                          │  └──────────┘  └──────────┘  └────────┘ │
                          └──────────────────────────────────────────┘
```

---

## 3. Startup Flow

The entire application bootstraps through `SajhaMCPServerWebApp` in `sajha/app.py`:

```
run_server.py
  └→ SajhaMCPServerWebApp()
       ├→ _create_app() → FastAPI instance
       │    ├→ _add_middleware()         CORS (allow all origins)
       │    ├→ _mount_static()          /static → sajha/web/static/
       │    ├→ _register_routes()       13 APIRouters
       │    └→ _register_error_handlers() 404/403/500
       └→ _lifespan() (async context manager)
            ├→ init_db()                 Run 001_schema.sql + 002_seed.sql
            ├→ run_legacy_import()       Import users.json + apikeys.json
            ├→ _init_managers()
            │    ├→ PropertiesConfigurator   Inject YAML values for ${var} resolution
            │    ├→ ToolsRegistry            Load 501 JSON configs → instantiate 497 tools
            │    ├→ PromptsRegistry          Load prompt catalog
            │    ├→ MCPHandler               Wire registries → 12 MCP methods
            │    └→ HotReloadManager         Watch config/ for changes (configurable interval)
            └→ _register_template_globals()  url_for(), app_name, filters
```

No route definitions exist in `app.py` — all 79+ endpoints live in `sajha/routes/`.

---

## 4. Package Structure

```
sajha/
├── app.py                          # FastAPI orchestrator (SajhaMCPServerWebApp)
├── __init__.py
├── core/
│   ├── config.py                   # YAML loader, Settings dataclass, _flatten()
│   ├── mcp_handler.py              # MCP JSON-RPC 2.0 handler (12 methods)
│   ├── properties_configurator.py  # ${var} resolution singleton
│   ├── prompts_registry.py         # Prompt catalog manager
│   └── hot_reload_manager.py       # Config file watcher
├── auth/
│   ├── __init__.py                 # AuthManager + FastAPI dependencies
│   ├── password.py                 # Direct bcrypt (not passlib)
│   └── jwt_handler.py              # JWT create/decode (python-jose)
├── db/
│   ├── engine.py                   # SQLAlchemy engine + SQL script runner
│   ├── base.py                     # DeclarativeBase
│   ├── models/__init__.py          # 8 ORM models
│   ├── dao/__init__.py             # 7 DAO classes
│   └── seed.py                     # Legacy JSON import
├── routes/
│   ├── auth_routes.py              # Login, logout, JWT (/login, /api/auth/login)
│   ├── dashboard_routes.py         # Dashboard (/dashboard)
│   ├── tools_routes.py             # Tool list, execute, schema (/tools/*)
│   ├── admin_routes.py             # User/tool management (/admin/*)
│   ├── api_routes.py               # REST API (/api/tools/*, /api/admin/*)
│   ├── mcp_routes.py               # MCP POST + SSE (/mcp, /mcp/sse, /mcp/message)
│   ├── a2a_routes.py               # A2A agent card + tasks (/.well-known/agent.json)
│   ├── reporting_routes.py         # Reports API + dashboard (/reports, /api/reports/*)
│   ├── prompts_routes.py           # Prompt CRUD (/prompts/*, /api/prompts/*)
│   ├── apikeys_routes.py           # API key management (/admin/apikeys/*)
│   ├── studio_routes.py            # MCP Studio (/studio/*)
│   ├── health_routes.py            # Health endpoint (/health)
│   └── misc_routes.py              # Help, about, docs, monitoring
├── tools/
│   ├── base_mcp_tool.py            # Abstract base tool class
│   ├── tools_registry.py           # Tool catalog manager
│   ├── http_utils.py               # HTTP helper functions
│   └── impl/                       # 15+ tool implementation files
│        ├── fmp_tools.py           # 100 FMP tools
│        ├── openbb_tools.py        # 70 OpenBB tools
│        ├── yfinance_tools.py      # 35 Yahoo Finance tools
│        ├── fred_tools.py          # 55 FRED tools
│        ├── alphavantage_tools.py  # 35 Alpha Vantage tools
│        ├── coingecko_tools.py     # 25 CoinGecko tools
│        ├── calc_tools.py          # 19 financial calculators
│        ├── enhanced_edgar_tool.py # 20 SEC EDGAR tools
│        └── ...                    # Additional provider modules
└── web/
    ├── templates/                  # 39 Jinja2 templates
    │   ├── common/                 # base.html, error.html
    │   ├── auth/                   # login.html
    │   ├── dashboard/              # dashboard.html
    │   ├── tools/                  # tools_list, tool_execute, tool_schema, tool_config
    │   ├── prompts/                # prompts_list, prompt_create, prompt_detail, prompt_test
    │   ├── admin/                  # admin_users, admin_tools, apikeys_*, studio/*
    │   ├── help/                   # help.html, about.html
    │   ├── docs/                   # docs_list, docs_view
    │   ├── monitoring/             # monitoring_tools, monitoring_users
    │   └── reporting/              # reports_dashboard
    └── static/                     # CSS, JS, images
```

---

## 5. Configuration System

### 5.1 Single Source: `config/application.yml`

All configuration is in YAML with environment variable substitution:

```yaml
db:
  type: sqlite
  path: data/sajha.db
  pool:
    size: ${DB_POOL_SIZE:10}
```

### 5.2 Config Loader (`sajha/core/config.py`)

1. Reads `config/application.yml`
2. Flattens nested keys to dot notation: `db.pool.size`
3. Resolves `${ENV_VAR:default}` syntax
4. Checks for `SAJHA_` prefixed env overrides: `SAJHA_DB_TYPE=postgresql`
5. Exposes a `Settings` dataclass via `get_settings()`

### 5.3 PropertiesConfigurator

A singleton that injects flattened YAML values so tool configs can resolve `${var}` references (e.g., `${data.duckdb.dir}` in a tool's JSON config).

### 5.4 What Was Removed from v2

- `application.properties` — replaced by `application.yml`
- `server.properties` — merged into `application.yml`
- All `.properties` fallback code and parsers

### 5.5 Storage Layer (`sajha/core/storage.py`)

All configuration and asset IO flows through a single storage abstraction, so the same
build runs unchanged on local disk, on-prem, or any cloud. `init_storage(config)` runs at
startup (before tools/prompts load) and `get_storage()` is the app-wide accessor.

```
StorageBackend (ABC)
 ├── LocalStorageBackend            backend: local (default) — filesystem / EFS, no SDK
 └── _ObjectStorageBackend          shared object-store base
       ├── S3StorageBackend         backend: s3     (boto3; endpoint_url → MinIO/R2/Wasabi)
       ├── AzureBlobStorageBackend  backend: azure  (azure-storage-blob)
       └── GCSStorageBackend        backend: gcs    (google-cloud-storage)
S3SyncManager                       cloud hot-reload (poll → cache → reload callbacks)
```

Design points:

- **Six primitives.** Each object store implements only `_fetch_bytes`, `_store_bytes`,
  `_object_exists`, `_delete_object`, `_list_keys`, `_object_mtime`. The shared base layers
  on prefix namespacing, a local read-through cache, recursive listing with filename-pattern
  matching, JSON helpers, and prefix sync.
- **Lazy SDKs.** Cloud SDKs import inside each backend, so the default `local` path requires
  none of them.
- **Read-through cache.** Cloud reads mirror objects into `cache_dir`, giving `importlib`
  and other real-file consumers a concrete file.
- **Subsystems on storage.** `tools_registry` (config reads/writes), `prompts_registry`
  (reads/writes/delete), the docs viewer, and all MCP Studio generators read/write through
  `get_storage()`. Tool/Studio `.py` implementations remain package-local because `importlib`
  needs a module on the path.
- **Read-mostly vs mutable state.** Object stores hold configs/prompts/docs; the SQLite DB
  and audit log must stay on a real filesystem (EFS) or a managed service.

```yaml
storage:
  backend: local        # local | s3 | azure | gcs
  base_dir: "."
  s3:   { bucket: "", prefix: "sajha/", region: us-east-1, endpoint_url: "", sync_interval: 60 }
  azure:{ container: "", account_url: "", connection_string: "", prefix: "sajha/" }
  gcs:  { bucket: "", project: "", prefix: "sajha/" }
```

---

## 6. Database Layer

### 6.1 Engine (`sajha/db/engine.py`)

- SQLAlchemy engine creation (SQLite or PostgreSQL)
- SQL script runner for the dialect-specific `db/scripts/<db.type>/` directory
  (`sqlite/` or `postgresql/`), each with `001_schema.sql` + `002_seed.sql`
- `CREATE TABLE IF NOT EXISTS` — no migrations needed
- Session factory via `get_db_session()`

### 6.2 Schema (9 Tables)

| Table | Key Columns |
|-------|-------------|
| `users` | user_id, user_name, password_hash (bcrypt), enabled |
| `roles` | role_id, role_name, description |
| `permissions` | permission_id, permission_name |
| `user_roles` | user_id → role_id |
| `role_permissions` | role_id → permission_id |
| `api_keys` | key_id, key_hash, user_id, tool_patterns (JSON array) |
| `tool_executions` | execution_id, tool_name, user_id, duration_ms |
| `tool_errors` | error_id, tool_name, error_message, timestamp |
| `sessions` | session_id, user_id, created_at, expires_at |

### 6.3 ORM Models and DAOs

8 ORM models in `sajha/db/models/__init__.py` map directly to the schema tables.

7 DAO classes in `sajha/db/dao/__init__.py` provide data access: UserDAO, RoleDAO, PermissionDAO, ApiKeyDAO, ToolExecutionDAO, ToolErrorDAO, SessionDAO.

### 6.4 Design Decisions

- **No Alembic**: Schema managed via SQL scripts with `IF NOT EXISTS`. Simpler to reason about and deploy.
- **Seed data**: Default admin user (bcrypt hash for `admin123`), default roles (`admin`, `user`), and base permissions inserted by `002_seed.sql`.
- **Legacy import**: `sajha/db/seed.py` imports from `config/users.json` and `config/apikeys.json` at startup for backward compatibility with v2 deployments.

---

## 7. Authentication and Authorization

### 7.1 AuthManager (`sajha/auth/__init__.py`)

Supports four authentication methods:

| Method | How It Works |
|--------|-------------|
| **Session cookie** | Web login → JWT stored in `sajha_token` cookie |
| **Bearer JWT** | `Authorization: Bearer <token>` header |
| **API Key** | `X-API-Key` header, checked against hashed keys in DB |
| **OAuth** | Optional, config-driven (Azure AD / Okta / Auth0 / Keycloak) |

### 7.2 FastAPI Dependencies

Three dependency functions gate route access:

- `get_current_user` — resolves auth context from request (cookie, header, or API key)
- `require_auth` — returns 401 if not authenticated
- `require_admin` — returns 403 if not in admin role

### 7.3 Password Hashing

Direct bcrypt via the `bcrypt` package (not passlib, which has compatibility issues with bcrypt 4.x).

### 7.4 JWT Tokens

Created and decoded via `python-jose`. Default HS256 algorithm, configurable expiry (default 60 minutes).

### 7.5 OAuth (Optional)

Config-driven via `oauth.mode` in `application.yml`:

| Mode | Description |
|------|-------------|
| `none` | No OAuth (default) |
| `internal` | SAJHA manages users, IdP authenticates |
| `external` | IdP manages both users and auth |
| `hybrid` | IdP authenticates, SAJHA maps scopes |

---

## 8. MCP Protocol Handler

### 8.1 MCPHandler (`sajha/core/mcp_handler.py`)

Handles all 12 MCP methods via a `handle_request()` method that routes JSON-RPC 2.0 messages:

```python
def handle_request(self, request_data: Dict, session: Optional[Dict] = None) -> Dict:
    method = request_data.get('method')
    # Routes: initialize, ping, tools/list, tools/call,
    #         prompts/list, prompts/get, resources/list, resources/read,
    #         resources/templates/list, resources/subscribe, resources/unsubscribe,
    #         completion/complete, logging/setLevel
```

### 8.2 Protocol Version

Declared protocol version: `2025-11-25` (latest). Full compliance including Tasks, Elicitation, Sampling with tools, OIDC Discovery, CIMD, PRM, tool icons, and Origin validation.

### 8.3 Capabilities

```json
{
  "tools": {"listChanged": true},
  "prompts": {"listChanged": true},
  "resources": {"subscribe": true, "listChanged": true},
  "logging": {},
  "completions": {}
}
```

### 8.4 Pagination

- `tools/list`: cursor-based, 100 tools per page
- `resources/list`: cursor-based, 50 resources per page, auto-discovers data files

### 8.5 Completion

`completion/complete` auto-suggests values from `enum` fields in tool input schemas.

---

## 9. Tools Framework

### 9.1 Base Class (`sajha/tools/base_mcp_tool.py`)

Abstract base class `BaseMCPTool` that all tools extend:

```python
class BaseMCPTool:
    def get_input_schema(self) -> Dict: ...   # JSON Schema
    def get_output_schema(self) -> Dict: ...  # JSON Schema
    def execute(self, arguments: Dict) -> Dict: ...  # Main logic
```

### 9.2 ToolsRegistry (`sajha/tools/tools_registry.py`)

- Enumerates and reads JSON configs through `get_storage()` (local | s3 | azure | gcs)
- Dynamically imports and instantiates tool classes via `implementation` dotted path
  (implementation modules ship with the package and import locally)
- `register_tool_from_dict()` is the shared register path for the file loader and plugins
- Config writes go through `get_storage().write_json()`
- Singleton pattern via `get_tools_registry()`
- Hot-reload: filesystem poller on `local`, `S3SyncManager` on cloud backends

### 9.3 Tool Configuration (JSON)

Each tool has a JSON config in `config/tools/`:

```json
{
  "name": "yahoo_finance_quote",
  "implementation": "sajha.tools.impl.yfinance_tools.YahooFinanceQuoteTool",
  "description": "Get real-time stock quote",
  "enabled": true,
  "metadata": {
    "category": "Financial",
    "tags": ["stocks", "quotes", "market"],
    "rateLimit": 60
  }
}
```

### 9.4 Generic Tool Pattern

`FMPGenericTool` and `OpenBBGenericTool` auto-map tool names to API endpoints. The tool name determines the endpoint path. Adding a new FMP or OpenBB tool requires only a JSON config file — no Python code. This pattern accounts for 170+ of the 497 tools.

### 9.5 Tool Groups

The web UI groups tools by provider prefix (text before the first `_` in the tool name). This creates consistent grouping: `yahoo_*`, `fmp_*`, `fred_*`, `openbb_*`, etc.

---

## 10. Route Modules

13 route modules register 79+ endpoints:

| Module | Prefix | Key Endpoints |
|--------|--------|---------------|
| `auth_routes` | `/` | `/login`, `/logout`, `/api/auth/login` |
| `dashboard_routes` | `/` | `/dashboard` |
| `tools_routes` | `/` | `/tools`, `/tools/{name}/execute`, `/tools/{name}/schema` |
| `admin_routes` | `/admin` | `/admin/users`, `/admin/tools` |
| `api_routes` | `/api` | `/mcp`, `/api/tools/execute`, `/api/tools/list`, admin APIs |
| `mcp_routes` | `/` | `/mcp/sse`, `/mcp/message`, resource/completion/logging APIs |
| `a2a_routes` | `/` | `/.well-known/agent.json`, `/a2a` |
| `reporting_routes` | `/` | `/reports`, `/api/reports/*` (7 endpoints) |
| `prompts_routes` | `/` | `/prompts/*`, `/api/prompts/*` |
| `apikeys_routes` | `/admin/apikeys` | CRUD for API keys |
| `studio_routes` | `/studio` | 11 studio pages |
| `health_routes` | `/` | `/health` |
| `misc_routes` | `/` | `/help`, `/about`, `/docs/*`, `/monitoring/*` |

---

## 11. A2A Protocol

### 11.1 Agent Card

`GET /.well-known/agent.json` returns an auto-generated agent card describing the server's capabilities, constructed from the tool registry.

### 11.2 Task Lifecycle

`POST /a2a` handles JSON-RPC task operations:

- `tasks/send` — submit a task for execution
- `tasks/get` — check task status
- `tasks/cancel` — cancel a running task

---

## 12. Reporting

7 API endpoints plus a Chart.js dashboard at `/reports`:

| Endpoint | Data |
|----------|------|
| `/api/reports/overview` | Summary statistics |
| `/api/reports/tools/usage` | Tool execution counts |
| `/api/reports/tools/{name}/detail` | Per-tool metrics |
| `/api/reports/users/activity` | User activity data |
| `/api/reports/heatmap` | Usage heatmap data |
| `/api/reports/audit` | Audit log entries |
| `/reports` | HTML dashboard with Chart.js visualizations |

---

## 13. MCP Studio

Visual tool creation platform accessible at `/studio`. Seven creator types, each generating both a JSON config and a Python implementation file that are deployed immediately via hot-reload.

| Creator | Route | Input Format |
|---------|-------|-------------|
| Python Code | `/studio` | `@sajhamcptool` decorated function |
| REST Service | `/studio/rest` | URL, method, headers, auth, schemas |
| DB Query | `/studio/dbquery` | SQL template + parameter definitions |
| Script | `/studio/script` | Script content + interpreter selection |
| PowerBI Report | `/studio/powerbi` | Workspace ID + Report ID + Azure AD creds |
| PowerBI DAX | `/studio/powerbidax` | Dataset ID + EVALUATE query |
| LiveLink | `/studio/livelink` | Server URL + operation + auth config |

Additional pages: `/studio/olap`, `/studio/sharepoint`, `/studio/examples`.

---

## 14. Hot-Reload System

The `HotReloadManager` monitors config directories for changes and reloads registries without server restart:

| What | Monitored Path | Default Interval |
|------|----------------|:----------------:|
| Tool configs | `config/tools/*.json` | 300s |
| Tool Python modules | `sajha/tools/impl/*.py` | 300s |
| Prompts | `config/prompts/*.json` | 300s |
| Users (legacy) | `config/users.json` | 300s |
| API keys (legacy) | `config/apikeys.json` | 300s |

Interval is configurable via `hot_reload.interval_seconds` in `application.yml`.

Force immediate reload: `POST /api/admin/tools/reload`.

**Cloud backends.** Object stores have no inotify. When `storage.backend` is `s3`/`azure`/`gcs`,
`S3SyncManager` runs instead of the filesystem poller: it polls the bucket every
`storage.*.sync_interval` seconds, mirrors changed objects into the local cache, and fires the
same reload callbacks (`tools_registry.reload_all_tools`, `prompts_registry.reload`). Exactly
one mechanism runs per deployment — the registry's local poller is skipped on cloud backends.

---

## 15. Template System

### 15.1 Jinja2 Integration

FastAPI + Jinja2Templates with a `render()` helper that auto-injects session data for `base.html`.

### 15.2 url_for Compatibility

A custom `url_for()` function mapped in template globals provides Flask-style URL resolution across all 39 templates.

### 15.3 Template Filters

| Filter | Purpose |
|--------|---------|
| `dt` | Date/time formatting with configurable length |
| `truncate_text` | Text truncation with ellipsis |
| `json_pretty` | Pretty-print JSON |

---

## 16. Security Architecture

### 16.1 Layers

1. **Transport**: CORS middleware (configurable origins)
2. **Authentication**: JWT / API Key / Session Cookie / OAuth
3. **Authorization**: Role-based (admin, user) + tool-level permissions on API keys
4. **Input validation**: JSON Schema validation on tool inputs
5. **Audit**: All tool executions logged to `tool_executions` table

### 16.2 API Key Permissions

API keys carry a `tool_patterns` field — a JSON array of glob patterns:

```json
["*"]                    // all tools
["yahoo_*", "fred_*"]    // specific providers
["calc_*"]               // calculators only
```

---

## 17. Client SDK

### 17.1 Design

Zero external dependencies (Python stdlib only: `urllib`, `json`, `threading`). Installable via `pip install .` from `clientsdk/`.

### 17.2 Components

| Class | Methods | Purpose |
|-------|:-------:|---------|
| `SajhaClient` | 25 | REST client for all API endpoints |
| `MCPClient` | 12 | MCP JSON-RPC 2.0 client |
| `MCPSSEClient` | — | SSE transport client |
| `A2AClient` | 6 | Agent-to-agent task client |

### 17.3 Auth Providers

4 auth provider classes: `NoAuth`, `ApiKeyAuth`, `JWTAuth`, `OAuthAuth`.

### 17.4 Exception Hierarchy

7 exception types for structured error handling.

---

## 18. Testing

120 tests in 4 modules, all passing:

| Module | Tests | Coverage |
|--------|:-----:|----------|
| `test_config.py` | 22 | YAML loading, env substitution, flattening |
| `test_auth.py` | 15 | Login, JWT, API key, bcrypt |
| `test_db.py` | 26 | Schema, CRUD, DAOs, seed data |
| `test_endpoints.py` | 57 | Route responses, auth gates, MCP protocol |

---

## 19. Deployment

### 19.1 Development

```bash
pip install -r requirements.txt
python run_server.py        # Uvicorn on 0.0.0.0:3002
```

### 19.2 Production

```bash
uvicorn sajha.app:create_app --host 0.0.0.0 --port 3002 --workers 4
```

Or use the factory: `uvicorn sajha.app:create_app --factory`.

### 19.3 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SERVER_HOST` | `0.0.0.0` | Bind address |
| `SERVER_PORT` | `3002` | Port |
| `JWT_SECRET` | (change me) | JWT signing key |
| `DB_POOL_SIZE` | `10` | Connection pool |
| `FMP_API_KEY` | — | Financial Modeling Prep |
| `FRED_API_KEY` | — | Federal Reserve |
| `GOOGLE_API_KEY` | — | Google Search |
| `TAVILY_API_KEY` | — | Tavily Search |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## 20. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| YAML only (no .properties) | Single config source, cleaner `${ENV:default}` syntax |
| No Alembic | SQL scripts with `IF NOT EXISTS` — simpler deployment |
| Direct bcrypt (not passlib) | passlib incompatible with bcrypt 4.x |
| Starlette 1.0 TemplateResponse | `request` as positional param (not in context dict) |
| MCP protocol 2025-11-25 | Latest — fully implemented including all Major and Minor changes |
| FMPGenericTool pattern | JSON-only tool creation — no Python needed for new endpoints |
| Zero-dep client SDK | stdlib only for maximum portability |
| Tool group = prefix before `_` | Simple, consistent, works for all 497 tools |
| No WebSocket (v2 had Socket.IO) | Replaced with SSE transport per MCP spec |

---

*SAJHA MCP Server v5.3.0 — Architecture Document*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
