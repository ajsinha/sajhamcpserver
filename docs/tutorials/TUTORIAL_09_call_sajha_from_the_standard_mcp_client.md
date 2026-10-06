# Tutorial 9: Call SAJHA from the Standard MCP Client

Connect to SAJHA with `SajhaMCPClient` / `SajhaMCPSyncClient`. These wrap the official MCP Python SDK, which speaks standard Streamable HTTP and negotiates the protocol version for you.

## What you'll learn

- How to install the optional MCP SDK dependency
- How protocol negotiation works: 2026-07-28 first, falling back to 2025-11-25
- How to list and call tools, synchronously and with asyncio
- How to reach SAJHA-specific features from the same client

## Prerequisites

- A running server ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Python with `pip`
- An API key (`sja_…`) or a username and password

## Steps

### 1. Install the client with the `mcp` extra

From the root of the SAJHA checkout:

```bash
pip install "./clientsdk[mcp]"
```

The `mcp` extra installs the official MCP Python SDK (`mcp>=2.3,<3`). Importing `sajhaclient` does not import `mcp`; the SDK is loaded the first time you construct a `SajhaMCPClient`. If it is missing, you get an `ImportError` that tells you what to install.

### 2. Connect and inspect the session (synchronous)

`SajhaMCPSyncClient` runs the async client on a background event loop, so you can use it from plain scripts:

```python
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key") as client:
    print(client.negotiated_protocol_version)        # "2026-07-28" against SAJHA
    if client.server_info:
        print(client.server_info.name, client.server_info.version)

    tools = client.list_all_tools()                  # follows nextCursor pagination
    print(len(tools), [t.name for t in tools[:5]])
```

The client accepts the same credentials as the other SDK clients:

- `api_key="sja_…"` is sent as `X-API-Key`.
- `jwt_token=…` is sent as `Authorization: Bearer`.
- `username=… , password=…` logs in first, then sends the JWT.
- An explicit `auth=` provider (`ApiKeyAuth`, `JWTAuth`, `OAuthAuth`) or a full `config=SajhaConfig(...)` also works.

### 3. Call a tool

```python
with SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key") as client:
    result = client.call_tool("calc_percentage_change", {"old_value": 100, "new_value": 125})
    if result.is_error:
        print("tool failed:", [c.text for c in result.content if hasattr(c, "text")])
    else:
        print(result.structured_content)             # {'old_value': 100, 'new_value': 125, 'percentage_change': 25.0}
```

A tool failure does **not** raise: check `result.is_error`. Protocol errors raise `SajhaMCPError`, and transport failures raise `SajhaConnectionError`.

### 4. The same with asyncio

```python
import asyncio
from sajhaclient import SajhaMCPClient

async def main():
    async with SajhaMCPClient("http://localhost:3002", api_key="sja_your_key") as client:
        print(client.negotiated_protocol_version)
        page = await client.list_tools()                     # one page: .tools, .next_cursor
        result = await client.call_tool("calc_percentage_change",
                                        {"old_value": 100, "new_value": 125})
        print(result.structured_content)

        prompts = await client.list_all_prompts()
        resources = await client.list_all_resources()

asyncio.run(main())
```

Other methods: `get_prompt(name, args)`, `read_resource(uri)`, `list_resource_templates()` and `complete(ref, argument)`. For anything not wrapped, `client.sdk` is the underlying `mcp.Client`.

### 5. Choose the protocol mode (optional)

By default, `mode="auto"`. The SDK first probes `server/discover` and adopts the stateless 2026-07-28 protocol. Against a server that only offers the `initialize` handshake, it falls back to 2025-11-25. SAJHA serves both protocols, so `auto` settles on 2026-07-28.

```python
SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key", mode="legacy")       # force initialize (2025-11-25)
SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key", mode="2026-07-28")   # adopt directly
```

Other options: `mcp_path` (default `"/mcp"`), `client_name` and `client_version` (sent as `clientInfo`). Any further keyword arguments, such as `sampling_callback`, `elicitation_callback` or `logging_callback`, are passed to `mcp.Client`.

### 6. Use SAJHA extras from the same object

The client shares its config and credentials with SAJHA's zero-dependency clients:

```python
with SajhaMCPSyncClient("http://localhost:3002", username="admin", password="admin123") as client:
    print(client.health()["status"])                         # GET /health
    print(client.tool_schema("calc_percentage_change")["name"])
    usage = client.tools_usage("7d")                         # GET /api/reports/tools/usage
    card = client.a2a.get_agent_card()                       # A2A agent card
    rest = client.rest                                       # SajhaClient (REST)
    ws = client.websocket()                                  # MCPWebSocketClient; .connect() needs `pip install websockets`
```

## What next

- [Client SDK Guide](../clients/Client%20SDK%20Guide.md): all clients, auth providers and exceptions
- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md): what the SDK negotiates on the wire
- [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md)
- A runnable example: `clientsdk/examples/standard_client_example.py`

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
