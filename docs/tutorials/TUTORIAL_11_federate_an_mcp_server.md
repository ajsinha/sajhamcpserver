# Tutorial 11: Federate an MCP server

Put another MCP server behind SAJHA: run a small upstream server, add it to SAJHA, approve
its tools, and call them through SAJHA from the standard MCP client and from Ask SAJHA.
How federation works, every upstream field and its limits are in
[Federation](../architecture/Federation.md).

## What you'll learn

- How to turn federation on and let SAJHA reach a server on the same machine
- How to add an upstream, test it, and review what it offers before anything is exposed
- How federated tools are named, granted and called
- What happens when a federated tool needs the user's input

## Prerequisites

- A SAJHA checkout with its virtual environment, and an admin sign-in
  ([Tutorial 1](TUTORIAL_01_getting_started.md))
- The official MCP Python SDK v2 (`pip install 'mcp>=2.3,<3'`), which SAJHA's client SDK
  already uses ([Tutorial 9](TUTORIAL_09_call_sajha_from_the_standard_mcp_client.md))

## Steps

### 1. Run the upstream server

The repository ships a small MCP server built on the official SDK:
`sajha/examples/federation/units_server.py`. It offers four tools
(`celsius_to_fahrenheit`, `kilometres_to_miles`, `countdown`, `reset_counter`), a prompt and
a resource. In one terminal:

```bash
python sajha/examples/federation/units_server.py --port 8765
```

It now answers MCP at `http://127.0.0.1:8765/mcp`, on both protocol eras.

### 2. Turn federation on

Federation is off by default, and SAJHA refuses loopback upstream URLs unless told
otherwise (an SSRF guard). For this tutorial, start SAJHA with both switched on:

```bash
SAJHA_FEDERATION_ENABLED=true SAJHA_FEDERATION_ALLOW_LOCALHOST=true python run_server.py
```

(To make it permanent, set `federation.enabled` and `federation.allow_localhost` in
`config/application.yml`; the keys are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#federation).)

### 3. Add the upstream

Sign in as an administrator and open **Admin → Federation** (`/admin/federation`).

1. Click **Add upstream**.
2. **Id**: `units`. **URL**: `http://127.0.0.1:8765/mcp`. Leave the transport on
   Streamable HTTP, the protocol on `auto` and the credentials on **None**.
3. Click **Test connection**. SAJHA connects, negotiates the protocol (the example speaks
   2026-07-28, so that is what `auto` picks) and lists the four tools.
4. Click **Save**.

The upstream appears as **connected**, and its four tools are listed as **pending**: with
`federation.require_approval` on (the default), nothing an upstream offers is exposed until
an administrator approves it.

The same from the command line, with the admin API (a signed-in session cookie in `jar`):

```bash
curl -s -c jar -d 'user_id=admin&password=<your password>' http://localhost:3002/login -o /dev/null
curl -s -b jar -X POST http://localhost:3002/api/federation/upstreams \
     -H 'content-type: application/json' \
     -d '{"id": "units", "title": "Unit conversions", "url": "http://127.0.0.1:8765/mcp"}'
```

### 4. Review and approve

Each row shows the name the tool will have in SAJHA, its status, the upstream's
description (screened: control characters removed, length capped, injection phrases
replaced and flagged) and its input schema. Approve `celsius_to_fahrenheit`,
`kilometres_to_miles` and `reset_counter`, and leave `countdown` pending.

```bash
curl -s -b jar -X POST http://localhost:3002/api/federation/upstreams/units/items \
     -H 'content-type: application/json' \
     -d '{"kind": "tool", "name": "celsius_to_fahrenheit", "action": "approve"}'
```

Approved tools are now SAJHA tools named `<prefix>__<tool>`: `units__celsius_to_fahrenheit`,
`units__kilometres_to_miles`, `units__reset_counter`. They are on the **Tools** page, in
`tools/list` on both protocol eras, in Ask SAJHA's tool search, and in the composite
builder. If the upstream later changes an approved tool's description or schema, the tool
goes back to **changed** and leaves SAJHA until you approve it again.

### 5. Call a federated tool through SAJHA

From the official SDK, exactly as for a native tool. Take an API key from **Admin → API
keys** (an allowlist of `units__*` grants every tool of this upstream and nothing else):

```python
import asyncio, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    http = httpx2.AsyncClient(headers={"X-API-Key": "sja_..."})
    async with Client(streamable_http_client("http://localhost:3002/mcp", http_client=http)) as c:
        r = await c.call_tool("units__celsius_to_fahrenheit", {"celsius": 37})
        print(r.structured_content)          # {'result': 98.6}
    await http.aclose()

asyncio.run(main())
```

Pass `mode="legacy"` to `Client` to use the 2025-11-25 handshake instead; the result is the
same. The upstream's result (content blocks and `structuredContent`) arrives unchanged, and
the call was checked against your key's access, counted in the tool's metrics, and guarded
by the upstream's circuit breaker on the way.

### 6. Ask SAJHA

Open **AI → Ask SAJHA** and ask *Convert a temperature of 100 degrees Celsius to
Fahrenheit*. The shortlist now includes the federated tool, the model calls
`units__celsius_to_fahrenheit` with `celsius: 100`, and the answer cites its result, 212.
From code: `POST /api/ai/ask` with `{"question": "..."}` (see
[Tutorial 10](TUTORIAL_10_ask_sajha.md)).

### 7. A tool that needs the user

`units__reset_counter` asks the user to confirm. Over 2026-07-28 the upstream answers with
an input request; SAJHA passes it to its own client as an `InputRequiredResult` and carries
the upstream's state, so a client with an elicitation handler completes it:

```python
from mcp_types import ElicitResult

async def confirm(ctx, params):
    print(params.message)                    # Reset counter 'visits' to zero?
    return ElicitResult(action="accept", content={"ok": True})

# Client(..., elicitation_callback=confirm)
r = await c.call_tool("units__reset_counter", {"counter": "visits"})
print(r.structured_content)                  # {'result': 'counter visits reset'}
```

A caller that cannot answer (the 2025-11-25 era, REST, Ask SAJHA) gets a tool error saying
the tool needs client input.

### 8. Watch it fail safely

Stop the upstream server (Ctrl+C). On the Federation page the upstream turns to **error**
with the reason, SAJHA keeps running, the three tools stay listed, and calling one returns a
tool error naming the upstream; after repeated failures its circuit breaker opens. Start
the server again: SAJHA reconnects in the background (backoff up to a minute) and the
calls work again. Use **Refresh** to reconnect and re-discover at once.

## What's next

- Credentials for a real upstream (`bearer`, an API-key header or OAuth client
  credentials, always as secret references) and the SSRF settings:
  [Federation, sections 3 and 9](../architecture/Federation.md#3-credentials-sent-to-an-upstream)
- Grant federated tools to roles and keys: [Security Model](../security/Security%20Model.md)
- Chain a federated tool with native ones: [Tutorial 3](TUTORIAL_03_build_a_composite_tool.md)
