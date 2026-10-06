# SAJHA Client SDK Guide

`sajhaclient` is the Python client SDK for the SAJHA MCP Server. It contains:

- **The standard MCP client**: `SajhaMCPClient` (async) and `SajhaMCPSyncClient` (blocking). Both wrap the official MCP Python SDK and use the standard Streamable HTTP transport. They need the optional `[mcp]` extra.
- **Zero-dependency clients** that use only the Python standard library: `SajhaClient` (REST), `MCPClient` (MCP JSON-RPC over HTTP POST), `MCPSSEClient` (legacy HTTP+SSE), `MCPWebSocketClient` (SAJHA's MCP-over-WebSocket) and `A2AClient` (Agent-to-Agent).
- **Shared pieces**: `SajhaConfig`, the auth providers (`NoAuth`, `ApiKeyAuth`, `JWTAuth`, `OAuthAuth`), the exception hierarchy, plus the experimental helpers `ClientPipeline`, `TransportCoalgebra` and `bisimilar`.

Related documents:

- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md): what the server speaks on `/mcp` (both protocol eras)
- [OAuth Guide](../protocol/OAuth%20Guide.md): server-side OAuth 2.1 and how to obtain tokens
- [API Reference](../protocol/API%20Reference.md): the REST endpoints the `SajhaClient` methods call

---

## Contents

