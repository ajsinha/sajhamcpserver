# Tutorial 53: Change a SAJHA Net Safely

[Tutorial 32](TUTORIAL_32_the_sajha_net_console.md) tours the SAJHA Net console's pages. This one
makes changes with it, the way an administrator should: see the **blast radius** of a change before
making it, give a reason, find the change in the net's change history, and **undo** it. You block a
tool for one member, watch the member's call be refused, undo the block, and set a timed block from a
console session with the page's CSRF token. The pages are described in
[SAJHA Net](../architecture/SAJHA%20Net.md) §17.1 (the change history and the confirmation dialog are
the bullets under its table); the console as a whole in
[Architecture](../architecture/Architecture.md) §10.

**What was verified.** Every step below was run as written on the
[local test lab](TUTORIAL_29_local_test_lab.md), started from a checkout with its folder and ports
moved (`SAJHA_LAB_DIR`, `SAJHA_LAB_PORT=3197`) and the offline mock provider instead of Ollama (step
1), and the outputs are from that run. Ids, times and trace ids differ in yours; the tool counts in the
blast radius depend on the tools your checkout ships.

## What you'll learn

- What the blast radius of a change counts, and where it comes from
- How a block's reason, effect and expiry are recorded, and what the refused caller sees
- How the change history records who, when, why and the inverse of every change
- How Undo applies the inverse as a new change, and which changes are final
- Why a change from a console session needs the page's CSRF token, and where it goes in the audit chain

## Prerequisites

- The local test lab's requirements ([Tutorial 29](TUTORIAL_29_local_test_lab.md)): a checkout with its
  environment and the MCP SDK. Ollama is not needed here: the console pages call no model.
- Free ports 3197 to 3199 (or any three in a row: `SAJHA_LAB_PORT`)

## 1. Start the lab with the mock provider

A `local.yml` in the lab's folder is merged into every instance's configuration; this one swaps
Ollama for the mock provider:

```bash
L=/tmp/t53; mkdir -p $L
cat > $L/local.yml <<'EOF'
# The mock provider instead of Ollama: the console pages need no model.
ai:
  aliases:
    default:   [mock/mock-planner]
    fast:      [mock/mock-planner]
    reasoning: [mock/mock-planner]
    embedding: [mock/mock-embed]
    toolsmith: [mock/mock-toolsmith]
EOF
SAJHA_LAB_DIR=$L SAJHA_LAB_PORT=3197 deployment/local-lab/lab.sh start
```

```text
warning: Ollama does not answer on http://127.0.0.1:11434; start it (`ollama serve`) before asking questions
risk-eu: starting on http://127.0.0.1:3197 (pid 1067829, log /tmp/t53/risk-eu/server.log)
cust-na: starting on http://127.0.0.2:3198 (pid 1068879, log /tmp/t53/cust-na/server.log)
treasury-eu: starting on http://127.0.0.3:3199 (pid 1068880, log /tmp/t53/treasury-eu/server.log)

risk-eu      http://127.0.0.1:3197    healthy   pid 1067829  lab-net: cust-na alive, treasury-eu alive
cust-na      http://127.0.0.2:3198    healthy   pid 1068879  lab-net: risk-eu alive, treasury-eu alive
treasury-eu  http://127.0.0.3:3199    healthy   pid 1068880  lab-net: cust-na alive, risk-eu alive
```

(The launcher's closing "LLM: ..." line names the models the running instances resolve, so with the
mock provider from your `local.yml` it says "the mock provider"; the warning is harmless here.) You work on `risk-eu`. In the shell:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'; B=http://127.0.0.1:3197
call() {  # call FROM-URL: run risk-eu's calc_percentage_change from another member
  curl -s -X POST $1/api/tools/execute -H "$K" -H 'Content-Type: application/json' \
    -d '{"tool": "lab-net__risk-eu__calc_percentage_change", "arguments": {"old_value": 100, "new_value": 125}}'
}
```

## 2. Traffic first

The blast radius counts what this server has seen, so make a call from `cust-na` to `risk-eu`:

```bash
call http://127.0.0.2:3198 | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['structuredContent'])"
```

```text
{'old_value': 100, 'new_value': 125, 'percentage_change': 25.0}
```

## 3. The blast radius

Before any change, the console's confirmation dialog asks `risk-eu` who would lose what. The same
question as JSON, for three possible blocks on `cust-na`: entirely, inbound only, one tool:

```bash
for q in "level=instance&target_instance=cust-na" "level=inbound&target_instance=cust-na" \
         "level=tool&target_instance=cust-na&tool=calc_percentage_change"; do
  curl -s "$B/api/sajhanet/nets/lab-net/blast-radius?kind=block_add&$q" -H "$K"; echo
