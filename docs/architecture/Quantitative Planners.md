# SAJHA MCP Server — Quantitative Planners

> **Status: planned, not built.** Wave 8, phase 8.2 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports)
> (release 8.9.0); Roadmap items L51 to L59. The owner approved it on 2026-10-11 ("add to the
> roadmap and build at the first opportunity"). Until it ships, nothing below exists in the code.
> It builds on the planner engine (`sajha/ai/planners_engine/`, [Planner Reference](Planner%20Reference.md)),
> the [Sandbox](Sandbox.md), DuckDB and the evals of [Tool Quality](Tool%20Quality.md) §5, and each of
> those has its own guide.

This document owns one topic: **planners for questions whose answer is a computed number**, and
the **quantitative workspace** they share: values that carry a unit, an as-of date and a source; a
tested library of operations; and a numbers validator. It also adds two planners that are not
quantitative, `research_writer` and `reconcile`, because they reuse the same parts. Terms are in the
[Glossary](../../GLOSSARY.md).

---

## 1. Why, and what is there today

A model is good at deciding which data a question needs. It is bad at arithmetic, and it is
careless with units. Asked "how much did US CPI rise over the last 12 months, and what was the
10-year yield spread over Bunds in basis points?", a model that has the right tool results can
still divide the wrong way round, mix a percent with a percentage point, or report 0.45 where
45 bp was meant.

What the planner engine has today ([Planner Reference](Planner%20Reference.md)):

- **Bounded graphs of stages.** A planner file is a graph of stages (`act`, `plan`, `execute`,
  `call`, `foreach`, `draft`, `verify`, `planner` and others), every loop bounded by `max_visits`,
  every run bounded by `limits` (section 3.4 there) and the server ceilings
  (`ai.planners.limits.*`, section 11 there).
- **Settings and overlays.** A file's `settings` can be replaced per tool or for the Ask page by an
  overlay (section 2.5 there). One reserved key, `locality`, is accepted by every planner (section
  3.3 there).
- **Extension points in code.** Custom stage types (`register_stage_type` in
  `sajha/ai/planners_engine/stages.py`) and custom verify checks (`register_check` in
  `sajha/ai/planners_engine/checks.py`) become usable in planner files once registered.
- **A numbers check that only looks up.** The verify check `numbers_in_results` (section 9.1
  there) passes a figure in the answer when some tool result contains it. A figure the model
  *computed* (a percent change, a CAGR, a spread) is in no result, so it either fails the check or,
  where the check is not used, goes out unverified.

Nothing tracks units, and nothing computes on the model's behalf.

---

## 2. The quantitative workspace

One new package under `sajha/ai/` (planned), used by every planner in this document and later by
[Reports](Reports.md) §5. It has no model code and calls no tools itself.

### 2.1 Quantities

A **quantity** is a number with what is needed to trust it:

| Field | Meaning |
|---|---|
| `value` | A float, or a table of floats (a column, a grid) |
| `unit` | One of the units in 2.2, with a scale (`USD`, `USD mn`, `percent`, `bp`, `ratio`, `years`) |
| `as_of` | The date or period the value describes, when the source says |
| `source` | Where it came from: a tool call (call id, tool, version, arguments, JSON path), a constant the question stated, or an operation |
| `lineage` | For a computed quantity, the operation and the quantities it was computed from |

Every figure a quantitative planner puts in an answer is a quantity, so every figure can be traced
back to tool calls (its **lineage**). The run record keeps the workspace, and the Ask SAJHA page
shows a figure's lineage when the figure is selected.

### 2.2 Units

- **Kinds:** currency (ISO 4217 code), `percent`, `bp` (basis points), `ratio`, `count`, `index`
  (index points), time (`days`, `years`), and `unitless`.
- **Scale:** `k`, `mn`, `bn`, `tn` on currency and count.
- **Conversions SAJHA makes:** percent ↔ bp ↔ ratio (1% = 100 bp = 0.01); scales of the same
  currency; days ↔ years by a stated day-count basis (default actual/365).
- **Conversions SAJHA never makes on its own:** between currencies (an FX rate has to be a
  quantity from a tool, with its as-of date), and between a level and a rate.
- **Where units come from:** a tool's `outputSchema` (a `x-sajha-unit` keyword on a property,
  planned), else the planner's declaration of the value it reads, which the model writes and SAJHA
  records as declared rather than known.

