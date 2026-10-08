# Tutorial 37: Re-export and Bridges

By default a SAJHA instance offers the net only its own tools. **Re-export** lets it offer onward tools
it imported from another member, so a caller reaches a host through an intermediary; a **bridge** does
the same between two nets, offering in one net tools imported from another. Calls through an
intermediary cannot carry the caller's API key onward, so they use the other identity resolvers:
**assertion** (the home signs a short-lived statement of who the user is) and **token exchange** (the
assertion is exchanged at the host for a host-scoped token). This tutorial builds both shapes on the
[local test lab](TUTORIAL_29_local_test_lab.md). The design is [SAJHA Net](../architecture/SAJHA%20Net.md)
sections 10.2 and 14.

## What you'll learn

- How `reexport`, `reexport_rules` and `max_hops` combine, and who decides
- What a re-exported tool looks like (`origin`) and how its call travels (an assertion with the origin as
  audience)
- How a bridge offers one net's tools in another as the bridging instance's own
- How to choose identity resolvers per net, and how to see which one a call used

## Prerequisites

- The local test lab ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset
  (`lab.sh reset`); the steps write `local.yml` files before starting it

## Steps

### 1. Re-export within one net

The shape: `risk-eu` imports only from `cust-na`; `cust-na` re-exports `treasury-eu`'s `calc_retirement`
to `risk-eu`. Three files, then start:

```bash
mkdir -p deployment/local-lab/run/risk-eu deployment/local-lab/run/cust-na
cat > deployment/local-lab/run/local.yml <<'EOF'
sajhanet:
  max_hops: 2                         # one intermediary: every instance on the chain must accept 2 hops
  user_identity: api_key,assertion    # as a home, send the first the host also lists; as a host, accept all
EOF
cat > deployment/local-lab/run/risk-eu/local.yml <<'EOF'
sajhanet:
  nets:
    - name: lab-net
      instance_name: risk-eu
      seeds: []
      export: [{tools: [calc_*, llm_*, units__*]}]
      import: [{tools: ['*'], instances: [cust-na]}]
EOF
cat > deployment/local-lab/run/cust-na/local.yml <<'EOF'
sajhanet:
  reexport: true
  reexport_rules:
    - {tools: [calc_retirement], from_instances: [treasury-eu], to_instances: [risk-eu]}
EOF
deployment/local-lab/lab.sh start
```

Re-export is off by default; with `reexport` on for the net offered into (advertised as the feature
`reexport`), an imported tool goes onward only when a rule names it (`tools`, `from_nets`,
`from_instances`, `to_instances`, `for_roles`). A tool is never offered back to its host or origin, never
under a local tool's name, and keeps the host's contract, so one name, one contract holds.

On `risk-eu`, the tool list now has `lab-net__cust-na__calc_retirement` with `origin: treasury-eu` in
its `_meta["io.sajha/net"]`. Call it by plain name:

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "calc_retirement", "arguments": {"current_savings": 100000, "annual_contribution": 10000, "return_rate": 5, "years": 20}}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['structuredContent']); print(r['_meta']['io.sajha/net'])"
```

```text
{'final_balance': 595989.31, 'total_contributed': 300000, 'investment_growth': 295989.31}
{'instance': 'cust-na', 'net': 'lab-net', 'qualified_name': 'lab-net__cust-na__calc_retirement', ..., 'via': {'net': 'lab-net', 'instance': 'treasury-eu', 'origin': 'treasury-eu'}}
```

`risk-eu` sent an assertion with `aud` = `treasury-eu` (never a key) to `cust-na`; `cust-na` verified it,
mapped and authorized the caller under its re-export rules, and relayed the assertion unchanged with hop
2 and the visited list. `treasury-eu`'s audit shows it (read it with the test admin key as in
[Tutorial 30](TUTORIAL_30_credentials_and_test_keys.md)): a `net.host_call` with `identity: assertion`,
`hop: 2`, `user: testadmin@risk-eu` and `visited: ["lab-net/risk-eu", "lab-net/cust-na"]`. Residency,
the hop limit and the call-chain budget apply on each step; a home ranks direct offers before re-exported
ones and refuses to send a chain back to a host it passed (`loop`).

### 2. A bridge between two nets

The shape: `risk-eu` and `cust-na` in `lab-net`; `cust-na` and `treasury-eu` in a second net,
`treasury-net`; `cust-na` bridges `calc_retirement` from `treasury-net` into `lab-net`. Reset and write:

```bash
deployment/local-lab/lab.sh reset
mkdir -p deployment/local-lab/run/cust-na deployment/local-lab/run/treasury-eu
cat > deployment/local-lab/run/local.yml <<'EOF'
sajhanet:
  max_hops: 2
  user_identity: api_key,assertion
