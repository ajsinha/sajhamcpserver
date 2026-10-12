# SAJHA Roadmap

This document owns one topic: **what is not built yet, and what should come next**. It
has two kinds of item. *Unfinished work* is a gap that the code or a guide already
records: a feature that is half built, a limit a guide lists, a release step
not taken. *Enhancements* are recommendations for making SAJHA the MCP server teams choose,
grounded in where the comparison (`/comparison`, data in `sajha/web/competitive.py`) says
others are stronger.

Each item is one line here. The detail of a feature's limits stays in the guide that owns
the feature, and every row links to it. When the two disagree, the owning guide is right
and this roadmap is the one to fix.

---

## 1. How to read this

The order in which these items are built is the
[Implementation Plan](Implementation%20Plan.md): waves, each a release, with each wave's status.

**Horizons.** *Now* is what the next release needs before it is cut. *Next* is the work that
closes the gaps an operator meets first (access control, the intelligence layer, evidence of
performance). *Later* is larger work that changes what kind of product SAJHA is (gateway
scale, container isolation, SaaS breadth, hosting, streaming between servers).

**IDs.** `N` (now), `X` (next) and `L` (later), so a "Depends on" cell can name an item.

**Size.**

| Size | Meaning |
|---|---|
| S | One module and its tests, plus an edit to the owning guide |
| M | A subsystem: code, tests, a guide section, usually a tutorial |
| L | Cross-cutting or a new subsystem: needs a design written down first |

