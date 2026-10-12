# SAJHA MCP Server — Changelog

Newest first. The current version is `app.version` in `config/application.yml`.

## v8.15.1 (October 2026) — SAJHA's own temporary folder (app.tmp_dir) and a sweep of its leftovers

### Added

- **SAJHA's own temporary folder, `app.tmp_dir`** (env `SAJHA_APP_TMP_DIR`; empty, the default, is the system
  temp directory: `/tmp` on Linux). At start-up the server, `--stdio` and every `python -m sajha.*` command
  create it if missing (mode 0700) and refuse an unusable one with an error naming the key; then
  `tempfile.tempdir` and `TMPDIR`/`TEMP`/`TMP` point at it, so every temp file of the process, its libraries
  and the processes it starts (sandbox launchers, `isolation: none` stdio upstreams, Playwright's Chromium)
  goes there. DuckDB connections spill to a folder of their own under it (they used to spill to `.tmp` in
  the working directory), and the object-storage cache (`storage.*.cache_dir`, now empty by default) is
  `<app.tmp_dir>/sajha-cache`. SAJHA's own temp entries are named `sajha-<kind>-p<pid>-...`, and a start-up
  sweep removes `sajha-*` leftovers older than `app.tmp_max_age_hours` (24; 0: off) whose process is gone,
  never anything else. `sajha/core/paths.py`;
  [Storage Guide](docs/getting-started/Storage%20Guide.md#temporary-files),
  [Configuration Reference](docs/getting-started/Configuration%20Reference.md#app),
  [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md#temporary-folder).
- The test suite keeps SAJHA's temp files (and those of the servers it starts) in its session folder, and
  leaves no `sajha-*` entries in the system temp directory.

## v8.15.0 (October 2026) — open data P2 and P3, the final documentation pass and tutorials, security fixes

### Upgrading

- **`db.name` now defaults to `sajha`**, as every recipe, chart, guide and the seed already assumed (it was
  `sajha_mcp` in code). A PostgreSQL install that left the name unset and used `sajha_mcp` must set
  `SAJHA_DB_NAME=sajha_mcp` (or `DB_NAME`) before upgrading.

- **Report definitions may no longer have `recipients` or `schedule`.** Delivery and scheduling were
  descoped in 8.11.0, and the loader accepted both keys while nothing acted on them. A definition that
  has either is now refused with a message saying so: remove the key, and use a workflow to run
  `report_run` on a schedule (a cron trigger and a `tool` step; [Reports](docs/architecture/Reports.md) §7).
  `report_list` and `report_describe` no longer return `schedule` (or recipients), and run summaries
  (`report_history`) no longer carry the always-empty `deliveries`.
- **API keys get nothing from personal document sources**, including a key bound to a user (it used to
  get that user's connected-account passages). Use the user's sign-in (a SAJHA JWT or OAuth token).
- **`run_sajha_web.py --port` / `--host` set `SAJHA_SERVER_PORT` / `SAJHA_SERVER_HOST`** before the
  settings load, so `server.port` and `server.host` are what the server listens on.

### Added

- **Open data P2: nine new tool folders, 46 read-only tools** (Open Data Tools §4, Roadmap L32 to L35), each
  source's terms checked again live on 2026-10-11 and 2026-10-12 (all nine pass). Every result names its
  source, with any credit line the licence asks for, in `source`; every fetch goes through the outbound fetch
  guard; keys come from the environment only; each source's rate limit is one sliding window in the state
  store shared by every worker (`sajha/tools/impl/open_data_common.py`), and results are cached by
  `cache_ttl`. Every tool has a probe case and a recorded cassette except BEA and EIA (below), and a
  provider guide under `docs/tools/public-data/` with generated tables.
  - `cftc` (4): `cftc_cot_latest`, `cftc_cot_history`, `cftc_cot_markets`, `cftc_cot_net_positioning` over
    the CFTC's Socrata datasets (legacy, disaggregated and TFF; futures only or combined). Keyless; optional
    `CFTC_APP_TOKEN`.
  - `eurostat` (7): `eurostat_search`, `eurostat_get_series` and curated `eurostat_hicp`, `eurostat_gdp`,
    `eurostat_unemployment`, `eurostat_government_debt`, `eurostat_house_prices`, a host profile on the
    shared SDMX client. Figures Eurostat may not license for commercial reuse (countries outside the EU,
    EFTA and the candidates) carry `reuse_note`.
  - `oecd` (6): `oecd_search`, `oecd_get_series` and curated `oecd_leading_indicators`,
    `oecd_main_economic_indicators`, `oecd_quarterly_national_accounts`, `oecd_economic_outlook`
    (projections marked); one window of 50 requests an hour for all workers.
  - `ons` (2), `statcan` (4), `abs` (4): `ons_search`, `ons_timeseries`; `statcan_search_tables`,
    `statcan_vector`, `statcan_table`, `statcan_changed_series` (each result carries the Open Licence
    notice); `abs_cpi`, `abs_labour_force`, `abs_gdp`, `abs_get_series` (on the shared SDMX client).
  - `bls` (7), `bea` (5), `eia` (7): `bls_series` and curated CPI, PPI, payrolls, unemployment rate,
    employment cost index and job openings (`BLS_API_KEY` for v2, else the keyless v1 API; every result
    carries the retrieval date and BLS's disclaimer); `bea_datasets`, `bea_nipa_table`,
    `bea_gdp_by_industry`, `bea_international_transactions`, `bea_regional` (`BEA_API_KEY`; no keyless
    tier); `eia_browse`, `eia_series` (follows the 5,000-row pages) and curated petroleum spot prices and
    stocks, natural gas storage, electricity retail sales and the short-term outlook (`EIA_API_KEY`).
- **Open data P3** (Open Data Tools §4, Roadmap L36 to L39), each source's terms checked again live on
  2026-10-12. Every result carries a `source` attribution; every fetch goes through the outbound fetch
  guard; every tool config sets `cache_ttl`; the rate-limited sources share throttles in the state store
  (`sajha/tools/impl/open_data_common.py`); probe cases and cassettes in `config/tool_tests/`.
  - **Hazards** (`config/tools/hazards/`, `sajha/tools/impl/hazards_tools.py`;
    [Hazards Tool Reference Guide](docs/tools/public-data/Hazards%20Tool%20Reference%20Guide.md)):
    `hazards_earthquakes` and `hazards_significant_earthquakes` (USGS, keyless) and
    `hazards_active_fires` (NASA FIRMS; needs `FIRMS_MAP_KEY`). GDACS alerts are not shipped: its terms
    grant no licence and the owner keeps it off until legal approves.
  - **Research literature** (`config/tools/research/`, `sajha/tools/impl/research_tools.py`;
    [Research Literature Tool Reference Guide](docs/tools/search/Research%20Literature%20Tool%20Reference%20Guide.md)):
    `research_search_works` and `research_get_work` (OpenAlex; optional `OPENALEX_API_KEY`; results report
    the day's budget left), `research_crossref_works` and `research_crossref_doi` (Crossref; optional
    `CROSSREF_MAILTO`), `research_arxiv_search` (arXiv, one request every 3 seconds across workers; links
    only).
  - **GDELT** (`config/tools/gdelt/`, `sajha/tools/impl/gdelt_tools.py`;
    [GDELT Tool Reference Guide](docs/tools/search/GDELT%20Tool%20Reference%20Guide.md)): `gdelt_articles`,
    `gdelt_coverage_timeline` (volume, article count or tone) and `gdelt_context`, serialised at one request
    every 5 seconds across workers, a 429 retried once. `gdelt_tv_mentions` is not shipped: GDELT's TV 2.0
    API has held no data since October 2024.
  - **US spending** (`config/tools/us_spending/`, `sajha/tools/impl/us_spending_tools.py`;
    [US Spending Tool Reference Guide](docs/tools/public-data/US%20Spending%20Tool%20Reference%20Guide.md)):
    `usaspending_awards`, `usaspending_by_category`, `usaspending_over_time`, `usaspending_recipient`
    (USAspending.gov), and `datagov_search` and `datagov_dataset` on the new data.gov catalogue API
    (the CKAN API is gone), its shape pinned by `tests/test_open_data_p3.py`.

### Changed

- **Documentation pass for waves 9 to 16.** Every live guide was checked against the code: stale
  "planned" wording removed for what is built; the Implementation Plan and Roadmap say every wave is done
  or dropped; Business Intelligence and Reports state what was built and what the owner descoped; Open
  Data Tools says P1, P2 and P3 are built except GDACS and GDELT TV, with the reasons; missing notice ids,
  configuration keys and security fixes added; duplicated explanations replaced by links to their owning
  guide. New tutorials, each run against a scratch server: PostgreSQL, several workers and the load
  harness ([Tutorial 46](docs/tutorials/TUTORIAL_46_scaling_postgresql.md)), federation at gateway scale
  (47), sandbox egress and contained stdio upstreams (48), signed plugins and the plugin catalog (49),
  provider packs (50), personal RAG over connected accounts (51), planner routing learned from results
  (52), changing a SAJHA Net safely (53) and how a figure was computed (54).
- **One open data helper module.** The P3 helpers (`open_data_http.py`) are merged into
  `sajha/tools/impl/open_data_common.py`, so every open data tool and FDIC take their shared request window
  through one `take_slot`.

- **The shared SDMX client keeps each observation's flag** (`OBS_FLAG`, `OBS_STATUS`) as `status`; the
  Eurostat tools return it as `flag` and list the flags present.

### Fixed

- **Security:**
  - **An MCP session is its owner's on every request.** `POST /mcp` and `DELETE /mcp` with an
    `Mcp-Session-Id` did not check that the session belonged to the caller (only the `GET /mcp` stream
    did), so another caller holding the ID could use or end it. Every use is now checked with the GET
    stream's rule, and another caller's session answers 404 as an unknown one (`sajha/routes/mcp_routes.py`).
  - **Personal document routes need the console's CSRF token.** `POST /api/ai/docs/mine/sync` and
    `/search` accepted the session cookie without it; they now need `X-CSRF-Token` with the cookie (SAJHA
    JWTs and bearer tokens unaffected). An API key bound to a user is refused there and by
    `sajha_search_my_docs`, as the Intelligence Layer guide says (`sajha/ai/rag/personal.py`).
- **Federation approvals are shared across workers.** An approval made on one worker stayed pending on the
  others until a restart, and a stale worker's save could overwrite it. The federation store's revision is
  in the state store: a change re-reads the document under a short lease before writing, is announced on
  the state store, and every manager re-applies the approvals at once (`sajha/federation/store.py`). Tutorial
  47 no longer restarts the workers.
- **A down upstream fails fast.** A call waited 5 s for a reconnect in backoff on every pool member and
  attempt (20 s or more a call with a pool, so the breaker took minutes to open). While a connection waits
  for its next retry a call now fails at once, and the breaker opens after its threshold in about a
  second (`sajha/federation/connection.py`).
- **Links built without a request use the listening port.** "Connect your account" links in tool results
  used `server.port` from the configuration, not the port the server listens on, and a provider pack plan's
  redirect URI was not built from the request it was asked on; both now use the request's base URL where
  there is one and the listening address otherwise (`sajha/core/transport.py::local_base_url`).
- **The Ask page names this server by its SAJHA Net instance name** (`sajhanet.nets[].instance_name`); it
  read a top-level key that does not exist and always showed the host name.
- **Smaller:** the Studio Folder hint no longer allows `-`; a learned planner choice streams the same reason
  as its audit record ("approved routing rules (<class>)"); a planner-routing proposal made through the
  HTTP API records `source: api`, not `console`; Escape on an open figure's button closes the Ask lineage
  panel; `reconcile` keeps tool names whole in quantity names; the lint `unit` message says once that a
  unit is unknown; the local lab's status names the models the instances resolve (the mock provider as
  such); the System page shows other workers' pool numbers as integers; `plugin_signing verify --trusted`
  says the key came from the `--trusted` file; `tools/bench/bench_federation.py` picks free ports.

- **No audit or usage record is lost when the database pool is busy.** An `audit_log` row whose write
  fails is kept (bounded) and written before the next one, as the hash chain already did; usage-ledger rows
  whose write fails go back on the queue instead of being dropped (`sajha/core/audit.py`,
  `sajha/observability/usage.py`).

- **Cassettes redact `UserID` and `registrationkey`** query parameters too (BEA sends its key as `UserID`).

### Known gaps

- The `bea_*` and `eia_*` test cases are skipped and have no cassettes yet: there was no BEA key, and EIA's
  `DEMO_KEY` allowance ran out during the build. Record them with a key
  (`python -m sajha.quality test --tool 'bea_*,eia_*' --record`). The BEA fixtures follow the BEA API user
  guide's documented shapes, and say so.

## v8.14.0 (October 2026) — cleanup and hardening: every tool fetch guarded, broken tools fixed, accessibility, figure lineage on the Ask page, x-sajha-unit

### Upgrading

- **`tools.apply_schema_defaults` is removed** (promised in 8.8.0). Schema defaults always apply;
  `SAJHA_TOOLS_APPLY_SCHEMA_DEFAULTS` and the YAML key are ignored. A caller that relied on a tool's old
  code default passes that value explicitly (the 8.8.0 entry lists the tools whose default changed).
- **Runtime files are no longer tracked:** `logs/server.log`, `data/sajha.db-shm`,
  `data/duckdb/duckdb_analytics.db.wal` and `.idea/`. Git now ignores them (and `data/*.db-shm`,
  `*.wal`, `data/cache/`, `data/shell_scratch/`). Pulling this release into another clone deletes
  those files there (the server recreates its own): stop the server before pulling (SQLite's
  `-shm` file belongs to a live database), and copy `.idea/` aside first if you use it.
- **`yf_sustainability` is removed.** Yahoo no longer serves ESG scores (every symbol answers "No
  fundamentals data found"), so the tool could only return nothing. There is no keyless replacement.
- **`cg_coin_history`'s `date` is optional** (default yesterday, UTC); a date more than 365 days back
  is now a clear error (CoinGecko's public API and demo keys reach only the past year).
- **The investor-relations tools leave unknown fields out** of a document object instead of sending
  `null`, and their SEC fallback for presentations and press releases returns 8-K filings with the
  matching item (2.02, 7.01, 8.01) instead of every recent filing.

### Added

- **Ask SAJHA shows how a figure was computed** (quantitative planners finished, Roadmap L60). When a
  quantitative planner answers, the figures it computed are underlined buttons in the answer;
  selecting one (click, or Tab and Enter) opens its lineage under the answer: the operation and its
  inputs, recursively, down to the tool calls, each with its tool, call id, arguments, JSON path,
  as-of date, unit and whether the tool or the model declared the unit. Escape or Close shuts it.
  The ask stream sends a new `workspace` event after `answer` (the marked `figures` and their
  `quantities`), and the `AskResult` has `figures`. The script is `static/js/ask_lineage.js`
  (Quantitative Planners §2.1; Intelligence Layer, "POST /api/ai/ask").
- **`x-sajha-unit`, an `outputSchema` keyword that declares a result field's unit** in the
  workspace's grammar (`{"type": "number", "x-sajha-unit": "percent"}`, `"USD mn"`, `"count k"`). A
  value a planner reads at that path takes the tool's unit, recorded as `unit_from: schema`, in
  `calc_graph` (before its unit check, so a tool read may leave out `unit`), `scenario` and
  `reconcile`. JSON Schema validation ignores the keyword; lint reports an unknown unit (new rule
  `unit`, Tool Quality §3). Units are declared on the rate tools of `fred`, `ecb`, `bank_of_canada`,
  `bank_of_japan`, `bis` and `us_treasury`, on most FRED series (index levels, US dollar amounts at
  their scale, counts, prices) and on the `calc` tools whose outputs have a fixed unit. The `fred`
  and those `calc` tools now advertise their real output shape instead of a placeholder `result`
  object (Quantitative Planners §2.2).

### Changed

- The legacy `test/` folder (pre-v3 tool scripts that broke a bare `pytest`) moved to
  `archive/legacy_tests/`. `pytest.ini` sets `testpaths = tests clientsdk/tests sajhanet_agent/tests`,
  so `python -m pytest` at the repository root runs the live suites.
- `data/duckdb/duckdb_analytics.db` stays shipped (the sample catalog: views over the CSV files
  beside it, used by Describe a tool for database context) and is now opened read-only, so it no
  longer changes at runtime or grows a `.wal`.
- **Policy-refused tools are no longer offered to a model.** The policy engine answers, with no side
  effects, whether every call of a tool from a source by a caller would be denied
  (`PolicyEngine.denies`, `sajha.policy.offered`). Ask SAJHA's shortlist (and so an LLM tool's
  planners) leaves out tools refused for source `ask`, and the OpenAI-compatible endpoint's model list
  leaves out LLM tools refused for `openai_api`. The shipped `sanctions_*` rule now keeps those tools
  out of a model's view, not only refuses them when called ([Policy and Audit](docs/architecture/Policy%20and%20Audit.md) §2).
- **MCP Studio shows the domain description.** Each creator's Folder field shows the chosen folder's
  `domain.txt` text, marked as the domain description; creator previews return `domain` (`folder`,
  `domain_description`, `served_description`), and an LLM tool's detail in Studio carries the same
  for the loaded tool (Architecture §5).
- **No database call on the event loop.** The remaining async console routes (provider and model
  edits, user creation and password reset, sign-in and password change, API key administration,
  composite tools, the credential files, A2A tasks, the REST tool endpoint's usage row) run their
  database part in the thread pool. `tests/test_db_session_hold.py` now also fails on any database
  call on the event loop in an async route or helper of `sajha/routes/` (Scaling and State §7).
- **Every tool fetch goes through the outbound fetch guard.** The tools that called urllib or
  requests directly (FRED, Federal Reserve, Bank of Canada, the PBoC/BoJ series, SEC EDGAR and the
  enhanced EDGAR tools, the investor-relations scrapers in `sajha/ir/`, CoinGecko, Alpha Vantage, FMP,
  Tavily, Google, World Bank, UN, FBI, `calc_currency_converter`, `yahoo_get_history`,
  `yahoo_search_symbols`, `yf_trending_tickers`, SharePoint's Graph calls) now use `outbound.request`,
  the new urllib-shaped `outbound.urlopen` or the requests-shaped `outbound.requests_compat`, so
  `tools.outbound.proxy` and the address rules reach them. `tests/test_tool_outbound_sweep.py` fails
  on direct network use under `sajha/tools/impl/` and `sajha/ir/` outside a commented allowlist. The
  yfinance and OpenBB SDKs cannot be routed and are a documented known limit (Security Model §8).
- **CoinGecko is paced.** A per-minute budget and a 429 cooldown (its `Retry-After`) shared by all workers through the state store
  (`coingecko.calls_per_minute`; 5 keyless, 30 with a demo key), result caching (`cache_ttl` in every
  `cg_` config), an optional demo key (`COINGECKO_API_KEY`, `coingecko.api.key`) and CoinGecko's own
  reason in every error; a failed call is an error, never an `{"error": ...}` object returned as data.
- **The live tool check** calls a tool whose class declares `keyless_fallback` even when its key is
  empty, classes a rate-limited call (429) as `error` rather than `not_configured`, and waits between a
  folder's calls as long as a tool's `check_pause_seconds` asks (Tool Quality §12.4).
- **The PBoC and BoJ guides no longer claim a FRED key for every tool**: the IMF-only tools
  (`boj_get_inflation`, `boj_get_money_supply`, `pboc_get_inflation`) and the `*_list_series` tools
  dropped the unused `api_key` from their configs, so the generated tables show the key per tool.
- `openbb_economy_calendar` without dates covers the past 7 days to the next 7 (OpenBB's default is
  today only, empty on a weekend), and a window with no events is an empty result with a `note`.
- `gleif_search`'s fuzzy fallback also tries `field=entity.legalName`, keeps GLEIF's best-match order
  and reports `matched_value` for each fuzzy result.
- **Cases, probes and cassettes for the open-data tools.** Each `gleif_*`, `bis_*`, `ust_*`, `fdic_*`,
  `wikidata_*` and `cal_*` tool has a test case with a probe in `config/tool_tests/`, and every HTTP one
  a recorded cassette, so `python -m sajha.quality test --replay` and CI check them offline (Open Data
  Tools §1).

### Fixed

- **Console accessibility.** `scripts/check_console.py --only-a11y --all` reported 80 failures over
  the 86 console pages (unlabelled selects and inputs, icon-only links and buttons with no name) on
  `/tools`, a tool's configuration page, `/prompts`, `/admin/prompts`, the system monitor, async
  tasks, users, the REST, database query, script, LiveLink, OLAP, Power BI, Power BI DAX and
  SharePoint creators, the composite builder and `/workflows`; it now reports none, light and dark.
  Labels name their controls (`<label for>`), icon-only buttons and links carry `aria-label` and
  `title`, rows that page scripts build (workflow steps and triggers, OLAP dimensions, parameters,
  headers, async tasks, models) are named too, the vendor JSON editor's controls are named, clickable
  chips, cards and remove icons are buttons the keyboard reaches (Enter and Space, via
  `static/js/csp-actions.js`), sortable table headers take focus, focus outlines cover them, and
  status regions that scripts rewrite are live regions. The scan's built-in rules now name a
  `role="button"` element from its text, as the ARIA rules do. `tests/test_console_checks.py`
  gains a static scan of every template and page script (unnamed controls, nameless icon-only
  buttons and links, click handlers the keyboard cannot reach) and the every-page browser scan
  (when `SAJHA_CHECK_BASE` is set); the scan is a release gate (Implementation Plan §9).

- The system monitor (`/api/admin/system-monitor`) reported a hardcoded MCP protocol version
  (`2025-11-25`) and a fallback SAJHA version of `5.3.0`; both are now derived (the newest version of
  each protocol era, and `app.version`). The response also carries `mcp_protocol_versions`.
- `/api/providers/health` and `/api/providers/graph` (the system monitor's Provider Health table) read a
  hard-coded table of providers, tool counts and prefixes that had rotted (CoinGecko tools are `cg_`, not
  `coingecko_`, so it showed none). Both are now derived from the live registry: one entry per tool
  domain, its tool count, and the worst circuit-breaker state of its tools; `expected_tools` and
  `is_local` are gone.
- The Tool Health page with lint (`/admin/tool-health?lint=1`) took 40 seconds or more: the `sajhanet`
  section of `config/application.yml` was re-parsed for every tool (SAJHA Net's description limit). It
  is now parsed once per version of the file (`sajha.core.net_extension.yaml_section`), and the page
  renders in about 3 seconds.
- Test suite: the in-process upstream MCP servers of the federation and proxied-server tests stop in
  1 second instead of waiting 10 for open streams, and the client SDK's live tests wait 1 second (not 20)
  for a server at the default URL; together about 90 seconds less per run.
- Deleting or redeploying an LLM tool in Studio removed the shared `sajha.ai.llm_tools` package from
  `sys.modules`; its next import made a second copy whose submodules were not attributes (found as an
  order-dependent test failure). Studio now forgets only a module it generated for that tool
  (`sajha.tools.impl.<prefix><name>`).
- `tests/test_observability.py` computed "today" once at import, so a run crossing UTC midnight
  failed; the usage queries now cover yesterday and today, read when each test runs.
- **The numbers check was too loose.** A figure written with `%` matched any bare result number equal
  to it ("25%" passed on a bare 25); it now needs a result known to be in percent (a percent-like key,
  `format: percent`, a "25%" string) or a ratio (0.25). A figure written with no unit matched a
  workspace quantity in every unit it converts to ("400" passed for 4%, as 400 bp); it now matches
  the quantity's own unit, or the unit the text names just before it ("in bp: 400"). Applies to the
  planners' `numbers_in_results` and `numbers_in_workspace`, the `numbers_check` setting and report
  narration (Quantitative Planners §2.4, Reports §5).
- **The investor-relations tools timed out or returned nothing** (`ir_get_all_resources`,
  `ir_get_presentations` past 60 s; `ir_get_annual_reports`, `ir_get_documents` empty). The HTTP client
  retried a 403 bot wall three times with backoffs of up to 25 s per page across ten pages; it now fails
  fast on 403 and 4xx, the scraper spends at most 15 s on IR pages, and the SEC EDGAR fallback answers
  (it also sent a `br` encoding the client could not decode, and a `Host` header of its own).
- **The FBI and UN tools were `not_configured` in the live check** although they work without a key
  (api.data.gov's `DEMO_KEY`, Comtrade's preview API); they are now called.
- **`cg_coin_history` answered 401**: its example date was more than a year old, beyond CoinGecko's
  public range.
- `enhanced_edgar_tool.py` put `/mnt/user-data/uploads` at the front of `sys.path` on import, so a
  module planted there would shadow a real one; removed.

## v8.13.0 (October 2026) — security and ecosystem, SAJHA Net finished: sandbox egress and warm pool, contained stdio upstreams, signed plugins, provider packs, personal RAG, planner learning

### Added

- **SAJHA Net console pages, finished** (Roadmap L16; `sajha/net/integration/pages.py`, `changes.py`,
  `sajha/routes/sajhanet_console_routes.py`, `static/js/sajhanet_console.js`;
  [SAJHA Net](docs/architecture/SAJHA%20Net.md) §17.1): administrators get Conflicts and reviews
  (`/admin/sajhanet/reviews`), Users across the net (`/users`), Access and blocks with the access matrix
  (`/blocks`), Key directory (`/keys`), Snapshots (`/snapshots`: verify, compare, download, restore), Live
  activity (`/activity`, with each call's records by trace id), Certificates (`/certificates`), Net settings
  (`/settings`), Sponsored servers (`/sponsored`) and Change history (`/changes`), and an instance's Traffic,
  Users, Keys, Blocks and History tabs (`/net/instances/{net}/{instance}?tab=`), each with JSON behind it, page
  help, menu entries (Govern, Operate) and phone layouts. Every change made through the admin API or the
  console now goes into the net's change history (`<data_dir>/<net>/changes.json`) with who, when, a reason
  and its inverse, and is audited (`sajhanet.change_recorded`); **Undo** applies the inverse as a new change
  (`POST /api/sajhanet/nets/{net}/changes/{id}/undo`, `sajhanet.change_undone`). Before a change the console
  shows its **blast radius** (`GET /api/sajhanet/nets/{net}/blast-radius`) and asks for a reason. Changing
  SAJHA Net admin routes now need the page's CSRF token (`X-CSRF-Token`) from a console session. New glossary
  terms: Net change, Undo (net change), Blast radius, Conflicts and reviews queue, Access matrix, Live activity.
- **The SAJHA Net agent as a home** (Roadmap L16; `sajhanet_agent/home.py`, `config.py`, `identity.py`,
  `rules.py`; [SAJHA Net Agent](docs/clients/SAJHA%20Net%20Agent.md) sections 4 and 6): a new `--config`
  JSON file (users and keys, identity resolvers, import rules, blocks, residency rules, re-export rules;
  re-read when it changes) and `--client-listen` (MCP over Streamable HTTP for local clients). The agent
  publishes its users' keys in the net key directory, lists other members' tools to its clients as
  proxies under qualified and plain names, and forwards their calls signed through the core router. It
  sends and accepts `api_key`, `assertion` and `token_exchange` (serving `/sajhanet/v1/token`), publishes
  and enforces blocks (feature `blocks`), applies residency rules at the home and as a host (feature
  `residency`; a `require_approval` rule refuses with a reason, the agent having no approval surface;
  the router now carries such a `detail` in its refusal), and re-exports imported tools with `origin`,
  relaying the caller's assertion (feature `reexport`). Conformance for target A: BLK-01 now runs against
  the agent in `tests/net/test_net_mixed_conformance.py`; CALL-07, CALL-13, CALL-14 and CALL-15 in
  `sajhanet_agent/tests/test_home.py` and, next to SAJHA, `tests/net/test_net_agent_home.py`.
- **Planners chosen by learning from results** (Roadmap L15; `sajha/ai/planners_engine/learning.py`;
  [LLM Tools](docs/architecture/LLM%20Tools.md#913-automatic-planner-selection) §9.13,
  [Planner Reference](docs/architecture/Planner%20Reference.md) §6.6.2): every automatic planner choice
  (`classify` with `menu: planners`, the shipped `auto`) and its outcome (held or not, reward, cost,
  latency) is recorded as `planner_choice` in the run's audit record and on eval rows. A learning job
  (`python -m sajha.ai.planners_engine.learn`, the new Planner routing page `/admin/planner-routing`, or
  the admin-only tool `sajha_planner_routing_propose` run by the shipped workflow `planner_routing_learn`,
  its trigger off) ranks planners per tool and question class from saved eval runs and those records and
  writes a proposal; an administrator approves its exact hash (policy pseudo tool
  `planners.routing.approve`) and the rules become a new immutable version that can be rolled back to
  any earlier one or none. An opt-in online bandit (`ai.planners.learning.bandit`, Thompson sampling or
  UCB) exploits and explores within a capped share of choices, only among the candidates the stage
  already allows, with a kill switch in the state store and a guard that sets it. New
  `ai.planners.learning.*` keys; `choice.by` gains `learned`, `bandit` and `explore`;
  `tests/ai/test_planner_learning.py`, `tests/test_planner_routing_page.py`.
- **A translation framework for the console, English only** (Roadmap L14; `sajha/web/i18n.py`;
  [Architecture](docs/architecture/Architecture.md) §10, "Languages"): the console's own words are
  gettext messages (`{{ _() }}` / `{% trans %}` through Jinja's i18n extension, each page's "About this
  page" line, the help catalog's card titles through `tr()`, and `_t()` / `_nt()` in page scripts from
  the new `static/js/i18n.js`), and `sajha/web/locale/sajha.pot` holds them all. Only English ships (by
  the owner's decision there is no other catalog and no language picker), so every page renders in
  English exactly as before. Adding a language later is a catalog, not a code change:
  `scripts/i18n.py` extracts, starts, updates, compiles and checks catalogs (needs Babel; the server
  does not), and a compiled catalog would be chosen by the browser's `Accept-Language`, then the new
  `console.default_language` (default `en`). `tests/test_console_languages.py` checks the `.pot` is
  current, the English fallback, the absence of a picker, and the framework with a temporary catalog.
- **A container per federated stdio server** (Roadmap L9; `sajha/federation/container.py`;
  [Federation](docs/architecture/Federation.md#stdio-isolation)): a stdio upstream now runs in its own
  container per connection, launched through the sandbox's `docker` backend with its network policy
  (`--network none` unless `container.network: allowlist`), a read-only root, read-only
  `container.mounts` (SAJHA's own folders, the home folder and the docker socket refused), memory, CPU
  and process limits capped by `sandbox.max`, every capability dropped and the `nobody` user; secrets
  passed by name only. The container is removed with its connection; when it ends, the reconnect loop
  starts a new one with backoff; orphans of a dead SAJHA process are removed. New per-upstream
  `isolation` (`container` | `none`) and `container` (`image`, `mounts`, `memory_mb`, `cpus`,
  `max_processes`, `network`, `allow_hosts`, `user`, `tmpfs_mb`), also in the mcpServers file, and
  `federation.container.image`. Notices `federation.stdio_isolation:<upstream>` and
  `federation.stdio_unconfined:<upstream>`.
- **Signed plugins and the plugin catalog** (Roadmap L12; `sajha/core/plugin_signing.py`,
  `sajha/core/plugin_catalog.py`; [Security Model](docs/security/Security%20Model.md#plugins)): Ed25519
  publisher signatures (`plugin.sig`, over every file's SHA-256) verified at load against
  `plugins.trusted_keys` and `plugins.trusted_keys_dir`; a tampered plugin is always refused, an
  unsigned or untrusted one loads only while `plugins.allow_unsigned` (default `true`) with the warning
  notice `plugins.unsigned:<name>`. `python -m sajha.core.plugin_signing keygen | sign | verify | pack`
  for publishers. The admin **Plugin catalog** page (`/admin/plugins/catalog`) lists the packages of
  `plugins.catalog.sources` (folders, `storage:<prefix>`, remote indexes through the outbound fetch
  guard) with their verdicts and installs a trusted one through the review-and-approve gate of Describe
  a tool: a review bound to the package hash, explicit approval, the package re-verified at install, and
  the policy engine's `studio.deploy` (`kind: plugin`); a failed upgrade restores the old version;
  reviews and installs are audited.
- **Documents from connected accounts as RAG sources** (Roadmap X8; `sajha/ai/rag/personal.py`,
  `account_sources.py`, `personal_tool.py`;
  [Intelligence Layer](docs/architecture/Intelligence%20Layer.md#documents-from-connected-accounts)):
  `ai.rag.accounts.sources` names Google Drive, OneDrive, SharePoint, GitHub and Confluence sources
  that are listed and read with each user's own linked token and indexed per user, in a store of its
  own. A search covers only the caller's own passages from sources whose link is active; a removed
  link or lost access (403/404) removes that user's passages. Sync is incremental by each file's
  change token (unchanged files are not downloaded, deleted files are removed; an unchanged GitHub
  commit skips the listing), runs in the background when a search finds a source stale, and can sweep
  every linked user (`sync_interval_seconds`). New tool `sajha_search_my_docs` and routes
  `GET /api/ai/docs/mine`, `POST /api/ai/docs/mine/sync`, `POST /api/ai/docs/mine/search`.
- **Optional OCR** (`ai.rag.ocr`; `sajha/ai/rag/ocr.py`): scanned PDFs, and images from
  connected-account sources, are read by OCR when an engine is installed (`rapidocr-onnxruntime`, or
  `pytesseract` with `tesseract`); without one they are refused with a message naming the packages.
- **Weaviate and Chroma data connectors** (Roadmap X10; `sajha/connectors/vector_weaviate.py`,
  `vector_chroma.py`; [Data Connectors](docs/architecture/Data%20Connectors.md#9-vector-databases-and-search-engines)):
  two new search kinds with the same allowlist, equality filters and masking as Qdrant, over their
  HTTP APIs (no SDK needed). Weaviate searches by `nearVector` (named vectors supported) or `bm25`,
  with filters checked against the class's properties; Chroma supports its v2 and v1 APIs, tenants
  and databases.
- **Sandbox egress proxy** (Roadmap L6; `sajha/sandbox/egress.py`;
  [Sandbox](docs/architecture/Sandbox.md#network-allowlist)): a tool whose sandbox policy says
  `network: allowlist` no longer has direct network. It gets its own network namespace with only a
  loopback interface (`subprocess`, `bwrap`, `nsjail`; `--network none` on `docker`), and a per-run
  HTTP CONNECT and forward proxy on a Unix socket, reached through a bridge the runner starts on the
  sandbox's loopback, is its only way out (`HTTP_PROXY`/`HTTPS_PROXY` are set). The proxy admits only
  the listed `host:port` and refuses cloud metadata, link-local, loopback, multicast, reserved and (by
  default) private addresses with the outbound guard's rule; it resolves names itself and connects to
  the address it checked. Every allowed and denied connection is a `sandbox.egress` audit record and
  counts in `sajha_sandbox_egress_total`. A long-lived container (a federated stdio upstream)
  gets the same proxy through the docker backend's `network_args(policy, name)`: it joins a loopback-only
  bridge sidecar, and both end with it. New keys `sandbox.egress.*`; `GET /api/sandbox/status`
  reports them.
- **Warm container pool for the docker sandbox backend** (Roadmap L6; `sajha/sandbox/pool.py`;
  [Sandbox](docs/architecture/Sandbox.md#warm-container-pool)): `sandbox.docker.pool.size` containers
  started ahead with the per-call confinement; a call runs with `docker exec`; afterwards the container
  is replaced (`reset: recreate`, default) or reset and the reset verified (`reuse`: processes killed,
  `/work`, `/tmp`, `/dev/shm` and SysV IPC emptied; replaced after `max_uses` calls or a failed reset,
  timeout or overflow). Bounded size, background refill, health checks, stale-container cleanup,
  metrics `sajha_sandbox_pool_containers` and `sajha_sandbox_pool_events_total`, and per-pool status.
- **Provider packs** (Roadmap L11; `sajha/packs/`, `sajha/accounts/presets.py`, `sajha/routes/packs_routes.py`;
  [Connected Accounts §11](docs/architecture/Connected%20Accounts.md#11-provider-packs)): a pack is a
  connected-account preset plus a reviewed API Import of the service's OpenAPI spec, bundled with the pack
  (never fetched at install) with its licence and a recorded SHA-256. Installing goes through the
  review-and-approve gate of Describe a tool: a plan with a review hash (the provider as it would be built,
  the redirect URI to register, each operation as API Import plans it, policy preview), explicit approval,
  the same hash on install, and the policy engine's `studio.deploy` (`kind: pack`); a pack whose API is not
  on its provider's `api_hosts` is refused. Admin API `/api/admin/packs` and `python -m sajha.packs list |
  show | plan | install | uninstall`. Bundled packs: GitHub (MIT), Slack (MIT) and Box (Apache-2.0), each
  an excerpt of the vendor's published spec. Presets live in `config/accounts/provider_presets/<id>.json` (storage
  backend; the YAML overrides them) and every worker's provider registry picks a new one up within seconds.
  New key `packs.dirs`.
- **Cassettes for more transports** (Roadmap L5; `sajha/quality/cassette_transports.py`;
  [Tool Quality §2.3](docs/architecture/Tool%20Quality.md#23-recorded-fixtures-cassettes)): urllib3 (and so
  botocore, the AWS SDK's transport), aiohttp (OpenBB providers) and curl_cffi (yfinance) are recorded and
  replayed like urllib, requests and httpx; a request made inside another intercepted client is recorded once.
- **Model-graded eval checks** (Roadmap L5; `sajha/quality/judge.py`;
  [Tool Quality §5](docs/architecture/Tool%20Quality.md#5-evals-for-ask-sajha)): a `graded` answer check
  (criterion, `min_score`, `model`) scored 1-5 by a grader reached only through `llm_factory().model(alias)`;
  off by default (skipped, not failed) unless `quality.evals.graded_checks` or `python -m sajha.quality eval
  --graded`; deterministic on the mock provider. New keys `quality.evals.graded_checks`,
  `quality.evals.grader_model`.
- **SharePoint large uploads and the delegated grant** (Roadmap L7; `sajha/tools/impl/sharepoint_upload.py`;
  [SharePoint Tool Reference Guide](docs/tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md#large-uploads)):
  files over 4 MB go through a Graph upload session (chunks in 320 KiB multiples, no token on the upload URL,
  retries resumed from the session's expected ranges, an interrupted upload resumable with
  `resume_upload_url`, cancelled on refusal), capped by the tool config's `max_upload_bytes`; `source_path`
  reads a file under the tool config's `upload_roots`. `authentication.type: delegated` calls Graph as the
  caller with their connected Microsoft account (refresh once on 401, then "reconnect").
- **Web crawler: JavaScript rendering and PDF text** (Roadmap L7; `sajha/tools/impl/webcrawler_render.py`;
  [Web Crawler Tool Reference Guide](docs/tools/search/Web%20Crawler%20Tool%20Reference%20Guide.md#javascript-rendering)):
  `render_js` on crawl_url, extract_content, extract_links, extract_metadata and get_page_info runs the page in
  headless Chromium (Playwright, optional; off unless `tools.webcrawler.javascript.enabled`) with every
  request the browser makes fetched through the outbound fetch guard and fulfilled by SAJHA; request, byte,
  time, concurrency and page limits (`tools.webcrawler.javascript.*`). PDF answers are read as text (title,
  page text, link annotations) and plain text as is.
- **SAJHA Net: tasks held at the host** (Roadmap L19; `sajha/net/integration/tasks.py`, `sajha/net/routing.py`;
  [SAJHA Net](docs/architecture/SAJHA%20Net.md#9-what-happens-on-a-call) §9, protocol §15.6): a client that
  runs a remote tool as a task now gets a task held by the host that runs the tool, for the user it
  resolved and the sending server, in the host's task record store and outside the hop's deadline. The
  home's task names the host's task and follows it with signed `tasks/get`, `tasks/update` (answers
  checked by residency) and `tasks/cancel`, screens the result and checks its residency on arrival, and
  survives a restart of the home. SAJHA lists the feature `tasks`; proxies of hosts that list it are
  offered with `execution.taskSupport: optional`. A host that does not list `tasks` is served as before
  (the home's task wraps the call). `sajhanet.tasks.enabled` (default true). The task store
  (`sajha/core/mcp_tasks.py`) gained remote tasks and runs outside an event loop.
- **SAJHA Net: the rest of the design** (Roadmap L16; [SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.5):
  forwarding on the 2025-11-25 era to a host that refuses 2026-07-28, on one session per net and host that
  the host binds to the participant that opened it (another member presenting it gets
  `404 session_invalid`; CALL-12); the `visibility` feature (`POST /sajhanet/v1/catalog/visibility`, CAT-05,
  also checked by the conformance runner), with which a home leaves out of `tools/list` the proxies the
  host says the caller may not call (`sajhanet.visibility.*`); mutual TLS (`sajhanet.mtls: client|require`,
  `sajhanet.mtls_client_cert_header`; `sajha/net/integration/mtls.py`); discovery sources for joining
  (`sajhanet.discovery`: DNS SRV, a Kubernetes headless Service, a registry; `sajha/net/discovery.py`);
  the net view in snapshots (`net_members`, `net_proxies`, `net_keys`, compared by
  `python -m sajha.snapshots diff`, never restored); sponsored members with the `assertion` and
  `token_exchange` identities (the assertion or token names the sponsored member, which serves its own token
  endpoint); an approval flow for residency rules (`effect: require_approval` on arguments leaving the home
  refuses `approval_required` with a pending policy approval that lets that exact call through once); LLM
  tools that record only the names of the tools they used have remote results masked in memory as if they
  had passed their steps; per-peer breakers and rate limits in the state store across workers
  (`sajhanet.peer.shared`, default `auto`); and opt-in caching of read-only remote results per caller
  (`sajhanet.cache.ttl_seconds`, default off).

### Changed

- **The navbar wordmark** is set in Cinzel (Roman capitals), bundled in `sajha/web/static/fonts/` with its SIL Open
  Font License (the console only loads fonts it serves itself).

- **stdio upstreams no longer start unconfined by default.** With `federation.allow_stdio: true`, a
  stdio upstream without `isolation` runs in a container when docker answers and is not started when it
  does not (notice `federation.stdio_isolation:<upstream>`). Set `isolation: none` to keep the old
  subprocess behaviour (with a warning notice), or give it a `container.image` that contains the server;
  the mcpServers templates under `config/mcp_servers/` show both.
- **The document index embeds a document before writing it**: each document's passages are embedded
  first and then written in one short store transaction, so no database connection (pgvector) or
  write lock (sqlite_vec) is held while a model is called. A build still holds one document's
  passages at a time, never the corpus.
- **Allowlisted sandbox tools go through the egress proxy by default.** A tool that opened raw sockets
  to an allowlisted host must now tunnel through `CONNECT`; `sandbox.egress.mode: direct` restores the
  earlier library-level check. On the `subprocess` backend the proxy needs unprivileged user
  namespaces; without them an allowlisted tool is refused rather than given direct network. A WASM
  backend is still planned (Roadmap L6).
- **SAJHA Net members list `tasks` and `visibility`** in their member records and `io.sajha/net` extension
  (protocol §6.2), and `tasks/get`, `tasks/update` and `tasks/cancel` at the 2026-07-28 endpoint now run off
  the event loop (a task held by another server is read through it).

### Fixed

- **Security: a user's connected-account token could reach a host outside its provider's `api_hosts`
  through API Import** (`sajha/api_import/service.py`, `executor.py`;
  [API Import §4](docs/architecture/API%20Import.md#4-servers-authentication-limits)). An imported operation
  bound to a connected account sent the caller's token to whatever base URL the import named. The preview
  now warns, test calls and deploys are refused with an error naming the allowed hosts, and the executor
  checks every request's URL again before it adds the token (so a config written by hand is refused too).
- **Security: credentials followed redirects to another origin** (`sajha/api_import/fetch.py`): a GET
  redirected to another scheme, host or port no longer carries `Authorization`, `Cookie` or
  `Proxy-Authorization` (API Import calls and the outbound fetch guard's tools share this client).


## v8.12.0 (October 2026) — platform depth, operations and scale: protocol gaps closed, federation complete and at gateway scale, no freeze under load, PostgreSQL verified

### Added

- **Federation at gateway scale** (Roadmap L10; `sajha/federation/scale.py`;
  [Federation](docs/architecture/Federation.md#gateway-scale)): connection pools per upstream
  (`federation.pool_size` or per upstream `pool_size`, default 1: one primary connection runs discovery,
  the others carry `tools/call`, each call taking the least busy connected one); a bound on calls in
  flight per upstream (`max_in_flight`, default no limit) with a first-come-first-served queue
  (`max_queue`, `federation.queue_timeout_seconds`), over which a call is refused at once with a
  retryable "at capacity" error that sends nothing and spares the breaker; replicas (`urls`: more
  endpoints of one upstream) chosen by health, with failover and a new primary when the primary
  connection is down; and shared upstream health: every worker publishes its view of each upstream to
  the state store (`fed:health:<upstream>:<worker>`, `federation.health.*`), the admin page and status
  show the cluster-wide view, and a breaker one worker opened opens the others' (each then probes on its
  own; `federation.health.follow_peer_breakers`). New metrics `sajha_federation_upstream_in_flight`,
  `_waiting`, `_shed_total`, `sajha_federation_pool_connections_connected` and
  `sajha_federation_cluster_*` ([Observability](docs/architecture/Observability.md#22-the-metrics)).
  `tools/bench/bench_federation.py` measures proxied calls and shedding.
- **API Import: multipart and binary request bodies** (Roadmap L4; `sajha/api_import/bodies.py`;
  [API Import](docs/architecture/API%20Import.md) §3, §5.1): operations with a `multipart/form-data` or
  binary body (`application/octet-stream`, or another media type whose schema is a binary string) are now
  imported instead of flagged. A file argument is a file value: `content_base64`, `text` or `path` (a
  storage-backend file under `api_import.file_roots`, empty by default; `{user}` in a root is the caller),
  with an optional `filename` and `content_type`. The whole body is capped by `api_import.max_upload_bytes`
  and refused before any connection when larger; the request goes through the SSRF guard.
- **API Import: opt-in pagination following** (Roadmap L4; `sajha/api_import/paging.py`;
  [API Import](docs/architecture/API%20Import.md) §5.2): per GET operation (the preview's **Pages** column, or
  the import request's `pagination` object), modes `link`, `next_url`, `cursor`, `page` and `offset`, with a
  page cap and a row cap per operation under `api_import.pagination_max_pages` and
  `api_import.pagination_max_items`. Off by default; kept in the import record. A next URL is checked by the
  SSRF guard and must keep the first request's origin before it is followed; the answer reports `pages`,
  `items`, `truncated`, `stopped` and how to continue.
- **API Import: Swagger 2.0 remote `$ref`** (Roadmap L4; `swagger2.bundle`): definitions, parameters and
  responses in other documents are fetched through the SSRF guard (bounded by `api_import.max_ref_documents`
  and `api_import.max_spec_bytes`) and bundled into the spec before conversion.
- **MCP: task status notifications** (Roadmap X12; `sajha/core/mcp_tasks.py`, `sajha/core/mcp_modern.py`;
  [MCP Protocol Guide](docs/protocol/MCP%20Protocol%20Guide.md) §2): a 2026-07-28 `subscriptions/listen` may name
  `taskIds` (SEP-2663; the client must declare the tasks extension, else `-32021`). The acknowledgement lists the
  caller's tasks among them, and each gets `notifications/tasks` with the full task (what `tasks/get` returns):
  its current state, then one per change. Task changes travel on the change bus, so a listen stream on one
  worker hears about a task on another when the state store is shared.
- **MCP: `list_changed` on 2025-11-25 Streamable HTTP sessions** (Roadmap X12; `sajha/routes/mcp_routes.py`):
  `GET /mcp` with a live `Mcp-Session-Id` and `Accept: text/event-stream` opens the session's server-to-client
  stream, which carries `notifications/{tools,prompts,resources}/list_changed` from the change bus. One per
  session (409 for a second), and it ends with the session. `initialize` on this transport now advertises
  `listChanged: true` (it was `false`, and that GET was 405).
- **Federation, complete** (Roadmap L2; `sajha/federation/`, `sajha/federation/tasks.py`, `sajha/federation/relay.py`;
  [Federation](docs/architecture/Federation.md) §4, §7, §12): a proxied MCP server's other features are carried
  through with the same namespacing, approval and access rules. Resource templates (approval kind `template`,
  listed as `sajha-federation://<id>/<template>`, expansions read from the upstream); `completion/complete` for
  proxied prompts and templates, answered by the upstream; `resources/subscribe` (2025-11-25 sessions) and
  `resourceSubscriptions` (2026-07-28 `subscriptions/listen`) subscribe at the upstream, whose
  `notifications/resources/updated` come back under SAJHA's URI; upstream tasks (SAJHA declares the tasks
  extension to 2026-07-28 upstreams, follows a task to its end, sends `tasks/cancel` when its own call is
  cancelled, and keeps `execution.taskSupport` so clients can make the call a SAJHA task); MCP Apps views of proxied
  tools as `ui://sajha-federation/<id>/...`, served without the upstream's CSP domains or permissions; and a
  2025-11-25 upstream's `sampling/createMessage`, `elicitation/create` and `roots/list` relayed to a 2025-11-25
  caller that declared the capability and took a streamed response (on a connection opened for that call), or
  refused with an error that says why (they were declined before).
- **MCP: `resources/updated` on 2025-11-25 Streamable HTTP sessions** (`sajha/routes/mcp_routes.py`,
  `sajha/core/mcp_handler.py`; [MCP 2025-11-25 Compliance](docs/protocol/MCP%202025-11-25%20Compliance.md) §2):
  `resources/subscribe` records the URI with the session, and `notifications/resources/updated` for it travels on
  the session's `GET /mcp` stream; `initialize` on this transport now advertises `resources.subscribe: true`.
- **OAuth: RFC 7662 token introspection for external issuers** (Roadmap X12; `sajha/auth/oauth/introspection.py`;
  [OAuth Guide](docs/protocol/OAuth%20Guide.md) §5): `mcp.auth.external.introspection.mode` `opaque` (tokens that
  are not JWTs) or `always`. The endpoint is configured or discovered from the issuer metadata, and SAJHA
  authenticates with `client_id` and a secret from `SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CLIENT_SECRET`. It
  checks `active`, `iss`, `exp`, `nbf` and `aud` (required unless `require_audience: false`), fails closed, and
  caches answers per process for `cache_seconds` (never past `exp`; failures are not cached).
- **OAuth: CORS for browser-based clients** (Roadmap X12; `sajha/auth/oauth/cors.py`): origins in
  `mcp.auth.cors.allowed_origins` (default none; `*` for any) get `Access-Control-Allow-Origin` and answered
  pre-flights on the protected-resource and authorization-server metadata, `/oauth/jwks`, `/oauth/token` and
  `/oauth/register`, never with credentials. `/oauth/authorize` gets none.
- **LLM providers: the last synchronous paths** (Roadmap X9; [Intelligence Layer](docs/architecture/Intelligence%20Layer.md)
  §3): embeddings on the HTTP providers (OpenAI and the compatible presets, Azure OpenAI, Mistral, Cohere,
  Gemini, Ollama) are natively async on `httpx.AsyncClient` (`HTTPEmbeddingModel` in `sajha/ai/llm/adapter.py`,
  exported by the SPI), and the governed `aembeddings_create` / `aembed` no longer use a worker thread. Bedrock's
  async chat, stream and embeddings are native when `aiobotocore` is installed (`pip install aiobotocore`, or
  aioboto3), one client per event loop, and fall back to boto3 in a worker thread otherwise; the module stays
  importable without either. Bedrock now sends `reasoning_effort` in `additionalModelRequestFields` for
  Anthropic Claude (`output_config.effort`) and Amazon Nova 2 (`reasoningConfig`) models that declare it, and
  refuses it for other families with an error naming the ones that take it.
- **Proxied servers: `auth.type: service_with_user`** (Roadmap L20;
  [Federation](docs/architecture/Federation.md#a-shared-identity-naming-the-user-service_with_user)): one shared
  service credential (`auth.service`) with the calling SAJHA user named in an audit header the vendor records
  (`auth.user_header`, default `X-SAJHA-User`; `auth.user_format`, default `{user}`). Discovery uses the service
  identity alone; anonymous callers are refused; a session-based upstream gets a session per user; the audit
  names the mode and the user.
- **Policy: approval for proxied writes, shipped and enabled** (Roadmap L20; `config/policies/20-proxied-writes.yaml`;
  [Policy and Audit](docs/architecture/Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes) §5.1): a
  proxied MCP server's tool without `readOnlyHint: true` now needs approval (`approver: caller`: the person at the
  client confirms where it can, else an administrator). This changes behaviour for existing deployments with
  proxied servers; set `enabled: false` in the file to keep the old behaviour. The rule language gains
  `match.proxied` and conditions on annotations (`annotations: {readOnlyHint: {ne: true}}`).
- **Ask SAJHA over MCP: confirmation through the client** (Roadmap X7; `sajha/ai/llm_tools/confirmation.py`;
  [Intelligence Layer](docs/architecture/Intelligence%20Layer.md#sajha_ask-mcp) §6): when `sajha_ask` (any
  answer-mode LLM tool that is the MCP call's own tool) wants to run a destructive tool, or a policy rule asks the
  caller to approve a call, the user is asked through the client. On 2026-07-28 the call answers
  `input_required` with one form `elicitation/create` per pending call (key `sajha_confirm_<fingerprint>`,
  boolean `confirm`); the retry runs the call when confirmed and tells the model the user declined otherwise. On
  2025-11-25 a session that declared form-mode elicitation and accepts `text/event-stream` gets the same request
  on the call's SSE stream. Clients without form elicitation still get `needs_confirmation` and `confirm`.
- **Ask SAJHA: trimming on `ContextTooLong`** (Roadmap X7; [Intelligence Layer](docs/architecture/Intelligence%20Layer.md)
  §6): a model call carrying earlier conversation turns that is too long for the model drops the oldest turn and
  asks the same model again before falling back to the alias's next (larger) model. Each trim is a
  `context_trimmed` event and an entry of `context_trims` in the result, the `ai_ask` audit record and the LLM
  tool's `llm_tool_run` record.
- **Workflows: `foreach` bodies that are graphs** (Roadmap L3; `sajha/workflows/model.py`, `engine.py`;
  [Workflows](docs/architecture/Workflows.md) §2): `do: {steps: [...], output: ..., on_error: ...}` runs a small
  graph of `tool`, `composite`, `ask`, `condition` and `wait` steps per item, in dependency order, with `$item`,
  `$index` and `$steps` (the run's steps and this item's), condition branches, `join`, `when` and per-step
  `on_error`. Bounded by `max_items` and `parallel` as before plus `workflows.foreach_max_body_steps` (default
  20). A body cannot park the run (no `approval`; a `wait` at most `workflows.inline_wait_seconds`).
- **Workflows: change-bus event triggers on every worker** (Roadmap L3; `sajha/core/change_bus.py`,
  `sajha/workflows/service.py`; [Workflows](docs/architecture/Workflows.md) §4,
  [Scaling and State](docs/architecture/Scaling%20and%20State.md) §4.5): with a shared state store the workflow
  service hears events relayed from other workers too (`ChangeBus.add_listener(fn, remote=True)`); every event
  carries an id, and a worker claims `wf:evclaim:<workflow>:<trigger>:<id>` before firing, so one event starts
  one run cluster-wide.
- **Workflows: cron catch-up** (Roadmap L3; [Workflows](docs/architecture/Workflows.md) §4): a cron trigger (or
  the whole definition) may set `catch_up: last` (one run for the latest slot missed while no worker ran) or
  `all` (one per missed slot, oldest first, at most `catch_up_max`, default 10), counted from the trigger's
  newest run. The default, `none`, is unchanged.
- **Storage: push-based reload** (Roadmap X11; `sajha/core/storage_events.py`;
  [Storage Guide](docs/getting-started/Storage%20Guide.md#push-based-reload)): with `storage.events.provider`
  (`sqs`, `azure_queue`, `pubsub` or `auto`) a listener reads the bucket's event notifications (S3 to SQS,
  through SNS or EventBridge; Azure Event Grid to a Storage Queue; GCS to a Pub/Sub pull subscription) and hands
  each changed path to the object-store sync manager, which fires the same reload callbacks, and so the same
  change-bus events, as its poll. Polling stays as the fallback and runs every
  `storage.events.healthy_poll_interval` seconds while the listener is healthy. With a shared state store the
  receiving worker relays the paths to the others. Workflow file triggers poll at the next tick on an event.
  Each SDK is imported lazily; a missing one or incomplete settings raise the info notice
  `storage.events:<provider>`, never a start-up error. The Dockerfile's `azure` and `gcs` extras add the queue
  SDKs.
- **Storage, finished** (Roadmap L1; [Storage Guide](docs/getting-started/Storage%20Guide.md)): a DuckDB data
  directory written `storage://<prefix>` is read through the storage backend, staged per load into a temporary
  directory within `data.duckdb.stage_max_file_mb` and `data.duckdb.stage_max_total_mb`; on a cloud backend
  Studio-generated modules and scripts are published to the bucket (`studio/modules/`, `config/scripts/`) with
  the tool JSON and materialised locally before the tool loads (`sajha/core/storage_modules.py`), and plugins
  are mirrored from the bucket, so no shared file system is needed for them; storage contract tests for moto,
  MinIO, Azurite and fake-gcs-server (`tests/test_storage_emulators.py`, run when available) with a CI recipe; a
  guard against direct `config/` IO in the migrated subsystems; pod identity for the bucket on EKS, AKS and GKE
  in [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md#bucket-access-on-eks-aks-and-gke).
- **A load harness with published numbers** (Roadmap X13; `tools/bench/bench.py`;
  [Scaling and State §9](docs/architecture/Scaling%20and%20State.md#9-measured-performance)): starts
  `run_sajha_web.py` on each `state.backend` (memory; database on a scratch SQLite file; redis when a server
  answers, otherwise skipped with a note) at one and several workers, and drives `/mcp` on both eras
  (2026-07-28 stateless; 2025-11-25 with one session per client) with `tools/list` and `tools/call` on a local
  calculator, new arguments every call so the cache never answers. It reports p50, p95 and p99 latency,
  throughput and errors as JSON and a markdown table, with the CPU, cores, RAM, OS, Python, SAJHA version and
  commit. Standard library and httpx only. One run's numbers, with the machine, date and load, are in Scaling
  and State; the deck may cite only those ([deck guide](tools/deck/GUIDE.md)).
- **Service level objectives and failure tests** (Roadmap X14;
  [Observability §6](docs/architecture/Observability.md#6-service-level-objectives)): availability of `/mcp`
  (99.9% not 5xx), latency of in-process tool calls (99% within 100 ms) and their errors (under 1%), each over
  30 days on existing metrics, with a `sajha-slo` group in `deployment/observability/sajha-alerts.yml` (fast
  and slow error-budget burn on availability; latency and error rules). `tests/test_failure_behaviour.py`
  (marker `failure`) asserts the failure behaviour of
  [Scaling and State §7](docs/architecture/Scaling%20and%20State.md#7-failure-behaviour-and-limits): an
  unreachable redis or database store stops start-up; Redis lost at run time fails requests that touch
  shared state with HTTP 500, `/health` reports it, nothing falls back and service resumes when it is back;
  the database store raises while its database is gone and keeps its rows; a worker killed with SIGKILL
  mid-task leaves the task `failed` with -32603 on the other worker once its heartbeat is gone, never re-run;
  a broken federated upstream keeps its tools listed, fails fast, opens its breaker and closes it after the
  upstream returns.
- **Database connection pool: fail fast, sized, visible** ([Scaling and State
  §7](docs/architecture/Scaling%20and%20State.md#7-failure-behaviour-and-limits)): new keys
  `db.pool.max_overflow` (default -1, as many as `db.pool.size`) and `db.pool.timeout_seconds` (default 5;
  validated at start-up). A request that finds no free connection within the timeout is answered at once with
  HTTP 503 and `Retry-After: 1` (on `/mcp` a JSON-RPC error, code -32000, `data.reason: db_pool_exhausted`,
  `retryable: true`), never a hang and never a 401. SQLite files get the same counting pool as PostgreSQL, with
  `synchronous=NORMAL` added to WAL. New metrics `sajha_db_pool_size`, `sajha_db_pool_max_overflow`,
  `sajha_db_pool_checked_out`, `sajha_db_pool_overflow_in_use`, `sajha_db_pool_waiting` and
  `sajha_db_pool_exhausted_total`, the alert rule `SajhaDbPoolExhausted`, a "Database Connection Pool" panel per
  worker on the System monitor page (`db_pool` in `/api/admin/system-monitor`: database type, URL with the
  password hidden, size, overflow, checked out, waiting, checkout timeouts). With `state.backend: database` the
  state store opens its own small pool (`state.database.pool_size`, default 3). `db.type` and the connection
  keys also take the short `DB_*` environment names. `session_scope()` in `sajha/db/engine.py` is the one way
  for services and jobs to open a session (always closed, rolled back on error).
- **Load harness: high concurrency with a pass/fail check** (`tools/bench/bench.py --scenario highconc`):
  `tools/call` on both eras at 64, 256 and 512 requests in flight, at 1 and 4 workers on SQLite and on
  PostgreSQL when `SAJHA_BENCH_PG_URL` is set (a scratch database with SAJHA's schema, dropped afterwards; the
  URL is never printed), `/health` probed throughout, and a verdict: no request unanswered or slower than the
  bound, `/health` within its bound, errors (503 shedding excluded) under the threshold. Guards in the suite:
  `tests/test_db_session_hold.py` (an AST check that fails when an async route holds a database session across
  an `await`), `tests/test_db_pool.py` (503 on a dry pool; a raising tool, a route raising after a database
  read and a client disconnecting mid-request all return their connection) and a bounded run of 128
  concurrent calls against one worker with a two-connection pool (`failure` marker).

### Changed

- **Ask SAJHA: freshness and agreement in the confidence score** (Roadmap X7;
  [Intelligence Layer](docs/architecture/Intelligence%20Layer.md) §6): each step records its result's as-of
  date (`as_of`), and a cited result older than a day lowers the score (0.95 to a week, 0.9 to 30 days, 0.8 to a
  year, 0.7 beyond) unless the question asked for that date; a reconciliation with differences beyond tolerance
  multiplies it by 0.8; figures of the answer found in the results of two or more different tools raise it by up
  to a quarter of the gap to 1. Scores of existing asks can change.

- **PostgreSQL test path** ([Database Setup](docs/getting-started/Database%20Setup.md) section 7): with
  `SAJHA_TEST_PG_URL` set to a disposable database, `tests/test_postgresql.py` runs the repositories (DAOs,
  workflow store, connected-accounts vault, conversation memory, audit chain) and `tests/test_state_store.py`
  runs the state store's contract (`database_pg`) on PostgreSQL, each in a private schema built from the
  schema files; without it they skip. CI sets it. Database Setup now gives the connection settings that
  switch SAJHA to PostgreSQL by environment alone, and notes that an unset `db.name` is `sajha_mcp`.

### Fixed

- **`/mcp` stalled under concurrent calls** (found by the load harness, Roadmap X13): an MCP request kept
  its database connection from authentication until its response ended, so with as many calls in flight as
  the pool has connections (15 on SQLite; twice `db.pool.size` on PostgreSQL) the next request's
  authentication blocked the event loop on the pool for its 30 s timeout, and every request on that worker
  waited. The request's session now gives its connection back once the caller's identity and tool policy are
  known (`AuthContext.to_legacy_session`), before the call runs or a stream opens.
- **Other routes held a database connection across slow work** (the same pool exhaustion as `/mcp`): every
  route signed in through `get_current_user` kept the connection its authentication used until the response
  ended, including streams (the notices stream of every open console tab, Ask SAJHA's step stream); so did the
  OpenAI-compatible endpoint (`/v1/*`) through its model call or stream, the REST tool endpoint
  (`/api/tools/execute`) and A2A (`tasks/send`) through the tool call, and the legacy `GET /mcp/sse` stream for
  its whole life. Each now gives the connection back (`release_session`, `AuthContext.release_db`) before the
  slow part and right after its own writes, so an async route never holds one across an `await`. A2A ran its
  tool on the event loop, and `/api/ai/complete`, the provider health check and the tool resolver made their
  model or network calls there; they now run in the thread pool, so `/health` and other requests answer while
  they wait. A client that disconnects before its request body arrives is logged at INFO ("Client
  disconnected"), no longer as an ERROR "Internal server error".
- **Database work on the event loop**: MCP authentication (`authorize_mcp`: the key or token lookup and the
  caller's tool policy), the WebSocket transport's authentication, `/oauth/authorize`, `/oauth/token` (with
  its password check) and the SSO callback ran their queries on the event loop, so a slow or busy database
  stalled every request of the worker; they now run in the thread pool. The contract-test and shell routes ran
  the tool or the code there too, and the System monitor API took its half-second CPU sample there; routes
  whose whole body is database work (console pages, reports, key and user lists) are now sync handlers.
  `AuthContext.has_permission` reads permissions already loaded instead of querying. Five API-key routes read
  their request body after a database lookup, holding a connection while the body arrived; they read it first.
  The audit log writer (`sajha/core/audit.py`) leaked its session when the write failed.
- **PostgreSQL tests that could not pass on a real server**: `tests/test_db_schema.py` expected four seeded
  roles after `seed.sql` on PostgreSQL (there are five since `llm_author`), and the pgvector cases of
  `tests/ai/test_rag_store_contract.py` errored on a PostgreSQL without the `vector` extension; they now skip
  there. No application code changed: SAJHA ran unchanged on PostgreSQL 17 built by `psql -f` of the two
  schema files ([Database Setup](docs/getting-started/Database%20Setup.md) section 2).

## v8.11.0 (October 2026) — business intelligence and reports: metrics, analysis, charts, report definitions, formats, narration

### Added

- **Reports** (Roadmap L45, L46; `sajha/reports/`, `config/reports/`, tool folder `config/tools/reports/`;
  [Reports](docs/architecture/Reports.md) §2–§4): report definitions in YAML, validated at load (a refused
  file raises the warning notice `reports.definition:<file>`) and re-read when they change; each enabled
  definition is published as a generated `report_<name>` tool. A run calls each section's tool as the
  caller, so tool access, policy, approvals and budgets apply per section, and a section the caller may
  not call shows "not permitted" instead of failing the report. Runs are stored under `data/reports/`
  (the report data with every value, its source and the quantities a narrator may cite, plus the
  rendered files) and are visible only to their runner and administrators. New tools: `report_list`,
  `report_describe`, `report_run`, `report_history`, `report_render` (a past run in another format, no
  tool called again) and `report_compare` (KPI changes; table rows added, removed and changed).
  Formats: Markdown and HTML always; PDF through Playwright and Chromium, XLSX (openpyxl), PPTX
  (python-pptx) and DOCX when installed; every format carries the classification marking and a
  provenance appendix with each source's attribution line. Shipped definitions: `desk_calendar`
  (offline) and `central_bank_watch` (live open data, off until enabled). New keys `reports.*`
  ([Configuration Reference](docs/getting-started/Configuration%20Reference.md#reports)); audit events
  `report.run` and `report.render`.
- **Report narration** (`report_narrate`, `sajha/reports/narrate.py`; [Reports](docs/architecture/Reports.md) §5):
  commentary on a stored run, written by the `reports.narrate_model` alias (empty: `default`) with no tools, then
  checked by the numbers validator against the run's data, with the run's computed comparisons (previous values,
  changes, percent changes and shares) as workspace quantities. Figures match at the precision written and by
  magnitude; dates must be parameters, the run's date or in the data. A draft with unmatched figures gets one
  revision; what still does not match is removed and named in a caveat, the run gets a warning and the audit
  records `report.narrate.rejected`. A text section waiting for commentary receives it, and the run's files are
  rendered again.
- **Reports page** (`/reports/library`, `sajha/routes/report_library_routes.py`): the reports you may run, each with
  Run (the report's tool) and a page with its parameters, your runs (administrators: every run) and their files
  to download (`/api/reports/library/runs/{run_id}/{format}`, as attachments, audited `report.download`).
- **Metrics layer and BI analysis tools** (Roadmap L40, L41 in part; `sajha/bi/`,
  `config/tools/bi/`, `sajha/tools/impl/bi_metric_tools.py`;
  [Business Intelligence](docs/architecture/Business%20Intelligence.md) §2–§4,
  [Business Intelligence Tool Reference Guide](docs/tools/analytics/Business%20Intelligence%20Tool%20Reference%20Guide.md)):
  metric definitions as YAML in `bi.metrics_dir` (`config/bi/metrics`), checked when read (a refused
  file raises the warning notice `bi.metric:<file>`) and re-read when a file changes; a compiler that
  builds one SELECT from the definition (caller values always bound parameters, identifiers only the
  metric's declared columns) and runs it through the source's own path (a data connection's guard,
  allowlist, masking and audit; the DuckDB sandbox; the OLAP semantic layer); `roles` hide a metric.
  Tools: `bi_list_metrics`, `bi_describe_metric`, `bi_query_metric` (grains, cumulative YTD/QTD/MTD,
  rolling), `bi_compare`, `bi_top_n` (Pareto), `bi_crosstab` (margins computed by the source) and
  `bi_explain_change` (contribution analysis; rate and mix effects for ratios). Three sample metrics
  (`net_sales`, `order_count`, `average_order_value`) over the DuckDB sample data. New keys
  `bi.metrics_dir` and `bi.max_rows`; the BI tools ship enabled.
- **Charts and loading tool results (BI, phase 8.4)** (`config/tools/bi/`, `sajha/tools/impl/bi_chart_tools.py`;
  [Business Intelligence §5–§6](docs/architecture/Business%20Intelligence.md#5-charts-and-mcp-apps)):
  `bi_chart` draws rows as `line`, `bar`, `area`, `scatter`, `heatmap`, `waterfall` or `pareto` and returns a
  Vega-Lite-subset spec in `structuredContent`, an SVG rendered in pure Python, and an MCP Apps view
  (`ui://sajha/bi-chart.html`); rows are given, come from a `bi_*` tool called as the caller, or from one
  read-only SELECT over the caller's loaded tables. `bi_load_tool_result` calls any tool as the caller (tool
  access, policy, budgets and audit apply: a tool the caller may not call is refused, and the shipped
  sanctions policy still keeps `sanctions_*` results from a model) and loads its rows into the caller's
  scratch database with provenance and a time to live.

### Changed

- The menu entry for the usage dashboard (`/reports`, unchanged) is now **Usage**; **Reports** is the report library.

## v8.10.0 (October 2026) — open data: calendars, GLEIF, BIS, US Treasury, sanctions screening, FDIC, Wikidata

### Added

- **GLEIF tools** (`config/tools/gleif/`, `sajha/tools/impl/gleif_tools.py`;
  [GLEIF Tool Reference Guide](docs/tools/public-data/GLEIF%20Tool%20Reference%20Guide.md)): `gleif_lookup`
  (by LEI or ISIN), `gleif_search`, `gleif_parents` (direct and ultimate parent, or the reporting
  exception; a 404 there is `not_applicable`, not an error), `gleif_children` and `gleif_isins`. No key;
  CC0.
- **BIS tools** (`config/tools/bis/`, `sajha/tools/impl/bis_tools.py`;
  [BIS Tool Reference Guide](docs/tools/public-data/BIS%20Tool%20Reference%20Guide.md)): `bis_policy_rates`,
  `bis_credit_gap`, `bis_total_credit`, `bis_debt_service_ratio`, `bis_property_prices`,
  `bis_effective_exchange_rates` and `bis_get_series`, a `bis` host profile on the shared SDMX client.
  Every result carries "Source: BIS".
- **Wikidata tools** in the `wikipedia` folder (`sajha/tools/impl/wikidata_tools.py`;
  [Wikipedia Search Tool Reference Guide](docs/tools/search/Wikipedia%20Search%20Tool%20Reference%20Guide.md)):
  `wikidata_search`, `wikidata_entity`, `wikidata_company_identifiers` (LEI, ISINs, tickers, websites)
  and `wikidata_sparql` (read-only SELECT or ASK, row cap, main or scholarly graph).
- **Business calendars** (`config/tools/calendars/`, `sajha/tools/impl/calendars_tools.py`;
  [Calendars Tool Reference Guide](docs/tools/analytics/Calendars%20Tool%20Reference%20Guide.md)): `cal_holidays`,
  `cal_is_business_day`, `cal_business_days_between`, `cal_add_business_days`, `cal_settlement_date` and
  `cal_adjust_date`, computed offline from the MIT `holidays` package for countries (ISO 3166, with
  subdivisions such as `CA-ON`) and exchanges (ISO 10383, such as `XNYS`); a day is a business day only when
  it is one in every named calendar. `holidays` is an optional dependency (`requires`), now in
  `requirements.txt`.
- **US Treasury tools** (`config/tools/us_treasury/`, `sajha/tools/impl/us_treasury_tools.py`;
  [US Treasury Tool Reference Guide](docs/tools/public-data/US%20Treasury%20Tool%20Reference%20Guide.md)):
  `ust_yield_curve` (nominal, real and bill curves from home.treasury.gov), `ust_debt_to_the_penny`,
  `ust_average_interest_rates`, `ust_auctions`, `ust_daily_treasury_statement` and `ust_exchange_rates`
  (Fiscal Data). No key.
- **FDIC BankFind tools** (`config/tools/fdic/`, `sajha/tools/impl/fdic_tools.py`;
  [FDIC Tool Reference Guide](docs/tools/public-data/FDIC%20Tool%20Reference%20Guide.md)): `fdic_institutions`,
  `fdic_financials`, `fdic_failures`, `fdic_locations`, `fdic_history` and `fdic_summary_of_deposits`. No key
  (an optional `FDIC_API_KEY` is sent when set); results cached (`cache_ttl`), and every request takes a slot
  in one state-store window (20 a minute) shared by all workers.
- The calendars, US Treasury and FDIC tools are tested offline (`tests/test_open_data_calendars_treasury_fdic.py`;
  the Treasury and FDIC ones against recorded responses in `tests/fixtures/open_data/`).
- The GLEIF, BIS and Wikidata tools fetch through the outbound fetch guard and are tested against
  responses recorded from the live services (`tests/test_open_data_gleif_bis_wikidata.py`,
  `tests/fixtures/open_data/`).
- **Sanctions screening** (`config/tools/sanctions/`, `sajha/sanctions/`, `sajha/tools/impl/sanctions_tools.py`;
  [Sanctions Tool Reference Guide](docs/tools/public-data/Sanctions%20Tool%20Reference%20Guide.md)):
  `sanctions_screen`, `sanctions_entry`, `sanctions_changes` and `sanctions_lists_status` (read-only and
  closed-world: a local index, so no name leaves the machine), and `sanctions_refresh` (administrators only).
  The official OFAC SDN and consolidated, EU and UK lists are downloaded through the outbound fetch guard into
  `sanctions.data_dir` (default `data/sanctions`, git-ignored; no tables), with the entries added, changed and
  removed at each refresh; `python -m sajha.sanctions refresh|status`. Fuzzy matching normalises names
  (transliteration, case, punctuation, word order, honorifics) and scores token-set similarity plus a phonetic
  key (`threshold` 85). Every result says "screening aid, not a determination". The UN list is refused until
  legal approves. Tested offline against small recorded list files (`tests/test_sanctions.py`).
- **Shipped policy `config/policies/10-sanctions.yaml`** denies `sanctions_*` for the sources `ask` and
  `openai_api`, so screening results never reach Ask SAJHA or an LLM tool. Because of this rule the policy
  engine is active by default.
- **Shipped workflows.** Definitions in `config/workflows/` are installed at start-up when no workflow of that
  name exists, owned by `admin` (`sajha/workflows/shipped.py`); the first is `sanctions_refresh` (daily, 06:30 UTC).

### Fixed

- **Outbound fetches on hosts without IPv6.** The fetch guard sorted a host's addresses as text, so an
  IPv6 address came first and the connection was pinned to it; on a machine without an IPv6 route every
  call to a dual-stack host (FDIC, for one) failed with "Network is unreachable". The resolver's order is
  kept now (`sajha/core/outbound.py`).
- **The `wiki_*` tools go through the outbound fetch guard and proxy** (they used `urllib` directly) and
  send a User-Agent with contact details, which Wikimedia asks for. The `language` argument is checked.
- **Cassettes record the host, not the pinned IP.** A call through the fetch guard was recorded under the
  address it connected to, so a replay never matched; the `wiki_search` cassette is re-recorded.
- **An LLM tool in narrate mode runs its source as a model call** (policy source `ask`), so a policy that
  keeps a tool's results from models, such as the shipped sanctions rule, also covers a narrate source.

## v8.9.0 (October 2026) — quantitative planners: computed numbers with units and lineage, scenarios, data analysis, optimisation

### Upgrading

- **Tool folder names.** A tool folder (a domain) is now named with letters, digits and `_` only, with at
  least one letter. A folder named otherwise (for example with `-`, or digits only) is ignored with every
  tool in it, and the warning notice `tools.bad_folder` names it; rename such a folder with `git mv`.
  Uppercase letters and a leading digit or `_` are now allowed; `-` is not. No shipped folder is affected.

- **`router` and `auto` are now version 1.1.0** and choose the quantitative planners (see Changed).
  Only the new versions ship: a tool or `ai.ask.planner` that pins `router@1.0.0` or `auto@1.0.0`
  no longer resolves, so use the bare name or pin `@1.1.0`. To keep the old routing, set
  `use_quant: false` in a `router` overlay, or replace `auto`'s `candidates` in an overlay.
- **The `optimize` planner needs SciPy** (an optional dependency, in `requirements-qlrisk.txt`);
  without it that planner is not loaded and the info notice `planners.unavailable:optimize` says why.

### Added

- **Quantitative workspace** (`sajha/ai/quant/`; [Quantitative Planners](docs/architecture/Quantitative%20Planners.md)
  §2): quantities that carry a unit, an as-of date, a source and their lineage; units with scales
  and the conversions SAJHA allows (percent, pp, bp and ratio; scales of one currency; days and
  years by `ai.quant.day_count`), refusing cross-currency and level-to-rate conversions; a run's
  workspace, kept in the ask's result as JSON (`workspace`).
- **Operation library** (`sajha/ai/quant/ops.py`): `diff`, `pp`, `pct_change`, `ratio`,
  `bp_spread`, `cagr`, `annualise`, `npv`, `irr`, `weighted_avg`, `sum`, `mean`, `median`,
  `stdev`, `min`, `max`, `regression`, `correlation`, `convert`, `fx_convert` and `round`, each
  with a unit check whose refusal is written for the model; known-answer tests, and tests that
  `npv`, `irr` and `pct_change` agree with `calc_npv`, `calc_irr` and `calc_percentage_change`.
- **Verify check `numbers_in_workspace`** (Planner Reference §9.6): `numbers_in_results` that also
  accepts a figure matching a workspace quantity in any unit it converts to.
- **Reserved planner setting `numbers_check`** (`off`, `warn`, `enforce`): any planner, through its
  file or an overlay, can caveat or revise and then remove the figures in its answer that match no
  tool result or computed quantity. The ask's event stream gets a `numbers_check` event. New keys
  `ai.planners.numbers_check` and `ai.quant.*` (Configuration Reference).
- **Planner `calc_graph`** (Quantitative Planners §3.1, Planner Reference §13.18) and the stage types
  `graph_plan` and `compute` (`sajha/ai/planners_engine/quant_stages.py`, `sajha/ai/quant/graph.py`):
  the model writes a computation graph (tool reads with declared units, constants, named operations)
  instead of an answer. Before anything runs, SAJHA checks it is acyclic, within
  `ai.quant.max_graph_nodes`, uses only offered tools and known operations, has read paths that
  parse and passes the unit checks on its declared units; then the reads run as one parallel step
  (identical calls once, uncapped outputs), the operations in dependency order in the workspace with
  lineage to the calls. A refused graph, or a failed node (which fails the nodes that need it), gets
  one re-plan told the errors; the draft is checked with `numbers_in_workspace`. The stream carries a
  `graph` event per attempt.
- **Planner `estimate_then_compute`** (Quantitative Planners §3.2, Planner Reference §13.19): a rough
  estimate without tools (stage type `estimate`), `calc_graph` as a sub-planner, and the verify
  check `estimate_consistent`; a computed figure more than `settings.tolerance_factor` (default 10)
  from the estimate, or in a unit that does not convert, is re-planned once with both figures named,
  then answered with a caveat giving the estimate.
- **Planner `scenario`** (Quantitative Planners §3.3, Planner Reference §13.20) and the stage types
  `grid`, `grid_call` and `tabulate`: a grid of shocks defined by the tool's settings
  (`settings.grid`) or by the model (validated: the tool offered, the paths, the unit, at most
  `settings.max_points` points with the base, capped by `ai.planners.limits.max_foreach_items`;
  errors go back once, a grid is never truncated), one tool call per point through the existing
  `foreach` (for example `qlrisk_price_trades` with `market_data.shocks`), and a sensitivity table in
  the workspace: base, shocked values, differences and percent changes from the base, columns and a
  table quantity, each with lineage to the calls. A failed point is reported with its reason, never
  filled in. The draft is checked with `numbers_in_workspace`; the stream carries `scenario_grid` and
  `scenario_table` events, and the ask's result and audit entry the table (`scenario_tables`).
- **Tool-result loader and per-user scratch databases** (`sajha/analytics/scratch.py`;
  [Business Intelligence](docs/architecture/Business%20Intelligence.md) §6): a tool result's rows
  become a table in the caller's own DuckDB file under `bi.scratch_dir`, with sanitised names,
  inferred types, provenance (call id, tool, arguments, time loaded) and a time to live, bounded by
  `bi.scratch_max_rows`, `bi.scratch_max_mb` and `bi.scratch_max_minutes` (new keys, Configuration
  Reference `bi`). Its query runs one read-only `SELECT` only, parsed by DuckDB and limited to the
  caller's loaded tables (no other statement, several statements, `ATTACH`, `COPY`, table functions
  such as `read_csv` or other catalogs), on a read-only connection with file access off, with a row
  and a time limit. The `bi_load_tool_result` tool is not built yet.
- **Planner `data_analyst`** (Quantitative Planners §3.4) and the stage types `load_results` and
  `sql` (Planner Reference §13.14): gather with tools, load the results whole (the service keeps
  uncapped outputs for such a run), have the model write a SELECT, send DuckDB's error back at most
  `settings.max_queries` times, then draft and verify. A query result is a result for
  `numbers_in_results`, its citation names its source calls, each numeric column of a query enters
  the workspace as `<query id>.<column>` with the query and its source calls as lineage, and every
  query is in the ask's result and audit entry (`queries`) and on the stream (`query`,
  `table_loaded`).
- **Planner `code_act`** (Quantitative Planners §3.5, Planner Reference §13.17) and the stage type
  `code_act` (`sajha/ai/code_act/`): model-written Python runs in the sandbox's default backend with
  the network off and the `sandbox.*` limits, reads the run's quantities and results as JSON on
  standard input, and must print quantities with units as JSON (anything else goes back to the
  model). The code, its input digest and its output are in the ask's result and audit entry
  (`code_runs`), on the stream (`code_run`) and in an `ai_code_act` audit event. Role-limited by
  `ai.quant.code_act.roles` (default none): a caller without the role is not offered it
  (`GET /api/ai/planners`, `classify` menus, `planner` stages), `auto` never picks it, and a direct
  run ends `stopped_by: refused`. Stage types can declare such a limit (`allowed_roles()`) or an
  optional dependency (`unavailable()`).
- **Planner `optimize`** (Quantitative Planners §3.6, Planner Reference §13.16) and the stage type
  `optimize` (`sajha/ai/optimize/`): the model writes a formulation (variables with bounds and
  integrality, a linear or quadratic objective, linear constraints, at most
  `settings.max_variables`) that is validated with every error sent back, then solved with SciPy
  (`linprog`, `milp`, or `minimize` for a convex quadratic). A coefficient, bound or right-hand side
  may name a single-number workspace quantity, and the solution's lineage names it. A feasibility
  check evaluates every bound and constraint at the solution; infeasible, unbounded, unsupported
  (non-convex) and check-failed problems are reported as such, never with an invented solution.
- **Planner `reconcile`** (Quantitative Planners §3.8, Planner Reference §13.21) and the stage type
  `reconcile`: the model says where each source holds a figure; SAJHA reads each value from the tool
  result, aligns the readings on as-of period (`settings.align`) and unit (scales, percent and bp;
  two currencies only through an FX rate read from a tool, otherwise the figure is reported as not
  comparable), and lists each difference beyond `settings.tolerance` or `settings.tolerance_abs`
  with both lineages; the model explains the table. The stream carries a `reconciliation` event, and
  the ask's result and audit entry the comparison (`reconciliations`).
- **Planner `research_writer`** (Quantitative Planners §3.7, Planner Reference §13.15): an outline,
  one ReAct sub-run per section, a draft with call ids cited inline, a per-paragraph citation check
  and one revision, from the existing stage library only.
- **Quantitative eval sets** (`config/evals/quant_calc_graph.yaml`, `quant_scenario.yaml`,
  `quant_optimize.yaml`; Quantitative Planners §4): questions with known answers (a percent change,
  a CAGR, a spread in basis points, an NPV, a weighted average, a regression slope, a sensitivity
  table, a linear programme with a known optimum) and `number` checks with tolerances. CI
  (`tests/ai/test_quant_evals.py`) runs them on the mock provider, on `mock-planner` and with
  scripted replies and recorded tool results that are wrong on purpose (an unknown operation, wrong
  units, a cycle, a self-computed figure, a bad grid, an invalid formulation), each of which must be
  refused and re-planned.
- **Mock planner replies** for the `graph_plan`, `estimate`, `optimize`, `code_act`, `grid`, `sql`
  and `reconcile` stages, so dry runs of those planners on `mock-planner` complete; it writes
  computation graphs for the eval sets' question shapes and solves a linear programme written out in
  the question, so the `quant_calc_graph` and `quant_optimize` sets pass offline. A question that names
  two or more tools calls each of them; a draft reports the quantities of a `code_act` program and an
  optimisation result, names a plan-step item by its heading and, when asked to, cites call ids in
  square brackets; `reconcile` skips fields that echo a call's inputs.
- **`foreach` `do` graphs may use stage types registered in code**, validated against their own
  schema as in a file's graph (Planner Reference §6.13).
- **Tutorial 45**, [Quantitative Planners](docs/tutorials/TUTORIAL_45_quantitative_planners.md): the
  workspace and units, `numbers_check`, each planner, enabling `code_act` by role, and how `auto` and
  `router` choose.

### Changed

- **`router` 1.1.0** sends a question asking for a computed figure (its new `quant_pattern`: percent
  change, CAGR, basis points, what if, sensitivity, spread, NPV and the like) to `quant_default`
  (`calc_graph`), after the configured rules and recipes and before the multi-step check; new
  settings `use_quant`, `quant_default` and `quant_pattern` (Quantitative Planners §3.9).
- **`auto` 1.1.0** offers `calc_graph`, `scenario` and `data_analyst` among its candidates (never
  `code_act` or `optimize`), verifies with `numbers_in_workspace` instead of `numbers_in_results`,
  and does not escalate a candidate in its new `self_checked` setting for low confidence alone.
  Eval filtering of its menu applies to the new candidates as to the others.
- **`queries` on the ask's result** are now collected from every sub-run, so they are reported when
  `auto` ran `data_analyst`.

### Fixed

- `numbers_in_results` with `ignore: []` now checks every number; an empty list used to fall back
  to the default ignore rules.

## v8.8.0 (October 2026) — tool health checks, domain descriptions, schema defaults, LLM providers import safe

### Upgrading

- **Schema defaults now win.** Where a tool's code default differed from its schema's, the schema's is
  used (see Added). Set `tools.apply_schema_defaults: false` (or `SAJHA_TOOLS_APPLY_SCHEMA_DEFAULTS=false`)
  to restore the old behaviour for this release only; the switch is removed in the next. Tools whose
  behaviour changes when an argument is left out: `fred_*`: `limit` is the schema's 20 or 30 instead of the
  code's 40 or 60 (fewer, newest observations), and the preset single-series tools on the custom-series
  class (for example `fred_core_cpi`, `fred_yield_spread`; formerly also `fred_gold_price`) now work
  without `series_id`; before, they failed unless it was sent. FMP tools that forward their arguments now
  send the schema defaults: `fmp_technical_*` send `period` (14; 20 for `fmp_technical_sma`);
  `fmp_cik_list`, `fmp_etf_list`, `fmp_stock_list`, `fmp_historical_market_cap`, `fmp_press_releases`,
  `fmp_financial_growth` and `fmp_stock_screener` send `limit` 20 (`fmp_earnings_transcript` has no
  `year` or `quarter` default, so FMP still chooses the transcript). LLM tools fill template placeholders from defaults (`llm_summarise`: "at most 2
  sentences"). Unchanged: `av_sma`, `av_ema`, `av_bbands` and `av_cci`, whose schemas now say
  `time_period` 20, as the code always sent; `sajha_search_docs`, whose schema no longer declares `top_k`
  3, so `ai.rag.top_k` still applies; the qlrisk tools (their schema defaults are the library's), though
  `qlrisk_inputs` now lists the defaulted values too.
- **Removed OpenBB tools** (OpenBB 4.6 has no command for them) and what to use instead:
  `openbb_commodity_lbma_gold` and `openbb_commodity_lbma_silver` → `openbb_derivatives_futures_historical`
  (`GC=F`, `SI=F`) or `imf_get_data` (database `PCPS`, keys `G001.PGOLD.USD.M`, `G001.PSILVER.USD.M`);
  `openbb_commodity_search` → `openbb_commodity_price` (its `commodity` enum) or `fmp_commodity_list`;
  `openbb_index_search` → `openbb_index_available`; `openbb_equity_fundamental_overview` →
  `openbb_equity_profile`, `openbb_equity_metrics`; `openbb_fixedincome_moody` → `fred_custom_series`
  (`AAA`, `BAA`); `openbb_news_search` (its command had no search parameter) → `openbb_market_news`,
  `openbb_company_news` or `tavily_news_search`.
- **Removed open data tools** and what to use instead: `rbi_get_exchange_rate`, `rbi_get_inflation`,
  `rbi_get_forex_reserves` → `imf_get_ifs_data` with country `IND` (`exchange_rate`, `cpi_inflation`,
  `international_reserves`); `rbi_get_policy_rate`, `rbi_get_gsec_yield` → none (no open source); the
  `reserve_bank_of_india` folder and guide (now in `docs/archive/`) are gone. `pboc_get_cgb_yield` →
  `pboc_get_policy_rate` with `interbank_3m` (no Chinese bond yield is published openly);
  `pboc_get_money_supply` → none. `un_get_sdg_progress` (a stub) → `un_get_sdg_data`.
  `fred_gold_price`, `fred_silver_price` (series gone from FRED) → `imf_get_data` with database `PCPS`
  and key `G001.PGOLD.USD.M` or `G001.PSILVER.USD.M`. Remove these and the OpenBB tools above from tool
  groups, workflows and prompts that name them.
- **Changed arguments**: `openbb_commodity_price` takes `commodity` instead of `symbol`;
  `openbb_equity_screener` drops `country` (OpenBB's yfinance screener returns nothing with it;
  `fmp_stock_screener` filters by country); `time_period` is gone from `av_macd`, `av_stoch`, `av_obv`,
  `av_ad_line` and `av_vwap`, which never sent it; `bdf_get_oat_yield` `bond_term` is `10y` only;
  `ecb_*` `eonia` is gone; `pboc_get_policy_rate` `rate_type` is `discount_rate` or `interbank_3m` (was
  `lending`/`deposit`); `pboc_get_inflation` `measure` and `boj_get_inflation` `index_type` are `cpi` or
  `cpi_inflation` (`core_cpi` and `ppi` are gone); `pboc_get_economic_indicator` drops `unemployment`,
  `industrial_production`, `retail_sales` and `fdi`; `boj_get_policy_rate` drops `discount`;
  `boj_get_money_supply` `aggregate` is `broad_money`; `boj_get_economic_indicator` drops
  `industrial_production`; `imf_get_ifs_data` takes one of its listed `indicator`s (no `indicator_code`)
  and `imf_get_data` a `key` for dataflows not keyed by country, indicator and frequency;
  `edgar_company_tickers_by_exchange` drops `AMEX`/`BATS`; `wiki_get_page` drops `include_references`.
- **Changed defaults**: OpenBB default providers changed, so an omitted `provider` now reaches a provider
  the command offers: for example `openbb_equity_metrics`, `openbb_equity_estimates_consensus`,
  `openbb_equity_management`, `openbb_equity_share_statistics`, `openbb_etf_info`, the discovery tools
  and the screener default to yfinance; `openbb_equity_search`, `openbb_insider_trading` and
  `openbb_regulators_sec_filings` to sec; `openbb_economy_cpi` to oecd; the calendars to nasdaq;
  `openbb_company_news` and `openbb_market_news` to fmp (OpenBB's yfinance news returns nothing at
  present). `boj_*` (among them `boj_get_policy_rate`, `boj_get_exchange_rate`, `boj_get_inflation`,
  `boj_get_jgb_yield`, `boj_get_money_supply`) and `pboc_*` return the last `recent_periods` (10)
  observations when no date is given (the whole history before); `fred_leading_index` reads
  `USALOLITOAASTSAM` (USSLIND ended in 2020); `edgar_financial_ratios` without `fiscal_year` uses the
  latest year (all ratio groups were empty).
- **Keys**: Alpha Vantage tools need `ALPHA_VANTAGE_API_KEY`; without it they return a configuration error
  instead of sending the `demo` key. `fed_*` configs now carry `"api_key": "${fred.api.key}"`; set
  `FRED_API_KEY` for every FRED-backed tool (`fred_*` tools no longer send `DEMO_KEY`).
- **Result shapes**: results of the generic OpenBB tools add `provider` and `truncated`;
  `openbb_etf_holdings` reports `data_points` instead of `holdings_count`. Results of the ECB, Banque de
  France, IMF and some PBoC/BoJ tools have new fields (`source`, `unit`, `label`, `latest_actual_year`),
  and IMF results new shapes (see the [IMF guide](docs/tools/public-data/IMF%20Tool%20Reference%20Guide.md)).
- **Requirements**: `requirements.txt` now asks for OpenBB 4.6 or later and yfinance 0.2.54 or later.
- A configuration naming the mock LLM provider's old class path `sajha.ai.llm.mock:MockProvider` must use
  `sajha.ai.llm.providers.mock:MockProvider` (the built-in name `mock` is unchanged).
- The Bank of Canada `gdp` indicator is removed from `boc_get_series`, `boc_get_latest`,
  `boc_get_common_indicators` and `boc_search_series`: its series did not exist and Valet has no ongoing
  Canadian GDP series. Calls passing `indicator: gdp` now fail schema validation.
- **The live tool check now covers the shipped data tools**: they declare `readOnlyHint: true`, so
  `python -m sajha.quality check` and a configured `quality.check.cron` call each against its outside
  service, paced per folder (`quality.check.pause_ms`). Keyless providers that rate-limit (CoinGecko)
  may need a longer pause; tools that depend on local files (`msdoc_*`, `sqlselect_*`) fail where those
  files are absent: list them in `quality.check.exclude`.
  Planner dry runs (`POST /api/ai/planners/dry-run`) and the offline LLM-tool test in Describe a tool
  run read-only tools unasked, so they now run these tools too (the calculators included) instead of
  stubbing them unless named in `run_tools`.

### Added

- **Schema defaults applied before every call** (Roadmap L21; [Tool Quality §12.1](docs/architecture/Tool%20Quality.md#121-schema-defaults-applied-before-a-call)).
  A tool's `inputSchema` `default` is filled in for an absent argument once, in
  `BaseMCPTool.execute_with_tracking`, so MCP (both eras), the REST API, Ask SAJHA, LLM tools,
  workflows, async tasks and SAJHA Net calls all see the same arguments; the composite step executor
  and the quality harness do the same. Never a `required` property; nested objects only when the caller
  sent them; nothing through `oneOf`/`anyOf`/`$ref`/`items`; a default that fails its own schema is
  skipped. The audit record names the filled keys (`details.defaults_applied`). Proxied and SAJHA Net
  tools forward arguments unchanged. New lint rules `required-default` and `unapplied-default`. What
  this changes for existing tools is under Upgrading.
- **Live tool check** (Roadmap L23; [Tool Quality §12.4](docs/architecture/Tool%20Quality.md#124-the-live-tool-check)):
  `python -m sajha.quality check [--tool] [--folder] [--json] [--junit] [--save]` calls every read-only
  tool once with arguments from its test case, its `inputSchema` `examples` or its required properties'
  examples, one call at a time per folder, and reports `ok`, `empty`, `error`, `schema_mismatch`,
  `not_configured`, `not_checked` or `skipped` with the reason. One `quality.check:<folder>` notice per
  folder with broken tools; an optional schedule (`quality.check.cron`) on the probe scheduler; the
  latest outcomes on the Tool Health page and `GET /api/quality/check`; lint rule `missing-example`.
- **Domain descriptions** (Roadmap L24; [Architecture §5](docs/architecture/Architecture.md#domain-descriptions)).
  An optional `<tools dir>/<folder>/domain.txt` says once what a tool folder as a whole is for; it is
  appended, after a blank line, to the description of every tool in that folder wherever descriptions
  are served (`tools/list` in both eras, the REST API, the Tools and execute pages, Ask SAJHA's tool
  definitions and search index, the OpenAI-compatible model list, SAJHA Net catalogs) and is never
  written into a tool's JSON. At most `tools.domain_description_max_chars` (600) characters: a longer
  file is refused with the notice `tools.domain_description:<folder>`, never cut; a root `domain.txt` is
  ignored with `tools.domain_description_root`. The file monitor reloads it and announces the catalog
  change. Where own description plus domain text would pass SAJHA Net's 1024-character limit, the
  catalog entry leaves the domain text out; lint rule `description-length` reports those tools. The
  Domains page shows each folder's description, and a tool's configuration page shows it read-only.
  Shipped for `fred`, `fmp`, `alphavantage`, `coingecko`, `edgar`, `qlrisk`, `yahoo`, `ecb`,
  `banque_de_france`, `imf`, `federal_reserve`, `fbi`, `tavily`, `sharepoint` and `webcrawler`; the
  sentences they say (source, key and its environment variable, rate limits, units, "no API key") were
  removed from those tools' own descriptions, and the domain texts were checked against the code (FRED
  sends no `DEMO_KEY`, Alpha Vantage no `demo` key, FMP without a key answers a demo placeholder, the
  `edgar_*` tools pause 110 ms between requests and the `sec_*` tools do not). Every shipped tool's own
  description plus its domain text now fits SAJHA Net's 1024 characters, so `description-length` is clean.
- **Read-only annotations and structured examples on the shipped data tools.** Every tool that only reads
  (market data, macro and central-bank data, filings, search, the web crawler's fetches, calculators, the
  read-only DuckDB, SQL Select, OLAP and document tools) declares `readOnlyHint: true` and
  `idempotentHint: true`, with `openWorldHint` true when it calls an outside service, so the live tool
  check covers them. Tools that write, send, delete or act on a connected account are not marked; nor are
  the SharePoint tools (they can check out, copy and delete files) or `duckdb_refresh_views`. Tools whose
  arguments could not be derived from their schema got an `inputSchema` `examples` entry equal to their
  description's `Example:`.
- **Generated Tool Reference Guide tables** (Roadmap L25; [Tool Quality §12.5](docs/architecture/Tool%20Quality.md#125-tool-reference-guide-tables-generated)):
  `python -m sajha.tools guides [--folder NAME] [--check]` rewrites the region between
  `<!-- generated:tools folder=... -->` and `<!-- /generated:tools -->` in the guides under
  `docs/tools/` from the tool configs: tool, title, the description's first sentence, required and
  optional parameters with schema defaults, annotations and the key a tool needs. Every guide whose
  table listed a folder's tools now has a marked region; `--check` runs in the test suite.
- **Shared SDMX client** (`sajha/tools/impl/sdmx_client.py`): SDMX 2.1 REST data and structure queries,
  SDMX-CSV and SDMX-JSON, host profiles (`ecb`, `imf`; `register_host` for the 8.2 sources), "no data"
  for an empty selection, every fetch through the outbound guard and proxy to the profile's host only.
  The ECB, Banque de France and IMF tools use it.
- **Hugging Face Inference Providers** as an LLM provider preset, `huggingface`
  (`https://router.huggingface.co/v1`, key `HF_TOKEN`; model ids may end `:fastest`, `:cheapest` or a
  host name). A self-hosted TGI server stays `openai_compatible`.
- [Tutorial 43: Connect and Configure LLM Providers](docs/tutorials/TUTORIAL_43_llm_providers.md).
- [Tutorial 44: Tool Health and Domain Descriptions](docs/tutorials/TUTORIAL_44_tool_health.md): schema
  defaults and the switch, a folder's `domain.txt`, read-only annotations, the live tool check with its
  notices and the Tool Health page, and the generated guide tables.

### Changed

- The mock LLM provider moved into the providers package with the others (`sajha/ai/llm/providers/mock.py`,
  with `mock_llm_tools.py` and `mock_toolsmith.py`); like every provider it is built by the factory from
  configuration (the class path change is under Upgrading).
- The generated `qlrisk_price_<product>` descriptions are shorter: units, the common `advanced` fields
  and the sample market are said once in `config/tools/qlrisk/domain.txt`, inputs are listed as
  `name=default`, and only the product's extra `advanced` fields are named
  (`python -m sajha.tools.impl.qlrisk.generate`). The hand-written qlrisk risk tools' descriptions were
  cut to what fits beside the domain text; `qlrisk_stress_test` and `qlrisk_frtb_sa_capital` have smaller
  worked examples (one swap under a stylised "risk off" scenario; one corporate bond).
- The LLM providers load one by one: a provider module that cannot be imported is logged and skipped and
  the others still register, so SAJHA always starts; optional vendor libraries stay imported only on use.

### Fixed

Broken market data and open data tools fixed or removed (Roadmap L22,
[Tool Quality §12.2–12.3](docs/architecture/Tool%20Quality.md#122-broken-tools-fix-or-remove)). Each
changed tool's description now states what it does, in at most 1000 characters with an `Example:` that
validates against its schema (`tests/test_open_data_fixes.py`). Every fixed tool was called live against
its upstream (FMP, FRED and Alpha Vantage tools, and FRED-backed series, only up to the key check: no keys
were available; their series ids were checked on fred.stlouisfed.org). Removals, changed arguments and
defaults are under Upgrading.

- **OpenBB** (`sajha/tools/impl/openbb_tools.py`, [OpenBB guide](docs/tools/market-data/OpenBB%20Tool%20Reference%20Guide.md#how-a-call-runs)).
  Every tool names one OpenBB command (`TOOL_COMMANDS`), checked by a test against the installed
  OpenBB 4.6. Commands that no longer existed now map to their successors: `openbb_treasury_rates`
  (`fixedincome.government.treasury_rates`: daily yields per maturity, not the fed funds rate),
  `openbb_yield_curve` (`fixedincome.government.yield_curve`), `openbb_earnings`
  (`equity.fundamental.historical_eps`), `openbb_commodity_price` (`commodity.price.spot`: EIA energy
  spot prices; argument `commodity` replaces `symbol`), `openbb_index_constituents`
  (`index.constituents` with `symbol` sp500, nasdaq or dowjones), `openbb_fixedincome_ice_bofa`
  (`fixedincome.bond_indices`), `openbb_regulators_sec_filings` (`equity.fundamental.filings`, with
  `form_type`), `openbb_economy_interest_rate` (`economy.interest_rates`, with `duration`). Each tool's
  `provider` is an enum of the providers OpenBB offers for its command, and the default is a keyless one
  where the command has one (yfinance, federal_reserve, oecd, sec, nasdaq, econdb, government_us);
  before, an omitted provider was sent as `yfinance`, which most commands refuse. Only arguments the
  command accepts are sent (others are listed in `ignored_arguments`); `openbb_equity_screener` sends
  `market_cap_min`/`max` as OpenBB's `mktcap_min`/`max`. Rows keep their dates (they were lost to the
  DataFrame index), and `limit` (1-1000) caps rows with `data_points` and `truncated`, keeping the most
  recent rows of a dated series. SAJHA's `fmp.api.key`, `fred.api.key` and `alpha_vantage.api.key` are
  given to OpenBB for credentials its `user_settings.json` leaves empty. A command missing from the
  installed OpenBB is an error naming it and the info notice `tools.openbb_command:<tool>`.
- **Yahoo**: `yahoo_get_quote` goes through yfinance (Yahoo's quoteSummary answers 401 without a
  cookie and crumb) and adds `exchange` and `market_time`; `yahoo_search_symbols` maps NYSE, NASDAQ,
  AMEX, LSE and TSX to Yahoo's exchange codes and fetches enough matches to fill `limit`;
  `yahoo_get_history`'s `adjusted_close` is Yahoo's dividend-adjusted series instead of a copy of
  `close`; `yf_screener` uses `yf.screen` with two more screens and a `limit`; `yf_trending_tickers`
  reads Yahoo's trending endpoint per `region` (symbols only); `yf_index_history`, `yf_forex_history`,
  `yf_stock_history`, `yf_multi_ticker_history`, `yf_dividends`, `yf_splits`, `yf_actions` and
  `yf_shares_outstanding` return the most recent `limit` rows (they returned the oldest) with
  `data_points` and `truncated`; `yf_multi_ticker_history` takes up to 10 tickers separated by spaces or
  commas; `yf_crypto_info` appends `-USD` only to a symbol without a pair (`BTC-EUR` was sent as
  `BTC-EUR-USD`); `yf_news` falls back to Yahoo's search news when `Ticker.news` is empty;
  `yf_options_chain`, `yf_upgrades_downgrades` and `yf_earnings_dates` take a `limit`.
- **Alpha Vantage**: Alpha Vantage's `Error Message`, `Information` and `Note` answers become
  `{"error": ...}`; `av_vwap` defaults to `15min` and accepts intraday intervals only; indicator
  `interval`s are an enum; `av_crypto_daily` and `av_crypto_weekly` no longer require `symbol` (default
  BTC); `av_treasury_yield` exposes `interval`.
- **Banque de France** (`bdf_*`): the ECB Data Portal through the SDMX client instead of the retired
  `sdw-wsrest.ecb.europa.eu`; every series parsed (the parser read one hard-coded key); `m3` is M3's
  annual growth rate (it was a loans series); inflation reads the ECB's `HICP` dataflow (`ICP` was
  retired in February 2026); `bdf_get_oat_yield` offers `10y` only, the one French yield the ECB
  publishes (the four tenors were one series); `recent_periods` (default 10) is applied.
- **ECB** (`ecb_*`): the SDMX client with `lastNObservations`, so `ecb_get_latest` and
  `ecb_get_common_indicators` return monthly and quarterly series (a 40-day look-back left them empty);
  HICP, €STR (`EST`), GDP (euro area 21) and unemployment on live keys; EONIA removed (no data since 2022).
- **IMF** (`imf_*`): the IMF's current SDMX API (`api.imf.org`, no key) instead of the dead
  `dataservices.imf.org`. `imf_get_databases` and `imf_get_dataflows` list live dataflows and key
  structures; `imf_get_data` takes a full key; `imf_get_ifs_data` reads the retired IFS indicators from
  their successor dataflows (CPI, ER, MFS_IR, IL, MFS_MA); WEO, BOP, comparisons (one request) and the
  country profile report `latest_actual_year`. Countries accept ISO alpha-2 or alpha-3.
- **Federal Reserve** (`fed_*`): no more synthetic "demo mode". The key comes from `FRED_API_KEY`
  (`fred.api.key`) through one lookup shared by every FRED-backed tool (`sajha/tools/impl/fred_key.py`);
  without it a call fails with a message saying how to set it.
- **FRED**: the preset tools use their schema `limit` default in code too.
- **PBoC and BoJ**: each label reads its own live series. `pboc_get_policy_rate` offers `discount_rate`
  and `interbank_3m`; `pboc_get_inflation` and `boj_get_inflation` read IMF CPI (`cpi`, `cpi_inflation`);
  `pboc_get_economic_indicator` offers GDP, GDP growth (IMF WEO), exports, imports, trade balance and
  property prices; `boj_get_economic_indicator`'s `trade_balance` is the balance (it read exports), with
  `exports` and `imports` added; `boj_get_money_supply` is IMF broad money; `currency_pair` says yen per
  unit.
- **UN** `un_get_sdg_data`: converts ISO codes to the M49 numbers the SDG API needs (an ISO code returned
  every area), reads the paged answer (it was always empty), filters years with `timePeriod`, adds
  `max_records`, `series` and `dimensions`.
- **EDGAR**: `edgar_company_search` and `edgar_company_tickers_by_exchange` read
  `company_tickers_exchange.json` (the tickers URL had moved and carried no exchange); exchanges are
  Nasdaq, NYSE, OTC, CBOE, TXSE. `edgar_companies_by_sic` no longer raises `NameError`, and scans the
  `max_scan` (200) largest companies. SC 13D/G and the SCHEDULE 13D/G names used since December 2024
  find each other. Frames fall back to instant periods (`CY2023Q4I`) for balance-sheet concepts
  (`period_type`). `edgar_financial_ratios` uses the period's own values, not prior-year comparatives.
  `sec_get_financial_data` maps its friendly names to us-gaap tags (`CurrentAssets` → `AssetsCurrent`,
  ...). `sec_get_mutual_fund_holdings` lists NPORT-P filings.
- **CoinGecko**: `cg_top_gainers` / `cg_top_losers` rank the 250 largest coins by 24-hour change in SAJHA
  (`limit`, default 20); `cg_coin_markets.order` is an enum of CoinGecko's documented sorts.
- **Wikipedia**: `wiki_get_page` `include_links` returns up to 500 article and external links;
  `redirect: false` works; `wiki_get_summary` returns `original_image`.
- **World Bank**: `wb_search_indicators` searches the whole catalogue (cached a day); `most_recent_year`
  in `wb_compare_countries` works. **FBI**: year schemas lost a fixed maximum of 2100 (the code allows
  1985 to the current year).
- **Bank of Canada**: the `boc_*` shorthands read the right Valet series (checked live): `policy_rate`
  `V39079` (was the missing `POLICY_RATE`), `overnight_rate` `AVG.INTWO` (CORRA; was the missing `CORRA`),
  `prime_rate` `V80691311` (was the Bank rate), `bond_2y`/`5y`/`10y` `BD.CDN.<N>YR.DQ.YLD` and `bond_30y`
  the long-term benchmark `BD.CDN.LONG.DQ.YLD` (were T-bill, other-term or missing series), `core_cpi`
  CPI-trim `CPI_TRIM` (was seasonally adjusted total CPI). Results with `recent_periods` now come oldest
  first, as described (Valet answers newest first).
- **Live tool check from the command line**: `python -m sajha.quality check --save` failed with "Database
  not initialized", and its notices and latest results never reached a server using the database state
  store. `python -m sajha.quality` now opens SAJHA's database when a command needs it (`check`, `runs`,
  `compare`, `--save`, and `eval` unless `--no-save`).
- **Output schemas that rejected real answers** (found by the live check): `extract_metadata` and
  `get_page_info` (title and meta tags may be absent), `wb_get_indicators` and `wb_get_topic_indicators`
  (the World Bank sends `per_page` as a string), `wb_compare_countries` (`latest_year` may be null),
  `un_get_sdgs` (`color` may be null), `ir_get_latest_earnings` (null when nothing is found),
  `edgar_frame_data` (`cik` is a number) and `sec_get_company_info` (address lines may be null). The web
  crawler's `crawl_sitemap`, `extract_content` and `extract_links` examples now point at pages that exist.
- **Required properties with a default** (lint `required-default`, which a required property contradicts:
  it is never filled in): `symbol` of `fmp_commitment_of_traders`, `fmp_commodity_*`, `fmp_crypto_*`,
  `fmp_forex_*` and `fmp_index_*`, and `operation` of `sharepoint_documents` and `sharepoint_lists`, now
  carry the value as an `examples` entry instead; the property stays required, as it always was.

### Planned

- **Quantitative planners** placed as phase 8.2 (release 8.9.0), Roadmap L51–L59, design
  [Quantitative Planners](docs/architecture/Quantitative%20Planners.md): a quantitative workspace
  (quantities with units, as-of and source, a tested operation library, a numbers validator), the
  planners `calc_graph`, `estimate_then_compute`, `scenario`, `data_analyst`, `code_act` and
  `optimize`, a `numbers_check` setting for every planner, `research_writer` and `reconcile`. Open data,
  business intelligence and reports move to phases 8.3, 8.4 and 8.5 (releases 8.10.0, 8.11.0, 8.12.0).
- Owner decisions of 2026-10-11 recorded in the designs: the UN sanctions list and GDACS stay off until
  legal approves, sanctions results are blocked from Ask SAJHA by policy, BIS ships with its citation,
  no paid data options, P2 and P3 open data may slip, the usage page's menu entry becomes "Usage" in the
  reports phase, and Playwright, openpyxl and python-pptx are acceptable as optional `requires`.

## v8.7.0 (October 2026) — full tool descriptions, safer document and SQL tools

### Changed

- **Every tool has a full description** in the style of the qlrisk tools (about 510 tools in 32 folders):
  what it does and its source, what it returns, every input with required ones marked and formats, units
  and defaults, related tools, the API key it needs, and an example call checked against its input schema.
  Where a tool's code and schema disagree, or a tool is broken upstream, the description says what the
  tool actually does; the fixes are planned in wave 8, phase 8.1. Missing input descriptions were added, so
  the tool lint reports no description warnings.
- The SAJHA logo in the navigation bar always leads to the landing page, signed in or not; `/` no longer
  redirects a signed-in visitor to the dashboard, and the landing page offers them Dashboard where a visitor
  gets Sign In.
- Wave 8 planned (Roadmap L21–L50; [Implementation Plan](docs/architecture/Implementation%20Plan.md)):
  tool health and domain descriptions, open-data tools, business intelligence and reports, with designs in
  [Open Data Tools](docs/architecture/Open%20Data%20Tools.md),
  [Business Intelligence](docs/architecture/Business%20Intelligence.md) and [Reports](docs/architecture/Reports.md).

### Fixed

- **Security: `msdoc_*` path traversal.** A file argument was joined to the documents folder unchecked
  (`../msd/sales.xlsx` was read). It is now resolved to its real path and refused when absolute, when it has
  a `..` part, or when it (or a symbolic link) lies outside `docs_directory`; links out of the folder are
  no longer listed. Shared helper `confined_path` in `sajha/core/storage.py`.
- **Security: `sqlselect_*` file read and SQL injection.** The connection never disabled DuckDB's file
  access (`SELECT read_text('/etc/passwd')` worked) and `sqlselect_count_rows` pasted `where_clause` and
  the source name into SQL. Sources are now copied into tables, then `enable_external_access` is switched
  off and the configuration locked (as the `duckdb_*` tools do); source names are quoted;
  `sqlselect_execute_query` runs one parser-checked read-only statement; `where_clause` must have no `;`
  or comment and parse as a single DuckDB expression. A changed data file is seen on the next tool load.
  `duckdb` now needs 1.1 or later.
- `sqlselect_execute_query` refused legitimate queries such as a column `created_at`: the write-keyword
  check now matches whole words only.
- `calc_bond_price` failed when `face_value` was omitted; the schema default 1000 is applied.
- `calc_currency_converter` silently used rate 1 for an unknown target currency; it now returns an error.
- `msdoc_read_excel` with `include_formulas` returned spreadsheet cell objects in `data`; it returns the
  formula text (`=A2+B2`) and plain values.
- The Word `msdoc_*` tools failed because `python-docx` was not installed: `python-docx` and `pypdf` are
  now in `requirements.txt`.
- `fmp_market_gainers`, `fmp_market_losers`, `fmp_most_active`, `fmp_senate_trading`, `fmp_sec_filings`,
  `fmp_price_target` and `fmp_upgrades_downgrades` sent `limit` 20 or 10 when it was omitted; they send
  the schema default, 5.
- `duckdb_list_files` ignored `include_metadata`; `false` now drops each file's size and date.

## v8.6.0 (October 2026) — an HTTP proxy for tool fetches; documentation brought up to date

### Added

- **A proxy for the guarded fetches** of the web crawler tools and Studio REST tools:
  `tools.outbound.proxy` (an `http://` or `https://` proxy URL, empty = direct as before; set it with
  `SAJHA_TOOLS_OUTBOUND_PROXY` because it may carry credentials, which are only ever shown masked) and
  `tools.outbound.no_proxy` (host patterns or CIDRs that go direct). `HTTP_PROXY` / `HTTPS_PROXY` are never
  read. Through the proxy the outbound fetch guard still refuses blocked names, literals and resolved
  addresses and checks every redirect hop; a host that does not resolve locally is left to the proxy;
  `https` goes by `CONNECT` with TLS verified to the real host. The connection cannot be pinned through a
  proxy; the residual is described in the [Security Model](docs/security/Security%20Model.md#other-features-that-need-care).
  API Import is unchanged (never proxied).

### Fixed

- Documentation brought in line with the code: per-user sign-in and the GitHub, Atlassian and Google
  guides described as built (no longer "design" or "proposal"); those guides no longer claim a default
  approval rule for proxied writes (none ships; an operator writes the policy rule, Roadmap L20); owners
  named for tool folders and domains, qlrisk, the outbound fetch guard and the Implementation Plan; the
  Implementation Plan and Roadmap statuses after wave 7; the Server connections pages in the menu table;
  a glossary term for the outbound fetch guard; three archived documents marked as archived.
- Console: removed buttons that only answered "Feature coming soon" (Admin > Tools "Enable/Disable All
  Tools", Admin > Users "Enable All Users" and "Reset All Passwords") and MCP Studio's "Coming Soon" banner
  for API import, which has shipped.

## v8.5.0 (October 2026) — outbound fetch guard for crawler and REST tools

### Upgrading

- **The web crawler tools and Studio REST tools refuse cloud metadata and localhost.** Their fetches now go
  through the outbound fetch guard: a URL whose host resolves to a cloud metadata or link-local address
  (169.254.169.254, `metadata.google.internal`), loopback (`localhost`, 127.0.0.0/8, ::1) or 0.0.0.0 gets the
  tool error `refused: <url> resolves to a blocked address (...)`. Private ranges stay allowed unless the new
  `tools.outbound.block_private_networks` is true. To call a service on localhost on purpose (a REST tool
  pointing at `http://localhost:8080/...`, say), list it in `tools.outbound.exempt_hosts` (`[localhost]` or
  `[127.0.0.1/32]`; env `SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS`). These fetches no longer use the environment's
  proxy variables, and a REST tool follows redirects for GET only. Regenerate a REST tool made before this
  release in MCP Studio to give it the guard (the generated code calls the guard; older files call
  `requests` directly).

### Fixed

- **Security: SSRF through the web crawler tools and Studio REST tools** (Adversarial QA finding F6). Every
  crawler fetch (page, followed links, robots.txt, sitemaps) and every REST tool call is checked by the
  outbound fetch guard (`sajha/core/outbound.py`, [Security Model](docs/security/Security%20Model.md#other-features-that-need-care)):
  every address the host resolves to, IP literals normalised in any form (decimal, octal, hex, IPv4 inside
  IPv6), the connection pinned to the checked address, each redirect hop checked again. It reuses the shared
  `address_allowed` rule and API Import's pinned client. A refusal is a tool error naming the setting, logged
  at warning without the query string, and does not open the tool's circuit breaker.
- Small screens: the Ask page's Clear button is a full-size tap target, and small text on Ask, the landing
  page's net diagram and the federation console's table headers is at least 12 px; the mobile check now
  covers the Domains page.

## v8.4.0 (October 2026) — per-user sign-in for proxied servers, access rules for prompts and resources

### Upgrading

- **API keys limited to a list of tools lose prompts and data files they were not granted.** A key whose
  tool access mode is `allowlist` or `regex` now reaches no prompt and no data resource (`sajha://data/*`,
  federated `sajha-federation://*`) unless its access list carries `prompt:<pattern>` /
  `resource:<uri pattern>` entries (the key forms have Prompts and Data resources fields; `prompt:*`
  restores the old behaviour for a key). Keys in mode `all` or `denylist`, users and roles keep what they
  had until a role is given `prompt` / `resource` permission rows. Anonymous callers are unchanged, except
  that federated resources now also need `mcp.anonymous.resources`.
- **Database:** no schema change; prompt and resource entries live in the existing `tool_access_list`.
  Per-user tokens for proxied servers use the existing `connected_accounts` table (provider `upstream:<id>`).
- **Proxied servers:** nothing changes for existing upstreams (their credential mode is `static`). "Sign out
  everywhere", an administrator's session revocation, disabling and deleting a user (on the console or in
  the users file) now also delete that user's personal tokens and OAuth sign-ins for proxied servers.
  Upstreams that use `auth.type: oauth_user` need `accounts.public_url` set to the address users reach,
  because the redirect URI registered at the vendor derives from it.
- **Connected accounts:** RFC 7009 revocation now authenticates a confidential client (its secret sent as
  `client_secret`, or HTTP Basic for `client_secret_basic`), as the RFC asks.

### Added

- **Per-user sign-in for proxied MCP servers, part 1** (wave 7 phase 7.2, Roadmap L18;
  [Per-User Sign-In for Proxied Servers](docs/architecture/Per-User%20Sign-In%20for%20Proxied%20Servers.md)):
  a credential mode per proxied server (`auth.type`: `static`, the default; `token_user`; `oauth_user`, part 2) in `federation.upstreams`, console-added
  upstreams and `config/mcp_servers.json`. A `token_user` server is called as the person who asked, with the
  personal token they saved once on the new **Server connections** pages (`/account/server-connections`,
  the connect page per server with a test call, and `/admin/server-connections` with revoke); no token
  gives the "connect your account" answer on MCP 2026-07-28, 2025-11-25, REST and Ask SAJHA, also relayed to
  SAJHA Net callers; a vendor 401/403 marks the connection "needs re-connect"; session-based upstreams get
  one session per user (`federation.per_user_session_idle_seconds`, `federation.per_user_sessions_max`);
  discovery uses a discovery credential or the first connected user's token and offers the union of what
  users see. Tokens are encrypted in the vault, masked in status, never logged or returned; every connect,
  disconnect and refusal is audited and every proxied call's audit record names the identity used.
  Templates `config/mcp_servers/11_github_token_user.json.example` and
  `12_atlassian_datacenter_token_user.json.example`; [Federation §3](docs/architecture/Federation.md#per-user-credentials-token_user).
- **Per-user sign-in for proxied MCP servers, part 2: OAuth** (wave 7 phase 7.3; Roadmap L18 done,
  remaining parts are L20): `auth.type: oauth_user` signs each user in at the vendor ("Connect with
  <vendor>" on the connect page). Discovery of the server's protected-resource metadata (RFC 9728, from the
  401's `WWW-Authenticate` or the well-known URL) and its authorization server's metadata (RFC 8414 or
  OpenID Connect), or operator-given endpoints; dynamic client registration (RFC 7591) kept encrypted in
  the vault, or an operator-registered client (`client_id`, `client_secret_ref`); authorization code with
  PKCE `S256` and a `state` bound to the user and the browser on the connected-accounts machinery; one
  redirect URI for every upstream (`/account/server-connections/oauth/callback`); the resource indicator
  (RFC 8707) on every token request; read `scopes` by default and `write_scopes` only for users who tick
  "allow changes". Tokens are refreshed before expiry and once after a vendor 401; a refused refresh marks
  "needs re-connect"; disconnecting and every revocation path revoke at the vendor (RFC 7009, or GitHub's
  and Google's forms). Per-user sessions and discovery work with OAuth tokens (a refreshed token opens a new
  session). The Connections and administrators' views show scopes and expiry; the federation console's
  form takes the OAuth settings. Templates `13_atlassian_cloud_oauth.json.example`,
  `14_github_oauth.json.example`, `15_google_workspace_oauth.json.example`, and
  `06_remote_oauth_sign_in.json.example` now marked supported. An upstream answering 401 without a
  credential now suggests `oauth_user`. A fake OAuth-protected MCP server for the lab and the tests
  (`deployment/local-lab/fake_oauth_mcp.py`) and [Tutorial 42](docs/tutorials/TUTORIAL_42_per_user_sign_in.md);
  [Federation, Per-user OAuth sign-in](docs/architecture/Federation.md#per-user-oauth-sign-in-oauth_user).

- **Adversarial QA, first automation** ([Adversarial QA Plan](docs/architecture/Adversarial%20QA%20Plan.md)):
  `tests/adversarial/` attacks the P0 surfaces: a denied tool under every name (plain, qualified, published,
  renamed, composite step), the API-key precedence matrix across the keys file, the database and the dump,
  the test admin key, forged and revoked JWTs, hostile strings on console pages and the CSP, tool-folder
  traversal and links, a hostile upstream MCP server (screened descriptions, timeouts, a canary secret in
  every output channel) and the outbound SSRF guard with its documented gaps.
- **Suite integrity** (`tests/suite_integrity.py`): random test order on every run (pytest-randomly, now in
  `requirements-dev.txt` with time-machine); `SAJHA_TEST_CLOCK_SHIFT_DAYS` runs the suite with the clock
  moved ahead; a required test module skipped for a missing dependency fails the run
  (`SAJHA_TEST_ALLOW_MISSING` names exceptions); a test that changes a file under `data/` or `config/` fails
  the run. CI (`.github/workflows/tests.yml`) runs the suite in random order and adds `shifted-clock` and
  `clean-install` jobs; the OpenAI SDK is installed for the tests again.

### Fixed

- Disabling a user in the users file (`config/users.json`, `"enabled": false`) now also revokes their
  tokens for proxied servers, as the console's disable route does; before, the next sync disabled the user
  but left their personal tokens in the vault.
- Per-caller access to prompts and data resources (Roadmap X3): roles limit prompts and data resources
  through `prompt` / `resource` permission rows, API keys through `prompt:` / `resource:` entries; one rule
  for `prompts/list`, `prompts/get`, prompt completion, `resources/list` and `resources/read` on both MCP
  eras, the REST prompt and resource endpoints and the console's prompt pages. Federated prompts and
  resources follow it by their namespaced names and URIs ([Security Model](docs/security/Security%20Model.md#tool-access)).
- Policy rules and caller tool access (role permissions, API-key allow and deny lists) now match every
  name a SAJHA Net tool answers to (its qualified `<net>__<instance>__<tool>` name and its plain alias), so a
  rule or a deny list naming one name is no longer bypassed through the other.
- A symbolic link in `config/tools` that points outside it is no longer loaded; a tool name with a path
  separator or a leading dot is refused by Import JSON and every tool-config writer instead of being written
  outside the tools directory.
- An upstream's status (federation console and admin API) masks credential-named header and environment
  values instead of showing them.
- The tool-config monitor no longer acts on a storage backend it did not start on (tests that point the
  storage at a temporary directory made the live catalog drop every tool for a moment).
- An Ask SAJHA run no longer leaves its asker set as the current caller in the thread that ran it after the
  run ends (a later tool call in that thread, such as a composite step, was checked against the wrong
  caller).
- Order- and date-dependent tests fixed (they relied on files, keys or net state made by another test, or
  on the calendar); tests no longer write `config/apikeys_db.json` (the multi-worker servers) or the tool
  result cache under `data/cache`.

## v8.3.0 (October 2026) — qlrisk risk analytics, tool domains

qlrisk, the owner's QuantLib-based risk library, arrives as native SAJHA tools: core risk tools (VaR and
ES, sensitivities, backtesting, P&L explain, stress testing, FRTB SA and IMA, Basel 2.5, counterparty
exposure, SA-CCR, initial margin, credit risk, XVA, Monte Carlo paths, the RiskEngine report and limits)
and one pricing tool per qlrisk product, generated from qlrisk's product registry — all in human units
(percent, basis points, tenors like 3Y) with short forms and checked against independent estimates.
Tools are browsable by domain (the Domains page and the landing page's "Out of the box" strip, both live
from the tool folders). The Adversarial QA Plan joins the docs.

### Upgrading from 8.2.0

- **qlrisk (optional):** install the wheel into SAJHA's environment (`requirements-qlrisk.txt`); without
  it the qlrisk tools are skipped quietly with one notice. Tool configs may declare `"requires"`.
- **Breaking for qlrisk callers sending decimals:** rates, recoveries, PDs, LGDs, haircuts and
  volatilities are in percent, spreads and rate shocks in basis points, confidence in percent; old
  decimal field names are refused with their replacement.
- **Creators:** the Folder field defaults to Unfiled (the tools base folder); a new folder name creates
  the folder. The tools base folder follows `config.tools.dir` everywhere.
- **`POST /api/tools/execute`** runs tools in a worker thread.
- **Dependencies:** the OpenBB line in `requirements.txt` lists only the extras that still exist.
- **Database:** no schema change since 8.2.0.

### Docs

- [Google Integration](docs/architecture/Google%20Integration.md) (proposal): proxy Google's Workspace MCP servers and
  other public MCP servers once proxied servers support per-user sign-in (Roadmap L18).
- [Per-User Sign-In for Proxied Servers](docs/architecture/Per-User%20Sign-In%20for%20Proxied%20Servers.md) (design,
  Roadmap L18), with proposals for [GitHub](docs/architecture/GitHub%20Integration.md) and
  [Atlassian](docs/architecture/Atlassian%20Integration.md) (Jira, Confluence).

- Fixed: qlrisk per-product pricing tools take rates in percent and maturities like 3Y, with a short form.
  `qlrisk_price_<product>` asked for qlrisk's raw fields, so a coupon of 3 meant 300% (a 3-year treasury
  priced at about 1,074 per 100 face instead of 97.85), "3Y" was not a maturity and the form listed fifteen
  fields. Each tool now asks only for the product's economic terms under human names and units (`maturity`
  as a tenor or date, `face_value`, `coupon_pct`, `spread_bp`, frequencies as words, currency default USD)
  converted to qlrisk's units inside the tool; trade ids and dates, issuer, position, market data, reporting
  currency and cash flows sit in one optional `advanced` object; implausible values are rejected with the
  field named or warned about; descriptions carry a worked example with its real result; the result carries
  `qlrisk_terms`. The tool execute page renders an optional object as a collapsed section, keeps the schema's
  field order and leaves empty fields out
  ([QLRisk Tool Reference Guide](docs/tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md#per-product-pricing-tools)).
- Changed (breaking for callers of the qlrisk tools): the 18 core qlrisk tools use the same units and layout.
  Trades in every tool take the per-product tools' inputs, flat (`maturity` "5Y", `fixed_rate_pct` 4.4,
  `face_value`, `option_type` ...; `tenor_years`, `fixed_rate` 0.044 and the like are rejected with the
  product's inputs listed); confidence levels are in percent (`confidence_pct` 99, `es_confidence_pct`,
  `drc_confidence_pct`), the SA-CVA recovery too (`recovery_pct`); each tool lists its essentials first and
  keeps the rest (market data, history, reporting currency, model settings) in an optional `advanced`
  object; every field has a title, the schema carries a worked example that pre-fills the execute page's
  JSON boxes, and each description ends with that example and its real result (kept true by a test). The
  layout is one table, `sajha/tools/impl/qlrisk/tools/layout.py`; `qlrisk_catalog` topic `products` lists
  each product's inputs.
- Changed (breaking for callers sending qlrisk's decimals): remaining qlrisk calculator inputs and stress
  shocks in human units (percent, bp). Calculator `inputs` and `config` of `qlrisk_credit_risk`,
  `qlrisk_xva` and `qlrisk_ccr_exposure` (mode `calculator`) take probabilities, LGDs, recoveries, rates,
  haircuts and volatilities in percent (`pd_pct` 2, `recovery_pct` 40, `volatility_pct` 1), spreads in
  basis points (`credit_spread_bp` 120, `funding_spread_bp`), horizons in years (`remaining_maturity_years`,
  `time_horizon_years`) and margin periods in business days (`margin_period_of_risk_days` 10); shocks in
  `market_data.shocks`, `qlrisk_pnl_explain` and `qlrisk_stress_test` name their unit (`size_bp` for
  absolute rate, spread and dividend moves, `size_pct` for relative and log moves and vol points, `size` for
  absolute price moves; curve shapes `short_end_bp` ...), and a rates-in-bp curve shock no longer also
  bumps that risk class's volatility surfaces; stylised stresses take `equity_pct`, `vol_pct`,
  `credit_pct` (relative, as qlrisk applies it), `fx_usd_pct`, `commodity_pct`, `fx_pct` and `rates_bp`
  (a 2y-10y twist as two numbers now works); VaR `liquidity.spreads_bp`; the nested terms of TRS and SFT
  products (`terms`, collateral positions and legs, borrowed securities) take `*_pct` / `*_bp` fields
  (a margin loan's `initial_margin_pct` is now 50, not 0.50). One table in `generate.py` (`CALC_INPUTS`,
  `CALC_CONFIG`, `SHOCK_UNITS`, `STRESS_DEFINITION`, `LIQUIDITY`, `NESTED_*`) holds every conversion over
  the schemas read from qlrisk; a decimal name is refused with its new one (`pd is now pd_pct`),
  impossible values are errors naming the field and decimal-looking ones run with a warning (`pd_pct = 0.02
  means 0.02%; for 2% send 2`); results carry `qlrisk_inputs` (what qlrisk received); `qlrisk_catalog`
  shows calculators and the stress library in the same units; `config.confidence_pct` now reaches the PFE
  calculator. Figures are unchanged for the same economic input (tests compare against qlrisk given
  decimals) ([QLRisk Tool Reference Guide](docs/tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md#units-of-qlrisks-own-objects)).
- Fixed: `qlrisk_initial_margin` SIMM took rate sensitivities in qlrisk's per-unit-rate convention and
  silently weighted an unknown bucket key (the guide's `USD-5Y`) at 10%, so a 4,500 DV01 swap gave IM 450;
  it now takes DV01 / CS01 per 1bp with qlrisk's bucket names (`5y`) and rejects unknown buckets (IM
  252,000, the 56bp SIMM weight). `qlrisk_ccr_exposure` no longer presents qlrisk's hard-coded zero CVA as
  an estimate (a warning points to `qlrisk_xva`); `qlrisk_risk_report` warns that `use_demo_book` ignores
  `market_data` and `history`. Plausibility tests check the tools against independent estimates
  (Black-Scholes, delta-normal VaR, SA-CCR and FRTB DRC by hand, CVA, Basel 2.5, SIMM, GBM moments).
- Added: **Domains** page (`/tools/domains`, Tools menu): one card per tool domain (tool folder, proxied MCP
  server, Unfiled) with the number of tools the viewer may see, readable labels, and a link to the Tools page
  filtered to that domain (`/tools?domain=<name>`, new). Labels come from one map in `sajha/tools/domains.py`
  (a folder it does not map is title-cased) ([Architecture §10](docs/architecture/Architecture.md#10-web-ui)).
- Changed: the landing page, `/help/tools` and Ask SAJHA's sky group tools by tool domain (as the Tools page
  does) instead of by name prefix; the landing hero says how many tools across how many domains, and a new
  "Out of the box" strip has a chip per domain with its live count, each opening the filtered Tools page
  through sign-in.
- Changed: the creators' and Import JSON's Folder field is optional and starts at **Unfiled** (the root of the
  tools directory); it lists Unfiled and the existing folders, and a new valid name creates the folder on save.
  `Unfiled` and empty both mean the root on the server, so `unfiled` is reserved as a folder name.
- Changed: the tools directory follows `config.tools.dir` (env `SAJHA_CONFIG_TOOLS_DIR`) everywhere: the
  Studio routes and generators, Ask SAJHA's config, the tool groups manager, the registry's default and the
  console's text no longer assume `config/tools`
  ([Configuration Reference](docs/getting-started/Configuration%20Reference.md#config)).

- Added: qlrisk risk tools as native tools in `config/tools/qlrisk/` (names `qlrisk_<tool>`, code in
  `sajha/tools/impl/qlrisk/`). Coarse-grained, read-only tools cover discovery, pricing and sensitivities,
  VaR / ES (historical, age-weighted, filtered, Monte Carlo, parametric; stressed VaR, decomposition,
  liquidity VaR), backtesting and PLA, P&L explain, stress (library, custom, reverse), FRTB SA and IMA,
  Basel 2.5, exposure and wrong-way risk, SA-CCR netting sets, ISDA SIMM, credit risk, XVA with SA-CVA and
  BA-CVA, Monte Carlo paths, the unified risk report and limit checks. Input schemas and enums are built
  from the installed qlrisk when a tool loads; results are `structuredContent` plus a one-line summary; work
  is bounded by the `qlrisk.*` keys (or a tool config's `bounds`). qlrisk is not on PyPI and not in
  `requirements.txt`: install its wheel (`requirements-qlrisk.txt`). Guide:
  [QLRisk Tool Reference Guide](docs/tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md);
  [Tutorial 41](docs/tutorials/TUTORIAL_41_qlrisk_risk_tools.md). The tests skip when qlrisk is not installed.
  Also one pricing tool per qlrisk product, `qlrisk_price_<product>`, whose inputs are only that product's
  fields; their configs are generated from qlrisk's product registry (`python -m sajha.tools.impl.qlrisk.generate`),
  and a test fails when they drift from it.
- Added: tool configs may declare `requires` (Python modules the tool needs). A tool whose module is
  missing is skipped (not loaded, not a failed tool, not in `tools/list`) with one info notice per missing
  module counting the tools; the failed-tool retry loop (`tools.retry_failed_seconds`) re-checks them, so
  installing the module loads them without a restart
  ([Architecture](docs/architecture/Architecture.md#tool-config-files-and-folders)).
- Changed: `POST /api/tools/execute` runs the tool in a worker thread, off the event loop, as `/mcp` does.
- Docs: the [Adversarial QA Plan](docs/architecture/Adversarial%20QA%20Plan.md) — every attack surface, what to try,
  the safe behaviour expected, priorities, automation and existing coverage, starting from the bugs this
  cycle found.

## v8.2.0 (October 2026) — streaming between servers, and tool folders

Wave 6 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md): protocol uniformity
between SAJHA Net members, and its security. A remote tool now behaves like a local one: progress, log
events, cancellation and input requests travel between servers as a signed event stream, every event
signed over the stream so far, and reach the client on whatever transport it uses. With it, tool configs
move into folders: every shipped tool now lives in a provider folder, the root keeps working, and a tool
name exists in exactly one place.

### Upgrading from 8.1.0

- **Tool folders:** every shipped tool moved from `config/tools/<name>.json` to
  `config/tools/<folder>/<name>.json`. Tool names are unchanged. Your own root files keep working; move
  them when you like with `python -m sajha.tools move` (move, never copy: a tool name may exist in one
  place only, and two files with one name disable both until one is removed).
- **Retrying failed tools:** `tools.retry_failed_seconds` (default 300) retries tools that failed to
  load; set 0 to turn it off.
- **Streaming between servers** is on by default (`sajhanet.streaming.enabled`); members without it keep
  the single signed JSON answer.
- **Dependencies:** `sse-starlette>=3.0.0,<4.0.0` (the install failed with the old pin).
- **Database:** no schema change since 8.1.0.

- Added (wave 6, phase 6.1): signed streaming between SAJHA Net members. A home asks for a stream in
  the signed body (`params._meta["io.sajha/net"].stream`) when the host lists `streaming`; the host
  streams progress and log events and the final answer as Server-Sent Events, every event signed over a
  running hash of the stream so far (protocol §8.9), so an injected, reordered, dropped, replayed or
  re-signed event is refused (`event_invalid`, `event_order`, `stream_truncated`, `stream_limit`,
  `stream_idle`), nothing after it reaches the caller, and the stream is closed (which cancels the
  host's tool). Cancellation from the caller closes the stream; limits `sajhanet.streaming.*`. Homes
  and hosts without the feature keep the single signed JSON answer.
- Added (wave 6, phase 6.2): progress and cancellation on every MCP client transport. A `tools/call`
  on 2025-11-25 Streamable HTTP with `_meta.progressToken` from a client that accepts SSE is answered as
  an SSE stream (JSON otherwise, as before); HTTP+SSE (2024-11-05) sends progress on the session's
  stream and takes `notifications/cancelled` on `/mcp?session=` and `/mcp/message`; WebSocket sends
  progress on the socket and takes `notifications/cancelled`; 2025-11-25 stdio writes progress lines.
  Local tools (`report_progress`) and remote SAJHA Net tools (their host's signed events) both reach the
  client under its own token. REST and A2A stay buffered. New `TransportToolContext` and
  `call_with_events` in `sajha/core/mcp_tool_context.py`. Conformance STR-06.
- Added (wave 6, phase 6.2): residency on streamed events. A tool with result data classes, or one a
  residency rule names, streams progress as numbers only and no log events: the host strips them before
  signing (rule `residency_events`), the home again on arrival (`residency.on_event`). Input responses
  sent back to a host (`inputResponses`) are checked like arguments. The SAJHA Net overview's recent
  forwarded calls show whether each streamed and how many events. Conformance STR-07.
- Added (wave 6, phase 6.3): input requests (MRTR) across SAJHA Net. A host tool that needs its caller's
  input answers `input_required` with a `requestState` the host signs and binds to the net, the sending
  server and the user (`<net>/<peer>/<user id>`), carrying the answers so far; the home keeps it inside
  its own signed state (`sajha.net`) and asks its 2026-07-28 caller; the answer goes back to the same
  host as a new signed request (residency checks `inputResponses` first), the user is resolved again,
  and a state presented by another server or for another user is refused before anything runs (new
  refusal `state_invalid`, `-32602`). Re-exporting intermediaries relay the question under their own
  state. 2025-11-25, REST and A2A callers get a tool error asking them to call over 2026-07-28. SAJHA
  (and its sponsored participants) now list `mrtr`. A task-augmented call at the home wraps the streamed
  call (`tasks/cancel` cancels the tool at the host); host-side tasks are deferred (Roadmap L19) and
  `tasks` is not listed. Conformance CALL-16 now runs (`tests/net/test_net_mrtr.py`).
- Added: tool folders. A tool config may be `config/tools/<name>.json` or
  `config/tools/<folder>/<name>.json` (one level; deeper files are ignored with the warning notice
  `tools.too_deep`). Folders file tools and never rename them. A name may exist in one place only:
  two files with one name load neither, with the critical notice `tools.duplicate:<name>`, until one
  is removed. `sajha/tools/tool_files.py` is the one map from names to files; edits, enable/disable,
  ownership, deletes, API Import and data connectors use it (an edit never moves a tool). Every Studio
  creator has a Folder field (the LLM tool creator defaults to `llm`, Describe a tool to its category,
  API Import to its prefix, a data connection to its id). New Studio page Import JSON (`/studio/json`,
  administrators): deploy a pasted or uploaded tool config into a folder taken from its `"folder"` key
  or `metadata.category`. `python -m sajha.tools folders | move <name-or-glob> --to <folder>
  [--dry-run]`. The Tools page groups tools by folder (root tools under "Unfiled", proxied servers by
  prefix); Admin > Tools and a tool's configuration page show the folder and file; `/api/tools/list`
  adds `folder`. Every shipped tool moved into a provider folder (`fmp`, `fred`, `yahoo`, `llm`,
  `sajha`, ...), content unchanged.
- Added: hot reload covers tool folders (new folders, changed and deleted files, removed folders, a
  duplicate resolved by removing a file), on the registry's poll and on every hot-reload check; the
  object-store sync manager now notices deleted objects. New `tools.retry_failed_seconds` (default
  300, 0 off): a tool that failed to load is retried without a change to its file, with doubling
  back-off up to 30 minutes, per worker.
- Fixed: a tool edited, enabled or disabled from outside the root of `config/tools` would have been
  written to the root path (the registry reduced every path to its file name); `python -m
  sajha.quality` read `config.tools_dir` instead of `config.tools.dir`; Admin > Tools never listed its
  tools (the template's `tools_metrics` was not passed).
- Fixed: a home that dropped a streamed forwarded call cancelled the host's tool only when the host's
  response generator was garbage collected (ASGI 2.4 servers report the drop as an error from `send`);
  `_serve_net` now closes the stream as soon as the response ends, so the tool stops at once.
- Changed: the units example server's `countdown` takes an optional `seconds_per_step` (default 0.05, at
  most 2), so Tutorial 40 can show a slow remote tool.
- Fixed: a `tools/call` over WebSocket ran on the event loop, so a slow or remote tool blocked every
  connection; it now runs in a worker thread as its own task (calls on one socket overlap).
- Fixed: `pip install -r requirements.txt` failed (`mcp` needs `sse-starlette>=3`); the pin is now
  `sse-starlette>=3.0.0,<4.0.0`.

### Upgrading

- **Tool configs:** nothing required. Files at the root of `config/tools` keep working, and the
  shipped tools now live in folders. A tool name in two files (root and folder, or two folders) now
  disables both until one is removed: move files (`git mv`, `mv`, `python -m sajha.tools move`),
  never copy them. Scripts that read `config/tools/<name>.json` directly should look one folder down
  too.

### Docs

- SAJHA Net Protocol: signed event streams on forwarded calls (§8.9 event chain, event signature and
  final binding; §15.6 for 2026-07-28 hops; new §15.10; stream refusals in §17, limits in §18, §19, the
  §21.4 test vector, decisions 38 to 42) and conformance ids SIG-14 (now S A L), STR-01 to STR-09 and
  CALL-16; CALL-11 and FB-07 now run.
- MCP Protocol Guide: "Progress and cancellation per transport" (§4). SAJHA Net: streaming on a call
  (§9), residency of streamed events (§12); §5.5 no longer lists STR-06 and STR-07. SAJHA Net Protocol
  §15.10: SAJHA applies the residency rule to streamed events.
- Phase 6.3: SAJHA Net Protocol §15.6 (the input-request round trip as built), §6.2 (SAJHA lists `mrtr`),
  §17.1 (`state_invalid`), CALL-16; SAJHA Net §5.5, §9 (event chain, input requests, tasks), §14, §16,
  §18 (stream tampering, replayed request state), §19; Configuration Reference rows for
  `sajhanet.streaming.*`; MCP Protocol Guide (remote tools in MRTR); glossary terms Signed event
  stream, Event chain and Transcript digest; Roadmap L17 removed (built) and L19 (host-side tasks)
  added; Implementation Plan wave 6 phases; new
  [Tutorial 40](docs/tutorials/TUTORIAL_40_stream_a_net_call.md): stream a call across the net.
- Tool folders: Architecture §5 "Tool config files and folders" (layout, one place per name, move
  don't copy, hot reload, retry) and §10 (the Tools page by folder); Command Line §6; MCP Studio User
  Guide (Folder field, Import JSON); API Import, Data Connectors, Tool Generation, Tool Quality, LLM
  Tools, Storage Guide, Configuration Reference (`tools.retry_failed_seconds`); tool reference guides
  and tutorials cite the moved paths; glossary terms Tool folder, Unfiled (tool) and Import JSON.

## v8.1.0 (October 2026) — sovereignty, the console and other MCP servers

Wave 5 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). SAJHA Net becomes
something a regulated organisation can adopt and other MCP servers can join: data residency with
redaction, planners and LLM tools across the net with one call-chain budget, re-export and bridges,
assertion and token-exchange identity, the full SAJHA Net console with a topology map, sponsored
members, the standalone SAJHA Net agent and conformance runner, third-party plug-ins, vendors and
proxied MCP servers (external ones are never members: the defining instance offers their tools as
`vendor__tool`), the standard mcpServers file with templates, console single sign-on and browser and
transport hardening. Open admission (no CA) is the shipped default; the docs were reviewed and
rewritten against the code, with eleven new tutorials and a local test lab; the deck redrawn with
native diagrams. SAJHA is proprietary software (see LICENSE).

### Upgrading from 8.0.0

- **Start script:** `run_server.py` is now `run_sajha_web.py` (same options).
- **Admission:** the shipped `sajhanet.plugins.admission` is `open` (no CA). Set `builtin_ca` to keep
  a CA; a net of one creates its CA at first start (`sajhanet.ca_auto_init`).
- **Tool names:** names containing `__` are refused unless the tool is namespaced (federated, external,
  SAJHA Net, connector). Rename any such local tool.
- **Dependencies:** `mcp>=2.3,<3` moved into `requirements.txt` (proxied MCP servers need it at run time).
- **Logging:** `logging.dir` and `logging.file` are honoured by the start script (shipped:
  `logs/server.log`).
- **Database:** no schema change since 8.0.0.

- Fixed: `sajhanet.peer_keys` written in `config/application.yml` is honoured (the loader flattens
  mappings, so only the `SAJHA_SAJHANET_PEER_KEYS` JSON worked). An instance name containing dots (an
  address name) must still use the environment variable.
- Fixed: raw-key records of `config/apikeys.json` reach the net key directory (by hash); test admin
  records are never published, so a host honours the test admin key only from its own file and switch.

- Fixed: an API-key caller's SAJHA Net calls were refused at the host (`key_unknown`): the home sent the
  key's name (`Caller.api_key`) as the key, and on REST the key presented with `X-API-Key` was lost
  because FastAPI authenticates in a worker thread. The home now forwards the key the caller presented
  (REST, MCP, A2A, the OpenAI-compatible API; owned and service keys), held in memory for the request
  only, else the user's default key; never a key name.
- Fixed: open mode, a server replaced on purpose could not rejoin. Forgetting a first-use key now also
  drops the member record, name lineage and cached certificates this server holds for the name; a name
  is learnt only from a live record, so a departed record another member holds no longer re-teaches the
  old key; and the refused server can retry (`POST /api/sajhanet/nets/{net}/rejoin`, or a restart in open
  mode) instead of holding its `name_conflict` refusal for ever. Recovery steps in
  [SAJHA Net](docs/architecture/SAJHA%20Net.md) §6.4 and Tutorial 31.
- Fixed: `first_use.json` (and the other per-net list documents) could be corrupted by concurrent first
  contacts ("Extra data"): they are read-modify-written under a lock and written atomically
  (`StorageBackend.write_json_atomic`: a temporary file renamed over the old one).
- Fixed: residency redaction corrupted text blocks by replacing a removed value inside other numbers
  (`"total_paid": 30[REDACTED…]`). A JSON text block is re-serialised from the redacted value; a value
  quoted in prose is replaced only as a whole token.
- Fixed: a call the home refused for residency before trying any host (every host excluded by a
  residency rule) wrote no `net.residency` record; it is now audited as `refused`, like the allows.
- Fixed: a bridge's call into another net always carried a user assertion and the host accepted it even
  where that net lists only `token_exchange` (or `api_key`). A bridge now uses the resolver the target
  net lists, and a host refuses an identity its net does not list, except the documented re-export relay
  within one net. Protocol §15.5, §15.2 and §16 say so.
- Fixed: Ask SAJHA's shortlist spent a slot on a SAJHA Net tool's plain alias and one on every qualified
  copy of it; one tool now takes one slot (the plain alias, which resolves across hosts).
- Fixed: a proxied MCP server whose prefix (by default its vendor) another upstream already used exposed
  no tools without saying so on the console; the clash is now an error notice `federation.prefix_clash`
  naming both and telling to set a `prefix`.
- Fixed: `run_sajha_web.py` always wrote `logs/server.log`, ignoring `logging.dir` and `logging.file`; it
  now honours them (empty `logging.file`: stdout only). The shipped `config/application.yml` sets
  `logging.file: server.log`, so the default log is unchanged.
- Fixed: "Your net access" offered a plain name that a disabled local tool still holds; it is no longer
  shown as an alias there.
- Changed: the official MCP SDK (`mcp>=2.3,<3`) moved from `requirements-dev.txt` to `requirements.txt`:
  federation imports it at run time.

- Fixed: tools of internal proxied MCP servers (`external: false`) are now offered into a member's nets
  under their federation names, like its own tools, as designed (one name, one contract applies to them);
  they were left out of the net catalog. External servers' tools are still offered only as
  `<vendor>__<tool>`.

- Fixed: per-member keys (`sajhanet.peer_keys`) now work as designed — the key is one the target
  member issued; the host checks it as its own API key and runs the call as that key's owner
  (audited as `peer_key`). Before, the host refused such a key with `key_not_from_home`.
- Fixed (security): open admission remembered a name's key before the message's signature, recipient
  and nonce were checked, so a forged message could claim an unused name. It now remembers a key only
  after a message signed with it fully verifies (`Trust.confirm`).
- Changed: the notice id `sajhanet.ca_created.<net>` is now `sajhanet.ca_created:<net>`, like every
  other id.

- **Upgrading:** the start script is renamed `run_server.py` → `run_sajha_web.py` (same options). Update service files, scripts and container commands that start SAJHA; the shipped Dockerfiles, Helm chart, systemd unit and docs are updated.

- Added: open mode, `sajhanet.plugins.admission: open` (owner decision, the shipped setting for now):
  SAJHA Net without a CA. Self-signed certificates are accepted the first time a name is seen and each
  name is then held to its key (an impostor is refused with `name_conflict`); remembered keys are kept
  in the storage backend (`<data_dir>/<net>/first_use.json`) and can be listed and forgotten
  (`/api/sajhanet/nets/{net}/first-use`). Specified as protocol §8.12. Set `builtin_ca` to
  use the CA. Fixed: a trust refusal for a held name now reports `name_conflict`, not
  `certificate_invalid`.
- Added: a net of one creates its CA at first start (`sajhanet.ca_auto_init`, default on; per net
  `ca.auto_init`; owner decision): audited, with a warning notice to back up the CA key. Peers can
  enroll without running `sajha net ca init` first.
- Docs: [SAJHA Net](docs/architecture/SAJHA%20Net.md) is rewritten as an as-built guide (admission
  modes and their trust, names, routing, identity with per-member and test admin keys, residency, the
  call-chain budget, re-export, the console, operations); §5.5 now lists only what is not built. The
  design note as it grew phase by phase, with its build plan, decisions and alternatives, is archived
  (`docs/archive/SAJHA Net Design Note.md`). The protocol specifies open mode (§8.12) and says what SAJHA
  advertises and does not implement; [Federation](docs/architecture/Federation.md) is the guide to proxied
  MCP servers (internal and external); the [Security Model](docs/security/Security%20Model.md) covers
  credential storage, the credential files, the test admin key, per-member keys and SAJHA Net admission
  as one whole; every SAJHA Net and credential notice id is in
  [System Notices](docs/architecture/System%20Notices.md).

### Vendors, external servers, the mcpServers file and self-recognition (wave 5, phase 5.4)

- Added: every SAJHA Net member names its **vendor**, the organisation that answers for its tools
  (`sajhanet.vendor`, default `sajha`, per net too; required on each `sajhanet.sponsored` entry and as the
  agent's `--vendor`). It is an optional `vendor` field of the member record and shows on the Instances,
  Remote tools and Net overview pages, in the status and topology data.
  [SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.6, protocol §5.5.
- Added: **external servers**: proxied MCP servers (federation upstreams) marked external are never
  members of a net; the SAJHA instance that defines them offers their tools as its own, published as
  `<prefix>__<tool>` (the prefix defaults to the vendor), with its full governance, so `search` of acme
  and of globex no longer meet on one name and are not quarantined. One name, one contract applies to
  the published name: two instances offering acme's identical tool are a fallback set; a different
  contract is quarantined, naming the host. Configured as `sajhanet.external_servers` or as entries of
  the mcpServers file. Catalog entries carry `vendor` and `external: true`; the console shows
  "external (via <instance>)". Export rules and tool blocks match the published or the local name; the
  host's audit records both (`local_tool`).
- Added: `rename` (`sajhanet.rename`, per net, on sponsored entries and external servers, the agent's
  `--rename`) offers a tool under a chosen short name, under the same rule. A tool whose qualified name
  would exceed 128 characters is not offered: warning notice `sajhanet.name:<net>:<tool>`, audit
  `tool_name_refused`, `refused_tools` in the views.
- Added: the **mcpServers file** `config/mcp_servers.json` (`federation.mcp_servers_file`, git-ignored;
  `config/mcp_servers.json.example` and the templates in `config/mcp_servers/`): paste the
  `{"mcpServers": {...}}` JSON of Claude Desktop, Cursor or VS Code. Each entry is an upstream, external
  unless `"external": false`; `vendor`, `prefix`, `tools`, `enabled`, `cwd`; `${NAME}` and
  `${NAME:default}` from the environment; raw credential headers work with an info notice; the YAML wins
  a duplicate id; reloaded on change. [Federation](docs/architecture/Federation.md#the-mcpservers-file).
- Added: an upstream that answers HTTP 401 without a credential (per-user OAuth sign-in, as Notion's and
  Supabase's hosted servers) shows as `needs_sign_in` ("needs sign-in (not supported yet)") with a
  warning notice `federation.sign_in:<id>` instead of failing silently; per-user OAuth to upstreams is
  roadmap L18.
- Changed: the console page and menu item Federation are now **Proxied MCP servers** (`/admin/federation`
  unchanged), with a table of every proxied server: name, vendor, internal or external, prefix,
  transport, status and tools.
- Added: a node **recognises itself**: a member record signed with its own key under another name, or
  naming its own URL under another name and key, is never added as a member (warning notice
  `sajhanet.self_seen:<net>`, audit `self_seen`); a seed or saved peer at its own address is skipped;
  sponsored participants sharing the sponsor's URL are unaffected. Identity never comes from an observed
  source address. Protocol §9.4 rule 7.
- Changed: a sponsored entry with `external: true` and the agent's `--external` are refused with a
  message pointing to external servers (both are members by definition); a net entry may not say
  `external`.
- Added: **proxies all the way down**: a call to a proxied MCP server carries its chain depth
  (`params._meta["io.sajha/chain"].depth`) and a SAJHA upstream continues from it, so a chain of
  proxies shares one budget (`tools.max_call_depth`) and a cycle (A proxies B proxies A) is refused at
  the limit instead of recursing. [Federation](docs/architecture/Federation.md#proxies-all-the-way-down).
- **Upgrading:** tool names containing `__` are now refused unless the tool is namespaced (a federated
  or external server's `<prefix>__<tool>`, a data connector's `<prefix>__<operation>`, a SAJHA Net remote
  tool): the registry refuses such a tool with an error notice `tools.reserved_name:<tool>`, and the
  creators (Studio, Describe, API import, workflows, the LLM tool builder) check it up front. Rename any
  such tool with a single `_`. Federation prefixes are unique across upstreams and external servers and
  never a local tool's name; a clash is a configuration error and the second is not loaded. Sponsored
  entries now need `vendor`.

### Console single sign-on, browser and transport hardening (wave 5, phase 5.3, roadmap X5 and X6)

- Added: **console single sign-on** with OpenID Connect (authorization code + PKCE, `sajha/auth/sso.py`,
  `GET /auth/sso/login`, `GET /auth/sso/callback`, `GET /api/auth/sso`), opt-in with `auth.sso.enabled`
  (default off) and alongside password sign-in, the users file and API keys. The ID token's signature
  (the provider's JWKS), `iss`, `aud`/`azp`, `exp`, `iat`, `nonce` and `at_hash` are checked; the state
  is single-use and bound to the browser. Claims map to SAJHA users (linked by `sub`, or by
  `auth.sso.user_claim` with `link_existing`; `auto_provision` creates them) and roles (`roles_claim`,
  `role_map`, `default_roles`, `sync_roles`, `require_role`). Sign-out also ends the provider session
  (`idp_logout`). Instances of a net that trust the same provider share one sign-in (`auto_redirect`).
  [Security Model](docs/security/Security%20Model.md#console-single-sign-on).
- Changed: the **Content-Security-Policy** uses a per-response nonce for scripts (`script-src 'self'
  'nonce-…'; script-src-attr 'none'`, plus `object-src 'none'`, `base-uri 'self'`, `frame-ancestors
  'self'`); `'unsafe-inline'` remains for styles only. Every inline script carries the nonce, and the
  console's inline event handlers became `data-on*` attributes run by `static/js/csp-actions.js`
  without evaluating script. `X-XSS-Protection` is `0`; HSTS is configurable (`security.hsts.*`).
  `scripts/check_mobile.py` and `scripts/check_console.py` now fail on CSP violations.
- Added: the **cross-site request check**: a cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE` from another
  site's `Origin` or `Referer` is refused with 403 on every route (`security.csrf.trusted_origins`); a
  test enumerates every state-changing route. Signing in now signs out the browser's previous session
  (session rotation). The session cookie's `Secure` is `auth.cookie.secure` and its lifetime follows
  `auth.jwt.expiry_minutes`.
- Added: transport settings: `server.max_request_bytes` (also enforced on streamed bodies without a
  `Content-Length`), `security.allowed_hosts`, `server.trusted_proxies`, and native TLS with
  `server.tls.certfile`, `server.tls.keyfile` and `server.tls.min_version`.
- Fixed: the WebSocket transport `/mcp/ws` applies the `/mcp` Origin allow-list before the upgrade;
  outbound HTTP calls in several data tools had no timeout; `/admin/tools` threw a script error when no
  tool had metrics.

### SAJHA Net: other MCP servers, the agent, the conformance suite and plug-ins (wave 5, phase 5.3)

- Added: **sponsored MCP servers**. A SAJHA server represents a plain MCP server (a federation upstream) in
  a net under an instance name of its own (kind `sponsored`, its member record naming the `sponsor`), with
  the sponsor's export rules, access, policy, residency and audit on every call; it shares the sponsor's URL
  and is reached by `Sajha-Net-To`. Configured in `sajhanet.sponsored` or through
  `/api/sajhanet/sponsored` (list, add, remove, enroll); shown in the status, Instances, topology and
  overview data. [SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.5.
- Added: **the SAJHA Net agent** (`sajhanet_agent/`, `python -m sajhanet_agent`): any MCP server, over stdio
  or Streamable HTTP, as a participant of kind `agent` (self-signed or CA-enrolled identity, gossip, catalog,
  forwarded-key verification against the net key directory, an export policy, signed calls), and **the
  reference library** it is built on (`sajha.net.library.NetParticipant`). Neither loads the SAJHA server
  (`tests/test_sajhanet_agent_boundary.py`). [SAJHA Net Agent](docs/clients/SAJHA%20Net%20Agent.md).
- Added: **the conformance suite runner**, `python -m sajha.net.conformance --target <url>|library`: every
  id of protocol §20 reported pass, fail or skip for a SAJHA instance, an agent, a sponsored participant or
  the library. A mixed net of all three passes it (`tests/net/test_net_mixed_conformance.py`).
- Added: **third-party plug-in registration**: `sajhanet.plugins.modules` and the entry-point group
  `sajha.net.plugins` are loaded at start; each plug-in must pass its contract check to be selectable, and a
  failure is an error notice and an audit record. Example: the routing strategy `region_first`
  (`sajha/examples/sajhanet/region_first.py`).
- Changed: importing the `sajha` package no longer loads the whole server (its top-level names load on first
  use), so the protocol core can be used on its own.
- Fixed: a signed `initialize` from a participant carries the net's extension object under
  `capabilities.experimental` (CAP-02) also for nets configured in code.

### SAJHA Net: re-export, identity resolvers and topology data (wave 5, phase 5.2)

- Added: **re-export** ([SAJHA Net](docs/architecture/SAJHA%20Net.md) §14, §5.5): with `sajhanet.reexport`
  on for the net offered into (per net too) and a `sajhanet.reexport_rules` entry naming the tool, an
  instance offers onward tools it imported. Within one net the tool carries `origin` and the host's
  contract; the caller's home sends a user assertion addressed to the origin, the intermediary verifies,
  maps and authorizes the caller and relays the assertion unchanged with hop 2 and the visited list (never
  a raw key); residency, `max_hops` and `sajhanet.max_call_chain` hold end to end, a tool never comes back
  to its origin and a chain never revisits an instance (`loop`). The feature `reexport` is advertised.
- Added: **bridges** between nets: a tool of net M re-exported into N is offered there as the bridge's
  own, and the bridge calls into M as the local user the caller maps to, with an assertion it signs in M.
- Added: the **`assertion`** and **`token_exchange`** identity resolvers (plug-ins beside `api_key`),
  selectable per net with `user_identity` (one or a list; the first the host lists is sent):
  `sajhanet.assertion.ttl_seconds`, `sajhanet.token_exchange.ttl_seconds`, the host's
  `POST /sajhanet/v1/token` (feature `token_exchange`, protocol §15.9), the header
  `Sajha-Net-User-Token` (covered by the request signature) and the refusal `-32013 token_invalid`.
  Per-member keys and the test admin key stay features of `api_key`, in the same order.
- Added: **`GET /api/sajhanet/topology`**: per net the instances and the `offers`, `reexports` and
  observed `calls` edges, for the console's topology map.
- Added: the identity, mapping, hops and visited list in the host's `net.host_call` audit record, the
  identity sent in the home's `net.call_attempt`, `net.token_issued`, and the resolver of each remote
  user in the users view. Conformance NET-05 and CALL-13 are covered, with the new CALL-14 (`assertion`)
  and CALL-15 (`token_exchange`).

### SAJHA Net: the console (wave 5, phase 5.2)

- Added: the **Net overview** (`/admin/sajhanet/overview`, JSON at `/api/sajhanet/overview`): per net,
  totals, a **topology map** (plain SVG from `/api/sajhanet/topology`, with a table equivalent, a pause
  for the live view and the members alone when the endpoint answers nothing), members and gossip
  health, open notices, quarantined and held tools with Approve, blocks, the admission panel, and from
  the audit chain the recent forwarded calls with trace ids, call-chain refusals and residency
  decisions ([SAJHA Net](docs/architecture/SAJHA%20Net.md) §17.5).
- Added: **Your net access** (`/net/access`, JSON at `/api/sajhanet/access`) for every signed-in user:
  each remote tool by name, its hosts in resolution order, and which of them the user may call.
- Added: the **admission panel** on the Net overview and SAJHA Net admin pages: in open mode the
  remembered first-use keys with Forget; in manual mode the pins (new `GET /api/sajhanet/nets/{net}/pins`),
  add and remove; on the CA instance issued certificates with Revoke, waiting tokens, Create token and
  Initialise. Runtime seeds can be removed from the admin page. Every change asks first.
- Added: the SAJHA Net menu entries for both pages, page help, help cards, glossary terms (Net overview,
  Topology map, Net access page, Admission mode, First-use key, Forwarded call) and the pages in
  `scripts/check_mobile.py`.

### SAJHA Net: residency (wave 5, phase 5.1)

- Added: **data classes**: `x-sajha-data-class` marks on schema fields (nested and array items too), a
  tool's own `data_classes`, and classification by configuration (`sajhanet.data_classes.tools`); each
  exported tool carries the summary in its net metadata.
- Added: **residency rules**, the policy conditions `data_classes`, `flow` and `destination` (net,
  instance, region, labels, here, `differs_from_here`), and `redact: {data_classes: [...]}` for
  field-level redaction ([Policy and Audit](docs/architecture/Policy%20and%20Audit.md) 3.5). Checked at
  the home before arguments leave (`-32012 residency_arguments`, executed false; a plain name falls back
  to a host that may receive the data), at the host before results leave (`-32012 residency_result`,
  executed true) and at the home as results arrive; `sajhanet.residency.enabled` and
  `sajhanet.residency.default_effect`.
- Added: **residency-aware shortlists**: a remote tool whose host may not receive the data every call
  sends is not eligible there (resolution order, `tools/list`, Ask SAJHA's shortlist).
- Added: **memory of remote results** by data class: `sajhanet.memory.remote_results` and
  `sajhanet.memory.by_class` (`store`, `summary` without figures, `none`).
- Added: the `net.residency` audit record for every decision on classified data, the metric
  `sajha_net_residency_decisions_total`, the feature `residency` in the extension, data classes on the
  Tools page and the Remote tools page. Conformance CALL-07 is covered.

### SAJHA Net: planners, LLM tools and the combined limit (wave 5, phase 5.1)

- Added: **locality-aware shortlists** (`sajha/ai/locality.py`): planners see local, remote and federated
  tools in one shortlist, local first, then remote hosts by `sajhanet.preferences`, same region, health
  and indicative latency; each `shortlist` event entry records `locality` with the reason in words;
  proxies of an unavailable host are not offered.
- Added: a **locality restriction** (`any`, `local`, `net:<name>`): `locality` on `POST /api/ai/ask`, the
  reserved planner setting `settings.locality` (accepted by every planner, in a file or a
  `planner_config` overlay), and `ai.ask.locality` (default `any`).
- Added: **remote LLM tools**: exported with `llm_tool: true` unless `sajhanet.allow_remote_llm_tools` is
  false (now read); they run on their host as the user with the host's models and budgets, and the host
  reports the spend in `_meta["io.sajha/net"].usage`, which the home records in `net.call_attempt` and
  never charges again.
- Added: the **combined hop and depth limit** `sajhanet.max_call_chain` (default 8, at most 32): hops plus
  tools nested in one another on every instance passed. Forwarded calls carry their nesting depth
  (`params._meta["io.sajha/net"].depth`); the host runs the tool with the incoming chain, so calls it
  makes onward carry the hop count and visited list (protocol §16); the home refuses before sending
  (`-32016` `loop`, `hop_limit`, `chain_limit` with `hops`, `depth` and `limit`) and the host on receipt
  (`chain_limit`, a new reason of `-32016`; CALL-08 extended).

## v8.0.0 (October 2026) — SAJHA Net core

Wave 4 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). SAJHA servers form
a net and share tools while each keeps its own data, rules, AI and memory: several named nets per
server, a CA run by SAJHA, signed requests on the normal port, gossip membership, automatic proxy
tools (`net__host__tool`), one name one contract, waterfall fallback, the caller's identity on every
call, blocks, linked audit, the Instances page and a three-instance demo. A server with no peers is a
net of one. Credentials follow the owner's intranet settings (plain storage, administrators' files).

### Upgrading from 7.3.0

- **Database:** new table `sajhanet_api_keys` and column `api_keys.key_value`. PostgreSQL: run what
  `python -m sajha.db upgrade-sql` prints. SQLite development: recreate the database.
- **Credentials:** `auth.credential_storage` defaults to `plain`; `config/apikeys.json` and the
  returning `config/users.json` win over the database; `config/apikeys_db.json` is written every 10
  minutes. The test admin key and account ship **enabled** (`sajhanet.test_admin_key.enabled: true`,
  owner decision) with a critical notice while active: disable it before production.
- **SAJHA Net** is off unless `sajhanet.enabled` is set; see Tutorial 28 and
  `deployment/sajhanet-demo/`.

### SAJHA Net: Instances page, navbar badge, Remote tools, the net of one (wave 4, phase 4.3)

- **Changed (owner decision):** a net entry with no seeds is a **net of one**: this server is its
  founder and only member, joined at once with no "not joined" error notice, no join retries and no
  gossip; it grows into an ordinary net when a peer joins through it or is added by address, without a
  restart. The rule "seeds are required unless `founder: true`" is withdrawn (protocol §9.7 and GOS-12,
  the Helm chart's render check). A net of one may initialise its CA (`sajha net ca init`) without
  `ca.enabled`; until it has a certificate an info notice says how to give it one.
- Added: the **Instances** page for every signed-in user (`/net/instances`, `/net/instances/{net}/{instance}`,
  `/net/instances/this`; JSON at `/api/sajhanet/instances`): every participant with kind, region, labels,
  state, last seen and how many of its tools the user may use here, with search and filters, and each
  instance's tools (alias, description, inputs and outputs, health, latency) with Try it. This server is
  always listed, as a net of one when SAJHA Net is off.
- Added: the navbar badge `Net · <instance name>` with a health dot (`+N` for further nets), linking to
  Instances; a SAJHA Net menu.
- Added: the admin's **Remote tools** page (`/admin/sajhanet/tools`): the host and tool table with
  filters, approve and withdraw for tools held under `review` trust, and the contract conflicts.
- Added: the three-instance test net, in process (`tests/net/test_net_three_instances.py`) and as
  containers (`deployment/sajhanet-demo/`, a compose file, a README and a smoke script), and Tutorial 28,
  "Build a SAJHA Net".
- Fixed: a forwarded call ran at the host without the local account's roles' permissions (the access
  policy was built without the host's database), so a host refused every remote user who was not an
  administrator; it now uses the host's database.
- Fixed: a peer that gave up on a request (a probe past its ping timeout) left a stack trace in the
  host's log; `/sajhanet/` now answers such a request quietly.
- Docs: [SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.5 lists the protocol's conformance ids SAJHA's
  tests cover and those that remain; §4's rows for the per-user cache key and the outbound `traceparent`
  now say they are built.

### Credentials: files, plain storage, test admin, per-member keys (owner decisions)

- **Upgrading:** `auth.credential_storage` defaults to `plain` — new and changed passwords and API keys
  are stored as given (existing bcrypt / hashed values keep working). Set `hashed` and run
  `python -m sajha.auth rehash` to harden. New column `api_keys.key_value` (PostgreSQL: run what
  `python -m sajha.db upgrade-sql` prints; SQLite development: recreate the database).
- **Upgrading:** precedence changed — keys in `config/apikeys.json` now win over the database (it
  was the other way round), and `config/users.json` (administrators' users) is back: it wins over the
  database and is applied to it at start-up and on every change.
- Added: `config/apikeys_db.json`, the database's keys dumped every 10 minutes, used when the database
  does not know a key or is down; admin pages `/admin/apikeys/file` and `/admin/users/file`.
- Added: test admin records (`"test_admin": true`) in both files, honoured while
  `sajhanet.test_admin_key.enabled` (on for now; critical notice while active); SAJHA Net calls carry
  the test admin key while it is on. Disable before production.
- Added: `sajhanet.peer_keys`, keys this server uses toward particular members (local only).

Wave 4 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md), phase 4.1: stream A,
SAJHA Net membership ([SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.5 says what is built), and
stream B, changes to existing code that SAJHA Net builds on (§21.1 items 2, 5, 6, 9, 12 and 13).

### Upgrading

- **Federated tool names:** a `.` in an upstream tool's name now becomes `_`
  (`v1.convert` is exposed as `<prefix>__v1_convert`), so the name is valid for every LLM
  provider. Update API-key allowlists or role patterns that named such a tool with its dot.
  Two upstream names that map to one exposed name are both refused (before, the first won).
- **Federated annotations** are corrected rather than copied: `openWorldHint` is always
  `true`, non-boolean hints and unknown keys are dropped, and `destructiveHint` is dropped for
  a read-only tool.
- **New table `sajhanet_api_keys`** (the SAJHA Net key directory) with two indexes. PostgreSQL: run
  what `python -m sajha.db upgrade-sql` prints before starting (`db.schema_check: strict` refuses to
  start without it). SQLite for development: SAJHA creates it.
- **Policy source `sajhanet`:** forwarded calls a host runs for a remote user carry the policy source
  `sajhanet`, so policy rules can match them (`sources: [sajhanet]`).
- **Federated schemas** must be valid JSON Schema (2020-12) object schemas: a tool whose
  `inputSchema` or `outputSchema` is not is listed as `invalid`, with the reason, and is not
  exposed.

### Added

- **SAJHA Net identity and authorization** (phase 4.2, stream D; [SAJHA Net](docs/architecture/SAJHA%20Net.md)
  §5.5 says what is built): the `api_key` identity resolver (the caller's own key, or a console user's
  default key from the vault, travels to the host, which verifies it against the net key directory and
  checks it came from its home); the net key directory (`sajhanet_api_keys`, signed records synced by
  `digests.keys` and digest comparison, tombstones, revoked certificates' records discarded, records of
  departed homes unusable); users across instances (links, name matching, `sajhanet.users.unknown`
  `refuse`/`map_roles` with role maps, `sajhanet.users.remote_admin`); export and import rules and the
  key's tool access as a ceiling (rule evaluator `policy_engine`); blocks at four levels with expiry,
  audit and a signed blocks document published through `digests.blocks`; linked audit records; notices
  for key-directory sync failing and blocks against this server; an identity and access section on
  `/admin/sajhanet` and its admin API (`/api/sajhanet/nets/{net}/blocks`, `/users`, `/role-maps`,
  `/name-matching`, `/keys`). Net settings refuse callers that arrived through the net.
- **SAJHA Net Protocol fix:** a key record's `tool_access_mode` may also be `regex` (SAJHA keys support
  it); the meaning of `owner.user_name` (the login name) is stated.
- **SAJHA Net catalogs and routing** (phase 4.2, stream C; [SAJHA Net](docs/architecture/SAJHA%20Net.md)
  §5.5): participants exchange catalogs (`POST /sajhanet/v1/catalog`, pulled on a new digest,
  incarnation or run, with `if_none_match`), every tool complete with a contract hash; a hash that
  does not match is not imported and the peer flagged; schemas checked, text screened and capped;
  trust levels `auto`, `review` (approvals) and `pinned`. Remote tools become proxy tools in the
  registry under qualified names (`<net>__<instance>__<tool>`) and bare aliases, with
  `_meta["io.sajha/net"]`; a plain name resolves local first, then `sajhanet.preferences`, then the
  nets in order. A host's tools disappear the moment it is `left` or `dead`, are `unavailable` while
  it is `suspect`, and after a restart nothing remote is listed until the peer answers. One name, one
  contract: a tool whose hosts disagree is quarantined everywhere, the local copy included, with an
  error notice naming the differing host and the first differing JSON Pointer, a signed conflicts
  document (`POST /sajhanet/v1/conflicts`), the `sajha_net_contract_conflicts` metric and audit
  records; it re-activates by itself. Calls are forwarded as signed `tools/call` requests on the
  MCP endpoint (hop and loop checks, `executed: false` on every refusal before execution) with
  waterfall fallback (`sajhanet.max_fallbacks`) and per-peer breakers, rate limits, timeouts and
  connection pools. Admin API: `/api/sajhanet/tools`, `/conflicts`, `/catalogs`, trust and
  approvals. The Tools page shows net badges and local, remote, net and instance filters; the Ask
  page's "Servers and tools" log names the host of a remote tool.
- **SAJHA Net membership** (off by default, `sajhanet.enabled`): servers join named nets, several
  per server, kept apart on the normal port by the signed `Sajha-Net-Name` header. The protocol
  core is `sajha/net/` (it imports nothing else from SAJHA): names and qualified names, RFC 9421
  request and response signatures with RFC 9530 digests and replay protection in the state store,
  JSON Schemas of every `/sajhanet/v1/` message, RFC 8785 record signatures, the plug-in
  interfaces of the design with a registry, `package.module:Class` and the entry-point group
  `sajha.net.plugins`, and a contract check per interface. Membership is SWIM gossip (ping,
  ping-req, suspicion, refutation, dissemination, anti-entropy, leave, dead probing) with required
  seeds (`founder` exempt), restarts through the saved peer list (`peers.json`, local disk), and one
  gossip agent per net and instance through the renewing state-store lease. Names are configured or
  `<ip>:<port>`; a name belongs to its certificate lineage and a different key claiming it is
  refused with `409 name_conflict`, an error notice and the `sajha_net_name_conflict` metric. The
  CA is run by SAJHA, one per net: `sajha net ca init | enroll | revoke | show`, enrollment with
  single-use tokens refused for held names, renewal with a new key, a signed revocation list spread
  by gossip; manual mode pins self-signed certificates. Administrators add a peer by address
  (`/admin/sajhanet`, `POST /api/sajhanet/nets/{net}/peers`, `sajha net peers add`), optionally kept
  as a runtime seed. Notices for not joined, name conflicts, member state, certificates, renewal,
  stale revocation lists, peers added and plain HTTP. Keys: `sajhanet.*` in the
  [Configuration Reference](docs/getting-started/Configuration%20Reference.md#sajha-net); routes in
  the [API Reference](docs/protocol/API%20Reference.md) §4.24. No schema change.
- **SAJHA Net Protocol fixes** found while building it: a join sync to a seed or an operator-given
  address carries `Sajha-Net-To: *` (its name is not known yet); a renewed certificate carries the
  renewed serial in an extension so members can follow a name's lineage; the enrollment answer
  omits `"signature";req` (the request is unsigned) and is bound by the CSR's key; §8.9 says the
  emptied `_meta` objects stay; the §21.2 example covers `sajha-net-name`.
- **`io.sajha/net` on both eras:** with `sajhanet.enabled` the extension is advertised in
  `server/discover` (`capabilities.extensions`) and in the 2025-11-25 `initialize` result
  (`capabilities.experimental`), reduced for requests not signed by a participant; clients'
  declarations are read from either place (`sajha/core/net_extension.py`).
- **Federation `on_change: hold`:** per upstream, the previously approved version keeps
  serving while a changed definition waits for review (default `withdraw`, as before).
- **Schema validation of imported tools:** new status `invalid` on the federation page and in
  its API (`items[].reason`); approving such a tool is refused.
- **Cancellation reaches the upstream from the 2025-11-25 era:** `notifications/cancelled`
  cancels the named in-flight `tools/call` (HTTP with a session, and stdio), relayed between
  workers through a shared state store; a federated call then cancels its upstream request
  (`sajha/core/mcp_cancellation.py`). `is_cancelled()` reports it to any tool.
- **SAJHA Net peer URL guard:** `check_peer_url` and `sajhanet.allowed_networks` (CIDRs),
  separate from `federation.allow_private_networks`; loopback and link-local are never allowed.
- **Helm:** `sajhanet` values (nets, instance names, advertise addresses, Secrets for
  certificates and keys, allowed networks, NetworkPolicy rules); the chart refuses several pods
  with a net that has no instance name or advertise address.

## v7.3.0 (October 2026) — planners, authoring and the OpenAI endpoint

Wave 3 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). Planning
strategies become configuration files with bounded loops; authors get an LLM tool creator, a
planner editor and per-creator permissions; SAJHA can serve any OpenAI-style client; every LLM
call in SAJHA goes through one package, one factory and one governed proxy.

### Upgrading from 7.2.0

- **Custom LLM providers:** `sajha/ai/gateway.py` and `sajha/ai/providers/` are gone. Build
  providers on `ProviderBase` from `sajha.ai.llm.spi`; application code uses
  `llm_factory().model(...)` only (enforced by `tests/test_llm_boundary.py`).
- **Planners:** the built-in names (`react`, `plan_execute`, `recipes`, `router`) now resolve to
  the shipped planner files in `config/planners/`, with the same behaviour; set
  `ai.planners.python_builtins: true` to keep the Python classes. LLM tools without
  `llm.planner` use `ai.planners.default`.
- **Studio permissions:** permissions per creator (`studio:<creator>`, `studio:*`); an existing
  `studio` permission still means every creator. New installs seed an `llm_author` role.
- **OpenAI-compatible endpoint:** off unless `ai.openai_api.enabled` is set.

### Added

- **Studio LLM tool creator** (`/studio/llm`, LLM Tools build step 10): a form for the `llm` block
  (mode, model alias, system prompt or library prompt, template, allowed and denied tools with a
  live matching preview, limits within the `ai.llm_tools.limits` ceilings, memory, planner and
  `planner_choices`, sampling, output, cache) with input and output schemas generated per mode;
  the config is checked by the loader's own rules (`parse_llm_block`, catalog and lint), run once
  on the mock model, and deployed or edited as `config/tools/<name>.json`.
  [Guide](docs/studio/MCP%20Studio%20LLM%20Tool%20Creator%20Guide.md).
- **Planner editor** (`/studio/planners`, administrators only): the registry's planners and the
  files it refused (with the last good version in use), a planner file checked as you type
  (JSON Schema and P-rules, each finding with its rule and location), a graph of stages and
  transitions with bounded edges marked, a dry run through `POST /api/ai/planners/dry-run` that
  highlights the stage path, and saving new versions (the replaced one kept as `name@version`).
  [Planner Reference §14.1](docs/architecture/Planner%20Reference.md#141-the-planner-editor).
- **Describe a tool proposes LLM tools** (kind `llm`): summarise, classify, extract, an assistant
  over named tools, or questions answered from document search; the `llm` block is checked by the
  LLM-tool loader, its tests run on the mock model, and it goes through the same review and
  deploy gate. [Tool Generation](docs/architecture/Tool%20Generation.md).
- **Conversations page** (`/conversations`, **AI → Ask**): a user's own conversations with Ask
  SAJHA and each LLM tool that remembers: open, continue in Ask (`/ask?conversation=<id>`),
  delete one or all. Administrators also see stored conversations per scope, counts only
  (`GET /api/ai/conversation-counts`).
- **Console end-to-end and accessibility checks** (Roadmap X15): `scripts/check_console.py` signs
  in, asks, builds and deploys an LLM tool, dry-runs a planner and opens the Conversations page in
  Chromium, then scans the pages with axe-core (WCAG 2.x A and AA) or a documented rule subset.
  Fixed what it found: the "About this page" guide link no longer sits inside its `<summary>`, the
  table's rows-per-page select has a label, scrollable regions on the new pages take focus.

- **SAJHA as an OpenAI-compatible endpoint** (opt-in, `ai.openai_api.enabled`):
  `POST /v1/chat/completions` (JSON or SSE chunks), `GET /v1/models`, `GET /v1/models/{model}` and
  `POST /v1/embeddings`, authenticated with a SAJHA API key as the bearer token. Calls run as the
  key's owner through the gateway (role policy, budgets, cache, fallback, usage and cost), the
  policy engine sees them as `openai_api.chat_completions` / `openai_api.embeddings` (source
  `openai_api`) so rules can rate-limit them, errors are OpenAI-shaped, and each enabled LLM tool
  the caller may run is the model `sajha:<tool>` (conversation handle in the `sajha` field).
  Tested with the official `openai` SDK. [LLM Tools §13.4](docs/architecture/LLM%20Tools.md#134-sajha-as-an-openai-compatible-endpoint).
- **MCP sampling for LLM tools:** `llm.sampling: prefer | require` on `complete`, `extract`,
  `classify` and `judge` tools sends the model call to a client that declared sampling: an MRTR
  input request on 2026-07-28, a server request on the session's SSE stream on 2025-11-25.
  Without one, `prefer` uses SAJHA's model and `require` refuses (`code: sampling_required`).
  Sampled calls cost SAJHA nothing (usage ledger provider `client`) and skip the result cache.
  [LLM Tools §12](docs/architecture/LLM%20Tools.md#12-models-sampling-budgets-and-limits).
- **Configurable planners** (LLM Tools build steps 4 and 5): a planner is a file,
  `config/planners/<name>.yaml`, a versioned graph of stages from a fixed library (`act`, `plan`,
  `execute`, `call`, `match`, `classify`, `draft`, `critique`, `revise`, `verify`, `sample`,
  `vote`, `foreach`, `planner`, `ask_user`, `condense`, `answer`, `fail`) with conditional and
  bounded transitions and a small `when` expression language. Files load with plain
  `yaml.safe_load`, are validated against rules P001–P071 and the JSON Schema of the Planner
  Reference, reload on change and keep their last good version when an edit fails. The service
  still enforces everything; planners only propose. Twelve strategies ship as files: the four
  built-ins (`react`, `plan_execute`, `recipes`, `router`, behaving as before) plus `rewoo`,
  `reflect`, `verify_then_answer`, `self_consistency`, `branch_and_judge`, `map_reduce`,
  `human_in_the_loop` and `auto` (a cheap classifier over the allowed planners that escalates
  once when a check fails). LLM tools take `llm.planner` as `name`, `name@version`, an inline
  definition or an overlay, and `llm.planner_choices` (an enum on an optional `planner`
  argument); resolution is version route, caller choice, tool config, `ai.planners.default`.
  `ask_user` asks over MRTR on 2026-07-28 and ends `needs_input` elsewhere; new `stopped_by`
  values `failed`, `needs_input` and `stage_limit`. Per-stage events on the ask stream (the Ask
  SAJHA page shows the path), metrics `sajha_planner_*`, the planner, version and stage path in the
  audit record, `kind: python` files and custom stage types registered in code, and an admin dry
  run on the mock model (`POST /api/ai/planners/dry-run`). Lint reports planner files.
  [Planner Reference](docs/architecture/Planner%20Reference.md), [Tutorial 27](docs/tutorials/TUTORIAL_27_write_a_planner.md).

### Changed

- **Studio permissions per creator, and ownership** (Roadmap X2). A role's `studio` permission now
  names the creator it opens (`studio:python`, `studio:rest`, `studio:api_import`, `studio:dbquery`,
  `studio:script`, `studio:powerbi`, `studio:powerbidax`, `studio:livelink`, `studio:sharepoint`,
  `studio:olap`, `studio:composite`, `studio:describe`, `studio:llm`); `studio:*`, which the
  existing `studio` rows already are, keeps opening all of them. The planner editor is admin only.
  A Describe a tool deploy also needs the permission of the kind deployed. Every Studio deploy
  records its creator (`metadata.created_by`; composites and API imports their `created_by`), and
  a non-admin may change or delete only what they created. The Studio menu shows only the
  creators a caller may use. New installs also get an `llm_author` role (`studio:llm`).
  [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md#permissions).

- **One LLM package boundary** (wave 3, phase 3.2). Every LLM is reached through `sajha.ai.llm`
  behind OpenAI-style signatures, and all provider and model specifics live in `sajha/ai/llm/`,
  one module per provider. `LLMProvider` and `LLMModel` are abstract base classes every provider
  implements (the shared implementations are `ProviderBase`, `ChatModel`, `EmbeddingModel`).
  `llm_factory()` returns the `LLMFactory`, which builds providers from `ai.providers`,
  `ai.aliases` and the registry; `factory.model(alias)` returns a `GovernedModel` proxy that
  applies policy, budgets, cache, retries, breakers, fallback, audit, usage and tracing (the
  former gateway) before delegating to the provider's model; `factory.provider(name)` serves the
  admin pages. Every caller outside the package moved to the factory and the canonical types
  (memory, document search, embedders, the tool resolver, connectors, LLM tools, Describe a tool,
  the OpenAI-compatible endpoint, quality evals, the AI routes); `tests/test_llm_boundary.py`
  fails on a vendor SDK, a private module, direct construction or a pre-canonical type outside
  the package. [Intelligence Layer](docs/architecture/Intelligence%20Layer.md), [LLM Tools §13.7](docs/architecture/LLM%20Tools.md#137-one-package-boundary).
- LLM tools' derived `readOnlyHint` is false when a tool they may call cannot be found in the
  registry (it was treated as read-only).
- The `Planner` protocol (`sajha/ai/planners.py`) and `IntelligenceService` speak the canonical
  Chat Completions types: `PlanState.messages` are `ChatMessage`s, `ShortlistEntry.tool` is a
  `ToolDefinition`, `CallTools` carries `ToolCall`s (`ToolCall.of(id, name, arguments)`),
  `state.chat` takes a `ChatCompletionRequest` (`state.request(...)` builds one) and returns a
  `ChatCompletion`. A Python planner written against the old types needs those edits;
  `CallTools` still accepts objects with `id`, `name` and `arguments`.

### Upgrading

- **Studio permissions:** nothing to do; existing `studio` rows (`resource_name` `*`) keep opening
  every creator. To give a role one creator, add a `permissions` row (`studio`, `<creator>`, `use`).
  Studio tools deployed before this record no creator, so only administrators may change or
  delete them. The `llm_author` role is seeded on new databases only; add it to an existing one
  with the two rows in `db/scripts/<dialect>/seed.sql` if you want it.

- **Import paths for LLM code changed.** `sajha.ai.gateway` and `sajha.ai.providers` are gone:
  `get_gateway()` / `init_gateway()` / `build_gateway()` are `llm_factory()` /
  `init_llm_factory()` / `build_llm_factory()` in `sajha.ai.llm`, and a call is
  `llm_factory().model(alias).chat_completions_create(...)` (the factory also takes
  `model=` like an OpenAI client). The gateway's `complete`, `complete_messages` and
  `list_all_models` are removed (use `chat_completions_create` and `models()`). `sajha.ai.llm`
  no longer exports the pre-canonical types (`ChatRequest`, `Message`, `ToolSpec`, ...) or the
  registry helpers.
- **Custom providers:** subclass `ProviderBase` and import it, `ChatModel`, `EmbeddingModel`,
  `HTTPChatModel`, `register_provider`, `register_model`, `ModelCapabilities`, `ProviderConfig`
  and the HTTP helpers from `sajha.ai.llm.spi`. `sajha.ai.llm.LLMProvider` is now the abstract
  base class, so a class that subclassed it for its implementation must switch to
  `ProviderBase`; a class that leaves an abstract method unimplemented is refused at
  registration. Pre-6.x providers import `LegacyLLMProvider` (formerly
  `sajha.ai.providers.LLMProvider`) and `register_provider_class` from `sajha.ai.llm.spi`.
  Class paths in `ai.providers[].class` and entry points are unchanged.
- New configuration section `ai.openai_api` (`enabled: false`, `llm_tools`, `cookie_auth`,
  `max_body_bytes`). Nothing changes until it is turned on.
- The policy source list gains `openai_api`.
- New configuration section `ai.planners` (`dir`, `default`, `python_builtins`, `limits.*`, ...).
  `ai.ask.planner` and `ai.ask.planner_config` keep working: the names resolve to the shipped
  files, whose settings have the same keys and defaults. `ai.planners.python_builtins: true`
  runs the four built-ins' Python classes instead.
- An `answer`-mode LLM tool that names no `llm.planner` now runs `ai.planners.default` (`react`)
  rather than `ai.ask.planner`, as LLM Tools §9.12 specifies; `sajha_ask` still follows
  `ai.ask.planner`.
- The ask event stream gains `planner_chosen`, `stage_start`, `stage_end`, `loop_exhausted` and
  `expression_error` events; clients that switch on event types and ignore unknown ones are
  unaffected. The `AskResult` gains `planner_version`, `planner_path`, `loops_exhausted`,
  `planner_by` and `input_request`.

## v7.2.0 (October 2026) — the model interface and LLM tools

Wave 2 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). SAJHA's model
interface becomes the OpenAI Chat Completions format end to end; LLM tools (tools whose work is
done by a model, configured like any tool) arrive with seven modes, per-tool memory and resource
safety; `sajha_ask` becomes one of them; document search gets a pluggable, disk-based store with
sqlite-vec as the default and reads PDF and Word.

### Upgrading from 7.1.0

- **Database:** `ai_conversations` gains `tool_name` and `expires_ts` plus two indexes.
  PostgreSQL: run what `python -m sajha.db upgrade-sql` prints. SQLite for development: recreate
  the database.
- **Document search store:** `ai.rag.store: auto` now means sqlite-vec (its own file,
  `data/rag/vectors.db`) when the `sqlite-vec` package loads, otherwise the in-memory store with a
  notice; it no longer picks pgvector by itself — set `ai.rag.store: pgvector` to keep using it.
  Install `sqlite-vec` (in `requirements.txt`). The index rebuilds itself on first start.
- **LLM tools:** the type is on; the shipped example tools are disabled; `sajha_ask` is now
  `config/tools/sajha_ask.json` and still switched by `ai.ask.mcp_tool_enabled`.
- **Optional packages:** `pypdf` and `python-docx` to index PDF and Word files.

### Upgrading

- **Database:** new columns `ai_conversations.tool_name` and `ai_conversations.expires_ts`, and
  indexes `ix_ai_conversations_user_tool_updated` and `ix_ai_conversations_expires`.
  PostgreSQL: run the statements `python -m sajha.db upgrade-sql` prints (SAJHA never runs DDL
  there). SQLite for development: recreate the database (the start-up check prints the
  statements if you prefer to add the columns).
- **Document search store:** `ai.rag.store: auto` (the default) now means the new sqlite_vec
  store (`data/rag/vectors.db`, created on first build; `pip install -r requirements.txt` brings
  `sqlite-vec`), else the memory store. It no longer picks pgvector by itself: a deployment that
  used pgvector sets `ai.rag.store: pgvector`.

### Document search: pluggable stores, sqlite-vec by default

- `ai.rag.store` chooses the store by configuration alone: `sqlite_vec`, `memory`, `pgvector`, a
  store registered through the new `sajha.rag.stores` entry-point group, or
  `package.module:Class`; per-store settings live under `ai.rag.stores.<name>` (env
  `SAJHA_AI_RAG_STORES_<STORE>_<KEY>`). The store contract (`VectorStore`, now with
  `keyword_search`, `create`, `probe` and `close`) has a contract test suite every shipped store
  passes (`tests/ai/test_rag_store_contract.py`; pgvector with `SAJHA_TEST_POSTGRES_URL`).
- New `sqlite_vec` store (`sajha/ai/rag/sqlite_vec.py`): a SQLite file of its own, never SAJHA's
  database, in WAL mode; sqlite-vec `vec0` for the vectors, FTS5 for the keywords, so both halves
  of the hybrid search run on disk and only the top k rows reach Python. The embedder and
  dimension are recorded: a new embedding model rebuilds the index cleanly. When the extension
  cannot load, `auto` uses the memory store and raises the System Notice `rag.store_fallback`
  with the reason.
- pgvector keyword search runs in PostgreSQL (full-text search) instead of an in-process BM25
  index over every row; the optional schema section shows a GIN index for it.
- Leaner indexing: documents are read one at a time and passages are embedded
  `ai.rag.embed_batch_size` (default 64) at a time while the store consumes them. The memory
  store keeps vectors as float32 arrays (about half the memory of before).
- Queries are embedded with the `query` purpose (passages keep `document`).
- `GET /api/ai/docs/status` adds `chunks`, `dimensions`, `store_configured` and `store_fallback`.

### LLM tools: the tool type, seven modes, resource safety; `sajha_ask` moved onto it

- **The LLM-tool type** (`sajha/ai/llm_tools/`, [LLM Tools](docs/architecture/LLM%20Tools.md)): a
  tool config with `implementation: sajha.ai.llm_tools.LLMTool` and an `llm` block is a tool whose
  work a model does. Modes `answer` (the intelligence service's planner loop over the allowed
  tools), `complete`, `extract` (output validated against the schema, one retry with the errors),
  `classify` (one enum label), `grounded` (answers only from document-search passages, with
  citations; `no_sources` when nothing is found), `narrate` (runs a composite or published
  workflow as the caller; the model writes the text) and `judge` (rubric scores, verdict computed
  by SAJHA). The loader refuses a block that cannot work and lint reports why (`llm-config`,
  `llm-catalog`, `llm-annotations`); annotations are derived from the tools the model may call.
- **Runs as the caller:** the model is offered the tool's `tools.allow − tools.deny` intersected
  with what the caller may execute; every inner call goes through the normal tool path. Nesting
  needs `nesting.allow`, is capped by `ai.llm_tools.max_depth` and shares the outer run's time and
  cost. Anonymous callers are refused unless `ai.llm_tools.anonymous.enabled`.
- **Conversation memory** per the tool's `memory` block (`conversation_id` in and out, or client
  history); **caching** of deterministic modes with `cache: true`.
- **Resource safety:** at most `ai.llm_tools.runtime.max_concurrent_runs` runs per process and a
  bounded queue, then `stopped_by: busy` (REST 503 with `Retry-After`); tool results larger than
  `spill_threshold_kb`, or past a run's `working_set_max_kb`, spill to `data/spool/llm_tools/<run>/`
  (deleted at run end; a janitor removes orphans); a memory guard (cgroup-aware) sheds caches and
  spills at the soft limit, refuses runs and ends running ones at their next step
  (`memory_pressure`) at the hard limit. System Notices `llm_tools.memory`, `llm_tools.busy`,
  `llm_tools.spool_full`; new `sajha_llm_tool_*` metrics ([Observability](docs/architecture/Observability.md)).
- **Results and errors** follow LLM Tools §15: error `stopped_by` values return `isError: true`
  over MCP and `success: false` over REST. Each run writes an `llm_tool_run` audit record with the
  trace id its inner `tool.call` records share.
- **Shipped examples, disabled:** `llm_markets_assistant`, `llm_summarise`, `llm_triage_ticket`,
  `llm_docs_qa`, with eval sets `config/evals/llm_*.yaml`; an eval set can now name an LLM tool
  (`tool:` and per-question `arguments`). The mock answers every mode offline.
- New `ai.llm_tools.*` settings (ceilings; [Configuration Reference](docs/getting-started/Configuration%20Reference.md)).
- [Tutorial 26: Build an LLM Tool](docs/tutorials/TUTORIAL_26_build_an_llm_tool.md).
- **Operator notes for `sajha_ask`:** it is now the LLM tool `config/tools/sajha_ask.json`
  (disabled in the file; `ai.ask.mcp_tool_enabled` still turns it on, at start-up and after each
  reload). It still runs as the caller and `ai.ask.mcp_allowed_tools` still narrows it. Its result
  adds `conversation_id` and `caveats`; pass `conversation_id` back to continue. Not built yet:
  configurable planners and sampling (wave 3).

### Conversation memory for LLM tools

- `ConversationMemory.open()`, `record()` and `from_client()` (`sajha/ai/memory.py`): the
  conversation handle of [LLM Tools](docs/architecture/LLM%20Tools.md) §10 (create when absent,
  continue when owned, `conversation not found` for an unknown, expired, another user's or another
  tool's id), per-tool scoping, idle expiry (`ttl_minutes`, renewed each turn), turns beyond
  `max_turns` folded into the summary and deleted, and `client` history mode. Anonymous callers
  get nothing stored.
- Questions are now clipped to `ai.memory.max_turn_chars` like answers, and a turn reads only the
  verbatim window instead of every turn of the conversation.
- A scheduled purge (`ai.llm_tools.memory.purge_interval_minutes`, default 15) runs on one worker
  per interval; it also enforces `ai.llm_tools.memory.max_conversations_per_tool` and can
  `VACUUM` SQLite (`sqlite_vacuum`). New metrics `sajha_llm_tool_conversations`,
  `sajha_llm_tool_turns_total`, `sajha_llm_tool_purged_total`.
- `GET /api/ai/conversations` takes `?tool=<name>` (or `*`); without it, it lists the Ask SAJHA
  page's conversations as before.

### Documents as RAG sources

- PDF and Word (`.docx`) files in `ai.rag.sources` folders and uploads, read through the
  optional packages `pypdf` and `python-docx` (commented in `requirements.txt`); without them
  those files are skipped and the index build names the package to install. Uploads take
  `content_base64` for them. A PDF or Word file is hashed on its bytes, so an unchanged one is
  not even extracted on re-index.

### The canonical model interface: OpenAI Chat Completions

Wave 2 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md), stream A:
[LLM Tools](docs/architecture/LLM%20Tools.md) §13 (except 13.4, the outward endpoint) and the
Roadmap's X9.

- **One format.** `sajha/ai/llm/canonical.py` types the Chat Completions request, response,
  stream chunk and embeddings shapes; SAJHA-only data rides in a `sajha` field (the caller's
  identity, cost, cache hit, fallback attempts, trace id, and the markers `ignored`,
  `usage_estimated`, `structured_output`). Fields are supported, passed through to
  OpenAI-compatible servers only, or refused with `invalid_request` naming the field, as §13.6
  settles.
- **OpenAI-style interfaces.** Models: `chat_completions_create`, `chat_completions_stream`,
  `achat_completions_create`, `achat_completions_stream`, `embeddings_create`, `info()`.
  Providers: `models()` (`ModelInfo`, today's `ModelCapabilities` extended with JSON mode, strict
  tools, named tool choice, parallel-call control, seed, stop sequences, reasoning effort, native
  `n` and variable embedding size) and `model(name)`. The gateway: the same methods plus
  `models(ctx)`, with policy, budgets, cache, retries, breakers and fallback as before. The
  original `chat` / `stream` / `achat` / `embed` and `generate` / `stream` / `embed` keep working
  through lossless converters (`sajha/ai/llm/convert.py`).
- **Adapters at the edge.** Every built-in provider translates the canonical format (OpenAI,
  Azure OpenAI, Mistral and the presets as a pass-through; Anthropic, Gemini, Bedrock, Cohere,
  Ollama natively), and the mock speaks it. New request fields: `developer` role, `top_p`,
  `seed`, `n`, `reasoning_effort`, per-request `parallel_tool_calls` and `strict`,
  `response_format: json_object`, `stream_options.include_usage`, `user` and `metadata` (audit
  only), and embeddings `dimensions`, `encoding_format: base64` and `sajha.input_purpose`.
- **Nothing dropped silently.** OpenAI's `refusal` is kept (refusals from every vendor become
  `finish_reason: content_filter` with `message.refusal`); a forced or named `tool_choice` on a
  model that cannot honour it (Ollama, catalogue flag `f`) is refused instead of becoming `auto`;
  Cohere takes a named choice only when it is the one tool offered; a temperature left out is
  named in `sajha.ignored`; a vendor's `error` finish (Gemini `MALFORMED_FUNCTION_CALL`, Cohere
  `ERROR`/`TIMEOUT`) raises the new `ModelFailed` and the gateway tries the next candidate;
  query embeddings use the query input type (Cohere `search_query`, Gemini `RETRIEVAL_QUERY`) —
  tool search and vector connectors pass it. A model with JSON mode but no schema output gets
  `json_schema` emulated (validated, one retry), marked `structured_output: "emulated"`.
- **Native async** for every HTTP provider (`httpx.AsyncClient` per event loop); the gateway's
  `achat_completions_create` / `achat_completions_stream` retry and fall back without threads.
- **Vertex AI** for Gemini and Claude (`platform: vertex`), and **Entra ID** for Azure OpenAI
  (`auth: entra`: client secret, AKS workload identity or managed identity), with tokens cached
  and refreshed before expiry (`sajha/ai/llm/cloud_auth.py`); new keys in the
  [Configuration Reference](docs/getting-started/Configuration%20Reference.md#aiproviders), and
  `ai.gateway.max_samples` caps `n`.
- **Tests.** Golden translation tests per provider against recorded vendor payloads
  (`tests/ai/test_golden_translation.py`, `tests/ai/golden/`), a portability suite through the
  mock and every adapter offline (`tests/ai/test_portability.py`), and `tests/ai/test_canonical.py`.
- **Extending.** [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md)
  is rewritten around the new interfaces; a provider over HTTP implements `wire`, `parse` and a
  `StreamTranslator` on `HTTPChatModel` and gets sync, streaming and native async I/O. The Acme
  example, the risk-model example and the recipe planner example moved to the canonical format.

## v7.1.0 (October 2026) — foundations

Wave 1 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md): the groundwork
LLM tools and SAJHA Net build on, and the release hygiene the Roadmap listed as "Now". API keys
belong to users and every user has one; tools called from inside other tools run as the caller;
every tool call is in the tamper-evident audit chain; the console shows what needs attention;
sign-ins can be revoked; snapshots record users, keys and tools; the test suite runs in CI.

### Upgrading from 7.0.0

- **Database:** new columns `users.token_version` and, on `api_keys`, `is_default`, `persistent`,
  `created_by`, `rotated_at`, `revoked_at`, `revoked_by`, `secret_ciphertext`, `secret_key_id`.
  PostgreSQL: run the statements `python -m sajha.db upgrade-sql` prints (SAJHA never runs DDL
  there). SQLite for development: recreate the database; the start-up check prints the statements
  if you prefer to add the columns.
- **API keys:** existing keys keep working exactly as before until an administrator assigns them
  an owner; an owned key then signs in as its owner with the owner's roles, its own tool list as a
  ceiling. Every user gets a default key at start-up.
- **Files:** `config/users.json` is removed (users live only in the database).
  `config/apikeys.json` is now hashed persistent keys only and git-ignored; a plaintext file in
  the old format is ignored with a warning; see `config/apikeys.json.example`.
- **Audit volume:** every tool call is now an audit record (about 0.9 KB each); review
  `audit.tool_calls.*` sampling and your SIEM routing and retention.
- **Snapshots** are on by default (`snapshots.*`, every 10 minutes, last 20 kept, in
  `data/snapshots`).
- **Rate limiting:** the unused per-user and per-key limiters are removed; use policy
  `rate_limit` rules.
- **Federation cache:** federated tools cache per user by default
  (`cache.per_user_federated`).

### System notices

- **System notices**: one service (`sajha/notices/`) every subsystem reports conditions into,
  each under a stable id with a severity, an audience (`admin` or `everyone`) and a ttl. Notices
  live in the state store, so every worker sees the same set; every transition (raised,
  escalated, acknowledged, cleared) is an audit event; `notices.max_active` bounds them.
- **In the console**: a banner on every page (the most severe unacknowledged error or critical
  notice the viewer may see), a **System status** panel on the dashboard (grouped by severity,
  acknowledge for administrators, recently cleared on demand) and a navbar badge that also shows
  on phones; kept live by server-sent events.
- **API**: `GET /api/notices`, `GET /api/notices/stream`, `GET /api/admin/notices`,
  `POST /api/admin/notices/{id}/acknowledge` and `/clear`.
- **First sources**: the database schema check, open circuit breakers (tool providers, federated
  upstreams, LLM providers), workflows whose scheduled runs keep failing, LLM model aliases with
  no available model and failing providers, federated servers down and tools held for approval,
  and alert rules through the new `notice` channel. `notices.forward` also sends notices through
  the alert channels (log, webhook, email).
- Configuration: `notices.*` (enabled by default; nothing to do on upgrade). Guide:
  [System Notices](docs/architecture/System%20Notices.md).

### Audit, tracing, cache and leases

- **Every tool call is in the tamper-evident audit chain** as a `tool.call` record: caller, API
  key, roles and auth type, tool, outcome, duration, trace id, source surface (and MCP era), and
  a SHA-256 of the arguments, not their values (`audit.tool_calls.arguments: redacted` stores
  them with secrets and personal data masked; `none` stores neither). SIEM sinks receive the
  records like any other. Volume control: failures, policy outcomes and destructive tools are
  always recorded; successful calls can be filtered (`include_tools`, `exclude_tools`) and
  sampled (`success_sample_rate`, per-tool `sample_rates`); skipped calls are counted in
  `sajha_audit_tool_calls_skipped_total`. Design and as-built:
  [Policy and Audit §13](docs/architecture/Policy%20and%20Audit.md#13-tool-calls-in-the-audit-chain).
  The record is hashed on the calling thread and stored by a background flusher
  (`audit.chain.flush_interval_ms`, `flush_batch`), so the call does not wait for the database:
  about 38 µs per call measured on SQLite (about 120 µs if stored synchronously). Chain
  verification is unchanged and passes.
- **Outbound W3C `traceparent`** on the HTTP calls SAJHA makes: federated `tools/call`
  (`params._meta.traceparent`), API-import tools, REST-creator tools (newly generated), LLM
  providers, connected-account requests, HTTP vector-store connectors and webhooks. It works
  without the OpenTelemetry SDK: SAJHA continues an inbound context or starts one per request
  ([Observability §3.3](docs/architecture/Observability.md#33-outbound-trace-context)).
- **Per-user tool cache keys:** `"cache_per_user": true` in a tool's config adds the caller to
  the cache key. Federated tools default to it (`cache.per_user_federated: true`; an upstream's
  `cache_per_user` overrides it).
- **Renewing state-store lease:** `lease_claim`, `lease_renew`, `lease_release` and
  `lease_holder` on every state backend, and `sajha.core.state.lease.Lease`, which renews in the
  background and reports loss
  ([Scaling and State §4.7](docs/architecture/Scaling%20and%20State.md#47-leases)). The one-slot
  claims of workflow cron and quality probes are unchanged.

**Operator notes**
- **Audit volume grows.** Each tool call adds one `audit_chain` row (about 0.9 KB on SQLite),
  so a million calls a day is about 1 GB a day, and the same number of records goes to each SIEM
  sink. Before upgrading a busy server, decide on sampling or exclusions for high-volume
  read-only tools (`audit.tool_calls.*`), size SIEM sink `queue_size` for the call rate, and plan
  retention: SAJHA never deletes chain rows; remove whole old chains once they are safe in the
  SIEM (Policy and Audit §13.4). `audit.tool_calls.enabled: false` restores the old volume.
- Tool-call records not yet flushed when a process is killed are lost (at most one flush
  interval); verification then reports that chain as not closed, as for any crash.
- **Federated tools with `cache_ttl` now cache per calling user** (a lower hit rate when many
  users ask the same thing). Set `cache_per_user: false` on an upstream whose answers do not
  depend on the caller to share results as before.
- No schema change.

### Release hygiene and snapshots

- **The schema check prints the SQL to run.** When tables, columns or indexes are missing, the
  start-up message lists the statements taken from the dialect's `schema.sql`: `CREATE TABLE`
  (with its indexes), `ALTER TABLE ... ADD COLUMN` (PostgreSQL: `... IF NOT EXISTS`) and
  `CREATE INDEX`. Missing indexes alone only warn. With `db.schema_check: warn` the same SQL is
  in the `db.schema` system notice. SAJHA prints the statements; it never runs them. An older
  SQLite file whose tables break `schema.sql` as a whole still gets its missing tables (the
  statements are retried one by one). For a development SQLite database the advice stays:
  recreate it.
- **`python -m sajha.db upgrade-sql`** (also `sql --missing`) compares the configured database
  with its `schema.sql` and prints the DDL an operator reviews and runs; exit 3 when there is
  something to run ([Database Setup §4](docs/getting-started/Database%20Setup.md#4-upgrades)).
- **The test suite runs in CI** (`.github/workflows/tests.yml`): `tests` and `clientsdk/tests`
  on every push and pull request to develop and main, with a PostgreSQL service so the schema
  tests apply the real PostgreSQL file. `requirements-dev.txt` lists the test-only packages.
- **Snapshots of users, API keys and tools.** Every `snapshots.interval_minutes` (default 10)
  one worker writes a signed, chained JSON snapshot to `snapshots.dir` (default
  `data/snapshots`, owner-only, git-ignored) and keeps the last `snapshots.keep` (default 20):
  users without password hashes, roles, API key records (hashes only for persistent keys) and
  local tools with a hash of their schemas. Writes, rotations, failures and restores are audit
  records. `python -m sajha.snapshots list|verify|diff|show|restore`; `restore` re-creates
  missing roles, users (each with a new default key) and persistent key records after confirmation
  ([Policy and Audit §7.5](docs/architecture/Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools)).

**Operator notes**
- **`config/users.json` is retired.** Nothing read it (users live in the database), but it was
  hot-reload watched and held a plaintext `admin123`. The watch, the `config.users.path` key and
  the unused users importer are gone; delete any copy you made from it.
- **One rate limiter.** The unused per-user and per-key limiters in `sajha/security.py`
  (`check_user_rate_limit`, `check_key_rate_limit`) were removed: they were never called, so no
  limit changes. Tool calls are limited only by policy `rate_limit` rules;
  `config/policies/00-default.yaml` now carries a commented per-user and per-API-key example
  ([Security Model](docs/security/Security%20Model.md#rate-limiting-and-lockout)).
- **Snapshots are on by default** and write a file every 10 minutes under `data/snapshots/`;
  `snapshots.enabled: false` turns them off. With several workers on `state.backend: memory`
  every worker writes its own; use `redis` or `database`.
- No schema change from this section.

### Identity and API keys

- **Tools called from tools run as the caller.** `sajha_ask` and composite steps now run their
  inner tool calls as the original caller, with no more than the caller's tool access: a step or
  inner call the caller may not execute is refused. The caller context
  (`sajha/observability/caller.py`) now carries the caller's tool access; a call chain
  (`sajha/core/inner_calls.py`) refuses cycles and chains deeper than `tools.max_call_depth`
  (default 8). `sajha_ask` no longer runs as the fixed identity `mcp:sajha_ask`.
- **API keys belong to users.** A key with an owner signs in as that user, with the user's
  roles (an administrator's key is an administrator); its tool access mode and list are an extra
  ceiling. Keys are created with an owner. Users manage their own keys on the new **My API keys**
  page (`/account/apikeys`, user menu): create, rotate, revoke, and **sign out everywhere**.
  Administrators manage every key on a rebuilt **API keys** page (`/admin/apikeys`, new key and
  key detail pages): owner, rotate, disable, revoke, persistent, delete; new JSON routes under
  `/api/account/apikeys` and `/api/admin/apikeys`. Key management needs a signed-in user, never
  an API key; browser requests carry a CSRF token.
- **Revocation record:** revoking a key sets `revoked_at` and `revoked_by`; the key never works
  again and the row stays.
- **A default key for every user**, created with the account and, at start-up, for every
  account without one. It can be rotated (by the user or an administrator) or disabled (by an
  administrator), never revoked or deleted. Its value is kept encrypted with the connected-accounts
  vault key (AES-256-GCM), so the server can act for the user with it later; the user sees it
  once after each rotation.
- **Persistent API keys:** keys an administrator marks persistent are also kept, as SHA-256
  records, in `config.apikeys.path` (default `config/apikeys.json`), which is checked after the
  database (the database wins for a key it knows), rewritten atomically with mode 0600 and
  re-read when it changes on disk. The format is in `config/apikeys.json.example`.
- **Revocable sign-in:** signing out (`GET /logout`, new `POST /api/auth/logout`) revokes that
  token (its `jti`, in the state store); every SAJHA JWT and built-in OAuth access token carries
  the user's token version (`tv`), so "sign out everywhere" (`POST /api/auth/sessions/revoke`), a
  password change (other sessions), an administrator's password reset and the new
  `POST /api/admin/users/{uid}/sessions/revoke` (Users page) end every session, and the user's
  OAuth refresh tokens stop refreshing.
- Configuration: `auth.api_keys.max_per_user` (default 25), `tools.max_call_depth` (default 8);
  `config.apikeys.path` is now the persistent key file. Guide:
  [Security Model](docs/security/Security%20Model.md#api-keys).

**Operator notes**
- **Database (both dialects): new columns.** PostgreSQL: run before starting this release
  (`python -m sajha.db upgrade-sql` prints the same):
  ```sql
  ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE api_keys ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE;
  ALTER TABLE api_keys ADD COLUMN persistent BOOLEAN NOT NULL DEFAULT FALSE;
  ALTER TABLE api_keys ADD COLUMN created_by VARCHAR(100);
  ALTER TABLE api_keys ADD COLUMN rotated_at TIMESTAMPTZ;
  ALTER TABLE api_keys ADD COLUMN revoked_at TIMESTAMPTZ;
  ALTER TABLE api_keys ADD COLUMN revoked_by VARCHAR(100);
  ALTER TABLE api_keys ADD COLUMN secret_ciphertext TEXT;
  ALTER TABLE api_keys ADD COLUMN secret_key_id VARCHAR(64);
  ```
  An existing SQLite database needs the same columns (`BOOLEAN NOT NULL DEFAULT 0`, `TIMESTAMP`);
  start-up stops and prints the statements until they are added.
- **How existing API keys behave.** Every key that exists today has no owner, so it keeps
  exactly its current behaviour (identity `apikey:<name>`, role `api_consumer`, its own tool
  access mode) until an administrator assigns an owner on the API keys page, which lists and
  counts the keys without one. From then on the key signs in as that user, with the user's
  roles, its mode as a ceiling: check the owner's roles before assigning. Workflows owned by
  `apikey:<name>` keep running as that key; once the key is revoked they stop, as for a disabled one.
- **Default keys appear** for every existing account at the first start-up (they need the vault
  key: `accounts.vault.key`, `SAJHA_ACCOUNTS_VAULT_KEY`, a `key_provider`, or the key SAJHA
  generates into the server secrets file; several hosts must share it). Nobody has seen their
  values; users rotate a default key to get one.
- **`config/apikeys.json` is no longer tracked.** Its four plaintext demo keys were never read
  (and are not carried over); it is now git-ignored and holds only hashed records. An old
  plaintext file left in place is ignored with a warning and replaced on the first persistent-key
  change.
- **`ai.ask.mcp_allowed_tools` now narrows instead of widening** what `sajha_ask` may run for a
  caller: it can no longer give an anonymous MCP caller tools the anonymous policy does not.
- **Signing out now revokes the token.** With `state.backend: memory`, only the process that
  handled the sign-out knows; run `redis` or `database` with several workers. Tokens issued
  before the upgrade carry no token version and count as version 0, so nobody is signed out by
  the upgrade.

## v7.0.0 (October 2026) — governance, intelligence and operations

Everything since 6.0.0. It finishes the items 6.0.0 deferred (MCP
authorization with OAuth 2.1, MCP Apps, `x-mcp-header`), closes the security gaps a full audit
found, and adds what running a shared tool catalog for real needs: governance (policy engine,
tamper-evident audit, connected accounts), new ways to build tools (API import, Describe a tool,
data connectors, federation, workflows), tool quality, an intelligence layer with planners,
memory and document search, horizontal scale, observability, Kubernetes, and a console that
works on phones. The map of what owns what is
[How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md).

### Breaking changes and operator actions

Read this list before upgrading from 6.0.0.

**Database**
- **PostgreSQL: SAJHA never creates or alters tables.** Before starting this release, run
  `db/scripts/postgresql/schema.sql`, then `db/scripts/postgresql/seed.sql`, with `psql`
  (`python -m sajha.db sql --dialect postgresql` prints them). At start-up SAJHA checks every
  table and column it uses and refuses to start, naming what is missing and the command
  (`db.schema_check: strict`; `warn` starts anyway). 6.0.0's PostgreSQL scripts never worked, so
  there is nothing to migrate. Re-running `schema.sql` is safe (`CREATE ... IF NOT EXISTS`) and is
  how the tables this release adds are created ([Database Setup](docs/getting-started/Database%20Setup.md)).
- **SQLite database from 6.0.0:** new tables are created at start-up, but one column is new on an
  existing table and must be added by hand, or start-up stops at the schema check:
  `ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;`
  (`python -m sajha.db check` lists anything else missing).
- New tables in both schema files: `sajha_state`, `sajha_state_events`, `obs_usage_events`,
  `connected_accounts`, `audit_chain`, `audit_anchors`, `ai_conversations`,
  `ai_conversation_turns`, `workflows`, `workflow_runs`, `workflow_run_steps`, `quality_runs`;
  the optional pgvector `rag_chunks` table is a commented section at the end of the PostgreSQL
  file. `db/scripts/*/001_schema.sql` and `002_seed.sql` are gone. The never-used tables
  `tenant_users`, `rate_limit_log`, `llm_usage` and `user_ai_preferences` are no longer created
  (existing ones are left alone).
- **`tool_versions` table removed** from both schema files and the ORM models: nothing ever read
  or wrote it (tool versions live in `config/tool_versions/*.yaml`). Existing databases may keep
  it; it is unused and can be dropped by hand (`DROP TABLE tool_versions;`). SAJHA never drops it.
- **Tenancy removed.** Tenant records were stored but never enforced (no request path consulted
  their tool patterns or quotas), so they are gone rather than half working: `sajha/core/tenancy.py`,
  the `TenantRecord` model, the `tenants` table in both schema files and the admin routes
  `GET`/`POST /api/tenants` and `GET`/`PUT`/`DELETE /api/tenants/{tenant_id}` (now 404). Roles,
  API-key tool access and policy rules separate teams
  ([Security Model](docs/security/Security%20Model.md#tool-access)). Existing databases may keep
  the `tenants` table; it is unused and can be dropped by hand (`DROP TABLE tenants;`). SAJHA
  never drops it.

**Secrets and sign-in**
- `config/application.yml` ships no JWT or session secret. Empty secrets are generated once into
  `data/secrets/server_secrets.json` (`auth.secrets_file`, mode 0600, git-ignored); JWTs signed
  with the old placeholder stop working, so users sign in again. A secret (or
  `mcp.mrtr.state_secret`) equal to any placeholder SAJHA ever shipped stops start-up; the MRTR
  secret derives from the persisted session secret, so `requestState` survives restarts. Several
  hosts must share the secrets file or set the variables, and share the OAuth signing key
  (`mcp.auth.builtin.signing_key_pem` for hosts without a shared data directory).
- The seed `admin`/`admin123`, admin-set passwords and default passwords are flagged
  `must_change_password` and show a banner until changed. `POST /api/admin/users/create` now
  requires a password that passes the policy (8+ characters, no well-known defaults).
- Sign-in: account lockout (423) and a per-IP failure limit (429) on the web form,
  `POST /api/auth/login` and the OAuth sign-in replace the old 5-per-minute limit on the JSON login.

**Who can see and run what**
- **Anonymous MCP and A2A callers see and run no registry tools, prompts or data resources by
  default.** List what they may use in `mcp.anonymous.tools`, `mcp.anonymous.prompts` and
  `mcp.anonymous.resources` (fnmatch), grant a role with `mcp.anonymous.role`, or refuse them with
  `mcp.anonymous.enabled: false`. The anonymous agent card has no skills.
- **Credentials that are sent but do not authenticate are rejected** (401 on `/mcp` and
  `POST /a2a`, close code 1008 on `/mcp/ws`) instead of running as anonymous, in every
  `mcp.auth.mode`. A stale web cookie alone still counts as no credentials.
- **The REST catalog and the REST mirrors of MCP methods need credentials:** `GET /api/tools/list`,
  `/api/tools/{tool}/schema`, `/api/tool-groups/*`, `GET /api/prompts/list`,
  `GET /api/prompts/{name}`, `POST /api/resources/list|read` and `POST /api/completion/complete`
  answer 401 where `/mcp` would, and list only what the caller may see.
- One tool-access policy (`sajha/auth/access.py`) for REST, MCP (both eras, SSE, WebSocket, stdio),
  A2A and async: API-key allowlist, denylist and regex modes are now enforced; external OAuth
  identities without an account get the role named `api_consumer` (none exists by default).
- Unauthenticated API/JSON requests (`/api`, `/mcp`, `/a2a`, `/admin/studio`, `/oauth`, any
  non-GET, or `Accept: application/json`) get a JSON 401 instead of a redirect; 403s there are JSON.
- Admin only now: `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`,
  `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity`, the tool configuration page and
  a tool schema page's resolved configuration; the shell endpoints need admin or `shell:execute`;
  MCP `logging/setLevel` changes the server log level only for admins.
- Async execution needs admin or `async:execute` plus tool access; file delivery only inside
  `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls` (empty,
  the default, refuses every webhook).
- **MCP Studio is open to the `developer` role.** Every Studio page and endpoint (`/studio/*`,
  `/admin/studio/*` including Describe a tool and Import an API, `/api/studio/*`) and creating a
  composite now need the admin role or the `studio` permission (`require_studio`); the seeded
  `developer` role's `studio` row, never checked before, now grants it, and the navigation shows
  Studio to those users. Developers can deploy and delete Studio tools and deploy Describe a tool
  proposals through the same policy-engine gate (add a `studio.deploy` rule to narrow it); they see
  only their own Describe drafts and change or delete only composites they created. Admin only
  still: deploying Python code or script tools while `sandbox.enforce_for_generated_tools` is
  `false`, sandbox configuration, federation, connectors, policies, approvals, audit and users.
  Remove the `studio` row from `developer` (or the role from users) to keep Studio admin-only.

**Tools behave differently**
- **Tool arguments are validated against the tool's JSON Schema** before it runs: a mismatch is
  `-32602` on 2026-07-28, an `isError` result on 2025-11-25, 400 on `POST /api/tools/execute`.
- **Studio Python code tools and script tools run in the sandbox**, not in the server: no server
  environment, no network unless the tool's `sandbox` block allowlists hosts, a script's
  `working_directory` is ignored. `sandbox.enforce_for_generated_tools: false` restores in-process
  loading.
- **OLAP tools** accept only dimensions and measures declared on the dataset in
  `config/olap/datasets.json` (raw column names are refused); each OLAP tool runs only its own
  operation (`_tool_name` is refused).
- **`duckdb_*` tools** run one parser-checked `SELECT`/`EXPLAIN` on in-memory copies of the data
  files with external access off; table and column names must exist; `having` is
  `<name> <op> <value>` conditions; `duckdb_analytics.db` is no longer written.
- **FBI tools** call the current Crime Data Explorer API with new input and output schemas
  (`fbi_search_agencies` needs `state`). **FRED** tools return the newest observations first.

**Configuration and removals**
- Storage environment variables (`SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`,
  `AZURE_STORAGE_CONNECTION_STRING`, ...) now override `application.yml`. `.env` names that are
  not settings no longer stop start-up. `async.*` and `shell.*` keys now take effect.
- Several workers on `state.backend: memory` get a start-up warning: shared state needs `redis`
  or `database` ([Scaling and State](docs/architecture/Scaling%20and%20State.md)).
- Removed: the top-level `oauth:` block in `config/application.yml` (never read; MCP authorization
  is `mcp.auth`), `sajha/core/auth_manager.py` and `sajha/core/apikey_manager.py`, the legacy SSE
  `Last-Event-ID` replay, a second unreachable `GET /health`.

### Protocol and clients

- **OAuth 2.1 for `/mcp`** (`mcp.auth.mode`: `off`, the default, `optional` or `required`).
  Resource server: RFC 9728 protected-resource metadata, `WWW-Authenticate` with
  `resource_metadata` and `scope`, audience-bound RS256 access tokens, scopes `mcp:read` /
  `mcp:tools`. Authorization server built in (SAJHA users; authorization code + PKCE S256, RFC 9207
  `iss`, Client ID Metadata Documents with SSRF guards, rotating refresh tokens with reuse
  detection, CSRF-protected consent) or an external issuer through its JWKS. API keys and SAJHA
  JWTs keep working in every mode; the signing key is generated under `data/oauth/`. Conformance
  `authorization` suite 3/3 for both spec versions; the server suites unchanged (43/43, 152/152);
  the official SDK completes the flow end to end. [OAuth Guide](docs/protocol/OAuth%20Guide.md).
- **MCP Apps** (`io.modelcontextprotocol/ui`): tools bind `ui://` views served by `resources/read`
  as `text/html;profile=mcp-app` (`mcp.apps.enabled`, default on); example view for
  `calc_loan_amortization`. **`x-mcp-header`** is validated when a schema loads (invalid
  annotations dropped with a warning); `Mcp-Param-Symbol` on the quote tools.
  [MCP Apps and Headers Guide](docs/protocol/MCP%20Apps%20and%20Headers%20Guide.md),
  [MCP 2026-07-28 Compliance §4](docs/protocol/MCP%202026-07-28%20Compliance.md).
- **MCP over stdio** (`sajha/cli/stdio.py`; `python run_server.py --stdio`, `sajha serve --stdio`)
  for Claude Desktop, Claude Code and IDEs: both eras on one connection, nothing but protocol on
  stdout, `notifications/cancelled` honoured, `list_changed` pushed; one caller per process
  (`--user` / `SAJHA_STDIO_USER`, `--api-key` / `SAJHA_API_KEY`, else anonymous); the LLM gateway
  only with `--with-ai`. Tested with the official SDK client in `legacy` and `auto` modes.
- **The `sajha` command line** (`pip install './clientsdk[cli]'`): `login` (token stored 0600 in
  `~/.config/sajha`), profiles, `tools list|show|call`, `prompts list|get`, a streamed `ask`,
  `studio deploy|delete|import-openapi|describe`, `federation list|add|refresh|remove`,
  `workflows list|run|runs|show`, `db check|sql`, `health`, `config show`, `completion`, `serve`;
  exit codes 0-6. [Command Line](docs/clients/Command%20Line.md),
  [Tutorial 15](docs/tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md).
- **Per-era argument validation** is stated in the MCP Protocol Guide ("Argument validation").

### Security fixes

Each is described with its code location in [Security Model §4](docs/security/Security%20Model.md#4-fixes-since-600).
- **SQL injection in the OLAP tools** (pivot, rollup, window, time series, statistics, cohort,
  `olap_top_n`, `olap_contribution`, `customer_olap_pivot`, `OLAPQueryBuilder`): filter values and
  dates are bound parameters, names resolve only through the dataset's declarations, operators,
  aggregations, directions, time grains and numbers are allowlisted or coerced
  (`sajha/olap/sql_safety.py`). `sales_analysis` and `financial_metrics` declare the columns the
  shipped examples use.
- **`duckdb_sql`** ran every statement after a `SELECT` and could read any file or URL; the other
  `duckdb_*` tools pasted table and column names (and `having`) into SQL. All now run on locked,
  in-memory sandboxes (see Breaking changes).
- **Catalog visibility:** prompts, the `sajha://tools/catalog` and `sajha://prompts/catalog`
  resources, `completion/complete`, the MCP `tool/schema`-style methods, the A2A agent card, the
  REST catalog, the console's tool pages and the tool names on public pages follow the caller's
  access; `sajha://data/*` resources follow `mcp.anonymous.resources`; `tool/description` no longer
  fails with an internal error.
- **Invalid credentials** ran as anonymous on MCP and A2A; **A2A** ran tools anonymously and showed
  every task (tasks are now visible only to their creator).
- **Async execution** wrote to any path and posted to any URL (now the CIMD SSRF guard and the
  allow-lists).
- Enabling or disabling a tool wrote its resolved configuration, API keys included, back to its
  config file (now only `enabled` changes); a tool's schema page showed that configuration to every
  signed-in user.
- `/login?next=` open redirect; path traversal in `sajha://data` resources; WebSocket
  authentication called a method that did not exist (an invalid token now closes the connection
  with 1008); security headers overwrote stricter per-route values.
- `sajha/auth/password.py` raised `NameError` on an invalid hash; an API key with an expiry date
  failed on SQLite (naive and aware datetimes compared).
- nginx (`deployment/baremetal/nginx.conf`) proxies `/mcp`, `/api/mcp` and `POST /api/ai/ask`
  unbuffered; compose files no longer pass placeholder secrets.

### Governance

- **Policy engine** (`sajha/policy/`): declarative rules (YAML or JSON in `config/policies/`,
  through the storage backend, hot-reloaded) evaluated in `BaseMCPTool.execute_with_tracking`, the
  one place MCP (both eras, stdio, WebSocket), REST, the playground bridge, A2A, Ask SAJHA, async
  tasks, workflows and federated tools run a tool; composite steps too. Matches on tool globs,
  groups, annotations, caller, source, time window and argument values. Effects `allow`, `deny`,
  `require_approval`; argument constraints; rate limits and calendar quotas in the state store;
  output redaction (emails, phone numbers, Luhn-valid cards, US SSN, UK NINO, Aadhaar, PAN,
  Canadian SIN, custom regexes); prompt-injection screening of results (`flag`, `strip`, `block`).
  Deny-overrides; `policy.default_effect: deny` is an allowlist mode. REST answers 403, 202
  (approval pending) or 429 with `Retry-After`; MCP a tool error with `_meta["io.sajha/policy"]`.
  Default unchanged: the shipped `00-default.yaml` has no rules and the two examples are disabled.
- **Approvals:** `approver: caller` asks the user (an MRTR form on 2026-07-28 clients with
  elicitation; Confirm in Ask SAJHA); `approver: admin` queues the call on the **Approvals** page
  (`/admin/approvals`); an approved call runs once for the same caller; no self-approval by
  default; optional webhook or Slack notification. **Policies** page (`/admin/policies`) with a test
  bench. Metrics `sajha_policy_decisions_total`, `sajha_policy_redactions_total`,
  `sajha_policy_output_flags_total`; every non-allow decision is audited.
- **Tamper-evident audit** (`sajha/audit/`): every audit record and policy decision is hash-chained
  (one chain per process), anchored every `audit.chain.anchor_every` records, every
  `anchor_interval_seconds` and at shutdown with an RS256 signature from the OAuth key (public
  half at `/oauth/jwks`). `python -m sajha.audit verify` and the **Audit** page (`/admin/audit`)
  detect edited, deleted, inserted or reordered records, rewritten tails and truncation.
  `audit_log` is still written for the existing audit API.
- **SIEM export** (`audit.export.sinks`): syslog (RFC 5424, TCP or TLS), HTTP (Splunk HEC, Datadog,
  generic; SSRF-guarded) and rotated JSON Lines files, as JSON, CEF or OCSF-style JSON; batched,
  retried, bounded queues with counted drops (`sajha_audit_export_total`).
  [Policy and Audit](docs/architecture/Policy%20and%20Audit.md),
  [Tutorial 20](docs/tutorials/TUTORIAL_20_policies_approvals_and_audit.md).
- **Connected accounts** (`sajha/accounts/`): users link their own account at a third-party service
  once on `/account/connections` (OAuth 2.0 authorization code, PKCE S256 where supported, exact
  redirect URI, single-use `state` bound to the user and browser, CSRF-protected Connect and
  Disconnect; Disconnect revokes where the provider can). Provider templates `github`, `slack`,
  `google`, `microsoft`, `atlassian`, `notion` (or any OAuth 2.0 service) under
  `accounts.providers`, each limited to its `api_hosts`. Token vault: AES-256-GCM in
  `connected_accounts`, key from `SAJHA_ACCOUNTS_VAULT_KEY` or the secrets file, rotation with
  `accounts.vault.previous_keys`, a KMS hook; refresh one worker at a time. A tool config's
  `"auth": {"connected_account": ...}` runs every call with the caller's token, never cached; new
  tools `github_list_my_repos`, `github_create_issue`, `slack_post_message`, `google_drive_search`,
  `ms365_list_my_events`, `connected_http_request`, listed only while their provider is configured.
  "Connect your account": an MRTR URL elicitation (2026-07-28), `-32042` (2025-11-25), a tool error
  with the URL, 428 on REST, a **Connect** card in Ask SAJHA. Federated upstreams can receive each
  caller's own token. `/admin/connections` shows who linked what (never a token).
  [Connected Accounts](docs/architecture/Connected%20Accounts.md),
  [Tutorial 18](docs/tutorials/TUTORIAL_18_connect_your_accounts.md).

### Building and composing tools

- **Sandboxed user code** (`sajha/sandbox/`): Studio Python code tools, script tools and the admin
  shell run per call in a sandbox with no server environment (secrets only by name through
  `sandbox.secrets_allowlist`), a temp work dir, CPU/memory/file/process/output/time limits and no
  network unless allowlisted. Backends (`sandbox.default_backend`): `subprocess` (default; on Linux
  user/PID/network namespaces, rlimits, Landlock and seccomp, each reported), `bwrap`, `nsjail`,
  `docker` (`runtime: runsc` for gVisor), `auto`. `GET /api/sandbox/status`, `sandbox` in
  `GET /health`; the creator pages show the policy a new tool gets. Built-in tools and Studio's
  template creators stay in-process. [Sandbox](docs/architecture/Sandbox.md),
  [Tutorial 14](docs/tutorials/TUTORIAL_14_sandboxed_studio_tools.md).
- **Federation** (off by default; `sajha/federation/`): other MCP servers' tools (and optionally
  prompts and resources) as registry tools named `<prefix>__<tool>`, under the same access policy,
  cache, one circuit breaker and rate-limit window per upstream, metrics and usage events.
  Upstreams over Streamable HTTP (either era), legacy SSE or stdio (`federation.allow_stdio`, off);
  credentials by secret reference. Discovery at start-up, periodically, on change notifications
  and on demand; results, progress, cancellation and MRTR pass through. Approval before exposure
  and on change, injection screening, SSRF guard, admin page `/admin/federation`.
  [Federation](docs/architecture/Federation.md), [Tutorial 11](docs/tutorials/TUTORIAL_11_federate_an_mcp_server.md).
- **API Import** (`sajha/api_import/`, Studio → Import an API, `/studio/api-import`): an OpenAPI
  3.x or Swagger 2.0 spec (URL, upload or paste) or a GraphQL endpoint becomes a preview of every
  operation with generated names, JSON Schema 2020-12 input and output (`$ref` inlined, cycles
  cut), annotations and flags; credentials as secret references (API key, bearer, basic, OAuth 2.0
  client credentials, the caller's connected account); test-call; deploy the selection, live at
  once. One generic executor, no generated code; SSRF guard on every fetch and call; a re-import
  shows a diff (`config/api_imports/<api_id>.json`). CLI `sajha studio import-openapi`.
  [API Import](docs/architecture/API%20Import.md), [Tutorial 19](docs/tutorials/TUTORIAL_19_import_an_openapi_spec.md).
- **Describe a tool** (`/studio/describe`, `sajha studio describe "<text>"`): the model behind the
  new `toolsmith` alias proposes a tool (`python`, `rest`, `dbquery`, `composite` or `openapi`)
  with schemas, implementation and test cases. The proposal is checked as untrusted input (SQL
  read-only and on listed tables, SSRF host checks, no generated credentials, risky imports and
  unmentioned hosts flagged), rendered into the files Studio's generators write, and bound to a
  SHA-256. Tests run before deploy (Python in the sandbox, REST against fixtures, DB queries on
  the listed database); a deploy needs `approve: true`, the reviewed hash, tests on that hash and
  the policy engine's consent to `studio.deploy`. Generated Python tools are always sandboxed; the
  cases become the tool's `tests`. Works offline with `mock-toolsmith`. New keys `studio.describe.*`.
  [Tool Generation](docs/architecture/Tool%20Generation.md), [Tutorial 24](docs/tutorials/TUTORIAL_24_describe_a_tool.md).
- **Data connectors** (`sajha/connectors/`, the **Data Connectors** page `/admin/connectors`):
  PostgreSQL, Redshift, MySQL/MariaDB, SQL Server, Oracle, Snowflake, BigQuery, Databricks SQL,
  SQLite and DuckDB files; pgvector, Qdrant, Elasticsearch/OpenSearch. One record per connection at
  `config/connectors/<id>.json` with secret references only. Generated tools
  `<id>__list_tables`, `__describe_table`, `__query` (one read-only SELECT with bound `:name`
  parameters), curated views as typed tools, and `__search` / `__list_collections` /
  `__describe_collection` for vector and search kinds. Read-only behind three walls (the statement
  guard, a read-only session where the database has one, the login's privileges); row, byte and
  time limits; column masking (`hide`, `null`, `redact`, `hash`, `partial`, `pii`); per-user
  credentials for Snowflake, BigQuery and Databricks through connected accounts; audit records
  `connector.query` / `connector.rejected` and metrics. No connection ships.
  [Data Connectors](docs/architecture/Data%20Connectors.md),
  [Data Connectors Reference Guide](docs/tools/enterprise/Data%20Connectors%20Reference%20Guide.md),
  [Tutorial 25](docs/tutorials/TUTORIAL_25_connect_a_database.md).
- **Workflows** (`sajha/workflows/`, the **Workflows** page `/workflows`): DAGs of `tool`,
  `composite`, `ask`, `condition`, `foreach`, `wait` and `approval` steps with `$steps.<id>`
  mapping, joins, retries, timeouts. Triggers: timezone-aware cron (one fire per slot across
  workers), HMAC-signed webhooks (`POST /api/workflows/{name}/hooks/{trigger}`), file arrival on
  the storage backend, change-bus events, manual runs with `Idempotency-Key`. Durable runs: every
  step stored, another worker resumes a run whose worker died, waits and approvals park the run,
  cancel, re-run from a failed step, concurrency limits, delivery through the async router. Steps
  run as the owner, under policy (source `workflow`), audited. Administrators can publish a
  workflow as a tool. New keys `workflows.*`.
  [Workflows](docs/architecture/Workflows.md), [Tutorial 22](docs/tutorials/TUTORIAL_22_schedule_a_workflow.md).
- **Tool quality** (`sajha/quality/`): a test harness (`python -m sajha.quality test`; cases in
  `config/tool_tests/*.yaml` or a tool's `tests`; JSON Schema and JSONPath assertions, latency
  budgets; text, JSON and JUnit output) with HTTP cassettes that record once and replay offline;
  a schema linter (`lint`); opt-in health probes on intervals or cron (`quality.probes.enabled`),
  **Tool Health** page; evals for Ask SAJHA (`config/evals/*.yaml`, `eval|compare|runs`;
  tool-selection and answer accuracy, steps, tokens, cost, latency), **Evals** page; tool versions
  (`config/tool_versions/<tool>.yaml`) routed per call by API-key pin, user, role, sticky canary
  percentage, then stable, with automatic rollback shared through the state store and sunset
  dates, **Tool Versions** page. `GET /api/tool-versions` and
  `POST /api/tool-versions/{tool}/deprecate`, placeholders until now, read and write the versions
  files. Probes are off and no tool has a versions file by default.
  [Tool Quality](docs/architecture/Tool%20Quality.md), [Tutorial 23](docs/tutorials/TUTORIAL_23_test_and_canary_your_tools.md).

### Intelligence layer

- **Ask SAJHA** (`/ask`): a chat over `POST /api/ai/ask` that streams each step (shortlist, tool
  calls and results, answer, confidence), shows the tool chain as expandable chips, asks before a
  destructive call and draws the chain on the tool sky; model picker, a *Mock model active* pill,
  Stop. [Tutorial 10](docs/tutorials/TUTORIAL_10_ask_sajha.md).
- **Planners** (`ai.ask.planner`): `react` (the previous loop, default), `plan_execute` (one
  planning call, independent steps in parallel, one re-plan), `recipes` and `router`; register more
  with `@register_planner`, a class path or a `sajha.planners` entry point. The service keeps RBAC,
  confirmation, limits, synthesis, confidence, audit and the event schema. New `plan` event;
  `GET /api/ai/planners`.
- **Conversation memory:** an ask with `conversation_id` gets recent turns, a summary of older
  ones and a standalone rewrite of its question; per user, `ai.memory.retention_days` and a
  per-user cap; `GET`/`DELETE /api/ai/conversations[/{id}]`. Ask SAJHA keeps a conversation.
- **Document search (RAG):** the `sajha_search_docs` tool and the help page's **Ask the docs** box
  search SAJHA's own guides, `ai.rag.sources` folders and admin uploads (`/api/ai/docs/*`), with
  citations; vector and BM25 rankings fused; an in-process store by default, pgvector when
  available.
- **Tools reach Ask SAJHA at once:** `ToolsRegistry.add_change_listener` fires on every register,
  unregister, enable and disable, so tools from Studio, composites, federation, API import,
  connectors or the file watcher are searchable without a reload.
- [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md):
  a provider, a model and a planner, with tested examples in `sajha/examples/intelligence/`.
  [Intelligence Layer](docs/architecture/Intelligence%20Layer.md),
  [Tutorial 21](docs/tutorials/TUTORIAL_21_planners_memory_and_rag.md).

### Operations

- **Several workers and hosts** (`state.backend`: `memory`, the default, `redis` or `database`;
  `sajha/core/state/`): OAuth consents, codes, refresh tokens and DCR clients, 2025-11-25 sessions
  (relayed to the worker holding the stream), legacy SSE queues, 2026-07-28 task records, rate
  limits, the sign-in throttle, LLM budgets and async task records are shared; change-bus events
  reach subscribers on every worker. Durable MCP tasks (`state.tasks.durable: auto`) survive a
  restart. `GET /health` has a `state` object; `run_server.py --workers N`. Conformance unchanged
  (43/43 for 2025-11-25 with 0.1.16, 152/152 for 2026-07-28 with 0.2.0-alpha.12) on the memory,
  redis and database backends. [Scaling and State](docs/architecture/Scaling%20and%20State.md),
  [Tutorial 13](docs/tutorials/TUTORIAL_13_run_sajha_on_several_workers.md).
- **Observability:** `GET /metrics` in the Prometheus text format (HTTP, MCP, tool, LLM, ask, auth,
  sandbox, federation, process metrics; `observability.metrics.auth`, admin by default; optional
  separate listener; cardinality caps; merged across workers); OpenTelemetry traces and metrics
  over OTLP (opt-in) with `traceparent` continued from HTTP and MCP `_meta`; the **Usage & cost**
  page (`/monitoring/usage`) on a usage ledger; alert rules to a log, an allow-listed webhook or
  email; Prometheus rules and a Grafana dashboard in `deployment/observability/`. `/api/metrics`
  and `/api/metrics/tools`, always empty before, are fed.
  [Observability](docs/architecture/Observability.md), [Tutorial 16](docs/tutorials/TUTORIAL_16_metrics_costs_and_alerts.md).
- **Database:** one schema file per database (`db/scripts/<dialect>/schema.sql` + `seed.sql`),
  no migrations, `tests/test_db_schema.py` keeps both in step with every model; the start-up
  check; the helper `python -m sajha.db check|sql`. 6.0.0's PostgreSQL scripts failed on every
  statement and its runner hid it; SQLite's `prompt_tags` was never created.
  [Database Setup](docs/getting-started/Database%20Setup.md).
- **Kubernetes:** a root `Dockerfile` (multi-stage, UID 10001 under `tini`, read-only-root ready;
  build args `EXTRAS`, `WITH_OPENBB`, `PLAYGROUND_ASSETS`), the Helm chart `charts/sajha` (seed
  init container, streaming Ingress, HPA, PDB, optional Redis, NetworkPolicies, ServiceMonitor,
  one shared Secret, refusal of settings that would split state) and Kustomize overlays rendered
  from it. Verified on kind: three pods on Redis and PostgreSQL passed 43/43 (2025-11-25, 0.1.16),
  152/152 (2026-07-28, 0.2.0-alpha.12) and the tasks-extension scenarios (44/44).
  [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md),
  [Tutorial 17](docs/tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md).
- **Deployment recipes:** the AWS CDK stack creates and passes the JWT and session secrets (and
  optionally the OAuth signing key), sets `SAJHA_STATE_BACKEND=database` and synthesizes again;
  its Dockerfile and compose file build from the repository root. The Hetzner and local AWS
  compose files have a `scale` profile with Redis, and the Hetzner one passes the session secret
  (`SESSION_SECRET`). Bare metal: `sajha.service`
  makes `logs/`, `temp/` and `sajha/tools/impl/` writable. Each recipe prints the PostgreSQL schema
  step.
- Start-up is faster; loading N tools publishes at most one change event instead of 3·N.

### Web console

- **Phones and tablets:** no sideways page scroll at 375, 390 or 768px (wide tables scroll in their
  own box, user and API-key lists become cards), a hamburger menu with an accordion, 40px touch
  targets, 16px inputs, 12px minimum text, a "Contents" disclosure on guides, readable charts.
  `scripts/check_mobile.py` checks every page; `tests/test_mobile_layout.py` keeps its routes live.
  [Architecture §10](docs/architecture/Architecture.md).
- **Python Playground** (`/playground`): Python in the browser with Pyodide (cells, CodeMirror,
  pandas tables, matplotlib inline, `.py`/`.ipynb` upload), `import sajha` to call tools and ask
  with the user's session, vendored assets checked against published hashes
  (`scripts/fetch_pyodide.py`) or the CDN; COOP/COEP and a `'wasm-unsafe-eval'` CSP on that route
  only. [Python Playground](docs/getting-started/Python%20Playground.md),
  [Tutorial 12](docs/tutorials/TUTORIAL_12_python_playground.md).
- **How SAJHA compares** (`/comparison`): SAJHA next to MCP frameworks, gateways and hosted
  platforms, each cell a verdict with a note, a source and a date; one data module,
  `sajha/web/competitive.py`, checked by `tests/test_competitive.py`.
- New admin pages: Approvals, Policies, Audit, Connections, Data Connectors, Federation, Tool
  Health, Tool Versions, Evals; new user pages: Connected accounts, Workflows, change password.
- Fixed: a table with both `data-enhance` and automatic controls got two search bars and pagers;
  the user and API-key tables had broken `class` attributes; landing-page counts come from the
  running server; star tooltips and a regex filter on the tool sky; guide pages render without the
  `markdown` package.

### Tools

- **FBI tools rewritten** for the current Crime Data Explorer API (every call returned 404): all
  nine `fbi_` tools keep their names (config `version` 3.0.0); key and rate-limit errors name
  `FBI_API_KEY`; per-tool `timeout`. [FBI Tool Reference Guide](docs/tools/public-data/FBI%20Tool%20Reference%20Guide.md).
- **FRED:** every `fred_*` tool, `fed_get_latest` and `fed_get_common_indicators` returned the
  oldest observations; they ask for the newest first and skip missing values.
- **OLAP datasets:** `customer_olap` failed on every query, `customer_analytics` and
  `inventory_analysis` lacked their data (`customer_data`, `inventory_data` added); a dataset's own
  dimension or measure wins over the shared definition; filters on a joined dataset apply over the
  joined row; weighted pivot totals; saving `datasets.json` keeps `${data.duckdb.dir}`.
  [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md).
- **SharePoint tools** use Microsoft Graph throughout; new `sharepoint.*` and `azure.tenant.id`
  keys from the environment; unconfigured tools say so; the Studio creator writes a valid schema
  and appears in the menu.
- Schema fixes so valid calls pass validation: Yahoo symbols (`BRK-A`, `BTC-USD`, `7203.T`,
  `EURUSD=X`, `^GSPC`), World Bank country and Wikipedia language codes.
- `${key:default}` is honoured by `PropertiesConfigurator`, so the DuckDB, SQL-select and OLAP tools
  resolve their data directory (no more directories named `${data.duckdb.dir:.`).
- New key `alpha_vantage.api.key` (`ALPHA_VANTAGE_API_KEY`); `ai.tool_search.enabled`/`persist`
  parsed as booleans.
- **Plugins:** `.py` tools in a plugin now register; `min_sajha_version` is compared as a version.

### Other fixes

- `/api/reports/audit` answered 500.
- Federation upstreams shared one rate-limit window; each has its own.
- Change events relayed to other workers are coalesced within 0.5 s.
- The SDK no longer installs an OpenTelemetry tracer provider with no exporter when tracing is off.
- The test suite is independent of test order (engine and registry state restored; a SQLite WAL
  start-up race between workers fixed) and no longer touches tracked data.

### Documentation

- Reorganised under `docs/` by topic with one owning document per topic (the map:
  [How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md)), a root
  `GLOSSARY.md` that the console's glossary and "About this page" panels read, `CLAUDE.md`
  conventions, and point-in-time reports moved to `docs/archive/`. The numbered tutorials in
  `docs/tutorials/` are new.
- The in-app help is one catalog (`sajha/web/help_catalog.py`) rendering the guides at
  `/help/guides/<name>`; `tests/test_documentation_rot.py` checks links, cited paths, app URLs and
  that every registered route is in the [API Reference](docs/protocol/API%20Reference.md).

## v6.0.0 (October 2026) — MCP 2026-07-28, dual-era

SAJHA now serves the stateless **MCP 2026-07-28** protocol and the session-based **2025-11-25**
protocol on the same `/mcp` endpoint. The request's `_meta` decides which: a protocol version
there means stateless, `initialize` means a 2025-11-25 session. Both are verified in CI by the
official conformance suite (`.github/workflows/mcp-conformance.yml`):
- **2026-07-28:** 40/40 scenarios, 152/152 checks; tasks extension 44/44.
- **2025-11-25:** 32/32 scenarios, 43/43 checks.

### 2026-07-28 (new)
- `server/discover`.
- Version, capabilities and log level read from `_meta` on every request.
- Required `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers (-32020); version errors are -32022.
- `resultType` and `ttlMs`/`cacheScope` on results.
- `GET`/`DELETE /mcp` return 405 for these clients.
- Streamed `tools/call` with progress and log notifications. Closing the stream cancels the call.
- `subscriptions/listen`, fed by a change bus over the tool and prompt registries. The legacy `/mcp/sse` and `/mcp/ws` streams receive the same events.
- Multi Round-Trip Requests with an HMAC-signed `requestState`, and elicitation through them. Optional confirmation for destructive tools: `mcp.confirm_destructive_tools`.
- Tasks extension `io.modelcontextprotocol/tasks`. Tools opt in with `execution.taskSupport`.
- Tool context API (`report_progress`, `report_log`, `is_cancelled`) for long-running tools.

### Client SDK
- `SajhaMCPClient` / `SajhaMCPSyncClient` (from 5.4.0) negotiate 2026-07-28 automatically through the official SDK (`pip install sajhaclient[mcp]`).

### Compatibility
- 2025-11-25 clients are unaffected.
- `v5.4.0` (also tagged `mcp-2025-11-25`) remains the last 2025-only release.

## v5.4.0 (October 2026) — MCP 2025-11-25, verified

This release makes SAJHA's MCP 2025-11-25 support match what it claims, proven by the official
MCP conformance suite 0.1.16: **32/32 server scenarios, 43 checks passed, 0 failed**, plus the
official Python SDK 2.3.0 client. It is tagged `v5.4.0` and `mcp-2025-11-25`.

### Protocol and transport
- `initialize` negotiates the version (2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05) instead of ignoring the client's.
- Streamable HTTP on `/mcp`:
  - `Mcp-Session-Id` sessions; `DELETE /mcp` ends a session.
  - The `MCP-Protocol-Version` header is validated.
  - Notifications get 202 with no body; JSON-RPC batches get 400.
  - `GET /mcp` returns 405 to Streamable HTTP clients.
- `Origin` allow-list (`mcp.allowed_origins`, env `SAJHA_MCP_ALLOWED_ORIGINS`) with 403 for other origins.
- The legacy 2024-11-05 HTTP+SSE flow now delivers responses over its stream.
- MCP tool calls run off the event loop. They now use the same path as the REST API: disabled tools are refused, and arguments, cache, circuit breaker and metrics all apply.

### Tools, prompts, resources
- `tools/list` emits `title`, `outputSchema`, `annotations` and `icons[]`.
- `tools/call` returns JSON text plus `structuredContent`. Turn this off with `mcp.tools.advertise_output_schema: false`.
- `prompts/list` includes arguments, and prompts responses carry their `id`.
- `prompts/get` returns real messages.
- Errors are proper JSON-RPC errors, not error objects inside `result`.

### Honesty fixes (breaking)
- Server capabilities no longer advertise client-only `elicitation`/`sampling`, or a `tasks` shape that never ran. `listChanged` and `subscribe` are `false` until notifications exist. Custom keys moved under `experimental.sajha`.
- Removed `/.well-known/openid-configuration`, `/.well-known/oauth-protected-resource` and `/.well-known/oauth-client/{id}`. They advertised OAuth endpoints that did not exist.
- `ping` returns `{}`. Unknown resources return `-32002`. Tool icons are `icons[]`.

### Also
- Opt-in conformance fixtures: `mcp.conformance_fixtures` / `SAJHA_MCP_CONFORMANCE_FIXTURES=true`.
- Client SDK: `SajhaMCPClient`, a wrapper over the official `mcp` SDK v2 (`pip install sajhaclient[mcp]`), with SAJHA's REST, A2A and WebSocket extras.
- Fixed: `POST /api/auth/login` 500; prompt pages' Save/Delete/Test endpoints; prompt detail 500.
- WCAG AA contrast pass across all screens and themes.

### Design: MAYA design language and themes

SAJHA now uses MAYA's look and MAYA's four themes, with the same names and the same colour values.

- **Themes:** Crimson (stored as `light`), Dark, Blue and Green replace Light / Dark / Wall Street / Ubuntu.
  - The palette menu matches MAYA's: a swatch and a name for each theme.
  - With nothing stored, the page follows the system's light/dark setting.
  - A stored Light or Dark choice carries over; a stored Wall Street or Ubuntu choice resets to the default.
- **Tokens:** `static/css/tokens.css` is MAYA's token set, renamed from `--maya-*` to `--sajha-*`. It is the only place colours are defined.
  - `style.css` maps its `--t-*` roles onto these tokens once and re-points Bootstrap's variables at them.
- **Chrome:**
  - A fixed gradient top bar with mega-menu panels (`common/_nav.html`).
  - Gradient `h1`s, soft-shadow 14px cards, alerts with a left rule, gradient primary buttons.
  - Hero banners and MAYA's footer.
  - The system-ui font at 14px.
- **Pages:**
  - Sign-in stands on the theme gradient.
  - The landing page is laid out with MAYA's `lp2-*` sections.
  - The Studio pages share `_studio_theme.html`.
  - Help and About use MAYA's hero, card and box classes.
  - Charts read their colours from the tokens (`window.SajhaChartTheme`) and re-colour when the theme changes.

## v5.3.0 (June 2026) — Storage-Backed Registries, Studio & Cloud Hot-Reload

Builds on the v5.2.0 multi-cloud storage abstraction by routing the live subsystems
through it: tool configs, prompts, and Studio output can now live on local disk, S3,
Azure Blob, or GCS, with cloud hot-reload. Default backend remains **local**.

### Tool registry → storage backend
- **`tools_registry` reads migrated.** `load_all_tools()` enumerates via
  `get_storage().list_files('config/tools', '*.json')` and reads each config through
  `get_storage().read_json()`. The loader (`load_tool_from_config`) now accepts a logical
  path (storage-relative string, `Path`, or filename) instead of a filesystem `Path`, and
  is normalized internally — so **tool configs can live in S3/Azure/GCS**. Verified end to
  end: real tool configs uploaded to a mocked S3 bucket load and instantiate correctly.
- **`register_tool_from_dict(config, source)` extracted** as the shared register path for
  the file loader and the plugin loader. This fixes a latent bug where `plugins.py` called
  `load_tool_from_config(name, config)` with two arguments against a one-arg method.
- **Implementation classes stay package-local.** Tool `.py` implementations are resolved by
  dotted module path via `importlib` and ship with the package, so they import locally
  regardless of where the JSON config lives.
- **Config writes migrated** (`_save_tool_config`) to `get_storage().write_json()`; the
  admin reload route (`api_routes`) uses the storage-backed path.

### Prompts registry → storage backend
- **Reads and writes migrated.** `_load_all_prompts_internal` lists/reads through storage;
  `create_prompt` / `update_prompt` write via `write_json()`; `delete_prompt` via
  `delete()`. Time-based auto-refresh now reloads from whichever backend is active.

### MCP Studio → storage backend
- **All eight tool generators** (code, REST, DB-query, script, SharePoint, LiveLink,
  PowerBI, PowerBI-DAX) write their JSON config through a shared
  `write_tool_config()` storage helper. Generated `.py` implementations are still written
  locally because `importlib` needs a real module on the path — on multi-instance cloud
  deployments, place that directory on shared EFS.

### Cloud hot-reload (no inotify on object stores)
- **`S3SyncManager` activated for cloud backends** at startup: it polls the bucket every
  `sync_interval` seconds, mirrors changed objects into the local cache, and fires the same
  reload paths (`tools_registry.reload_all_tools`, `prompts_registry.reload`). On the
  `local` backend the registry's filesystem poller is used and the sync manager is skipped,
  so exactly one mechanism runs per deployment. Verified via mocked S3: initial sync
  materializes the cache and a new object triggers the reload callback.

### Semantic tool search (pluggable embedder)
- **Natural-language tool discovery** at `/api/ai/resolve-tool`: a query like "discount future
  cash flows to today" returns the top-k matching tools by vector similarity. The index
  embeds each tool's name + description + parameter names + tags + an optional `literature`
  field.
- **Configurable ranking** via `ai.tool_search.embedder`:
  - `bm25` (default) — a dependency-free lexical BM25/TF-IDF ranker (no model, no key, no
    network), built over the same rich text (name + description + parameters + tags + literature).
  - `gateway` — optional API-driven vector similarity via the LLM gateway's embedding provider
    (e.g. OpenAI) for paraphrase matching. Switch with one config value; no code change.
  - Decoupled from the LLM gateway — semantic search needs no provider in the default mode.
- **Accurate on change.** The index does incremental, content-hash-based sync: only tools
  whose embedding text changed are re-embedded, removed tools are dropped, unchanged tools
  keep their vectors. It hooks the registry's reload path (`add_reload_listener`), so adds /
  edits / deletes — local or via the cloud sync manager — keep embeddings current.
- **Persisted via the storage backend** (local | s3 | azure | gcs) with a header recording the
  embedder + dimension; a restart reloads vectors (no re-embedding) and a changed embedder
  forces a clean rebuild (vectors from different models aren't comparable).
- **Non-blocking + graceful.** The initial index builds in a background thread so startup is
  never blocked; until it's ready (or if no embedder is available) search falls back to
  keyword matching. In-memory numpy cosine search — a `VectorIndex` seam is left for FAISS /
  Chroma if scale ever demands it.

### Database scripts cleanup
- **Fixed a critical regression where the file monitor unloaded all tools every 5s.** The
  storage migration changed `load_tool_from_config` to key `_file_timestamps` by
  storage-relative paths (`config/tools/foo.json`), but the registry's `_monitor_files`
  poller still compared against absolute paths — so every tool looked simultaneously "new"
  and "deleted" each cycle and the delete branch unregistered them all, leaving the registry
  empty. The monitor now keys on the same relative paths (`_config_rel`), so new/modified/
  deleted detection works correctly and legitimate hot-reload is preserved. Semantic tool
  search was also made fully non-blocking on reload, so the optional feature can never affect
  core tool loading.
- **Fixed SharePoint tools failing to load.** `SharePointBaseTool` never implemented the
  `get_input_schema` / `get_output_schema` abstract methods from `BaseMCPTool`, so all three
  SharePoint tools (documents, lists, search) raised "Can't instantiate abstract class …" at
  load. Added both getters to the base (returning the config's `inputSchema` / `outputSchema`,
  matching every other tool), making all four SharePoint classes concrete. Tool count
  496 → 499.
- **Removed obsolete top-level `db/scripts/001_schema.sql` + `002_seed.sql`.** The engine runs
  the dialect-specific `db/scripts/<db.type>/` directory; the top-level scripts were bypassed
  for SQLite and only reached as a buggy fallback (below).
- **Renamed `db/scripts/postgres/` → `db/scripts/postgresql/`** to match `db.type: postgresql`.
  Previously the engine looked for `db/scripts/postgresql/` (the `db.type` value), didn't find
  it, and silently fell back to the top-level scripts — so a Postgres deployment never used its
  own schema. Now `db/scripts/sqlite/` and `db/scripts/postgresql/` are the single source of
  truth per dialect.
- **Reconciled schema drift:** `llm_usage` and `user_ai_preferences` (previously only in the
  top-level file) are now defined in **both** dialect schemas alongside `rate_limit_log` and
  `tenant_users`, so SQLite and Postgres create an identical table set. Verified: SQLite boot
  creates all tables; both `db.type` values select the correct script directory.

### Documentation
- **New Storage Management help page** (`/help/storage`) with sections on local, EFS, S3,
  Azure Blob, and GCS — backend selection, auth, the read-mostly-vs-mutable-state rule, and
  how hot-reload works. Linked from the Help index.
- **README, ARCHITECTURE, and STORAGE_ROADMAP updated** to describe the storage-backed
  registries and cloud hot-reload. Version bumped to **5.3.0**.

## v5.2.0 (June 2026) — Offline Assets, Self-Only CSP & UI Polish

### Front-End Vendoring (offline-capable, no CDNs)

- **All third-party assets vendored** to `sajha/web/static/vendor/`: jQuery 3.7.1, Bootstrap 5.3.0 (CSS + bundle JS), Bootstrap Icons 1.10.0 (+ fonts), Socket.IO 4.5.4, marked 4.3.0 (pinned — preserves the `marked.setOptions({highlight})` API the docs viewer relies on), highlight.js 11.9.0 (+ 7 language packs + github-dark theme), Chart.js 4.4.0, jsoneditor 9.10.4 (+ icons), and three webfonts (Ubuntu, Plus Jakarta Sans, JetBrains Mono).
- **Zero external resource loads** remain across all 52 templates — the app renders fully offline / air-gapped.

### Security — Content-Security-Policy

- **Docs viewer fixed**: the markdown viewer previously spun forever because jQuery and Socket.IO were loaded from CDNs that the CSP `script-src` did not whitelist, so `$` was undefined and `$(document).ready()` threw before the render path. With everything vendored, this class of failure is gone.
- **CSP tightened to self-only**: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:`. No third-party origins to drift out of sync with.
- **CORS** default aligned with the `0.0.0.0` bind: localhost / 127.0.0.1 / 0.0.0.0 on :3002 (override via `SAJHA_CORS_ORIGINS`).

### Config Substitution Fix

- **`${data.duckdb.dir}` / `${data.sqlselect.dir}` now resolve correctly.** Root cause: `tools_registry` constructed `PropertiesConfigurator()` with no `yaml_file`, so it loaded nothing and every `${key}` fell through to its literal text — which created directories literally named `${data.duckdb.dir}`. The registry now loads the same config the app uses (respecting `SAJHA_CONFIG_FILE` / `--config`).
- `app.py` PropertiesConfigurator load also respects `SAJHA_CONFIG_FILE` instead of hardcoding the path.
- All 15 affected tool configs given `:default` fallbacks (e.g. `${data.duckdb.dir:./data/duckdb}`) as defense-in-depth.

### Storage Abstraction (on-prem ↔ cloud)

- **Pluggable storage backend** wired into startup: `storage:` config block (`backend: local|s3|azure|gcs`), `init_storage()` called before tools/prompts load, `get_storage()` available app-wide. Default `local` is a transparent filesystem wrapper — no behaviour change on-prem, and it needs none of the cloud SDKs.
- **Four backends behind one `StorageBackend` interface**: `LocalStorageBackend` (default) plus three object stores — **S3** (boto3, now with `endpoint_url` for MinIO/R2/Wasabi), **Azure Blob** (azure-storage-blob; connection-string or managed-identity auth), and **GCS** (google-cloud-storage; ADC/workload-identity auth). The three object stores share an `_ObjectStorageBackend` base (app-prefix namespacing, local read-through cache, recursive listing, `get_local_path` materialization); each implements only six small primitives. Cloud SDKs are lazy-imported, so only the selected backend's SDK is required.
- **Docs viewer migrated** to read through the backend (listing + content), so docs can be served from any backend; added a path-traversal guard.
- **`list_files` contract aligned** across local and object backends (recursive listing, filename-pattern match).
- Validated: S3 against a `moto`-mocked bucket; Azure + GCS against the real SDK surfaces (API-method introspection) plus injected-client logic tests; and the local default proven to boot with all cloud SDKs blocked. Remaining adoption (tools/prompts/studio, mutable-state placement, cloud hot-reload) tracked in `docs/STORAGE_ROADMAP.md`.

### Config-Driven UI Metadata

- Version, author, copyright, email, and GitHub URL/repo-name are all surfaced on the UI from `application.yml` via Jinja globals. Closed the two remaining hardcoded spots (About-page email, an Enterprise help version literal) and added a GitHub link to the About page.

### UI / Theming

- **About page rewritten**: 1384 → 314 lines. The old page duplicated its marketing cards 7–14× with malformed closing tags (causing visual overlap); the rewrite renders each section exactly once, is structurally valid, and is fully theme-driven via `var(--t-*)` surfaces and `card-header-*` helpers.
- **Theme sweep**: 113 `card-header` elements using fixed `bg-*`/`text-white` across 28 templates converted to the theme-aware `card-header-*` helpers (no more colour bleed in Dark / Wall Street / Ubuntu themes). Intentional fixed colours (code-editor surfaces, provider/brand accents, status badges, landing-page gradients) deliberately preserved.
- **Landing page**: added a `<canvas>` "living intelligence mesh" behind the hero — a pulsing SAJHA hub routing animated data packets between AI-agent nodes (Claude, GPT-4o, Bedrock, Together, Ollama, Azure) and data-provider nodes (FMP, OpenBB, FRED, Yahoo, SEC EDGAR, CoinGecko). Vanilla JS, theme-matched, DPR/resize-aware, pointer-interactive, and respects `prefers-reduced-motion` (renders a single static frame).
- Dead duplicate templates removed: `help/docs_list.html`, `help/docs_view.html` (the live versions live under `docs/`).

### Dependencies

- **`requirements.txt` pinned** with next-major ceilings on all dependencies (0 unbounded) to keep fresh installs reproducible. A `pip freeze` lockfile from a tested environment remains the gold standard for full reproducibility.

---

## v5.1.0 (May 2026) — Security hardening, System Monitor, Composition Framework, MCP 2025-11-25

Three bodies of work were released under 5.1.0. Several MCP claims below were later found to be inaccurate and were corrected in v5.4.0 (see its "Honesty fixes").

### Security hardening and System Monitor

#### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

#### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

#### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

#### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

#### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

#### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

#### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

#### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

#### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

#### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

### Composition Framework and UX overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

#### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

#### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

#### UX Overhaul (22 recommendations implemented)

- **4 UI Themes**: Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal amber-on-black, Consolas font), Ubuntu (aubergine + orange, Ubuntu font). Variable-driven CSS — 545 lines replaces 4,441.
- **CSS rewrite**: Clean architecture — design tokens → theme definitions (var(--t-*)) → components. Zero hardcoded colors. Every Bootstrap color class overridden for all themes. WCAG AA contrast verified.
- **Landing page**: Standalone dark-navy theme, gradient hero, 9 feature cards, code snippet, stats bar.
- **Login page**: Standalone dark theme matching landing page. Glass-morphism card.
- **Dashboard**: Welcome bar with transport badges, 4 metric cards, quick actions panel, platform stats, status panel, onboarding wizard.
- **Tools list**: Card-grid view toggle, category filter chips (auto-generated from tool data).
- **AI → LLM**: 5 Bootstrap tabs (Providers, Models, Preferences, Semantic Search, Usage). Add Provider form with type-specific fields (Bedrock: region+AWS keys, Azure: deployment+endpoint, Ollama: host+model, Custom: class+JSON).
- **Composite Builder**: Visual SVG flow diagram (updates live), drag-and-drop step reorder.
- **Studio sub-navigation**: Horizontal chip bar across all 10 studio pages.
- **Help page**: Search-within-help, 6 tutorial cards, 5 v4 feature sections.
- **Active nav highlighting**, button press feedback, loading skeletons, keyboard shortcuts (/ = search, Shift+? = help), skip-to-content link, focus-visible outlines, empty state CTAs with action buttons.
- **0 modals** — all replaced with inline forms/banners.
- **table-enhance.js**: Reusable component — search, pagination, rows-per-page for any table via `data-enhance="true"`.
- **Custom SVG icon set**: 8 icons (sajha, mcp, tool, composite, provider, transport, plugin, agent) as inline sprite.

#### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

#### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

### MCP 2025-11-25 upgrade

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

#### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

#### Updated Capabilities Declaration

```json
{
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "tools": {"listChanged": true},
    "prompts": {"listChanged": true},
    "resources": {"subscribe": true, "listChanged": true},
    "logging": {},
    "completions": {},
    "elicitation": {"form": {}, "url": {}},
    "sampling": {"tools": true},
    "tasks": {"experimental": true}
  }
}
```

#### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

#### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
