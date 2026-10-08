# Tutorial 33: Proxied MCP Servers

A SAJHA instance can embed other MCP servers and proxy calls to them: their tools join its catalog and
every call passes its governance (access, policies, approvals, audit). You list them in the
**mcpServers file**, the JSON shape Claude Desktop, Cursor and VS Code use. In a SAJHA Net each entry is
either **external** (the default: a vendor's server, offered to the other members by this instance under
the vendor's prefix, never a member itself) or **internal** (`"external": false`: an ordinary federation
upstream, governed like this instance's own tools). This tutorial uses the units example server over stdio, so it
runs offline, on the [local test lab](TUTORIAL_29_local_test_lab.md). The file and federation are in
[Federation](../architecture/Federation.md); vendors and external servers in
[SAJHA Net](../architecture/SAJHA%20Net.md) section 5.6.

## What you'll learn

- What the mcpServers file holds, where it lives and how a change applies without a restart
- How an external server's tools are named here (`<prefix>__<tool>`) and in the net
  (`<net>__<instance>__<prefix>__<tool>`), and why they never collide with another vendor's
- How an internal entry differs, and how sponsoring makes a server a member instead
- Where the templates are, and what `sajhanet.external_servers` adds

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)) with the MCP SDK installed
  in its Python (`pip install "mcp>=2.3,<3"`)

## Steps

### 1. The file risk-eu already has

The lab gave `risk-eu` an mcpServers file (`federation.mcp_servers_file`, in the lab
`run/risk-eu/config/mcp_servers.json`; on a normal install `config/mcp_servers.json`, git-ignored
because it may hold credentials):

```json
{"mcpServers": {
  "units": {
    "command": "/path/to/python",
    "args": [".../sajha/examples/federation/units_server.py", "--stdio"],
    "vendor": "units",
    "tools": ["celsius_to_fahrenheit", "kilometres_to_miles"]
  }
}}
```

