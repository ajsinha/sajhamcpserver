# Tutorial 48: Sandbox Egress and Contained stdio Upstreams

A sandboxed tool that needs the network gets exactly the hosts its policy lists, and nothing else: no
direct network, one egress proxy per run that admits only the listed `host:port`, refuses cloud
metadata, loopback and private addresses, and audits every connection. A federated stdio upstream, which
is someone else's program, runs in a container of its own with the same proxy. This tutorial shows
both. The sandbox, its backends and the proxy are owned by [Sandbox](../architecture/Sandbox.md)
([Network allowlist](../architecture/Sandbox.md#network-allowlist)); stdio upstreams by
[Federation](../architecture/Federation.md#stdio-isolation). It continues
[Tutorial 14](TUTORIAL_14_sandboxed_studio_tools.md), which deploys sandboxed Studio tools.

**What was verified.** Every step below was run as written on Linux (kernel 7.1, unprivileged user
namespaces on, Docker 29) from a checkout, with a scratch SQLite database (`SAJHA_DB_PATH`), cache
directory (`SAJHA_CACHE_DIR`) and directory for loaded results (`SAJHA_BI_SCRATCH_DIR`), the default
`subprocess` sandbox backend and the offline mock LLM provider. The outputs are from that run; container
names, run ids and addresses are your machine's. Steps 2 to 4 need outbound HTTPS from the host; steps 5
to 7 need Docker.

## What you'll learn

- What `GET /api/sandbox/status` says about egress on your host
- How `network: allowlist` turns into a per-run proxy, and what it refuses
- Where every allowed and denied connection is recorded
- How a stdio upstream runs in its own container, and what happens when it dies
- How a contained upstream gets the same egress proxy through a sidecar

## Prerequisites

- A checkout with its virtual environment ([Quick Start](../getting-started/Quick%20Start.md)) and the
  development API key `sja_test_admin_dev_key_0001` from `config/apikeys.json` (role `admin`).
- Linux with unprivileged user namespaces for the `subprocess` backend's proxy mode (without them an
  allowlisted tool is refused rather than given direct network), and Docker for the second half.
- A small helper that calls one tool over MCP with the official SDK, saved as `call.py`:

```python
import asyncio, sys, json, httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async def main(name, args):
    http = httpx2.AsyncClient(headers={"X-API-Key": "sja_test_admin_dev_key_0001"}, timeout=60)
    async with Client(streamable_http_client("http://127.0.0.1:3195/mcp", http_client=http)) as c:
        r = await c.call_tool(name, json.loads(args))
        print(r.content[0].text if r.is_error else r.structured_content)
    await http.aclose()

asyncio.run(main(sys.argv[1], sys.argv[2]))
```

The SDK warns on stderr that it cannot validate a result of a tool it has not listed; the commands below
drop stderr.

## 1. Start the server and read the sandbox status

The second half of the tutorial needs federation with stdio upstreams and an image that contains the
upstream server. Build the image first (it installs the MCP SDK while building, so the running container
needs no network):

```bash
mkdir -p /tmp/t48/image && cp sajha/examples/federation/units_server.py /tmp/t48/image/
cat > /tmp/t48/image/Dockerfile <<'EOF'
FROM python:3.13-slim
RUN pip install --no-cache-dir "mcp>=2.3,<3"
COPY units_server.py /srv/units_server.py
EOF
docker build -q -t sajha-tutorial/units-mcp:1 /tmp/t48/image
```

Then start SAJHA with two stdio upstreams: `units` in a container of that image, and `units_raw` with
`isolation: none`, the old unconfined behaviour, for comparison:

```bash
P=/tmp/t48
export SAJHA_DB_PATH=$P/t48.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  SAJHA_FEDERATION_ENABLED=true SAJHA_FEDERATION_ALLOW_STDIO=true SAJHA_FEDERATION_REQUIRE_APPROVAL=false \
  SAJHA_FEDERATION_STATE_PATH=$P/federation.json SAJHA_FEDERATION_MCP_SERVERS_FILE=$P/mcp_servers.json \
  SAJHA_FEDERATION_UPSTREAMS='[
    {"id":"units","transport":"stdio","command":"python","args":["/srv/units_server.py","--stdio"],
     "container":{"image":"sajha-tutorial/units-mcp:1","memory_mb":256}},
    {"id":"units_raw","transport":"stdio","command":"'$PWD'/.venv/bin/python",
     "args":["sajha/examples/federation/units_server.py","--stdio"],"isolation":"none"}]'
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195
```

(`SAJHA_FEDERATION_REQUIRE_APPROVAL=false` skips the review step of
[Tutorial 11](TUTORIAL_11_federate_an_mcp_server.md) to keep this tutorial short; leave approval on in
production.)

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
curl -s http://127.0.0.1:3195/api/sandbox/status -H "$K" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('active', d['active_backend']); print('egress', d['egress'])
for g in d['guarantees']:
    if 'etwork' in g['guarantee']: print(g['enforced'], '|', g['guarantee'], '|', g['how'])"
```

```text
active subprocess
egress {'mode': 'proxy', 'block_private_networks': True, 'exempt_hosts': [], 'max_connections': 32}
True | Allowlisted network only through the egress proxy: listed host:port only, cloud metadata, loopback and private addresses refused, every connection audited | own network namespace with loopback only; per-run proxy on a Unix socket
True | Network off unless allowlisted | network namespace, seccomp: no sockets, Landlock TCP
```

The guarantees come from a live probe of this host, so a missing kernel feature shows as `False`.

## 2. A tool with no network

Deploy a Python code tool that tries to open each URL it is given (on the console: **MCP Studio**,
Python Code Tool Creator; here through the same endpoint). Save it as `egress_probe.py`:

```python
from sajha.studio import sajhamcptool

@sajhamcptool(description="Try to open each URL and report what happened", category="Test")
def egress_probe(urls: list) -> dict:
    import urllib.request
    out = {}
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                out[url] = f"HTTP {r.status}"
        except Exception as e:
            out[url] = f"{type(e).__name__}: {e}"[:140]
    return out
```

```bash
python3 -c "import json; print(json.dumps({'tool_name':'egress_probe','code':open('egress_probe.py').read()}))" > deploy.json
curl -s -X POST http://127.0.0.1:3195/admin/studio/deploy -H "$K" -H 'Content-Type: application/json' -d @deploy.json
python3 -c "import json; print(json.load(open('config/tools/egress_probe.json'))['sandbox'])"
.venv/bin/python call.py egress_probe '{"urls": ["https://example.com/"]}' 2>/dev/null
```

```text
{"success":true,"message":"Tool \"egress_probe\" deployed successfully!","tool_name":"egress_probe","json_path":"config/tools/egress_probe.json",...}
{'network': 'none'}
{'https://example.com/': 'URLError: <urlopen error [Errno -3] Temporary failure in name resolution>'}
```

Studio gives every generated tool `"sandbox": {"network": "none"}`: the sandbox has no network at all,
not even DNS.

## 3. Allow one host

Edit the tool's configuration (`egress_probe.json` in the `config/tools` folder) so that its `sandbox` block lists `example.com:443`, and, to see
the address rule at work, the cloud metadata address too:

```json
"sandbox": {"network": "allowlist", "allow_hosts": ["example.com:443", "169.254.169.254:80"]}
```

The registry reloads the file within seconds. Call it with three URLs:

```bash
.venv/bin/python call.py egress_probe \
  '{"urls": ["https://example.com/", "https://www.iana.org/", "http://169.254.169.254/latest/meta-data/"]}' 2>/dev/null
```

```text
{'https://example.com/': 'HTTP 200', 'https://www.iana.org/': 'URLError: <urlopen error Tunnel connection failed: 403 Forbidden>', 'http://169.254.169.254/latest/meta-data/': 'HTTPError: HTTP Error 403: Forbidden'}
```

The tool's code did nothing special: the runner set `HTTP_PROXY` and `HTTPS_PROXY` to a bridge on the
sandbox's own loopback, which relays to this run's proxy. The proxy admitted `example.com:443`, refused
a host that is not listed, and refused the metadata address even though it is listed: cloud metadata,
link-local, loopback, multicast and reserved addresses are always refused, and private ranges too
while `sandbox.egress.block_private_networks` is `true`.

## 4. Every connection is audited

```bash
curl -s "http://127.0.0.1:3195/api/audit/records?event=sandbox.egress&limit=3" -H "$K" | python3 -c "
import json,sys
for r in json.load(sys.stdin)['records']:
    d=r['details']; print(r['event'], r['outcome'], d['method'], d['host'], d['port'], '|', d['reason'], '|', r['resource']['id'])"
```

```text
sandbox.egress denied GET 169.254.169.254 80 | blocked address (cloud metadata) | sajha-sbx-2289aa4d72b3
sandbox.egress denied CONNECT www.iana.org 443 | not in sandbox.allow_hosts | sajha-sbx-2289aa4d72b3
sandbox.egress allowed CONNECT example.com 443 | allowed | sajha-sbx-2289aa4d72b3
```

The records are in the tamper-evident audit chain (the **Audit** page), each naming the run and the tool
(`details.tool`). They are also counted (`/metrics` needs an administrator's session or JWT):

```text
sajha_sandbox_egress_total{outcome="allowed"} 1
sajha_sandbox_egress_total{outcome="denied"} 2
```

Remove the tool when you are done:

```bash
curl -s -X POST http://127.0.0.1:3195/admin/studio/delete -H "$K" -H 'Content-Type: application/json' \
  -d '{"tool_name":"egress_probe"}'
```

```text
{"success":true,"message":"Deleted: egress_probe.json, studio_egress_probe.py",...}
```

## 5. A stdio upstream in its own container

```bash
curl -s http://127.0.0.1:3195/api/federation/upstreams -H "$K" | python3 -c "
import json,sys
for u in json.load(sys.stdin)['upstreams']: print(u['id'], u['state'], u['isolation'], u['container_name'])"
docker ps --format '{{.Names}} | {{.Image}}' | grep sajha-fed
N=$(docker ps --format '{{.Names}}' | grep '^sajha-fed-units' | head -1)
docker inspect $N --format 'network={{.HostConfig.NetworkMode}} readonly={{.HostConfig.ReadonlyRootfs}} user={{.Config.User}} memory={{.HostConfig.Memory}} pids={{.HostConfig.PidsLimit}} capdrop={{.HostConfig.CapDrop}} secopt={{.HostConfig.SecurityOpt}}'
```

```text
units connected container sajha-fed-units-1083917-24a3807b
units_raw connected none None
sajha-fed-units-1083917-24a3807b | sajha-tutorial/units-mcp:1
network=none readonly=true user=65534:65534 memory=268435456 pids=64 capdrop=[ALL] secopt=[no-new-privileges]
```

The container has no network, a read-only root with a small writable `/tmp`, the memory asked for
(`container.memory_mb`, capped by `sandbox.max`), a process limit, no capabilities and the `nobody`
user. The only host folders it could see are `container.mounts`, read-only; SAJHA's own tree, the home
folder and the docker socket are refused. `units_raw`, run unconfined because it says `isolation: none`,
raises a warning notice:

```bash
curl -s http://127.0.0.1:3195/api/notices -H "$K" | python3 -c "
import json,sys
for n in json.load(sys.stdin)['notices']:
    if n['id'].startswith('federation.'): print(n['id'], n['severity'], '|', n['detail'])"
```

```text
federation.stdio_unconfined:units_raw warning | units_raw has isolation: none, so its command runs as a subprocess of SAJHA with the server's user, files and network. Remove isolation: none to run it in its own container.
```

Without `isolation`, and with Docker not answering, a stdio upstream is not started at all (notice
`federation.stdio_isolation:<upstream>`) rather than run unconfined.

## 6. The container ends, a new one starts

```bash
.venv/bin/python call.py units__kilometres_to_miles '{"km": 42.195}' 2>/dev/null
docker kill $N >/dev/null; sleep 6
docker ps --format '{{.Names}} | {{.Status}}' | grep sajha-fed
.venv/bin/python call.py units__kilometres_to_miles '{"km": 10}' 2>/dev/null
```

```text
{'result': 26.2187}
sajha-fed-units-1083917-57e57897 | Up 4 seconds
{'result': 6.2137}
```

One container per connection: when it ends, the reconnect loop starts a fresh one (with backoff), and
when SAJHA stops, its containers are removed (a later start also removes any left by a process that
died).

## 7. Egress for a contained upstream

A contained upstream that needs the network says so in its `container` block. Stop SAJHA and start it
again with only the `units` upstream, now allowed to reach `example.com:443`:

```bash
export SAJHA_FEDERATION_UPSTREAMS='[{"id":"units","transport":"stdio","command":"python",
  "args":["/srv/units_server.py","--stdio"],"container":{"image":"sajha-tutorial/units-mcp:1",
  "memory_mb":256,"network":"allowlist","allow_hosts":["example.com:443"]}}]'
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195
```

The container now shares the network namespace of a sidecar (`<name>-egress`) whose only process
bridges its loopback to this container's egress proxy:

```bash
docker ps --format '{{.Names}} | {{.Image}}' | grep sajha-fed
N=$(docker ps --format '{{.Names}}' | grep '^sajha-fed-units' | grep -v egress)
docker exec $N sh -c 'env | grep ^HTTPS_PROXY'
docker exec $N python -c "
import urllib.request
for u in ('https://example.com/', 'https://www.iana.org/'):
    try: print(u, urllib.request.urlopen(u, timeout=10).status)
    except Exception as e: print(u, type(e).__name__, e)"
