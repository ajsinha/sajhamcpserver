# FBI Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [The CDE API](#the-cde-api)
3. [Authentication & API Keys](#authentication--api-keys)
4. [How Figures Are Computed](#how-figures-are-computed)
5. [Tool Descriptions](#tool-descriptions)
6. [Offense Types](#offense-types)
7. [Calling the Tools](#calling-the-tools)
8. [Error Handling](#error-handling)
9. [Limitations](#limitations)

---

## Overview

The FBI tools (prefix `fbi_`, one implementation module: `sajha/tools/impl/fbi_tool_refactored.py`, configs `config/tools/fbi_*.json`) read crime statistics from the FBI Crime Data Explorer (CDE), the publication platform of the FBI's Uniform Crime Reporting (UCR) program, at national, state and agency level. The live catalog in the app (Tools page, or `tools/list`) is authoritative for the tools and their schemas.

| Tool | Answers | CDE API path(s) |
|------|---------|-----------------|
| `fbi_get_national_statistics` | US offenses, rate, clearances for a year | `/summarized/national/{offense}` |
| `fbi_get_state_statistics` | One state, compared with the US rate | `/summarized/state/{state}/{offense}` |
| `fbi_get_agency_statistics` | One agency (ORI), compared with its state and the US | `/summarized/agency/{ori}/{offense}` |
| `fbi_search_agencies` | Agencies in a state, with ORI codes | `/agency/byStateAbbr/{state}` |
| `fbi_get_agency_details` | One agency's directory entry and staffing | `/agency/byStateAbbr/{state}`, `/pe/{state}/{ori}` |
| `fbi_get_offense_data` | NIBRS victim, offender, weapon and location breakdowns | `/nibrs/national/{code}`, `/nibrs/state/{state}/{code}` |
| `fbi_get_participation_rate` | Population covered by reporting agencies, by month | `/summarized/national/V`, `/summarized/state/{state}/V` |
| `fbi_get_crime_trend` | Year-by-year series and trend statistics | `/summarized/{national \| state/{state} \| agency/{ori}}/{offense}` |
| `fbi_compare_states` | Several states ranked on one offense | `/summarized/state/{state}/{offense}` per state |

---

## The CDE API

All tools call `https://api.usa.gov/crime/fbi/cde`, the CDE API behind the api.data.gov gateway. The paths above are the ones in the API specification published on the Crime Data Explorer's API page (<https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi>). The older Crime Data Explorer paths (`/statistics/...`, `/agencies/{ori}`, `/participation/...`) no longer exist.

Request shapes:

- `/summarized/...` and `/nibrs/...` take `from` and `to` as `MM-YYYY`; the tools ask for January to December of the requested year(s). `/nibrs/...` also takes `type=counts` (monthly series) or `type=totals` (breakdowns).
- `/pe/...` (police employees) takes `from` and `to` as `YYYY`.
- `/agency/byStateAbbr/{state}` returns the state's agencies grouped by county.

A summarized response holds monthly series keyed by display name, for example `"United States Offenses"`, `"California Clearances"` or `"Burlington Police Department Offenses"`, under `offenses.actuals` (counts) and `offenses.rates` (per 100,000), plus `populations.population`, `populations.participated_population` and `tooltips["Percent of Population Coverage"]`. A state or agency response also carries the US rates (and, for an agency, its state's rates), so the comparison figures need no extra request. Recorded responses are in `tests/fixtures/fbi/`.

---

## Authentication & API Keys

### How the Key Is Supplied

The api.data.gov gateway requires a key on every request. Each `fbi_` tool config carries `"api_key": "${fbi.api.key:}"`, and `config/application.yml` binds `fbi.api.key` to the `FBI_API_KEY` environment variable. `FBIBaseTool` sends the key in the `X-Api-Key` header, so it never appears in URLs or logs. Resolution order: the config value, then the `FBI_API_KEY` or `DATA_GOV_API_KEY` environment variables, then api.data.gov's shared `DEMO_KEY`. `DEMO_KEY` works but its limits are very low and shared by everyone calling from the same IP, so a few calls exhaust it; request a free key at [api.data.gov/signup](https://api.data.gov/signup/). See the [Configuration Reference](../../getting-started/Configuration%20Reference.md) for how other providers' keys are configured.

### Other Tool Config Keys

| Key | Default | Meaning |
|-----|---------|---------|
| `timeout` | `30` | Seconds to wait for each API request |
| `api_url` | `https://api.usa.gov/crime/fbi/cde` | Base URL (override only for testing) |

### Rate Limiting and Caching

- SAJHA does not rate-limit these tools. The `rateLimit` and `cacheTTL` values under `metadata` in the `fbi_` configs are informational only and are not enforced.
- Server-side caching is opt-in: add a top-level `"cache_ttl": <seconds>` to a tool's JSON config in `config/tools/`. Crime statistics change slowly (each response's `metadata.data_last_refreshed` says when the FBI last refreshed them), so long TTLs are appropriate.

---

## How Figures Are Computed

- **Year.** Optional wherever it appears; the default is the last calendar year. Years before 1985 or after the current year are rejected before any request is made.
- **Counts.** `total_incidents` and `total_cleared` are the sums of the monthly counts for the year. `clearance_rate_pct` is cleared / incidents x 100.
- **Rates.** The API's monthly rate is offenses per 100,000 people in the population covered by agencies that reported that month. `rate_per_100k` for a year is the sum of the twelve monthly rates.
- **Coverage.** `participated_population` is the average monthly covered population; `population_coverage_pct` is the average of the API's monthly coverage percentages. Low coverage (for example in 2021, the first year of NIBRS-only collection) makes counts incomparable across years; compare rates instead.
- **Comparisons.** `percent_of_national` and `percent_of_state` compare rates.
- **`months_reported`.** Months with data; a current year is usually partial.
- Every result carries `metadata` with the API path called, `data_last_refreshed` and `data_available_through`.

---

## Tool Descriptions

`state` is a two-letter USPS code (the 50 states and DC; lower case is accepted). `ori` is a 9-character agency identifier; find one with `fbi_search_agencies`.

### fbi_get_national_statistics

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `offense_type` | string | Yes | See [Offense Types](#offense-types) |
| `year` | integer | No | Data year |
| `include_monthly` | boolean | No | Also return `monthly` (`month`, `incidents`, `rate_per_100k`) |

Returns `offense_type`, `year`, `national_data` (`total_incidents`, `total_cleared`, `clearance_rate_pct`, `rate_per_100k`, `population`, `participated_population`, `population_coverage_pct`, `months_reported`) and `metadata`.

### fbi_get_state_statistics

Parameters: `state` and `offense_type` (required), `year`, `include_monthly`. Returns `state`, `state_name`, `state_data` (the fields of `national_data`), `comparison` (`national_rate_per_100k`, `percent_of_national`) and `metadata`.

### fbi_get_agency_statistics

Parameters: `ori` and `offense_type` (required), `year`. Returns `ori`, `agency_name` (as the API names it), `state`, `agency_data` (the fields of `national_data`; `population` is the jurisdiction's), `comparison` (`state_rate_per_100k`, `national_rate_per_100k`, `percent_of_state`, `percent_of_national`) and `metadata`. An ORI the API has no data for is an error that points at `fbi_search_agencies`.

### fbi_search_agencies

The API lists agencies per state; it has no free-text or nationwide search, so `state` is required and the other filters are applied locally.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `state` | string | Yes | State to list |
| `agency_name` | string | No | Case-insensitive substring of the agency name |
| `county` | string | No | Case-insensitive substring of the county name |
| `agency_type` | string | No | `city`, `county`, `state` (State Police and Other State Agency), `university`, `tribal`, `other`, `all` (default) |
| `limit` | integer | No | 1-500, default 20 |

Returns `state`, `search_query`, `total_results` (matches before the limit) and `agencies`, sorted by name, each with `ori`, `agency_name`, `agency_type`, `county`, `state`, `state_name`, `is_nibrs`, `nibrs_start_date`, `latitude`, `longitude`.

### fbi_get_agency_details

Parameters: `ori` (required), `year` (for staffing). Looks the agency up in its state's list (the state is the ORI's first two letters) and reads its police-employee data. Returns `ori`, `agency_name`, `agency_type`, `location` (`state`, `state_name`, `county`, `latitude`, `longitude`), `reporting_status` (`is_nibrs`, `nibrs_start_date`) and `personnel` (`year`, `male_officers`, `female_officers`, `total_officers`, `male_civilians`, `female_civilians`, `total_civilians`, `total_employees`, `employees_per_1000`, `population_served`). `personnel` is `null` when the agency reported no staffing for the year; if the staffing request fails, the directory details are still returned with `personnel_error`.

### fbi_get_offense_data

NIBRS (incident-based) detail for one offense, nationally or for a state.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `offense_type` | string | Yes | An offense with a NIBRS code (see [Offense Types](#offense-types)) |
| `state` | string | No | Omit for national |
| `year` | integer | No | Data year |
| `include_subcategories` | boolean | No | Include `breakdown` (default true; costs a second request) |
| `top_n` | integer | No | Largest buckets kept per breakdown, default 10 |

Returns `nibrs_offense_code`, `scope`, `total_offenses`, `rate_per_100k`, `nibrs_population_coverage_pct`, `metadata` and `breakdown`: `victim` (`age`, `sex`, `race`, `ethnicity`, `location`, `relationship`), `offender` (`age`, `sex`, `race`, `ethnicity`) and `offense` (`weapons`, `related_offenses`), each a `{bucket: count}` map with zero buckets dropped, largest first.

### fbi_get_participation_rate

Parameters: `state`, `year` (both optional; no `state` means national). The API no longer publishes counts of participating agencies, so this reports population coverage from the summarized violent-crime series, which every reporting agency contributes to. Returns `scope`, `participation_data` (`total_population`, `average_participated_population`, `average_population_coverage_pct`, `months_reported`), `monthly` (`month`, `population_coverage_pct`, `participated_population`) and `metadata`.

### fbi_get_crime_trend

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `offense_type` | string | Yes | See [Offense Types](#offense-types) |
| `start_year`, `end_year` | integer | Yes | Inclusive range |
| `state` | string | No | State-level trend |
| `ori` | string | No | Agency-level trend (takes precedence over `state`) |
| `per_capita` | boolean | No | Trend on `rate_per_100k` (default) or on `total_incidents` |

One request covers the whole range. Returns `scope`, `metric`, `time_period`, `time_series` (per year: `total_incidents`, `rate_per_100k`, `months_reported`, `percent_change` from the previous year, `null` for the first) and `trend_analysis`: `overall_change` (percent, first to last year), `average_annual_change`, `direction` (`increasing` / `decreasing` beyond +/-5%, else `stable`), `peak_year`, `lowest_year`, `volatility` (mean absolute year-on-year change above 10% `high`, above 5% `medium`, else `low`).

### fbi_compare_states

Parameters: `states` (2-10 codes) and `offense_type` (required), `year`, `per_capita` (rank by rate, default, or by count), `include_national_average` (default true). One request per state. Returns `states_compared` (per state: `total_incidents`, `rate_per_100k`, `state_population`, `population_coverage_pct`, `percent_of_national`, `rank`), `comparison_summary` (`highest_state`, `lowest_state`, `range`, `average_of_compared`), `national_reference` (`rate_per_100k`), `metadata`, and `errors` for any state that could not be fetched.

---

## Offense Types

| `offense_type` | Summarized code (all tools but `fbi_get_offense_data`) | NIBRS code (`fbi_get_offense_data`) |
|----------------|------|------|
| `violent_crime` | `V` | none |
| `homicide` | `HOM` | `09A` Murder and Nonnegligent Manslaughter |
| `rape` | `RPE` | `11A` |
| `robbery` | `ROB` | `120` |
| `aggravated_assault` | `ASS` | `13A` |
| `property_crime` | `P` | none |
| `burglary` | `BUR` | `220` Burglary/Breaking & Entering |
| `larceny` | `LAR` | none (NIBRS splits larceny into several offenses) |
| `motor_vehicle_theft` | `MVT` | `240` |
| `arson` | `ARS` | `200` |
| `simple_assault` | none | `13B` |
| `kidnapping` | none | `100` Kidnapping/Abduction |
| `identity_theft` | none | `26F` |

The summarized figures combine Summary Reporting System (SRS) data and summarized NIBRS data; NIBRS figures cover only agencies that report incident-level data.

---

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "fbi_compare_states", "arguments": {"states": ["CA", "TX", "FL", "NY"], "offense_type": "violent_crime", "year": 2024}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "fbi_compare_states", "arguments": {"states": ["CA", "TX", "FL", "NY"], "offense_type": "violent_crime", "year": 2024}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("fbi_compare_states", states=["CA", "TX", "FL", "NY"], offense_type="violent_crime", year=2024)
```

A typical agency workflow: `fbi_search_agencies` with `{"state": "VT", "agency_name": "burlington"}` gives the ORI `VT0040100`; then `fbi_get_agency_statistics` with `{"ori": "VT0040100", "offense_type": "violent_crime"}` and `fbi_get_agency_details` with `{"ori": "VT0040100"}`.

---

## Error Handling

Errors are raised as `FBIAPIError` (a `ValueError`) with a message an agent can act on:

| Cause | Message says |
|-------|--------------|
| HTTP 403 (`API_KEY_MISSING`, `API_KEY_INVALID`, ...) | The key was rejected; set `FBI_API_KEY` (config key `fbi.api.key`) |
| HTTP 429 (`OVER_RATE_LIMIT`) | Rate limit exceeded; with no key configured, that the shared `DEMO_KEY` was used and how to set a key |
| HTTP 400 | The API's own explanation (for example an invalid offense or date format) |
| HTTP 404 | The API has no resource at the path |
| Network failure or timeout | The API is unreachable, or did not answer within `timeout` seconds |
| No data for the requested entity or year | Which state, agency or year had none |

Invalid arguments (unknown state or offense, malformed ORI, year out of range, `start_year` after `end_year`) are rejected before any request.

---

## Limitations

- Data starts in 1985 and is refreshed by the FBI on its own schedule; `metadata.data_available_through` reports the latest month.
- Rates are per 100,000 people in the covered population, as the API publishes them; the tools do not report the FBI's full-population estimates.
- Agency search is per state; federal agencies (listed by judicial district in the API) are not searchable.
- Agency counts by participation status are not published by the current API.
- Each call is one or two requests (one per state for `fbi_compare_states`), so a `DEMO_KEY` is exhausted quickly.

See the [Glossary](../../../GLOSSARY.md) for FBI, UCR, NIBRS and ORI.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
