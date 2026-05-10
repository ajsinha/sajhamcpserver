# SAJHA MCP Server

**Version 3.1.0** · FastAPI · Python 3.9+ · MCP Protocol 2025-06-18

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

---

## What is SAJHA?

SAJHA (Hindi: साझा — "shared, collaborative") MCP Server is a production-grade implementation of the [Model Context Protocol](https://modelcontextprotocol.io) built on FastAPI. It exposes **497 tools** across financial markets, government data, search, analytics, and enterprise integrations through a single, standards-compliant MCP interface.

The server ships with a full web UI, role-based access control, an MCP Studio visual tool creator, live reporting dashboards, and a zero-dependency Python client SDK — everything needed to run a secure, multi-user MCP server from a single `python run_server.py` command.

---

## Quick Start

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver
pip install -r requirements.txt
python run_server.py
```

The server starts at **http://localhost:3002**. Log in with `admin` / `admin123`.

---

## Architecture at a Glance

```
run_server.py → SajhaMCPServerWebApp
  ├── FastAPI app (CORS, static files, 13 route modules)
  ├── Lifespan startup
  │     ├── init_db()          → SQL scripts (schema + seed)
  │     ├── run_legacy_import() → users.json, apikeys.json
  │     ├── PropertiesConfigurator (YAML → ${var} resolution)
  │     ├── ToolsRegistry      → 501 JSON configs → 497 live tools
  │     ├── PromptsRegistry    → prompt catalog
  │     ├── MCPHandler         → 12 MCP methods, JSON-RPC 2.0
  │     └── HotReloadManager   → watches config/ for changes
  └── Uvicorn (ASGI)
```

**Config:** `config/application.yml` — single source, `${ENV_VAR:default}` substitution, `SAJHA_` env prefix override.

**Database:** SQLite by default (`data/sajha.db`), PostgreSQL supported via `db.type: postgresql`.

**Auth:** Cookie JWT (web UI) · Bearer JWT (API) · X-API-Key (automation) · OAuth optional (Azure AD, Okta, Auth0, Keycloak).

---

## MCP Protocol Compliance

Fully compliant with MCP specification version **2025-06-18**. Twelve JSON-RPC 2.0 methods:

| Method | Description |
|--------|-------------|
| `initialize` | Handshake — declares 5 capabilities |
| `ping` | Health check |
| `tools/list` | Paginated tool catalog (100/page) |
| `tools/call` | Execute any registered tool |
| `prompts/list` | List prompt templates |
| `prompts/get` | Retrieve prompt with argument substitution |
| `resources/list` | Paginated resource catalog (50/page) |
| `resources/read` | Read tool catalog, prompt catalog, data files |
| `resources/templates/list` | 2 URI templates |
| `resources/subscribe` / `unsubscribe` | Resource change notifications |
| `completion/complete` | Auto-suggest from enum values in tool schemas |
| `logging/setLevel` | Dynamically adjust server log level |

**Transports:** HTTP POST (`/mcp`) and SSE (`/mcp/sse` + `/mcp/message`).

**5 Capabilities:** `tools` (listChanged), `prompts` (listChanged), `resources` (subscribe, listChanged), `logging`, `completions`.

---

## A2A Protocol

Agent-to-Agent protocol support for multi-agent orchestration:

- **Agent card:** `GET /.well-known/agent.json` (auto-generated from tool registry)
- **Task lifecycle:** `tasks/send`, `tasks/get`, `tasks/cancel` via `POST /a2a`

---

## Tool Inventory (497 Tools)

| Provider | Count | API Key Required | Source |
|----------|------:|:----------------:|--------|
| FMP (Financial Modeling Prep) | 100 | Yes | 30 named + FMPGenericTool auto-mapping |
| OpenBB | 70 | No (SDK) | 25 named + OpenBBGenericTool auto-mapping |
| FRED (Federal Reserve) | 55 | Yes | 30 named + FREDCustomSeriesTool |
| Yahoo Finance | 35 | No | yfinance_tools.py |
| Alpha Vantage | 35 | Yes | alphavantage_tools.py |
| CoinGecko | 25 | No | coingecko_tools.py |
| SEC / EDGAR | 20 | No | enhanced_edgar_tool.py |
| Financial Calculators | 19 | No | calc_tools.py (pure math) |
| World Bank | 10 | No | v2 module |
| IMF, ECB, Fed, BoC, RBI, BoJ, PBoC, BdF | ~40 | No | Central bank modules |
| Wikipedia, Google, Tavily, Web Crawler | ~15 | Varies | Search/knowledge modules |
| DuckDB, SQL Select, OLAP | ~15 | No | Analytics modules |
| Investor Relations, MS Docs | ~10 | No | Enterprise modules |
| **Total** | **497** | | |

**Generic tool pattern:** `FMPGenericTool` and `OpenBBGenericTool` auto-map tool names to API endpoints from JSON configs. Adding a new tool requires only a JSON file in `config/tools/` — no Python code needed.

---

## Configuration

All configuration lives in `config/application.yml`:

```yaml
server:
  host: ${SERVER_HOST:0.0.0.0}
  port: ${SERVER_PORT:3002}

db:
  type: sqlite                    # sqlite | postgresql
  path: data/sajha.db

auth:
  jwt:
    secret: ${JWT_SECRET:change-me}
    algorithm: HS256
    expiry_minutes: 60

fmp:
  api:
    key: ${FMP_API_KEY:}
fred:
  api:
    key: ${FRED_API_KEY:}
```

Override any key via environment variable with `SAJHA_` prefix: `SAJHA_DB_TYPE=postgresql`.

---

## Authentication

| Method | Use Case | Header/Cookie |
|--------|----------|---------------|
| Session cookie | Web UI login | `sajha_token` cookie |
| Bearer JWT | API access | `Authorization: Bearer <token>` |
| API Key | Automation, scripts | `X-API-Key: <key>` |
| OAuth | Enterprise SSO | Azure AD / Okta / Auth0 / Keycloak |

API keys support granular tool permissions with wildcard patterns: `["yahoo_*", "fred_*"]`.

---

## Web Interface

The server includes a full web UI at `http://localhost:3002`:

- **Dashboard** — tool count, error summary, provider group badges with click-to-filter
- **Tools List** — searchable, filterable table of all 497 tools with group dropdown and description search
- **Tool Execute** — interactive testing with schema-aware forms
- **Prompts** — full CRUD with category/tag organization and test interface
- **MCP Studio** — visual tool creator (7 creator types)
- **Reports** — Chart.js dashboards for usage, activity heatmaps, audit logs
- **Monitoring** — tool metrics and user activity
- **Admin** — user management, tool enable/disable, API key management
- **Docs** — live markdown viewer for all project documentation
- **Light/dark theme** toggle

---

## MCP Studio

Visual tool creation platform with seven creator types:

| Creator | Input | Output |
|---------|-------|--------|
| **Python Code** | `@sajhamcptool` decorated function | JSON config + BaseMCPTool class |
| **REST Service** | URL, method, auth, schemas | HTTP client tool |
| **DB Query** | SQL template + parameters | DuckDB/SQLite/PostgreSQL/MySQL tool |
| **Script** | Bash/Python/Node.js/Ruby/Perl | Script execution tool |
| **PowerBI Report** | Workspace + Report IDs | PDF/PPTX/PNG export tool |
| **PowerBI DAX** | EVALUATE statement + params | DAX query tool |
| **LiveLink** | Server URL + auth | OpenText ECM document tool |

All creators generate both the JSON config and Python implementation, with immediate hot-reload deployment.

---

## Client SDK

Zero-dependency Python client (stdlib only — `urllib`, `json`, `threading`):

```bash
cd clientsdk && pip install .
```

```python
from sajhaclient import SajhaConfig, SajhaClient, ApiKeyAuth

config = SajhaConfig(base_url="http://localhost:3002")
client = SajhaClient(config, auth=ApiKeyAuth("sk_live_..."))

tools = client.list_tools()
result = client.execute_tool("yahoo_finance_quote", {"symbol": "AAPL"})
```

Full documentation: `clientsdk/docs/USER_GUIDE.md` (607 lines).

---

## Database

9 tables managed via SQL scripts (no ORM migrations):

| Table | Purpose |
|-------|---------|
| `users` | User accounts with bcrypt password hashes |
| `roles` | Role definitions |
| `permissions` | Permission entries |
| `user_roles` | User ↔ role mapping |
| `role_permissions` | Role ↔ permission mapping |
| `api_keys` | API key records with tool permission patterns |
| `tool_executions` | Execution audit log |
| `tool_errors` | Error tracking |
| `sessions` | Active session management |

Schema: `db/scripts/001_schema.sql` · Seed: `db/scripts/002_seed.sql`

---

## Testing

```bash
python -m pytest tests/ -v
```

120 tests across 4 modules: config (22), auth (15), database (26), endpoints (57).

---

## Project Structure

```
sajha-v3/
├── run_server.py                 # Entry point
├── config/
│   ├── application.yml           # All configuration
│   ├── tools/                    # 501 tool JSON configs
│   ├── prompts/                  # Prompt templates
│   ├── users.json                # Legacy user data
│   └── apikeys.json              # Legacy API keys
├── db/scripts/
│   ├── 001_schema.sql            # 9 tables + indexes
│   └── 002_seed.sql              # Default roles, permissions, admin
├── sajha/
│   ├── app.py                    # FastAPI orchestrator
│   ├── core/                     # Config, MCP handler, hot-reload
│   ├── auth/                     # AuthManager, bcrypt, JWT
│   ├── db/                       # Engine, 8 ORM models, 7 DAOs
│   ├── routes/                   # 13 route modules (79+ endpoints)
│   ├── tools/                    # Base class, registry, 15+ impl files
│   └── web/                      # 39 templates, static assets
├── clientsdk/                    # Zero-dep Python client
├── tests/                        # 120 tests
└── docs/                         # Architecture, API ref, user guides
```

---

## Known Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| 3 SharePoint tools fail to load | Low | Abstract class — `get_input_schema`/`get_output_schema` not implemented |
| Missing sqlselect CSV data files | Low | Referenced in tool configs but absent in fresh install |
| Dashboard description escaping | Low | Some tool descriptions with special chars; `|tojson` fix applied to tools_list but not dashboard |

---

## License

Proprietary. Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