**Decision** marks an item whose direction is the owner's call, not an engineering
judgement. They are collected in [section 5](#5-decisions-needed).

---

## 2. Now

Every wave of the [Implementation Plan](Implementation%20Plan.md) is done or dropped: waves 1 to 14
and 16 shipped (the last in 8.15.0, open data P2 and P3), and wave 15 (business intelligence
finished) was dropped by the owner; the CHANGELOG has each release. Nothing is needed before the next
release is cut. What is still open is below: L1, L6, L7, L11 to L14, and GDACS
(L36, waiting for legal) in [section 4.3](#43-wave-8-placed). GDELT's TV tool is not a row: its
upstream API has held no data since October 2024 ([Open Data Tools](Open%20Data%20Tools.md)). The
rest of BI and reports was descoped (see [section 5](#5-decisions-needed)).

---

## 3. Next

### 3.1 Unfinished work

None open.

### 3.2 Enhancements

None open.

---

## 4. Later

### 4.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L1 | Storage, finished | A few read-mostly folders still need a local or shared disk on a cloud backend | The SQL-select and advanced OLAP data folders, `config/mcp_servers.json`, the MCP Apps folder, the tool-quality folders, shipped workflows and the OLAP datasets file use direct file IO; the storage emulator tests exist but CI does not run them; no `fsspec` backend ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built)) | The Storage Guide's planned list, in its order; the emulator job in CI | M | none |
| L6 | Sandbox depth: WASM | A pure-Python tool could run with no system calls at all | The egress proxy and the warm container pool are built; there is no WASM backend, and no WASI Python runtime is among the dependencies ([Sandbox](Sandbox.md#9-limits-and-future-work)) | A WASM backend (wasmtime with a WASI Python build) for pure-Python tools | M | none |
| L7 | Provider tool gaps | Each limits a common task | SharePoint's app-only grant takes a client secret only ([SharePoint Tool Reference Guide](../tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md#known-issues)); the other provider guides' limitations are the upstream APIs' own | Certificate credentials (a signed client assertion) for SharePoint's app-only grant | S | none |

### 4.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L11 | SaaS breadth through packs | Composio, Zapier and Smithery reach thousands of apps with per-user sign-in (`/comparison`, "integrations") | Provider packs install a provider and its reviewed tools from the admin API or `python -m sajha.packs`; there is no console page ([Connected Accounts §11](Connected%20Accounts.md#11-provider-packs)) | A console page over the same plan, review and install API; more packs for the services users ask for, each with a spec whose licence allows bundling | M | none |
| L12 | SAJHA in the official MCP Registry | Clients and teams look for servers in the official registry | Signed plugins and the plugin catalog are built ([Security Model](../security/Security%20Model.md#plugins)); SAJHA itself is not listed in the official MCP Registry (https://registry.modelcontextprotocol.io, a preview since September 2025) | Publish a `server.json` for SAJHA's container image and its stdio entry (`sajha serve --stdio`) and register it | S | none |
| L13 | One-click deployment templates (no hosted service, by decision) | Every hosted competitor in `/comparison` is chosen partly because nobody has to run it | No hosted service; the Helm chart and recipes for AWS, Hetzner and bare metal exist ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md), `deployment/README.md`) | First, one-click templates (Azure and Google Cloud recipes, a published Helm repository, a marketplace image); a hosted service is a business decision, and would need tenant isolation, which SAJHA does not have (see [section 6](#6-not-planned)) | L | none |
| L14 | Console in other languages | Regulated and global users ask for it | Built: the translation framework, English only ([Architecture](Architecture.md) §10, "Languages"): gettext through Jinja, `_t()` in page scripts, `sajha.pot` kept current, `scripts/i18n.py`, language resolution among compiled catalogs. By the owner's decision no translation ships and there is no language picker | The translations themselves, if the owner decides to ship one: a catalog per language (`scripts/i18n.py init`), a way for a user to choose it, and wrapping the templates not yet in `TRANSLATED_TEMPLATES`; the glossary and guides stay English | M | none |

### 4.3 Wave 8 (placed)

The owner approved these items on 2026-10-11 (L51–L59, quantitative planners, the same day: "add to
the roadmap and build at the first opportunity") and placed them in wave 8 of the
[Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports):

| Phase | Items | Release |
|---|---|---|
| 8.1 | L21–L25 (shipped; rows removed) | 8.8.0 |
| 8.2 | L51–L60 (quantitative planners; built, rows removed; L60 in 8.14.0) | 8.9.0 |
| 8.3 | L26–L39 (P1 L26–L31 and Wikidata shipped, rows removed; P2 L32–L35, and P3 L37–L39 and L36 but GDACS, shipped in 8.15.0, rows removed) | 8.10.0, 8.15.0 |
| 8.4 | L40–L44 (L40, L42 shipped; L41 in part; the rest descoped; rows removed) | 8.11.0 |
| 8.5 | L45–L50 (L45 to L47 and the library page shipped; the rest descoped; rows removed) | 8.11.0 |

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L36 | GDACS disaster alerts (`hazards`) (wave 8) | Disaster alerts beside the earthquake and fire tools | Not built: GDACS's terms grant no licence; USGS earthquakes and NASA FIRMS fires shipped in 8.15.0 ([Hazards guide](../tools/public-data/Hazards%20Tool%20Reference%20Guide.md)) | `hazards_disaster_alerts` with GDACS's disclaimer in every result, once legal approves (**Decision**) | S | legal approval |

---

## 5. Decisions needed

None open.

Recorded decisions:

- **Wave 8 (2026-10-11):** schema defaults are applied by default, with `tools.apply_schema_defaults`
  as a one-release off switch (L21); the UN sanctions list and GDACS stay off until legal approves;
  sanctions screening results are blocked from Ask SAJHA by a policy rule; BIS ships with its
  citation; no paid data options; P2 and P3 open data sources may slip to a later release
  ([Open Data Tools §6](Open%20Data%20Tools.md#6-decisions)); the `/reports` usage page's menu entry
  becomes "Usage" in the reports phase ([Reports §9](Reports.md#9-console-and-studio)); Playwright,
  openpyxl and python-pptx are acceptable as optional `requires`; quantitative planners are added
  and built at the first opportunity (L51–L59).
- **Release 7.0.0** cut on the owner's decision (formerly N1).
- **TypeScript client**: dropped by the owner (2026-10-11); the client SDK stays Python only, and any standard MCP client works against `/mcp`.
- **BI and reporting products** descoped by the owner (2026-10-11): an MCP server gives models governed tools, it is not a BI or reporting product. The shipped metric tools (`bi_*`), `bi_load_tool_result`, `bi_chart` and the report tools stay; dashboards, the BI page, the dataset catalogue and data-quality suites, cohort, anomaly and forecast tools (formerly L41 in part, L43, L44), report delivery, the Studio Report creator, more flagships and PNG charts in PPTX and DOCX (formerly L46, L48 to L50) are not planned. A workflow can run `report_run` on a schedule.
- **Deployment:** one-click templates only; no hosted service (L13).
- **No tenants** (formerly X1, see section 6) and **no open-source licence**.

---

## 6. Not planned

Limits that are deliberate, so they are not roadmap items. Each owner says why.

- **No tenants**: decided (formerly X1). The tenant records, which were stored but never
  enforced, were removed; roles, API-key tool access and policy rules (which also meter
  quotas) separate teams ([Security Model](../security/Security%20Model.md#tool-access)).
  Usage and cost are therefore not reported per tenant.
- **No open-source licence**: decided. SAJHA is proprietary ("All rights reserved", as `/comparison` records); evaluations that require an OSI licence are out of scope.

- **No stream resumability on the 2026-07-28 path**: by design of that protocol version
  ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits)).
- **No writes or stored procedures through data connectors**
  ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)).
- **No DDL on PostgreSQL from SAJHA**; an operator runs the schema files
  ([Database Setup](../getting-started/Database%20Setup.md)); the start-up check and `python -m sajha.db upgrade-sql` only print SQL.
- **SQLite on several hosts** ([Scaling and State](Scaling%20and%20State.md#7-failure-behaviour-and-limits)).
- **Template creators run in-process** ([Sandbox](Sandbox.md#9-limits-and-future-work)).
- **Syslog over UDP** for SIEM export ([Policy and Audit](Policy%20and%20Audit.md#11-limits)).
- **Killing a running thread-pool call**: Python cannot; calls are abandoned and tools may
  poll for cancellation ([Workflows](Workflows.md#9-limits)).

---

## 7. Keeping this document current

- **When an item ships**, delete its row, describe it in the CHANGELOG's Unreleased
  section, and remove it from the owning guide's limits section. A shipped feature is
  described by its guide, not here.
- **When a new gap is found**, add it to the owning guide's limits section first, then
  one row here that links to it.
- **No numbers from the code** (tool counts, test counts, versions); name where the live
  answer is ([CLAUDE.md](../../CLAUDE.md)).

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
