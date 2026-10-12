# Tutorial 47: Federation at Gateway Scale

[Tutorial 11](TUTORIAL_11_federate_an_mcp_server.md) federated one MCP server into SAJHA. This tutorial
runs SAJHA as a gateway in front of it: two workers, a pool of connections per upstream, two replica
endpoints, a bound on calls in flight with a queue and load shedding, the upstream's prompts and
resources carried through, and a shared health view in which one worker's open breaker opens the
other's. It ends with the federation load harness. Everything about federation, including the
features not shown here (resource templates, completions, subscriptions, upstream tasks, relayed
sampling and elicitation), is owned by [Federation](../architecture/Federation.md); the gateway part
is its [Gateway scale](../architecture/Federation.md#gateway-scale) section, and every `federation.*`
key is in the [Configuration Reference](../getting-started/Configuration%20Reference.md#federation).

**What was verified.** Every step below was run as written on a checkout, with a scratch SQLite
database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`) and directory for loaded results
(`SAJHA_BI_SCRATCH_DIR`), the default offline mock LLM provider, and the example upstream
`sajha/examples/federation/units_server.py`. The outputs shown are from that run; worker ids, timings,
which worker took which call, and throughput are your machine's.

## What you'll learn

- How to configure an upstream with a connection pool, replicas and an admission bound
- How a call over the bound is refused at once, safely, and where shed calls are counted
- How the upstream's prompts and resources are exposed under SAJHA's names
- How each worker publishes its view of the upstream, and how a breaker opened on one worker opens
  on the others
- How `tools/bench/bench_federation.py` measures proxied calls and shedding

## Prerequisites

- A checkout with its virtual environment ([Quick Start](../getting-started/Quick%20Start.md)) and the
  development API key `sja_test_admin_dev_key_0001` from `config/apikeys.json` (role `admin`).
- [Tutorial 11](TUTORIAL_11_federate_an_mcp_server.md) for the basics (approval, namespacing, the
  Proxied MCP servers page). The examples use the upstream on port 3196 and SAJHA on port 3195.

## 1. Start the upstream

```bash
.venv/bin/python sajha/examples/federation/units_server.py --port 3196
```

It serves four tools (`celsius_to_fahrenheit`, `kilometres_to_miles`, `countdown`, `reset_counter`),
one prompt and one resource on both protocol eras.

## 2. Start SAJHA with a pooled, bounded upstream on two workers

The upstream comes from `SAJHA_FEDERATION_UPSTREAMS` (a JSON list; the same fields go in
`federation.upstreams` in the YAML, or in the mcpServers file). `urls` adds a second replica: here the
same server under another host name, so that both replicas exist on one machine; in production each
would be another instance. `pool_size: 3` opens three connections per replica in each worker;
`max_in_flight: 2` with `max_queue: 2` lets two calls run per worker and two wait.

```bash
P=/tmp/t47; mkdir -p $P
export SAJHA_DB_PATH=$P/t47.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  SAJHA_STATE_BACKEND=database \
  SAJHA_FEDERATION_ENABLED=true SAJHA_FEDERATION_ALLOW_LOCALHOST=true \
  SAJHA_FEDERATION_STATE_PATH=$P/federation.json SAJHA_FEDERATION_MCP_SERVERS_FILE=$P/mcp_servers.json \
  SAJHA_FEDERATION_UPSTREAMS='[{"id":"units","url":"http://127.0.0.1:3196/mcp",
    "urls":["http://localhost:3196/mcp"],"pool_size":3,"max_in_flight":2,"max_queue":2,
    "expose_prompts":true,"expose_resources":true}]'
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195 --workers 2
```

`state.backend: database` is what lets the two workers share their view of the upstream (step 6);
`SAJHA_FEDERATION_STATE_PATH` keeps this tutorial's approvals out of `config/federation/`.

## 3. Read the upstream's status

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
curl -s http://127.0.0.1:3195/api/federation/upstreams/units -H "$K" | python3 -c "
import json,sys; u=json.load(sys.stdin)
for k in ('state','protocol_version','counts','pool','replicas','admission'): print(k, json.dumps(u.get(k)))
for it in u['items']: print(it['kind'], it['name'], it['status'])"
```

