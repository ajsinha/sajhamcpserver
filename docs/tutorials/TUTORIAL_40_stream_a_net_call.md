# Tutorial 40: Stream a Call Across the Net

A tool that runs on another SAJHA Net member should feel like a local one: its progress reaches you as
the work goes on, you can cancel it, and it can ask you a question. This tutorial shows all three on the
[local test lab](TUTORIAL_29_local_test_lab.md): `cust-na` calls a slow tool that `risk-eu` hosts, you
watch its progress arrive event by event, cancel a second run, compare the two servers' audit records
of the same stream, and answer a remote tool's question. The design is
[SAJHA Net](../architecture/SAJHA%20Net.md) section 9; the wire format is the
[SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md) §8.9, §15.6 and §15.10.

## What you'll learn

- How a forwarded call streams: who asks for it, what flows, and how each event is protected
- How cancellation travels from your client to the tool on the other server
- What the transcript digest in both servers' audit records proves
- How an input request (MRTR) crosses the net and comes back

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), started with a Python that
  has the MCP SDK (`risk-eu` proxies the units example server; `lab.sh start` warns if the SDK is
  missing)
- `curl` and `python3`

## Steps

### 1. Offer two more tools of the units server

`risk-eu` proxies the units example server (`sajha/examples/federation/units_server.py`) and offers its
tools to the net as `units__<tool>`. The lab offers only two of them; add `countdown` (reports progress,
`seconds_per_step` apart) and `reset_counter` (asks you to confirm). Edit `risk-eu`'s
`mcp_servers.json`, in `run/risk-eu/config/` of the lab folder (`deployment/local-lab`), so the `tools`
list reads:

```json
"tools": ["celsius_to_fahrenheit", "kilometres_to_miles", "countdown", "reset_counter"]
```

Restart `risk-eu` and give the others a catalog refresh (the lab refreshes every 30 seconds):

```bash
deployment/local-lab/lab.sh stop risk-eu
deployment/local-lab/lab.sh start risk-eu
sleep 35
curl -s http://127.0.0.2:3003/api/tools/list -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; print([t['name'] for t in json.load(sys.stdin)['tools'] if 'units' in t['name']])"
```

`cust-na` now lists `units__countdown` and `units__reset_counter` (and their qualified names
`lab-net__risk-eu__units__...`).

### 2. Check that both sides stream

A home asks for a stream only from a host whose member record lists `streaming`:

```bash
curl -s "http://127.0.0.2:3003/api/sajhanet/overview?net=lab-net" -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; [print(m['name'], m['features']) for m in json.load(sys.stdin)['net']['members']]"
```

The other members (seen from `cust-na`) each list `streaming`, `progress`, `cancellation` and `mrtr`, because
`sajhanet.streaming.enabled` is on (the default; the keys are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)).

### 3. Watch progress arrive

Call the remote tool on `cust-na` over MCP 2026-07-28, asking for progress with a `progressToken`. The
script prints each line with the time it arrived:

```bash
curl -sN http://127.0.0.2:3003/mcp \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' -H 'Mcp-Name: units__countdown' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"units__countdown",
       "arguments":{"steps":5,"seconds_per_step":0.5},
       "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                "io.modelcontextprotocol/clientCapabilities":{},
                "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},
                "progressToken":"tok-1"}}}' \
  | while IFS= read -r line; do [ -n "$line" ] && echo "$(date +%T.%N | cut -c1-12) ${line:0:120}"; done
```

```text
16:34:46.710 data: {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "tok-1", "progress": 1.0, ...
16:34:47.210 data: {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "tok-1", "progress": 2.0, ...
16:34:47.712 data: ... "progress": 3.0 ...
16:34:48.213 data: ... "progress": 4.0 ...
16:34:48.716 data: ... "progress": 5.0 ...
16:34:49.224 data: {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "lift-off"}], ...
```

The events come half a second apart, as the tool reports them, not all at the end. What happened:

1. `cust-na` (the home) resolved `units__countdown` to `risk-eu` and sent a signed `tools/call` with
   `_meta["io.sajha/net"].stream = 1` and a progress token of its own for this hop.
2. `risk-eu` (the host) ran its checks, then answered with a signed event stream: the units server's
   progress, each event signed into an **event chain** (its signature covers a hash of every event
   before it), then the final answer, which closes the chain.
3. `cust-na` verified each event before relaying it to you, under your own token `tok-1`. A forged,
   reordered, dropped or spliced event would have ended the call with `event_invalid` or `event_order`.

The same call over the other transports (2025-11-25 HTTP with SSE, HTTP+SSE, WebSocket, stdio) relays the
progress the same way; REST and A2A get the final result only
([MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md), "Progress and cancellation per transport").

### 4. Cancel a remote call

Start a 20-second countdown and stop listening after three seconds. On 2026-07-28 closing the response
stream cancels the request:

```bash
timeout 3 curl -sN http://127.0.0.2:3003/mcp \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' -H 'Mcp-Name: units__countdown' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"units__countdown",
       "arguments":{"steps":20,"seconds_per_step":1},
       "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                "io.modelcontextprotocol/clientCapabilities":{},
                "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},
                "progressToken":"tok-2"}}}'
sleep 5
grep 'units__countdown' deployment/local-lab/run/risk-eu/server.log | tail -1
```

