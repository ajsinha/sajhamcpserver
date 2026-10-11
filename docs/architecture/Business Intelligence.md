# SAJHA MCP Server — Business Intelligence

> **Status: partly built (8.11.0).** Wave 8, phase 8.4 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports);
> Roadmap items L40 to L44. Built: the metrics layer (section 3), the tools `bi_list_metrics`,
> `bi_describe_metric`, `bi_query_metric`, `bi_compare`, `bi_top_n`, `bi_crosstab` and
> `bi_explain_change` (section 4), `bi_chart` and `bi_load_tool_result` (sections 5 and 6), and the
> tool-result loader (built in phase 8.2 for the `data_analyst` planner). Planned: `bi_cohort_retention`,
> `bi_anomalies`, `bi_forecast`, dashboards (section 7) and the catalogue, profiling and data quality
> (section 8). The tools are listed in the
> [Business Intelligence Tool Reference Guide](../tools/analytics/Business%20Intelligence%20Tool%20Reference%20Guide.md); the parts it builds on (DuckDB, the OLAP semantic layer, SQL select, data
> connectors, workflows, MCP Apps) do, and their own guides describe them.

This document owns one topic: **business intelligence as governed tools**. A *metrics layer*
(metric definitions an owner writes once), analysis tools that answer the questions people
actually ask of those metrics (how much, compared with when, why did it change, what next),
charts, blending a tool's output with internal data, profiling and data-quality checks, saved
dashboards and a catalogue of datasets. Terms are in the [Glossary](../../GLOSSARY.md).

---

## 1. Why, and what is there today

SAJHA already reads data four ways, each with a narrow job:

| Existing piece | What it gives | What is missing for BI |
|---|---|---|
| `duckdb_*` tools (`sajha/tools/impl/duckdb_olap_tools_refactored.py`) | SQL over local files in DuckDB | No business definitions: every caller re-invents "revenue" in SQL |
| OLAP semantic layer (`sajha/olap/`, `config/olap/`) and the `olap_*` tools | Datasets, measures and dimensions over DuckDB; pivots; time series with YoY/QoQ/MoM; engines for cohorts, windows, roll-ups and statistics (`sajha/olap/cohort_engine.py`, `window_engine.py`, `rollup_engine.py`, `stats_engine.py`) | DuckDB only; measures are expressions, not owned metrics with a grain and a time column; only pivot and time-series are tools; the engines for cohorts and windows are not exposed |
| `sqlselect_*` tools | Read-only SQL over registered file sources | Same as DuckDB |
| [Data connectors](Data%20Connectors.md) | Governed, read-only SQL on enterprise databases: statement guard, allowlist, masking, per-user credentials | Raw tables, not metrics; no analysis beyond one SELECT |

A model asked "why did revenue drop in Q3?" today writes SQL against a table it has to
discover, with its own idea of revenue, and stops at a number. BI in SAJHA closes that gap
without a new database and without bypassing any guard that exists.

---

## 2. Placement: a new `bi` tool folder