```text
state "connected"
protocol_version "2026-07-28"
counts {"pending": 6, "approved": 0, "changed": 0, "rejected": 0, "disabled": 0, "invalid": 0}
pool {"size": 3, "connections": 6, "connected": 6}
replicas [{"replica": 0, "url": "http://127.0.0.1:3196/mcp", "connections": 3, "connected": 3, "primary": true, "in_flight": 0, "fail_streak": 0, "latency_ms": null}, {"replica": 1, "url": "http://localhost:3196/mcp", "connections": 3, "connected": 3, "primary": false, "in_flight": 0, "fail_streak": 0, "latency_ms": null}]
admission {"limit": 2, "queue": 2, "queue_timeout_seconds": 5.0, "in_flight": 0, "waiting": 0, "admitted": 0, "queued_total": 0, "shed": 0, "peak_in_flight": 0}
tool celsius_to_fahrenheit pending
tool countdown pending
tool kilometres_to_miles pending
tool reset_counter pending
prompt explain_conversion pending
resource units://table pending
```

Six connections: three on each replica. The primary connection (on replica 0) runs discovery and
change listening; the others carry only `tools/call`, each call taking the least busy one. The same
fields are on the **Proxied MCP servers** page (Admin, `/admin/federation`).

## 4. Approve

Nothing is exposed until an administrator approves it. Approve every tool, prompt and resource (on the
page: **Approve all**):

```bash
for k in tool prompt resource; do
  curl -s -X POST http://127.0.0.1:3195/api/federation/upstreams/units/items -H "$K" \
    -H 'Content-Type: application/json' -d '{"kind":"'$k'","action":"approve_all"}'; echo
done
```

```text
{"ok":true,"changed":4}
{"ok":true,"changed":1}
{"ok":true,"changed":1}
```

The approval is saved in the federation store and announced on the shared state store, so the other
worker applies it at once: both report `approved: 6`, whichever worker answers. No restart is needed.

## 5. Prompts, resources and tools through SAJHA

From the official MCP SDK. SAJHA's catalog is paged, so list it page by page:

```python
import asyncio, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main():
    http = httpx2.AsyncClient(headers={"X-API-Key": "sja_test_admin_dev_key_0001"})
    async with Client(streamable_http_client("http://127.0.0.1:3195/mcp", http_client=http)) as c:
        names, cursor = [], None
        while True:                                   # SAJHA's catalog is paged
            page = await c.list_tools(cursor=cursor)
            names += [t.name for t in page.tools]
            cursor = page.next_cursor
            if not cursor:
                break
        print("tools:", sorted(n for n in names if n.startswith("units__")))
        prompts = await c.list_prompts()
        print("prompts:", [p.name for p in prompts.prompts if p.name.startswith("units__")])
        res = await c.list_resources()
        print("resources:", [str(r.uri) for r in res.resources if "units" in str(r.uri)])
        p = await c.get_prompt("units__explain_conversion", {"unit_from": "km", "unit_to": "mile"})
        print("prompt text:", p.messages[0].content.text)
        uri = [str(r.uri) for r in res.resources if "units" in str(r.uri)][0]
        r = await c.read_resource(uri)
        print("resource:", r.contents[0].text.splitlines()[:2])
        r = await c.call_tool("units__celsius_to_fahrenheit", {"celsius": 37})
        print("call:", r.structured_content)
    await http.aclose()

asyncio.run(main())
```

```text
tools: ['units__celsius_to_fahrenheit', 'units__countdown', 'units__kilometres_to_miles', 'units__reset_counter']
prompts: ['units__explain_conversion']
resources: ['sajha-federation://units/units%3A%2F%2Ftable']
prompt text: Explain how to convert km to mile, with one worked example.
resource: ['unit,to,factor', 'km,mile,0.621371']
call: {'result': 98.6}
```

The prompt keeps the `units__` prefix; the resource is listed under SAJHA's own URI
(`sajha-federation://<upstream>/<the upstream's URI, encoded>`) and read from the upstream.

## 6. Load shedding

`units__countdown` with two steps a second apart takes about two seconds. Twelve clients call it at
once (the SDK's warning that it cannot validate the result of a tool it has not listed goes to stderr,
dropped here):

```python
import asyncio, collections, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def one(i):
    http = httpx2.AsyncClient(headers={"X-API-Key": "sja_test_admin_dev_key_0001"}, timeout=30)
    async with Client(streamable_http_client("http://127.0.0.1:3195/mcp", http_client=http)) as c:
        r = await c.call_tool("units__countdown", {"steps": 2, "seconds_per_step": 1.0})
    await http.aclose()
    return r.content[0].text if r.is_error else "ok: " + str(r.structured_content)

async def main():
    results = await asyncio.gather(*(one(i) for i in range(12)))
    for text, n in collections.Counter(results).most_common():
        print(n, "x", text)

asyncio.run(main())
```

