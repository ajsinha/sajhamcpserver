# Tutorial 45: Quantitative Planners

A model is good at deciding which data a question needs and bad at arithmetic. The quantitative
planners keep the arithmetic out of the model: it names the figures and the operations, SAJHA reads
the figures, computes, and keeps every result in a workspace of quantities with a unit, an as-of
date, a source and a lineage back to the tool calls. This tutorial runs each of them: the numbers
check, `calc_graph` and `estimate_then_compute`, a sensitivity table with `scenario`, SQL over tool
results with `data_analyst`, a solver with `optimize`, sandboxed code with `code_act` (and how to
allow it by role), `reconcile`, `research_writer`, the eval sets, and how `router` and `auto` choose
among them. The design, every setting and the limits are in
[Quantitative Planners](../architecture/Quantitative%20Planners.md); planner files are in the
[Planner Reference](../architecture/Planner%20Reference.md).

**What was verified.** Every step below was run as written against a server started from a
checkout on a scratch database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`) and scratch
directory for loaded results (`SAJHA_BI_SCRATCH_DIR`), with the default offline mock provider, and
the outputs shown are from that run, shortened where marked. Step 4 uses the qlrisk risk tools, which
need the `qlrisk` package ([Tutorial 41](TUTORIAL_41_qlrisk_risk_tools.md)); step 5 reads the sample
DuckDB database the checkout ships; step 6 needs SciPy. With a real model the replies differ; with the
mock they are deterministic.

## What you'll learn

- What a quantity is, and how the workspace and its lineage reach the Ask result
- How the reserved `numbers_check` setting checks any planner's figures
- How `calc_graph` and `estimate_then_compute` compute an answer the model only describes
- How `scenario` turns a grid of shocks into a sensitivity table, and `reconcile` compares one figure
  across sources
- How `data_analyst` runs read-only SQL over tool results, and `optimize` solves an allocation
- Why `code_act` is refused until a role is allowed, and how to allow one
- How `router` and `auto` pick a quantitative planner, and how the eval sets measure them

## Prerequisites

- SAJHA running from a checkout ([Quick Start](../getting-started/Quick%20Start.md)) and an
  administrator credential: choosing the planner per ask is for administrators. The examples use the
  development key from `config/apikeys.json` (role `admin`), a server on port 3133, and two shell
  helpers: `ask` returns the Ask result as JSON, `stream` prints chosen events of the ask's event
  stream and then the answer.

```bash
P=/tmp/t45; mkdir -p $P
SAJHA_DB_PATH=$P/t45.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3133
```

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
ask() {  # ask QUESTION [PLANNER-JSON]
  body=$(python3 -c "import json,sys; d={'question': sys.argv[1]}; d.update({'planner': json.loads(sys.argv[2])} if len(sys.argv) > 2 else {}); print(json.dumps(d))" "$@")
  curl -s -X POST http://127.0.0.1:3133/api/ai/ask -H "$K" -H 'Content-Type: application/json' -d "$body"
}
stream() {  # stream QUESTION PLANNER-JSON EVENT-TYPES...
  q=$1; p=$2; shift 2
  body=$(python3 -c "import json,sys; print(json.dumps({'question': sys.argv[1], 'planner': json.loads(sys.argv[2])}))" "$q" "$p")
  curl -s -N -X POST 'http://127.0.0.1:3133/api/ai/ask?stream=1' -H "$K" -H 'Content-Type: application/json' -d "$body" \
  | python3 -c "
import json,sys
want=set(sys.argv[1:])
for line in sys.stdin:
    if not line.startswith('data: '): continue
    e=json.loads(line[6:])
    if e['type'] in want: print(json.dumps({k: v for k, v in e.items() if k not in ('seq', 'ts', 'trace_id')}))
    if e['type'] == 'done' and e.get('result'): print('answer:', e['result']['answer']); print('caveats:', e['result']['caveats'])
" "$@"
}
```

The planner argument is JSON: a name (`'"calc_graph"'`) or an overlay that replaces some of a
planner's settings for this ask (`'{"use": "react", "settings": {...}}'`).

## 1. The planners and who may run them

