# Tutorial 34: Sponsor a Server and the SAJHA Net Agent

A plain MCP server can be a **member** of a SAJHA Net, with an instance name of its own, in two ways. A
SAJHA instance can **sponsor** it: connect to it as a federation upstream and represent it in the net,
applying its own rules to every call. Or the **SAJHA Net agent** can sit beside it as a sidecar and do
everything a participant does. Unlike an external server
([Tutorial 33](TUTORIAL_33_proxied_mcp_servers.md)), a member keeps its tools' own names and falls under
one name, one contract with everyone else. This tutorial sponsors the units example server from
`cust-na` and puts the agent's echo test server into the net, on the
[local test lab](TUTORIAL_29_local_test_lab.md). The guides are [SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md)
and [SAJHA Net](../architecture/SAJHA%20Net.md) section 5.1.

## What you'll learn

- How to sponsor a server: a federation upstream, a `sajhanet.sponsored` entry and an export rule
- What a sponsored member looks like to the others (kind `sponsored`, its sponsor named)
- How to run the agent in front of a stdio MCP server, and what it checks on every call
- Why calls to an agent need the callers' own keys rather than the test admin key

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset, with the
  MCP SDK installed in its Python
- The full path of that Python (`$PYTHON` below; for example `.venv/bin/python`)

## Steps

### 1. Give cust-na an internal upstream

Sponsoring starts from an internal federation upstream. Write an mcpServers file for `cust-na`
(replace `/path/to/python` with your Python and `/path/to/sajhamcpserver` with the checkout):

```bash
cat > deployment/local-lab/run/cust-na/servers.json <<'EOF'
{"mcpServers": {
  "convert": {"command": "/path/to/python",
              "args": ["/path/to/sajhamcpserver/sajha/examples/federation/units_server.py", "--stdio"],
              "vendor": "units", "prefix": "convert", "external": false}
}}
EOF
```

`"external": false` keeps it an ordinary upstream: its tools appear on `cust-na` as
`convert__celsius_to_fahrenheit` and so on, governed like `cust-na`'s own tools. The prefix
defaults to the vendor; in the lab, `units__` names are already in use on `cust-na` (they are `risk-eu`'s
external server, Tutorial 29 step 14), and in the run behind this tutorial the upstream then exposed no
tools, so give it a prefix of its own.

### 2. Sponsor it

Create `run/cust-na/local.yml`:

```yaml
federation:
  enabled: true
  allow_stdio: true
  require_approval: false
  mcp_servers_file: /path/to/sajhamcpserver/deployment/local-lab/run/cust-na/servers.json
sajhanet:
  sponsored:
    - {net: lab-net, instance_name: units-svc, upstream: convert, vendor: units, tools: ['*']}
  nets:
    - name: lab-net
      instance_name: cust-na
      seeds: [http://127.0.0.1:3002]
      export: [{tools: [calc_*, llm_*, convert__*]}]
      import: [{tools: ['*']}]
```

The `sponsored` entry names the net, the member's instance name, the federation upstream and the vendor
(required). The net entry repeats the lab's, with one addition: the export rule names `convert__*`. A
sponsored server's tools pass the sponsor's export rules under their local (registry) names, so without
that rule the member would join with an empty catalog. The same rule also offers the tools as
`cust-na`'s own internal tools (`lab-net__cust-na__convert__celsius_to_fahrenheit`); the sponsored member
offers them under the server's own names. Restart `cust-na`:

```bash
deployment/local-lab/lab.sh stop cust-na
deployment/local-lab/lab.sh start cust-na
```

Within seconds every instance sees a fourth member:

```text
risk-eu      http://127.0.0.1:3002    healthy   pid ...  lab-net: cust-na alive, treasury-eu alive, units-svc alive
```

