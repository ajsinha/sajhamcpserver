# SAJHA MCP Server — Reports

> **Status: planned, not built.** Wave 8, phase 8.4 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports);
> Roadmap items L45 to L50. Until it ships, nothing below exists in the code. It builds on
> [Business Intelligence](Business%20Intelligence.md) (metrics, tiles, charts),
> [Workflows](Workflows.md) (schedules), [Policy and Audit](Policy%20and%20Audit.md) (approval,
> audit) and the intelligence layer ([LLM Tools](LLM%20Tools.md), `narrate` mode).

This document owns one topic: **reports**. A report is a governed, repeatable document built from
tool calls and metric queries. It is rendered to a file format, can be narrated by a model under a
numbers check, and is delivered to people. Terms are in the [Glossary](../../GLOSSARY.md).

Do not confuse this with the existing **Reports** console page (`/reports`). That page is a usage
dashboard showing tool calls by tool and user over 24 hours, 7 days and 30 days
(`sajha/routes/reporting_routes.py`). Section 9 proposes how to name the two apart.

---

## 1. Shape

```
 config/reports/<name>.yaml (report definition: parameters, sections, formats, recipients, governance)
        │ load + validate (hot reload, storage backend)
        ▼
 report_<name> tool (generated, tool folder "reports")      report_run(name, parameters)
        │                                                          │
        └───────────────────────────┬──────────────────────────────┘
                                    ▼
   run (as the caller; as the owner when scheduled)  ── each section: tool call │ metric tile │ sub-report
                                    │                   → table │ chart │ KPIs │ text
                                    ▼
   report data (JSON: every value, its source, tool version, as-of)  ──►  report_narrate (optional; numbers check)
                                    │
                                    ▼
   render: HTML │ PDF │ XLSX │ PPTX │ DOCX │ Markdown  (+ classification marking, provenance appendix)
                                    │
                                    ▼
   deliver: email │ Teams / Slack webhook │ SharePoint │ folder   (external targets need approval)
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
owner: risk-reporting                # a user; scheduled runs run as this user
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
recipients:
  - {kind: email, to: [risk-committee@bank.example]}
  - {kind: folder, path: reports/daily_risk/}
classification: confidential         # public | internal | confidential | restricted
schedule: {cron: "30 7 * * 1-5", timezone: America/Toronto}   # optional; becomes a workflow (section 7)
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

---

## 3. Tools

All report tools are in the tool folder `reports`, so they share its domain description. They are
written as generated tool configs, in the same way data connectors write theirs.

| Tool | Arguments | Returns / does | Annotations |
|---|---|---|---|
| `report_<name>` (one per definition) | the definition's parameters, `formats?`, `deliver?` (boolean, default false) | Runs the report as the caller; returns the report data, links to the rendered files, the run id | read-only unless `deliver` |
| `report_list` | `search?`, `tag?` | Reports the caller may run: name, title, owner, parameters, schedule, last run | read-only |
| `report_describe` | `report` | The definition, its sources (tools and metrics), schedule, recipients (redacted for non-owners), last runs | read-only |
| `report_run` | `report`, `parameters`, `formats?` | The same as `report_<name>`, by name; never delivers | read-only |
| `report_render` | `run_id`, `format` | Renders a past run's data to another format without calling any tool again | read-only |
| `report_compare` | `report`, `run_a`, `run_b` (run ids, or dates for the runs on those dates) | Section-by-section differences: KPIs with their change, and table rows added, removed and changed | read-only |
| `report_deliver` | `run_id`, `recipients?` (default: the definition's) | Delivers a run's files (section 6); external targets wait for approval | not read-only, not destructive |
| `report_history` | `report`, `from?`, `to?`, `status?` | Runs: id, time, who ran it, parameters, status, formats, deliveries | read-only |
| `report_narrate` | `run_id`, `sections?`, `length?`, `audience?` | Commentary that passes the numbers check (section 5) | read-only |

Some definition names are reserved because they would collide with the fixed tools: `list`,
`describe`, `run`, `render`, `compare`, `deliver`, `history` and `narrate`.

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

PNG charts are made by rasterising the SVG in headless Chromium. Without Chromium, PPTX and DOCX
show each chart's data table instead and say so. Every format carries the classification marking
(section 8) and ends with the provenance appendix.

---

## 5. Narration with a numbers check

`report_narrate` writes commentary over a run's data. It uses an [LLM tool](LLM%20Tools.md) in
`narrate` mode, with a configurable model alias (`reports.narrate_model`). It then **validates**
the text:

1. **Extract.** Every number in the text is extracted: integers, decimals, percentages, currency
   amounts, suffixed amounts such as `1.2bn` or `350k`, and basis points.
2. **Match.** Each number is normalised and must match a value in the run's data. The comparison
   uses the precision the report displays, or the precision written if that is coarser. A match
   can be a value, a change or a percent change, as long as the report itself computed it.
   - To make this possible, the report computes the comparisons a narrator would cite: changes
     versus the previous run, shares and rankings. These are data, not arithmetic left to the
     model.
3. **Dates.** Dates and years must be parameters of the run or appear in the data. Ordinal words
   and section numbers are ignored.
4. **Reject.** A text with any unmatched number is **rejected**.
   - The model gets one retry, with the rejected numbers named.
   - If the retry also fails, the section is left empty with the message "commentary withheld: it
     cited figures not in the report", and the run record gets a warning.
   - An invented figure is never delivered.

The narrator sees only the run's data and has no tools, so it cannot fetch numbers of its own.

---

## 6. Delivery

| Kind | How | Notes |
|---|---|---|
| `email` | SMTP through the same sender the alert rules use (`observability.alerts_email.*`, `sajha/observability/alerts.py`); files are attached or linked | A domain allowlist (`reports.email_internal_domains`) separates internal from external addresses |
| `webhook` (Teams, Slack) | An incoming-webhook URL from the secret store; posts a short summary card with the KPIs and a link. Files are linked, not posted | Outbound requests go through the outbound fetch guard and HTTP proxy settings (`sajha/core/outbound.py`), like every tool fetch |
| `sharepoint` | The `sharepoint_documents` tool's `upload` operation, called as whoever runs the report | Graph's simple-upload size limit applies ([Roadmap L7](Roadmap.md)) |
| `folder` | A path in the storage backend under `reports.output_dir` (local, S3, Azure Blob or GCS) | History keeps every run's files here in any case |

**External delivery needs approval.** These targets count as external:

- an email recipient outside the internal domains;
- any webhook not on `reports.webhook_allowlist`;
- any SharePoint site outside `reports.sharepoint_internal_sites`.

Delivery to an external target creates an approval in the policy engine's approval store (shown on
the Approvals page) and waits for it. The run's other deliveries proceed meanwhile. Policy rules can
add their own conditions on `report_deliver` ([Policy and Audit](Policy%20and%20Audit.md)).

---

## 7. Scheduling

A definition's `schedule` becomes a [workflow](Workflows.md) owned by the report's owner. The
workflow has a cron trigger and one `tool` step that calls `report_<name>` with `deliver: true`.
The workflow engine provides single-fire across workers, durable runs, retries and the run history,
so reports add no scheduler of their own. Removing `schedule` from the definition disables that
workflow.

---

## 8. Governance

- **Identity.**
  - An on-demand run runs as the caller. A scheduled run runs as the owner, using the workflow's
    identity ([Workflows §5](Workflows.md#5-identity-and-security)).
  - Every section's tool call is an ordinary call through `execute_with_tracking`. RBAC, policy,
    per-user credentials and connected accounts therefore apply section by section.
  - A section the runner may not call renders "not permitted"; the report does not fail.
- **Classification and marking.**
  - The effective classification is the higher of the definition's `classification` and the
    highest data class among the sections' results (wave 5's residency data classes).
  - Every page or sheet carries a header and footer marking. At `confidential` and above, PDF and
    HTML also get a diagonal watermark.
- **Audit.** `report.run`, `report.render`, `report.deliver` and `report.narrate.rejected` are
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

- **A Report creator in Studio (planned).**
  - It lets an author pick tools and metrics, map parameters, choose a visual for each section,
    preview with sample parameters, and save a definition.
  - Studio's per-creator permissions and ownership apply, as for every creator
    ([MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md)).
- **A report library page.**
  - It lists the definitions the user may run. From it the user can run a report with parameters,
    see history, compare two runs and download files.
  - **Naming (decision needed).** The existing `/reports` page is a usage dashboard. The proposal:
    rename that page's menu entry to "Usage", give the new page the name "Reports" under a new
    path, and keep `/reports` working.

---

## 10. Flagship reports

These ship as definitions, off until enabled. Each one is also a test of the design.

| Report | Sections from | Notes |
|---|---|---|
| Daily risk report | qlrisk VaR, ES, stress, limits, P&L explain | Needs qlrisk installed |
| Counterparty exposure | qlrisk SA-CCR and CCR exposure; GLEIF direct and ultimate parents; sanctions screening | Aggregates exposure up the LEI hierarchy |
| Regulatory capital summary | qlrisk Basel and FRTB capital, SA-CCR | |
| Morning market brief | FRED, ECB, the US Treasury yield curve, FX, equity indices, today's holidays | Narrated |
| Company tearsheet | EDGAR facts and filings; FMP profile, ratios and prices | Parameter: ticker |
| Country macro profile | World Bank, IMF, BIS, OECD or Eurostat | Parameter: country |
| Central bank watch | BIS policy rates, ECB, Bank of Canada, Bank of Japan, FRED | Shows changes since the previous run |
| BI metric pack | A set of `bi_compare`, `bi_explain_change` and `bi_anomalies` tiles | Parameter: tag |
| Data quality report | `bi_check_quality` suites | |
| SAJHA platform report | Usage and cost, tool health and probes, notices, an audit summary | Administrators only |
| Access review | Users, roles, API keys and their owners, tool access, connected accounts | Administrators only; restricted |

---

## 11. Configuration (planned keys)

These keys go into the
[Configuration Reference](../getting-started/Configuration%20Reference.md) when the feature is built:

- `reports.enabled` (default `false`)
- `reports.dir`
- `reports.output_dir`
- `reports.history_days`
- `reports.narrate_model`
- `reports.email_internal_domains`
- `reports.webhook_allowlist`
- `reports.sharepoint_internal_sites`
- `reports.max_sections`
- `reports.max_run_seconds`

---

## 12. Build order and tests

1. **Core.** Definitions, the loader, the run engine, report data and history. The tools
   `report_list`, `report_describe`, `report_run`, `report_history` and the generated
   `report_<name>` tools. Markdown and HTML output.
2. **Formats.** PDF, XLSX, PPTX and DOCX, each with its optional dependency. Classification
   marking, the provenance appendix, `report_render` and `report_compare`.
3. **Narration.** `report_narrate` and its validator. Tests must show that each of these is
   rejected: an invented number, a rounded number, a percent of a value not in the data, and a
   date not in the run.
4. **Delivery.** Delivery with approval for external targets, scheduling through workflows, and
   the audit events.
5. **Authoring and docs.**
   - The Studio Report creator.
   - The report library page, with the mobile check in all four themes.
   - The flagship definitions.
   - This guide rewritten as-built, a tutorial, glossary terms and help cards.

---

## 13. Limits of this design

- A report is a snapshot. Re-rendering never re-runs tools, and comparing runs compares what was
  stored.
- The numbers check proves that every figure is in the data. It does not prove that the sentence
  around the figure is right, so narration stays labelled as model-written.
- Delivery is only as private as the channel. External delivery is approved, but SAJHA does not
  encrypt it end to end.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