```bash
curl -s http://127.0.0.1:3133/api/ai/planners -H "$K" | python3 -c "
import json,sys
for p in json.load(sys.stdin)['planners']:
    if p['name'] in ('calc_graph','estimate_then_compute','scenario','data_analyst','code_act','optimize','research_writer','reconcile','auto','router'):
        print(p['name'], p['version'], p.get('roles'), p.get('permitted'))"
```

```text
auto 1.1.0 None None
calc_graph 1.0.0 None None
code_act 1.0.0 [] False
data_analyst 1.0.0 None None
estimate_then_compute 1.0.0 None None
optimize 1.0.0 None None
reconcile 1.0.0 None None
research_writer 1.0.0 None None
router 1.1.0 None None
scenario 1.0.0 None None
```

`code_act` runs code, so it is role-limited: no role may run it until `ai.quant.code_act.roles`
names one, and even an administrator sees `permitted: False` (step 7). `optimize` needs SciPy;
without it the file is not loaded and an administrator finds it under `unavailable`.

## 2. A computed figure: `calc_graph`

The model writes a computation graph, not an answer: tool reads, constants the question states and
operations from the library. SAJHA validates the graph before anything runs (cycles, unknown tools and
operations, read paths, and the units of every operation), runs it, and the model writes prose around
the quantities.

```bash
stream "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"calc_graph"' graph
```

```text
{"type": "graph", "stage": "compute", "attempt": 1, "status": "done", "nodes": 4, "errors": [], "failed": {}, "answer_with": ["growth"]}
answer: growth is 8.44717712 percent.
caveats: []
```

The Ask result carries the workspace, each quantity with its unit, its source and, for a computed
one, its lineage:

```bash
ask "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"calc_graph"' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('path:', d['planner_path'])
for q in d['workspace']['quantities']: print(q['name'], q['value'], q['unit'], q['source'], q.get('lineage'))"
```

```text
path: ['plan', 'compute', 'draft', 'verify', 'answer']
end 180.0 unitless {'kind': 'constant', 'text': 'stated in the question'} None
start 120.0 unitless {'kind': 'constant', 'text': 'stated in the question'} None
years 5.0 years {'kind': 'constant', 'text': 'stated in the question'} None
growth 8.447177119769854 percent {'kind': 'operation', 'op': 'cagr'} {'op': 'cagr', 'inputs': ['start', 'end', 'years'], 'args': {'years': 5.0}}
```

`verify` ran `numbers_in_workspace`: the figure in the answer matched the `growth` quantity at the
precision written. A graph that does not validate (a percent change of a rate, USD minus EUR, an
operation that does not exist, a cycle) goes back to the model once with its errors; a second refusal
ends the run with the errors as caveats, so no figure is invented. The mock model always writes a
valid graph; `tests/ai/test_quant_evals.py` scripts wrong ones to show the refusal and the re-plan.

## 3. A sanity check: `estimate_then_compute`

The model first gives a rough magnitude with a unit, then `calc_graph` runs as a sub-planner, and the
check `estimate_consistent` compares the two. When they agree within a factor of
`settings.tolerance_factor` (10), the computed figure is the answer:

```bash
stream "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"estimate_then_compute"' estimate graph
```

```text
{"type": "estimate", "stage": "estimate", "value": 50.0, "unit": "percent"}
{"type": "graph", "stage": "compute", "attempt": 1, "status": "done", "nodes": 4, "errors": [], "failed": {}, "answer_with": ["growth"]}
answer: growth is 8.44717712 percent.
caveats: []
```

When they disagree, the graph is planned once more, and if they still disagree the computed figure is
answered with the estimate as a caveat. The mock's estimate for a spread is a bare difference with no
unit, which shows that path:

```bash
stream "What is the spread of a 4.25% Treasury yield over a 3.80% Bund yield, in basis points?" '"estimate_then_compute"' estimate graph
```

```text
{"type": "estimate", "stage": "estimate", "value": -0.4500000000000002, "unit": "unitless"}
{"type": "graph", "stage": "compute", "attempt": 1, "status": "done", "nodes": 3, "errors": [], "failed": {}, "answer_with": ["spread"]}
{"type": "graph", "stage": "compute", "attempt": 2, "status": "done", "nodes": 3, "errors": [], "failed": {}, "answer_with": ["spread"]}
answer: spread is 45.0 bp.
caveats: ['The computed spread is 45 bp, but a rough estimate was -0.45 unitless: the units do not agree.']
```