done
```

```text
{"net":"lab-net","kind":"block_add","remote_users":1,"remote_tools":19,"local_users":0,"local_tools":19,"words":"cust-na's 1 user(s) seen here lose access to 19 tool(s) this server offers; This server's users lose 19 tool(s) of cust-na (0 called them recently)."}
{"net":"lab-net","kind":"block_add","remote_users":1,"remote_tools":19,"local_users":0,"local_tools":0,"words":"cust-na's 1 user(s) seen here lose access to 19 tool(s) this server offers."}
{"net":"lab-net","kind":"block_add","remote_users":1,"remote_tools":1,"local_users":0,"local_tools":0,"words":"cust-na's 1 user(s) seen here lose the tool calc_percentage_change."}
```

The counts come only from what `risk-eu` holds (users seen in its audit chain, tools in its table and
catalogs); no peer is asked. The smallest block that does the job is the tool block.

## 4. Block one tool, with a reason

```bash
curl -s -X POST $B/api/sajhanet/nets/lab-net/blocks -H "$K" -H 'Content-Type: application/json' \
  -d '{"level": "tool", "target_instance": "cust-na", "tool": "calc_percentage_change", "reason": "cust-na reported wrong figures from it; until the fix ships"}'; echo
call http://127.0.0.2:3198; echo
```

```text
{"id":"253eb6f2080612ad","level":"tool","target_instance":"cust-na","reason":"cust-na reported wrong figures from it; until the fix ships","set_at":"2026-10-12T05:23:24Z","set_by":"testadmin","tool":"calc_percentage_change","direction":"inbound","version":1,"effect":"Calls from cust-na to the tool calc_percentage_change are refused here."}
{"success":true,"result":{"content":[{"type":"text","text":"risk-eu refused the call to lab-net__risk-eu__calc_percentage_change: tool."}],"isError":true,"_meta":{"io.sajha/net":{"refusal":{"reason":"tool","side":"host","net":"lab-net","instance":"risk-eu","tool":"calc_percentage_change","trace_id":"b9846d9847e111f9e99bea6ff0809be0","executed":false,"retryable":false,"attempt":1},"attempts":[{"attempt":1,"net":"lab-net","host":"risk-eu","qualified_name":"lab-net__risk-eu__calc_percentage_change","outcome":"tool","executed":false}]}}}}
```

The answer states the block's effect in words. The caller learns that the host refused and why in one
word (`tool`), with a trace id; the tool never ran (`executed: false`), so `cust-na` does not retry.
On the console, the same block is **Add a block** on **SAJHA Net > Access and blocks**
(`/admin/sajhanet/blocks`), which shows the blast radius and will not send without a reason.

## 5. The change history

Every change made through the admin API or the console is kept in the net's change history, with its
inverse:

```bash
curl -s "$B/api/sajhanet/nets/lab-net/changes" -H "$K" | python3 -m json.tool
```

```text
{
    "net": "lab-net",
    "changes": [
        {
            "id": "216bea6290e4",
            "at": "2026-10-12T05:23:24Z",
            "by": "testadmin",
            "net": "lab-net",
            "kind": "block_add",
            "target": "cust-na",
            "summary": "block (tool calc_percentage_change) on cust-na",
            "reason": "cust-na reported wrong figures from it; until the fix ships",
            "params": {
                "level": "tool",
                "target_instance": "cust-na",
                "tool": "calc_percentage_change",
                "user": "",
                "direction": "inbound",
                "expires_in_minutes": null,
                "withhold_reason": false
            },
            "undo": {
                "kind": "block_remove",
                "params": {
                    "block_id": "253eb6f2080612ad"
                }
            },
            "final": null
        }
    ]
}
```

The page is **SAJHA Net > Change history** (`/admin/sajhanet/changes`), and an instance's **History**
tab (`/net/instances/lab-net/cust-na?tab=history`) lists the changes that named it. The file is
`<data_dir>/lab-net/changes.json` in the storage backend (the newest 500).

## 6. Undo

Undo applies the inverse as a new change, and needs a reason too:

```bash
curl -s -X POST "$B/api/sajhanet/nets/lab-net/changes/216bea6290e4/undo" -H "$K" -H 'Content-Type: application/json' -d '{}'; echo
curl -s -X POST "$B/api/sajhanet/nets/lab-net/changes/216bea6290e4/undo" -H "$K" -H 'Content-Type: application/json' \
  -d '{"reason": "cust-na shipped the fix"}'; echo
