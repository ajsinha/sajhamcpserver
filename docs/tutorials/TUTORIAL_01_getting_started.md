# Tutorial 1: Getting Started — Browse, Execute and Connect

Log in to SAJHA, find a tool, run it from the browser, then call the same tool from the command line over MCP and REST.

## What you'll learn

- How to sign in with the seeded administrator account
- How to browse, filter and inspect tools
- How to execute a tool from the web UI
- How to create an API key
- How to call a tool over MCP (both protocol eras SAJHA serves) and over REST

## Prerequisites

- A SAJHA checkout with its Python dependencies installed (`pip install -r requirements.txt`)
- `curl` (for steps 6–8)

## Steps

### 1. Start the server

```bash
python run_sajha_web.py
```

The server listens on `server.host` / `server.port` from `config/application.yml` (by default `0.0.0.0:3002`). Override them with `--host` and `--port`, for example `python run_sajha_web.py --port 8080`.

### 2. Sign in

Open `http://localhost:3002/login` and sign in as:

| User | Password |
|------|----------|
| `admin` | `admin123` |

This account is created by the database seed script (`db/scripts/<db>/seed.sql`). Change its password straight after your first login.

### 3. Browse tools

Open **Tools → All tools** (`/tools`). From there you can:

- narrow the list with the **Tool group** drop-down,
- type in the **Search by name or description** box,
- click a category chip to filter by category.

Click a tool's name, or the info button on its card, to open its schema page (`/tools/<name>/schema`). It shows the description, the input schema and the output schema.

### 4. Execute a tool

On any tool card, click **Run**. The button opens `/tools/<name>/execute`. Fill in the parameter form and click **Execute Tool**.

For a first try, use a calculator tool, which needs no external API key. For example, `calc_percentage_change` with `old_value = 100` and `new_value = 125`. A successful run shows the execution time, a human-readable **Summary** (when one can be derived) and the raw JSON result:

```json
{ "old_value": 100, "new_value": 125, "percentage_change": 25.0 }
```

Use **Run Again** to repeat the call, and **View execution history** to see earlier runs.

### 5. Create an API key

Open **Admin → API keys** (`/admin/apikeys`, admin only) and create a key. SAJHA generates a key of the form `sja_…`, stores only its hash and shows the full key **once**, so copy it now:

```bash
export SAJHA_KEY=sja_your_key_here
```

You can send the key as `X-API-Key: sja_…` or as a bare `Authorization: sja_…` header.

### 6. Call a tool over MCP, 2025-11-25 (session) style

The MCP endpoint is `POST /mcp`; `POST /api/mcp` is an alias. A 2025-11-25 client opens a session with `initialize`, and the server returns its id in the `Mcp-Session-Id` response header:

```bash
curl -si -X POST http://localhost:3002/mcp \
  -H "X-API-Key: $SAJHA_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-11-25","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1.0"}}}'
# -> HTTP/1.1 200 OK ... mcp-session-id: 3201bbc1...
export SID=<value of the mcp-session-id header>
```

Then send `notifications/initialized` (the server answers `202`) and call a tool. Every later request carries both `Mcp-Session-Id` and `MCP-Protocol-Version`:

```bash
H=(-H "X-API-Key: $SAJHA_KEY" -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-11-25'
   -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')

curl -s -X POST http://localhost:3002/mcp "${H[@]}" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

curl -s -X POST http://localhost:3002/mcp "${H[@]}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"calc_percentage_change","arguments":{"old_value":100,"new_value":125}}}'
```

The result carries both `content` (text) and `structuredContent`. `tools/list` is paginated: pass the returned `nextCursor` back as `params.cursor` to get the next page. When you are done, `DELETE /mcp` with the same `Mcp-Session-Id` header ends the session.

### 7. Call a tool over MCP, 2026-07-28 (stateless) style

In the 2026-07-28 protocol there is no handshake and no session. Each request states its protocol version in `params._meta`, together with the client capabilities. Both keys are required. The request must also repeat routing information in headers:

- `MCP-Protocol-Version` must equal the `_meta` version.
- `Mcp-Method` must equal the JSON-RPC method.
- `Mcp-Name` must equal the tool name, prompt name or resource URI, for `tools/call`, `prompts/get` and `resources/read`.

If a header is missing or doesn't match the body, the server answers HTTP 400 with error `-32020`.

Discover the server first:

```bash
curl -s -X POST http://localhost:3002/mcp \
  -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: server/discover' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover",
       "params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                          "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

The result lists `supportedVersions`, `capabilities` and `instructions`. Now call a tool:

```bash
curl -s -X POST http://localhost:3002/mcp \
  -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: tools/call' \
  -H 'Mcp-Name: calc_percentage_change' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"calc_percentage_change","arguments":{"old_value":100,"new_value":125},
                 "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                          "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Some tools mark arguments with `x-mcp-header` in their input schema, and those arguments must be mirrored in an `Mcp-Param-<Name>` header. For example, `yahoo_get_quote` needs `-H 'Mcp-Param-Symbol: AAPL'` when `symbol` is `AAPL`. List results (`tools/list` and the other list methods) also carry `ttlMs` and `cacheScope` caching hints.

### 8. Use the REST API

The REST API sits under `/api` and takes the same credentials as `/mcp`:

```bash
curl -s http://localhost:3002/api/tools/list -H "X-API-Key: $SAJHA_KEY"
curl -s http://localhost:3002/api/tools/calc_percentage_change/schema -H "X-API-Key: $SAJHA_KEY"

curl -s -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -d '{"tool":"calc_percentage_change","arguments":{"old_value":100,"new_value":125}}'
# -> {"success": true, "result": {"old_value": 100, "new_value": 125, "percentage_change": 25.0}}
```

Execution checks the caller's tool access: an API key's tool access mode, or a user's role permissions (the [Security Model](../security/Security%20Model.md) has the rules). Programs that sign in as a user get a JWT from `POST /api/auth/login`; later tutorials keep it as `$TOKEN`:

```bash
TOKEN=$(curl -s -X POST http://localhost:3002/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"admin123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s http://localhost:3002/api/tools/list -H "Authorization: Bearer $TOKEN"
```

> **Authentication on `/mcp`:** `mcp.auth.mode` in `config/application.yml` is `"off"` by default, so a call without credentials is accepted, but as the anonymous caller, who sees only the tools in `mcp.anonymous.tools` (none by default). Set the mode to `required` to refuse such calls outright. The modes, and OAuth bearer tokens, are in the [OAuth Guide](../protocol/OAuth%20Guide.md).

## What next

- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md): both protocol eras in depth
- [API Reference](../protocol/API%20Reference.md)
- [Client SDK Guide](../clients/Client%20SDK%20Guide.md): the same calls from Python
- [Quick Start](../getting-started/Quick%20Start.md)
- Next tutorial: [Create a Custom Tool](TUTORIAL_02_create_a_custom_tool.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
