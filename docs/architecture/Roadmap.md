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

Every wave of the [Implementation Plan](Implementation%20Plan.md) through wave 7 has shipped, and so
has phase 8.1 of wave 8 (tool health, L21 to L25: schema defaults, broken tools fixed or removed,
the live tool check, domain descriptions and generated guide tables; the CHANGELOG has them). The rest
of wave 8 (quantitative planners, open data, business intelligence and reports) is placed and
planned: its items are L26 to L59 in [section 4.3](#43-wave-8-placed). One carry-over: the release
after 8.8.0 removes the `tools.apply_schema_defaults` switch
([Tool Quality §12.1](Tool%20Quality.md#121-schema-defaults-applied-before-a-call)).

---

## 3. Next

### 3.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X7 | Ask SAJHA over MCP, finished | `sajha_ask` is the one tool most clients will call | Destructive-tool confirmation comes back as `needs_confirmation`, not as a Multi Round-Trip Request; history is not trimmed on `ContextTooLong`; freshness and agreement are not in the confidence score ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Confirmation as MRTR on 2026-07-28; trim oldest turns before falling back to a larger model | M | none |
| X8 | Document connectors as RAG sources | Answers grounded in SharePoint, Drive or Confluence are what most people ask an assistant for | A source is a folder in the storage backend, or an upload; PDF and Word are read, scanned PDFs are not (no OCR) ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Sources that read through connected accounts, so a user's index respects their own access; incremental re-index; optional OCR | M | none |
| X9 | LLM providers: the last synchronous paths | Thread-pool wrappers limit concurrency under load | Bedrock (boto3 is synchronous) and embeddings run in a worker thread; Bedrock refuses `reasoning_effort` (`sajha/ai/llm/providers/bedrock.py`; [Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | An async Bedrock client; native async embeddings on the HTTP providers; `reasoning_effort` through `additionalModelRequestFields` per model | S | none |
| X10 | Weaviate and Chroma connectors | Two common vector stores reachable today only by federating their own MCP servers | Not built ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)); the `VectorAdapter` interface in `sajha/connectors/vector.py` is small | One adapter each, with the same allowlist, filters and masking as Qdrant | S | none |
| X11 | Push-based reload | Polling delays a change on cloud storage by up to the interval, and costs list calls | `hot_reload.interval_seconds` polls; workflow file triggers poll too ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built), [Workflows](Workflows.md#9-limits)) | Bucket event notifications (S3 to SQS or EventBridge, Azure Event Grid, GCS Pub/Sub) feeding the change bus; polling stays as the fallback | M | none |
| X12 | Protocol gaps | Each is a client a strict reviewer can name | `notifications/tasks` is not emitted; legacy streamable-HTTP sessions get no `list_changed`; external issuers must issue JWTs (no RFC 7662 introspection); no CORS on the OAuth endpoints for browser clients ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits), [MCP 2025-11-25 Compliance](../protocol/MCP%202025-11-25%20Compliance.md#7-not-implemented-on-this-path)) | Take them in that order; each lands with conformance evidence in its compliance report | M | none |

### 3.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X13 | A benchmark suite with published numbers | A buyer comparing servers asks "how fast, on what hardware"; SAJHA has no answer | Nothing measures throughput or latency; the deck states that it "claims no performance it has not measured" ([deck guide](../../tools/deck/GUIDE.md)) | A repeatable load harness against `/mcp` in both eras, calling mock tools, at one and several workers on each `state.backend`; publish p50, p99 and throughput with the hardware in [Scaling and State](Scaling%20and%20State.md), and let the deck read them at build time | M | none |
| X14 | SLOs and failure tests | The failure behaviour is written down but not exercised | [Scaling and State](Scaling%20and%20State.md#7-failure-behaviour-and-limits) describes Redis loss, slow databases and dying workers; [Observability](Observability.md) ships alert rules | State SLOs on the existing metrics; failure tests that stop Redis, kill a worker mid-task and break an upstream, asserting the documented behaviour | M | X13 |
| X16 | A TypeScript client SDK (deferred by decision) | Most agent front ends are TypeScript | The client SDK (`clientsdk`) is Python only; any standard MCP client already works against `/mcp` ([Client SDK Guide](../clients/Client%20SDK%20Guide.md)). The owner has deferred this | A thin package on the official TypeScript MCP SDK, mirroring `SajhaMCPClient`, plus the REST and A2A helpers | M | none |

---

## 4. Later

### 4.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L1 | Storage, finished | Cloud deployments still need a shared file system in places | DuckDB reads a local directory only; Studio modules need a shared file system; plugins and some other subsystems use direct file IO; no storage-backend tests in CI; no Azure or GCP deployment guide ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built)) | The Storage Guide's planned list, in its order; backend tests on emulators in CI | M | none |
| L2 | Federation, complete | Federated servers lose features they have | Resource templates, completions, `resources/subscribe`, upstream tasks and `ui://` views are not carried; 2025-11-25 upstreams' requests to the client are declined ([Federation](Federation.md#12-limits)) | Carry each feature through with the same namespacing and policy | M | none |
| L3 | Workflow engine limits | Long or fan-out workflows hit them first | A `foreach` body is one call; change-bus event triggers fire only on the producing worker; missed cron slots are coalesced ([Workflows](Workflows.md#9-limits)) | Sub-graph bodies; relay trigger events through the state store; an opt-in replay of missed slots | M | none |
| L4 | API Import coverage | Real-world specs use what is not imported | No multipart or binary bodies, callbacks or GraphQL subscriptions; pagination is a hint, not followed; remote `$ref` in Swagger 2.0 not converted ([API Import](API%20Import.md#8-limits)) | Multipart first (it blocks uploads), then opt-in pagination following with a page cap | M | none |
| L5 | Tool quality reach | Tests that run live are flaky; lexical evals miss meaning | Cassettes cover `urllib.request`, `requests` and `httpx` only; eval answer checks are lexical ([Tool Quality](Tool%20Quality.md#10-limits)) | Cassettes for other HTTP clients and SDK transports; an optional model-graded check beside the lexical ones | M | none |
| L6 | Sandbox depth | Host-name allowlisting is library-level; a container per call is slow | No egress proxy; no warm pool; no WASM backend ([Sandbox](Sandbox.md#9-limits-and-future-work)) | An egress proxy that enforces the allowlist on the wire; a warm container pool with state reset; WASM for pure-Python tools | M | none |
| L7 | Provider tool gaps | Each limits a common task | SharePoint uploads stop at Graph's simple-upload size and only the client-credentials grant is implemented (`sajha/tools/impl/sharepoint_tool.py`; [SharePoint Tool Reference Guide](../tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md#known-issues)); the web crawler runs no JavaScript and parses HTML only ([Web Crawler Tool Reference Guide](../tools/search/Web%20Crawler%20Tool%20Reference%20Guide.md#limitations)). The other provider guides' limitations are the upstream APIs' own | Upload sessions and certificate credentials for SharePoint; PDF text for the crawler | S | none |

### 4.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L9 | A container per federated stdio server | Docker's and Microsoft's gateways run each server in its own container (`/comparison`, "isolation"); SAJHA runs a stdio upstream as its own process user | stdio upstreams are off unless `federation.allow_stdio` is set, and then run unconfined (`sajha/federation/connection.py`; [Federation](Federation.md)) | Launch stdio upstreams through the sandbox's `docker` backend with its network policy, one container per upstream, restarted by the federation manager | L | L6 |
| L20 | Per-user sign-in for proxied servers: the remaining parts | Some vendors let a service identity act on behalf of named users; writes through proxied servers are approved only where an operator wrote a rule | `token_user` and `oauth_user` are built ([Per-User Sign-In for Proxied Servers §10](Per-User%20Sign-In%20for%20Proxied%20Servers.md#10-what-is-built)); the `service_with_user` mode is not, and no default policy rule asks for approval of proxied writes | `service_with_user` (a shared identity with the SAJHA user named in an audit header the vendor records); a shipped, switchable default rule requiring approval for proxied tools without `readOnlyHint` | S | none |
| L10 | Federation at gateway scale | The gateways are built to put many servers behind one endpoint (`/comparison`) | Connection state, the event loop and breakers are per process; federation is off by default ([Federation](Federation.md#12-limits)) | Shared upstream health in the state store, connection pools per upstream, routing and load shedding across many upstreams, published with X13's numbers | L | X13 |
| L11 | SaaS breadth through packs | Composio, Zapier and Smithery reach thousands of apps with per-user sign-in (`/comparison`, "integrations") | Connected accounts link a handful of providers; any OAuth 2.0 service can be added ([Connected Accounts](Connected%20Accounts.md)) | Provider packs: a connected-account preset plus a reviewed API Import of the service's spec, installed together; start with the services users ask for most | L | L12 |
| L12 | Signed plugins and a catalog | Sharing tools between teams needs trust in who wrote them | A plugin's optional `checksum` sits beside its code and detects corruption, not tampering (`sajha/core/plugins.py`; [Security Model](../security/Security%20Model.md#plugins)) | Publisher signatures verified against configured trusted keys; a catalog page that installs a signed plugin through the same review-and-approve gate as Describe a tool. Separately, list SAJHA in the official MCP Registry (https://registry.modelcontextprotocol.io, launched as a preview in September 2025) | L | none |
| L13 | One-click deployment templates (no hosted service, by decision) | Every hosted competitor in `/comparison` is chosen partly because nobody has to run it | No hosted service; the Helm chart and recipes for AWS, Hetzner and bare metal exist ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md), `deployment/README.md`) | First, one-click templates (Azure and Google Cloud recipes, a published Helm repository, a marketplace image); a hosted service is a business decision, and would need tenant isolation, which SAJHA does not have (see [section 6](#6-not-planned)) | L | none |
| L14 | Console in other languages | Regulated and global users ask for it | Every console string is English in the templates | Extract strings with a gettext catalog for templates and page help; the glossary and guides stay English | L | none (console checks: X15, shipped) |
| L15 | Planners chosen by learning from results | The `auto` planner chooses by rules, a model's label and escalation on failed checks; it does not yet learn which strategy actually wins for each tool and kind of question | SAJHA records what a learner needs (verify outcomes, confidence, `stopped_by`, cost, latency, eval scores per planner), but nothing feeds it back into the choice ([LLM Tools](LLM%20Tools.md#913-automatic-planner-selection)) | Offline first: eval sets rank planners per tool and question class, and a person approves updated routing rules. Then an opt-in online bandit (Thompson sampling or epsilon-greedy) across a tool's allowed planners, scoring quality minus a cost weight, exploring a capped share of traffic through the canary machinery with automatic rollback | M | LLM tools built; enough traffic and eval history |
| L16 | SAJHA Net, finished | Domain data sovereignty across SAJHA and other MCP servers is built (waves 4 and 5 of the [Implementation Plan](Implementation%20Plan.md)); a few parts of the design are not | [SAJHA Net §5.5](SAJHA%20Net.md#55-what-is-built) lists what is built and what remains, with the protocol's conformance ids not yet covered | Take the remaining items in that section's order; each lands with its conformance case | M | none |
| L19 | SAJHA Net: tasks held at the host | A long remote job should survive a restart of the server the client called, and run longer than one hop's deadline | A task at the home wraps a forwarded call (polling and cancellation work for remote tools); the task lives only at the home, so a home restart loses it and the hop's deadline (`sajhanet.default_timeout_seconds`) bounds it; the `tasks` feature is not listed ([SAJHA Net §5.5](SAJHA%20Net.md#55-what-is-built), protocol §15.6 and §22) | Host-side tasks: a task-augmented forwarded call creates the task at the host for the resolved net user, and the home relays `tasks/get`, `tasks/update` and `tasks/cancel` as signed requests with the same identity; list `tasks` | M | none |

### 4.3 Wave 8 (placed)

The owner approved these items on 2026-10-11 (L51–L59, quantitative planners, the same day: "add to
the roadmap and build at the first opportunity") and placed them in wave 8 of the
[Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports):

| Phase | Items | Release |
|---|---|---|
| 8.1 | L21–L25 (shipped; rows removed) | 8.8.0 |
| 8.2 | L51–L59 (quantitative planners) | 8.9.0 |
| 8.3 | L26–L39 | 8.10.0 |
| 8.4 | L40–L44 | 8.11.0 |
| 8.5 | L45–L50 | 8.12.0 |

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L26 | Business calendars (`calendars`) (wave 8) | Settlement dates, business-day counts and holidays are in every finance question | Not built; Nager.Date dropped for its commercial terms ([Open Data Tools](Open%20Data%20Tools.md)) | Offline calendars from the MIT `holidays` package: holidays, business days, add business days, settlement and date adjustment | S | none |
| L27 | Legal entities (`gleif`) (wave 8) | Counterparty hierarchy is the base of exposure reporting | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | LEI lookup and search, direct and ultimate parents and children, ISINs; CC0 | S | none |
| L28 | BIS statistics (`bis`) (wave 8) | One cross-country source for policy rates, credit gaps, property prices and effective exchange rates | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | Host profile on the shared SDMX client; "Source: BIS" on every result | S | none (the shared SDMX client shipped in 8.8.0) |
| L29 | US Treasury (`us_treasury`) (wave 8) | The official yield curve, debt, auctions and daily statement | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | Fiscal Data and the par yield curve feeds, tenors and percent as inputs | S | none |
| L30 | Sanctions screening (`sanctions`) (wave 8) | Screening against official lists is a daily control | Not built; OpenSanctions dropped for its licence ([Open Data Tools](Open%20Data%20Tools.md)) | OFAC, EU, UK and (after legal sign-off; off until then) UN lists in a local index refreshed by a workflow; fuzzy screening, entries, changes; results blocked from Ask SAJHA by a policy rule | M | none |
| L31 | FDIC BankFind (`fdic`) (wave 8) | US bank institutions, financials and failures | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | Institutions, financials, failures, locations, history, deposits; optional key; cached | S | none |
| L32 | CFTC Commitments of Traders (`cftc`) (wave 8) | Positioning by trader category | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | Latest, history, markets and net positioning over the Socrata datasets, with an app token | S | none |
| L33 | Eurostat and OECD (`eurostat`, `oecd`) (wave 8) | Monthly and quarterly European and OECD statistics | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | Host profiles on the shared SDMX client; OECD under one shared hourly budget | M | none (the shared SDMX client shipped in 8.8.0) |
| L34 | Statistics offices (`ons`, `statcan`, `abs`) (wave 8) | First-hand national statistics for the UK, Canada and Australia | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | One folder per office; ABS on the SDMX client | M | none (the shared SDMX client shipped in 8.8.0) |
| L35 | US BLS, BEA and EIA (`bls`, `bea`, `eia`) (wave 8) | First-hand US labour, national accounts and energy data | Not built; BEA answered 503 on the day it was checked ([Open Data Tools](Open%20Data%20Tools.md)) | Keys from the environment; BLS v2; curated and generic tools | M | none |
| L36 | Hazards (`hazards`) (wave 8) | Operational and physical-climate risk questions | Not built; Open-Meteo dropped for its non-commercial free tier ([Open Data Tools](Open%20Data%20Tools.md)) | USGS earthquakes, NASA FIRMS fires, and GDACS alerts with their disclaimer once legal approves (off until then) | S | none |
| L37 | Research and Wikidata (`research`, `wikipedia`) (wave 8) | Literature and entity facts behind an answer | Not built ([Open Data Tools](Open%20Data%20Tools.md)) | OpenAlex (key and budget), Crossref, arXiv (global throttle); Wikidata in the existing `wikipedia` folder | M | none |
| L38 | News events (`gdelt`) (wave 8) | Coverage and tone of events over time | Not built; GEO 2.0 dropped ([Open Data Tools](Open%20Data%20Tools.md)) | DOC, TV and Context APIs, serialised at one call per 5 seconds, cached | S | none |
| L39 | Public spending and catalogue (`us_spending`) (wave 8) | US federal awards and the data.gov catalogue | Not built; the CKAN API is gone ([Open Data Tools](Open%20Data%20Tools.md)) | USAspending search and recipients; the new data.gov catalogue API pinned by a contract test | S | none |
| L40 | Metrics layer (`bi`) (wave 8) | Every caller re-invents "revenue" in SQL | OLAP measures are DuckDB expressions, not owned metrics ([Business Intelligence](Business%20Intelligence.md)) | Metric definitions with owner, grain and dimensions, compiled to safe SQL that runs through the source's own guard; list, describe, query | L | none |
| L41 | BI analysis tools (wave 8) | People ask compared with when, why it changed and what next | The OLAP engines for cohorts and windows are not exposed ([Business Intelligence](Business%20Intelligence.md)) | Compare, top-N and Pareto, crosstab, cohort retention, contribution analysis, anomalies, forecasts | M | L40 |
| L42 | Charts and blending tool results (wave 8) | Answers need pictures, and public data joined with internal data | No chart tool; tool output cannot be joined with tables ([Business Intelligence](Business%20Intelligence.md)) | `bi_chart` (spec, SVG, MCP Apps view); `bi_load_tool_result` into a private, expiring DuckDB table per user, exposing the tool-result loader built with L54 | M | L40, L54 |
| L43 | Dataset catalogue, profiling and data quality (wave 8) | Trust in a metric needs its data's freshness and checks | Not built ([Business Intelligence](Business%20Intelligence.md)) | A catalogue across OLAP, DuckDB and connectors; profiling; check suites scheduled as workflows with notices and alerts | M | L40 |
| L44 | Dashboards (wave 8) | Teams look at the same metrics every day | Not built ([Business Intelligence](Business%20Intelligence.md)) | Dashboard files of tiles (the unit reports reuse), a BI console page | M | L41, L42 |
| L45 | Report definitions and engine (`reports`) (wave 8) | Recurring documents built by hand from tool output | Not built ([Reports](Reports.md)) | Definitions in a reports directory published as `report_<name>` tools; run, list, describe, history | L | L44 |
| L46 | Report formats (wave 8) | Recipients want PDF, Excel, PowerPoint or Word | Not built ([Reports](Reports.md)) | HTML, Markdown, DOCX; PDF through headless Chromium, XLSX and PPTX as optional dependencies; classification marking; provenance appendix | M | L45 |
| L47 | Narration with a numbers check (wave 8) | Model commentary must not invent figures | Not built ([Reports](Reports.md)) | `report_narrate` over the run's data only; every number checked against the data by the numbers validator of L51; rejected text never delivered | M | L45, L51 |
| L48 | Report delivery and governance (wave 8) | Reports leave the building | Not built ([Reports](Reports.md)) | Email, Teams or Slack webhook, SharePoint, folder; approval for external targets; audit; scheduling through workflows | M | L45, L46 |
| L49 | Studio Report creator and report library page (wave 8) | Authors need to build and run reports without YAML | Not built; `/reports` is today the usage dashboard ([Reports](Reports.md)) | A Studio creator with preview; a library page with run, history and compare | M | L45 |
| L50 | Flagship reports (wave 8) | Each proves the design on a real need | Not built ([Reports](Reports.md)) | Daily risk, counterparty exposure, regulatory capital, morning brief, company tearsheet, country profile, central bank watch, metric pack, data quality, platform report, access review | M | L46–L48 |
| L51 | Quantitative workspace (wave 8) | A model's arithmetic and units cannot be trusted, and a computed figure is in no tool result | The verify check `numbers_in_results` only finds figures that a result contains; nothing tracks units ([Quantitative Planners](Quantitative%20Planners.md)) | Quantities with unit, as-of and source; a tested operation library (percent change, CAGR, bp spread, annualise, NPV, weighted average, regression and more); a unit-aware numbers validator, shared later with report narration | M | none |
| L52 | `calc_graph` and `estimate_then_compute` planners (wave 8) | Numeric answers need computed figures with lineage | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | The model writes a computation graph of tool inputs and library operations; SAJHA validates it, runs it with unit checks and records each figure's lineage; a rough estimate first catches order-of-magnitude slips | M | L51 |
| L53 | `scenario` planner (wave 8) | "What if" and sensitivity questions are a grid of runs | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | A shock grid run as parallel tool calls (for example qlrisk) and tabulated by SAJHA as a sensitivity table | S | L51 |
| L54 | `data_analyst` planner and the tool-result loader (wave 8) | Questions over many rows need a query, not a lookup | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | Tool results loaded into the caller's private DuckDB scratch database (the loader BI's `bi_load_tool_result` exposes, L42); the model writes read-only SQL | M | L51 |
| L55 | `code_act` planner (wave 8) | Some computations do not fit a fixed library | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | Model-written Python in the existing sandbox, network off, typed quantities out, only for roles an administrator lists | M | L51 |
| L56 | `optimize` planner (wave 8) | Allocation and sizing questions need a solver | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | A restricted formulation solved with SciPy (optional), every constraint checked at the solution | M | L51 |
| L57 | Numbers check for every planner (wave 8) | Any planner can cite a figure it did not get from a tool | Only planners whose files run `verify` check figures ([Quantitative Planners](Quantitative%20Planners.md)) | A reserved `numbers_check` setting (`off`, `warn`, `enforce`) every planner accepts, so an overlay turns it on | S | L51 |
| L58 | `research_writer` and `reconcile` planners (wave 8) | Cited write-ups and source comparisons are common requests | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | A per-section gather and cited draft from the existing stages; figures from several sources aligned on unit and date, differences listed with lineage | S | L51 |
| L59 | Router and `auto` candidates, quantitative evals (wave 8) | The new planners must be chosen, and proven | Not built ([Quantitative Planners](Quantitative%20Planners.md)) | `auto` and `router` offer `calc_graph`, `scenario` and `data_analyst`; eval sets of quantitative questions with known answers run on the mock provider in CI | S | L52–L58 |

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
- **TypeScript client** stays deferred (X16).
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
