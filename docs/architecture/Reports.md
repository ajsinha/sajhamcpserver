# SAJHA MCP Server — Reports

> **Status: built in 8.11.0 as far as the owner wanted it; the rest is descoped** (wave 8, phase 8.5
> of the [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports)).
> Built (`sajha/reports/`): definitions, the loader, the run engine, report data and history, the
> tools `report_list`, `report_describe`, `report_run`, `report_history`, `report_render`,
> `report_compare`, `report_narrate` and the generated `report_<name>` tools, every format of §4
> (charts as inline SVG; no PNG), narration under the numbers check (§5), classification marking and
> the provenance appendix, the report library page (§9) and two flagship definitions (§10).
> **Descoped by the owner (2026-10-11)**, because an MCP server gives models governed tools and is
> not a reporting product: delivery and `report_deliver` (§6), scheduling from the definition (§7),
> the Studio Report creator (§9), the other flagship reports (§10) and PNG charts. They are not
> planned ([Roadmap §5](Roadmap.md#5-decisions-needed)). A [workflow](Workflows.md) can call
> `report_run` on a schedule. It builds on [Business Intelligence](Business%20Intelligence.md)
> (metrics, charts), [Policy and Audit](Policy%20and%20Audit.md) (audit) and the intelligence layer
> ([LLM Tools](LLM%20Tools.md)).

This document owns one topic: **reports**. A report is a governed, repeatable document built from
tool calls and metric queries. It is rendered to a file format, can be narrated by a model under a
numbers check. Terms are in the [Glossary](../../GLOSSARY.md).

Do not confuse this with the existing **Reports** console page (`/reports`). That page is a usage
dashboard showing tool calls by tool and user over 24 hours, 7 days and 30 days
(`sajha/routes/reporting_routes.py`). Section 9 records how the two are named apart.

---

## 1. Shape

```
 config/reports/<name>.yaml (report definition: parameters, sections, formats, governance)
        │ load + validate (hot reload, storage backend)
        ▼
 report_<name> tool (generated, tool folder "reports")      report_run(name, parameters)
        │                                                          │
        └───────────────────────────┬──────────────────────────────┘
                                    ▼
   run (as the caller)  ── each section: tool call │ metric tile │ sub-report
                                    │                   → table │ chart │ KPIs │ text
                                    ▼
   report data (JSON: every value, its source, tool version, as-of)  ──►  report_narrate (optional; numbers check)
                                    │
                                    ▼
   render: HTML │ PDF │ XLSX │ PPTX │ DOCX │ Markdown  (+ classification marking, provenance appendix)
                                    │
                                    ▼
   history (run record, files in the storage backend, audit events)
```

---

## 2. The report definition

Each report is one YAML file in a reports directory. The default path is
`config/reports/<name>.yaml`, set by a `reports.dir` key. Files are read through the storage
backend and hot-reloaded.

```yaml
name: daily_risk                     # the tool is report_daily_risk; never contains __
title: Daily risk report
description: VaR, expected shortfall, stress results and limit usage for the trading book.
owner: risk-reporting                # who maintains it; shown, recorded with each run
parameters:                          # JSON Schema properties: the report tool's inputSchema
  as_of: {type: string, format: date, description: "Business date (YYYY-MM-DD)"}
  book:  {type: string, default: TRADING}
sections:
  - id: headline
    kind: kpis                       # kpis | table | chart | text | metric | report
    title: Headline
    call: {tool: qlrisk_value_at_risk, arguments: {portfolio: "$params.book"}}
    values:                          # JSONPath into the call's result; one KPI each
      - {label: "VaR 99% 1d", path: $.var, format: currency}
      - {label: "ES 97.5%", path: $.expected_shortfall, format: currency}
  - id: stress
    kind: table
    call: {tool: qlrisk_stress_test, arguments: {portfolio: "$params.book"}}
    rows: $.scenarios[*]
    columns: [scenario, pnl, pnl_pct]
  - id: limits
    kind: table
    call: {tool: qlrisk_check_limits, arguments: {portfolio: "$params.book"}}
    rows: $.limits[*]
    highlight: {column: utilisation_pct, above: 90}
  - id: revenue
    kind: metric                     # a BI tile: one bi_* call plus a visual
    tile: {tool: bi_compare, arguments: {metric: net_revenue, period: MTD, against: same_period_last_year}, visual: bar}
  - id: commentary
    kind: text
    narrate: {sections: [headline, stress, limits], length: short}   # report_narrate (section 5)
formats: [pdf, xlsx]
classification: confidential         # public | internal | confidential | restricted
```

The arguments shown for the qlrisk tools are illustrative. A definition uses whatever each tool's
`inputSchema` declares.

**Load-time checks.** A refused file raises a warning notice that names it. The loader checks:

- the name rule;
- every `call` names a tool that exists. A missing tool is only a warning: the section renders
  "unavailable" and the report still runs;
- argument references (`$params.x`, `$sections.<id>.<path>`) resolve to declared parameters or
  to earlier sections;
- JSONPaths parse (`sajha/quality/jsonpath.py`);
- formats and recipient kinds are known;
- a sub-report (`kind: report`) does not recurse.

**As built (8.11.0).** `sajha/reports/model.py` parses a definition; `sajha/reports/store.py` loads
`*.yaml`, `*.yml` and `*.json` directly under `reports.dir` (through the storage backend, or from the
local disk when the path is absolute) and rescans every `reports.reload_seconds`.

- **More keys.** `enabled` (default `true`; a disabled report has no tool and does not run), `tags`,
  `roles` (only callers with one of them, or administrators, may run it) and `required` (a list of
  parameter names; parameters are otherwise optional). A parameter's `default` may be `$run.date`
  or `$run.year`. `formats` defaults to `[markdown, html]`; Markdown is always made.
- **References.** Whole-string argument values only: `$params.<name>`,
  `$sections.<id>.<jsonpath>` (an earlier section's result) and `$run.date`, `$run.year`,
  `$run.time`. A `text` section may write `${params.<name>}` inside its text.
- **Sections.** A table's `columns` are keys or `{key, label, path, format, decimals, currency}`,
  where `path` is a JSONPath into the row; `key` names the column `report_compare` matches rows on
  (default the first); `limit` caps the rows. A `chart` is a table plus `x`, `y` (one column or a
  list) and `type` (`bar` or `line`). A `metric` section's `tile` is any tool call (normally a
  `bi_*` tool): `values` or `rows` present it, otherwise its top-level numbers become KPIs and its
  first list of rows a table; `visual: bar|line` adds a chart. Value formats: `number`, `integer`,
  `percent` (already in percent), `ratio` (a fraction shown as percent), `currency`, `bps`, `date`,
  `text`.
- **Names.** Lowercase letters, digits and `_`, starting with a letter, at most 48 characters, never
  `__`, never a reserved name (§3). The parameter names `formats` and `deliver` are reserved. A
  sub-report may not have sub-reports of its own (one level), nor be the report itself.
- **`recipients` and `schedule` are refused.** These keys of the original design name features that
  were descoped (§6, §7); a definition that has either is refused with a message saying so and to
  use a workflow to run `report_run` on a schedule.
- **Notices.** A refused file raises `reports.definition:<file>`; two files naming one report raise
  `reports.duplicate:<report>` and neither loads; a report calling tools the server lacks raises the
  info notice `reports.missing_tools:<report>` ([System Notices](System%20Notices.md)).

---

## 3. Tools

All report tools are in the tool folder `reports`, so they share its domain description. They are
written as generated tool configs, in the same way data connectors write theirs.

| Tool | Arguments | Returns / does | Annotations |
|---|---|---|---|
| `report_<name>` (one per definition) | the definition's parameters, `formats?` | Runs the report as the caller; returns the report data, links to the rendered files, the run id | read-only |
| `report_list` | `search?`, `tag?` | Reports the caller may run: name, title, owner, parameters, last run | read-only |
| `report_describe` | `report` | The definition, its sources (tools and metrics), last runs | read-only |
| `report_run` | `report`, `parameters`, `formats?` | The same as `report_<name>`, by name | read-only |
| `report_render` | `run_id`, `format` | Renders a past run's data to another format without calling any tool again | read-only |
| `report_compare` | `report`, `run_a`, `run_b` (run ids, or dates for the runs on those dates) | Section-by-section differences: KPIs with their change, and table rows added, removed and changed | read-only |
| `report_history` | `report`, `from?`, `to?`, `status?` | Runs: id, time, who ran it, parameters, status, formats, warnings | read-only |
| `report_narrate` | `run_id`, `sections?`, `length?`, `audience?` | Commentary that passes the numbers check (section 5): `commentary`, `label`, `model`, `revised`, `rejected`, `removed`, `caveats`, `stored_in`; stored in the run's waiting text section, if it has one | not read-only (writes the run record), not destructive |

Some definition names are reserved because they would collide with the fixed tools: `list`,
`describe`, `run`, `render`, `compare`, `deliver`, `history` and `narrate`.

**As built (8.11.0).** The fixed tools ship in `config/tools/reports/` (`sajha/reports/tools.py`).
A definition's `report_<name>` config is generated there by `sajha/reports/service.py` (marked by
`"report": {"name", "definition_hash"}`), synced at start-up and whenever definitions change; only
marked configs are ever rewritten or removed, and a name taken by another tool raises
`reports.name_conflict:<tool>`. `deliver` stays a reserved name and parameter name, but no tool takes
it (delivery was descoped, §6).

- **Who may run.** A caller runs a report when reports are enabled, the definition is enabled, the
  caller has one of its `roles` (if any) and may execute its `report_<name>` tool. `report_list`
  lists exactly those.
- **A run** returns `run_id`, `status` (`succeeded`; `partial` when a section is not permitted,
  unavailable, failed or skipped; `failed` when every tool section failed), the Markdown, `files`,
  `files_unavailable`, the sections (tables cut to 50 rows inline) and `warnings`.
- **Stored runs.** `reports.output_dir/<report>/<run_id>/run.json` holds the report data and
  `report.<ext>` each file; a run id is `<report>-<UTC yyyymmddThhmmssmmm>-<6 hex>`. A run's data
  was fetched with its runner's access, so **only its runner and administrators** see it in
  `report_history`, `report_render` and `report_compare`. Runs older than `reports.history_days`
  are pruned when the report runs again. The shape of the data, for code that reads runs, is in
  `sajha/reports/__init__.py`.
- **Quantities.** Each run stores the figures a narrator may cite (§5): every KPI and numeric cell,
  each KPI's previous value, change and percent change against the previous run with the same
  parameters that the runner may see, and each numeric column's shares (2 to 50 rows, none
  negative) and ranks, each with the text and precision the report displays.

