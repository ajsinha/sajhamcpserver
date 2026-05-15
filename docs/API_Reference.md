# SAJHA MCP Server v5.0.0 — API Reference

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## Authentication

All API endpoints require authentication. Three methods supported:

```bash
# Method 1: API Key (recommended for automation)
curl -H "X-API-Key: sja_your_key_here" http://localhost:3002/api/tools

# Method 2: Bearer JWT
TOKEN=$(curl -s -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"admin","password":"admin123"}' | jq -r '.token')
curl -H "Authorization: Bearer $TOKEN" http://localhost:3002/api/tools

# Method 3: Session cookie (web UI — automatic)
```

### POST /api/auth/login

```bash
curl -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"admin","password":"admin123"}'
```

Response:
```json
{"token": "eyJhbGciOiJIUzI1NiJ9...", "expires_in": 3600, "user_id": "admin"}
```

---

## MCP Protocol (JSON-RPC 2.0)

### POST /mcp — Stateless HTTP

```bash
# Initialize
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"my-agent","version":"1.0"}},"id":1}'

# Call a tool
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"yahoo_quote","arguments":{"symbol":"AAPL"}},"id":2}'
```

### GET /mcp/sse — Server-Sent Events

```bash
curl -N -H "X-API-Key: sja_key" http://localhost:3002/mcp/sse
# Server sends: event: endpoint\ndata: /mcp/message?session=abc-123
# Then POST to: /mcp/message?session=abc-123
```

### WebSocket /mcp/ws — Full-Duplex

```python
import websockets, json, asyncio
async def main():
    async with websockets.connect("ws://localhost:3002/mcp/ws?token=JWT") as ws:
        await ws.send(json.dumps({"jsonrpc":"2.0","method":"tools/call","params":{"name":"yahoo_quote","arguments":{"symbol":"AAPL"}},"id":1}))
        print(await ws.recv())
asyncio.run(main())
```

### All 12 MCP Methods

| Method | Description |
|--------|-------------|
| `initialize` | Negotiate capabilities |
| `initialized` | Confirm init complete |
| `ping` | Health check |
| `tools/list` | List tools (100/page) |
| `tools/call` | Execute tool |
| `resources/list` | List resources |
| `resources/read` | Read resource by URI |
| `prompts/list` | List prompts |
| `prompts/get` | Get prompt with vars |
| `completion/complete` | Auto-complete args |
| `logging/setLevel` | Set log level |
| `notifications/cancelled` | Cancel request |

---

## REST API — Tools

### GET /api/tools/{name}/schema

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/tools/yahoo_quote/schema
```

Response:
```json
{
  "name": "yahoo_quote",
  "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}
}
```

### POST /api/tools/{name}/execute

```bash
curl -X POST http://localhost:3002/api/tools/yahoo_quote/execute \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"symbol": "AAPL"}'
```

Response:
```json
{"success": true, "result": {"symbol": "AAPL", "price": 198.42, "change": 2.35}, "execution_time": 0.23}
```

---

## REST API — Composite Tools

### POST /api/composite-tools

```bash
curl -X POST http://localhost:3002/api/composite-tools \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"name":"market_snapshot","arrangement":"sibling","master_tool":"yahoo_quote","master_output_key":"quote","steps":[{"tool_name":"fred_vix","output_key":"vix","execution_mode":"parallel","param_mapping":{},"static_params":{}}]}'
```

### Composite Result with _composition Metadata

```json
{
  "quote": {"symbol": "AAPL", "price": 198.42},
  "vix": {"value": 18.5},
  "_composition": {
    "confidence": 0.85, "entropy_bits": 0.61, "duration_ms": 680.5,
    "steps_executed": 2, "steps_succeeded": 2,
    "trace": ["✓ yahoo_quote: 230ms", "✓ fred_vix: 180ms"],
    "guard_passed": true
  }
}
```

---

## REST API — AI Integration

### POST /api/ai/resolve-tool

```bash
curl -X POST http://localhost:3002/api/ai/resolve-tool \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"query": "find companies with high debt ratios", "top_k": 5}'
```

### POST /api/ai/complete

```bash
curl -X POST http://localhost:3002/api/ai/complete \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"prompt": "Explain the Sharpe Ratio", "max_tokens": 100}'
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai/providers` | GET | List providers with health |
| `/api/ai/providers/{type}/config` | POST | Update provider config |
| `/api/ai/models` | GET/POST | List/create models |
| `/api/ai/models/{id}` | PUT/DELETE | Update/delete model |
| `/api/ai/preferences` | GET/POST/DELETE | User preferences |
| `/api/ai/usage` | GET | Token usage stats |
| `/api/ai/registry` | GET | Registered provider classes |

---

## REST API — Observability

### GET /health

```bash
curl http://localhost:3002/health
# {"status": "ok"}
```

### GET /ready

```bash
curl http://localhost:3002/ready
# {"status": "ready", "checks": {"database": "ok", "tools": "ok", "tools_count": 497}}
```

### GET /api/metrics/tools/{name}

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/metrics/tools/yahoo_quote
```

