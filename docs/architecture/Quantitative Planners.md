# SAJHA MCP Server — Quantitative Planners

> **Status: built (8.9.0).** Wave 8, phase 8.2 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports).
> Every section describes the code, except where it says *planned*: showing a figure's lineage on
> the Ask SAJHA page (2.1) and the `x-sajha-unit` keyword (2.2), both Roadmap L60.
> It builds on the planner engine (`sajha/ai/planners_engine/`, [Planner Reference](Planner%20Reference.md)),
> the [Sandbox](Sandbox.md), DuckDB and the evals of [Tool Quality](Tool%20Quality.md) §5, and each of
> those has its own guide. A walk-through is
> [Tutorial 45](../tutorials/TUTORIAL_45_quantitative_planners.md).

This document owns one topic: **planners for questions whose answer is a computed number**, and
the **quantitative workspace** they share: values that carry a unit, an as-of date and a source; a
tested library of operations; and a numbers validator. It also adds two planners that are not
quantitative, `research_writer` and `reconcile`, because they reuse the same parts. Terms are in the
[Glossary](../../GLOSSARY.md).

---

## 1. Why

A model is good at deciding which data a question needs. It is bad at arithmetic, and it is
careless with units. Asked "how much did US CPI rise over the last 12 months, and what was the
10-year yield spread over Bunds in basis points?", a model that has the right tool results can
still divide the wrong way round, mix a percent with a percentage point, or report 0.45 where
45 bp was meant.

What the planner engine had before this design ([Planner Reference](Planner%20Reference.md)):

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

Nothing tracked units, and nothing computed on the model's behalf. The rest of this document is
what was added.

---

## 2. The quantitative workspace (as built)

The package `sajha/ai/quant/`, used by every planner in this document and later by
[Reports](Reports.md) §5. It has no model code and calls no tools. Its module docstring
(`sajha/ai/quant/__init__.py`) is the API reference; the tests are `tests/ai/test_quant.py` and
`tests/ai/test_numbers_check.py`.

### 2.1 Quantities

A **quantity** (`Quantity`) is a number with what is needed to trust it:

| Field | Meaning |
|---|---|
| `value` | A float, a column (a list of floats) or a grid (a list of equal-length lists), at most `ai.quant.max_table_cells` cells; anything that is not a finite number is refused |
| `unit` | One of the units in 2.2, with a scale where the kind has one (`USD`, `USD mn`, `percent`, `bp`, `ratio`, `years`) |
| `as_of` | The date or period the value describes, when the source says |
| `source` | Where it came from: a tool call (`kind: tool`, with call id, tool, version, arguments, JSON path and `unit_from`), a constant the question stated (`kind: constant`), or an operation (`kind: operation`) |
| `lineage` | For a computed quantity: the operation, its inputs (workspace names, or the literal values) and its arguments |
| `name` | Its name in the workspace |

A run's **workspace** (`Workspace`) holds its named quantities. It lives in the run's state
(`workspace_of(state)`), so a sub-run shares its parent's. Operations run through it by name
(`run("pct_change", "cpi_then", "cpi_now", name="inflation")`), so every result's lineage leads
back, through `lineage(name)`, to the tool calls (its **lineage**). When a run ends with a
workspace that is not empty, the ask's result (the run record) carries it as JSON
(`workspace.quantities`, each with its lineage). Showing a figure's lineage on the Ask SAJHA page
when the figure is selected is planned.

### 2.2 Units

- **Kinds:** currency (an ISO 4217 code), `percent`, `pp` (percentage points), `bp` (basis
  points), `ratio`, `count`, `index` (index points), time (`days`, `years`), `unitless`, and a
  unit per unit (`USD/EUR`, `USD/count`). An FX rate is a per unit of two currencies: `USD/EUR`
  is USD per EUR.
- **Scale:** `k`, `mn`, `bn`, `tn` on currency and count (`USD mn`, `count k`).
- **Conversions SAJHA makes:** percent ↔ pp ↔ bp ↔ ratio (1% = 100 bp = 0.01); scales of the
  same currency, and of count; days ↔ years by the day-count basis `ai.quant.day_count`
  (`act/365` by default; `act/360`, `30/360`, `act/365.25`).
- **Conversions SAJHA never makes on its own:** between currencies (an FX rate has to be a
  quantity, used with `fx_convert`), and between a level (currency, count, index) and a rate. Each
  refusal says what to do instead.
- **Where units come from:** `Quantity.from_tool` records `unit_from: schema` when the tool's
  `outputSchema` declared the unit, else `declared` (the planner's, that is the model's,
  declaration). The `x-sajha-unit` keyword that would let an `outputSchema` declare a unit is
  planned.

