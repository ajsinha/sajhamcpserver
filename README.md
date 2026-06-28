# SAJHA MCP Server

**Version 5.2.0** · FastAPI · Python 3.9+ · **MCP Protocol 2025-11-25** (latest)

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

**Command-line options:**

```bash
python run_server.py                              # Default config
python run_server.py --config /path/to/custom.yml # Custom config file
python run_server.py --host 0.0.0.0 --port 8080   # Custom host/port
python run_server.py --reload                      # Dev mode (auto-reload)
python run_server.py --log-level DEBUG             # Verbose logging
```

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
| **Caching** | Per-tool output cache with configurable TTL. FRED: 1hr, FMP: 5min, Yahoo: 30s. LRU eviction. Cache stats API |
| **Circuit Breakers** | Per-provider circuit breakers: CLOSED → OPEN (5 failures) → HALF_OPEN (probe). Prevents cascading failures |
| **Webhooks** | Subscribe to events (tool.completed, task.failed, circuit.opened). Async delivery with retry + exponential backoff |
| **Tool Health** | Dependency graph (497 tools → 16 providers → APIs). Per-provider health status with circuit breaker state |
| **Execution Replay** | Last 20 executions per tool stored with arguments, result preview, timing. Recent executions API |
| **Audit Log** | Structured security events: login, logout, user/key CRUD, permission changes. DB-persisted, queryable API |
| **Shell Tools** | Sandboxed Python + Bash execution for AI agents. Allowlisted imports/commands. Memory/time limits. Every execution audit-logged. Disabled by default — explicit config opt-in |
| **Async Execution** | Submit tools for background execution. Bounded worker pool (8 threads). Result delivery via webhook, Kafka, or filesystem. Task lifecycle: queued → running → completed → delivered. Backpressure with HTTP 503 |
| **Rate Limiting** | Auth: 5/min/IP. API: 100/min/user, 200/min/key. Account lockout after 5 failures (15 min) |
| **Observability** | OpenTelemetry: per-tool p50/p95/p99 latency, error alerting, /health + /ready probes. Optional export to Datadog, Grafana, Splunk |
| **Multi-Tenancy** | Tenant-isolated tools with fnmatch wildcards, per-tenant quotas (daily/monthly), data isolation |
| **Plugins** | Drop directory + plugin.json manifest → discover → validate (SHA-256) → load. Hot-reload |
| **Tool Versioning** | v1/v2 side-by-side. Lifecycle: active → deprecated → sunset → retired. Contract testing |
| **UI** | 4 themes (Light, Dark, Wall Street, Ubuntu). 42 screens. Custom SVG icon set. Full A11y (WCAG AA) |
| **Client SDK** | Zero-dependency Python: SajhaClient, MCPClient, MCPSSEClient, MCPWebSocketClient, A2AClient. TransportCoalgebra + bisimilar() + ClientPipeline |
| **Configuration** | YAML-only: `config/application.yml` with `${ENV_VAR:default}` substitution. Overridable via `--config` CLI or `SAJHA_CONFIG_FILE` env var. PropertiesConfigurator with native YAML support |
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
| [Changelog](CHANGELOG.md) | v3.1.0 → v4.0.0 → v4.5.0 → v5.2.0 |
| [Deployment](deployment/README.md) | AWS CDK, Hetzner, Bare Metal guides |

50 markdown files, 45,000+ lines of documentation.

---

## Why SAJHA

| # | Capability | FastMCP | TS SDK | Others | **SAJHA** |
|:-:|-----------|:-------:|:------:|:------:|:---------:|
| | **DESIGN & CREATION** | | | | |
| 1 | Visual Tool Designer (MCP Studio) | ❌ | ❌ | ❌ | **✅ 9 creator types** |
| 2 | Composite Tool Builder (visual flow) | ❌ | ❌ | ❌ | **✅ drag-drop + confidence** |
| | **AI & INTELLIGENCE** | | | | |
| 3 | Built-in LLM Gateway | ❌ | ❌ | ❌ | **✅ 6 providers, DB-managed** |
| 4 | Semantic Tool Discovery | ❌ | ❌ | ❌ | **✅ vector embeddings** |
| 5 | Composition with Confidence | ❌ | ❌ | ❌ | **✅ EntropyGuard + ParamLens** |
| | **EXECUTION** | | | | |
| 6 | Async execution + delivery | ❌ | ❌ | ❌ | **✅ webhook / Kafka / file** |
| 7 | Sandboxed shell tools | ❌ | ❌ | ❌ | **✅ Python + Bash sandbox** |
| 8 | Tool output caching | ❌ | ❌ | ❌ | **✅ file-based, per-tool TTL** |
| 9 | Circuit breakers | ❌ | ❌ | ❌ | **✅ 16 providers monitored** |
| | **ENTERPRISE** | | | | |
| 10 | Multi-tenancy | ❌ | ❌ | ❌ | **✅ tenant isolation + quotas** |
| 11 | Plugin system | ❌ | ❌ | ❌ | **✅ discover → validate → load** |
| 12 | Tool versioning + contracts | ❌ | ❌ | ❌ | **✅ v1/v2 side-by-side** |
| 13 | OpenTelemetry observability | ❌ | ❌ | Some | **✅ p50/p95/p99 + alerting** |
| | **PLATFORM** | | | | |
| 14 | MCP 2025-11-25 compliance | Partial | Partial | Varies | **✅ Full (18/18)** |
| 15 | Built-in tools | 0 | 0 | 1–20 | **497** |
| 16 | Web UI (4 themes) | ❌ | ❌ | Some | **✅ 42+ screens** |
| 17 | Client SDK + transport coalgebra | — | — | — | **✅ 5 clients + pipelines** |
| 18 | Cybersecurity (OWASP aligned) | Basic | Basic | Varies | **✅ 42 controls** |

