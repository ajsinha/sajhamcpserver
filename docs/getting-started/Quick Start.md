# Quick Start

From a fresh clone to a first MCP tool call in a few minutes. Every key mentioned
here is described in the [Configuration Reference](Configuration%20Reference.md).

## 1. Install and run

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_server.py
```

CI runs on Python 3.12. The server listens on `http://localhost:3002`
(`server.host` / `server.port`).

`run_server.py` options: `--config <file.yml>`, `--host`, `--port`, `--reload`
(development auto-reload), `--workers` (keep 1, see the
[Architecture](../architecture/Architecture.md) on in-memory state), `--log-level`.

## 2. Sign in and secure the defaults

Open `http://localhost:3002` and sign in as `admin` / `admin123` (the seeded account).
Before the server is reachable by anyone else, **replace that account**: there is no
change-password endpoint, so create a new admin and disable `admin` (steps in the
[Security Model](../security/Security%20Model.md#default-admin-account)). Also set real
secrets through environment variables; the shipped defaults are public:

```bash
export JWT_SECRET=...        # auth.jwt.secret
export SESSION_SECRET=...    # auth.session.secret_key
```

The full checklist is in the [Security Model](../security/Security%20Model.md).

## 3. Call a tool over MCP

Any MCP client can connect to `http://localhost:3002/mcp`. With curl, a stateless
2026-07-28 call:

```bash
curl -s http://localhost:3002/mcp \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' -H 'Mcp-Name: calc_percentage_change' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"calc_percentage_change","arguments":{"old_value":80,"new_value":100},
        "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                 "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Or from Python, with SAJHA's client on top of the official MCP SDK:

```bash
pip install './clientsdk[mcp]'
```

```python
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002") as mcp:
    print(mcp.negotiated_protocol_version)          # 2026-07-28
    print(len(mcp.list_tools().tools), "tools")
    print(mcp.call_tool("calc_percentage_change", {"old_value": 80, "new_value": 100}))
```

How the two protocol eras work is in the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md);
the client is documented in the [Client SDK Guide](../clients/Client%20SDK%20Guide.md).

## 4. Add API keys for data providers

Many tools call external data services. Keys are read from configuration, usually via
environment variables, for example `FRED_API_KEY`, `FMP_API_KEY`, `GOOGLE_API_KEY` with
`GOOGLE_SEARCH_ENGINE_ID`, and `TAVILY_API_KEY`. A tool whose provider key is missing cannot
reach that service; tools that need no key are unaffected. Each provider's guide under `docs/tools/` says what it
needs.

## 5. Where next

- [How SAJHA Fits Together](How%20SAJHA%20Fits%20Together.md): the map, and which
  document owns each topic.
- [Tutorials](../README.md#tutorials): step-by-step walkthroughs, starting with
  [Tutorial 1](../tutorials/TUTORIAL_01_getting_started.md).
- [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md): generating your own
  tools.
- [OAuth Guide](../protocol/OAuth%20Guide.md): require OAuth 2.1 on `/mcp`.
- [Storage Guide](Storage%20Guide.md): run from S3, Azure Blob or GCS.
- Deployment recipes (AWS, Hetzner, bare metal): [`deployment/`](../../deployment/README.md).

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