### 2.3 The operation library

Operations are pure functions in `sajha/ai/quant/ops.py`, each with a unit check and known-answer
tests. The model names operations; it never writes the arithmetic. The live list, with each
operation's signature, is `operations()`.

| Operation | Inputs | Result unit |
|---|---|---|
| `diff` | a, b (same kind; b is converted to a's unit) | the inputs' unit; percent − percent (or bp, or ratio) is `pp` |
| `pp` | rate a, rate b | `pp` |
| `pct_change` | from, to (same kind), `of_rate` | `percent`, as (to − from) / \|from\| |
| `ratio` | a, b | `ratio` when the kinds match; otherwise a per unit (`USD/count`, or an FX rate `USD/EUR`) |
| `bp_spread` | rate a, rate b (percent, pp, bp or ratio) | `bp` |
| `cagr` | start, end (same kind), years (a number, or `days`/`years`) | `percent` |
| `annualise` | a rate or a volatility, its period (a time, or `day`, `week`, `month`, `quarter`, `half`, `year`) or `periods_per_year`, the convention (`simple`, `compound`, `sqrt_time`) | `percent` per year |
| `npv` | cash flows (a column), a rate per year, period length in years (default 1) | the cash flows' unit |
| `irr` | cash flows | `percent` per period |
| `weighted_avg` | values, weights | the values' unit |
| `sum`, `mean`, `median`, `stdev`, `min`, `max` | a column | the column's unit (`stdev` is the sample standard deviation) |
| `regression` | y column, x column or columns | `slope` (or `slope_1`…), `intercept`, `r2` (ordinary least squares) |
| `correlation` | two columns | `unitless` |
| `convert` | a quantity, a target unit | the target (only the conversions 2.2 allows) |
| `fx_convert` | an amount, an FX-rate quantity | the rate's other currency |
| `round` | a quantity, places | unchanged (half away from zero) |

Element-wise operations (`diff`, `pp`, `pct_change`, `ratio`, `bp_spread`) accept two columns of
the same length, or a column and a number. A **unit check** runs before each operation. Adding
USD to EUR, taking a percent change of a percent without `of_rate`, or a `cagr` over zero years is
refused with a `QuantError` (a `UnitError` for a unit refusal) whose message the planner passes back
to the model unchanged. The existing calculator tools in the `calc` folder (`calc_npv`,
`calc_irr`, `calc_percentage_change` and others) stay tools for callers; the library is the
planners' own, and `tests/ai/test_quant.py` runs both on the same inputs: `npv` and `pct_change`
agree with the tools to the places the tools round to, and `irr` to within the calculator's own
stopping tolerance (`calc_irr` stops once the NPV is within 0.01; the library solves to machine
precision).

### 2.4 The numbers validator

The validator generalises `numbers_in_results`. A figure in an answer passes when it matches:

1. a number in a tool result (today's rule, Planner Reference §9.1); or
2. a quantity in the run's workspace, at the precision the answer writes it, in the quantity's unit
   or a unit 2.2 converts to (so "45 bp", "0.45%" and "0.0045" all match a `bp_spread` of 45).

A figure written with a rate unit (`%` or "percent", "bp" or "basis points", "pp" or "percentage
points") matches only a quantity expressed in that unit, so "45%" does not match 45 bp. A figure
with a scale word ("1.5 bn") matches through its value and its mantissa, as in §9.1. The figures
that are checked, and the tolerance, are those of `numbers_in_results`; a run with no workspace is
checked exactly as `numbers_in_results` checks it.

It is registered as the verify check `numbers_in_workspace` (in
`sajha/ai/planners_engine/checks.py`), so any planner file can use it, and it is the validator
[Reports](Reports.md) §5 uses for narration once reports are built (report narration adds its own
run's computed comparisons as quantities).

### 2.5 The numbers-check setting

Any planner can turn the validator on without changing its file. A second reserved setting, beside
`locality`, is accepted by every planner, declared or not, in a file or an overlay:

```yaml
numbers_check: warn      # off | warn | enforce; default ai.planners.numbers_check (off)
```

Another value is refused at load (P011). In YAML a bare `off` reads as false, which is taken as
`off`.

- `warn`: after the planner's `answer`, the service runs `numbers_in_workspace` (which is
  `numbers_in_results` for a run with no workspace) and adds one caveat naming each unmatched
  figure.
- `enforce`: the answer gets one revision with the unmatched figures named (one model call); a
  figure still unmatched is replaced in the answer by `[unverified figure removed]`, with a caveat
  that says how many were removed and names them. An invented figure is never delivered.

The check runs on the final answer, after synthesis, unless the run stopped for a confirmation, a
connection, input or a `fail` stage. The ask's event stream gets a `numbers_check` event (`mode`,
`check`, `unmatched`, `revised`, `removed`).

Because it is a setting, an overlay turns it on for one LLM tool (`llm.planner: {use: react,
settings: {numbers_check: enforce}}`) or for the Ask page (`ai.ask.planner_config.<name>`).

---

## 3. The planners

Each is a planner file in `config/planners/`, with new stage types registered in code where the
stage library has no equivalent ([Planner Reference](Planner%20Reference.md) §13 lists every shipped
planner). Every tool call goes through the service as today: access, policy,
approvals, budgets and limits apply to each.

### 3.1 `calc_graph` (as built)

The model writes a **computation graph** instead of an answer; SAJHA runs it. As built:
`config/planners/calc_graph.yaml`, the stage types `graph_plan` and `compute` (in
`sajha/ai/planners_engine/quant_stages.py`; [Planner Reference](Planner%20Reference.md) §13.18
has their keys and outcomes) and the graph itself in `sajha/ai/quant/graph.py`, which holds no
model code and calls no tools.

```yaml
# what the model returns (a structured reply, schema title sajha.graph_plan)
nodes:
  cpi_now:  { tool: fred_cpi, arguments: { limit: 13 }, read: "$.data.observations[0].value", unit: index }
  cpi_then: { tool: fred_cpi, arguments: { limit: 13 }, read: "$.data.observations[12].value", unit: index }
  inflation: { op: pct_change, from: cpi_then, to: cpi_now }
answer_with: [inflation]
```

- **Nodes.** A node is a **tool read** (`tool`, `arguments`, `read`: a JSONPath into the result,
  `unit`: the declared unit, optional `as_of`), a **constant** the question states (`value`,
  `unit`) or an **operation** (`op`, its arguments by the names of its signature in
  `operations()`, or `args` for positional ones). An argument that names a node (or `node.part`
  for `regression`'s parts) is a reference; anything else is a literal. `answer_with` names the
  nodes that answer the question. There is no gathering loop: the graph's tool reads are the
  planner's only tool calls.
- **Validation before anything runs** (`parse_graph`): node names are identifiers not already in
  the workspace; at most `ai.quant.max_graph_nodes` nodes (default 40; a stage's `max_nodes` can
  only lower it); every tool is offered to the run; every operation exists; every read path parses
  (the JSONPath subset of `sajha/quality/jsonpath.py`, as the tool-result loader uses); the graph
  is acyclic; and every operation runs once on placeholders that carry the declared units, so a unit
  refusal (USD minus EUR, a percent change of a rate) is found before any call. A value-dependent
  refusal (a zero start, too few points) is left to execution. Every error names its node.
- **Re-plan.** A graph that fails validation, or whose `answer_with` nodes could not be computed,
  gets one re-plan (bounded edges, `max_visits: 1`): `graph_plan` sees the previous graph with its
  errors, or with each failed node and why (a node whose input failed says
  `needs <node>, which failed`). A second failure ends the run at `fail`, with the errors as
  caveats. The re-plan's graph replaces the first one's quantities in the workspace.
- **Execution.** The tool reads run as one parallel step through the service (access, policy,
  approvals and budgets apply to each); identical calls (same tool and arguments) run once, and a
  call already made earlier in the run with the same arguments is reused. Reads see each call's
  uncapped output (as `load_results` does) and become `Quantity.from_tool` quantities whose source
  names the call id, tool, arguments, path and `unit_from: declared`. Operations then run in
  dependency order through `Workspace.run` with their unit checks, so each result's lineage leads
  back to the calls. A failed call or read fails its node and every node that needs it; a failed
  node that `answer_with` does not need becomes a caveat.
- **Answer.** The computed quantities go to the model (data, not instructions), and a `draft`
  writes prose around them, citing the calls; `verify` runs `numbers_in_workspace` and
  `no_failed_citations`, with one `revise`. The stream carries a `graph` event per attempt
  (`status` `done`, `invalid` or `failed`, `errors`, `failed`).

### 3.2 `estimate_then_compute` (as built)

For questions where a wrong order of magnitude is the likely error (unit slips, per-share versus
total, monthly versus annual). As built: `config/planners/estimate_then_compute.yaml`, the stage
type `estimate` and the check `estimate_consistent` (both in
`sajha/ai/planners_engine/quant_stages.py`; Planner Reference §13.19).

1. An `estimate` stage (a structured reply, no tools) asks for a rough magnitude and unit
   (`{value, unit, why}`; `value` may be null when no estimate is possible).
2. `calc_graph@1.0.0` runs as a sub-planner.
3. The check `estimate_consistent` converts the computed figure (the graph's first `answer_with`
   quantity, or the check's `quantity`) to the estimate's unit and compares magnitudes. When they
   differ by more than `settings.tolerance_factor` (default 10), or the units do not convert, the
   graph is re-planned once (`calc_graph` again; its `graph_plan` sees the previous graph and both
   figures). If they still disagree, the computed figure is answered with a caveat giving the
   estimate. The computed figure always wins; the estimate is never the answer. No estimate, or no
   scalar figure computed, passes. A final `verify` keeps what is unresolved (the estimate caveat,
   and any figure `numbers_in_workspace` still cannot match) as caveats.

### 3.3 `scenario` (as built)

A grid of shocks, each a tool run, in parallel, collected into a sensitivity table. The planner file
is `config/planners/scenario.yaml` (`grid`, then `points`, a `foreach` of one `grid_call` per point,
then `table`, `draft`, `verify` with `numbers_in_workspace`, one `revise`, `answer`); the stage types
are in `sajha/ai/planners_engine/scenario_stages.py` ([Planner Reference](Planner%20Reference.md)
§13.20 has their keys and outcomes).

- **The grid.** `settings.grid`, when the tool's overlay sets it, defines the grid and the model is
  not asked; otherwise the model replies with one (a structured reply): the `tool` (one offered to
  the run), the base call's `arguments`, `shock_path` (where in the arguments the point's shocks go,
  dotted: `market_data.shocks` for `qlrisk_price_trades`, `custom_scenarios.0.shocks` for
  `qlrisk_stress_test`), `value_path` (a JSONPath to the number tabulated, `$.total_npv`), `unit`,
  optionally `as_of_path`, and up to four `factors`, each a risk-factor key (`factor`) or the shock's
  other fields (`shock`, for curve shapes), its `size_field` (`size_bp`, `size_pct` or `size`, as the
  qlrisk shock shape names them), `shock_type`, and `sizes` or `from`, `to` and `step` (for example
  `IR.FWD.SOFR.5Y` −50 to +50 bp in 25 bp steps). SAJHA expands it into points: the base call
  (`base: false` leaves it out, for a tool with no unshocked call) and one point per combination of
  sizes (a zero size is the base). A grid that does not validate (a tool not offered, a path that
  does not parse, an unknown unit, more points than `settings.max_points`, default 9, including the
  base) goes back to the model with every error (two replies in all), then the run fails with the
  reason; it is never truncated. `max_points` is capped by `ai.planners.limits.max_foreach_items`.
- **The points.** The existing `foreach` stage runs one `grid_call` per point (call id
  `point_<id>`), `settings.concurrency` at a time (default 4, capped by `max_parallel`). Each call
  goes through the service like any other: access, policy, approvals and the run's limits apply, and
  a large grid can reach `max_tool_calls` before it ends.
- **The table.** `tabulate` reads the number at `value_path` from each point's whole result (the
  service keeps uncapped outputs for a planner that uses it) into the run's workspace as a quantity
  read from that call: `<stage>.base`, `<stage>.p1`, ...; then, through the operation library,
  each point's difference from the base (`<stage>.p1.change`, `diff`) and percent change
  (`<stage>.p1.change_pct`, `pct_change`; none for a zero base); then the columns `<stage>.shocked`,
  `<stage>.change` and `<stage>.shock` (the sizes, in bp, percent or the factor's unit) and a table
  quantity `<stage>.table` (value and change per point), each with lineage back to the calls. A
  point whose call failed, or whose result has no single number at the path, is a failed row with
  the reason and a caveat; it gets no quantity and nothing is filled in. When the base fails there
  are no differences. The stage's outcome is `done`, `partial` or `failed` (no value at all).
- **The answer.** The model sees the table as SAJHA wrote it and describes it; it computes nothing.
  `verify` with `numbers_in_workspace` checks every figure against the table's quantities (a figure
  the model computed itself is a finding, revised once, then a caveat). The stream carries
  `scenario_grid` (who defined it, the points) and `scenario_table` (every row) events; the run
  record's `workspace` holds the quantities and their lineage, and its `scenario_tables` holds each
  table (the tool, unit, factors and every row, failed ones with the reason), also in the `ai_ask`
  audit entry (each row's point, value, change, percent change, call id and error), so a caller
  need not rebuild the table from the workspace.

### 3.4 `data_analyst` (as built)

For questions over many rows, where an answer is a query, not a lookup. As built:
`config/planners/data_analyst.yaml`, the stage types `load_results` and `sql`
(`sajha/ai/planners_engine/data_stages.py`) and the **tool-result loader**
(`sajha/analytics/scratch.py`), shared with Business Intelligence, where `bi_load_tool_result`
will expose it as a tool ([Business Intelligence](Business%20Intelligence.md) §6 has the rules:
per-user files, time to live, row and size bounds, provenance).

- **The path.** `gather` (an `act` loop, at most `settings.max_gather` rounds), `load`
  (`load_results`), `query` (`sql`), `draft`, `verify` (`numbers_in_results`,
  `no_failed_citations`), one `revise`, `answer`. When no result holds rows, or the query fails,
  the draft is written from the tool results as they are, with a caveat.
- **Loading.** Every successful tool result of the run is loaded whole: for a planner that uses
  `load_results`, the service keeps each call's uncapped output for the length of the ask (the
  model still sees `ai.ask.max_result_chars`). The rows are the largest list of records within
  three levels of the result, a columnar object (`{col: [...]}`), or a flat object as one row;
  the stage's `rows_path` (tool name to JSONPath) overrides that. Table and column names are
  sanitised to lower-case identifiers (a keyword gets a trailing `_`, a repeat `_2`); types are
  inferred (integers, numbers and numeric text, ISO dates and timestamps; anything else is text,
  nested values as JSON text). Each table keeps its provenance: call id, tool, arguments, time
  loaded and expiry (`settings.ttl_minutes`, capped by `bi.scratch_max_minutes`).
- **The query.** The model sees the loaded tables (columns, types, first rows, source call) and
  replies with `{sql, why}`. SAJHA runs only one read-only `SELECT`: DuckDB's parser must see one
  statement of type SELECT (starting `SELECT`, `WITH` or `FROM`), and its syntax tree may name only
  this run's loaded tables and its own CTEs (no table functions such as `read_csv`, no other
  catalog or schema). It runs on a read-only connection to the caller's scratch file with file
  access disabled and locked (no `ATTACH`, `COPY` or file reads), returns at most
  `settings.max_rows` rows and is stopped after `settings.timeout_s` seconds. A refused or failed
  query goes back to the model with the error (DuckDB's own for a failure), at most
  `settings.max_queries` queries in all.
- **Results and the record.** A successful query is a result of the run (`query_1`, ...), so
  `numbers_in_results` matches figures taken from it; the draft cites the query id and the answer's
  citations name the query's source calls. Every query, failed ones too, is in the run record
  (`queries` on the Ask result and in its audit entry: the SQL, its tables and source calls, also
  when `data_analyst` ran as a sub-run of `auto`), and the stream carries `table_loaded` and `query`
  events.
- **Into the workspace.** Each numeric column of a successful query that is not truncated enters
  the workspace as a quantity `<query id>.<column>` (a number for one row, a column for several;
  `unitless`, since a query result carries no unit), whose lineage names the query (`op: sql`, its
  SQL) and its source calls. So `numbers_in_workspace` and the `numbers_check` setting (2.5) cover
  the query's figures, and a later stage (an `optimize` formulation, a `code_act` program) can use
  them. A column with a non-number, or more cells than `ai.quant.max_table_cells`, is left out; the
  query's record names the quantities it made (`quantities`).
- **Not yet.** Columns are typed from the values, not from the tool's `outputSchema`.

### 3.5 `code_act` (as built)

For the computation the operation library cannot express. The model writes Python; SAJHA runs it in
the existing [Sandbox](Sandbox.md). The planner file is `config/planners/code_act.yaml` (gather with
tools, then a `code_act` stage, then `draft`); the stage type is in `sajha/ai/code_act/`
([Planner Reference](Planner%20Reference.md) §13.17 has its keys and outcomes).

- **Role-limited.** Only callers holding a role listed in `ai.quant.code_act.roles` (default: none,
  so administrators enable it deliberately; being an administrator is not enough) may run a planner
  that uses it, directly or through a sub-planner it always runs. For anyone else the planner is
  left out of `GET /api/ai/planners` (administrators see it marked `permitted: false`), a `classify`
  menu (so `auto`) never offers it, a `planner` stage that reaches it fails with the reason, and a
  direct run stops with `stopped_by: refused` before any model call. The stage checks the role
  again before it runs anything.
- **Confined.** The sandbox's default backend (`sandbox.default_backend`), network off whatever
  `sandbox.defaults` say, no files but its own temporary directory, the sandbox's time, memory,
  process, file-size and output limits (`sandbox.defaults` capped by `sandbox.max`). The code
  receives `{question, quantities, results}` (the workspace's quantities and the run's successful
  results) as JSON on standard input.
- **Typed output.** Standard output must be exactly one JSON object of quantities,
  `{"quantities": {"<name>": {"value": ..., "unit": "..."}}}` (the wrapper may be left out; `as_of`
  is optional). Anything else (other text, a bare number, a unit the workspace does not know, a name
  already in the workspace, a non-zero exit, a timeout) is an error returned to the model, which
  gets `max_attempts` tries in all (default 2). The quantities enter the workspace with the code as
  their lineage (`op: code`, with the code's and the input's digests), and the model sees them to
  draft the answer.
- **Audited.** Every run (each attempt) is recorded with the code, its input digest (SHA-256), its
  output, standard error's tail, the exit code and the backend: in the run record
  (`code_runs` on the ask's result, also in the `ai_ask` audit entry), as a `code_run` event on the
  ask's event stream, and as its own `ai_code_act` audit event.

### 3.6 `optimize` (as built)

For allocation and sizing questions ("the cheapest mix that meets these limits"). The planner file
is `config/planners/optimize.yaml` (gather with tools, then an `optimize` stage, then `draft`); the
package is `sajha/ai/optimize/` (`formulation.py`, `solver.py`, `stage.py`;
[Planner Reference](Planner%20Reference.md) §13.16 has the stage's keys and outcomes).

- The model writes a **formulation** in a restricted JSON form (a structured reply): `sense`
  (`min` or `max`), `variables` (name, `lower` default 0, `upper`, `integer`), an `objective` with
  `linear` terms, optional `quadratic` terms (`{a, b, coef}`: coef × a × b) and a `constant`, and
  linear `constraints` (`terms`, `op` `<=` `>=` `==`, `rhs`), at most `settings.max_variables`
  variables (default 50, never more than 500) and 1000 constraints. Validation names every error
  (an unknown variable, a duplicate, a bound the wrong way round, a coefficient that is not a finite
  number) and the errors go back to the model (`max_attempts`, default 2). A coefficient, bound or
  right-hand side may instead be the name of a single-number quantity in the run's workspace (a
  figure `calc_graph` or `data_analyst` computed earlier in the run; the prompt lists them): it is
  used at its value in its own unit, an unknown name is an error sent back, and the names used are
  recorded (`quantities_used`) and become the inputs of the solution's lineage.
- SAJHA solves it with SciPy: `linprog` (HiGHS) for a linear problem, `milp` for one with integer
  variables, `minimize` (SLSQP, from a feasible point) for a convex quadratic objective (concave
  for `max`). A non-convex quadratic objective, or a quadratic one with integer variables, is
  refused (`unsupported`) rather than answered with a local optimum. SciPy is an optional
  dependency imported only when a problem is solved: without it the planner file is not loaded
  (it is not a load error), the registry lists it under `unavailable` in `GET /api/ai/planners`
  (administrators), and the info notice `planners.unavailable:optimize` says why
  ([System Notices](System%20Notices.md) §4).
- A **feasibility check** evaluates every bound, constraint and integrality requirement at the
  solution within a tolerance (10⁻⁶, relative for large terms). An infeasible or unbounded problem
  (HiGHS's "infeasible or unbounded" is settled with a feasibility problem; a quadratic problem's
  unboundedness is decided exactly, by a recession direction), a solver failure, or a solution that
  fails the check (`check_failed`) is reported as such; a solution is never invented. The stage's
  outcome is `solved`, `infeasible`, `unbounded`, `failed` or `invalid`; for all but `invalid` the
  model drafts from the result as labelled (an `optimization` event carries the status), and an
  optimal solution's values and objective enter the workspace as `<stage>.<variable>` and
  `<stage>.objective`, unitless (a decision variable has no declared unit).

### 3.7 `research_writer` (not quantitative; as built)

A cited write-up from several sources: an outline (`plan`), one gathering sub-run per section
(`foreach` of `react`), a `draft` with inline call ids, `verify` with
`citations_present: {per: paragraph}`, and one revision. Built from the existing stage library
only. As built: `config/planners/research_writer.yaml`. The outline is a `plan` stage whose steps
are the sections (`why` is the heading; at most `settings.max_sections`); `sections` runs
`react@1.0.0` per section (`settings.concurrency` at a time); with no usable outline, an `act` loop
gathers for the whole question instead. The draft cites call ids in square brackets, and a
paragraph with a figure but no citation is a finding; after one revision, findings left become
caveats.

### 3.8 `reconcile` (not quantitative; as built)

Compares the same figure from two or more sources (FRED against the World Bank, a position system
against a risk report). The planner file is `config/planners/reconcile.yaml` (`gather`, an `act`
loop of at most `settings.max_gather` rounds, then `compare`, `draft`, `verify` with
`numbers_in_workspace`, one `revise`, `answer`); the stage type is `reconcile`, in
`sajha/ai/planners_engine/reconcile_stage.py` ([Planner Reference](Planner%20Reference.md) §13.21).

- **Where each source holds it.** The model replies (a structured reply) with the figures to compare,
  each with at least two readings, the first being the reference: a `source` label, a successful
  `call_id` of the run, a JSONPath `path` to the value (or to a list of dated records, with
  `value_field` and `date_field`), the `unit` the source states and its `as_of` or `as_of_path`;
  optionally the unit to compare in and an `align` period. It never gives a value. A reading SAJHA
  cannot read (an unknown call, a path with no number, an unknown unit) goes back to the model with
  the errors (two replies in all).
- **Read and aligned by SAJHA.** Each value is read from the tool's whole result into the workspace
  as a quantity with its lineage (`<stage>.<figure>.<source>`). Readings are aligned on as-of date by
  `settings.align` (`exact`, `day`, `month`, `quarter` or `year`; default `day`): only the periods
  every source has are compared and the rest are listed per source; a missing observation (FRED's
  `.`) is skipped, not zero; two values of one source in one period, or a dated reading against an
  undated one, are not compared. Units are aligned on the comparison unit through the conversions of
  section 2.2 (`USD mn` against `USD bn`, percent against bp). Two currencies are compared only
  through an FX rate read from a tool result (`fx`: call id, path, unit such as `USD/EUR`, applied
  with `fx_convert`); without one the figure is **not comparable**, with the reason, and nothing is
  converted at a guessed rate. A level against a rate is not comparable either.
- **Differences.** For each other source, `diff` and `pct_change` against the reference, in the
  reference's unit (`<stage>.<figure>.<source>.diff`, `.diff_pct`), and with several periods or
  sources a table quantity `<stage>.<figure>.table`. A difference is listed when it is larger than
  `settings.tolerance` (a fraction of the reference value, default 0.005) or `settings.tolerance_abs`
  (in the reference's unit, default 0), whichever is larger; each listed difference carries both
  lineages (call id, tool, path, unit, as-of and the conversions on each side). The outcome is
  `matched`, `breaks`, `not_comparable` (nothing could be compared) or `invalid` (no usable reply);
  all go to the draft, with a caveat for each figure not compared.
- **The answer** is the comparison table as SAJHA wrote it; the model explains it and computes
  nothing, and `numbers_in_workspace` checks its figures. The stream carries a `reconciliation`
  event (each figure's status and reason, and the listed differences); the run record's
  `reconciliations` holds each comparison (figures, rows, the differences beyond the tolerance with
  both lineages, the tolerance and alignment), and the `ai_ask` audit entry a summary of it (each
  figure's status and reason, and the differences).

### 3.9 Choosing them: `router` and `auto` (as built)

- **`auto`** (`config/planners/auto.yaml`, version 1.1.0). `settings.candidates` includes
  `calc_graph`, `scenario` and `data_analyst`; their `use_when` sentences are what the classifier
  reads (Planner Reference §6.6). `code_act` and `optimize` are never default candidates: a tool or
  the Ask page adds them by overlay (and `code_act` only for a permitted role, 3.5). Two changes
  make the computed answers fit `auto`'s checks: its `verify` runs `numbers_in_workspace` (which is
  `numbers_in_results` for a run with no workspace), so a figure the sub-run computed is matched;
  and the candidates in `settings.self_checked` (these three) are not escalated for low confidence,
  because they verify their own figures and a graph of stated figures calls no tool, so the
  confidence score has nothing to rest on. A failed check, or a first try that ran out of steps,
  still escalates them.
- **`router`** (`config/planners/router.yaml`, version 1.1.0). After the configured rules and the
  recipes, a `quant` stage matches `settings.quant_pattern` (a case-insensitive regular expression
  for percent change, CAGR, basis points, what if, sensitivity, spread, NPV, IRR, weighted average,
  annualised, regression, year over year and the like; the file has the full pattern) and routes a
  match to `settings.quant_default` (`calc_graph`), before the multi-step check. So "compare the
  CAGR of ..." goes to `calc_graph`, not `plan_execute`. `use_quant: false` turns the stage off.
- **Eval filtering** (Planner Reference §6.6.1) applies unchanged: a candidate whose latest eval run
  on a tool's eval set passed fewer than `ai.planners.menu_min_pass_rate` of its questions is dropped
  from that tool's menu.

---

## 4. Evaluation (as built)

Eval sets of quantitative questions with known answers ship in `config/evals/` (the format is
[Tool Quality](Tool%20Quality.md) §5); each answer check is a `number` check with a tolerance:

| Set | Planners | Questions |
|---|---|---|
| `quant_calc_graph` | `calc_graph`, `estimate_then_compute` | A percent change, a CAGR, a spread in basis points, an NPV, a weighted average and a regression slope, all from figures the question states |
| `quant_scenario` | `scenario` | A sensitivity table over `qlrisk_price_trades` (needs the qlrisk tools) |
| `quant_optimize` | `optimize` | A linear programme with a known optimum (needs SciPy) |

Each set names `mock/mock-planner` as its model: the mock writes a computation graph for the
`quant_calc_graph` question shapes and solves a linear programme written out in the question, so
`python -m sajha.quality eval quant_calc_graph` passes offline. The known answers of
`quant_scenario` are those of the recorded pricer results in CI; against the live qlrisk server the
figures are the book's own, so compare planners there on the table's shape. With `--model` and
`--planner` the same sets run against real models on demand to compare planners.

In CI (`tests/ai/test_quant_evals.py`) every set runs on the mock provider with no live service or
real model: on mock-planner, and again with scripted replies and recorded tool results (a fake
`qlrisk_price_trades` that returns fixed values for each shock). The scripted replies are wrong on
purpose: an operation that does not exist, a period in USD, a rate declared as a currency, a cycle,
a draft quoting a figure the model computed itself, a grid with an unknown unit and a bad path, and a
formulation naming an unknown variable. Each must be refused and re-planned (or revised) and the
question must still pass; a unit error repeated in the re-plan must end the run `failed`, which the
eval scores as a failure. The same file tests `router`'s `quant_pattern`, `auto`'s candidates and
its eval filtering, and the `scenario_tables` and `reconciliations` of the run record.

---

## 5. Configuration (as built)

The keys, their defaults and their environment variables are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md), which owns them:

| Key | What it governs |
|---|---|
| `ai.planners.numbers_check` | The default of the reserved `numbers_check` setting (2.5) |
| `ai.quant.max_graph_nodes` | Nodes in one computation graph (read by `calc_graph`, 3.1) |
| `ai.quant.max_table_cells` | Cells in one table quantity (2.1) |
| `ai.quant.day_count` | The basis for days ↔ years (2.2) |
| `ai.quant.code_act.roles` | Roles that may run `code_act` (3.5) |

They are read like the other `ai.*` keys (environment, then `config/application.yml`, then the
default); `sajha/ai/quant/settings.py` resolves the `ai.quant` ones.

The tool-result loader's keys are Business Intelligence's (`bi.scratch_dir`, `bi.scratch_max_rows`,
`bi.scratch_max_mb`, `bi.scratch_max_minutes`), because the two share one loader.

---

## 6. Build order and tests (as built)

Phase 8.2 was built in this order, each step with its tests:

1. **Workspace, units, operation library, validator and the `numbers_check` setting.** Known-answer
   tests for every operation; unit-refusal tests; validator tests against `numbers_in_results`' own
   cases plus unit conversions (`tests/ai/test_quant.py`, `tests/ai/test_numbers_check.py`).
2. **`calc_graph` and `estimate_then_compute`.** Graph validation (cycles, unknown tools and
   operations, bad paths, unit errors, the node cap); re-plan, failed-node and estimate paths on the
   mock model (`tests/ai/test_calc_graph.py`).
3. **`scenario`, and `data_analyst` with the tool-result loader.** A non-`SELECT` statement and
   another user's table are refused; a grid is bounded by `max_points` and the `foreach` limits; the
   table's differences carry lineage to both calls; a failed point is reported, not filled in
   (`tests/ai/test_data_planners.py`, `tests/ai/test_scenario_reconcile.py`).
4. **`code_act` and `optimize`.** A role without permission never sees `code_act`; infeasible and
   unbounded problems are reported as such (`tests/ai/test_code_act.py`, `tests/ai/test_optimize.py`).
5. **`research_writer` and `reconcile`** (unit and as-of alignment, the tolerance, refusal across
   currencies without an FX rate, in `tests/ai/test_scenario_reconcile.py`), then **`router` and
   `auto`, and the eval sets** (section 4, `tests/ai/test_quant_evals.py`).

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
