# Tutorial 52: Planner Routing Learned from Results

The `auto` planner chooses a strategy per question: its own rules first, then a cheap model picks
from a menu of the planners the tool allows. Learning adds a third source of evidence: how each
planner actually did. A learning job ranks planners per question class from saved eval runs and the
recorded outcomes of past choices and writes a **proposal**; nothing changes until an administrator
approves the proposal's exact hash, and every approved version can be rolled back. This tutorial
runs that loop end to end: record evidence, propose, approve, watch the choice change, roll back. The
design is [LLM Tools](../architecture/LLM%20Tools.md#913-automatic-planner-selection) §9.13; the files,
settings and commands are in the [Planner Reference](../architecture/Planner%20Reference.md) §6.6.2.

**What was verified.** Every step below was run as written against a server started from a checkout
on a scratch database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`), scratch directory
(`SAJHA_BI_SCRATCH_DIR`) and routing directory (`SAJHA_AI_PLANNERS_LEARNING_DIR`), with the default
offline mock provider, and the outputs are from that run. Proposal ids, hashes and times differ in
yours; with a real model the choices and scores do too.

## What you'll learn

- What is recorded about every automatic planner choice, and its outcome
- How saved eval runs become evidence, and how the job ranks planners per question class
- What a proposal holds, and why approving needs its hash and an explicit yes
- How an approved version changes `auto`'s choice (`by: learned`), and how to roll it back
- Where the opt-in bandit and its kill switch fit

## Prerequisites

- A SAJHA checkout and its environment ([Tutorial 1](TUTORIAL_01_getting_started.md)); planner
  basics from [Tutorial 45](TUTORIAL_45_quantitative_planners.md) help
- An administrator credential: the examples use the development key from `config/apikeys.json`

```bash
P=/tmp/t52; mkdir -p $P
export SAJHA_DB_PATH=$P/t52.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  SAJHA_AI_PLANNERS_LEARNING_DIR=$P/routing
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3197
```

In a second shell, export the same four variables (the command-line job reads the same database and
directory) and define a helper that asks with a chosen planner and prints chosen events of the ask's
event stream, then the answer:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'; B=http://127.0.0.1:3197
stream() {  # stream QUESTION PLANNER-JSON EVENT-TYPES...
  q=$1; p=$2; shift 2
  body=$(python3 -c "import json,sys; print(json.dumps({'question': sys.argv[1], 'planner': json.loads(sys.argv[2])}))" "$q" "$p")
  curl -s -N -X POST "$B/api/ai/ask?stream=1" -H "$K" -H 'Content-Type: application/json' -d "$body" \
  | python3 -c "
import json,sys
want=set(sys.argv[1:])
for line in sys.stdin:
    if not line.startswith('data: '): continue
    e=json.loads(line[6:])
    if e['type'] in want: print(json.dumps({k: v for k, v in e.items() if k not in ('seq', 'ts', 'trace_id')}))
    if e['type'] == 'done' and e.get('result'): print('answer:', e['result']['answer'])
" "$@"
}
```

## 1. Nothing learned yet

```bash
.venv/bin/python -m sajha.ai.planners_engine.learn status
```

```text
rules directory: /tmp/t52/routing; active version: none
bandit: off; 0 arm(s)
```

The settings in effect are on the page and in `GET /api/ai/planner-routing`. The ones that matter
here are `min_samples` (5: outcomes a planner needs in a class before it is ranked) and `window_days`
(30); the rest are `ai.planners.learning.*` in the
[Configuration Reference](../getting-started/Configuration%20Reference.md).

## 2. A choice, and what is recorded

Ask through `auto` and watch its choice:

```bash
stream "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"auto"' planner_chosen
```

```text
{"type": "planner_chosen", "planner": "auto", "version": "1.1.0", "by": "caller choice", "reason": "caller choice"}
{"type": "planner_chosen", "planner": "calc_graph", "version": "1.0.0", "by": "label 0.60", "reason": "mock: calc_graph"}
answer: growth is 8.44717712 percent.
```

The model labelled the question. The run's audit record (`ai_ask`) now holds the choice and how it
turned out, as `planner_choice` (the question text is not part of it):

```bash
curl -s "$B/api/audit/records?limit=1&event=ai_ask" -H "$K" | python3 -c "
import json,sys; r=json.load(sys.stdin)['records'][0]; d=json.loads(r['details']); print(json.dumps(d['planner_choice'], indent=1))"
```

```text
{
 "tool": "ask",
 "class": "compute",
 "candidates": [
  "react",
  "plan_execute",
  "reflect",
  "map_reduce",
  "calc_graph",
  "scenario",
  "data_analyst"
 ],
 "chosen": "calc_graph",
 "by": "model",
 "reason": "mock: calc_graph",
 "outcome": {
  "success": true,
  "reward": 1.0,
  "escalated": false,
  "stopped_by": "answer",
  "cost_usd": 0.0,
  "latency_ms": 48
 }
}
```

`class` comes from fixed rules with no model call (`compute`: a number with a word such as percent,
rate or growth). The choice **held**: the planner answered, nothing escalated, the run ended by
`answer`, so its reward is 1.

## 3. Evidence from eval runs

One recorded run is too little. Saved eval runs are the other evidence: run the computation eval set
on two planners ([Tool Quality](../architecture/Tool%20Quality.md) §5; the runs are saved in the
database):

```bash
.venv/bin/python -m sajha.quality eval quant_calc_graph --planner calc_graph --planner react 2>&1 | grep -E "^quant|pass |saved"
```

```text
quant_calc_graph · mock/mock-planner · calc_graph
  pass 6/6 (100%) · tool selection 100% · answers 100% · mean steps 0.0 · tokens 18952 · cost $0.0000 · p95 56 ms
  saved run 5102411f-a2b9-45fe-a5cf-40b747e14cf3
quant_calc_graph · mock/mock-planner · react
  pass 0/6 (0%) · tool selection 100% · answers 17% · mean steps 0.833 · tokens 27897 · cost $0.0000 · p95 35 ms
  saved run 5f2dbefc-6740-410d-bbb4-8cf6cbf75c42
```

See what the job would propose, writing nothing:

```bash
.venv/bin/python -m sajha.ai.planners_engine.learn --dry-run
```

```text
evidence: 12 eval outcome(s), 1 run outcome(s)
  ask [*]: calc_graph 1.00 (n=7), react 0.00 (n=6)
  ask [compute]: calc_graph 1.00 (n=6), react 0.00 (n=5)
```

A planner's score is its mean quality, less `cost_weight` × mean cost and `latency_weight` × mean
latency (both 0 by default). A class gets a rule only when two planners have `min_samples` outcomes;
`*` covers every class of the tool.

## 4. Propose

**Rank now and propose** on **Admin > Planner routing** (`/admin/planner-routing`) does the same as
the API call below, the command line without `--dry-run`, and the admin-only tool
`sajha_planner_routing_propose` (which the shipped workflow `planner_routing_learn` runs weekly once
an administrator turns its trigger on):

```bash
curl -s -X POST $B/api/ai/planner-routing/learn -H "$K" -H 'Content-Type: application/json' -d '{}' > $P/prop.json
python3 -c "
import json,sys; d=json.load(open(sys.argv[1])); doc=d['doc']
print(d['notice']); print('evidence:', {k: doc['evidence'][k] for k in ('eval_outcomes','run_outcomes','tools')})
for x in doc['diff']: print(x)
print('hash:', doc['hash'])" $P/prop.json
```

```text
Proposal p20261012052053-980677 written: 2 change(s) to review.
evidence: {'eval_outcomes': 12, 'run_outcomes': 1, 'tools': ['ask']}
{'tool': 'ask', 'class': '*', 'before': None, 'after': ['calc_graph', 'react'], 'change': 'added'}
{'tool': 'ask', 'class': 'compute', 'before': None, 'after': ['calc_graph', 'react'], 'change': 'added'}
hash: c80387e63cec6ae7ce48006b381cfbf9d38ff7b21264feb438fa029ae03cf3fb
```

The proposal (`proposals/<id>.json` in the routing directory) holds the ranked rules with the
evidence behind each planner (`n`, quality, mean cost and latency, score, how many outcomes came from
evals and from runs), the diff against the rules in effect, and the hash of the rules. It changes
nothing yet.

## 5. Approve

Approval names the proposal's exact hash and says yes explicitly; either missing is refused:

```bash
ID=$(python3 -c "import json;print(json.load(open('$P/prop.json'))['doc']['id'])")
H=$(python3 -c "import json;print(json.load(open('$P/prop.json'))['doc']['hash'])")
U=$B/api/ai/planner-routing/proposals/$ID/approve
curl -s -X POST $U -H "$K" -H 'Content-Type: application/json' -d "{\"hash\": \"$H\"}"; echo
curl -s -X POST $U -H "$K" -H 'Content-Type: application/json' -d '{"hash": "0000", "approve": true}'; echo
curl -s -X POST $U -H "$K" -H 'Content-Type: application/json' \
  -d "{\"hash\": \"$H\", \"approve\": true, \"note\": \"calc_graph wins every compute question\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['notice'])"
```

```text
{"error":"approving needs explicit approval (approve) after you have reviewed the rules"}
{"error":"the hash is not the proposal's: review it again"}
Approved: version 1 is active.
```

The approval also goes through the policy engine as the pseudo tool call `planners.routing.approve`:
a `deny` rule refuses it, and `require_approval` sends it to the Approvals page for a second
administrator ([Policy and Audit](../architecture/Policy%20and%20Audit.md)). The approved rules
became version 1, a file that never changes:

```bash
ls -R $P/routing
.venv/bin/python -m sajha.ai.planners_engine.learn status
```

```text
/tmp/t52/routing:
active.json
proposals
versions

/tmp/t52/routing/proposals:
p20261012052053-980677.json

/tmp/t52/routing/versions:
1.json
rules directory: /tmp/t52/routing; active version: 1
  version 1: approved by testadmin from p20261012052053-980677
  proposal p20261012052053-980677: approved, 2 change(s), hash c80387e63cec
bandit: off; 0 arm(s)
```

## 6. The choice now

Workers notice the new `active.json` within `reload_interval_s` (2 seconds). Ask again:

```bash
stream "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"auto"' planner_chosen
curl -s "$B/api/audit/records?limit=1&event=ai_ask" -H "$K" | python3 -c "
import json,sys; d=json.loads(json.load(sys.stdin)['records'][0]['details'])['planner_choice']; print({k: d[k] for k in ('class','chosen','by','reason')})"
```

```text
{"type": "planner_chosen", "planner": "auto", "version": "1.1.0", "by": "caller choice", "reason": "caller choice"}
{"type": "planner_chosen", "planner": "calc_graph", "version": "1.0.0", "by": "learned", "reason": "approved routing rules (compute)"}
answer: growth is 8.44717712 percent.
{'class': 'compute', 'chosen': 'calc_graph', 'by': 'learned', 'reason': 'approved routing rules (compute)'}
```

`by: learned`: the approved rule for `compute` chose, and no model was asked. A rule only orders the
candidates the stage already allows (the tool's planner choices, the eval filter, role-limited
planners such as `code_act`); it can never add one. With the mock, the model happened to choose the
same planner; with a real model the rules matter where it would not have.

The proposal and the approval are in the audit chain:

```bash
curl -s "$B/api/audit/records?limit=20" -H "$K" | python3 -c "
import json,sys
for r in json.load(sys.stdin)['records']:
    if r['event'].startswith('planners.routing'): print(r['event'], r['details'][:120])"
```

```text
planners.routing.approve {"hash": "c80387e63cec6ae7ce48006b381cfbf9d38ff7b21264feb438fa029ae03cf3fb", "version": 1, "approval": null}
planners.routing.propose {"hash": "c80387e63cec6ae7ce48006b381cfbf9d38ff7b21264feb438fa029ae03cf3fb", "evidence": {"eval_
```

## 7. Roll back

Make no version active (on the page, **Make active** "none (rules off)" with a reason, then **Activate
(roll back)**; here, the API with version 0), then version 1 again from the command line:

```bash
curl -s -X POST $B/api/ai/planner-routing/activate -H "$K" -H 'Content-Type: application/json' \
  -d '{"version": 0, "reason": "checking the model alone again"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['notice'])"
sleep 3; stream "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"auto"' planner_chosen | sed -n 2p
.venv/bin/python -m sajha.ai.planners_engine.learn rollback 1
.venv/bin/python -m sajha.ai.planners_engine.learn status --json | python3 -c "
import json,sys; d=json.load(sys.stdin); print('active:', d['active'])
for h in d['history']: print({k: h.get(k) for k in ('action','version','by','reason')})"
```

```text
Routing rules are off (no version active).
{"type": "planner_chosen", "planner": "calc_graph", "version": "1.0.0", "by": "label 0.60", "reason": "mock: calc_graph"}
active version: 1
active: 1
{'action': 'rollback', 'version': 1, 'by': 'cli', 'reason': 'command line'}
{'action': 'off', 'version': 0, 'by': 'testadmin', 'reason': 'checking the model alone again'}
{'action': 'approve', 'version': 1, 'by': 'testadmin', 'reason': 'proposal p20261012052053-980677'}
```

With no version active the model chose again (`label 0.60`). Any earlier version can be made active
the same way; the history keeps who did what and why. `ai.planners.learning.rules: false` ignores
approved rules without touching the files.

## 8. The bandit and its kill switch

The online bandit is off unless `ai.planners.learning.bandit` is `true` (optionally only for the tools
in `bandit_tools`). On, it keeps arms per tool, class and planner in the state store, exploits the best
arm with enough outcomes and explores within a capped share, again only among the allowed candidates.
Its kill switch (**Stop (kill switch)** on the page) stops it on every worker at once:

```bash
curl -s -X POST $B/api/ai/planner-routing/bandit -H "$K" -H 'Content-Type: application/json' -d '{"action": "stop", "reason": "not yet"}'; echo
curl -s $B/api/ai/planner-routing -H "$K" | python3 -c "import json,sys; b=json.load(sys.stdin)['bandit']; print({k: b[k] for k in ('enabled','killed')})"
curl -s -X POST $B/api/ai/planner-routing/bandit -H "$K" -H 'Content-Type: application/json' -d '{"action": "resume"}'; echo
```

```text
{"success":true,"notice":"The bandit is stopped on every worker (kill switch set)."}
{'enabled': False, 'killed': {'by': 'testadmin', 'at': 1791782486.7448957, 'reason': 'not yet'}}
{"success":true,"notice":"The kill switch is cleared."}
```

A guard sets the switch itself when explored choices succeed too rarely. With the `memory` state
store, `learn bandit stop` on the command line reaches only its own process: use the page or the API,
or a shared store (`redis` or `database`) with several workers.

## Summary

- Every automatic choice and its outcome is `planner_choice` in the run's audit record and on eval rows
- The learning job ranks planners per tool and question class from saved eval runs and those records,
  and writes a proposal with evidence, a diff and a hash
- Approval needs the exact hash, an explicit yes and the policy engine's consent; it creates an
  immutable version
- Approved rules choose with no model call (`by: learned`), only among allowed candidates; any version,
  or none, can be made active again
- The bandit is opt-in, capped, and has a kill switch shared by every worker

## Next

- The design: [LLM Tools](../architecture/LLM%20Tools.md#913-automatic-planner-selection) §9.13
- [Tutorial 53: Change a SAJHA Net Safely](TUTORIAL_53_sajha_net_console.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