`command` and `args` start the server over stdio as a process of SAJHA, which needs
`federation.allow_stdio: true` (the lab sets it on `risk-eu`, with `federation.enabled: true`, and
turns off `federation.require_approval`, which otherwise holds newly discovered tools until an
administrator approves them on that page). `vendor`
names the organisation that answers for the tools (default: the entry's key); `tools` takes only the
listed tools (globs work). A `url` instead of a `command` means Streamable HTTP; `headers` carry a
credential, preferably as `${ENV_NAME}`. Keys starting with `_` are comments.

**Admin > Proxied MCP servers** (`/admin/federation`) on `risk-eu` shows the server connected, with its
two tools.

### 2. External: offered into the net under the vendor's prefix

On `risk-eu` the tools are `units__celsius_to_fahrenheit` and `units__kilometres_to_miles`. The lab's
export rule names `units__*`, so `risk-eu` offers them into `lab-net` as its own; every member sees
`lab-net__risk-eu__units__celsius_to_fahrenheit`, and the plain `units__celsius_to_fahrenheit`, with
`vendor: units` and `external: true` in `_meta["io.sajha/net"]`:

```bash
curl -s http://127.0.0.2:3003/api/tools/list -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; [print(t['name'], t['_meta']['io.sajha/net'].get('vendor'), t['_meta']['io.sajha/net'].get('external')) for t in json.load(sys.stdin)['tools'] if 'units__' in t['name']]"
curl -s -X POST http://127.0.0.2:3003/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' -d '{"tool": "units__celsius_to_fahrenheit", "arguments": {"celsius": 21}}' | head -c 160; echo
```

The call from `cust-na` went to `risk-eu`, which applied its export rules, access, policies and audit and
then called the server. The server never gossips, has no certificate and is not on the Instances page;
its address and any credential stay on `risk-eu`.

Why the prefix: one name, one contract is right inside one organisation, but servers from different
vendors often share names (`search`, `fetch`) with different schemas, and the net would quarantine the
name although nobody did anything wrong. Under their vendor's prefix, `acme__search` and
`globex__search` never meet. Two instances that both define acme's server and offer the same
`acme__search` are one fallback set for that name; two that claim one vendor with different contracts are
a loud quarantine.

### 3. Internal: governed like this server's own tools

Add an entry marked `"external": false` to `risk-eu`'s file, using the same server under another name:

```bash
python3 - <<'EOF'
import json
p = 'deployment/local-lab/run/risk-eu/config/mcp_servers.json'
d = json.load(open(p))
u = d['mcpServers']['units']
d['mcpServers']['convert'] = {'command': u['command'], 'args': u['args'], 'external': False,
                              'tools': ['kilometres_to_miles']}
json.dump(d, open(p, 'w'), indent=2)
EOF
```

No restart: SAJHA checks the file's modification time and size every
`federation.mcp_servers_reload_seconds` (5). Within seconds `risk-eu` lists `convert__kilometres_to_miles`
(the federation name: the entry's prefix, then the tool, with `_meta["sajha/federation"]`).

An internal server's tools are treated like `risk-eu`'s own: they keep their federation names, carry no
vendor or `external` mark, fall under one name, one contract with every other member's tools, and go into
the net only when an export rule names them. The lab's rule does not, so `cust-na` does not see
`convert__kilometres_to_miles` yet. Name it in `run/risk-eu/local.yml` (a net entry there replaces the
lab's whole, so repeat it):

```yaml
sajhanet:
  nets:
    - name: lab-net
      instance_name: risk-eu
      seeds: []
      export: [{tools: [calc_*, llm_*, units__*, convert__*]}]
      import: [{tools: ['*']}]
```

Restart `risk-eu`, and `cust-na` lists `lab-net__risk-eu__convert__kilometres_to_miles` (and the plain
`convert__kilometres_to_miles`), which answers `6.2137` for `{"km": 10}`. Use internal entries for your
own teams' servers, and external entries for vendors' servers, whose tool names you do not control.

To make a server a **member** of the net instead, with an instance name of its own, sponsor it
([Tutorial 34](TUTORIAL_34_sponsor_a_server_and_the_net_agent.md)) or run the SAJHA Net agent in front
of it.

### 4. The same with configuration keys

The mcpServers file is one way in. Federation upstreams defined in `application.yml` become external
servers when `sajhanet.external_servers` lists them with a vendor:

```yaml
federation:
  upstreams:
    - {id: units, url: "http://127.0.0.1:8765/mcp"}
sajhanet:
  external_servers:
    - {upstream: units, vendor: units, tools: ["*"], rename: {kilometres_to_miles: km_to_miles}}
```

Entries take `upstream`, `vendor` (required), `prefix` (default the vendor), `tools`, `rename` (a
published name of your choosing, under the same contract rule) and `nets` (default every net). An
upstream listed both there and in the mcpServers file uses the `sajhanet.external_servers` entry. A
published name that would make a qualified name longer than 128 characters is not offered; a notice
suggests `rename`.

### 5. The templates

`config/mcp_servers.json.example` and the files in `config/mcp_servers/` are ready-made entries: local
servers over stdio with `npx`, `uvx` or `docker run -i`, hosted servers with a bearer token or none, the
legacy SSE transport, servers that need each user's OAuth sign-in (kept disabled: not supported yet), and
internal entries. Their [README](../../config/mcp_servers/README.md) lists every key. The `npx`, `uvx` and
hosted templates fetch packages or reach the internet; check each server against its maintainer's
documentation, and narrow what you expose with `tools`.

### 6. Clean up

Remove the `convert` entry from the file (it disappears within seconds) and delete
`run/risk-eu/local.yml`, or `lab.sh reset`.

## What you learned

- The mcpServers file lists the MCP servers an instance embeds, in the Claude Desktop shape, and is
  re-read on change
- External entries (the default) reach the net as `<vendor>__<tool>` through the defining instance, which
  governs every call; they are never members
- Internal entries are governed like local tools and enter the net under their federation names when an
  export rule names them; sponsoring or the agent make a server a member
- `sajhanet.external_servers` does the same for upstreams defined in configuration, with `prefix`,
  `rename` and `nets`

## Next

- [Tutorial 34: Sponsor a Server and the SAJHA Net Agent](TUTORIAL_34_sponsor_a_server_and_the_net_agent.md)
- Federation in depth, including approvals of newly discovered tools: [Tutorial 11](TUTORIAL_11_federate_an_mcp_server.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