1. [Installation](#1-installation)
2. [Choosing a client](#2-choosing-a-client)
3. [Standard MCP client: SajhaMCPClient / SajhaMCPSyncClient](#3-standard-mcp-client-sajhamcpclient--sajhamcpsyncclient)
4. [Configuration: SajhaConfig](#4-configuration-sajhaconfig)
5. [Authentication](#5-authentication)
6. [REST client: SajhaClient](#6-rest-client-sajhaclient)
7. [Zero-dependency MCP clients](#7-zero-dependency-mcp-clients)
8. [A2A client: A2AClient](#8-a2a-client-a2aclient)
9. [Errors](#9-errors)
10. [Experimental: ClientPipeline, transport coalgebra, bisimilar](#10-experimental-clientpipeline-transport-coalgebra-bisimilar)
11. [curl and wget](#11-curl-and-wget)
12. [Examples and tests](#12-examples-and-tests)

---

## 1. Installation

```bash
pip install sajhaclient            # core: zero dependencies, Python 3.9+
pip install 'sajhaclient[mcp]'     # adds the standard MCP client (official SDK: mcp>=2.3,<3)
```

To install from a checkout of this repository:

```bash
pip install ./clientsdk            # or: pip install './clientsdk[mcp]'
pip install -e './clientsdk[dev]'  # editable, with pytest and pytest-asyncio
```

Extras declared in `clientsdk/setup.py`:

| Extra | Installs | Needed for |
|-------|----------|------------|
| `mcp` | `mcp>=2.3,<3` | `SajhaMCPClient`, `SajhaMCPSyncClient` |
| `cli` | `mcp>=2.3,<3` | the `sajha` command line ([Command Line](Command%20Line.md)) |
| `dev` | `pytest`, `pytest-asyncio` | running `clientsdk/tests` |

`MCPWebSocketClient` also needs the `websockets` package, which is not part of any extra. Install it with `pip install websockets`.

Importing `sajhaclient` never imports `mcp`. The SDK is imported the first time a `SajhaMCPClient` is constructed. If it is missing, you get an `ImportError` that tells you to run `pip install 'sajhaclient[mcp]'`.

---

## 2. Choosing a client

All clients are importable from the package root, e.g. `from sajhaclient import SajhaMCPClient`.

| Class | Protocol / transport | Dependencies | Use it for |
|-------|---------------------|--------------|------------|
| `SajhaMCPClient` | MCP over Streamable HTTP via the official SDK; negotiates 2026-07-28 or the `initialize` handshake | `[mcp]` extra | **Default choice** for MCP: agents, LLM integrations, anything that must stay spec-compliant |
| `SajhaMCPSyncClient` | Same, as a blocking facade | `[mcp]` extra | The same thing, without asyncio |
| `SajhaClient` | SAJHA REST API | none | Health, tool schemas, tool execution, usage reports, admin |
| `MCPClient` | MCP JSON-RPC via plain HTTP POST (`initialize` with `2025-11-25`) | none | Environments where you cannot install packages |
| `MCPSSEClient` | Legacy MCP HTTP+SSE (the 2024-11-05 pattern) | none | Old SSE-based setups only. **Deprecated** |
| `MCPWebSocketClient` | SAJHA's MCP-over-WebSocket (`/mcp/ws`), a SAJHA extension rather than a standard MCP transport | `websockets` | Full-duplex sessions with server-pushed notifications |
| `A2AClient` | A2A JSON-RPC (`/a2a`, `/.well-known/agent.json`) | none | Multi-agent orchestration |

---

## 3. Standard MCP client: SajhaMCPClient / SajhaMCPSyncClient

`SajhaMCPClient` is a thin wrapper over the official MCP Python SDK's `mcp.Client`. It speaks Streamable HTTP to `<base_url>/mcp`, so it behaves like any other spec-compliant MCP client. It also gives you SAJHA's own features through the zero-dependency clients (see [3.6](#36-sajha-extras-on-the-same-object)).

### 3.1 Quick start (async)

```python
import asyncio
from sajhaclient import SajhaMCPClient

async def main():
    async with SajhaMCPClient("http://localhost:3002", api_key="sja_your_key") as client:
        print(client.negotiated_protocol_version)       # "2026-07-28" or "2025-11-25"
        tools = await client.list_all_tools()            # follows pagination
        print([t.name for t in tools[:5]])

        result = await client.call_tool("calc_percentage_change",
                                        {"old_value": 100, "new_value": 125})
        print(result.is_error, result.structured_content)

asyncio.run(main())
```

### 3.2 Quick start (sync)

`SajhaMCPSyncClient(base_url=None, **kwargs)` takes the same arguments as `SajhaMCPClient` and exposes the same methods as blocking calls. It runs the async client on a private event loop in a background thread (`anyio.from_thread.start_blocking_portal`).

```python
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002", api_key="sja_your_key") as client:
    print(client.negotiated_protocol_version)
    print([t.name for t in client.list_all_tools()])
    result = client.call_tool("calc_percentage_change", {"old_value": 80, "new_value": 100})
```

Without `with`, call `client.connect()` and `client.close()` yourself. A blocking method called before `connect()` raises `RuntimeError`. Properties and extras such as `negotiated_protocol_version`, `server_info`, `rest`, `a2a`, `websocket()` and `sdk` pass straight through to the wrapped async client.

### 3.3 Constructor

```python
SajhaMCPClient(
    base_url=None, *,
    config=None, auth=None,
    api_key=None, jwt_token=None, username=None, password=None,
    mode="auto",
    mcp_path="/mcp",
    client_name="sajhaclient",
    client_version=None,          # defaults to sajhaclient.__version__
    **client_kwargs,
)
```

| Argument | Meaning |
|----------|---------|
| `base_url` | Server URL, e.g. `"http://localhost:3002"`. Overrides `config.base_url`; a trailing `/` is removed. |
| `config` | A [`SajhaConfig`](#4-configuration-sajhaconfig): credentials, `timeout`, `headers`, `verify_ssl`. |
| `auth` | An explicit [`AuthProvider`](#5-authentication). It takes precedence over any credentials. |
| `api_key`, `jwt_token`, `username`, `password` | Shortcuts that are copied into `config`. |
| `mode` | Protocol negotiation mode for the SDK (see [3.4](#34-protocol-negotiation)). |
| `mcp_path` | Path of the MCP endpoint relative to `base_url`. |
| `client_name`, `client_version` | Sent to the server as `clientInfo`. |
| `**client_kwargs` | Passed through to `mcp.Client`, e.g. `sampling_callback`, `elicitation_callback`, `logging_callback`, `read_timeout_seconds`, `cache`. |

The HTTP client uses `config.timeout` as its general timeout and allows reads of up to 300 s, so long-running tool calls can stream. It sends `config.headers` on every request, honours `config.verify_ssl`, and sets `User-Agent: sajhaclient/<version>`.

### 3.4 Protocol negotiation

The SAJHA server is dual-era. The SDK negotiates the era according to `mode`:

| `mode` | Behaviour |
|--------|-----------|
| `"auto"` (default) | Probes `server/discover` (MCP 2026-07-28). If the server does not support it, falls back to the `initialize` handshake (2025-11-25 and earlier). |
| `"legacy"` | Always uses the `initialize` handshake. |
| a modern version string, e.g. `"2026-07-28"` | Adopts that version directly, with no probe. |

After connecting, these session properties are available:

| Property | Value |
|----------|-------|
| `negotiated_protocol_version` | The agreed version, e.g. `"2026-07-28"` or `"2025-11-25"` |
| `server_info` | `mcp_types.Implementation`, or `None` because 2026-era servers may stay anonymous |
| `server_capabilities` | The server's capabilities |
| `instructions` | The server's instructions string, if any |
| `connected` | `True` while a session is open |
| `sdk` | The underlying `mcp.Client`, for anything this wrapper does not cover |

Reading `sdk` or any of the properties above (except `connected`) before connecting raises `RuntimeError`. See the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md) for what the two eras mean on the wire.

### 3.5 MCP operations

All of these are coroutines on `SajhaMCPClient` and blocking calls on `SajhaMCPSyncClient`. They return the SDK's typed pydantic results.

| Method | MCP request | Returns |
|--------|-------------|---------|
| `list_tools(cursor=None, **kw)` | `tools/list` (one page) | `ListToolsResult` |
| `list_all_tools()` | `tools/list`, following `next_cursor` | `list[Tool]` |
| `call_tool(name, arguments=None, **kw)` | `tools/call` | `CallToolResult` |
| `list_prompts(cursor=None, **kw)` / `list_all_prompts()` | `prompts/list` | page / `list[Prompt]` |
| `get_prompt(name, arguments=None, **kw)` | `prompts/get` | `GetPromptResult` |
| `list_resources(cursor=None, **kw)` / `list_all_resources()` | `resources/list` | page / `list[Resource]` |
| `list_resource_templates(cursor=None, **kw)` | `resources/templates/list` | page |
| `read_resource(uri, **kw)` | `resources/read` | `ReadResourceResult` |
| `complete(ref, argument, **kw)` | `completion/complete` | completion result |

Notes:

- `call_tool` does **not** raise when the tool itself fails. Check `result.is_error`. Use `result.structured_content` when the tool returns structured output, or `result.content` for the content blocks.
- `get_prompt` turns every argument value into a string, because the MCP spec requires string prompt arguments.
- SAJHA runs `tools/call` only for authenticated callers, so pass credentials (see [3.7](#37-auth-results-and-errors)).

```python
prompt = await client.get_prompt("bug_diagnosis", {
    "bug_description": "Average of an empty list crashes",
    "error_message": "ZeroDivisionError: division by zero",
    "code": "def avg(xs):\n    return sum(xs) / len(xs)",
    "language": "python",
})
resources = await client.list_all_resources()
if resources:
    contents = await client.read_resource(str(resources[0].uri))
```

### 3.6 SAJHA extras on the same object

These members are SAJHA features, not standard MCP. They reuse the client's `config` and auth.

| Member | What it is |
|--------|------------|
| `client.rest` | A [`SajhaClient`](#6-rest-client-sajhaclient) for health, schemas, reports and admin. It is blocking (urllib). |
| `client.a2a` | An [`A2AClient`](#8-a2a-client-a2aclient). It is blocking. |
| `client.websocket()` | A new, unconnected [`MCPWebSocketClient`](#73-mcpwebsocketclient). Call `.connect()` on it. Needs `websockets`. |
| `client.auth` | The resolved `AuthProvider` |
| `await client.health()` | `GET /health` |
| `await client.tool_schema(tool_name)` | `GET /api/tools/{name}/schema` |
| `await client.tool_metrics(tool_name, period="30d")` | `GET /api/reports/tools/{name}/detail` (latency percentiles, errors) |
| `await client.tools_usage(period="7d")` | `GET /api/reports/tools/usage` |

The four async shortcuts run the blocking REST call in a worker thread (`anyio.to_thread`), so they do not block the event loop. On `SajhaMCPSyncClient` they are ordinary blocking methods.

```python
print((await client.health()).get("status"))
print(client.a2a.get_agent_card().get("name"))
usage = client.rest.report_tools_usage("7d")
```

### 3.7 Auth, results and errors

- **Auth precedence** (same as the zero-dependency clients): explicit `auth=`, then `api_key` (sent as `X-API-Key`), then `jwt_token` (sent as `Authorization: Bearer`), then `username` + `password` (logs in via `JWTAuth` and sends `Bearer`), then no auth. Headers are stamped on every request and `refresh_if_needed()` runs each time, so JWT and OAuth refresh keep working on long sessions. A failed refresh is logged rather than raised; the server then answers 401.
- **Protocol errors** (JSON-RPC errors from the server) raise `SajhaMCPError`, with `.code`, `.message` and `.data`.
- **Transport failures** (connection refused, network errors) raise `SajhaConnectionError`. This applies when connecting too.
- Other exceptions from the SDK propagate unchanged.

---

## 4. Configuration: SajhaConfig

`SajhaConfig` is a dataclass shared by every client.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `base_url` | `str` | `"http://localhost:3002"` | Server URL. A trailing `/` is stripped. |
| `api_key` | `str \| None` | `None` | API key (`sja_...`) |
| `jwt_token` | `str \| None` | `None` | A JWT you already have |
| `username` | `str \| None` | `None` | Login user for `JWTAuth` |
| `password` | `str \| None` | `None` | Login password for `JWTAuth` |
| `timeout` | `int` | `30` | Request timeout in seconds |
| `max_retries` | `int` | `3` | Attempts used by `SajhaClient` on 5xx and connection errors |
| `verify_ssl` | `bool` | `True` | TLS verification. Only `SajhaMCPClient` applies it; the urllib-based clients use the default SSL context. |
| `headers` | `dict` | `{}` | Extra headers sent on every request by `SajhaClient` and `SajhaMCPClient` |

Derived URLs (read-only properties): `mcp_url` (`<base_url>/mcp`), `mcp_sse_url` (`<base_url>/mcp`), `a2a_url` (`<base_url>/a2a`), `agent_card_url` (`<base_url>/.well-known/agent.json`).

```python
from sajhaclient import SajhaConfig

config = SajhaConfig(
    base_url="https://sajha.example.com",
    api_key="sja_your_key",
    timeout=60,
    max_retries=5,
    headers={"X-Request-ID": "req-001"},
)
```

---

## 5. Authentication

Every client accepts either credentials in `SajhaConfig` or an explicit `auth=` provider. All providers implement `AuthProvider`: `get_headers()`, `refresh_if_needed()` and the `auth_type` property.

| Provider | Constructor | Header sent | `auth_type` |
|----------|-------------|-------------|-------------|
| `NoAuth` | `NoAuth()` | none | `"none"` |
| `ApiKeyAuth` | `ApiKeyAuth(api_key)`; raises `SajhaAuthError` if the key is empty | `X-API-Key: <key>` | `"apikey"` |
| `JWTAuth` | `JWTAuth(base_url, username, password, timeout=30)` | `Authorization: Bearer <jwt>` | `"jwt"` |
| `JWTAuth.from_token` | `JWTAuth.from_token(token)` | `Authorization: Bearer <jwt>` | `"jwt"` |
| `OAuthAuth` | `OAuthAuth(token_url, client_id, client_secret, scope="", timeout=30)` | `Authorization: Bearer <token>` | `"oauth"` |

Behaviour:

- `JWTAuth(...)` logs in immediately with `POST /api/auth/login` (`{"user_id", "password"}`) and logs in again once the token is within 5 minutes of an assumed 1-hour lifetime. The token is on `.token`. `JWTAuth.from_token` never refreshes.
- `OAuthAuth(...)` fetches a token immediately with the OAuth 2.0 **client credentials** grant and refreshes it 5 minutes before `expires_in` (1 hour if the server does not send it). It works with any token endpoint, e.g. Azure AD, Okta, Auth0 or Keycloak. See the [OAuth Guide](../protocol/OAuth%20Guide.md) for how the server validates these tokens.
- Login and token failures raise `SajhaAuthError`.

```python
from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth, JWTAuth, OAuthAuth

cfg = SajhaConfig(base_url="http://localhost:3002")

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_key"))   # from config
client = SajhaClient(cfg, auth=ApiKeyAuth("sja_key"))                                     # explicit
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002",
                                 username="admin", password="admin123"))                  # JWT login
client = SajhaClient(cfg, auth=JWTAuth.from_token("eyJhbGciOi..."))                        # existing JWT

auth = OAuthAuth(
    token_url="https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token",
    client_id="your-client-id",
    client_secret="your-client-secret",
    scope="api://sajha/.default",
)
client = SajhaClient(SajhaConfig(base_url="https://sajha.example.com"), auth=auth)
```

**Which clients read credentials from `SajhaConfig`:**

| Client | `api_key` | `jwt_token` | `username` + `password` |
|--------|-----------|-------------|-------------------------|
| `SajhaMCPClient`, `SajhaClient`, `MCPClient` | yes | yes | yes |
| `A2AClient` | yes | no | yes |
| `MCPSSEClient`, `MCPWebSocketClient` | no | no | no |

For `MCPSSEClient` and `MCPWebSocketClient`, always pass `auth=` explicitly. Otherwise they connect with `NoAuth`.

---

## 6. REST client: SajhaClient

`SajhaClient(config=None, auth=None)` wraps the SAJHA REST API using urllib. On 5xx responses and connection errors it retries up to `config.max_retries` times, with exponential backoff (1 s, 2 s, ...). The REST endpoints are documented in the [API Reference](../protocol/API%20Reference.md).

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))

print(client.health())
tools = client.list_tools()                                 # list of dicts
schema = client.get_tool_schema("calc_percentage_change")
result = client.execute_tool("calc_percentage_change", old_value=80, new_value=100)
quote = client.execute_tool("yahoo_get_quote", symbol="AAPL")
```

Tool arguments are passed as keyword arguments to `execute_tool(tool_name, **arguments)`.

### Methods

| Method | Endpoint | Notes |
|--------|----------|-------|
| `health()` | `GET /health` | |
| `list_tools()` | `GET /api/tools/list` | Returns the `tools` list |
| `get_tool_schema(tool_name)` | `GET /api/tools/{name}/schema` | |
| `execute_tool(tool_name, **arguments)` | `POST /api/tools/execute` | Body: `{"tool": ..., "arguments": {...}}` |
| `list_prompts()` | `GET /api/prompts/list` | Returns the `prompts` list (anonymous callers: only `mcp.anonymous.prompts`) |
| `get_prompt(prompt_name)` | `GET /api/prompts/{name}` | |
| `report_overview(period="24h")` | `GET /api/reports/overview` | |
| `report_tools_usage(period="7d")` | `GET /api/reports/tools/usage` | |
| `report_tool_detail(tool_name, period="30d")` | `GET /api/reports/tools/{name}/detail` | p50/p95/p99, errors |
| `report_user_activity(period="30d")` | `GET /api/reports/users/activity` | |
| `report_heatmap(days=30, tool=None)` | `GET /api/reports/heatmap` | Day-of-week by hour |
| `report_audit(limit=100, action=None)` | `GET /api/reports/audit` | |
| `admin_list_users()` | `GET /api/admin/users` | Returns the `users` list |
| `admin_create_user(user_id, user_name, password, roles=None, email="")` | `POST /api/admin/users/create` | `roles` defaults to `["user"]` |
| `admin_enable_user(user_id)` / `admin_disable_user(user_id)` | `POST /api/admin/users/{id}/enable` / `/disable` | |
| `admin_delete_user(user_id)` | `DELETE /api/admin/users/{id}/delete` | |
| `admin_enable_tool(tool_name)` / `admin_disable_tool(tool_name)` | `POST /api/admin/tools/{name}/enable` / `/disable` | |
| `admin_get_tool_config(tool_name)` | `GET /api/admin/tools/{name}/config` | |
| `admin_save_tool_config(tool_name, config)` | `POST /api/admin/tools/{name}/config` | |
| `admin_reload_tools()` | `POST /api/admin/tools/reload` | |
| `login(username, password)` | `POST /api/auth/login` | Replaces the client's auth with a new `JWTAuth` and returns the token |
| `auth_type` (property) | | `"none"`, `"apikey"`, `"jwt"` or `"oauth"` |

The `report_*` methods need an authenticated user, and the `admin_*` methods need the admin role. The server decides which calls succeed.

```python
client.report_overview("7d")
client.report_tool_detail("calc_percentage_change", "30d")
client.report_audit(limit=50, action="user.login")

client.admin_create_user("analyst1", "Jane Analyst", "s3cret", roles=["analyst"])
client.admin_disable_tool("calc_percentage_change")
client.admin_reload_tools()
```

---

## 7. Zero-dependency MCP clients

These clients use only the standard library and talk MCP JSON-RPC to SAJHA directly. Use them when you cannot install third-party packages, need Python 3.9 support, or want SAJHA's WebSocket transport. They always use the `initialize` handshake with `protocolVersion: "2025-11-25"` and do not negotiate. For interoperability with current and future MCP revisions, prefer `SajhaMCPClient`.

Unlike the standard client, these take tool arguments as **keyword arguments** (`call_tool("name", x=1)`) and return plain dicts.

### 7.1 MCPClient (HTTP POST)

`MCPClient(config=None, auth=None)` sends each request as a JSON-RPC `POST` to `<base_url>/mcp`.

```python
from sajhaclient import MCPClient, SajhaConfig

mcp = MCPClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
init = mcp.initialize(client_name="my-agent", client_version="1.0")
print(mcp.server_info, list(mcp.capabilities))

tools = mcp.list_tools()                                               # list of dicts
result = mcp.call_tool("calc_percentage_change", old_value=80, new_value=100)
```

| Method | MCP request | Returns |
|--------|-------------|---------|
| `initialize(client_name="sajhaclient", client_version=...)` | `initialize` | The full result. It also sets `server_info` and `capabilities`. |
| `ping()` | `ping` | dict |
| `list_tools()` | `tools/list` | list of tool dicts (first page only) |
| `call_tool(tool_name, **arguments)` | `tools/call` | The result dict (`content`, `isError`, ...) |
| `list_prompts()` | `prompts/list` | list |
| `get_prompt(prompt_name, arguments=None)` | `prompts/get` | dict |
| `list_resources()` | `resources/list` | list |
| `read_resource(uri)` | `resources/read` | dict |
| `complete(tool_name, argument_name, partial_value="")` | `completion/complete` with a `ref/tool` reference | list of suggested values |
| `set_log_level(level)` | `logging/setLevel` | dict |
| `server_info`, `capabilities` (properties) | | Set by `initialize()` |

HTTP 401 raises `SajhaAuthError`. Other HTTP errors raise `SajhaMCPError(-32000, ...)`, JSON-RPC errors raise `SajhaMCPError` with the server's code, and network failures raise `SajhaConnectionError`.

### 7.2 MCPSSEClient (legacy HTTP+SSE, deprecated)

`MCPSSEClient(config=None, auth=None)` implements the legacy MCP 2024-11-05 HTTP+SSE pattern, **not** Streamable HTTP. `connect()` opens `GET <base_url>/mcp`, reads the `endpoint` event, then starts a background thread that passes every SSE `data:` JSON message to your handlers. Requests are POSTed to the announced endpoint. The server still serves this transport for old clients. The class is kept for zero-dependency use only; prefer `SajhaMCPClient`.

```python
from sajhaclient import MCPSSEClient, SajhaConfig, ApiKeyAuth

sse = MCPSSEClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sja_your_key"))
sse.connect()
sse.on_notification(lambda msg: print("SSE:", msg))
sse.initialize()                     # also calls connect() if needed
print(len(sse.list_tools()))
sse.call_tool("calc_percentage_change", old_value=80, new_value=100)
sse.disconnect()
```

Methods: `connect()`, `disconnect()`, `on_notification(handler)`, `initialize(client_name="sajhaclient-sse", client_version=...)`, `list_tools(cursor=None)`, `call_tool(name, **arguments)`, `ping()`, `list_prompts()`, and the `connected` property.

### 7.3 MCPWebSocketClient

`MCPWebSocketClient(config=None, auth=None)` connects to SAJHA's MCP-over-WebSocket endpoint at `ws(s)://<host>/mcp/ws`. This is a SAJHA extension, not a standard MCP transport. It is full-duplex: responses are matched to requests by id, and server-initiated notifications go to the handlers you register. It needs `pip install websockets`.

WebSocket auth is passed as a query parameter: `?token=<jwt>` for Bearer providers, or `?api_key=<key>` for `ApiKeyAuth`. The `ws_url` property shows the URL that will be used.

```python
from sajhaclient import MCPWebSocketClient, SajhaConfig, ApiKeyAuth

with MCPWebSocketClient(SajhaConfig(base_url="http://localhost:3002"),
                        auth=ApiKeyAuth("sja_your_key")) as ws:      # connect() / disconnect()
    info = ws.initialize()
    ws.on_notification(lambda n: print("notification:", n.get("method")))
    tools = ws.list_tools()["tools"]
    result = ws.call_tool("calc_percentage_change", old_value=80, new_value=100)
    resources = ws.list_resources()
    prompts = ws.list_prompts()
    ws.ping()
```

Methods: `connect()`, `disconnect()`, `initialize(client_name="sajhaclient-ws", client_version=...)`, which also sends the `initialized` notification, `list_tools(cursor=None)`, `call_tool(name, **arguments)`, `list_resources()`, `read_resource(uri)`, `list_prompts()`, `get_prompt(name, arguments=None)`, `ping()`, `on_notification(handler)`, and the `connected` and `ws_url` properties. These methods return the raw JSON-RPC `result` dicts. For example, `list_tools()` returns `{"tools": [...]}`, not a list. JSON-RPC errors raise `SajhaError`.

From a standard client, `client.websocket()` returns one of these, already configured with the same config and auth.

---

## 8. A2A client: A2AClient

`A2AClient(config=None, auth=None)` lets an orchestrator discover SAJHA as an agent and send it tasks over A2A JSON-RPC.

```python
from sajhaclient import A2AClient, SajhaConfig

a2a = A2AClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))

card = a2a.get_agent_card()
print(card["name"], len(card.get("skills", [])))

task = a2a.send_task("Get the latest AAPL stock quote")
print(task["id"], task["status"]["state"])
task = a2a.get_task(task["id"])

done = a2a.send_and_wait("Summarize today's market movers", timeout=30)

session = "research-001"                       # multi-turn: reuse a session id
a2a.send_task("I'm researching EV stocks", session_id=session)
a2a.send_task("Compare TSLA and RIVN", session_id=session)
```

| Method | Request | Notes |
|--------|---------|-------|
| `get_agent_card()` | `GET /.well-known/agent.json` | Cached for `list_skills()` |
| `list_skills()` | | Returns the `skills` from the agent card, fetching it if needed: the tools the caller may see (none for an anonymous caller by default) |
| `send_task(text, session_id=None, metadata=None)` | `tasks/send` | Sends a single text part |
| `get_task(task_id)` | `tasks/get` | |
| `cancel_task(task_id)` | `tasks/cancel` | |
| `send_and_wait(text, timeout=60, poll_interval=1.0)` | `tasks/send` then polls `tasks/get` | Returns when the task reaches `completed`, `failed` or `cancelled`. Raises `SajhaA2AError` if a polled task fails or the wait times out. |

HTTP and JSON-RPC errors raise `SajhaA2AError`. Network failures raise `SajhaConnectionError`.

---

## 9. Errors

All SDK exceptions derive from `SajhaError`.

| Exception | Raised when | Exported from package root |
|-----------|-------------|---------------------|
| `SajhaError` | Base class; also other HTTP status codes in `SajhaClient`, and JSON-RPC errors in `MCPWebSocketClient` | yes |
| `SajhaConnectionError` | The server cannot be reached (all clients), or there is an MCP transport failure in `SajhaMCPClient` | yes |
| `SajhaAuthError` | HTTP 401, login failure, OAuth token failure, or an empty API key | yes |
| `SajhaPermissionError` | HTTP 403 (`SajhaClient`) | yes |
| `SajhaNotFoundError` | HTTP 404 (`SajhaClient`) | yes |
| `SajhaValidationError` | HTTP 400 (`SajhaClient`) | no: import from `sajhaclient.exceptions` |
| `SajhaServerError` | HTTP 5xx after retries (`SajhaClient`) | no: import from `sajhaclient.exceptions` |
| `SajhaMCPError(code, message, data=None)` | JSON-RPC / MCP protocol error. Has `.code`, `.message` and `.data`. | yes |
| `SajhaA2AError` | A2A request or task failure | yes |

```python
from sajhaclient import (SajhaClient, SajhaConfig, SajhaError, SajhaAuthError,
                         SajhaPermissionError, SajhaNotFoundError, SajhaConnectionError)
from sajhaclient.exceptions import SajhaValidationError

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
try:
    client.execute_tool("calc_percentage_change", old_value=80, new_value=100)
except SajhaValidationError as e:
    print("bad arguments:", e)
except SajhaAuthError:
    print("authenticate first (API key, JWT or OAuth)")
except SajhaPermissionError:
    print("no access to this tool")
except SajhaNotFoundError:
    print("no such endpoint or tool")
except SajhaConnectionError:
    print("server unreachable")
except SajhaError as e:
    print("other error:", e)
```

With the standard client, remember that a failing **tool** is reported in the result (`CallToolResult.is_error`), not raised.

---

## 10. Experimental: ClientPipeline, transport coalgebra, bisimilar

These helpers live in `sajhaclient.mcp_client` and are importable from the package root. They are not listed in `sajhaclient.__all__`, so a star import does not bring them in.

### 10.1 ClientPipeline

`ClientPipeline(client)` chains tool calls on the client side. `client` is any object with an `execute_tool(name, **kwargs)` method, normally a `SajhaClient`. Each step's output can feed the next one.

```python
from sajhaclient import SajhaClient, SajhaConfig, ClientPipeline

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))

pipeline = (ClientPipeline(client)
            .add_step("yahoo_get_quote", param_map={"symbol": "$input.ticker"}, output_key="quote")
            .add_step("calc_percentage_change",
                      param_map={"old_value": "$input.cost_basis", "new_value": "$input.target"},
                      output_key="upside"))

result = pipeline.execute({"ticker": "AAPL", "cost_basis": 150, "target": 210},
                          max_entropy_bits=3.0)
print(result["quote"]["result"], result["upside"]["result"])
print(result["_composition"])
```

`add_step(tool_name, param_map=None, static_params=None, output_key=None)` returns the pipeline, so calls can be chained. The values in `param_map` work like this:

| Value | Resolves to |
|-------|-------------|
| `"$input.<field>"` | `<field>` from the dict passed to `execute()` (`""` if missing) |
| `"$.<field>"` | Top-level `<field>` of the previous step's output (`""` if missing). With `SajhaClient`, a step's output is the REST envelope `{"success": true, "result": ...}`, so `"$.result"` passes the whole previous tool result. Nested paths such as `"$.result.price"` are not supported. |
| any other string or value | Used as a literal |

`static_params` are merged in first, and `output_key` defaults to the tool name.

`execute(initial_input, max_entropy_bits=3.0)` returns every step's output under its `output_key`, plus a `_composition` dict:

| Key | Meaning |
|-----|---------|
| `confidence` | The product of per-step confidences. Each successful step currently counts as a fixed `0.92`. |
| `entropy_bits` | The binary entropy of `confidence` |
| `confidence_floor` | `2 ** -entropy_bits` |
| `guard_passed` | `entropy_bits <= max_entropy_bits` |
| `duration_ms`, `steps_executed`, `trace` | Timing and a per-step trace |

The first failing step stops the pipeline. Its `output_key` gets `{"error": ...}`, and `_composition` reports `confidence: 0.0`, the error and the trace.

### 10.2 Transport coalgebra and bisimilar

`TransportCoalgebra(config=None, auth=None)` is a common interface over the zero-dependency MCP transports: `step(method, params=None) -> (result, state)`, plus the shortcuts `initialize()`, `list_tools()`, `call_tool(name, **kwargs)`, `ping()` and the `state` property (`initialized`, `request_count`, `transport`). The concrete classes are:

| Class | Wraps | `state["transport"]` |
|-------|-------|----------------------|
| `HTTPTransport(config, auth)` | `MCPClient` | `"http_post"` |
| `SSETransport(config, auth)` | `MCPSSEClient` | `"sse"` |
| `WSTransport(config, auth)` | `MCPWebSocketClient` (connects on `initialize`) | `"websocket"` |

`bisimilar(transport_a, transport_b, test_sequence, comparator=None)` runs the same `(method, params)` sequence on both transports and compares each pair of outputs. The default comparator checks that the types match and, for dicts, that the key sets are equal. It returns `{"passed", "steps", "first_divergence", "total_steps"}`.

```python
from sajhaclient import HTTPTransport, SSETransport, bisimilar, SajhaConfig, ApiKeyAuth

config = SajhaConfig(base_url="http://localhost:3002")
auth = ApiKeyAuth("sja_your_key")

report = bisimilar(HTTPTransport(config, auth), SSETransport(config, auth),
                   [("initialize", None), ("tools/list", None), ("ping", None)])
print(report["passed"], report["first_divergence"])
```

Caveats in the current code:

- **Shape differences.** The wrapped clients do not return identical shapes. For example, `MCPClient.list_tools()` returns a list, but `MCPWebSocketClient.list_tools()` returns `{"tools": [...]}`. As a result, HTTP and WebSocket transports diverge at `tools/list` under the default comparator.
- **`tools/call` is broken.** Routing `tools/call` through `step()` (or through `TransportCoalgebra.call_tool`) currently passes the arguments dict positionally to the wrapped client's keyword-only `call_tool` and fails. Call tools on the underlying clients instead.
- **`WSTransport` passthrough is broken.** `WSTransport.step` with a method other than `initialize`, `tools/list`, `tools/call` or `ping` fails.

---

## 11. curl and wget

Sometimes the SDK is not needed. These requests hit the same endpoints the clients use:

```bash
# Health
curl http://localhost:3002/health

# Login -> JWT
curl -X POST http://localhost:3002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id": "admin", "password": "admin123"}'

# Execute a tool over REST (API key; use "Authorization: Bearer <jwt>" for JWT)
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Content-Type: application/json" -H "X-API-Key: sja_your_key" \
  -d '{"tool": "calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}'

# A2A agent card
curl http://localhost:3002/.well-known/agent.json

# wget
wget -qO- http://localhost:3002/health
wget -qO- --header="X-API-Key: sja_your_key" http://localhost:3002/api/tools/list
```

For raw MCP JSON-RPC on `/mcp`, including the headers each protocol era requires, see the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md). More scripts are in `clientsdk/examples/curl_examples.sh` and `wget_examples.sh`.

---

## 12. Examples and tests

`clientsdk/examples/`:

| File | Shows |
|------|-------|
| `standard_client_example.py` | `SajhaMCPClient` and `SajhaMCPSyncClient`: negotiation, tools, prompts, resources, SAJHA extras |
| `mcp_client_example.py` | `MCPClient` |
| `rest_apikey.py`, `rest_jwt.py`, `rest_oauth.py` | `SajhaClient` with each auth method |
| `a2a_client_example.py` | `A2AClient` |
| `admin_operations.py` | Admin user and tool management |
| `financial_analysis.py` | Chaining several tools over REST |
| `curl_examples.sh`, `wget_examples.sh` | The same calls without Python |

`clientsdk/tests/test_legacy_transports.py` covers the zero-dependency MCP clients and the transport coalgebra, offline. `clientsdk/tests/test_standard_client.py` covers the standard client. The offline tests check the lazy import, the install hint, URL and auth resolution, header stamping, and connection-error mapping. The live tests check `auto` mode negotiating 2026-07-28, `legacy` mode using `initialize`, tool calls, prompts, resources, the SAJHA extras and the sync facade. Run them with:

```bash
pip install -e './clientsdk[dev,mcp]'
pytest clientsdk/tests
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
