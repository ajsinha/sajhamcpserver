# SAJHA MCP Server — Python Client SDK

**Version 5.0.0** · Zero dependencies (stdlib only) · Python 3.9+

## Install

```bash
pip install sajhaclient
# For WebSocket: pip install sajhaclient websockets
```

## Client Classes

| Class | Transport | Auth |
|-------|-----------|------|
| `SajhaClient` | REST (HTTP) | JWT, API Key |
| `MCPClient` | MCP (HTTP POST) | JWT, API Key |
| `MCPSSEClient` | MCP (SSE) | JWT, API Key |
| `MCPWebSocketClient` | MCP (WebSocket) | JWT, API Key |
| `A2AClient` | A2A Protocol | JWT, API Key |

## Quick Start

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

client = SajhaClient(
    SajhaConfig(base_url="http://localhost:3002"),
    auth=ApiKeyAuth("sja_your_key")
)
result = client.execute_tool("yahoo_quote", symbol="AAPL")
```

## Client-Side Pipeline (v5.0.0)

```python
from sajhaclient import ClientPipeline

pipeline = ClientPipeline(client)
pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})

result = pipeline.execute({"ticker": "AAPL"})
print(result['_composition']['confidence'])  # 0.85
print(result['_composition']['entropy_bits'])  # 0.61
```

## Transport Coalgebra (v5.0.0)

```python
from sajhaclient import HTTPTransport, WSTransport, bisimilar

# Prove HTTP and WebSocket produce identical results
result = bisimilar(
    HTTPTransport(config, auth),
    WSTransport(config, auth),
    [('initialize', None), ('tools/list', None)]
)
assert result['passed']
```

## WebSocket

```python
from sajhaclient import MCPWebSocketClient, SajhaConfig, ApiKeyAuth

with MCPWebSocketClient(
    SajhaConfig(base_url="http://localhost:3002"),
    auth=ApiKeyAuth("sja_key")
) as ws:
    ws.initialize()
    result = ws.call_tool("yahoo_quote", symbol="AAPL")
```

## Auth Providers

| Provider | Usage |
|----------|-------|
| `NoAuth()` | Development |
| `ApiKeyAuth("sja_...")` | API key via X-API-Key |
| `JWTAuth("user", "pass")` | JWT with auto-refresh |
| `OAuthAuth("token")` | Enterprise SSO |

## Documentation

See `docs/USER_GUIDE.md` for complete reference with examples.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