---

## 4. Formats

| Format | How | Dependency |
|---|---|---|
| HTML | Jinja2 templates (already a requirement), with charts as inline SVG from `bi_chart` | none new |
| PDF | The HTML, printed by headless Chromium through Playwright. Today Playwright is used only by the console checks (`scripts/check_mobile.py`) | Playwright and Chromium become an optional runtime dependency (`requires`). Without them, PDF is not offered and an info notice says why |
| XLSX | One sheet per table section, a summary sheet with KPIs, and a provenance sheet | openpyxl, optional (`requires`) |
| PPTX | A title slide, then one slide per section (KPIs as tiles, tables, charts as PNG) | python-pptx (today a dev requirement), optional (`requires`) |
| DOCX | Headings, KPI tables, tables, charts as PNG | python-docx (already a requirement) |
| Markdown | The report as Markdown tables and text; this is what `report_<name>` returns inline to a model | none |

The owner accepted Playwright, openpyxl and python-pptx as optional `requires` (2026-10-11): a
format whose dependency is missing is not offered, and nothing else is affected.

PNG charts are made by rasterising the SVG in headless Chromium. Without Chromium, PPTX and DOCX
show each chart's data table instead and say so. Every format carries the classification marking
(section 8) and ends with the provenance appendix.

**As built (8.11.0).** `sajha/reports/render.py`. Charts are inline SVG in HTML and PDF. PNG
rasterising is not built: XLSX, PPTX and DOCX always show each chart's data table and say so. PPTX
shows at most 14 rows of a table (the XLSX has every row). Whether PDF works is probed once per
process (Playwright importable and its Chromium installed); a definition asking for a format this
server cannot make raises the info notice `reports.format_unavailable:<format>`, and its run records
the reason in `files_unavailable` while the other formats are made.