EOF
cat > deployment/local-lab/run/cust-na/local.yml <<'EOF'
sajhanet:
  reexport_rules:
    - {tools: [calc_retirement], from_nets: [treasury-net]}
  nets:
    - name: lab-net
      instance_name: cust-na
      seeds: [http://127.0.0.1:3002]
      export: [{tools: [calc_*, llm_*]}]
      import: [{tools: ['*']}]
      reexport: true
    - name: treasury-net
      instance_name: cust-na
      seeds: [http://127.0.0.3:3004]
      export: []
      import: [{tools: [calc_*]}]
      user_identity: token_exchange
EOF
cat > deployment/local-lab/run/treasury-eu/local.yml <<'EOF'
sajhanet:
  nets:
    - name: treasury-net
      instance_name: treasury-eu
      seeds: []
      export: [{tools: [calc_*]}]
      import: [{tools: ['*']}]
      user_identity: token_exchange
EOF
deployment/local-lab/lab.sh start
```

`lab.sh status` now prints each instance's nets: `cust-na` is in both, `treasury-eu` only in
`treasury-net`, and `risk-eu` does not know `treasury-eu` at all. On `risk-eu` the bridged tool is
`lab-net__cust-na__calc_retirement` with no origin: in `lab-net` it is `cust-na`'s own.

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "calc_retirement", "arguments": {"current_savings": 100000, "annual_contribution": 10000, "return_rate": 5, "years": 20}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['_meta']['io.sajha/net'])"
```

```text
{'instance': 'cust-na', 'net': 'lab-net', 'qualified_name': 'lab-net__cust-na__calc_retirement', ..., 'via': {'net': 'treasury-net', 'instance': 'treasury-eu', 'origin': None}}
```

The call from `lab-net` runs at `cust-na` as the local account the caller maps to there, which calls into
`treasury-net` with an assertion `cust-na` signs (a guest mapping cannot cross a bridge); hops and the
visited list continue. `cust-na`'s audit has the `net.host_call` from `risk-eu` (with `reexport.source`
`treasury-net__treasury-eu__calc_retirement`) and its own `net.call_attempt` into `treasury-net` with
`identity: assertion`; `treasury-eu`'s `net.host_call` shows `hop: 2` and `user: testadmin@cust-na`.

### 3. Token exchange

`treasury-net` lists only `token_exchange` as its identity. A direct call from `cust-na` (as home) to
`treasury-eu` therefore exchanges an assertion at `treasury-eu`'s `POST /sajhanet/v1/token` for an opaque
token bound to the net and to `cust-na`, and sends that token:

```bash
curl -s -X POST http://127.0.0.2:3003/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "treasury-net__treasury-eu__calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}' > /dev/null
curl -s 'http://127.0.0.3:3004/api/audit/records?limit=3' -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; [print(r['event'], r['details'].get('identity') or r['details'].get('outcome')) for r in json.load(sys.stdin)['records']]"
```

```text
net.host_call token_exchange
tool.call None
net.token_issued issued
```

The token lives hashed in the host's state store for `sajhanet.token_exchange.ttl_seconds` (300), is
cached at the home per host and key until ten seconds before it expires, and is re-checked against the key
record, blocks and the user mapping on every call; a `token_invalid` refusal makes the home exchange again
and retry once. The host audits each token it issues (never the token). Note that the bridged call of
step 2 used `assertion` although `treasury-net` lists only `token_exchange`: a bridge always relays an
assertion.

### 4. Clean up

```bash
deployment/local-lab/lab.sh reset
rm deployment/local-lab/run/local.yml
```

## What you learned

- Re-export is decided by the net offered into: `reexport` on, and a rule naming the tool; every instance
  on the chain must accept the extra hop (`max_hops: 2`)
- A re-exported tool keeps its contract and names its `origin`; its calls carry an assertion addressed to
  the origin, relayed by the intermediary
- A bridge offers another net's tools as the bridging instance's own, and calls into that net as the
  mapped local user
- `user_identity` per net chooses among `api_key`, `assertion` and `token_exchange`; the host's audit
  records which one each call used

## Next

- [Tutorial 38: The SAJHA Net Conformance Runner](TUTORIAL_38_net_conformance_runner.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
