# SAJHA MCP Server — API Reference

**Version:** 3.1.0 · **Protocol:** MCP 2025-06-18 · **Base URL:** `http://localhost:3002`

---

## Authentication

All API endpoints require authentication via one of:

| Method | Header / Cookie | Example |
|--------|----------------|---------|
| **API Key** | `X-API-Key: <key>` | `X-API-Key: sk_live_abc123` |
| **Bearer JWT** | `Authorization: Bearer <token>` | Obtain via `POST /api/auth/login` |
| **Session cookie** | `sajha_token` cookie | Set automatically on web login |

### Obtain a JWT Token

```
POST /api/auth/login
Content-Type: application/json

{"user_id": "admin", "password": "admin123"}

→ {"token": "eyJ...", "user_id": "admin"}
```

---

## MCP Protocol Endpoints

### POST /mcp

The primary MCP endpoint. Accepts JSON-RPC 2.0 requests.

```
POST /mcp
Content-Type: application/json
X-API-Key: <key>

{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "<method>",
  "params": {}
}
```

#### Supported Methods

**initialize** — Handshake, returns server info and capabilities.

```json
{"jsonrpc": "2.0", "id": "1", "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
```

Response includes `protocolVersion`, `serverInfo`, and `capabilities` (tools, prompts, resources, logging, completions).

**tools/list** — List available tools with cursor-based pagination (100/page).

```json
{"jsonrpc": "2.0", "id": "2", "method": "tools/list", "params": {"cursor": null}}
```

**tools/call** — Execute a tool.

```json
{"jsonrpc": "2.0", "id": "3", "method": "tools/call", "params": {
  "name": "yahoo_finance_quote",
  "arguments": {"symbol": "AAPL"}
}}
```

**prompts/list** — List prompt templates.

**prompts/get** — Get a prompt with argument substitution.

```json
{"jsonrpc": "2.0", "id": "4", "method": "prompts/get", "params": {
  "name": "market_analysis",
  "arguments": {"symbol": "TSLA"}
}}
```

**resources/list** — List resources (50/page), auto-discovers data files.

**resources/read** — Read a resource by URI.

**resources/templates/list** — List URI templates (2 available).

**resources/subscribe** / **resources/unsubscribe** — Resource change notifications.

**completion/complete** — Auto-suggest values from tool schema enums.

**logging/setLevel** — Change server log level dynamically.

```json
{"jsonrpc": "2.0", "id": "5", "method": "logging/setLevel", "params": {"level": "debug"}}
```

**ping** — Health check.

### SSE Transport

**GET /mcp/sse** — Establish an SSE connection for streaming responses.

**POST /mcp/message** — Send a message over an established SSE session.

---

## REST API Endpoints

### Tool Execution

**POST /api/tools/execute** — Execute a tool via REST.

```
POST /api/tools/execute
Content-Type: application/json
X-API-Key: <key>

{
  "tool": "yahoo_finance_quote",
  "arguments": {"symbol": "AAPL"}
}
```

**GET /api/tools/list** — List all tools (JSON array).

**GET /api/tools/{tool_name}/schema** — Get input/output schema for a tool.

### Admin APIs

**POST /api/admin/tools/{tool_name}/enable** — Enable a tool.

**POST /api/admin/tools/{tool_name}/disable** — Disable a tool.

**GET /api/admin/tools/{tool_name}/config** — Get tool JSON config.

**POST /api/admin/tools/{tool_name}/config** — Update tool config.

**POST /api/admin/tools/reload** — Force immediate hot-reload of all tools.

**GET /api/admin/users** — List all users.

**POST /api/admin/users/create** — Create a new user.

**POST /api/admin/users/{uid}/enable** — Enable a user.

**POST /api/admin/users/{uid}/disable** — Disable a user.

**DELETE /api/admin/users/{uid}/delete** — Delete a user.

**GET /api/admin/tools/metrics/export** — Export tool usage metrics.

### Prompts API

**GET /api/prompts/list** — List all prompts (JSON).

**GET /api/prompts/{prompt_name}** — Get a specific prompt.

**POST /api/prompts/create** — Create a new prompt.