---

## 5. Narration with a numbers check

As built: `report_narrate`, in `sajha/reports/narrate.py` (its module docstring is the reference;
tests in `tests/test_report_narrate.py`).

- **The narrator.** A model reached through the LLM layer under the alias `reports.narrate_model`
  (empty: `default`). It sees only the selected sections' data and the run's computed comparisons,
  and it has no tools, so it cannot fetch numbers of its own.
- **Which sections.** With no `sections`, the first text section waiting for commentary (its
  definition has `narrate:`) sets the sections, `length` and `audience`, and the commentary is
  stored in it: the section's text, `narration` on the run (model, sections, revised, removed), and
  the run's files rendered again. Without such a section, every other section is narrated and
  nothing is stored. Only the runner and administrators may narrate a run.

The text is then **validated** with the numbers validator of the quantitative workspace
([Quantitative Planners](Quantitative%20Planners.md) §2.4), given the run's data as tool results
and the run's computed comparisons as quantities:

1. **Extract.** Every number in the text is extracted: integers, decimals, percentages, suffixed
   amounts such as `1.2bn` or `350k`, basis points and percentage points.
2. **Match.** Each number must match a value in the run's data or a quantity, at the precision
   written (`1.2bn` matches 1,234,000,000; `about 1,200` does not match 1,234.56) and by magnitude
   (the sign is in the words: "fell 3.2%"). The validator's unit rules apply: a figure with a rate
   unit matches a quantity in that unit; a figure written with `%` matches a value of the data known
   to be in percent (a key such as `pnl_pct`, a `percent` format, a string "4.5%") or any value as a
   fraction (0.045), never a bare 4.5; a figure with no unit matches a value of the data or a
   quantity in its own unit, or in the unit the text names just before it ("in bp: 475"), not in
   every unit the quantity converts to (a 4.75% change is not "475").
   - The quantities are the comparisons the run computed (`quantities` in the run data): each value,
     its previous value against the previous run with the same parameters, the change and percent
     change, each table cell's share of its column total, and ranks. They are data, not arithmetic
     left to the model.