call http://127.0.0.2:3198 | python3 -c "import json,sys; print(json.load(sys.stdin)['result'].get('structuredContent'))"
curl -s "$B/api/sajhanet/nets/lab-net/changes" -H "$K" | python3 -c "
import json,sys
for c in json.load(sys.stdin)['changes']: print(c['id'], c['kind'], '|', c['summary'], '|', c['reason'], '| undo:', c['undo'])"
```

```text
{"error":"give a reason for the undo"}
{"net":"lab-net","undone":"216bea6290e4","as":"b6e4113589f9","result":true}
{'old_value': 100, 'new_value': 125, 'percentage_change': 25.0}
b6e4113589f9 block_remove | remove block (tool) on cust-na | cust-na shipped the fix | undo: {'kind': 'block_add', 'params': {'level': 'tool', 'target_instance': 'cust-na', 'tool': 'calc_percentage_change', 'direction': 'inbound', 'block_reason': 'cust-na reported wrong figures from it; until the fix ships'}}
216bea6290e4 block_add | block (tool calc_percentage_change) on cust-na | cust-na reported wrong figures from it; until the fix ships | undo: {'kind': 'block_remove', 'params': {'block_id': '253eb6f2080612ad'}}
```

`cust-na`'s call works again, and the undo is itself a change with an inverse (the block, with its
original reason), so it can be undone in turn. Blocks, links, role maps, name matching, trust,
approvals, pins, runtime seeds and sponsoring are undoable; revocations, forgotten keys, enrollment
tokens, renewals and key re-syncs are final: they have no inverse, `final` says why, and Undo answers
409 with that reason.

Both steps are in the audit chain as `config_change` records named `sajhanet.change_recorded` and
`sajhanet.change_undone`, beside the record of the block itself:

```bash
curl -s "$B/api/audit/records?limit=200&event=config_change" -H "$K" | python3 -c "
import json,sys
for r in json.load(sys.stdin)['records'][:4]: print(r['resource']['id'], r['details'][:110])"
```

```text
sajhanet.change_undone {"net": "lab-net", "id": "216bea6290e4", "as": "b6e4113589f9", "kind": "block_add", "reason": "cust-na shi
sajhanet.change_recorded {"net": "lab-net", "id": "b6e4113589f9", "kind": "block_remove", "target": "cust-na", "summary": "remov
sajhanet.block_removed {"net": "lab-net", "id": "253eb6f2080612ad", "reason": "cust-na shipped the fix", "version": 2}
sajhanet.change_recorded {"net": "lab-net", "id": "216bea6290e4", "kind": "block_add", "target": "cust-na", "summary": "block
```

## 7. From a console session: the CSRF token

The examples above use an API key. A browser session changes the net only with the page's CSRF token
in `X-CSRF-Token`; without it the change is refused:

```bash
J=$L/jar
curl -s -c $J -b $J -o /dev/null -X POST $B/login -d user_id=testadmin -d password=testadmin-dev-1
curl -s -c $J -b $J -X POST $B/api/sajhanet/nets/lab-net/blocks -H 'Content-Type: application/json' \
  -d '{"level": "inbound", "target_instance": "cust-na", "reason": "x"}'; echo
T=$(curl -s -c $J -b $J "$B/admin/sajhanet/blocks?net=lab-net" | grep -o 'csrf="[^"]*"' | head -1 | cut -d'"' -f2)
curl -s -c $J -b $J -X POST $B/api/sajhanet/nets/lab-net/blocks -H "X-CSRF-Token: $T" -H 'Content-Type: application/json' \
  -d '{"level": "inbound", "target_instance": "treasury-eu", "reason": "treasury-eu is being rebuilt; no calls from it until Friday", "expires_in_minutes": 60}'; echo
```

```text
{"error":"missing or invalid X-CSRF-Token (reload the page)"}
{"id":"b577fb567ea9fa8c","level":"inbound","target_instance":"treasury-eu","reason":"treasury-eu is being rebuilt; no calls from it until Friday","set_at":"2026-10-12T05:23:52Z","set_by":"testadmin","expires_at":"2026-10-12T06:23:52Z","version":3,"effect":"Calls from treasury-eu are refused here; this server still calls its tools."}
```

The console's dialog does this for you. A change that arrives through the net (a caller from another
instance) is refused outright.

## 8. See it from both sides

The access matrix (**Access and blocks**) puts callers in rows and hosts in columns, from this
server's blocks and those the others publish:

```bash
curl -s "$B/api/sajhanet/nets/lab-net/access-matrix" -H "$K" | python3 -c "
import json,sys
for row in json.load(sys.stdin)['matrix']: print(row['caller'], [(c['host'], c['state'], c['by']) for c in row['cells']])"
```

```text
risk-eu [('risk-eu', 'self', []), ('cust-na', 'allowed', []), ('treasury-eu', 'allowed', ['risk-eu'])]
cust-na [('risk-eu', 'allowed', []), ('cust-na', 'self', []), ('treasury-eu', 'allowed', [])]
treasury-eu [('risk-eu', 'inbound', ['risk-eu']), ('cust-na', 'allowed', []), ('treasury-eu', 'self', [])]
```

`treasury-eu` calling `risk-eu` is blocked inbound, set by `risk-eu`; `risk-eu` still calls
`treasury-eu`. A refused call shows up on **Live activity** (`/admin/sajhanet/activity`), red with its
reason:

```bash
call http://127.0.0.3:3199 > /dev/null
curl -s "$B/api/sajhanet/activity?net=lab-net" -H "$K" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['calls'][0]))"
```

```text
{"at": "2026-10-12T05:24:07.358956Z", "event": "net.host_refused", "side": "host", "other": "treasury-eu", "from": "treasury-eu", "to": "risk-eu", "tool": "calc_percentage_change", "outcome": "inbound", "ok": false, "attempt": null, "executed": false, "user": "treasury-eu", "trace_id": "88efdacef2cf449ba05c731d1830dcba", "mapping": "", "streamed": false, "net": "lab-net"}
```

The block lifts itself after 60 minutes; to lift it now, Undo its change on **Change history**.

## 9. Stop the lab

```bash
SAJHA_LAB_DIR=$L SAJHA_LAB_PORT=3197 deployment/local-lab/lab.sh stop
```

```text
risk-eu: stopped (pid 1076779)
cust-na: stopped (pid 1077529)
treasury-eu: stopped (pid 1077530)
```

`start` again keeps the instances' folders and the net; `reset` deletes them (the lab's
[README](../../deployment/local-lab/README.md)).

## Summary

- Before a change, the blast radius says who loses what, counted from what this server holds
- Every change carries a reason, lands in the net's change history with its inverse, and is audited
- Undo applies the inverse as a new, undoable change; a few kinds are final
- A console session changes the net only with the page's CSRF token; the console's dialog shows the
  effect, the blast radius and whether it can be undone, and asks for the reason

## Next

- The pages and the change history: [SAJHA Net](../architecture/SAJHA%20Net.md) §17.1
- [Tutorial 54: How a Figure Was Computed](TUTORIAL_54_figure_lineage.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
