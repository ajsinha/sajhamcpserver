# SAJHA MCP Server

**Version 5.0.0** · FastAPI · Python 3.9+ · **MCP Protocol 2025-11-25** (latest)

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

---

## What is SAJHA?

SAJHA (Hindi: साझा — "shared, collaborative") is a production-grade [Model Context Protocol](https://modelcontextprotocol.io) server built on FastAPI. It is **fully compliant with MCP specification 2025-11-25** — the latest protocol version — including Tasks, Elicitation, Sampling with tool calling, tool icons, and all authorization enhancements.

The server exposes **497 tools** across financial markets, government data, search, analytics, and enterprise integrations through three MCP transports (HTTP POST, SSE, WebSocket), a REST API, and an A2A agent protocol.

---

## MCP 2025-11-25 Compliance

SAJHA implements all 9 major and 10 minor changes from the [2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25):

| Feature | SEP | Status |
|---------|-----|:------:|
| **Tasks** — async tracking for long-running requests | SEP-1686 | ✅ |
| **Elicitation** — server-initiated user input (form + URL modes) | SEP-1330, SEP-1036 | ✅ |
| **Sampling with Tools** — server-initiated LLM calls with tool use | SEP-1577 | ✅ |
| **Tool Icons** — icon metadata for tools, resources, prompts | SEP-973 | ✅ |
| **OAuth CIMD** — Client ID Metadata Documents | SEP-991 | ✅ |
| **OIDC Discovery** — `/.well-known/openid-configuration` | PR #797 | ✅ |
| **Incremental Scope** — `WWW-Authenticate` with scope parameter | SEP-835 | ✅ |
| **Tool Name Guidance** — provider_action naming convention | SEP-986 | ✅ |
| **RFC 9728 PRM** — `/.well-known/oauth-protected-resource` | SEP-985 | ✅ |
| **Origin Validation** — HTTP 403 for invalid Origin in SSE | PR #1439 | ✅ |
| **Tool Execution Errors** — `isError: true` (not protocol errors) | SEP-1303 | ✅ |
| **SSE Event IDs** — stream resumption via `Last-Event-ID` | SEP-1699 | ✅ |
| **JSON Schema 2020-12** — declared as default dialect | SEP-1613 | ✅ |

**Protocol version declared:** `2025-11-25` in `initialize` response.

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

## Feature Overview

| Category | Details |
|----------|---------|
| **MCP Protocol** | 2025-11-25 (latest). 15 MCP methods: initialize, tools/list, tools/call, tasks/get, tasks/list, tasks/cancel, elicitation/respond, notifications/cancelled, resources/list, resources/read, prompts/list, prompts/get, completion/complete, logging/setLevel, ping |
| **Transports** | HTTP POST `/mcp` (stateless) · SSE `/mcp/sse` (server-push with event IDs) · WebSocket `/mcp/ws` (full-duplex) |
| **Tools** | 497 built-in: FMP (100), OpenBB (70), FRED (55), Alpha Vantage (35), Yahoo Finance (35), CoinGecko (25), EDGAR (20), Calculators (19), World Bank (10), and more |
| **Composition** | Composite tools with Kleisli arrows (StepResult envelope), ParamLens (surgical param projection), EntropyGuard (cumulative confidence tracking with parallel-aware model) |
| **LLM Gateway** | 6 providers: Anthropic, OpenAI, AWS Bedrock, Together.ai, Ollama, Azure OpenAI. DB-managed models. Semantic tool discovery via embeddings |
| **Auth** | Cookie JWT (web UI) · Bearer JWT (API) · API Key (automation) · OAuth SSO (Azure AD, Okta, Auth0, Keycloak) · OIDC Discovery · CIMD |
| **Observability** | OpenTelemetry: per-tool p50/p95/p99 latency, error alerting, /health + /ready probes. Optional export to Datadog, Grafana, Splunk |
| **Multi-Tenancy** | Tenant-isolated tools with fnmatch wildcards, per-tenant quotas (daily/monthly), data isolation |
| **Plugins** | Drop directory + plugin.json manifest → discover → validate (SHA-256) → load. Hot-reload |
| **Tool Versioning** | v1/v2 side-by-side. Lifecycle: active → deprecated → sunset → retired. Contract testing |
| **UI** | 4 themes (Light, Dark, Wall Street, Ubuntu). 42 screens. Custom SVG icon set. Full A11y (WCAG AA) |
| **Client SDK** | Zero-dependency Python: SajhaClient, MCPClient, MCPSSEClient, MCPWebSocketClient, A2AClient. TransportCoalgebra + bisimilar() + ClientPipeline |
| **Configuration** | Single `config/application.yml` with `${ENV_VAR:default}` substitution |
| **Database** | SQLite default, PostgreSQL ready. 19 tables. Two SQL scripts only (schema + seed) |
| **Deployment** | AWS CDK (ECS Fargate) · Hetzner (Docker + Caddy) · Bare metal (systemd + Nginx) |

---

## Architecture

```
run_server.py → SajhaMCPServerWebApp (FastAPI)
  ├── 14 route modules, 79+ REST endpoints
  ├── MCPHandler (MCP 2025-11-25, 15 methods)
  │     ├── TaskManager        → async task tracking
  │     ├── ElicitationManager → form + URL user input
  │     └── SamplingManager    → LLM calls with tools
  ├── ToolsRegistry (497 tools from JSON configs)
  ├── CompositeToolEngine + Composition Framework
  │     ├── StepResult (Kleisli envelope)
  │     ├── ParamLens (parameter projection)
  │     └── EntropyGuard (confidence tracking)
  ├── LLM Gateway (6 providers, DB-managed)
  ├── OpenTelemetry (metrics, alerts, health)
  ├── TenantManager (multi-tenant isolation)
  ├── PluginManager (discover → validate → load)
  └── OAuth Discovery
        ├── /.well-known/openid-configuration
        ├── /.well-known/oauth-protected-resource
        └── /.well-known/oauth-client/{id}
```

**Composition Framework** (from "On the Composability of Intelligence"):

```
Pillar 1 (Kleisli):   StepResult — error short-circuit, trace accumulation, confidence
Pillar 2 (Coalgebra): TransportCoalgebra — step() interface, bisimilar() testing
Pillar 3 (Lenses):    ParamLens — $.field / $input.field projection
Pillar 4 (Giry):      EntropyGuard — sequential multiply, parallel min (weakest-link)
```

---

## Client SDK

Zero-dependency Python (stdlib only). `pip install sajhaclient`

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth, ClientPipeline

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_key"))

# Simple tool call
result = client.execute_tool("yahoo_quote", symbol="AAPL")

# MCP client (protocol version 2025-11-25)
from sajhaclient import MCPClient
mcp = MCPClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_key"))
caps = mcp.initialize()  # Negotiates 2025-11-25
tools = mcp.list_tools()
result = mcp.call_tool("fred_gdp")

# Client-side pipeline with confidence tracking
pipeline = ClientPipeline(client)
pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})
result = pipeline.execute({"ticker": "AAPL"})
print(result['_composition']['confidence'])  # 0.85

# Transport equivalence testing
from sajhaclient import HTTPTransport, WSTransport, bisimilar
assert bisimilar(HTTPTransport(config, auth), WSTransport(config, auth),
    [('initialize', None), ('tools/list', None)])['passed']
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](docs/API_Reference.md) | 79+ endpoints with curl examples |
| [Composition Framework](docs/Composition_Framework.md) | Kleisli, Lenses, EntropyGuard deep-dive |
| [Architecture](docs/architecture/SAJHA_MCP_Server_Architecture.md) | Full system architecture |
| [Glossary](docs/architecture/Glossary.md) | 30+ terms defined |
| [UX Audit](docs/UX_Audit_Report.md) | 22 recommendations (all implemented) |
| [SDK User Guide](clientsdk/docs/USER_GUIDE.md) | Complete client SDK reference |
| [Changelog](CHANGELOG.md) | v3.1.0 → v4.0.0 → v4.5.0 → v5.0.0 |
| [Deployment](deployment/README.md) | AWS CDK, Hetzner, Bare Metal guides |

47 markdown files, 45,000+ lines of documentation.

---

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