**Decision:** the BI tools live in a new tool folder, `bi` (domain "BI"), and their code in a
new package (`sajha/bi/`: `metrics.py`, `periods.py`, `compiler.py`, `analysis.py`; the metric tools are
`sajha/tools/impl/bi_metric_tools.py`, the folder's domain description `config/tools/bi/domain.txt`) that **reuses** the OLAP engines and the connector engine as
libraries. Neither existing folder is extended:

- `duckdb` and `olap` are *executors over one store* (DuckDB files). BI tools are *metric-centric
  and cross-source*: one metric may be computed on DuckDB, another on a PostgreSQL connector. A
  domain description (Architecture §5, domain descriptions) for `duckdb` would mislead a model
  about tools that query Snowflake.
- The existing `olap_*` and `duckdb_*` tools keep their names, schemas and behaviour (nothing
  breaks); the `bi` description tells a model to prefer `bi_query_metric` for defined metrics and
  to fall back to the `duckdb_*` or `<connector>__query` tools for ad-hoc SQL.
- The OLAP semantic layer stays the definition format for OLAP datasets; a metric may name an OLAP
  dataset as its source (section 3), so nothing is defined twice.

---

## 3. The metrics layer

### 3.1 A metric definition

One YAML file per metric (or a list per file) in a metrics directory, `config/bi/metrics/<name>.yaml`
by default (a `bi.metrics_dir` key), read through the storage backend and hot-reloaded like tool
configs.

```yaml
name: net_revenue                  # lower case, letters, digits, _; unique; never contains __
title: Net revenue
description: Invoiced revenue net of refunds and discounts, in the reporting currency.
owner: finance-analytics           # a user or role; shown in bi_describe_metric and the catalogue
source:                            # exactly one of:
  connector: shop                  #   a data connector id (its guard, allowlist and masking apply)
  table: public.invoice_lines      #   ... and a table the connector allows
  # olap_dataset: customer_olap    #   an OLAP semantic-layer dataset
  # duckdb_table: sales            #   a DuckDB table or view
  # loaded: true                   #   a caller's loaded tool result (section 6), by table name at call time
measure:
  sql: sum(amount - refund_amount - discount)   # an aggregate over source columns, checked at load
  type: sum                        # sum | count | count_distinct | avg | ratio | min | max
  # ratio: {numerator: <metric>, denominator: <metric>}   # a ratio metric is defined by two metrics
time:
  column: invoice_date
  grains: [day, week, month, quarter, year]     # the grains a caller may ask for
  fiscal_year_start: 4             # optional: fiscal periods (YTD, quarters) start in April
dimensions:                        # the only columns a caller may group or filter by
  - {name: region, column: region}
  - {name: product_line, column: product_line}
  - {name: channel, column: sales_channel, values: [web, store, partner]}
filters:                           # always applied (cannot be removed by a caller)
  - "status = 'posted'"
format: {unit: currency, currency: CAD, decimals: 0}
roles: [finance, analyst]          # optional: who may query it (in addition to tool RBAC)
tags: [finance, kpi]
```

**Load-time checks** (a refused file is a warning notice naming the file, as for tools): the name
rule; one source; the measure is one aggregate expression over the source's columns (parsed by
the connector's statement guard machinery, `sajha/connectors/guard.py`, or DuckDB's parser for
DuckDB sources); every column exists in the source's schema catalog; fixed filters are boolean
expressions without subqueries; a ratio names two metrics on the same source and time column.

**As built** (`sajha/bi/metrics.py`; notice id `bi.metric:<file>`, cleared when the file is fixed):