On **SAJHA Net > Instances**, `units-svc` is of kind `sponsored`, vendor `units`, with `cust-na` as its
sponsor. `cust-na` runs a node for it on its own URL, holds its key and certificate (self-signed in an
open net, under `sponsored/units-svc/` in the net's folder) and ticks it with its own gossip agent. The
admin view is `GET /api/sajhanet/sponsored` on `cust-na`; entries can also be added there
(`POST /api/sajhanet/sponsored`) instead of in configuration.

### 3. Call it

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "lab-net__units-svc__celsius_to_fahrenheit", "arguments": {"celsius": 21}}' | head -c 220; echo
```

```text
{"success":true,"result":{"content":[{"type":"text","text":"69.8"}], ... "instance":"units-svc" ...
```

The tool keeps its own name, `celsius_to_fahrenheit`: members are internal, so the plain name works on
`risk-eu` too. `cust-na` ran its checks as for its own tools (identity, blocks, export rules, the local
account's access, policies, approvals, residency on the result, audit) and then called the server through
federation.

### 4. Turn the test admin key off

The agent verifies every forwarded key against its copy of the net key directory and has no test admin
record, so calls carrying the test admin key are refused there (`key_unknown`). Turn the switch off on
all three, as in [Tutorial 30](TUTORIAL_30_credentials_and_test_keys.md):

```bash
mkdir -p deployment/local-lab/run
printf 'sajhanet:\n  test_admin_key:\n    enabled: false\n' > deployment/local-lab/run/local.yml
deployment/local-lab/lab.sh stop
deployment/local-lab/lab.sh start
```

### 5. Run the agent

```bash
mkdir -p deployment/local-lab/run/agent
$PYTHON -m sajhanet_agent --net lab-net --instance echo-agent --vendor acme \
  --url http://127.0.0.4:3011 --seed http://127.0.0.1:3002 \
  --mcp-command "$PYTHON sajhanet_agent/tests/echo_mcp_server.py" \
  --allow-plain-http --data-dir deployment/local-lab/run/agent
```

It starts the echo server over stdio, makes itself a self-signed certificate (open admission), joins
through `risk-eu` and publishes the server's `tools/list` (one tool, `echo`) as its catalog.
`--allow-plain-http` is for a lab only. Its health check answers at the root of its address:

```bash
curl -s http://127.0.0.4:3011/healthz
```

```text
{"ok": true, "net": "lab-net", "instance": "echo-agent", "joined": true}
```

`echo-agent` is now on every Instances page, kind `agent`, vendor `acme`.

### 6. Call the agent as yourself

With the test admin key off, a forwarded call carries the caller's own key. Sign in to `cust-na` as
`admin` / `admin123` and run `lab-net__echo-agent__echo` from the Tools page, or with a session token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.2:3003/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id": "admin", "password": "admin123"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -X POST http://127.0.0.2:3003/api/tools/execute -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool": "lab-net__echo-agent__echo", "arguments": {"text": "hi"}}' | head -c 160; echo
```

```text
{"success":true,"result":{"content":[{"type":"text","text":"echo: hi"}], ... "instance":"echo-agent" ...
```

`cust-na` sent `admin`'s default key; the agent found it in the key directory `cust-na` publishes,
checked that it came from `cust-na`, applied its export policy (`--export-tools`, `--export-peers`,
`--export-roles`; default everything) with the key's own tool access as a ceiling, and called the server.
The agent has no accounts of its own: the user is the key's owner at home. It is never a home itself (it
calls no other member's tools) and publishes no keys.

### 7. Clean up

Stop the agent with Ctrl+C (on SIGTERM it leaves the net with a signed leave), then:

```bash
deployment/local-lab/lab.sh reset
rm deployment/local-lab/run/local.yml
rm -r deployment/local-lab/run/agent
```

## What you learned

- Sponsoring makes a federation upstream a member under its own instance name, with the sponsor's rules
  on every call; its tools pass the sponsor's export rules under their local names
- The agent makes any MCP server a member from beside it: certificate, gossip, catalog, key verification
  and an export policy
- Members keep their tools' own names; external servers ([Tutorial 33](TUTORIAL_33_proxied_mcp_servers.md))
  are offered under their vendor's prefix and are never members
- An agent verifies callers' own keys; the test admin key is a SAJHA-to-SAJHA convenience it does not
  honour

## Next

- [Tutorial 35: Data Residency Across Instances](TUTORIAL_35_data_residency_across_instances.md)
- Check a participant against the protocol: [Tutorial 38](TUTORIAL_38_net_conformance_runner.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
