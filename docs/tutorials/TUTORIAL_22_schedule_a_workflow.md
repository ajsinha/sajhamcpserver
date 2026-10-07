# Tutorial 22: Schedule a Workflow

Build a workflow that loops over a list of prices, branches on the result and calls a tool
on one branch; run it from the command line and read its step timeline; break a step and
re-run the workflow from that step; put it on a cron schedule; start it from a signed
webhook; watch a parked run survive a restart; and publish it as an MCP tool. The design
(every field, durability, triggers, identity) is in
[Workflows](../architecture/Workflows.md).

## What you'll learn

- The shape of a workflow definition: steps, dependencies, mapping, branches, loops
- How a run is recorded step by step, and where to read it (page, CLI, API)
- How re-running from a failed step reuses the steps before it
- How cron and webhook triggers start runs, and how webhooks are signed
- What happens to a run when the server stops while it waits
- How a workflow becomes an ordinary MCP tool

## Prerequisites

- A SAJHA checkout with its virtual environment, running on `http://localhost:3002`, and an
  admin sign-in ([Tutorial 1](TUTORIAL_01_getting_started.md))
- The `sajha` CLI signed in as that admin ([Tutorial 15](TUTORIAL_15_sajha_cli_and_claude_desktop.md)):
  `sajha login -u admin`
- `curl`, and a token for the REST calls:

```bash
export SAJHA=http://localhost:3002
export TOKEN=$(curl -s -X POST $SAJHA/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"<your password>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
```

## Steps

### 1. Write the definition

Save this as `price_moves.yaml`. It uses only `calc_percentage_change`, which ships with
SAJHA and needs no API key.

```yaml
name: price_moves
description: Percentage moves for a list of prices, and a closer look at a big first move
input_schema:
  type: object
  properties:
    pairs: {type: array, description: "[{old, new}, ...]"}
    target: {type: number}
steps:
  - id: moves                          # one tool call per element of the list
    kind: foreach
    items: $input.pairs
    max_items: 10
    parallel: 2
    do:
      tool: calc_percentage_change
      params: {old_value: $item.old, new_value: $item.new}
  - id: first_big                      # depends on moves because it reads $steps.moves
    kind: condition
    if: "$steps.moves.items.0.percentage_change > 10"
    then: [to_target]
    else: [calm]
  - id: to_target
    tool: calc_percentage_change
    params: {old_value: $steps.moves.items.0.new_value, new_value: $input.target}
    retry: {max_attempts: 2, backoff_seconds: 1}
  - id: calm
    kind: wait
    seconds: 1
output:
  moves: $steps.moves.items
  to_target: $steps.to_target.percentage_change
```

Save it:

```bash
curl -s -X POST $SAJHA/api/workflows -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/yaml' --data-binary @price_moves.yaml | python -m json.tool | head -20
```

The answer is the normalised definition: every default filled in, and `first_big` with
`depends_on: [moves]`, which you never wrote. Open **Tools → Workflows** (`/workflows`)
and select `price_moves`: the graph shows `moves → first_big`, then two dashed branch
edges to `to_target` and `calm`. The **JSON** and **YAML** tabs show the same definition;
edit in any tab, the others follow.

### 2. Run it and read the timeline

```bash
sajha workflows run price_moves --wait 30 \
  --input-json '{"pairs": [{"old": 100, "new": 125}, {"old": 50, "new": 49}], "target": 150}'
```

```
run 6f0c...: succeeded
{"moves": [{"old_value": 100, "new_value": 125, "percentage_change": 25.0}, ...], "to_target": 20.0}
```

The first move is 25 %, so `to_target` ran and `calm` was skipped. See the steps:

```bash
sajha workflows show <run-id>
```

```
STEP       KIND       STATUS     TRIES  TIME   ERROR
moves      foreach    succeeded  1      12ms
first_big  condition  succeeded  0      0ms
to_target  tool       succeeded  1      4ms
calm       wait       skipped    0      -      branch not taken (first_big was true)
```

On the page, **Run history → Steps** draws the same run as a timeline: a bar per step on
one time axis, with each step's input and output, and the graph coloured by status.

### 3. Break a step, then re-run from it

Run it without `target`:

```bash
sajha workflows run price_moves --wait 30 --input-json '{"pairs": [{"old": 100, "new": 125}]}'
```

```
run 9a41...: failed (step to_target: Invalid arguments for tool calc_percentage_change: 'new_value': '' is not of type 'number' (after 2 attempts))
```

