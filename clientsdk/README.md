# sajhaclient — Python Client SDK for SAJHA MCP Server

**Zero-dependency Python SDK** for connecting to SAJHA MCP Server via REST, MCP, and A2A protocols.

## Install

```bash
pip install .
```

## Quick Start

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_your_key",
))

# Execute a tool
result = client.execute_tool("fmp_stock_quote", symbol="AAPL")
print(result)
```

## Authentication

```python
# API Key
client = SajhaClient(SajhaConfig(base_url="...", api_key="sja_xxx"))

# JWT Login
client = SajhaClient(SajhaConfig(base_url="...", username="admin", password="pass"))

# OAuth
from sajhaclient import OAuthAuth
auth = OAuthAuth(token_url="...", client_id="...", client_secret="...")
client = SajhaClient(SajhaConfig(base_url="..."), auth=auth)
```

## Three Protocol Clients

| Client | Use Case |
|--------|----------|
| `SajhaClient` | REST API — tool execution, admin, reports |
| `MCPClient` | MCP JSON-RPC 2.0 — AI agent integrations |
| `A2AClient` | Agent-to-Agent — multi-agent systems |

## Documentation

See [USER_GUIDE.md](USER_GUIDE.md) for comprehensive documentation, all examples, and API reference.

## Examples

```
examples/
  rest_apikey.py          # REST with API key
  rest_jwt.py             # REST with JWT login
  rest_oauth.py           # REST with OAuth (Azure AD, Okta)
  mcp_client_example.py   # MCP protocol
  a2a_client_example.py   # A2A protocol
  admin_operations.py     # User/tool management
  financial_analysis.py   # Multi-tool workflow
  curl_examples.sh        # curl commands
  wget_examples.sh        # wget commands
```

## License

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