```text
7 x Tool execution failed: upstream units is at capacity (2 calls in flight, limit 2; 2 waiting, queue 2): its queue is full. Nothing was sent; retry in a moment.
5 x ok: {'result': 'lift-off'}
```

The bound is per worker; in this run every call landed on one worker, so two ran, two waited in the
queue and the rest were refused at once. A refused call is never sent to the upstream, so it is safe to
retry whatever the tool does, and it counts neither as a failure nor against the breaker. The status and
the metrics record it:

```bash
curl -s http://127.0.0.1:3195/api/federation/upstreams/units -H "$K" | python3 -c "
import json,sys; u=json.load(sys.stdin); print('admission', json.dumps(u['admission']))
c=u['cluster']; print('cluster', json.dumps({k: c[k] for k in ('reporting','connected','breaker_open','in_flight','shed')}))"
T=$(curl -s -X POST http://127.0.0.1:3195/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"testadmin","password":"testadmin-dev-1"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s http://127.0.0.1:3195/metrics -H "Authorization: Bearer $T" \
  | grep -E "^sajha_federation_(upstream_shed_total|pool_connections_connected)"
```

```text
admission {"limit": 2, "queue": 2, "queue_timeout_seconds": 5.0, "in_flight": 0, "waiting": 0, "admitted": 4, "queued_total": 2, "shed": 7, "peak_in_flight": 2}
cluster {"reporting": 2, "connected": 2, "breaker_open": [], "in_flight": 0, "shed": 7}
sajha_federation_upstream_shed_total{upstream="units",worker="oryxpro:1068495:75e1e8"} 7
sajha_federation_upstream_shed_total{upstream="units",worker="oryxpro:1068496:291841"} 0
sajha_federation_pool_connections_connected{upstream="units",replica="0",worker="oryxpro:1068495:75e1e8"} 3
sajha_federation_pool_connections_connected{upstream="units",replica="1",worker="oryxpro:1068495:75e1e8"} 3
sajha_federation_pool_connections_connected{upstream="units",replica="0",worker="oryxpro:1068496:291841"} 3
sajha_federation_pool_connections_connected{upstream="units",replica="1",worker="oryxpro:1068496:291841"} 3
```

`cluster` is every worker's published view, read from the state store (`fed:health:<upstream>:<worker>`).
`/metrics` needs an administrator's session or JWT, not an API key (`testadmin` is the development user
in `config/users.json`).

## 7. One worker's breaker opens the others'

Stop the upstream (Ctrl+C in its terminal), then call `units__celsius_to_fahrenheit` eight times in a row
on one MCP connection:

```python
import asyncio, sys, time, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main(n):
    http = httpx2.AsyncClient(headers={"X-API-Key": "sja_test_admin_dev_key_0001"}, timeout=60)
    async with Client(streamable_http_client("http://127.0.0.1:3195/mcp", http_client=http)) as c:
        for i in range(n):
            t = time.monotonic()
            r = await c.call_tool("units__celsius_to_fahrenheit", {"celsius": i})
            text = r.content[0].text if r.is_error else str(r.structured_content)
            print(f"{i + 1}: {time.monotonic() - t:5.2f}s {text[:110]}")
    await http.aclose()

asyncio.run(main(int(sys.argv[1])))
```

```text
1:  0.27s Tool execution failed: upstream units connection failed: MCP error -32000: Connection closed
2:  0.26s Tool execution failed: upstream units connection failed: MCP error -32000: Connection closed
3:  0.26s Tool execution failed: upstream units connection failed: MCP error -32000: Connection closed
4: 35.29s Tool execution failed: upstream units is not connected (ConnectError: All connection attempts failed)
5: 35.31s Tool execution failed: upstream units is not connected (ConnectError: All connection attempts failed)
6:  0.01s Tool execution failed: Service temporarily unavailable for units__celsius_to_fahrenheit (circuit breaker open)
7:  0.01s Tool execution failed: Service temporarily unavailable for units__celsius_to_fahrenheit (circuit breaker open)
8:  0.01s Tool execution failed: Service temporarily unavailable for units__celsius_to_fahrenheit (circuit breaker open)
```