3. **Dates.** Dates and years (ISO, `9 October 2026`, `Oct 9, 2026`, `October 2026`, `2026-10`,
   `9 Oct`, bare years) must be parameters of the run, the run's own date, or appear in its data
   (a section's as-of date included). Ordinals and section numbers are ignored.
4. **Reject.** A text with any unmatched figure or date is **rejected**.
   - The model gets one revision, with the rejected figures named.
   - A figure still unmatched after the revision is replaced by `[unverified figure removed]`,
     and a caveat names each one removed. The run record gets a warning and the audit records
     `report.narrate.rejected`.
   - An invented figure is never delivered.

---

## 6. Delivery

Descoped by the owner (2026-10-11). There is no `report_deliver` and no delivery to email, webhooks,
SharePoint or folders, and a definition may not have `recipients` (§2). A run's files stay under `reports.output_dir`, where the report library page
(§9) and its download route serve them to the runner and administrators. A workflow can call
`report_run` and then any tool that sends what it returns.

---

## 7. Scheduling

Descoped by the owner (2026-10-11): a definition may not have a `schedule` (§2). To run a report on a schedule, write a [workflow](Workflows.md) with a cron trigger and one
`tool` step that calls `report_run` (or `report_<name>`); the workflow's identity is the runner.

---

## 8. Governance

- **Identity.**
  - A run runs as the caller; a run started by a workflow runs as the workflow's identity
    ([Workflows §5](Workflows.md#5-identity-and-security)).
  - Every section's tool call is an ordinary call through `execute_with_tracking`. RBAC, policy,
    per-user credentials and connected accounts therefore apply section by section.
  - A section the runner may not call renders "not permitted"; the report does not fail.
- **Classification and marking.**
  - The effective classification is the higher of the definition's `classification` and the
    highest data class among the sections' results (wave 5's residency data classes).
  - Every page or sheet carries a header and footer marking. At `confidential` and above, PDF and
    HTML also get a diagonal watermark.
  - As built: a section whose tool marks data classes on its results (residency marks,
    `sajha/net/integration/residency.py`) raises the effective classification to at least
    `confidential`; there is no per-class mapping yet.
- **Audit.** `report.run`, `report.render`, `report.download` and `report.narrate.rejected` are
  events in the hash-chained audit, recorded with the run id and the trace id.
- **Provenance appendix.** Every rendered report ends with an appendix that records:
  - the run id, the runner, the time and the parameters;
  - for each section: the tool, its version (`_meta["io.sajha/tool-version"]` when the tool is
    versioned, [Tool Quality §6](Tool%20Quality.md#6-tool-versions-and-canary)), the arguments,
    the as-of time of the data, and the source's attribution line (several open data licences
    require one, [Open Data Tools](Open%20Data%20Tools.md));
  - the narrator's model alias, when narration was used.
- **History.** Run records (definition hash, parameters, status, file locations, deliveries) are
  kept for `reports.history_days`. The files themselves are in `reports.output_dir`.

---

## 9. Console and Studio

- **No Report creator in Studio** (descoped by the owner, 2026-10-11): definitions are YAML files
  under `reports.dir`.
- **The report library page (as built).** `/reports/library` (`sajha/routes/report_library_routes.py`)
  lists the definitions the user may run: enabled, with a matching role when the definition names
  roles, and (for a non-administrator) access to its `report_<name>` tool.
  - Run opens the report's tool on the tool execute page, which builds the parameter form.
  - `/reports/library/{name}` shows the parameters, the sections and the runs the user may see (their
    own; every run for administrators), each with its files.
  - `/api/reports/library/runs/{run_id}/{format}` downloads a file as an attachment (the runner and
    administrators only).
  - Comparing two runs is not on the page; use `report_compare`.
  - **Naming (owner decision, 2026-10-11).** The existing `/reports` page is a usage dashboard; its
    menu entry is "Usage", the library takes the name "Reports" at `/reports/library`, and `/reports`
    keeps working.

---

## 10. Flagship reports

Two definitions ship in `config/reports/`: `desk_calendar` (enabled as the working example; offline:
settlement dates from the business calendars, the market's holidays this year and a bond priced with
`calc_bond_price`) and `central_bank_watch` (off until enabled: BIS policy rates and the US Treasury
yield curve, with changes since the previous run and a narrated commentary section). More flagship
reports were descoped by the owner (2026-10-11); a definition is a YAML file an operator writes (§2).

---

## 11. Configuration

The built keys are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#reports): `reports.enabled`,
`reports.dir`, `reports.output_dir`, `reports.history_days`, `reports.max_sections`,
`reports.max_run_seconds`, `reports.max_table_rows` and `reports.reload_seconds`.
`reports.enabled` defaults to `true`, not `false` as first planned (owner decision, 2026-10-11): a
report gives a caller nothing they could not already call, since every section runs with the
caller's own access. `reports.narrate_model` belongs to narration (§5). The delivery keys of the
original design were descoped with delivery.

---

## 12. Tests

The narration validator's tests (`tests/test_report_narrate.py`) show that an invented number, a
rounded number, a percent of a value not in the data and a date not in the run are each rejected.
The definitions, runs, formats, comparison and the library page have their own `tests/test_report*.py`
files.

---

## 13. Limits of this design

- A report is a snapshot. Re-rendering never re-runs tools, and comparing runs compares what was
  stored.
- The numbers check proves that every figure is in the data. It does not prove that the sentence
  around the figure is right, so narration stays labelled as model-written.
- There is no delivery or scheduling of its own (§6, §7).

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