### 2.3 The operation library

Operations are pure functions with a unit signature and known-answer tests. The model names
operations; it never writes the arithmetic.

| Operation | Inputs | Result unit |
|---|---|---|
| `diff` | a, b (same kind) | the inputs' unit (percent − percent is percentage points, reported as `pp`) |
| `pct_change` | from, to (same unit) | `percent` |
| `ratio` | a, b | `ratio`, or a currency per unit when the units differ |
| `bp_spread` | rate a, rate b (percent or ratio) | `bp` |
| `cagr` | start, end (same unit), years | `percent` |
| `annualise` | a rate or a volatility, its period, the convention (`simple`, `compound`, `sqrt_time`) | `percent` per year |
| `npv` | cash flows (a column), a rate, period length | the cash flows' currency |
| `irr` | cash flows | `percent` |
| `weighted_avg` | values, weights | the values' unit |
| `sum`, `mean`, `median`, `stdev`, `min`, `max` | a column | the column's unit |
| `regression` | y column, x column(s) | slope, intercept, r² (ordinary least squares) |
| `correlation` | two columns | `unitless` |
| `convert` | a quantity, a target unit | the target (only the conversions 2.2 allows) |
| `fx_convert` | an amount, an FX-rate quantity | the rate's quote currency |
| `round` | a quantity, places | unchanged |

A **unit check** runs before each operation. Adding USD to EUR, taking a percent change of a
percent without saying so, or a `cagr` over zero years is refused with a message the planner passes
back to the model. The existing calculator tools in the `calc` folder (`calc_npv`, `calc_irr`,
`calc_percentage_change` and others) stay tools for callers; the library is the planners' own,
tested against the same known answers so the two cannot disagree.

### 2.4 The numbers validator

The validator generalises `numbers_in_results`. A figure in an answer passes when it matches:

1. a number in a tool result (today's rule, Planner Reference §9.1); or
2. a quantity in the run's workspace, at the precision the answer writes it, in the quantity's unit
   or a unit 2.2 converts to (so "45 bp", "0.45%" and "0.0045" all match a `bp_spread` of 45).

It is registered as the verify check `numbers_in_workspace`, so any planner file can use it, and
it is the validator [Reports](Reports.md) §5 uses for narration once reports are built (report
narration adds its own run's computed comparisons as quantities).

### 2.5 The numbers-check setting

Any planner can turn the validator on without changing its file. A second reserved setting, beside
`locality`, is accepted by every planner, declared or not, in a file or an overlay:

```yaml
numbers_check: off | warn | enforce      # default off; ai.planners.numbers_check sets the default
```

- `warn`: after the planner's `answer`, the service runs `numbers_in_workspace` (or
  `numbers_in_results` for a planner with no workspace) and adds a caveat naming each unmatched
  figure.
- `enforce`: the answer gets one revision with the unmatched figures named; a figure still
  unmatched is removed from the answer, with a caveat that says so. An invented figure is never
  delivered.

Because it is a setting, an overlay turns it on for one LLM tool (`llm.planner: {use: react,
settings: {numbers_check: enforce}}`) or for the Ask page (`ai.ask.planner_config.<name>`).

---

## 3. The planners

Each is a planner file in `config/planners/`, with new stage types registered in code where the
stage library has no equivalent. Every tool call goes through the service as today: access, policy,
approvals, budgets and limits apply to each.

### 3.1 `calc_graph`

The model writes a **computation graph** instead of an answer; SAJHA runs it.

```yaml
# what the model returns (a structured reply, validated against the graph schema)
nodes:
  cpi_now:  { tool: fred_cpi, arguments: { limit: 13 }, read: "$.data.observations[0].value", unit: index }
  cpi_then: { tool: fred_cpi, arguments: { limit: 13 }, read: "$.data.observations[12].value", unit: index }
  inflation: { op: pct_change, from: cpi_then, to: cpi_now }
answer_with: [inflation]
```

- **New stage types.** `graph_plan` (one structured model call returning the graph) and `compute`
  (validate, then execute).
- **Validation before anything runs:** the graph is acyclic; at most `ai.quant.max_graph_nodes`
  nodes (default 40); every tool is offered to the run; every operation exists; every read path
  parses; unit checks pass on the declared units. A graph that fails gets one re-plan with the
  errors (a bounded edge, `max_visits: 1`).
- **Execution:** tool nodes run as one parallel step (identical calls run once); reads extract
  quantities; operations run in dependency order with their unit checks; a failed node fails the
  nodes that need it, and the re-plan is told which.
- **Answer:** a `draft` stage writes prose around the quantities named in `answer_with`, then
  `verify` with `numbers_in_workspace`.

### 3.2 `estimate_then_compute`

For questions where a wrong order of magnitude is the likely error (unit slips, per-share versus
total, monthly versus annual).

1. An `estimate` stage (a structured `draft`, no tools) asks for a rough magnitude and unit.
2. `calc_graph` runs as a sub-planner.
3. The check `estimate_consistent` compares the two. When they differ by more than
   `settings.tolerance_factor` (default 10), the graph is re-planned once with both figures named.
   If they still disagree, the computed figure is answered with a caveat giving the estimate. The
   computed figure always wins; the estimate is never the answer.

### 3.3 `scenario`

A grid of shocks, each a tool run, in parallel, collected into a sensitivity table.

- The model, or the tool's settings, defines the grid: risk factors and shock sizes (for example
  `IR.FWD.SOFR.5Y` −50 to +50 bp in 25 bp steps), within `settings.max_points`.