The computed figure always wins; the estimate is never the answer.

## 4. A sensitivity table: `scenario`

`scenario` prices a grid of shocks, one tool call per point, and SAJHA tabulates the values and their
differences from the base. The model defines the grid unless the planner's `grid` setting does; here
an overlay sets it, so the trades and the shock are exact. The tool is qlrisk's `qlrisk_price_trades`
with the payer swap of [Tutorial 41](TUTORIAL_41_qlrisk_risk_tools.md), shocked in parallel from
−50 to +50 bp in 25 bp steps:

```bash
cat > $P/grid.json <<'EOF'
{"use": "scenario", "settings": {"grid": {
  "tool": "qlrisk_price_trades",
  "arguments": {"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000,
                            "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}],
                "advanced": {"market_data": {"valuation_date": "2026-10-09"}}},
  "shock_path": "advanced.market_data.shocks", "value_path": "$.total_npv", "unit": "USD",
  "as_of_path": "$.valuation_date",
  "factors": [{"label": "rates parallel", "shock": {"risk_classes": ["IR"], "shape": "parallel"},
               "size_field": "size_bp", "from": -50, "to": 50, "step": 25}]}}}
EOF
stream "Price the trades: how does the swap's total NPV move when rates shift in parallel?" "$(cat $P/grid.json)" scenario_grid
```

```text
{"type": "scenario_grid", "stage": "grid", "by": "settings", "tool": "qlrisk_price_trades", "points": 5, "factors": ["rates parallel"]}
answer: base: -22,834.98 USD [point_base]; rates parallel -50 bp: -253,701.46 USD (change -230,866.48, -1011.02%) [point_p1]; rates parallel -25 bp: -137,571.78 USD (change -114,736.80, -502.46%) [point_p2]; rates parallel +25 bp: 90,525.95 USD (change 113,360.93, 496.44%) [point_p3]; rates parallel +50 bp: 202,527.80 USD (change 225,362.78, 986.92%) [point_p4].
caveats: []
```

The question names the tool's purpose ("price the trades") so that it is among the tools offered to
the ask; a grid naming a tool that is not offered is refused. The base is Tutorial 41's NPV, and the
swap gains about 4,560 USD per basis point, as its DV01 said. The table is on the Ask result as
`scenario_tables` (also in the `ai_ask` audit entry), so a caller reads it without parsing the
workspace; each value is a quantity read from its call, and each change has lineage to both calls:

```bash
ask "Price the trades: how does the swap's total NPV move when rates shift in parallel?" "$(cat $P/grid.json)" | python3 -c "
import json,sys; d=json.load(sys.stdin)
t=d['scenario_tables'][0]; print({k: t[k] for k in ('stage','tool','unit','failed')})
for r in t['rows']: print(r['point'], r['label'], r['status'], round(r['value'],2), r['change'] and round(r['change'],2), r['call_id'])
q={x['name']: x for x in d['workspace']['quantities']}
print(json.dumps({k: q['table.p3'][k] for k in ('value','unit','as_of','source')}))
print(json.dumps(q['table.p3.change']['lineage']))"
```

```text
{'stage': 'table', 'tool': 'qlrisk_price_trades', 'unit': 'USD', 'failed': 0}
base base ok -22834.98 None point_base
p1 rates parallel -50 bp ok -253701.46 -230866.48 point_p1
p2 rates parallel -25 bp ok -137571.78 -114736.8 point_p2
p3 rates parallel +25 bp ok 90525.95 113360.93 point_p3
p4 rates parallel +50 bp ok 202527.8 225362.78 point_p4
{"value": 90525.95251532923, "unit": "USD", "as_of": "2026-10-09", "source": {"kind": "tool", "call_id": "point_p3", "tool": "qlrisk_price_trades", "version": "", "arguments": {"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}], "advanced": {"market_data": {"valuation_date": "2026-10-09", "shocks": [{"risk_classes": ["IR"], "shape": "parallel", "size_bp": 25.0}]}}}, "path": "$.total_npv", "unit_from": "declared"}}
{"op": "diff", "inputs": ["table.p3", "table.base"], "args": {}}
```