After five failures the worker's breaker opened and later calls failed in milliseconds. (Calls 4 and 5
waited out the upstream's reconnection attempt before failing.) The four tools stay listed throughout. A
few seconds later, the other worker, which made no call at all, has opened its breaker too, following
its peer:

```bash
curl -s http://127.0.0.1:3195/api/federation/upstreams/units -H "$K" | python3 -c "
import json,sys; c=json.load(sys.stdin)['cluster']; print('breaker_open', c['breaker_open'])
for w in c['workers']: print(' ', w['worker'], 'self' if w['self'] else 'peer', w['state'], 'breaker', w['breaker'], w['breaker_source'])"
```

```text
breaker_open ['oryxpro:1068495:75e1e8', 'oryxpro:1068496:291841']
  oryxpro:1068495:75e1e8 peer connected breaker open peer
  oryxpro:1068496:291841 self error breaker open local
```

`breaker_source: peer` marks a breaker opened by following (`federation.health.follow_peer_breakers`,
on by default); a followed breaker is never followed in turn. Start the upstream again. Each worker
reconnects in the background and, after its breaker's recovery timeout (60 seconds by default), lets one
call through and closes on success:

```text
1:  0.03s {'result': 32.0}
2:  0.03s {'result': 33.8}
3:  0.02s {'result': 35.6}
```

```text
breaker_open ['oryxpro:1068496:291841'] [('75e1e8', 'closed'), ('291841', 'open')]
```

The worker that took those calls closed its breaker; the other closes its own on its next call.

## 8. Measure proxied calls

Stop SAJHA and the upstream. `tools/bench/bench_federation.py` starts the example upstream and a SAJHA
per configuration (`backend:workers:pool_size`) with federation on, and runs three phases: a local tool
as the baseline, a proxied tool, and a slow proxied tool against a tight `max_in_flight` with no queue,
so that most calls are shed:

```bash
for c in memory:1:1 memory:1:4; do
  .venv/bin/python tools/bench/bench_federation.py --configs $c --duration 5 --warmup 1 \
    --port 3195 --upstream-port 3196 --out $P/bench --scratch $P
done
```

```text
[bench-federation] memory:1 pool 1: starting on port 3195
[bench-federation]   local       309.0 req/s  p50 92.65 ms  p95 173.95 ms  p99 305.08 ms  shed 0  errors 0
[bench-federation]   proxied     214.6 req/s  p50 135.47 ms  p95 219.91 ms  p99 288.58 ms  shed 0  errors 0
[bench-federation]   shed         27.2 req/s  p50 183.34 ms  p95 566.67 ms  p99 689.52 ms  shed 1206  errors 0
[bench-federation] memory:1 pool 4: starting on port 3195
[bench-federation]   local       309.0 req/s  p50 92.49 ms  p95 158.78 ms  p99 286.64 ms  shed 0  errors 0
[bench-federation]   proxied     207.2 req/s  p50 143.34 ms  p95 223.9 ms  p99 283.82 ms  shed 0  errors 0
[bench-federation]   shed         26.8 req/s  p50 185.85 ms  p95 499.36 ms  p99 565.45 ms  shed 1158  errors 0
```

Shed calls are counted apart from errors. On this short run, on a machine shared by the upstream, SAJHA
and the load generator, four connections made no difference; how much a pool helps depends on where the
time goes. The published run and its conditions are in
[Scaling and State §9](../architecture/Scaling%20and%20State.md#9-measured-performance). Each configuration
takes the next port after `--port`, so run one configuration at a time when the upstream's port follows
SAJHA's.

## Summary

- `pool_size`, `urls`, `max_in_flight`, `max_queue` and `federation.queue_timeout_seconds` make one
  upstream a pooled, replicated, bounded backend; every field can be set per upstream or under
  `federation.*`
- A call over the bound is refused at once with a retryable error, never sent, and counted in
  `admission.shed` and `sajha_federation_upstream_shed_total`
- `expose_prompts` and `expose_resources` carry the upstream's prompts and resources under SAJHA's names
- With a shared state store, every worker publishes its view (`cluster`), and a breaker opened on one
  worker opens the others'
- `tools/bench/bench_federation.py` measures local, proxied and shed calls

## Next

- Everything federation does, and its limits: [Federation](../architecture/Federation.md)
- [Tutorial 48: Sandbox Egress and Contained stdio Upstreams](TUTORIAL_48_sandbox_egress.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
