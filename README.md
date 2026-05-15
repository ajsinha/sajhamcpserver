# SAJHA MCP Server

**Version 5.0.0** · FastAPI · Python 3.9+ · MCP Protocol 2025-06-18

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

---

## What is SAJHA?

SAJHA (Hindi: साझा — "shared, collaborative") MCP Server is a production-grade implementation of the [Model Context Protocol](https://modelcontextprotocol.io) built on FastAPI. It exposes **497 tools** across financial markets, government data, search, analytics, and enterprise integrations through a single, standards-compliant MCP interface.

The server ships with an embedded LLM gateway (6 providers), semantic tool discovery, composite tool orchestration with category-theory-inspired composition (Kleisli arrows, entropy guard, lens-based param projection), OpenTelemetry observability, multi-tenancy, a plugin system, three transport options (HTTP POST, SSE, WebSocket), a full web UI with 4 themes, and a zero-dependency Python client SDK with transport coalgebra and client-side pipelines.

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

## v5.0.0 Highlights

| Feature | Description |
|---------|-------------|
| **Composition Framework** | Category-theory-inspired tool composition: Kleisli arrows (StepResult envelope), ParamLens (surgical param projection), EntropyGuard (cumulative confidence tracking). [Architecture guide](docs/Composition_Framework.md) |
| **Parallel Confidence Model** | Sibling steps use weakest-link (min) instead of multiply. Parent-Child uses Giry bind (multiply). Mixed pipelines combine both correctly |
| **Tool Confidence Registry** | 497 tools classified by reliability: calculators 1.0, FRED 0.95, web crawlers 0.80. Composite results include `_composition.confidence` |
| **Transport Coalgebra** | Client SDK: `HTTPTransport`, `SSETransport`, `WSTransport` with shared `step()` interface. `bisimilar()` proves behavioral equivalence |
| **Client-Side Pipelines** | `ClientPipeline` builds tool chains client-side with param mapping and entropy tracking — no server composite needed |
| **4 UI Themes** | Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal), Ubuntu. Variable-driven CSS (545 lines, was 4,441) |
| **UX Overhaul** | Active nav highlighting, button press feedback, loading skeletons, keyboard shortcuts, onboarding wizard, empty state CTAs, studio sub-nav, visual flow diagram in composite builder |
| **Full A11y** | Skip-to-content, focus-visible outlines, ARIA labels, color-scheme per theme, WCAG AA contrast |
| **3 Transports** | HTTP POST `/mcp`, SSE `/mcp/sse`, WebSocket `/mcp/ws` — all using same MCPHandler |
| **LLM Gateway** | 6 providers (Anthropic, OpenAI, Bedrock, Together, Ollama, Azure) via official SDKs |
| **OpenTelemetry** | Per-tool p50/p95/p99 latency histograms, error spike alerting, health probes |
| **Multi-Tenancy** | Tenant-isolated tools, per-tenant quotas, data isolation |
| **Plugin System** | Standardized plugin.json manifest. Drop directory → discover → validate → load |
| **19-Table DB** | Two SQL scripts only (schema + seed). No migrations. SQLite default, PostgreSQL ready |
| **Property-Driven** | Single `config/application.yml` drives version, email, paths, DB, logging — ${ENV_VAR} substitution |
| **Client SDK** | 5 client classes: SajhaClient (REST), MCPClient (MCP), MCPSSEClient (SSE), MCPWebSocketClient (WS), A2AClient (A2A) + TransportCoalgebra + ClientPipeline |

---

## Architecture

```
run_server.py → SajhaMCPServerWebApp
  ├── FastAPI app (CORS, static, 14 route modules, 79+ endpoints)
  ├── Lifespan startup
  │     ├── init_db()              → 19 SQL tables
  │     ├── init_storage()         → Local or S3
  │     ├── ToolsRegistry          → 497 tools from JSON configs
  │     ├── CompositeToolEngine    → DB composites with composition framework
  │     ├── init_observability()   → MetricsCollector + HealthProbe + OTEL
  │     ├── init_tenant_manager()  → Multi-tenant isolation
  │     ├── PluginManager          → Discover + load plugins
  │     ├── init_gateway()         → LLM Gateway (6 providers from DB)
  │     ├── init_resolver()        → Semantic tool embeddings
  │     ├── MCPHandler             → 12 MCP methods, JSON-RPC 2.0
  │     └── HotReloadManager      → Watches config/ for changes
  └── Uvicorn (ASGI)
```

**Composition Framework** (from Category Theory):

```
Pillar 1 (Kleisli):  StepResult envelope — Dict → M[Dict]
                     Error short-circuits, traces accumulate, confidence compounds
Pillar 3 (Lenses):   ParamLens — surgical view/set projection
                     Child tools see ONLY mapped fields, nothing else
Pillar 4 (Giry):     EntropyGuard — cumulative entropy tracking
                     Sequential: multiply (Giry bind)
                     Parallel: min (weakest link)
                     Mixed: master × min(siblings)
Pillar 2 (Coalgebra): TransportCoalgebra in client SDK
                     step(input) → (output, new_state)
                     bisimilar() proves transport equivalence
```

**Transports:**

| Transport | Endpoint | Direction | Best For |
|-----------|----------|-----------|----------|
| HTTP POST | `/mcp` | Request → Response | Automation, CI/CD, simple calls |
| SSE | `/mcp/sse` | Server → Client push | Long-running tools, web UI |
| WebSocket | `/mcp/ws` | Full duplex | Interactive agents, real-time |

**Config:** `config/application.yml` — single source, `${ENV_VAR:default}` substitution.

**Database:** SQLite default (`data/sajha.db`), PostgreSQL via `db.type: postgresql`. Two SQL scripts only.

**Auth:** Cookie JWT (web UI) · Bearer JWT (API) · X-API-Key (automation) · OAuth (Azure AD, Okta, Auth0, Keycloak).

**Deployment:** [AWS CDK](deployment/aws/) · [Hetzner Docker](deployment/hetzner/) · [Bare Metal](deployment/baremetal/)

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
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth, ClientPipeline

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_key"))

# Simple tool call
result = client.execute_tool("yahoo_quote", symbol="AAPL")

# Client-side pipeline with confidence tracking
pipeline = ClientPipeline(client)
pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})
result = pipeline.execute({"ticker": "AAPL"})
print(result['_composition']['confidence'])  # 0.85
```

---

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