A point whose call fails is a failed row with the reason and a caveat; nothing is filled in. The grid
is bounded by `settings.max_points` (9 with the base) and the run's limits.

## 5. SQL over tool results: `data_analyst`

`data_analyst` gathers with tools, loads every successful result into the caller's private DuckDB
scratch file, and lets the model write one read-only `SELECT` over those tables only:

```bash
stream "List the tables in the DuckDB database with their row counts" '"data_analyst"' tool_call table_loaded query
```

```text
{"type": "tool_call", "id": "call_1_d8be7ab1", "name": "duckdb_list_tables", "arguments": {"include_system_tables": false}, "step": 1}
{"type": "table_loaded", "table": "duckdb_list_tables", "call_id": "call_1_d8be7ab1", "tool": "duckdb_list_tables", "rows": 3, "columns": ["name", "type", "schema", "row_count"]}
{"type": "query", "id": "query_1", "sql": "SELECT * FROM duckdb_list_tables LIMIT 20", "ok": true, "error": "", "rows": 3, "sources": ["call_1_d8be7ab1"]}
answer: The query query_1 returned: [{"name": "customers", "type": "table", "schema": "main", "row_count": 50}, {"name": "orders", "type": "table", "schema": "main", "row_count": 80}, {"name": "products", "type": "table", "schema": "main", "row_count": 27}]
caveats: []
```

Every query is on the Ask result as `queries`, and each numeric column of a successful one enters the
workspace with the query and its source calls as lineage. Asking again within the time to live
(`settings.ttl_minutes`, 60) finds the first table still in your scratch file, so the new one is
`duckdb_list_tables_2`:

```bash
ask "List the tables in the DuckDB database with their row counts" '"data_analyst"' | python3 -c "
import json,sys; d=json.load(sys.stdin)
for q in d['queries']: print({k: q.get(k) for k in ('id','sql','ok','tables','sources','row_count','quantities')})
for q in d['workspace']['quantities']: print(q['name'], q['value'], q['unit'], q['lineage']['op'], q['lineage'].get('sources') or q['lineage'].get('inputs'))"
```

```text
{'id': 'query_1', 'sql': 'SELECT * FROM duckdb_list_tables_2 LIMIT 20', 'ok': True, 'tables': ['duckdb_list_tables_2'], 'sources': ['call_1_d8be7ab1'], 'row_count': 3, 'quantities': ['query_1.row_count']}
query_1.row_count [50.0, 80.0, 27.0] unitless sql [{'call_id': 'call_1_d8be7ab1', 'tool': 'duckdb_list_tables'}]
```

A statement that is not one `SELECT`, or that names a table this run did not load, is refused and goes
back to the model with the reason.

## 6. A solver: `optimize`

The model writes a formulation (variables, a linear or convex quadratic objective, linear
constraints); SciPy solves it and SAJHA checks the solution against every constraint before the model
sees it:

```bash
stream "Maximise 3x + 5y subject to x <= 4, 2y <= 12 and 3x + 2y <= 18. What is the optimal objective value?" '"optimize"' optimization
```

```text
{"type": "optimization", "stage": "solve", "status": "optimal", "method": "linprog", "objective": 36.0, "message": "Optimization terminated successfully. (HiGHS Status 7: Optimal)"}
answer: The optimal objective is 36 at x = 2, y = 6.
caveats: []
```

The values and the objective are in the workspace as `solve.x`, `solve.y` and `solve.objective`. An
infeasible problem is reported as such, never answered with made-up numbers:

```bash
stream "Maximise 3x + 5y subject to x <= 4, 2y <= 12, 3x + 2y <= 18 and x + y >= 20. What is the optimum?" '"optimize"' optimization
```

```text
{"type": "optimization", "stage": "solve", "status": "infeasible", "method": "linprog", "objective": null, "message": "no point satisfies every constraint and bound"}
answer: There is no solution: the problem is infeasible (no point satisfies every constraint and bound).
caveats: ['solve: infeasible: no point satisfies every constraint and bound']
```