```text
... | ERROR | FederatedTool | Tool execution failed: units__countdown - cancelled by the client
```

The cancellation went all the way: your closed stream cancelled the call at `cust-na`, which closed its
stream to `risk-eu`, whose tool context was cancelled, and the federated tool cancelled its request to
the units server. The host notices a closed stream the next time it writes (an event or a heartbeat),
so this can take a few seconds.

### 5. Compare both sides' audit records

Each side audits the call: `cust-na` a `net.call_attempt`, `risk-eu` a `net.host_call`. Both carry the
trace id, whether the call streamed, the number of events and the **transcript digest**, the event
chain's final hash:

```bash
for q in "127.0.0.2:3003/api/audit/records?event=net.call_attempt&limit=3" \
         "127.0.0.1:3002/api/audit/records?event=net.host_call&limit=3"; do
  curl -s "http://$q" -H 'X-API-Key: sja_test_admin_dev_key_0001' | python3 -c "
import json,sys
for r in json.load(sys.stdin)['records']:
    d = r['details']; print(r['event'], d['trace_id'][:8], d['outcome'], d['events'], d['transcript'][:16])"
done
```

```text
net.call_attempt da1d9dbb cancelled 4 f7fae88ce86b35d0
net.call_attempt 289f191c answered 5 5fb5d8421b82a095
net.host_call da1d9dbb cancelled 6 be80e99425b83df6
net.host_call 289f191c ok 5 5fb5d8421b82a095
```

Newest first; match the rows by trace id (yours differ). For the completed call (step 3) the two
digests are equal: both servers saw the same events in the same
order, and either audit chain can show it. For the cancelled call they differ, as they should: the host
wrote events after you left that the home never read.

### 6. Answer a remote tool's question

On `risk-eu`, where the units server is proxied, the shipped policy for proxied writes (`config/policies/20-proxied-writes.yaml`) holds it for approval before it
reaches the upstream, because it declares no `readOnlyHint`
([Policy and Audit §5.1](../architecture/Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)). For this step
set `enabled: false` in that file (the lab's servers share it; it is reloaded within seconds), and set
it back to `true` when you put the lab back.

`units__reset_counter` asks you to confirm before it resets. Call it as a 2026-07-28 client that can
answer form elicitations, then answer with the `requestState` you were given:

```bash
call() {
curl -s http://127.0.0.2:3003/mcp \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' -H 'Mcp-Name: units__reset_counter' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"units__reset_counter",
       "arguments":{"counter":"visits"},
       "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                "io.modelcontextprotocol/clientCapabilities":{"elicitation":{"form":{}}},
                "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"}}'"$1"'}}'
}
R1=$(call "")
echo "$R1" | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['resultType'], r['inputRequests']['confirm']['params']['message'])"
STATE=$(echo "$R1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["requestState"])')
call ',"inputResponses":{"confirm":{"action":"accept","content":{"ok":true}}},"requestState":"'"$STATE"'"' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['content'][0]['text'])"
```

```text
input_required Reset counter 'visits' to zero?
counter visits reset
```

Three states were nested in that one `requestState`: `cust-na` signed its own for you, with `risk-eu`'s
inside it, and `risk-eu`'s carries the units server's. `risk-eu` bound its state to `lab-net`, to
`cust-na` and to you (`lab-net/cust-na/testadmin`); a state presented by another server or for another
user is refused before the tool runs (`state_invalid`). Your answer passed `cust-na`'s residency rules
before it left, like arguments do.

A client that cannot answer questions gets a plain tool error instead:

```bash
curl -s -X POST http://127.0.0.2:3003/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' -d '{"tool":"units__reset_counter","arguments":{"counter":"visits"}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['content'][0]['text'])"
```

```text
units__reset_counter needs input from you; call it over MCP 2026-07-28 from a client that can answer input requests
```

### 7. Put the lab back

Remove `countdown` and `reset_counter` from `risk-eu`'s `mcp_servers.json` and restart it, or reset
`risk-eu` (`lab.sh reset risk-eu`, which regenerates its folder).

## What you learned

- A home asks for a stream only from a host that lists `streaming`; events are relayed as they come,
  under your own progress token, on whichever transport you used
- Every event is signed into an event chain; one bad event ends the call, and nothing after it reaches
  you
- Closing your stream cancels the tool on the other server, through a federated tool to its upstream
- Equal transcript digests in the home's and the host's audit records prove they saw the same stream
- Input requests cross the net as `input_required` results with a host-signed state bound to the server
  and the user; the answer travels back as a new signed request
- Run as a task, a remote call is held by the host that runs it (a host listing `tasks`): your server's
  task follows it with signed `tasks/get` and `tasks/cancel`, so it outlives a restart of your server and
  the hop's deadline ([SAJHA Net](../architecture/SAJHA%20Net.md) section 9, "Tasks")

## Next

- The design: [SAJHA Net](../architecture/SAJHA%20Net.md) section 9; the wire:
  [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md) §8.9, §15.6, §15.10
- Next: [Tutorial 41: qlrisk Risk Tools](TUTORIAL_41_qlrisk_risk_tools.md), risk analytics as native SAJHA
  tools

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
