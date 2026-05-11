# SAJHA MCP Server v4.0.0 — API Reference

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## Transports

| Transport | Endpoint | Method | Description |
|-----------|----------|--------|-------------|
| HTTP POST | `/mcp` | POST | Stateless JSON-RPC 2.0 |
| SSE | `/mcp/sse` | GET | Server-push streaming |
| SSE Message | `/mcp/message` | POST | Paired with SSE endpoint |
| WebSocket | `/mcp/ws` | WS | Full-duplex bidirectional |

## MCP Methods (JSON-RPC 2.0)

| Method | Description |
|--------|-------------|
| `initialize` | Negotiate capabilities, exchange server/client info |
| `initialized` | Client confirms initialization complete |
| `ping` | Health check |
| `tools/list` | List available tools (paginated) |
| `tools/call` | Execute a tool with arguments |
| `resources/list` | List available resources |
| `resources/read` | Read a resource by URI |
| `prompts/list` | List prompt templates |
| `prompts/get` | Get a prompt with variable substitution |
| `completion/complete` | Auto-complete tool/prompt arguments |
| `logging/setLevel` | Change server log level |

## Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/login` | GET/POST | Web UI login (session cookie) |
| `/logout` | GET | Clear session |
| `/api/auth/login` | POST | JWT authentication (returns token) |
| `/api/auth/me` | GET | Current user info |

## Tools

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tools` | GET | List all tools |
| `/api/tools/{name}/schema` | GET | Tool input/output schema |
| `/api/tools/{name}/execute` | POST | Execute a tool |

## AI Integration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai/providers` | GET | List LLM providers with health |
| `/api/ai/providers/{type}/config` | POST | Update provider config |
| `/api/ai/providers/{type}/health` | POST | Health check provider |
| `/api/ai/models` | GET | List all models |
| `/api/ai/models` | POST | Create model entry |
| `/api/ai/models/{id}` | PUT | Update model |
| `/api/ai/models/{id}` | DELETE | Delete model |
| `/api/ai/defaults` | POST | Set default provider/model |
| `/api/ai/preferences` | GET/POST/DELETE | User AI preferences |
| `/api/ai/usage` | GET | Token usage |
| `/api/ai/resolve-tool` | POST | Semantic tool search |
| `/api/ai/complete` | POST | LLM completion via gateway |
| `/api/ai/registry` | GET | Registered provider classes |

## Composite Tools

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/composite-tools` | GET | List composites |
| `/api/composite-tools` | POST | Create composite |
| `/api/composite-tools/{name}` | GET | Get composite with schemas |
| `/api/composite-tools/{name}` | PUT | Update composite |
| `/api/composite-tools/{name}` | DELETE | Delete composite |
| `/api/composite-tools/{name}/preview-schema` | GET | Preview auto-generated schemas |

## Observability & Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe (always OK) |
| `/ready` | GET | Readiness probe (checks DB, tools) |
| `/api/metrics` | GET | Global metrics summary |
| `/api/metrics/tools` | GET | Per-tool metrics (p50/p95/p99) |
| `/api/metrics/tools/{name}` | GET | Single tool metrics |

## Multi-Tenancy

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tenants` | GET | List tenants |
| `/api/tenants` | POST | Create tenant |
| `/api/tenants/{id}` | GET | Get tenant |
| `/api/tenants/{id}` | PUT | Update tenant |
| `/api/tenants/{id}` | DELETE | Delete tenant |

## Plugins

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plugins` | GET | List plugins + status |
| `/api/plugins/{name}/load` | POST | Load a plugin |
| `/api/plugins/{name}/unload` | POST | Unload a plugin |
| `/api/plugins/discover` | POST | Rescan plugins directory |

## Tool Versioning & Testing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tool-versions` | GET | List tool versions |
| `/api/tool-versions/{name}/deprecate` | POST | Deprecate a tool version |
| `/api/contract-test` | POST | Run contract tests on all tools |
| `/api/contract-test/{name}` | POST | Test a single tool |

## Reporting

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/overview` | GET | Platform overview (totals, top tools) |
| `/api/reports/tools/usage` | GET | Per-tool usage stats |
| `/api/reports/tools/{name}/detail` | GET | Single tool deep dive |
| `/api/reports/users/activity` | GET | Per-user activity |
| `/api/reports/heatmap` | GET | Hour × day execution heatmap |
| `/api/reports/audit` | GET | Audit trail (filterable, paginated) |

## Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/users` | GET/POST | User CRUD |
| `/api/admin/tools/{name}/enable` | POST | Enable tool |
| `/api/admin/tools/{name}/disable` | POST | Disable tool |
| `/api/admin/apikeys` | GET/POST | API key management |

## A2A Protocol

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/.well-known/agent.json` | GET | Agent card |
| `/a2a/tasks/send` | POST | Create task |
| `/a2a/tasks/{id}` | GET | Get task status |
| `/a2a/tasks/{id}/cancel` | DELETE | Cancel task |

## WebSocket Sessions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ws/sessions` | GET | List active WebSocket connections |

---

*SAJHA MCP Server v4.0.0 — API Reference*