- The existing `foreach` stage runs one tool call per grid point (for example `qlrisk_price_trades`
  with `market_data.shocks`, or `qlrisk_stress_test` with custom scenarios), bounded by
  `ai.planners.limits.max_foreach_items` and `max_parallel`.
- A `tabulate` stage (new) builds the table as a quantity: base value, shocked values, differences
  from base, each with its lineage. The model describes the table; it does not compute it.

### 3.4 `data_analyst`

For questions over many rows, where an answer is a query, not a lookup.

- Tool results are loaded into the caller's private DuckDB scratch database: the **tool-result
  loader**, built in this phase and shared with Business Intelligence, where
  `bi_load_tool_result` exposes it as a tool ([Business Intelligence](Business%20Intelligence.md)
  §6 has the rules: per-user files, time to live, row and size bounds, provenance).
- The model writes SQL against the loaded tables. SAJHA runs only a single read-only `SELECT`
  (the statement is parsed; anything else is refused), against the scratch database only, with a
  row and time limit. A failed query goes back to the model with DuckDB's error, at most
  `settings.max_queries` times.
- Query results are results for the numbers check, and each figure's lineage names the query and
  the loaded tables' source calls.

### 3.5 `code_act`

For the computation the operation library cannot express. The model writes Python; SAJHA runs it in
the existing [Sandbox](Sandbox.md).

- **Role-limited.** Only roles listed in `ai.quant.code_act.roles` (planned; default: none, so
  administrators enable it deliberately) may run a planner that uses it; for anyone else the
  planner is not offered and `auto` does not pick it.
- **Confined.** The sandbox's default backend, network off, no files but its own temporary
  directory, the sandbox's time, memory and output limits (`sandbox.*`). The code receives the
  workspace's quantities and the run's results as JSON on standard input.
- **Typed output.** It must print quantities (value and unit) as JSON; anything else is an error
  returned to the model. Its quantities enter the workspace with the code as their lineage.
- **Audited.** The code, its input digest and its output are in the run record and the audit
  event.

### 3.6 `optimize`

For allocation and sizing questions ("the cheapest mix that meets these limits").

- The model writes a **formulation** in a restricted JSON form: variables with bounds, a linear or
  quadratic objective, linear constraints, at most `settings.max_variables` variables. Coefficients
  are quantities from the workspace or constants the question gives.
- SAJHA solves it with SciPy (`scipy.optimize.linprog`, `milp` or `minimize`). SciPy is an
  optional dependency: without it the planner is not loaded, and an info notice says why.
- A **feasibility check** evaluates every constraint at the solution within tolerance. An
  infeasible or unbounded problem, or a solution that fails the check, is reported as such; a
  solution is never invented.