```

```text
sajha-fed-units-1089133-1b88f146 | sajha-tutorial/units-mcp:1
sajha-fed-units-1089133-1b88f146-egress | python:3.13-slim
HTTPS_PROXY=http://127.0.0.1:3128
https://example.com/ 200
https://www.iana.org/ URLError <urlopen error Tunnel connection failed: 403 Forbidden>
```

The audit records name the container:

```text
denied {"id": "sajha-fed-units-1089133-1b88f146", "type": "sandbox_run"} www.iana.org | not in sandbox.allow_hosts
allowed {"id": "sajha-fed-units-1089133-1b88f146", "type": "sandbox_run"} example.com | allowed
```

Stop SAJHA; the container and its sidecar are removed with it.

## Summary

- `network: allowlist` gives a sandboxed tool no direct network, only a per-run proxy that admits the
  listed `host:port` and refuses metadata, loopback and (by default) private addresses
- Every connection the proxy allows or denies is a `sandbox.egress` audit record and counts in
  `sajha_sandbox_egress_total`
- A stdio upstream runs in its own confined container, one per connection, restarted when it ends;
  `isolation: none` runs it unconfined and raises a warning notice
- `container.network: allowlist` gives a contained upstream the same proxy through a sidecar

## Next

- Backends, limits and the warm container pool: [Sandbox](../architecture/Sandbox.md)
- [Tutorial 49: Signed Plugins and the Plugin Catalog](TUTORIAL_49_signed_plugins.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