- The expression checks are a token check (the `sajha/connectors/sqltext.py` tokenizer and the
  guard's denied-function list), not a parse: no statement keywords, subqueries, windows, comments,
  parameters, qualified names or denied functions; a measure must contain an aggregate and a fixed
  filter must not. **Columns are checked against the source's catalog on every call**, not when the
  file is read, so a definition naming a dropped column fails then, with the column's name.
- Files are re-read when the listing or a modification time changes, checked on use at most every
  2 seconds.
- A ratio takes its source, time column and fixed filters from its numerator; numerator and
  denominator must share source, time column **and fixed filters**; its dimensions default to those
  both declare alike.
- `fiscal_year_start` shapes `FY<year>` (the fiscal year that ends in that year), `YTD` and `QTD`;
  grains are calendar grains.
- `source: {loaded: true}` is refused as not built yet.
- Three sample metrics ship over the DuckDB sample data: `net_sales`, `order_count` and the ratio
  `average_order_value`.

### 3.2 Compilation to safe SQL

`bi_query_metric(metric, by, filters, grain, period, ...)` never accepts SQL from the caller.
The compiler builds one SELECT from the definition: identifiers come only from the definition
(and are checked against the catalog again at call time), `by` must name declared dimensions,
`filters` are `{dimension, op, value}` with `op` in `eq, ne, in, not_in, gte, lte, between,
contains`, and every value is a bound parameter. `period` takes human forms:
`2025-Q3`, `2025-07`, `2025`, `FY2025`, `YTD`, `QTD`, `MTD`, `last 12 months`, `last 8 quarters`,
or `{from, to}` dates.

The compiled statement then runs **through the source's own path**: a connector source goes
through that connector's engine (statement guard, table allowlist, masking, row/byte/time limits,
read-only session and the caller's per-user credentials when the connector has them,
[Data Connectors §5–§10](Data%20Connectors.md#5-the-statement-guard)); a DuckDB or OLAP source goes
through the OLAP read-only check (`sajha/olap/sql_safety.py`). So a metric can never read what
its connector would refuse; the metric adds a definition, not an access path.

As built (`sajha/bi/compiler.py`): grains compile on DuckDB, PostgreSQL, Redshift, Snowflake,
Databricks and SQLite sources (others answer without a grain); relative periods (`YTD`,
`last 12 months`) end today, and `previous_period` of a to-date period is the same span one unit
earlier. A connector source's compiled text goes through `guard.check`, then the connection's
session, caps, masking and audit (`connector.query`, op `bi_query`, the SQL's SHA-256). A metric
does not need the connection's `tools.query` switch: like a curated view, it is written by an
administrator. Rows are capped by `bi.max_rows` (and the connection's own cap).

### 3.3 Governance

- **Who may query:** tool RBAC on `bi_*` tools, then the metric's `roles`, then the connector's own
  rules. A metric the caller may not query is absent from `bi_list_metrics`.
- **Policy:** the policy engine sees `bi_query_metric` with its arguments, so rules may constrain
  `metric`, `by` or `period` ([Policy and Audit](Policy%20and%20Audit.md)).
- **Audit:** the tool call is audited as every call is; the compiled SQL is recorded in the
  connector's query record when the source is a connector.
- **Residency:** the result carries the source's data classes ([SAJHA Net](SAJHA%20Net.md))
  (not built).
- **As built:** an administrator passes the role check; for a connector source the caller also needs
  access to the connection's `<id>__list_tables`; a hidden metric answers "unknown metric" everywhere.
  The owner (the `owner` user or role, or an administrator) sees fixed filters and roles in
  `bi_describe_metric`. **Masking:** a metric that uses a masked column anywhere (measure, filter,
  time or dimension, any mode) is refused, so a masked value is never grouped, filtered or aggregated.

---

## 4. Tools

All tools are read-only (`readOnlyHint: true`), take inputs in human units (periods as above,
percent where a share is asked for) and return `structuredContent` with an `outputSchema`, a
`as_of` (the source's latest time value) and the compiled query's fingerprint.

| Tool | Arguments | Returns |
|---|---|---|
| `bi_list_metrics` | `tag?`, `search?` | Metrics the caller may query: name, title, owner, unit, grains, dimensions |
| `bi_describe_metric` | `metric` | The definition (without fixed-filter SQL for non-owners), source, freshness, data-quality status, dashboards and reports that use it |
| `bi_query_metric` | `metric`, `by?`, `filters?`, `grain?`, `period?`, `cumulative?` (`ytd`, `qtd`, `mtd`), `rolling?` (`{window, fn}`), `limit?` | A table of values per grain and dimension members |
| `bi_compare` | `metric`, `period`, `against` (`previous_period`, `same_period_last_year`, or a period), `by?` | Value, comparison value, change and percent change per member |
| `bi_top_n` | `metric`, `dimension`, `n`, `period`, `pareto?` | The top members with share and cumulative share; with `pareto`, the members that make up a given share (default 80 percent) |
| `bi_crosstab` | `metric`, `rows`, `columns`, `period`, `totals?`, `normalize?` (`row`, `column`, `total`) | A real two-way table (row and column headers, cells, margins) |
| `bi_cohort_retention` | `metric` (a count or count-distinct metric), `cohort_by` (first activity grain), `periods`, `period?` | A cohort triangle of retained counts and percent retained (OLAP `cohort_engine`) |
| `bi_explain_change` | `metric`, `period`, `against`, `dimensions` (one to three), `top?` | Contribution analysis: each member's share of the change, ranked; for ratio metrics, a rate effect and a mix effect per member; the members that explain most of the change |
| `bi_anomalies` | `metric`, `grain`, `period`, `by?`, `sensitivity?` | Points flagged against a seasonal baseline (robust z-score on the residual), with the expected value and band |
| `bi_forecast` | `metric`, `grain`, `horizon`, `by?`, `method?` (`seasonal_naive`, `holt_winters`, `auto`) | Forecast with an interval from residuals; `auto` chooses by back-test error, which it reports |
| `bi_chart` | `data` (rows; `{tool, arguments, rows_path?}` for a `bi_*` tool, called as the caller; or `{sql}`: one read-only SELECT over the caller's loaded tables), `kind` (`line`, `bar`, `area`, `scatter`, `heatmap`, `waterfall`, `pareto`), `x`, `y`, `series?`, `value?` (heatmap: the column that colours each cell), `title?` | A chart spec (a small Vega-Lite subset) in `structuredContent`, an SVG, and an MCP Apps view (section 5) |
| `bi_load_tool_result` | `tool`, `arguments?`, `rows_path?` (JSONPath or dotted path to the rows), `table?` (default: the tool name), `ttl_minutes?` | Calls the tool as the caller and loads the rows into a private DuckDB table (section 6); the provenance and the first rows |
| `bi_profile` | `dataset` (catalogue name) or `table`, `columns?` | Per column: type, nulls, distinct count, min, max, mean, percentiles, top values, pattern classes |
| `bi_check_quality` | `suite` (a check suite name) | Each check's pass or fail, the observed value and the threshold |
| `bi_list_datasets` | `search?`, `source?` | The dataset catalogue (section 8) |
| `bi_describe_dataset` | `dataset` | Columns, owner, source, freshness, quality status, metrics and dashboards that use it |
| `bi_dashboard_list` / `bi_dashboard_run` | `dashboard`, `parameters?` | Saved dashboards (section 7); a run returns every tile's data and chart |

The analysis tools are thin: each compiles a few metric queries (section 3.2) and does the
arithmetic in Python on the bounded result (row limits apply). As built, the arithmetic is in
`sajha/bi/analysis.py`, not the OLAP engines (`window_engine.py` and `stats_engine.py` build SQL over
OLAP datasets only, so they do not fit connector sources); `cohort_engine.py` remains the plan for
`bi_cohort_retention`. Every metric tool also takes `filters`; `bi_describe_metric` returns `as_of` and
a `status`, with no data-quality status or dashboards until sections 7 and 8 are built. Shares and
Pareto sets are given for additive metrics only; a ratio's mix effect is centred on the old overall
ratio, `(w1 - w0)(r0 - R0)`, so rate and mix effects add up exactly to the change. Forecasting and anomaly detection use numpy (already
installed with yfinance and OpenBB) and no new required dependency.

---

## 5. Charts and MCP Apps

> **Built (8.11.0).** `sajha/tools/impl/bi_chart_tools.py`, the view
> `sajha/core/mcp_app_views/bi_chart.html`; tests `tests/test_bi_chart.py` (golden spec and SVG per
> kind in `tests/fixtures/bi_chart/`, escaping).

`bi_chart` returns three things, so every client gets something useful:

1. a chart spec in `structuredContent` (a documented subset of Vega-Lite: mark, encodings, title,
   axis formats) that a capable client may render itself;
2. an SVG rendered server-side by a small SAJHA renderer (no browser), which reports reuse;
3. `_meta.ui` naming a bundled view (a new file beside `sajha/core/mcp_app_views/loan_amortization.html`)
   that draws the spec in the host's iframe and follows its theme.

A view must be self-contained with no network access
([MCP Apps and Headers Guide](../protocol/MCP%20Apps%20and%20Headers%20Guide.md#writing-a-view)) and at
most 2 MB. The built view does not carry a second renderer: it redraws the server's SVG, copying
only chart elements (`svg`, `g`, `rect`, `path`, `line`, `circle`, `text`, `title`) and geometry
attributes whose values have the shape the renderer writes, setting text with `textContent`, and
colouring the SVG's classes from the host theme; a details table shows `data.values`.

As built:

- **The spec.** `mark` (or a two-part `layer` for `pareto`, with `resolve.scale.y: independent`),
  `encoding` (`x`, `y`, `y2`, `color`, `xOffset`, `tooltip`), `data.values` and `usermeta.kind`. What a
  kind derives is computed into `data.values` (a waterfall's `_start`, `_end` and `_kind`, ending with
  a total bar; a pareto's descending order and `_cumulative_pct`; stacked areas' `_y0` and `_y1`), so
  no Vega-Lite transform is needed. Rows with the same `x` (and series) are summed for `bar`, `area`,
  `waterfall`, `pareto` and `heatmap` (the result counts them in `combined`); rows without `x` or a
  number are `skipped`.
- **Limits.** At most 5000 rows, 12 series and 200 categories; a `pareto` needs values of zero or
  more; `waterfall` and `pareto` take no `series`. A refusal says why.
- **Escaping.** Every text from the data or the title is XML-escaped (characters XML forbids are
  dropped) and placed as element text; attributes hold only numbers, fixed class names and computed
  colours.
- **PNG** (for PPTX and XLSX in [Reports](Reports.md)) is not built in this phase: it is to be
  rasterised by headless Chromium when it is installed; otherwise those formats embed nothing and
  say so.

---

## 6. Blending tool results with internal data

`bi_load_tool_result` turns any tool's output (FRED series, a World Bank indicator, an FMP
statement, a qlrisk result) into a DuckDB table the caller can join with internal data. **The loader
is built** (`sajha/analytics/scratch.py`, phase 8.2, used by the `data_analyst` planner:
[Quantitative Planners](Quantitative%20Planners.md) §3.4, which also describes how rows are found,
named and typed and how a query is guarded); **the tool is built in 8.11.0** (`BILoadToolResultTool` in
`sajha/tools/impl/bi_chart_tools.py`; tests `tests/test_bi_load_tool_result.py`). The rules, with what is built marked:

- the inner call runs **as the caller** through `execute_with_tracking` (RBAC, policy, cache,
  audit), exactly as Ask SAJHA's inner calls do (built: the caller's tool access is checked first, and a
  tool that does not exist and one the caller may not call get the same refusal; then
  `execute_with_tracking` applies policy, so under the shipped sanctions policy a model cannot load
  `sanctions_*` results; in `data_analyst` the calls are the ask's own);
- a caller with no user (anonymous) is refused: scratch databases are per user (built);
- rows are taken at `rows_path` (built, as is finding them without one); columns are typed from the
  tool's `outputSchema` when it has one (planned), else inferred from the values (built);
- the table lives in a **per-user scratch database** (one DuckDB file per user under
  `bi.scratch_dir`), never shared, dropped after `ttl_minutes` (default 60, capped by
  `bi.scratch_max_minutes`), bounded by `bi.scratch_max_rows` (a larger result is refused) and
  `bi.scratch_max_mb` (built: the keys are in the
  [Configuration Reference](../getting-started/Configuration%20Reference.md#bi));
- it records its provenance (call id, tool, tool version, arguments, time loaded and expiry) for
  [Reports](Reports.md)' provenance appendix, and the source tool's data classes (built: the loader
  stores what it is given; the planner and the tool pass call id, tool and
  arguments; the tool also passes the tool's version and its result data classes);
- a metric with `source: {loaded: true}` and `bi_query_metric` with a `table` override can then
  query it (planned); `duckdb_query` cannot see scratch tables (they are not in the shared DuckDB).
  Today the way in is `bi_chart` with `data: {sql}` (the loader's own query: one read-only `SELECT`,
  the caller's file only).

---

## 7. Dashboards

A dashboard is a YAML file in `config/bi/dashboards/<name>.yaml`: a title, parameters (period,
filters) and **tiles**. A tile is one `bi_*` call (usually `bi_query_metric`, `bi_compare` or
`bi_top_n`) plus a visual (`table`, `kpi`, or a `bi_chart` kind). The **tile is the shared unit**:
a [report](Reports.md) section of type `metric` is a tile, so one definition renders live on a
dashboard and in a delivered report.

- `bi_dashboard_run` runs every tile as the caller (tiles are independent and run in parallel,
  bounded by `bi.dashboard_concurrency`) and returns data and charts.
- A console page (a BI page under the Tools menu, planned) renders dashboards, the metrics list and
  the dataset catalogue, with the page help that every console page has
  ([Architecture §10](Architecture.md#10-web-ui)).

---

## 8. Dataset catalogue, profiling and data quality

**Catalogue.** One list of everything a metric can stand on: OLAP datasets, DuckDB tables and
views, each data connector's allowed tables and curated views (from its schema catalog), and the
caller's loaded tool results. Each entry shows owner (from the metric or connector record),
freshness (the latest value of a declared time column, measured by a cheap `max()` query, cached),
quality status (the last check suite run) and the metrics and dashboards that use it. Visibility
follows the source: a connector's tables appear only to callers who may call its tools.

**Check suites.** A YAML file in `config/bi/checks/<suite>.yaml` lists checks on a dataset:
`not_null`, `unique`, `accepted_values`, `range`, `freshness` (max age), `row_count` (min, or
change versus the last run in percent), `referential` (values exist in another dataset), and
`metric_bounds` (a metric's value within a band). `bi_check_quality` runs a suite and records the
result.

**Scheduling and alerts.** Suites are scheduled as [Workflows](Workflows.md): a workflow with a
cron trigger and one `tool` step calling `bi_check_quality`; a failing suite raises a system
notice (source `bi`, id `bi.quality:<suite>`, [System Notices](System%20Notices.md)) and, when the
workflow says so, an alert through the existing alert channels (log, webhook, email,
[Observability](Observability.md)). No second scheduler is built.

---

## 9. Configuration

Built: `bi.metrics_dir` and `bi.max_rows` (cap on any compiled query, below the connector's own), in
the [Configuration Reference](../getting-started/Configuration%20Reference.md#bi). There is **no
`bi.enabled` switch** (decided for 8.11.0): the `bi_*` tools ship enabled, each by its own config's
`enabled`, so the sample metrics work out of the box; disable a tool as any other. Planned:
`bi.dashboards_dir`, `bi.checks_dir`, `bi.dashboard_concurrency`. The loader's
keys (`bi.scratch_dir`, `bi.scratch_max_minutes`, `bi.scratch_max_rows`, `bi.scratch_max_mb`) are
built and are there already.

---

## 10. Build order and tests

1. Metric definitions, loader and checks; the compiler; `bi_list_metrics`, `bi_describe_metric`,
   `bi_query_metric` on DuckDB and OLAP sources, then connector sources. Tests: compilation
   never interpolates a caller value; a metric cannot read a table its connector denies; masking
   applies; `roles` hide a metric.
2. Analysis tools (`bi_compare`, `bi_top_n`, `bi_crosstab`, `bi_cohort_retention`), then
   `bi_explain_change`, `bi_anomalies`, `bi_forecast`, each with golden results on the OLAP sample
   data. Steps 1 and 2 are built in 8.11.0 except `bi_cohort_retention`, `bi_anomalies` and
   `bi_forecast` (tests: `tests/test_bi_metrics.py`, golden results on the DuckDB sample data).
3. `bi_chart` (spec, SVG, view) and `bi_load_tool_result` (scratch isolation per user, TTL,
   provenance) (built in 8.11.0).
4. Catalogue, profiling, check suites and their workflow template; dashboards and the BI page
   (mobile check in all four themes).
5. This guide becomes as-built; a tutorial ("define a metric and ask why it changed"); glossary and
   help cards.

---

## 11. Limits of this design

- Metrics are computed by the source at query time; there is no materialisation or cache beyond
  the tool result cache (`cache_ttl`).
- A metric reads one source; cross-source joins happen only through loaded tool results in the
  caller's scratch database.
- Contribution analysis is exact for additive metrics (sum, count) and a decomposition (rate and mix
  effects that add up to the change of the overall ratio) for ratios; distinct counts are not additive and are explained by member, not summed.
- Forecasts are statistical baselines for planning, not models of causes.
- A ratio's numerator and denominator share their fixed filters.
- Rolling windows count rows, not calendar periods: a period with no data is not a row.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