**SAJHA has 18 competitive advantages. No other MCP server has more than 2 of these.**

### MCP Studio — Visual Tool Designer

No other MCP server provides a visual tool creation platform. MCP Studio lets users create tools without writing JSON configs manually:

| Creator Type | What It Creates | How |
|-------------|----------------|-----|
| **Python** | Custom Python function tool | Write function → auto-generate schema → test → save |
| **REST** | REST API wrapper tool | Enter URL + method + params → test endpoint → save |
| **DB Query** | Database query tool | Write SQL → bind params → preview results → save |
| **Script** | Shell script tool | Upload/write script → define args → save |
| **PowerBI** | PowerBI report tool | Connect workspace → select report → save |
| **PowerBI DAX** | DAX query tool | Write DAX → bind params → save |
| **LiveLink** | OpenText LiveLink tool | Configure server → select operation → save |
| **SharePoint** | SharePoint connector | Configure site → select list/library → save |
| **OLAP** | DuckDB analytics tool | Write query → bind params → save |

### Composite Tool Builder — Visual Pipeline Designer

The only MCP server where you can visually design tool pipelines with mathematical confidence guarantees:

1. **Choose arrangement** — Sibling (parallel) or Parent-Child (fan-out)
2. **Set master tool** — the tool that runs first
3. **Add steps** — drag-and-drop ordering, param mapping (`$.field` / `$input.field`)
4. **Live flow diagram** — SVG visualization updates as you add steps
5. **Preview schemas** — auto-generated input/output schemas
6. **Confidence preview** — estimated pipeline confidence from EntropyGuard
7. **Save** — registered as MCP tool immediately, available on all transports

No code. No JSON editing. No restart. The composite is live in seconds.

### AI/LLM Gateway — Embedded Intelligence

SAJHA is the only MCP server with a built-in LLM gateway. Six providers via official SDKs, all managed through the web UI:

| Provider | SDK | Models |
|----------|-----|--------|
| **Anthropic** | anthropic | Claude Opus, Sonnet, Haiku |
| **OpenAI** | openai | GPT-4o, GPT-4, GPT-3.5 |
| **AWS Bedrock** | boto3 | Claude, Titan, Llama |
| **Together.ai** | together | Mixtral, Llama, CodeLlama |
| **Ollama** | HTTP | Any local model |
| **Azure OpenAI** | openai | GPT-4, GPT-3.5 (Azure-hosted) |

Providers and models managed via DB tables — add, test, enable/disable from the UI. Three-tier model resolution: explicit params → user preferences → system defaults. Registry-based factory supports custom provider classes.

### Semantic Tool Discovery

Type what you need in plain English. SAJHA finds the best matching tools:

```
"find companies with high debt ratios"
  → fmp_key_metrics (0.89)
  → fmp_financial_ratios (0.85)
  → fmp_balance_sheet (0.82)
```

497 tool descriptions embedded as vectors. Cosine similarity search. No need to know exact tool names. Available via API (`POST /api/ai/resolve-tool`) and the web UI (AI → Semantic Search).

### Enterprise Features

| Feature | Description |
|---------|-------------|
| **Multi-Tenancy** | Per-tenant tool access via fnmatch wildcards + blocked lists. Daily/monthly call quotas. Isolated data directories. API: `POST /api/tenants` |
| **Plugin System** | Drop a directory in `config/plugins/` with `plugin.json` manifest. Auto-discovered, SHA-256 validated, dependencies installed, tools registered. Hot-reload. |
| **Tool Versioning** | Run v1 and v2 side-by-side. Deprecation lifecycle: active → deprecated → sunset → retired. Contract testing validates all tools: `POST /api/contract-test` |
| **OpenTelemetry** | Per-tool p50/p95/p99 latency histograms. Error spike alerting (>10/5min). Health probes (`/health`, `/ready`). Optional export to Datadog, Grafana, Splunk, Jaeger |

---

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
