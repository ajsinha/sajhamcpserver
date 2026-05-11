# SAJHA MCP Server

**Version 4.0.0** · FastAPI · Python 3.9+ · MCP Protocol 2025-06-18

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

---

## What is SAJHA?

SAJHA (Hindi: साझा — "shared, collaborative") MCP Server is a production-grade implementation of the [Model Context Protocol](https://modelcontextprotocol.io) built on FastAPI. It exposes **497 tools** across financial markets, government data, search, analytics, and enterprise integrations through a single, standards-compliant MCP interface.

The server ships with an embedded LLM gateway (6 providers), semantic tool discovery, composite tool orchestration, OpenTelemetry observability, multi-tenancy, a plugin system, three transport options (HTTP POST, SSE, WebSocket), a full web UI, and a zero-dependency Python client SDK.

---

## Quick Start

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver
pip install -r requirements.txt
python run_server.py
```

Server starts at **http://localhost:3002**. Login: `admin` / `admin123`.

---

## v4.0.0 Highlights

| Feature | Description |
|---------|-------------|
| **3 Transports** | HTTP POST `/mcp`, SSE `/mcp/sse`, WebSocket `/mcp/ws` — all using same MCPHandler |
| **LLM Gateway** | 6 providers (Anthropic, OpenAI, Bedrock, Together, Ollama, Azure) via official SDKs. Registry-based factory for custom providers |
| **Semantic Discovery** | Vector embeddings of 497 tool descriptions. NL intent → tool resolution with LLM parameter extraction |
| **Composite Tools** | Sibling (parallel) and Parent-Child (fan-out) patterns. Declarative DB definitions, dynamic schema building |
| **OpenTelemetry** | Per-tool p50/p95/p99 latency histograms, error spike alerting, health probes. Optional OTEL SDK export |
| **Tool Versioning** | v1/v2 side-by-side. Deprecation lifecycle: active → deprecated → sunset → retired. Contract testing |
| **Multi-Tenancy** | Tenant-isolated tool access, per-tenant quotas (daily/monthly), data isolation, API key pools |
| **Plugin System** | Standardized plugin.json manifest. Drop directory → discover → validate → load. Checksum verification |
| **19-Table DB** | users, roles, permissions, api_keys, sessions, audit, prompts, tags, llm_providers, llm_models, llm_usage, ai_prefs, composite_tools, composite_steps, a2a_tasks, tenants, tool_versions |
| **Client SDK** | SajhaClient (25 REST), MCPClient (12 MCP), MCPSSEClient (SSE), MCPWebSocketClient (WS), A2AClient (6 A2A) |

---

## Architecture

```
run_server.py → SajhaMCPServerWebApp
  ├── FastAPI app (CORS, static files, 14 route modules, 79+ endpoints)
  ├── Lifespan startup
  │     ├── init_db()              → 19 SQL tables (schema + seed)
  │     ├── init_storage()         → Local or S3 backend
  │     ├── ToolsRegistry          → 497 tools from JSON configs
  │     ├── CompositeToolEngine    → DB-defined composite tools
  │     ├── init_observability()   → MetricsCollector + HealthProbe + OTEL
  │     ├── init_tenant_manager()  → Multi-tenant isolation
  │     ├── PluginManager          → Discover + load plugins
  │     ├── init_gateway()         → LLM Gateway (6 providers from DB)
  │     ├── init_resolver()        → Semantic tool embeddings
  │     ├── MCPHandler             → 12 MCP methods, JSON-RPC 2.0
  │     └── HotReloadManager      → Watches config/ for changes
  └── Uvicorn (ASGI)
```

**Transports:**

| Transport | Endpoint | Direction | Best For |
|-----------|----------|-----------|----------|
| HTTP POST | `/mcp` | Request → Response | Automation, CI/CD, simple calls |
| SSE | `/mcp/sse` | Server → Client push | Long-running tools, web UI |
| WebSocket | `/mcp/ws` | Full duplex | Interactive agents, real-time |

**Config:** `config/application.yml` — single source, `${ENV_VAR:default}` substitution.

**Database:** SQLite default (`data/sajha.db`), PostgreSQL via `db.type: postgresql`.

**Auth:** Cookie JWT (web UI) · Bearer JWT (API) · X-API-Key (automation) · OAuth (Azure AD, Okta, Auth0, Keycloak).

---

## Web UI Screens

| Screen | Path | Purpose |
|--------|------|---------|
| Dashboard | `/` | Summary cards, charts, activity feed |
| Tools | `/tools` | Browse, search, test 497 tools |
| AI Settings | `/ai/settings` | LLM providers, models, preferences, semantic search |
| Composite Builder | `/composite/builder` | Visual multi-tool orchestration |
| MCP Studio | `/studio` | 7 visual tool creators |
| Reports | `/reports` | 6 Chart.js reports + CSV export |
| Prompts | `/prompts` | Template management with tags |
| Admin | `/admin` | Users, roles, API keys, tools |

---

## Tool Categories

| Category | Sources | Count |
|----------|---------|------:|
| Equities & Fundamentals | FMP, Yahoo Finance, Alpha Vantage, OpenBB | ~240 |
| Central Banks | FRED, ECB, BoC, BoJ, PBoC, RBI, BdF, IMF | ~80 |
| Crypto & Forex | CoinGecko, FMP, OpenBB | ~25 |
| Regulatory | SEC EDGAR, OpenBB SEC | ~20 |
| Analytics & Calculators | DuckDB OLAP, 19 financial calculators | ~40 |
| Search & Research | Tavily, Google, Wikipedia, Web Crawler | ~15 |
| Enterprise | PowerBI, OpenText LiveLink, SharePoint | ~10 |

---

## Client SDK

Zero-dependency Python SDK (stdlib only). Install: `pip install sajhaclient`

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_key"))
result = client.execute_tool("yahoo_quote", symbol="AAPL")
```

Four client classes: `SajhaClient` (REST), `MCPClient` (JSON-RPC), `MCPSSEClient` (SSE), `MCPWebSocketClient` (WebSocket), `A2AClient` (agent-to-agent).

---

## Deployment

| Environment | Method |
|-------------|--------|
| **Local dev** | `python run_server.py` |
| **Docker** | `docker compose up` (see `deployment/aws/docker-compose.yml`) |
| **AWS ECS** | CDK in `deployment/aws/cdk/` (VPC + ALB + RDS + S3 + Secrets Manager) |
| **Hetzner** | Docker + Caddy auto-SSL (see `deployment/hetzner/`) |
| **On-prem** | Nginx + systemd (see `deployment/baremetal/`) |

Storage + Reload abstractions ensure identical behavior: `SAJHA_STORAGE_BACKEND=local` for dev, `=s3` for cloud.

---

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
