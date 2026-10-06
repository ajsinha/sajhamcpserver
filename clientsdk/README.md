# sajhaclient: Python Client SDK for SAJHA MCP Server

`sajhaclient` is the Python client for the [SAJHA MCP Server](https://github.com/ajsinha/sajhamcpserver).

- **Standard MCP client.** `SajhaMCPClient` (async) and `SajhaMCPSyncClient` (blocking) are built on the official MCP Python SDK. They speak Streamable HTTP and automatically negotiate either MCP 2026-07-28 or the 2025-11-25 `initialize` handshake.
- **Zero-dependency clients.** These use only the standard library: `SajhaClient` (REST: tools, reports, admin), `MCPClient`, `MCPSSEClient` and `MCPWebSocketClient`, and `A2AClient`.
- **Auth.** All clients support API key, JWT and OAuth authentication.
- **Command line.** The `sajha` command (`pip install 'sajhaclient[cli]'`): sign in, call tools, render prompts, ask, deploy Studio tools, and run SAJHA over stdio for desktop clients. See [Command Line](../docs/clients/Command%20Line.md).

## Install

```bash
pip install sajhaclient            # core, zero dependencies (Python 3.9+)
pip install 'sajhaclient[mcp]'     # adds the standard MCP client (official mcp SDK)
pip install 'sajhaclient[cli]'     # adds the sajha command line
```

## Quick start

```python
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key") as client:
    print(client.negotiated_protocol_version)          # "2026-07-28" or "2025-11-25"
    print([t.name for t in client.list_tools().tools])
    result = client.call_tool("calc_percentage_change", {"old_value": 80, "new_value": 100})
    print(result.is_error, result.structured_content)
```

For the async client, the REST/A2A/WebSocket clients, auth providers, configuration and errors, see the [Client SDK Guide](../docs/clients/Client%20SDK%20Guide.md).

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
