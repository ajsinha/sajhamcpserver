# SAJHA MCP Server — Client SDK User Guide

**Version 3.0.0** | Copyright 2025-2030, Ashutosh Sinha | ajsinha@gmail.com

---

## Table of Contents

1. [Installation](#1-installation)
2. [Quick Start](#2-quick-start)
3. [Authentication Methods](#3-authentication-methods)
4. [REST API Client](#4-rest-api-client)
5. [MCP Protocol Client](#5-mcp-protocol-client)
6. [A2A Protocol Client](#6-a2a-protocol-client)
7. [curl & wget Reference](#7-curl--wget-reference)
8. [Tool Execution](#8-tool-execution)
9. [Admin Operations](#9-admin-operations)
10. [Reporting & Analytics](#10-reporting--analytics)
11. [Error Handling](#11-error-handling)
12. [Advanced Usage](#12-advanced-usage)
13. [API Reference](#13-api-reference)

---

## 1. Installation

### From Source

```bash
cd clientsdk
pip install .
```

### Development Mode

```bash
pip install -e .
```

### Zero Dependencies

The SDK uses only Python standard library (`urllib`, `json`, `threading`). No `requests`, no `httpx`, no third-party packages required. Works with Python 3.9+.

---

## 2. Quick Start

### 30-Second Example

```python
from sajhaclient import SajhaClient, SajhaConfig

# Connect with API key
client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_your_key_here",
))

# Check server health
print(client.health())

# List available tools
tools = client.list_tools()
print(f"{len(tools)} tools available")

# Execute a tool
result = client.execute_tool("fmp_stock_quote", symbol="AAPL")
print(result)
```

### Connection Methods at a Glance

| Method | Use When | Example |
|--------|----------|---------|
| API Key | Scripts, automation, CI/CD | `SajhaConfig(api_key="sja_xxx")` |
| JWT Login | Interactive apps, admin tasks | `SajhaConfig(username="admin", password="pass")` |
| OAuth | Enterprise SSO (Azure AD, Okta) | `OAuthAuth(token_url, client_id, secret)` |
| No Auth | Health check, public endpoints | `SajhaConfig()` |

### Protocol Clients

| Client | Protocol | Use When |
|--------|----------|----------|
| `SajhaClient` | REST/HTTP | Standard tool execution, admin, reports |
| `MCPClient` | MCP JSON-RPC 2.0 | AI agents, LLM integrations |
| `A2AClient` | Agent-to-Agent | Multi-agent systems, agent orchestration |

---

## 3. Authentication Methods

### 3.1 API Key Authentication

The simplest method. Get your key from the SAJHA Admin Panel → API Keys.

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

# Method 1: In config (auto-detected)
client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_abc123def456",
))

# Method 2: Explicit auth object
auth = ApiKeyAuth("sja_abc123def456")
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=auth)
```

**HTTP Header:** `X-API-Key: sja_abc123def456`

### 3.2 JWT Authentication (Username/Password)

Login with credentials. The SDK handles token refresh automatically.

```python
from sajhaclient import SajhaClient, SajhaConfig, JWTAuth

# Method 1: In config (auto-login)
client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    username="admin",
    password="admin123",
))

# Method 2: Login after creation
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"))
token = client.login("admin", "admin123")

# Method 3: Pre-obtained token
auth = JWTAuth.from_token("eyJhbGciOiJIUzI1NiIs...")
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=auth)
```

**HTTP Header:** `Authorization: Bearer eyJhbG...`

### 3.3 OAuth 2.0 Authentication

For enterprise environments with Azure AD, Okta, Auth0, or Keycloak.

```python
from sajhaclient import SajhaClient, SajhaConfig, OAuthAuth

# Azure AD
auth = OAuthAuth(
    token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    client_id="your-client-id",
    client_secret="your-secret",
    scope="api://sajha/.default",
)

client = SajhaClient(
    SajhaConfig(base_url="https://sajha.company.com"),
    auth=auth,
)
```

The SDK obtains and refreshes OAuth tokens automatically.

---

## 4. REST API Client

### 4.1 Tool Discovery

```python
# List all tools
tools = client.list_tools()
for tool in tools:
    print(f"{tool['name']}: {tool.get('description', '')}")

# Get full schema for a specific tool
schema = client.get_tool_schema("fmp_stock_quote")
print(schema['inputSchema'])
```

### 4.2 Tool Execution

```python
# Execute any tool by name with keyword arguments
result = client.execute_tool("fmp_stock_quote", symbol="AAPL")
result = client.execute_tool("wikipedia_search", query="Python programming")
result = client.execute_tool("fmp_stock_screener", sector="Technology", limit=10)
result = client.execute_tool("openbb_equity_price", symbol="TSLA", start_date="2025-01-01")
```

### 4.3 Prompts

```python
prompts = client.list_prompts()
prompt = client.get_prompt("code_review")
```

---

## 5. MCP Protocol Client

Use `MCPClient` for AI agent integrations. Implements the full MCP (Model Context Protocol) JSON-RPC 2.0 specification.

### 5.1 Basic Usage

```python
from sajhaclient import SajhaConfig
from sajhaclient.mcp_client import MCPClient

mcp = MCPClient(SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_xxx",
))

# Step 1: Initialize (required first call)
caps = mcp.initialize(client_name="my-agent", client_version="1.0")
print(f"Capabilities: {list(caps['capabilities'].keys())}")

# Step 2: Discover tools
tools = mcp.list_tools()

# Step 3: Call tools
result = mcp.call_tool("fmp_stock_quote", symbol="AAPL")
```

### 5.2 All MCP Methods

```python
# Session
mcp.initialize()
mcp.ping()

# Tools
mcp.list_tools()
mcp.call_tool("tool_name", arg1="val1", arg2="val2")

# Prompts
mcp.list_prompts()
mcp.get_prompt("prompt_name", arguments={"key": "value"})

# Resources
mcp.list_resources()
mcp.read_resource("sajha://tools/catalog")

# Completion (auto-suggest)
mcp.complete("fmp_stock_quote", "symbol", "AA")  # → ["AAPL", "AAL", ...]

# Logging
mcp.set_log_level("DEBUG")
```

### 5.3 SSE Streaming Transport

```python
from sajhaclient.mcp_client import MCPSSEClient

sse = MCPSSEClient(SajhaConfig(base_url="http://localhost:3002"))
sse.connect()

# Listen for server notifications (tool list changes, etc.)
sse.on_notification(lambda n: print(f"Server notification: {n}"))

# Disconnect when done
sse.disconnect()
```

---

## 6. A2A Protocol Client

Use `A2AClient` when building multi-agent systems. SAJHA acts as an agent that your orchestrator can delegate tasks to.

### 6.1 Agent Discovery

```python
from sajhaclient.a2a_client import A2AClient

a2a = A2AClient(SajhaConfig(base_url="http://localhost:3002"))

# What can this agent do?
card = a2a.get_agent_card()
print(f"Agent: {card['name']}")
print(f"Skills: {len(card['skills'])}")
for skill in card['skills'][:5]:
    print(f"  - {skill['id']}: {skill['description']}")
```

### 6.2 Task Lifecycle

```python
# Send a task (async — returns immediately)
task = a2a.send_task("Get the latest AAPL stock quote")
print(f"Task {task['id']}: {task['status']['state']}")

# Check status
status = a2a.get_task(task['id'])

# Send and wait (blocking — waits for completion)
result = a2a.send_and_wait("Analyze Tesla's balance sheet", timeout=30)

# Cancel a running task
a2a.cancel_task(task['id'])
```

### 6.3 Multi-Turn Sessions

```python
session = "research-session-001"
a2a.send_task("I'm researching EV stocks", session_id=session)
a2a.send_task("Compare TSLA and RIVN financials", session_id=session)
result = a2a.send_task("Which looks better for investment?", session_id=session)
```

---

## 7. curl & wget Reference

### Health Check

```bash
curl http://localhost:3002/health
```

### Login (Get JWT Token)

```bash
curl -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id": "admin", "password": "admin123"}'
```

### Execute Tool (API Key)

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sja_your_key" \
  -d '{"tool": "fmp_stock_quote", "arguments": {"symbol": "AAPL"}}'
```

### Execute Tool (JWT)

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbG..." \
  -d '{"tool": "fmp_stock_quote", "arguments": {"symbol": "AAPL"}}'
```

### MCP Protocol

```bash
# Initialize
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"clientInfo":{"name":"curl","version":"1.0"}}}'

# List tools
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call tool
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fmp_stock_quote","arguments":{"symbol":"AAPL"}}}'
```

### A2A Protocol

```bash
# Agent card
curl http://localhost:3002/.well-known/agent.json

# Send task
curl -X POST http://localhost:3002/a2a \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"message":{"parts":[{"type":"text","text":"Get AAPL quote"}]}}}'
```

### wget

```bash
wget -qO- http://localhost:3002/health
wget -qO- --header="X-API-Key: sja_xxx" http://localhost:3002/api/tools/list
```

---

## 8. Tool Execution

### Available Tool Categories

| Category | FMP Tools | OpenBB Tools |
|----------|-----------|--------------|
| Company Data | `fmp_company_profile`, `fmp_company_peers`, `fmp_exec_compensation` | `openbb_equity_profile` |
| Market Data | `fmp_stock_quote`, `fmp_historical_price` | `openbb_equity_price` |
| Financial Statements | `fmp_income_statement`, `fmp_balance_sheet`, `fmp_cash_flow` | `openbb_income_statement`, `openbb_balance_sheet`, `openbb_cash_flow` |
| Financial Analysis | `fmp_key_metrics`, `fmp_analyst_estimates`, `fmp_price_target`, `fmp_upgrades_downgrades` | `openbb_equity_metrics`, `openbb_dividends`, `openbb_earnings` |
| Valuation | `fmp_dcf_valuation`, `fmp_historical_dcf` | — |
| Market Movers | `fmp_market_gainers`, `fmp_market_losers`, `fmp_most_active`, `fmp_sector_performance` | — |
| Calendars | `fmp_earnings_calendar`, `fmp_dividend_calendar`, `fmp_ipo_calendar`, `fmp_economic_calendar` | — |
| News | `fmp_stock_news` | `openbb_market_news`, `openbb_company_news` |
| Ownership | `fmp_insider_trading`, `fmp_institutional_holders`, `fmp_senate_trading` | `openbb_insider_trading`, `openbb_institutional_ownership` |
| Screening | `fmp_stock_screener` | `openbb_equity_screener` |
| SEC | `fmp_sec_filings` | — |
| ETFs | `fmp_etf_holdings` | `openbb_etf_holdings` |
| Economics | `fmp_treasury_rates` | `openbb_economy_gdp`, `openbb_economy_cpi`, `openbb_unemployment`, `openbb_economic_indicators` |
| Fixed Income | — | `openbb_treasury_rates`, `openbb_yield_curve` |
| Forex | — | `openbb_forex_historical` |
| Crypto | — | `openbb_crypto_price` |
| Commodities | — | `openbb_commodity_price` |
| Derivatives | — | `openbb_options_chains` |
| Indexes | — | `openbb_index_constituents` |

---

## 9. Admin Operations

Requires admin role.

```python
# User management
client.admin_list_users()
client.admin_create_user("analyst1", "Jane", "password", roles=["analyst"])
client.admin_enable_user("analyst1")
client.admin_disable_user("analyst1")
client.admin_delete_user("analyst1")

# Tool management
client.admin_enable_tool("fmp_stock_quote")
client.admin_disable_tool("fmp_senate_trading")
client.admin_reload_tools()
client.admin_get_tool_config("fmp_stock_quote")
client.admin_save_tool_config("fmp_stock_quote", {...})
```

---

## 10. Reporting & Analytics

```python
# Usage overview
client.report_overview("24h")   # Last 24 hours
client.report_overview("7d")    # Last 7 days
client.report_overview("30d")   # Last 30 days

# Per-tool usage
client.report_tools_usage("7d")

# Tool detail (percentiles, errors)
client.report_tool_detail("fmp_stock_quote", "30d")

# User activity
client.report_user_activity("30d")

# Usage heatmap
client.report_heatmap(days=30, tool="fmp_stock_quote")

# Audit trail
client.report_audit(limit=100, action="user.login")
```

---

## 11. Error Handling

```python
from sajhaclient import SajhaClient, SajhaConfig
from sajhaclient.exceptions import (
    SajhaError,           # Base exception
    SajhaConnectionError, # Cannot connect
    SajhaAuthError,       # Auth failed (401)
    SajhaPermissionError, # No permission (403)
    SajhaNotFoundError,   # Not found (404)
    SajhaValidationError, # Bad input (400)
    SajhaServerError,     # Server error (500)
    SajhaMCPError,        # MCP protocol error
    SajhaA2AError,        # A2A protocol error
)

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"))

try:
    result = client.execute_tool("nonexistent_tool")
except SajhaNotFoundError:
    print("Tool does not exist")
except SajhaAuthError:
    print("Authentication required — provide API key or login")
except SajhaPermissionError:
    print("You don't have access to this tool")
except SajhaConnectionError:
    print("Cannot reach the server — check URL and network")
except SajhaError as e:
    print(f"Something went wrong: {e}")
```

---

## 12. Advanced Usage

### Custom Headers

```python
client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_xxx",
    headers={"X-Request-ID": "req-001", "X-Correlation-ID": "corr-abc"},
))
```

### Timeout and Retry

```python
config = SajhaConfig(
    base_url="http://localhost:3002",
    timeout=60,        # 60 second timeout
    max_retries=5,     # Retry 5 times on server errors
)
```

### Disable SSL Verification (dev only)

```python
config = SajhaConfig(
    base_url="https://localhost:3002",
    verify_ssl=False,
)
```

### Multiple Servers

```python
prod = SajhaClient(SajhaConfig(base_url="https://sajha.prod.com", api_key="sja_prod"))
staging = SajhaClient(SajhaConfig(base_url="https://sajha.staging.com", api_key="sja_stg"))

# Compare tool counts
print(f"Prod tools: {len(prod.list_tools())}")
print(f"Staging tools: {len(staging.list_tools())}")
```

---

## 13. API Reference

### SajhaConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | str | `http://localhost:3002` | Server URL |
| `api_key` | str | None | API key (sja_xxx) |
| `jwt_token` | str | None | Pre-obtained JWT |
| `username` | str | None | Login username |
| `password` | str | None | Login password |
| `timeout` | int | 30 | Request timeout (seconds) |
| `max_retries` | int | 3 | Retry count on 5xx errors |
| `verify_ssl` | bool | True | Verify SSL certificates |
| `headers` | dict | {} | Custom HTTP headers |

### SajhaClient Methods

| Method | Auth Required | Description |
|--------|---------------|-------------|
| `health()` | No | Server status |
| `list_tools()` | No | All available tools |
| `get_tool_schema(name)` | No | Tool input/output schema |
| `execute_tool(name, **args)` | Yes | Run a tool |
| `list_prompts()` | No | All prompts |
| `report_overview(period)` | Yes | Usage statistics |
| `report_tools_usage(period)` | Yes | Per-tool stats |
| `report_tool_detail(name, period)` | Yes | Tool percentiles |
| `report_user_activity(period)` | Yes | Per-user stats |
| `report_heatmap(days, tool)` | Yes | Usage heatmap |
| `report_audit(limit, action)` | Admin | Audit log |
| `admin_list_users()` | Admin | List all users |
| `admin_create_user(...)` | Admin | Create user |
| `admin_enable/disable_user(id)` | Admin | Toggle user |
| `admin_delete_user(id)` | Admin | Delete user |
| `admin_enable/disable_tool(name)` | Admin | Toggle tool |
| `admin_reload_tools()` | Admin | Reload tool configs |
| `login(username, password)` | No | Get JWT token |

### MCPClient Methods

| Method | Description |
|--------|-------------|
| `initialize(name, version)` | Start MCP session |
| `ping()` | Health check |
| `list_tools()` | Discover tools |
| `call_tool(name, **args)` | Execute tool |
| `list_prompts()` | Discover prompts |
| `get_prompt(name, args)` | Get prompt |
| `list_resources()` | Discover resources |
| `read_resource(uri)` | Read resource |
| `complete(tool, arg, value)` | Auto-complete |
| `set_log_level(level)` | Set server log level |

### A2AClient Methods

| Method | Description |
|--------|-------------|
| `get_agent_card()` | Discover agent capabilities |
| `list_skills()` | Get agent skills |
| `send_task(text, session_id)` | Submit a task |
| `get_task(task_id)` | Check task status |
| `cancel_task(task_id)` | Cancel a task |
| `send_and_wait(text, timeout)` | Submit and wait for completion |

---

*SAJHA MCP Server Client SDK v3.0.0 — Built for the developer community.*