```json
{"tool": "yahoo_quote", "call_count": 142, "error_count": 3, "latency": {"p50": 210, "p95": 450, "p99": 890}}
```

---

## REST API — Multi-Tenancy

### POST /api/tenants

```bash
curl -X POST http://localhost:3002/api/tenants \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"name":"research-team","tool_patterns":["fred_*","fmp_*","calc_*"],"max_calls_per_day":5000}'
```

---

## REST API — Plugins

```bash
# Discover new plugins
curl -X POST http://localhost:3002/api/plugins/discover -H "X-API-Key: sja_key"

# Load a plugin
curl -X POST http://localhost:3002/api/plugins/my-plugin/load -H "X-API-Key: sja_key"
```

---

## REST API — Entropy Guard

### POST /api/entropy/pipeline

```bash
curl -X POST http://localhost:3002/api/entropy/pipeline \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"tools": ["yahoo_quote", "calc_risk", "fmp_profile"], "threshold": 2.0}'
```

```json
{
  "passed": true, "entropy_bits": 0.842, "cumulative_confidence": 0.812,
  "steps": [
    {"step": "yahoo_quote", "confidence": 0.92},
    {"step": "calc_risk", "confidence": 1.0},
    {"step": "fmp_profile", "confidence": 0.93}
  ]
}
```

---

## REST API — Admin & Reporting

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/users` | GET/POST | User CRUD |
| `/api/admin/apikeys` | GET/POST | API key management |
| `/api/admin/tools/{name}/enable` | POST | Enable tool |
| `/api/admin/tools/{name}/disable` | POST | Disable tool |
| `/api/reports/overview` | GET | Platform stats |
| `/api/reports/tools/usage` | GET | Per-tool usage |
| `/api/reports/audit` | GET | Audit trail (filterable) |
| `/api/reports/heatmap` | GET | Usage heatmap |
| `/api/contract-test` | POST | Run all 497 contract tests |
| `/api/ws/sessions` | GET | Active WebSocket sessions |

---

## Configuration — application.yml

```yaml
app:
  name: SAJHA MCP Server
  version: 4.5.0
  author: Ashutosh Sinha
  email: ajsinha@gmail.com

server:
  host: 0.0.0.0
  port: 3002

db:
  type: sqlite
  path: data/sajha.db

# PostgreSQL:
# db:
#   type: postgresql
#   host: ${DB_HOST:localhost}
#   port: 5432
#   name: sajha
#   user: ${DB_USER:sajha}
#   password: ${DB_PASSWORD:secret}

data:
  dir: data
logging:
  dir: logs
  file: sajha.log
config:
  plugins:
    dir: config/plugins
```

---

*SAJHA MCP Server v5.0.0 — API Reference*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
