# SAJHA MCP Server v5.2.0 — API Reference

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
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"my-agent","version":"1.0"}},"id":1}'

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


---

## MCP 2025-11-25 — New Methods

### Tasks (Async Tracking)

```bash
# Get task status
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tasks/get","params":{"taskId":"abc-123"},"id":1}'

# List all tasks
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tasks/list","params":{},"id":2}'

# Cancel a task
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"tasks/cancel","params":{"taskId":"abc-123"},"id":3}'
```

### Elicitation (Server → User Input)

```bash
# Respond to an elicitation request
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"jsonrpc":"2.0","method":"elicitation/respond","params":{"requestId":"req-456","action":"submit","content":{"field1":"value1"}},"id":4}'
```

### OAuth Discovery Endpoints

```bash
# OpenID Connect Discovery (Major 1)
curl http://localhost:3002/.well-known/openid-configuration

# Protected Resource Metadata — RFC 9728 (Minor 8)
curl http://localhost:3002/.well-known/oauth-protected-resource

# Client ID Metadata Document — CIMD (Major 8)
curl http://localhost:3002/.well-known/oauth-client/my-client-id
```

### All 15 MCP Methods

| Method | Description | Since |
|--------|-------------|-------|
| `initialize` | Negotiate capabilities (2025-11-25) | 2024-11-05 |
| `initialized` | Confirm init complete | 2024-11-05 |
| `ping` | Health check | 2024-11-05 |
| `tools/list` | List tools (100/page, with icons) | 2024-11-05 |
| `tools/call` | Execute tool (isError on failure) | 2024-11-05 |
| `resources/list` | List resources | 2024-11-05 |
| `resources/read` | Read resource by URI | 2024-11-05 |
| `prompts/list` | List prompts | 2024-11-05 |
| `prompts/get` | Get prompt with vars | 2024-11-05 |
| `completion/complete` | Auto-complete args | 2025-03-26 |
| `logging/setLevel` | Set log level | 2025-03-26 |
| `notifications/cancelled` | Cancel pending request | 2025-06-18 |
| `tasks/get` | Get task status | **2025-11-25** |
| `tasks/list` | List all tasks | **2025-11-25** |
| `tasks/cancel` | Cancel a task | **2025-11-25** |

## Configuration — application.yml

```yaml
app:
  name: SAJHA MCP Server
  version: 5.2.0
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

*SAJHA MCP Server v5.2.0 — API Reference*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*

---

## REST API — Cache (v5.2.0)

### GET /api/cache/stats

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/cache/stats
```

Response:
```json
{"type": "file", "cache_dir": "data/cache", "size": 142, "size_bytes": 284600, "size_human": "277.9 KB", "max_files": 50000, "tools_cached": 8, "hits": 1203, "misses": 456, "writes": 1659, "hit_rate": 72.5}
```

### POST /api/cache/invalidate

```bash
# Invalidate specific tool cache
curl -X POST http://localhost:3002/api/cache/invalidate \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"tool_name": "yahoo_quote"}'

# Invalidate all
curl -X POST http://localhost:3002/api/cache/invalidate \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" -d '{}'
```

---

## REST API — Circuit Breakers (v5.2.0)

### GET /api/circuits

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/circuits
```

Response:
```json
{
  "circuits": [
    {"name": "FMP", "state": "closed", "failure_count": 0, "failure_threshold": 5},
    {"name": "Yahoo Finance", "state": "open", "failure_count": 7, "recovery_timeout": 60}
  ]
}
```

---

## REST API — Provider Health (v5.2.0)

### GET /api/providers/health

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/providers/health
```

Response:
```json
{
  "providers": [
    {"provider": "FMP", "registered_tools": 100, "api_endpoint": "https://financialmodelingprep.com/api", "status": "healthy", "circuit_state": "closed"},
    {"provider": "Yahoo Finance", "registered_tools": 35, "status": "degraded", "circuit_state": "half_open"}
  ]
}
```

### GET /api/providers/graph

Full dependency graph: tools → providers → API endpoints.

---

## REST API — Execution Replay (v5.2.0)

### GET /api/replay/recent

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/replay/recent
```

### GET /api/replay/tool/{name}

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/replay/tool/yahoo_quote
```

