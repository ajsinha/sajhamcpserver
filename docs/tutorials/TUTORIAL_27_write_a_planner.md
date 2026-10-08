# Tutorial 27: Write a Planner

A planner is the strategy an LLM tool (or the Ask SAJHA page) follows: which model calls, in
what order, when to call tools, when to check its own work and when to stop. In SAJHA a planner
is a file: a small graph of stages from a fixed library, with every loop bounded. Here you write
one for a desk that mostly asks "how much did this change?", answer those questions with one
calculator call and no model, send everything else to ReAct, and check the figures ReAct writes.
Everything runs offline on the mock model. The file format is owned by the
[Planner Reference](../architecture/Planner%20Reference.md); why planners are configuration is
in [LLM Tools](../architecture/LLM%20Tools.md) section 9.

## What you'll learn

- How a planner file is laid out: stages, outcomes, transitions and bounded edges
- How the loader refuses a planner that could loop forever, and how lint reports it
- How to dry-run a planner on the mock model and read the stage path
- How an LLM tool names a planner, pins a version and lets the caller choose
- How to change a planner safely with versions

## Prerequisites

- A SAJHA checkout with its virtual environment and an admin sign-in
  ([Tutorial 1](TUTORIAL_01_getting_started.md))
- An LLM tool to put the planner in: [Tutorial 26](TUTORIAL_26_build_an_llm_tool.md)

## Steps

### 1. Read a shipped planner

SAJHA ships its strategies as files in `config/planners/`. Open `config/planners/react.yaml`, the
default:

```yaml
name: react
version: 1.0.0
start: act
stages:
  act:
    type: act                                   # one model call with the offered tools
    outcomes:
      called:   { next: act, max_visits: steps }   # bounded by max_steps
      answered: { next: answer }
  answer:
    type: answer
```

Each stage has a `type` from the stage library and ends with an **outcome** (`act` ends `called`
or `answered`); `outcomes` sends each outcome to the next stage. The `act` loop is a
**bounded edge**: it can repeat only as long as the run has steps left. Then open
`config/planners/reflect.yaml`: a draft is reviewed by a critic and revised at most twice
(`max_visits: 2, on_exhausted: answer`), so a critic that never passes still ends in an answer.

### 2. Decide the shape first

Before writing YAML, decide the stages and where each outcome goes:

- `match` the question against a pattern ("from 80 to 100" and the word "percent"); a match
  goes to `call` the calculator, then `answer` with a template, and no model is called
- anything else goes to a `planner` stage that runs `react`
- what ReAct writes is checked with `verify` (every figure must appear in a tool result); a
  mismatch is `revise`d once, then the run answers whatever the check says, with the findings as
  caveats

### 3. Write the file

Create the file `pct_desk.yaml` in `config/planners/`:

```yaml
name: pct_desk
version: 1.0.0
description: Answers percentage-change questions with one calculator call and no model; other questions go to ReAct and are checked against the data.
use_when: Desks that mostly ask how much a figure changed between two values.
start: shape
stages:
  shape:
    type: match
    rules:
      - name: pct
        pattern: 'from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)'
        keywords: [percent]
        tool: calc_percentage_change          # matches only if the caller may use this tool
    outcomes:
      pct:  { next: compute }
      none: { next: general }
  compute:
    type: call
    tool: calc_percentage_change
    arguments: { old_value: "{{groups.old_value}}", new_value: "{{groups.new_value}}" }
    outcomes:
      done:  { next: done }
      error: { next: general }                # the call failed: let ReAct try
  done:
    type: answer
    template: "From {{groups.old_value}} to {{groups.new_value}} is a change of {{results[-1].data.percentage_change}}%."
  general:
    type: planner
    planner: react@1.0.0                      # pinned: a new react version will not change this desk
    next: check
  check:
    type: verify
    checks: [numbers_in_results]
    outcomes:
      ok:       { next: answer }
      mismatch: { next: fix, max_visits: 1, on_exhausted: answer }
  fix:
    type: revise
    address: findings
    next: check
  answer:
    type: answer
```

A few things to notice. `{{groups.old_value}}` is a template: the named group the `match` stage
captured. Because the whole value is one placeholder, it keeps its type, and the `call` stage
converts the text to the number the tool's input schema wants. The rule's `tool` makes it match
only when the caller may use the calculator, so the deterministic path can never reach a tool the
caller cannot. And `react@1.0.0` pins a version: editing `react.yaml` later will not change this
desk.

