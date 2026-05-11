# SAJHA MCP Server — Python Client SDK

**Version 4.0.0** · Zero dependencies (stdlib only) · Python 3.9+

## Install

```bash
pip install sajhaclient
# For WebSocket support:
pip install sajhaclient websockets
```

## Client Classes

| Class | Transport | Methods | Auth |
|-------|-----------|--------:|------|
| `SajhaClient` | REST (HTTP) | 25 | JWT, API Key |
| `MCPClient` | MCP (HTTP POST) | 12 | JWT, API Key |
| `MCPSSEClient` | MCP (SSE) | 12 | JWT, API Key |
| `MCPWebSocketClient` | MCP (WebSocket) | 12 | JWT, API Key |
| `A2AClient` | A2A Protocol | 6 | JWT, API Key |

## Quick Start

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

client = SajhaClient(
    SajhaConfig(base_url="http://localhost:3002"),
    auth=ApiKeyAuth("sja_your_key")
)

# Execute a tool
result = client.execute_tool("yahoo_quote", symbol="AAPL")

# List tools
tools = client.list_tools()
```

## WebSocket (v4.0.0)

```python
from sajhaclient import MCPWebSocketClient, SajhaConfig, ApiKeyAuth

with MCPWebSocketClient(
    SajhaConfig(base_url="http://localhost:3002"),
    auth=ApiKeyAuth("sja_key")
) as ws:
    ws.initialize()
    ws.on_notification(lambda n: print(f"Changed: {n}"))
    result = ws.call_tool("yahoo_quote", symbol="AAPL")
```

## Auth Providers

| Provider | Usage |
|----------|-------|
| `NoAuth()` | Development (no authentication) |
| `ApiKeyAuth("sja_...")` | API key via X-API-Key header |
| `JWTAuth("user", "pass")` | JWT with auto-refresh |
| `OAuthAuth("token")` | Enterprise SSO token |

## Documentation

See `docs/USER_GUIDE.md` for complete reference with examples.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
