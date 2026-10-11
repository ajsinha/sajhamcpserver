# SAJHA MCP Server — Open Data Tools

> **Status: P1 built (8.10.0); P2 and P3 planned.** Wave 8, phase 8.3 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports).
> The P1 folders (`calendars`, `gleif`, `bis`, `us_treasury`, `sanctions`, `fdic`) and the Wikidata
> tools in `wikipedia` are built; each section says so. P2 and P3 (Roadmap L32 to L39) are not built. Each source was checked live on
> 2026-10-11 (endpoint, key, terms, limits). Terms change, so the 8.3 gate re-checks every source in
> the week of release.

This document owns one topic: **which public data sources SAJHA adds as tools, and on what
terms**. It covers which sources were verified and which were dropped (and why), the tool folder
each source goes in, the tools with their inputs, and the priority order.

Once a source is built, its provider guide under `docs/tools/` owns that source's parameters and
examples, and this document keeps only the source list, the placement and the terms. Terms are in
the [Glossary](../../GLOSSARY.md).

---

## 1. Rules every new source follows

- **Placement.** A tool goes in an existing tool folder when that folder's provider already serves
  the data. Otherwise it gets a new folder named after the provider or the topic
  ([Architecture §5](Architecture.md#tool-config-files-and-folders)). Each new folder ships a
  domain description ([Architecture §5](Architecture.md#domain-descriptions)) that carries
  its attribution line and its main conventions (codes, units, lag).
- **Human units.** As in qlrisk, inputs are what a person would say:
  - dates as `YYYY-MM-DD`;
  - periods as `2025-Q3`, `2025-07` or `last 12 months`;
  - rates and shares in percent;
  - tenors as `3M`, `2Y` or `10Y`;
  - countries as ISO 3166 codes (with names accepted where unambiguous).

  Outputs state their units.
- **Attribution in the output.** Where a licence asks for a credit line, every result carries it in
  a `source` field. Reports print it in the provenance appendix ([Reports §8](Reports.md#8-governance)).
- **Keys.** A key comes from an environment variable, never `config/application.yml`. A tool whose
  required key is missing does not invent data; the live tool check reports it as
  `not_configured` ([Tool Quality §12.4](Tool%20Quality.md#124-the-live-tool-check)).
- **Outbound.** Every fetch goes through the outbound fetch guard and HTTP proxy
  (`sajha/core/outbound.py`).
- **Rate limits.** Where a source has a low or shared limit, the rule is: cache results, and keep
  any throttle in the state store, so that all workers share one budget behind the bank's shared
  egress IP. The sources that need this are OECD, arXiv, GDELT, FDIC and OpenAlex.
- **Tests.** Every tool has a probe case and a cassette, so CI never depends on the live service
  ([Tool Quality §2.3](Tool%20Quality.md#23-recorded-fixtures-cassettes)).
- **Defaults** follow the schema-defaults rule
  ([Tool Quality §12.1](Tool%20Quality.md#121-schema-defaults-applied-before-a-call)).

---

## 2. Verdicts

Checked live on 2026-10-11. "Caveat" means the source can be used once the condition in the
Terms column is met. Rate limits are those published, or seen in response headers where nothing
is published.

| Source | Endpoint | Key | Terms (link) | Limits | Verdict |
|---|---|---|---|---|---|
| GLEIF LEI | `https://api.gleif.org/api/v1/` (JSON:API) | none | CC0 ([LEI Data Terms of Use](https://www.gleif.org/en/meta/lei-data-terms-of-use)); no endorsement or logo use | none published; plan 60/min and cache | **usable** |
| BIS statistics | `https://stats.bis.org/api/v1/` (SDMX 2.1) and `https://stats.bis.org/api/v2/` (SDMX 3.0) | none | [Terms of permitted use of BIS statistics](https://data.bis.org/help/legal): cite the BIS; no extra charge to users in a commercial product; the BIS may throttle by IP | none published | **usable, caveat**: cite "Source: BIS" on every output; ships (section 6) |
| US Treasury Fiscal Data | `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/` | none | "free, without restriction" ([API documentation, License and Authorization](https://fiscaldata.treasury.gov/api-documentation/)) | none published | **usable** |
| US Treasury par yield curve | `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/` (XML and CSV feeds; a different host) | none | US government work | none published | **usable** |
| OFAC sanctions lists | `https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/{file}` (SDN and consolidated, XML and CSV; redirects to a one-hour signed URL); `/changes/latest` (the latest delta) | none | US government work | none published | **usable** |
| EU consolidated sanctions | `https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=…` (the public token published in the feed); RSS at `/fsd/fsf/public/rss` | public token | EC reuse notice (Decision 2011/833/EU): reuse with acknowledgement; only the Official Journal is authentic | none published | **usable** |
| UK sanctions list | `https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml` (the OFSI Consolidated List closed on 28 January 2026) | none | [Open Government Licence v3.0](https://www.gov.uk/government/publications/the-uk-sanctions-list) | none published | **usable** |
| UN Security Council consolidated list | `https://scsanctions.un.org/resources/xml/en/consolidated.xml` | none | [un.org Terms of Use](https://www.un.org/en/about-us/terms-of-use) read literally permit "personal, non-commercial use", although the list exists so that institutions can implement it | none published | **usable, caveat**: off until legal signs off (section 6) |
| FDIC BankFind | `https://api.fdic.gov/banks/` (the old host redirects) | none today; [docs](https://api.fdic.gov/banks/docs/) say that may change | US government work | `x-ratelimit-limit: 20`, window undocumented | **usable, caveat**: key optional in configuration; cache |
| CFTC Commitments of Traders | `https://publicreporting.cftc.gov/resource/<id>.json` (Socrata; legacy `6dca-aqww`, disaggregated `72hh-3qpy`, TFF `gpe5-46if`; combined `jun7-fc8e`, `kh3c-gbw2`, `yw9f-hn96`) | none; free app token advised | US government work | without a token a shared per-IP pool ([Socrata app tokens](https://dev.socrata.com/docs/app-tokens)) | **usable** with an app token |
| Eurostat | `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/` (also JSON-stat and SDMX 3.0) | none | [Eurostat copyright notice](https://ec.europa.eu/eurostat/help/copyright-notice): reuse with acknowledgement; some third-party data excluded | none published | **usable**; datasets get renamed (HICP moved from `prc_hicp_manr`, frozen, to `prc_hicp_minr`) |
| OECD Data Explorer | `https://sdmx.oecd.org/public/rest/` | none | CC BY 4.0 for material from July 2024 ([open by default](https://www.oecd.org/en/about/oecd-open-by-default-policy.html)) | about 60 downloads per hour ([API best practices](https://www.oecd.org/en/data/insights/data-explainers/2024/11/Api-best-practices-and-recommendations.html); oecd.org refused direct fetches, so this figure is from a search summary) | **usable, caveat**: one shared hourly budget and a long cache |
| UK ONS | `https://api.beta.ons.gov.uk/v1` (alive, much of it frozen); headline series through the website's time-series JSON | none | [OGL v3.0](https://developer.ons.gov.uk/) | 120 per 10 s, 200 per minute ([bots](https://developer.ons.gov.uk/bots/)) | **usable, caveat**: the live series path is undocumented; watch for the new ONS Data API |
| Statistics Canada | `https://www150.statcan.gc.ca/t1/wds/rest/` | none | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence): commercial use with the source notice | 25 per second per IP ([WDS user guide](https://www.statcan.gc.ca/en/developers/wds/user-guide)) | **usable** |
| Australian Bureau of Statistics | `https://data.api.abs.gov.au/rest/` (SDMX 2.1; keys removed in 2024) | none | CC BY 4.0 ([copyright](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer)) | 30 s and 10 MB per response | **usable, caveat**: small queries; a 404 `NoRecordsFound` means no data |
| US BLS | `https://api.bls.gov/publicAPI/v2/` | v1 keyless (25 queries a day: too few); v2 a free registration key | public domain; the [terms](https://www.bls.gov/developers/termsOfService.htm) require the retrieval date and BLS's disclaimer with the data | v2: 500 queries a day, 50 series, 20 years ([FAQ](https://www.bls.gov/developers/api_faqs.htm)) | **usable** with a v2 key |
| US BEA | `https://apps.bea.gov/api/data` | free UserID | public domain, subject to the API terms accepted at sign-up | 100 requests, 100 MB and 30 errors a minute ([user guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf)) | **usable, caveat**: answered 503 on every attempt on 2026-10-11; re-verify |
| US EIA | `https://api.eia.gov/v2/` | free key (in the query string) | [public domain, reuse allowed](https://www.eia.gov/about/copyrights_reuse.php) | about 9,000 an hour, 5 a second; 5,000 rows a page ([FAQ](https://www.eia.gov/opendata/faqs.php)) | **usable** with a key |
| USGS earthquakes | `https://earthquake.usgs.gov/fdsnws/event/1/` and the GeoJSON summary feeds | none | public domain; credit "U.S. Geological Survey" ([credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)) | 20,000 events a query | **usable** |
| GDACS | `https://www.gdacs.org/gdacsapi/api/events/geteventlist/` (GeoJSON), RSS | none | [Terms of use](https://www.gdacs.org/documents/2025/GDACS_Terms_of_use_Mar_25.pdf): no stated licence; alerts are automatic and not for decisions without confirmation | none published | **usable, caveat**: show the disclaimer, credit GDACS; off until legal approves (section 6) |
| NASA FIRMS | `https://firms.modaps.eosdis.nasa.gov/api/area/` | free MAP_KEY | NASA open data ([guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance)); no endorsement | 5,000 transactions per 10 minutes | **usable, caveat**: key; the country services are marked unavailable |
| OpenAlex | `https://api.openalex.org/` | key advised: usage pricing (about $0.10 a day without a key, $1 a day with a free key; search costs ten times a filter) ([pricing](https://help.openalex.org/access/pricing/)) | CC0 | the daily budget | **usable, caveat**: a key and a budget; prefer filters to search |
| Crossref | `https://api.crossref.org/` | none (send `mailto`) | [metadata usable for any purpose](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | live headers: 3 a second, 3 concurrent with `mailto` (lower than the documentation says); honour `x-rate-limit-*` | **usable** |
| arXiv | `https://export.arxiv.org/api/query` | none | [API Terms of Use](https://info.arxiv.org/help/api/tou.html): metadata CC0; e-prints may not be stored or served | one request every 3 seconds, one connection, across all machines | **usable**: a global throttle; links only, no PDFs |
| Wikidata SPARQL | `https://query.wikidata.org/sparql` (main graph); scholarly articles at `https://query-scholarly.wikidata.org/sparql` since the 2025 graph split | none; a meaningful User-Agent is mandatory | CC0 | 60 s per query; 60 s of processing per minute; 5 parallel ([user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual)) | **usable** |
| GDELT | `https://api.gdeltproject.org/api/v2/doc/doc`, `/tv/tv`, `/context/context` | none | [unrestricted use with a citation and link](https://www.gdeltproject.org/about.html) | one request every 5 seconds (stated only in its 429 message); frequent 429s | **usable, caveat**: serialised throttle and cache; GEO 2.0 answers 404 and is dropped |
| USAspending | `https://api.usaspending.gov/api/v2/` | none | US government work | none published | **usable** |
| data.gov catalogue | `https://catalog.data.gov/search` and `https://catalog.data.gov/api/dataset/{id}` (the CKAN `https://catalog.data.gov/api/3` API answers 404; the new API is v0.1.0) | none | metadata public domain; each dataset carries its own licence | none published | **usable, caveat**: an undocumented new API; a contract test pins it |

### Dropped

| Source | Why |
|---|---|
| **Nager.Date** (public holidays API) | Its [Terms of Service](https://nagerholidays.com/legal/termsofservice) require "active sponsorship" for commercial purposes, including self-hosting, which needs a licence key. Replaced by the MIT-licensed [`holidays`](https://github.com/vacanza/holidays) Python package, which works offline from rules and includes financial-market calendars by ISO 10383 code (for example XNYS, XLON, XTSE and XECB). It becomes an optional dependency (`requires`) |
| **Open-Meteo** (weather) | The free API is "only for non-commercial purposes" ([terms](https://open-meteo.com/en/terms)), and an internal bank tool is commercial use. It can return as a hazards tool if the owner buys a plan (the customer API needs a key) |
| **OpenSanctions** | Its data is CC BY-NC 4.0, and its [FAQ](https://www.opensanctions.org/faq/32/) says any use inside a for-profit business, including screening, needs a paid data licence. SAJHA screens against the official lists and does not depend on it |
| **GDELT GEO 2.0** | Answers 404 in every form; the DOC, TV and Context APIs are kept |
| **BIS `WS_LONG_PP`** | Not a BIS dataflow (404); property prices come from `WS_SPP` and `WS_DPP` |

---

## 3. One SDMX client

BIS, Eurostat, OECD, ECB and ABS all answered the same SDMX 2.1 REST pattern,
`data/{flow}/{key}?lastNObservations=N`. They differ only in two settings:

- **Flow-reference syntax:** `AGENCY,ID,VERSION` on OECD and ABS, and a bare id elsewhere.
- **CSV selector:**
  - the `format=` parameter: `csvdata` (ECB), `csvfile` (OECD), `SDMX-CSV` (Eurostat);
  - the `Accept: application/vnd.sdmx.data+csv` header (BIS, ABS).

The shared client was built in phase 8.1 for the ECB, IMF and Banque de France fixes
(`sajha/tools/impl/sdmx_client.py`, [Tool Quality §12.3](Tool%20Quality.md#123-a-shared-sdmx-client)).
It ships the `ecb` and `imf` host profiles; the IMF (`api.imf.org/external/sdmx/2.1`, no key) uses
`AGENCY,ID` flow references and the `Accept: application/vnd.sdmx.data+csv;version=1.0.0` header.
The 8.3 sources are host profiles on that client (`register_host`), not new parsers.

---

## 4. Placement and tools, by priority

Every tool is read-only (`readOnlyHint: true`). "Complements" names the existing tools that the
new tools sit beside; their descriptions point at each other.

### P1 (release 8.10.0 cannot ship without these)

**`calendars` (new folder; L26).** Source: the `holidays` package, offline.

| Tool | Inputs |
|---|---|
| `cal_holidays` | `country` or `market` (ISO 10383, e.g. `XNYS`), `year` or `from`/`to` dates, `subdivision?` (e.g. `ON`) |
| `cal_is_business_day` | `date`, `calendars` (one or more countries or markets; a day is a business day only if it is one in all of them) |
| `cal_business_days_between` | `from`, `to`, `calendars` |
| `cal_add_business_days` | `date`, `days` (may be negative), `calendars` |
| `cal_settlement_date` | `trade_date`, `convention` (`T+0` to `T+3`), `calendars` |
| `cal_adjust_date` | `date`, `rule` (`following`, `modified_following`, `preceding`), `calendars` |

Complements `qlrisk` pricing dates and every report's as-of date.

> **Built (8.10.0):** [Calendars Tool Reference Guide](../tools/analytics/Calendars%20Tool%20Reference%20Guide.md).

**`gleif` (new folder; L27).**

| Tool | Inputs |
|---|---|
| `gleif_lookup` | `lei` (20 characters), or `isin` |
| `gleif_search` | `name` (fuzzy, through `fuzzycompletions` with `field=fulltext`), `country?`, `status?` |
| `gleif_parents` | `lei` → direct and ultimate parent, or the reporting exception (a 404 there means "not applicable", not an error) |
| `gleif_children` | `lei`, `level` (`direct`, `ultimate`) |
| `gleif_isins` | `lei` |

Complements `edgar_company_search` and FMP profiles, and gives the counterparty exposure report
its hierarchy.

> **Built (8.10.0):** [GLEIF Tool Reference Guide](../tools/public-data/GLEIF%20Tool%20Reference%20Guide.md).
> `gleif_search` matches names with `filter[entity.names]` and falls back to `fuzzycompletions`
> (`field=fulltext`), which answered an empty list for every query tried on 2026-10-11.

**`bis` (new folder; L28).**

| Tool | Inputs |
|---|---|
| `bis_policy_rates` | `countries`, `period`, `frequency` (`daily`, `monthly`); `WS_CBPOL`; percent |
| `bis_credit_gap` | `countries`, `period`; `WS_CREDIT_GAP`; percentage points of GDP |
| `bis_total_credit` | `countries`, `sector`, `period`; `WS_TC` |
| `bis_debt_service_ratio` | `countries`, `sector`; `WS_DSR` |
| `bis_property_prices` | `countries`, `real` (boolean), `period`; `WS_SPP`, with `WS_DPP` for detail; `WS_CPP` for commercial property |
| `bis_effective_exchange_rates` | `countries`, `real` (boolean), `basket` (`broad`, `narrow`); `WS_EER` |
| `bis_get_series` | `dataflow`, `key`, `period` (the generic escape hatch) |

Complements the central bank folders (`ecb`, `bank_of_canada`, `bank_of_japan`,
`federal_reserve`, `peoples_bank_of_china`) with one cross-country source.

> **Built (8.10.0):** [BIS Tool Reference Guide](../tools/public-data/BIS%20Tool%20Reference%20Guide.md);
> the `bis` host profile is registered by `sajha/tools/impl/bis_tools.py`.

**`us_treasury` (new folder; L29).**

| Tool | Inputs |
|---|---|
| `ust_yield_curve` | `date` or `from`/`to`; `curve` (`nominal`, `real`, `bills`); tenors as `1M` to `30Y`; percent |
| `ust_debt_to_the_penny` | `from`/`to` |
| `ust_average_interest_rates` | `period`, `security_type?` |
| `ust_auctions` | `security_type` (`Bill`, `Note`, `Bond`, `TIPS`, `FRN`), `term?`, `from`/`to` |
| `ust_daily_treasury_statement` | `table` (operating cash balance and the other DTS tables), `date` or range |
| `ust_exchange_rates` | `country` or `currency`, `period` (Treasury reporting rates) |

The stale `upcoming_auctions` dataset is not wrapped. Complements `fred_10yr_treasury` and its
siblings with the official curve, and `qlrisk_price_treasury_*` with market inputs.

> **Built (8.10.0):** [US Treasury Tool Reference Guide](../tools/public-data/US%20Treasury%20Tool%20Reference%20Guide.md). The Daily Treasury Statement tables that stopped in 2023 (federal tax deposits, short-term cash investments) are not offered.

**`sanctions` (new folder; L30).** **Built in 8.10.0**; parameters, matching and the refresh are in
the [Sanctions guide](../tools/public-data/Sanctions%20Tool%20Reference%20Guide.md). The official
lists are downloaded into a local index by a refresh job (the shipped workflow `sanctions_refresh`,
daily; the EU RSS feed says when the EU file is new; OFAC's delta file is not used: the whole list
is downloaded and compared), so screening never sends a name to a third party. A fifth tool,
`sanctions_refresh` (administrators only), is the workflow's step.

| Tool | Inputs |
|---|---|
| `sanctions_screen` | `name`, `type?` (`individual`, `entity`, `vessel`, `aircraft`), `date_of_birth?`, `country?`, `lists?` (`ofac_sdn`, `ofac_consolidated`, `eu`, `uk`, `un`), `threshold` (percent similarity, default 85) → candidate matches with score, matched alias, list, programme, entry id |
| `sanctions_entry` | `list`, `entry_id` |
| `sanctions_changes` | `list?`, `since` (date) → entries added, changed and removed |
| `sanctions_lists_status` | → each list's publication date, last refresh, entry count |

Fuzzy matching normalises names (transliteration, case, punctuation, word order, honorifics) and
scores them with token-set similarity plus a phonetic key. Every result states that it is a
**screening aid, not a determination**. Screening results are not offered to Ask SAJHA or to a
model: a shipped policy rule blocks `sanctions_*` there (owner decision, section 6). The UN list
ships disabled until legal approves (section 6); `lists` refuses `un` until then.

**`fdic` (new folder; L31).**

| Tool | Inputs |
|---|---|
| `fdic_institutions` | `name?`, `state?`, `cert?`, `active?` |
| `fdic_financials` | `cert`, `fields` (Call Report items, e.g. total assets), `period` (quarters) |
| `fdic_failures` | `from`/`to`, `state?` |
| `fdic_locations` | `cert`, `state?` |
| `fdic_history` | `cert` (structure events) |
| `fdic_summary_of_deposits` | `cert` or `state`, `year` |

Complements `edgar_*` (bank holding companies) and `gleif_*`.

> **Built (8.10.0):** [FDIC Tool Reference Guide](../tools/public-data/FDIC%20Tool%20Reference%20Guide.md). `fdic_history` lists institution-level events unless `include_branches` is set.

### P2

**`cftc` (new folder; L32).** `cftc_cot_latest(market, report)` and
`cftc_cot_history(market, report, from, to)` (`report`: `legacy`, `disaggregated`, `tff`;
`futures_only` or `combined`); `cftc_cot_markets(search)`; `cftc_cot_net_positioning(market,
category, period)` (net long as a percent of open interest). Requests always sort newest first.
Complements the commodity and futures tools in `openbb` and `fmp`.

**`eurostat` and `oecd` (two new folders on the shared SDMX client; L33).**

- `eurostat_search(text)`, `eurostat_get_series(dataset, filters, period)` and curated tools:
  - `eurostat_hicp` (from `prc_hicp_minr`), `eurostat_gdp`, `eurostat_unemployment`,
    `eurostat_government_debt`, `eurostat_house_prices`.
- `oecd_search(text)`, `oecd_get_series(dataflow, key, period)` and curated tools:
  - `oecd_leading_indicators` (`DF_CLI`), `oecd_main_economic_indicators`,
    `oecd_quarterly_national_accounts`, `oecd_economic_outlook`.
- OECD calls share one hourly budget kept in the state store.

Complements `ecb_*`, `imf_*` and `wb_*` (Eurostat and OECD are monthly and quarterly where the
World Bank is annual).

**`ons`, `statcan`, `abs` (three new folders; L34).** One folder per office, because each has its
own codes and attribution.

- `ons_search(text)`, `ons_timeseries(cdid, dataset)` (e.g. CPI annual rate).
- `statcan_search_tables(text)`, `statcan_vector(vector, latest_n or period)`,
  `statcan_table(table, coordinate, period)`, `statcan_changed_series(date)`.
- `abs_get_series(dataflow, key, period)` and curated `abs_cpi`, `abs_labour_force`, `abs_gdp`.

Statistics Canada complements `bank_of_canada`.

**`bls`, `bea`, `eia` (three new folders; L35).**

- `bls_series(series, from_year, to_year)` (up to 50 series) and curated `bls_cpi`,
  `bls_payrolls`, `bls_unemployment_rate`, `bls_ppi`, `bls_employment_cost_index`,
  `bls_job_openings`. The output carries the retrieval date and BLS's disclaimer, as its terms
  require.
- `bea_datasets()`, `bea_nipa_table(table, frequency, years)`, `bea_gdp_by_industry`,
  `bea_international_transactions`, `bea_regional(table, geography, years)`.
- `eia_browse(route)`, `eia_series(route, facets, frequency, period)` and curated
  `eia_petroleum_spot_prices`, `eia_petroleum_stocks`, `eia_natural_gas_storage`,
  `eia_electricity_retail_sales`, `eia_short_term_outlook`. Each fetch follows EIA's 5,000-row
  pages.

These complement `fred_*`, which re-publishes many of the same series. The sources are first-hand,
with the release vintage.

### P3

- **`hazards` (new topic folder; L36).**
  - `hazards_earthquakes(region or point and radius_km, from, to, min_magnitude)` and
    `hazards_significant_earthquakes(window)` (USGS).
  - `hazards_disaster_alerts(types, alert_level, from, to)` (GDACS, with its disclaimer in every
    result). It ships disabled (`"enabled": false`) until legal approves GDACS (section 6).
  - `hazards_active_fires(region, days, source)` (NASA FIRMS, MAP_KEY).
  - Weather is not included (Open-Meteo dropped).
  - The folder serves operational-risk and physical-climate-risk questions.
- **`research` (new topic folder; L37).**
  - `research_search_works(query, filters, from_year)` and `research_get_work(doi or id)`
    (OpenAlex with a key; a filter by default, search only when asked).
  - `research_crossref_works(query, filters)` and `research_crossref_doi(doi)`.
  - `research_arxiv_search(query, category, max_results)` (a global 3-second throttle; links only).
  - Complements the `literature` metadata on tools and Ask SAJHA's document search.
- **Wikidata goes in the existing `wikipedia` folder (L37).** It has the same operator (Wikimedia)
  and the same User-Agent policy.
  - `wikidata_search(name)` (`wbsearchentities`).
  - `wikidata_entity(qid, properties?)`.
  - `wikidata_company_identifiers(name or qid)` (LEI, ticker, ISIN, official website), which ties
    into `gleif_*`.
  - `wikidata_sparql(query)`, read-only, with a timeout and a row cap, against the main graph, or
    the scholarly graph when `graph: scholarly`.
  - **Built (8.10.0)** with phase 8.3's P1 sources:
    [Wikipedia Search Tool Reference Guide](../tools/search/Wikipedia%20Search%20Tool%20Reference%20Guide.md#wikidata).
    `wikidata_sparql` takes SELECT and ASK only. Wikidata refuses (403) a User-Agent without contact
    information; the tools send the project URL.
- **`gdelt` (new folder; L38).**
  - `gdelt_articles(query, from, to, max_records)`.
  - `gdelt_coverage_timeline(query, from, to)` (volume and tone).
  - `gdelt_tv_mentions(query, stations, from, to)`.
  - `gdelt_context(query)`.
  - All calls are serialised at one per 5 seconds across workers, and cached.
- **`us_spending` (new folder; L39).**
  - `usaspending_awards(keywords, agency?, recipient?, award_types, from, to)`.
  - `usaspending_by_category(category, filters)`.
  - `usaspending_over_time(filters, group)`.
  - `usaspending_recipient(name or id)`.
  - `datagov_search(query, organization?, keyword?)` and `datagov_dataset(id)` (the new catalogue
    API, pinned by a contract test).

---

## 5. What existing folders gain

| Existing folder | Gains | Why there |
|---|---|---|
| `wikipedia` | the Wikidata tools | same operator and access policy |
| `ecb`, `imf`, `banque_de_france` | the shared SDMX client (phase 8.1 fixes); no new tools | same providers |
| `fred` | nothing; its descriptions point at `bls_*`, `bea_*`, `eia_*` and `ust_*` as first-hand sources | FRED stays the one-key aggregator |

No other new source belongs to an existing provider, so the rest are new folders. The new folders
are `calendars`, `gleif`, `bis`, `us_treasury`, `sanctions`, `fdic`, `cftc`, `eurostat`, `oecd`,
`ons`, `statcan`, `abs`, `bls`, `bea`, `eia`, `hazards`, `research`, `gdelt` and `us_spending`.
Each ships a domain description and a provider guide under `docs/tools/` with tables generated by
the guide generator ([Tool Quality §12.5](Tool%20Quality.md#125-tool-reference-guide-tables-generated)).

---

## 6. Decisions

Recorded by the owner on 2026-10-11:

- **UN consolidated list:** off until legal approves. The un.org terms, read literally, are
  non-commercial; the other lists do not wait for the sign-off.
- **Screening results and LLMs:** sanctions screening results are blocked from Ask SAJHA by a
  policy rule (`sanctions_*` is not offered there, nor to LLM tools); people use the tools directly.
- **BIS:** ships, with "Source: BIS" cited on every output.
- **GDACS:** off until legal approves (no stated licence).
- **Paid options:** none. OpenAlex beyond its free daily budget, Open-Meteo (needs a plan) and a
  Nager.Date sponsorship are not bought; the design works without them.
- **Priorities:** P2 and P3 sources may slip to a later release; P1 may not.

---

## 7. Limits

- These are public sources with no service-level agreement. A tool reports an upstream outage as
  an error; it never returns cached data as current without saying how old it is.
- Rate limits are per source and shared by the whole organisation behind one egress IP.
- Dataset codes change (Eurostat HICP, BIS property prices); the live tool check finds such breaks.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
