# Tutorial 5: Connect the Python SDK

Use `sajhaclient`, SAJHA's zero-dependency Python client, to list and execute tools over REST, chain tools on the client side, and talk MCP over HTTP and WebSocket.

## What you'll learn

- How to install the client SDK
- How to authenticate with a user login or an API key
- How to execute tools with `SajhaClient` and chain them with `ClientPipeline`
- How to call tools with `MCPClient` (HTTP) and `MCPWebSocketClient` (WebSocket)

## Prerequisites

- A running server ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Python 3.9+
- For the API-key examples, a key created under **Admin → API keys**

## Steps

### 1. Install

From the root of the SAJHA checkout:

```bash
pip install ./clientsdk            # core client: Python standard library only
pip install websockets             # only needed for MCPWebSocketClient (step 6)
```

### 2. Create a client and run a tool

`SajhaClient` talks to the REST API. Given a username and password, it logs in through `POST /api/auth/login` and sends the resulting JWT:

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    username="admin",
    password="admin123",
))

print(client.health()["status"])                 # "healthy"
tools = client.list_tools()                      # [{"name": ..., "description": ..., "inputSchema": ...}, ...]
schema = client.get_tool_schema("calc_percentage_change")

result = client.execute_tool("calc_percentage_change", old_value=100, new_value=125)
print(result)
# {'success': True, 'result': {'old_value': 100, 'new_value': 125, 'percentage_change': 25.0}}
```

`SajhaConfig` also takes `api_key`, `jwt_token`, `timeout`, `max_retries`, `verify_ssl` and extra `headers`. You can also pass an explicit `auth=` provider: `ApiKeyAuth`, `JWTAuth` or `OAuthAuth`.

### 3. Using an API key

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

keyed = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_your_key"))
keyed.list_tools()
keyed.execute_tool("calc_npv", discount_rate=8, cash_flows=[-1000, 300, 400, 500])
```

An API key runs exactly the tools its tool access mode allows; a tool outside it raises `SajhaPermissionError` (HTTP 403).

### 4. Chain tools on the client with `ClientPipeline`

`ClientPipeline` runs steps in order through `client.execute_tool`. It short-circuits on the first error and adds a `_composition` summary with confidence, entropy and a trace. Each step's `param_map` takes one of:

- `"$input.<field>"`: a field of the pipeline input
- `"$.<field>"`: a top-level field of the **previous step's response**. With `SajhaClient`, that response is the REST envelope `{"success": …, "result": …}`.
- anything else: a literal value

```python
from sajhaclient import ClientPipeline

pipeline = (ClientPipeline(client)
    .add_step("calc_percentage_change",
              param_map={"old_value": "$input.start", "new_value": "$input.end"},
              output_key="change")
    .add_step("calc_future_value",
              param_map={"present_value": "$input.end"},
              static_params={"rate": 5, "years": 10},
              output_key="fv"))

out = pipeline.execute({"start": 100, "end": 125})
print(out["fv"]["result"]["future_value"])        # 203.61
print(out["_composition"]["trace"])               # ['✓ calc_percentage_change: 3ms', '✓ calc_future_value: 3ms']
```

### 5. MCP over HTTP with `MCPClient`

`MCPClient` speaks MCP JSON-RPC to `/mcp`, using the 2025-11-25 `initialize` handshake:

```python
from sajhaclient import MCPClient, SajhaConfig

mcp = MCPClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
mcp.initialize(client_name="my-agent", client_version="1.0")
print(mcp.call_tool("calc_percentage_change", old_value=1, new_value=2))
# {'content': [...], 'structuredContent': {'old_value': 1, 'new_value': 2, 'percentage_change': 100.0}}
```

### 6. MCP over WebSocket with `MCPWebSocketClient`

The WebSocket endpoint `/mcp/ws` is a SAJHA extension. The client passes your credentials as a `?api_key=` or `?token=` query parameter.

```python
from sajhaclient import MCPWebSocketClient, SajhaConfig, ApiKeyAuth

ws = MCPWebSocketClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_your_key"))
ws.connect()
ws.initialize()
print(ws.call_tool("calc_percentage_change", old_value=1, new_value=2))
ws.on_notification(lambda n: print("server push:", n["method"]))   # e.g. notifications/tools/list_changed
ws.disconnect()
```

`MCPWebSocketClient` also supports `with` blocks: `__enter__` connects and `__exit__` disconnects.

## What next

- [Client SDK Guide](../clients/Client%20SDK%20Guide.md): every client, auth provider and exception
- [Composition Framework](../architecture/Composition%20Framework.md)
- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md)
- Next tutorial: [Configure Tool Caching](TUTORIAL_06_configure_tool_caching.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