A missing input reads as `""`, the tool refuses it, the step was retried once (its
`retry`) and the run failed. Fix the definition: on the page, set `to_target`'s params to
`{"old_value": "$steps.moves.items.0.new_value", "new_value": 150}` and **Save**
(version 2). Then re-run the failed run from its failed step with the new definition:

```bash
curl -s -X POST $SAJHA/api/workflows/runs/<failed-run-id>/rerun -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"latest_definition": true}' | python -m json.tool
```

The new run has `parent_run_id` set to the failed one and `from_step: to_target`. Its
`moves` and `first_big` steps were not run again: their records say `reused_from` the old
run. (The page's **Re-run** button does the same with the definition the run used.)

### 4. Put it on a schedule

On the page, open **Triggers**, **Add trigger → cron schedule**, set the cron to
`* * * * *` (every minute) and your timezone, set the trigger's **Input** to
`{"pairs": [{"old": 10, "new": 12}]}`, and **Save**. Within a minute or so:

```bash
sajha workflows runs price_moves
```

shows a run with trigger `cron`. Each run's input also has `scheduled_for`, the slot it
fired for. With several workers, each slot still fires once: the first worker to claim
the slot in the shared state store fires it (see
[Scaling and State](../architecture/Scaling%20and%20State.md)). Remove the trigger (or
**Disable** the workflow) before you go on.

### 5. Start it from a signed webhook

Add a **webhook** trigger with id `inbound` and **Save**; SAJHA generates its secret. Read
it (the page shows it masked):

```bash
curl -s "$SAJHA/api/workflows/price_moves?reveal=1" -H "Authorization: Bearer $TOKEN" \
  | python -c 'import sys,json;print([t for t in json.load(sys.stdin)["definition"]["triggers"] if t["id"]=="inbound"][0]["secret"])'
```

Send a delivery the way a partner system would, signing the timestamp and the body:

```python
import hashlib, hmac, json, time, urllib.request
secret = "<the secret>"
body = json.dumps({"pairs": [{"old": 80, "new": 100}], "target": 90}).encode()
ts = str(int(time.time()))
sig = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
req = urllib.request.Request("http://localhost:3002/api/workflows/price_moves/hooks/inbound", data=body,
                             headers={"Content-Type": "application/json", "X-Sajha-Timestamp": ts,
                                      "X-Sajha-Signature": sig, "X-Sajha-Delivery": "order-1"})
print(urllib.request.urlopen(req).read())
```

The answer is `202` with the run id. Send exactly the same request again: `409`, "already
received (replay)". Change one byte of the body without re-signing: `401`. A timestamp
more than five minutes old is refused too. Sending a new signature with the same
`X-Sajha-Delivery: order-1` returns the first run instead of starting another (the delivery
id is the run's idempotency key).

### 6. Watch a parked run survive a restart

Change `calm`'s `seconds` to `60` and make the condition false for your input (or add a
wait step of its own), save, and run it without waiting:

```bash
sajha workflows run price_moves --input-json '{"pairs": [{"old": 100, "new": 101}]}'
sajha workflows runs price_moves --status waiting
```

A wait longer than `workflows.inline_wait_seconds` (5 s) parks the run: status `waiting`,
no worker busy, the wake-up time stored in the database. Stop the server (Ctrl-C) and start
it again. A minute after you started the run, it finishes `succeeded`: the scheduler found
the parked run and woke it. A run that was **executing** a step when a worker died is
picked up the same way by another worker once its heartbeat is stale; a step that cannot
safely run twice is marked failed instead, and you re-run it from that step as in step 3
([Workflows, section 3](../architecture/Workflows.md#durability-resume-and-re-run)).

### 7. Publish it as a tool

Tick **Publish as an MCP tool** (administrators only) and **Save**. `price_moves` is now in
`tools/list` for every client allowed to see it, in both protocol eras, with the
workflow's `input_schema`:

```bash
sajha tools call price_moves --json '{"pairs": [{"old": 4, "new": 5}], "target": 6}'
```

returns `{run_id, status, output}`, and the run appears in the history with trigger
`tool`. The steps ran as you, the owner, whoever called the tool, which is why only
administrators may publish.

## What you built

A durable, scheduled, signed-webhook-triggered workflow with a loop and a branch, that you
can follow step by step, re-run from a failure, and call as a tool. Next: add an
`approval` step and decide it on **Admin → Approvals**
([Tutorial 20](TUTORIAL_20_policies_approvals_and_audit.md)); deliver each run's output to a
file or an allow-listed webhook with `delivery`; or chain a composite tool
([Tutorial 3](TUTORIAL_03_build_a_composite_tool.md)) as a `composite` step.

Next tutorial: [Test and Canary Your Tools](TUTORIAL_23_test_and_canary_your_tools.md).