### 3.7 `research_writer` (not quantitative)

A cited write-up from several sources: an outline (`plan`), one gathering sub-run per section
(`foreach` of `react`), a `draft` with inline call ids, `verify` with
`citations_present: {per: paragraph}`, and one revision. Built from the existing stage library
only.

### 3.8 `reconcile` (not quantitative)

Compares the same figure from two or more sources (FRED against the World Bank, a position system
against a risk report): each source read as a quantity, values aligned on as-of date and unit,
differences beyond `settings.tolerance` listed with both lineages. The answer is the comparison
table; the model explains it.

### 3.9 Choosing them: `router` and `auto`

- **`auto`.** `settings.candidates` gains `calc_graph`, `scenario` and `data_analyst`. Their
  `use_when` sentences are what the classifier reads (Planner Reference §6.6). `code_act` and
  `optimize` are never default candidates: a tool or the Ask page adds them by overlay.
- **`router`.** A new setting, `quant_pattern` (a regular expression for "percent change",
  "CAGR", "basis points", "what if", "sensitivity" and the like), routes to
  `settings.quant_default` (`calc_graph`) before the multi-step check.
- **Eval filtering** (Planner Reference §6.6.1) applies: a quantitative planner whose latest eval
  run on a tool's eval set passed fewer than `ai.planners.menu_min_pass_rate` of its questions is
  dropped from that tool's menu.

---

## 4. Evaluation

Eval sets of quantitative questions with known answers ship in `config/evals/`: percent changes,
CAGRs, spreads in basis points, NPVs, weighted averages, a regression slope, a sensitivity table,
an optimisation with a known optimum. Each question's answer check is a `number` check with a
tolerance (Tool Quality §5).

In CI they run against the mock provider with scripted replies and recorded tool results
(cassettes), so no live service or real model is called. The scripted replies include wrong graphs
and wrong units on purpose, so the tests prove that a unit error is refused and a re-plan happens.
The same sets run against real models on demand to compare planners.

---

## 5. Configuration (planned keys)

| Key | Default | Meaning |
|---|---|---|
| `ai.planners.numbers_check` | `off` | The default of the reserved `numbers_check` setting (2.5) |
| `ai.quant.max_graph_nodes` | 40 | Nodes in one computation graph |
| `ai.quant.max_table_cells` | 10000 | Cells in one table quantity |
| `ai.quant.code_act.roles` | `[]` | Roles that may run `code_act` |
| `ai.quant.day_count` | `act/365` | The basis for days ↔ years |

The tool-result loader's keys are Business Intelligence's (`bi.scratch_dir`, `bi.scratch_max_rows`,
`bi.scratch_max_mb`, `bi.scratch_max_minutes`), because the two share one loader.

---

## 6. Build order and tests

1. **Workspace, units, operation library, validator and the `numbers_check` setting** (L51, L57).
   Known-answer tests for every operation; unit-refusal tests; validator tests against
   `numbers_in_results`' own cases plus unit conversions.
2. **`calc_graph` and `estimate_then_compute`** (L52). Graph validation tests (cycles, unknown
   tools, bad paths, unit errors); path tests on the mock model.
3. **`scenario`** (L53) and **`data_analyst` with the tool-result loader** (L54). Tests that a
   non-`SELECT` statement and another user's table are refused.
4. **`code_act`** (L55) and **`optimize`** (L56). Tests that a role without permission never sees
   `code_act`; infeasible and unbounded problems reported as such.
5. **`research_writer`, `reconcile`** (L58), **router and `auto` candidates, eval sets** (L59).

Each step updates this document from planned to as-built, the Planner Reference (new stage types,
checks and shipped files), the Glossary and the help cards, as every phase does.

---

## 7. Limits of this design

- Units are only as good as their declaration. Until tools declare `x-sajha-unit` in their output
  schemas, a unit read from a result is the model's declaration, recorded as declared.
- The operation library is deliberately small; `code_act` is the escape hatch, and it is
  role-limited.
- The numbers validator proves that a figure was computed from tool results, not that the right
  figure was computed. Lineage lets a person check the method; evals measure it.
- `optimize` handles linear, mixed-integer linear and smooth quadratic problems of modest size, not
  general non-convex optimisation.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
