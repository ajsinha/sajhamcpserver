# SAJHA MCP Server — Business Intelligence

> **Status: planned, not built.** Wave 8, phase 8.4 (release 8.11.0) of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports);
> Roadmap items L40 to L44. Until it ships, nothing below exists in the code; the parts it builds
> on (DuckDB, the OLAP semantic layer, SQL select, data connectors, workflows, MCP Apps) do, and
> their own guides describe them.

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
new package (sajha/bi/, planned) that **reuses** the OLAP engines and the connector engine as
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

### 3.3 Governance

- **Who may query:** tool RBAC on `bi_*` tools, then the metric's `roles`, then the connector's own
  rules. A metric the caller may not query is absent from `bi_list_metrics`.
- **Policy:** the policy engine sees `bi_query_metric` with its arguments, so rules may constrain
  `metric`, `by` or `period` ([Policy and Audit](Policy%20and%20Audit.md)).
- **Audit:** the tool call is audited as every call is; the compiled SQL is recorded in the
  connector's query record when the source is a connector.
- **Residency:** the result carries the source's data classes ([SAJHA Net](SAJHA%20Net.md)).

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
| `bi_chart` | `data` (rows, or a `bi_*` call to make), `kind` (`line`, `bar`, `area`, `scatter`, `heatmap`, `waterfall`, `pareto`), `x`, `y`, `series?`, `title?` | A chart spec (a small Vega-Lite subset) in `structuredContent`, an SVG, and an MCP Apps view (section 5) |
| `bi_load_tool_result` | `tool`, `arguments`, `rows_path` (JSONPath to the rows), `table`, `ttl_minutes?` | Calls the tool as the caller and loads the rows into a private DuckDB table (section 6) |
| `bi_profile` | `dataset` (catalogue name) or `table`, `columns?` | Per column: type, nulls, distinct count, min, max, mean, percentiles, top values, pattern classes |
| `bi_check_quality` | `suite` (a check suite name) | Each check's pass or fail, the observed value and the threshold |
| `bi_list_datasets` | `search?`, `source?` | The dataset catalogue (section 8) |
| `bi_describe_dataset` | `dataset` | Columns, owner, source, freshness, quality status, metrics and dashboards that use it |
| `bi_dashboard_list` / `bi_dashboard_run` | `dashboard`, `parameters?` | Saved dashboards (section 7); a run returns every tile's data and chart |

The analysis tools are thin: each compiles one or two metric queries (section 3.2) and does the
arithmetic in Python on the bounded result (row limits apply), reusing `sajha/olap/window_engine.py`,
`cohort_engine.py` and `stats_engine.py`. Forecasting and anomaly detection use numpy (already
installed with yfinance and OpenBB) and no new required dependency.

---

## 5. Charts and MCP Apps

`bi_chart` returns three things, so every client gets something useful:

1. a chart spec in `structuredContent` (a documented subset of Vega-Lite: mark, encodings, title,
   axis formats) that a capable client may render itself;
2. an SVG rendered server-side by a small SAJHA renderer (no browser), which reports reuse;
3. `_meta.ui` naming a bundled view (a new file beside `sajha/core/mcp_app_views/loan_amortization.html`)
   that draws the spec in the host's iframe and follows its theme.

A view must be self-contained with no network access
([MCP Apps and Headers Guide](../protocol/MCP%20Apps%20and%20Headers%20Guide.md#writing-a-view)) and at
most 2 MB, so the view carries its own small SVG renderer rather than the Vega libraries.
PNG (for PPTX and XLSX in [Reports](Reports.md)) is rasterised by headless Chromium when it is
installed; otherwise those formats embed nothing and say so.

---

## 6. Blending tool results with internal data

`bi_load_tool_result` turns any tool's output (FRED series, a World Bank indicator, an FMP
statement, a qlrisk result) into a DuckDB table the caller can join with internal data. The loader
itself is built earlier, in phase 8.2, for the `data_analyst` planner
([Quantitative Planners](Quantitative%20Planners.md) §3.4); this phase exposes it as a tool, and the
rules below are the loader's:

- the inner call runs **as the caller** through `execute_with_tracking` (RBAC, policy, cache,
  audit), exactly as Ask SAJHA's inner calls do;
- rows are taken at `rows_path`; columns are typed from the tool's `outputSchema` when it has one,
  else inferred;
- the table lives in a **per-user scratch database** (one DuckDB file per user under a
  `bi.scratch_dir`, planned), never shared, dropped after `ttl_minutes` (default 60, capped by
  `bi.scratch_max_minutes`), bounded by `bi.scratch_max_rows` and `bi.scratch_max_mb`;
- it records its provenance (tool, tool version, arguments, time) for [Reports](Reports.md)'
  provenance appendix, and the source tool's data classes;
- a metric with `source: {loaded: true}` and `bi_query_metric` with a `table` override can then
  query it; `duckdb_query` cannot see scratch tables (they are not in the shared DuckDB).

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

## 9. Configuration (planned keys)

`bi.enabled` (default `false`: no `bi_*` tool loads), `bi.metrics_dir`, `bi.dashboards_dir`,
`bi.checks_dir`, `bi.scratch_dir`, `bi.scratch_max_minutes`, `bi.scratch_max_rows`,
`bi.scratch_max_mb`, `bi.max_rows` (cap on any compiled query, below the connector's own),
`bi.dashboard_concurrency`. They go into the
[Configuration Reference](../getting-started/Configuration%20Reference.md) when built.

---

## 10. Build order and tests

1. Metric definitions, loader and checks; the compiler; `bi_list_metrics`, `bi_describe_metric`,
   `bi_query_metric` on DuckDB and OLAP sources, then connector sources. Tests: compilation
   never interpolates a caller value; a metric cannot read a table its connector denies; masking
   applies; `roles` hide a metric.
2. Analysis tools (`bi_compare`, `bi_top_n`, `bi_crosstab`, `bi_cohort_retention`), then
   `bi_explain_change`, `bi_anomalies`, `bi_forecast`, each with golden results on the OLAP sample
   data.
3. `bi_chart` (spec, SVG, view) and `bi_load_tool_result` (scratch isolation per user, TTL,
   provenance).
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
- Contribution analysis is exact for additive metrics (sum, count) and approximate (rate and mix
  effects) for ratios; distinct counts are not additive and are explained by member, not summed.
- Forecasts are statistical baselines for planning, not models of causes.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
