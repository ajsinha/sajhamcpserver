# SAJHA MCP Server — Python Client SDK

**Version 5.3.0** · Zero-dependency core (stdlib only) · Python 3.9+ · **MCP 2025-11-25** · optional `[mcp]` extra adds the standard client (official MCP SDK, negotiates up to 2026-07-28)

## Install

```bash
pip install sajhaclient
# Standard MCP client (official MCP Python SDK): pip install 'sajhaclient[mcp]'
# For WebSocket: pip install sajhaclient websockets
```

## Client Classes

| Class | Transport | Auth |
|-------|-----------|------|
| `SajhaMCPClient` / `SajhaMCPSyncClient` | MCP Streamable HTTP via the official `mcp` SDK (needs `[mcp]` extra) | JWT, API Key, OAuth |
| `SajhaClient` | REST (HTTP) | JWT, API Key |
| `MCPClient` | MCP (HTTP POST) | JWT, API Key |
| `MCPSSEClient` | MCP legacy HTTP+SSE (2024-11-05 pattern; deprecated) | JWT, API Key |
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

## Standard MCP Client (official MCP SDK)

`SajhaMCPClient` is a thin wrapper over the official MCP Python SDK
(`mcp` v2, `mcp.Client`). It talks the standard **Streamable HTTP** transport to
`<base_url>/mcp`, so it behaves like any other spec-compliant MCP client.

```bash
pip install 'sajhaclient[mcp]'      # adds mcp>=2.3,<3; the core SDK stays zero-dependency
```

```python
import asyncio
from sajhaclient import SajhaMCPClient

async def main():
    async with SajhaMCPClient("http://localhost:3002", api_key="sja_xxx") as client:
        print(client.negotiated_protocol_version)        # e.g. "2025-11-25" or "2026-07-28"
        tools = await client.list_all_tools()             # follows nextCursor pagination
        res = await client.call_tool("calc_percentage_change", {"old_value": 100, "new_value": 125})
        prompt = await client.get_prompt("bug_diagnosis", {"bug_description": "...",
                    "error_message": "...", "code": "...", "language": "python"})
        resources = await client.list_all_resources()

asyncio.run(main())
```

Prefer blocking code? `SajhaMCPSyncClient` takes the same arguments and exposes the
same methods synchronously (it runs the async client on a background event loop):

```python
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002", jwt_token="eyJ...") as client:
    print([t.name for t in client.list_all_tools()])
```

**Protocol-era negotiation.** With the default `mode="auto"` the SDK first probes
`server/discover` at MCP **2026-07-28**; if the server does not speak it, the SDK
falls back to the classic `initialize` handshake (2025-11-25, 2025-06-18,
2025-03-26, 2024-11-05). The result is in `client.negotiated_protocol_version`.
Pass `mode="legacy"` to force the handshake, or `mode="2026-07-28"` to pin the
modern era without a probe.

**Auth.** Same conventions as the rest of the SDK: `api_key=` (sent as
`X-API-Key`), `jwt_token=` or `username=`/`password=` (sent as
`Authorization: Bearer <jwt>`), or any `AuthProvider` via `auth=` (e.g.
`OAuthAuth`). Headers are applied per request, so JWT/OAuth refresh works on
long sessions. A full `SajhaConfig` can be passed as `config=`.

**Results and errors.** Methods return the SDK's typed results
(`ListToolsResult`, `CallToolResult`, `GetPromptResult`, ...). A failing tool
returns `CallToolResult.is_error == True`; protocol errors raise `SajhaMCPError`
and transport failures raise `SajhaConnectionError`. Anything not wrapped is
available on `client.sdk` (the underlying `mcp.Client`); extra keyword arguments
(`sampling_callback`, `elicitation_callback`, `logging_callback`,
`read_timeout_seconds`, ...) are passed straight to it.

**SAJHA extras on the same object** (these are SAJHA features, not standard MCP):

| Member | What it is |
|--------|------------|
| `client.rest` | `SajhaClient`: health, tool schemas, usage reports, admin APIs (blocking) |
| `await client.health()`, `tool_schema(name)`, `tool_metrics(name, period)`, `tools_usage(period)` | Async shortcuts to those REST endpoints |
| `client.a2a` | `A2AClient`: agent card, skills, tasks (blocking) |
| `client.websocket()` | New `MCPWebSocketClient` (SAJHA's MCP-over-WebSocket; needs `websockets`) |

The `import mcp` happens only when a `SajhaMCPClient` is created; if the SDK is
missing you get an `ImportError` telling you to `pip install 'sajhaclient[mcp]'`.
See `examples/standard_client_example.py`.

### When to use the zero-dependency clients

`MCPClient`, `MCPSSEClient` and `MCPWebSocketClient` use only the Python standard
library and target SAJHA specifically. Use them when you cannot install third-party
packages, need Python 3.9 (the MCP SDK requires 3.10+), or want SAJHA's WebSocket
transport, coalgebra/pipeline helpers. Note that `MCPSSEClient` implements the
legacy **HTTP+SSE** pattern from MCP 2024-11-05 (not Streamable HTTP) and is
deprecated in favour of `SajhaMCPClient`. For interoperability with current and
future MCP revisions, prefer `SajhaMCPClient`.

## Client-Side Pipeline (v5.3.0)

```python
from sajhaclient import ClientPipeline

pipeline = ClientPipeline(client)
pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})

result = pipeline.execute({"ticker": "AAPL"})
print(result['_composition']['confidence'])  # 0.85
print(result['_composition']['entropy_bits'])  # 0.61
```

## Transport Coalgebra (v5.3.0)

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