Response:
```json
{
  "tool": "yahoo_quote",
  "executions": [
    {"id": "yahoo_quote:a1b2c3:1716000000", "arguments": {"symbol": "AAPL"}, "result_preview": "{\"symbol\":\"AAPL\",\"price\":198.42,...}", "duration_ms": 230.1, "success": true, "timestamp": 1716000000}
  ]
}
```

---

## REST API — Webhooks (v5.2.0)

### POST /api/webhooks/subscribe

```bash
curl -X POST http://localhost:3002/api/webhooks/subscribe \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"event": "tool.completed", "url": "https://my-app.com/webhook"}'
```

Events: `tool.completed`, `tool.failed`, `task.completed`, `task.failed`, `circuit.opened`, `circuit.closed`, `health.degraded`

### GET /api/webhooks

Lists all subscriptions and delivery statistics.

---

## REST API — Audit Log (v5.2.0)

### GET /api/audit

```bash
curl -H "X-API-Key: sja_key" "http://localhost:3002/api/audit?action=login_failed&limit=20"
```

Params: `action`, `user_id`, `limit` (max 500).

Actions: `login_success`, `login_failed`, `logout`, `user_create`, `user_delete`, `apikey_create`, `apikey_revoke`, `tool_execute`, `config_change`, `permission_change`, `account_locked`


---

## REST API — Async Tool Execution (v5.2.0)

### POST /api/tools/{name}/execute-async

Submit a tool for background execution with result delivery.

```bash
# Webhook delivery
curl -X POST http://localhost:3002/api/tools/fmp_stock_screener/execute-async \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"marketCapMoreThan": 1000000000, "async": {"delivery": "webhook", "destination": "https://my-app.com/results"}}'

# Kafka delivery
curl -X POST http://localhost:3002/api/tools/fred_gdp/execute-async \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"async": {"delivery": "kafka", "destination": "sajha.results", "kafka_key": "gdp-daily"}}'

# File delivery
curl -X POST http://localhost:3002/api/tools/yahoo_quote/execute-async \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"symbol": "AAPL", "async": {"delivery": "file", "destination": "quote-aapl.json"}}'
```

Response (immediate, ~50ms):
```json
{"task_id": "t-a1b2c3d4e5f6", "status": "queued", "tool_name": "fmp_stock_screener", "delivery": "webhook", "poll_url": "/api/async/tasks/t-a1b2c3d4e5f6"}
```

### GET /api/async/tasks

```bash
curl -H "X-API-Key: sja_key" "http://localhost:3002/api/async/tasks?status=running"
```

### GET /api/async/tasks/{task_id}

```bash
curl -H "X-API-Key: sja_key" http://localhost:3002/api/async/tasks/t-a1b2c3d4e5f6
```

### POST /api/async/tasks/{task_id}/cancel

### POST /api/async/tasks/{task_id}/retry

### GET /api/async/stats

```json
{"workers": 8, "queue_size": 3, "queue_max": 1000, "submitted": 847, "completed": 830, "failed": 4, "delivered": 826, "cancelled": 2}
```

---

## REST API — Shell Execution (v5.2.0)

**DISABLED BY DEFAULT.** Requires `shell.enabled: true` in `config/application.yml`.

### POST /api/shell/python

```bash
curl -X POST http://localhost:3002/api/shell/python \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"code": "import json\ndata = {\"pi\": 3.14159, \"e\": 2.71828}\nprint(json.dumps(data, indent=2))"}'
```

Response:
```json
{"execution_id": "py-a1b2c3d4", "type": "python", "tier": "sandbox", "success": true, "stdout": "{\n  \"pi\": 3.14159,\n  \"e\": 2.71828\n}", "stderr": "", "exit_code": 0, "duration_ms": 45.2}
```

Blocked example:
```json
{"code": "import os; os.system('ls')"}
→ {"success": false, "blocked_reason": "Blocked import: os (security policy)"}
```

### POST /api/shell/bash

```bash
curl -X POST http://localhost:3002/api/shell/bash \
  -H "Content-Type: application/json" -H "X-API-Key: sja_key" \
  -d '{"command": "echo hello | wc -c"}'
```

Blocked example:
```json
{"command": "rm -rf /"}
→ {"success": false, "blocked_reason": "Blocked: command matches security pattern 'rm'"}
```

### GET /api/shell/capabilities

Returns what's enabled and the full security policy (allowed/blocked imports and commands).

### GET /api/shell/history

Admin-only. Last 50 shell executions with code, output, and timing.