The registry reads the file through the storage backend and reloads it on change. Files load with
plain `yaml.safe_load`, so any YAML editor reads them the same way; that is why transitions live
under `outcomes`, never `on` (a bare `on:` loads as `true` in YAML 1.1).

### 4. Lint it, and watch the loader refuse a loop

```bash
python -m sajha.quality lint --tool 'planner:*'
```

The new file reports nothing. Now delete `max_visits: 1, on_exhausted: answer` from the
`mismatch` transition and run lint again:

```
planner:pct_desk.yaml
  ERROR   P020                 planner pct_desk@1.0.0: stages: unbounded cycle: check -> fix -> check (add max_visits to an edge of it)
```

The file is refused: every cycle must cross a bounded edge. A refused edit never replaces the
version that was loaded before, so anything already using `pct_desk` keeps running the last good
file. Put the bound back. The full list of rules (P001 to P071) is in the
[Planner Reference](../architecture/Planner%20Reference.md) section 12.

### 5. Dry-run it on the mock model

The dry run runs a planner against the mock model and returns the stages it took. Tools are
offered as usual, but only tools marked read-only actually run; name the calculator in
`run_tools` to let it run:

```bash
curl -s -X POST http://localhost:3002/api/ai/planners/dry-run -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"planner": "pct_desk", "question": "What is the percent change from 80 to 100?",
       "run_tools": ["calc_percentage_change"]}'
```

The answer has `"path": ["shape", "compute", "done"]` and
`"answer": "From 80 to 100 is a change of 25.0%."`, with no model call on the way. Ask
`"What is the future value of 5000 at 7 percent for 20 years?"` with
`"run_tools": ["calc_future_value"]`: the path is `shape → general → check → answer`, and
`trace` shows ReAct's own stages inside the sub-run (`pct_desk>react/act`). Without `run_tools`
the calculator is not run, the `call` stage ends `error`, and the path shows the fallback:
`shape → compute → general → check → answer`.

(Use the port your server listens on; the token comes from `POST /api/auth/login`.
`GET /api/ai/planners/pct_desk` shows the compiled stages.)

### 6. Use it from an LLM tool

In the `llm` block of an `answer`-mode tool (for example a copy of
`config/tools/llm_markets_assistant.json`), name the planner, pinned:

```json
"planner": "pct_desk@1.0.0",
"planner_choices": ["pct_desk@1.0.0", "react"]
```

`planner_choices` is optional. With it, the tool gets an optional `planner` argument whose schema
is an enum of exactly those values, so the caller may pick ReAct instead; any other value fails
argument validation. Without it the tool's owner, not the caller, decides the strategy, because
the strategy decides cost and looping. If a tool names a planner that does not exist or does not
validate, the tool does not load. The result's `planner` and the `llm_tool_run` audit record name
the planner, its version, why it was chosen (`tool config`, `caller choice`, `version route` or
`server default`) and the stages taken.

On the Ask SAJHA page an admin can try it on one question with `"planner": "pct_desk"` in the
`POST /api/ai/ask` body: the stages appear as a path line above the answer while it runs.

### 7. Change it safely

To change the desk without surprising the tools that pin it:

1. Copy `pct_desk.yaml` to `pct_desk@1.0.0.yaml` (the kept version; the file name and the
   `version` inside must agree).
2. Edit `pct_desk.yaml` and set `version: 1.1.0`. Editing a file without changing its version
   changes every tool that resolves that version; lint warns about it (P070).
3. Tools that name `pct_desk` now get 1.1.0; tools that pin `pct_desk@1.0.0` keep the old one.
   To compare the two on live traffic, give the tool a versions file whose new version names
   `pct_desk@1.1.0` and send it a canary share ([Tutorial 23](TUTORIAL_23_test_and_canary_your_tools.md)).

## What you learned

- A planner file is a graph of stages; each outcome goes to the next stage, and every loop
  crosses a bounded edge with somewhere to go when the bound is reached
- Deterministic stages (`match`, `call`, `verify`) cost no model calls; put them first
- The loader and lint refuse a planner that could loop forever, and a refused edit keeps the
  last good version running
- The dry run shows the path a question takes, on the mock model, without running tools that
  write
- Tools pin planner versions, and may let the caller choose among a fixed list

## Next

- Every stage type, the `when` expression language and the shipped strategies:
  [Planner Reference](../architecture/Planner%20Reference.md)
- A stage type of your own, in code: [Extending the Intelligence Layer](../architecture/Extending%20the%20Intelligence%20Layer.md)
  section 4.6
- Next tutorial: [Tutorial 28: Build a SAJHA Net](TUTORIAL_28_build_a_sajha_net.md)

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