## 7. Sandboxed code, by role: `code_act`

For a computation the operation library cannot express, `code_act` lets the model write Python that
runs in the [Sandbox](../architecture/Sandbox.md), network off, and prints a JSON object of
quantities. Out of the box nobody may run it:

```bash
ask "Add up 1.5, 2.25 and 3" '"code_act"' | python3 -c "
import json,sys; d=json.load(sys.stdin); print(d['stopped_by'], '|', d['answer'])"
```

```text
refused | planner code_act uses the code_act stage, which no role is allowed to run
```

The run stopped before any model call. Allow a role with `ai.quant.code_act.roles` (here by
environment, `SAJHA_AI_QUANT_CODE_ACT_ROLES`, a comma-separated list or a JSON list) and restart:

```bash
SAJHA_AI_QUANT_CODE_ACT_ROLES=admin SAJHA_DB_PATH=$P/t45.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3133
```

```bash
curl -s http://127.0.0.1:3133/api/ai/planners -H "$K" | python3 -c "
import json,sys; print([{k: p.get(k) for k in ('name','roles','permitted')} for p in json.load(sys.stdin)['planners'] if p['name']=='code_act'])"
ask "Add up 1.5, 2.25 and 3" '"code_act"' | python3 -c "
import json,sys; d=json.load(sys.stdin); print(d['stopped_by'], '|', d['planner_path'], [s['name'] for s in d['steps']], '|', d['answer'])
for c in d['code_runs']: print({k: c.get(k) for k in ('stage','attempt','ok','exit_code','backend','output')})"
```

```text
[{'name': 'code_act', 'roles': ['admin'], 'permitted': True}]
answer | ['gather', 'gather', 'compute', 'draft', 'answer'] ['qlrisk_saccr'] | mock_total is 6.75 unitless.
{'stage': 'compute', 'attempt': 1, 'ok': True, 'exit_code': 0, 'backend': 'subprocess', 'output': '{"quantities": {"mock_total": {"value": 6.75, "unit": "unitless"}}}\n'}
```

The mock model's gather step picks a tool by keyword, here one that failed for want of trades (its
caveat is left out above); the program does not depend on it. Every run, with its code, input digest,
output and exit code, is on the Ask result as `code_runs`, in the `ai_ask` audit entry and in its own
`ai_code_act` audit event. A tool or the Ask page may still offer `code_act` only to the roles listed.

## 8. One figure, two sources: `reconcile`

`reconcile` asks the model where each source holds the figure (a call id and a JSONPath, never a
value); SAJHA reads, aligns units and dates, and lists each difference beyond the tolerance
(`settings.tolerance`, 0.5% of the reference). Two calculators that compound differently disagree on
a future value:

```bash
Q='Do calc_future_value and calc_compound_interest agree on the future value? present value 5000, principal 5000, rate 7, years 20, compounds_per_year 12'
stream "$Q" '"reconcile"' tool_call
ask "$Q" '"reconcile"' | python3 -c "
import json,sys; d=json.load(sys.stdin); r=d['reconciliations'][0]
print({k: r[k] for k in ('stage','tolerance','align')}); print(r['figures'][0]['rows'])
b=r['breaks'][0]; print({k: b[k] for k in ('figure','source','reference','value','reference_value','difference')}); print([(x['call_id'], x['tool'], x['path']) for x in b['lineage']])"
```

```text
{"type": "tool_call", "id": "call_1_3e9a4cda", "name": "calc_compound_interest", "arguments": {"principal": 5000, "rate": 7, "years": 20, "compounds_per_year": 12}, "step": 1}
{"type": "tool_call", "id": "call_2_91248c16", "name": "calc_future_value", "arguments": {"present_value": 5000, "rate": 7, "years": 20}, "step": 1}
answer: undated: calc_compound_interest 20,193.69; calc_future_value 19,348.42; calc_future_value − calc_compound_interest -845.27 (-4.19%) BEYOND TOLERANCE.
caveats: []
{'stage': 'compare', 'tolerance': 0.005, 'align': 'day'}
[{'as_of': None, 'values': {'calc_compound_interest': 20193.69, 'calc_future_value': 19348.42}, 'differences': {'calc_future_value': -845.2700000000004}, 'differences_pct': {'calc_future_value': -4.185812498854843}, 'breaks': ['calc_future_value']}]
{'figure': 'future_value', 'source': 'calc_future_value', 'reference': 'calc_compound_interest', 'value': 19348.42, 'reference_value': 20193.69, 'difference': -845.2700000000004}
[('call_2_91248c16', 'calc_future_value', '$.future_value'), ('call_1_3e9a4cda', 'calc_compound_interest', '$.future_value')]
```