### Resources API

**POST /api/resources/list** — List MCP resources.

**POST /api/resources/read** — Read a resource by URI.

**POST /api/completion/complete** — Autocomplete from tool schemas.

**POST /api/logging/setLevel** — Set server log level.

### Reporting API

**GET /api/reports/overview** — System overview statistics.

**GET /api/reports/tools/usage** — Tool execution counts.

**GET /api/reports/tools/{tool_name}/detail** — Per-tool detail metrics.

**GET /api/reports/users/activity** — User activity data.

**GET /api/reports/heatmap** — Usage heatmap data.

**GET /api/reports/audit** — Audit log entries.

### Health

**GET /health** — Server health check (no auth required).

---

## A2A Protocol Endpoints

**GET /.well-known/agent.json** — Agent card (auto-generated from tool registry).

**POST /a2a** — Agent-to-agent task operations (JSON-RPC):

```json
{"jsonrpc": "2.0", "id": "1", "method": "tasks/send", "params": {
  "task": {"tool": "wikipedia", "arguments": {"action": "search", "query": "AI"}}
}}
```

Methods: `tasks/send`, `tasks/get`, `tasks/cancel`.

---

## Web UI Endpoints

| Path | Page |
|------|------|
| `/` | Redirect to login or dashboard |
| `/login` | Login page |
| `/logout` | Logout |
| `/dashboard` | Main dashboard |
| `/tools` | Tool list with search and filtering |
| `/tools/{name}/execute` | Tool execution interface |
| `/tools/{name}/schema` | Tool schema viewer |
| `/tools/{name}/config` | Tool config viewer |
| `/prompts` | Prompts list |
| `/prompts/create` | Create new prompt |
| `/prompts/{name}` | Prompt detail |
| `/prompts/{name}/test` | Prompt test interface |
| `/reports` | Reporting dashboard |
| `/studio` | MCP Studio home |
| `/studio/rest` | REST Service Tool Creator |
| `/studio/dbquery` | DB Query Tool Creator |
| `/studio/script` | Script Tool Creator |
| `/studio/powerbi` | PowerBI Report Tool Creator |
| `/studio/powerbidax` | PowerBI DAX Query Tool Creator |
| `/studio/livelink` | LiveLink Tool Creator |
| `/studio/olap` | OLAP Dataset Creator |
| `/studio/sharepoint` | SharePoint Tool Creator |
| `/studio/examples` | Studio examples |
| `/admin/users` | User management |
| `/admin/tools` | Tool management |
| `/admin/apikeys` | API key management |
| `/monitoring/tools` | Tool metrics |
| `/monitoring/users` | User activity |
| `/help` | Help center |
| `/about` | About page |
| `/docs` | Documentation browser |
| `/docs/view/{path}` | Document viewer |
| `/api/docs` | FastAPI OpenAPI docs |
| `/api/redoc` | FastAPI ReDoc |

---

## Error Codes (JSON-RPC 2.0)

| Code | Meaning |
|------|---------|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32001` | Unauthorized |
| `-32002` | Forbidden |

---

## Python Client SDK

```python
from sajhaclient import SajhaConfig, SajhaClient, MCPClient, A2AClient, ApiKeyAuth

# REST Client
config = SajhaConfig(base_url="http://localhost:3002")
client = SajhaClient(config, auth=ApiKeyAuth("sk_live_..."))
tools = client.list_tools()
result = client.execute_tool("yahoo_finance_quote", {"symbol": "AAPL"})

# MCP Client (JSON-RPC)
mcp = MCPClient(config, auth=ApiKeyAuth("sk_live_..."))
mcp.initialize()
tools = mcp.list_tools()
result = mcp.call_tool("fred_gdp", {"start_date": "2020-01-01"})

# A2A Client
a2a = A2AClient(config, auth=ApiKeyAuth("sk_live_..."))
card = a2a.get_agent_card()
task = a2a.send_task({"tool": "wikipedia", "arguments": {"action": "search", "query": "AI"}})
```

Full SDK documentation: `clientsdk/docs/USER_GUIDE.md`.

---

*SAJHA MCP Server v3.1.0 — API Reference*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