(The mock calls every tool a question names; a real model chooses its sources.) The summary is on the
Ask result as `reconciliations` and in the `ai_ask` audit entry; the difference carries both
lineages. Two currencies are compared only through an FX rate read from a tool result, never at a
guessed rate.

## 9. A cited write-up: `research_writer`

`research_writer` is not quantitative: an outline whose steps are sections, one gathering sub-run per
section, a draft that cites call ids in square brackets, and a check that every paragraph with a
figure cites one:

```bash
ask "Write a short note on the DuckDB tables and their row counts" '"research_writer"' | python3 -c "
import json,sys; d=json.load(sys.stdin); print([p for p in d['planner_path'] if '/' not in p]); print(d['answer']); print(d['caveats'], d['citations'])"
```

```text
['outline', 'sections', 'draft', 'verify', 'answer']
duckdb list tables for the question: total count = 3 (from duckdb_list_tables with include_system_tables=False). [call_1_d8be7ab1]
[] ['call_1_d8be7ab1']
```

## 10. The numbers check on any planner

The reserved setting `numbers_check` (`off`, `warn`, `enforce`; default `ai.planners.numbers_check`)
runs the numbers validator on any planner's final answer, without changing its file. Here an overlay
turns it on for `react`:

```bash
stream "What is the percentage change from 80 to 100?" '{"use": "react", "settings": {"numbers_check": "warn"}}' tool_call numbers_check
```

```text
{"type": "tool_call", "id": "call_1_cd51247c", "name": "calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}, "step": 1}
{"type": "numbers_check", "mode": "warn", "check": "numbers_in_results", "unmatched": [], "revised": false, "removed": []}
answer: percentage change = 25.0 (from calc_percentage_change with old_value=80, new_value=100).
caveats: []
```

Every figure came from the tool result, so nothing is unmatched. With `warn` an unmatched figure is
named in a caveat; with `enforce` the answer is revised once and a figure still unmatched is removed.
The check is `numbers_in_results` for a run with no workspace and `numbers_in_workspace` once a
planner has computed quantities, so "45 bp", "0.45%" and "0.0045" all match a spread of 45 bp.

## 11. How `router` and `auto` choose

`router` (1.1.0) tries its configured rules and the recipes first, then its `quant_pattern` (percent
change, CAGR, basis points, spread, NPV, what-if, sensitivity and the like) before the multi-step
check, sending a match to `settings.quant_default` (`calc_graph`). `auto` (1.1.0) offers
`calc_graph`, `scenario` and `data_analyst` to its classifier beside `react`, `plan_execute`,
`reflect` and `map_reduce`, each described by its `use_when`; `code_act` and `optimize` are never
default candidates.

```bash
for pl in '"router"' '"auto"'; do
  ask "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" "$pl" | python3 -c "
import json,sys; d=json.load(sys.stdin); print(d['planner'], '|', [p for p in d['planner_path'] if '/' not in p], '|', d['answer'])"
done
stream "Price the trades: how does the swap's total NPV move in a sensitivity to rates?" '"auto"' planner_chosen | head -2
ask "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '{"use": "router", "settings": {"use_quant": false}}' | python3 -c "
import json,sys; d=json.load(sys.stdin); print(d['planner'])"
```

```text
router>calc_graph | ['rules', 'recipes_check', 'quant', 'computed', 'answer'] | growth is 8.44717712 percent.
auto>calc_graph | ['known', 'choose', 'run', 'verify', 'gate'] | growth is 8.44717712 percent.
{"type": "planner_chosen", "planner": "auto", "version": "1.1.0", "by": "caller choice", "reason": "caller choice"}
{"type": "planner_chosen", "planner": "scenario", "version": "1.0.0", "by": "label 0.60", "reason": "mock: scenario"}
router>react
```

`auto` checks the chosen planner's answer with `numbers_in_workspace`, so a computed figure is not
mistaken for an invented one, and it does not escalate `calc_graph`, `scenario` or `data_analyst`
merely for low tool confidence (`settings.self_checked`): they verify their own figures. With the mock,
the sensitivity question's model-written grid has no trades, so its points fail and `auto` escalates;
a real model writes the trades, or a tool's overlay sets the grid as in step 4. `use_quant: false`
restores the old routing.

**Eval filtering.** When an LLM tool has an eval set, a candidate whose latest eval run on it passed
less than `ai.planners.menu_min_pass_rate` (0.5) of its questions is dropped from that tool's menu, so
a quantitative planner that does badly on a tool's own questions is not offered there.

## 12. The eval sets

Three eval sets of quantitative questions with known answers ship in `config/evals/`:
`quant_calc_graph` (percent change, CAGR, a spread in basis points, NPV, a weighted average, a
regression slope; `calc_graph` and `estimate_then_compute`), `quant_optimize` (a linear programme with
optimum 36) and `quant_scenario` (a sensitivity table over `qlrisk_price_trades`, whose known answers
are those of the recorded results the CI test replays). Each answer check is a `number` with a
tolerance. They run offline on the mock provider:

```bash
SAJHA_DB_PATH=$P/t45.db SAJHA_CACHE_DIR=$P/cache .venv/bin/python -m sajha.quality eval quant_calc_graph quant_optimize --no-save
```

```text
quant_calc_graph · mock/mock-planner · calc_graph
  PASS pct-change: tools=- steps=0 tokens=4054 111 ms
  PASS cagr: tools=- steps=0 tokens=3611 1 ms
  PASS bp-spread: tools=- steps=0 tokens=3291 1 ms
  PASS npv: tools=- steps=0 tokens=4124 1 ms
  PASS weighted-average: tools=- steps=0 tokens=1821 1 ms
  PASS regression-slope: tools=- steps=0 tokens=1946 1 ms
  pass 6/6 (100%) · tool selection 100% · answers 100% · mean steps 0.0 · tokens 18847 · cost $0.0000 · p95 111 ms

quant_calc_graph · mock/mock-planner · estimate_then_compute
  ... (6/6, shortened)

quant_optimize · mock/mock-planner · optimize
  PASS product-mix: tools=- steps=0 tokens=4058 4 ms
  pass 1/1 (100%) · tool selection 100% · answers 100% · mean steps 0.0 · tokens 4058 · cost $0.0000 · p95 4 ms
```

Against a real model, add `--model <alias or provider/model>` and compare planners with
`--planner`. In CI, `tests/ai/test_quant_evals.py` runs the same sets with scripted replies and
recorded tool results, including wrong graphs, wrong units, a wrong grid and an invalid formulation,
and checks that each is refused and re-planned, and that a figure the model computed itself is revised
away.

## Summary

- A quantity carries a unit, an as-of date, a source and a lineage; the workspace is on the Ask result
- `calc_graph` and `estimate_then_compute` compute; the model names figures and operations and
  describes the result
- `scenario` tables a grid of tool calls; `reconcile` compares one figure across sources; both
  summaries are on the Ask result and in the audit entry
- `data_analyst` runs one read-only `SELECT` over this run's loaded results; `optimize` solves and
  checks feasibility; `code_act` runs sandboxed code only for the roles in `ai.quant.code_act.roles`
- `numbers_check` checks any planner's figures; `router` and `auto` choose the quantitative planners;
  the `quant_*` eval sets measure them

## Next

- The design, every setting and the limits: [Quantitative Planners](../architecture/Quantitative%20Planners.md)
- Writing a planner of your own: [Tutorial 27: Write a Planner](TUTORIAL_27_write_a_planner.md)
- [Tutorial 46: PostgreSQL, Several Workers and the Load Harness](TUTORIAL_46_scaling_postgresql.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
