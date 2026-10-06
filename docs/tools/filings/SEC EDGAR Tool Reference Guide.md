# SEC EDGAR Tool Reference Guide

SAJHA exposes the U.S. Securities and Exchange Commission's EDGAR data through two tool families. Both read the free, public SEC APIs (`data.sec.gov` and `www.sec.gov/files`) and need no API key.

| Family | Tool prefix | Implementation | Best for |
|--------|-------------|----------------|----------|
| [Enhanced EDGAR](#enhanced-edgar-tools-edgar_) | `edgar_*` | `sajha/tools/impl/enhanced_edgar_tool.py` | Form-specific filing lists, XBRL concepts and frames, computed ratios, industry/exchange discovery. Identifies companies by **CIK**. |
| [SEC EDGAR](#sec-edgar-tools-sec_) | `sec_*` | `sajha/tools/impl/sec_edgar_tool_refactored.py` | Quick lookups that accept either a **CIK or a ticker** (the ticker is resolved to a CIK for you). |

Each tool has a JSON definition in `config/tools/<tool_name>.json`; the `inputSchema` there is authoritative.

---

## Table of Contents

1. [Calling the tools](#calling-the-tools)
2. [SEC access rules](#sec-access-rules)
3. [Enhanced EDGAR tools (`edgar_*`)](#enhanced-edgar-tools-edgar_)
4. [SEC EDGAR tools (`sec_*`)](#sec-edgar-tools-sec_)
5. [Choosing a tool](#choosing-a-tool)
6. [Workflows](#workflows)
7. [Troubleshooting](#troubleshooting)
8. [Quick reference](#quick-reference)

---

## Calling the tools

Call any tool over MCP with `tools/call` on `POST /mcp`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "edgar_company_search",
    "arguments": {"query": "AAPL", "search_type": "ticker"}
  }
}
```

The `Mcp-Session-Id` header is optional. For the handshake, protocol versions and streaming, see the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

Or use the REST execute route:

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"tool": "sec_get_company_info", "arguments": {"ticker": "MSFT"}}'
```

A successful call returns `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. The host and port depend on your deployment; see the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

The examples below show only the `arguments` object.

---

## SEC access rules

- **No API key.** EDGAR is public. Neither family reads any `*.api.key` setting.
- **User-Agent.** The SEC requires every request to carry a descriptive `User-Agent` that includes a contact email, and it answers `403 Forbidden` without one. Both implementations set this header for you: `edgar_*` sends `Enhanced EDGAR Tool ashutosh.sinha@research.com` and `sec_*` sends `SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)`. The values are hard-coded in the implementation classes; no config key controls them.
- **Rate limit.** The SEC allows at most 10 requests per second per client. The `edgar_*` tools throttle themselves to one request every 110 ms. The `sec_*` tools do not throttle, so space out bulk loops yourself. If you exceed the limit, the SEC returns HTTP 429, which the tool reports as an error, and repeated abuse can get your IP blocked temporarily.
- **Caching.** The `edgar_*` family caches the SEC company-tickers file for one hour per tool instance. Nothing else is cached.
- **Data freshness.** Filings appear on EDGAR shortly after acceptance. After-hours filings show up the next business day. XBRL data exists only for filings from about 2009 onward.

SEC endpoints in use:

| Endpoint | Used for |
|----------|----------|
| `https://www.sec.gov/files/company_tickers.json` (and the `data.sec.gov` mirror) | Company search, ticker to CIK |
| `https://data.sec.gov/submissions/CIK{cik}.json` | Company profile and filing lists |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | All XBRL facts for a company |
| `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json` | One concept over time |
| `https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{frame}.json` | One concept across all companies |

**CIK format.** A CIK is the SEC's numeric company identifier. Every tool accepts it with or without leading zeros (`320193` or `0000320193`) and pads it to 10 digits internally.

---

## Enhanced EDGAR tools (`edgar_*`)

All `edgar_*` tools identify companies by `cik`. If you only have a name or ticker, call `edgar_company_search` first to get the CIK.

### Discovery

#### edgar_company_search

Finds companies by name or ticker and returns their CIKs.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `query` | string | yes | | Company name or ticker, e.g. `Apple Inc`, `AAPL` |
| `search_type` | string | no | `auto` | `name`, `ticker`, `auto` |
| `limit` | integer | no | 10 | 1 to 100 |

```json
{"query": "Microsoft", "search_type": "name", "limit": 5}
```

#### edgar_company_tickers_by_exchange

Lists companies listed on one exchange.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `exchange` | string | yes | | `Nasdaq`, `NYSE`, `AMEX`, `BATS`, `OTC` |
| `limit` | integer | no | 100 | 1 to 5000 |

```json
{"exchange": "NYSE", "limit": 50}
```

The tool filters the SEC company-tickers file on an `exchange` field. If that file has no exchange data, the result can be empty. In that case, filter `edgar_company_search` results instead.

#### edgar_companies_by_sic

Finds companies in one industry by SIC code.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `sic_code` | string | yes | | 4-digit SIC, e.g. `7372` (software), `3674` (semiconductors), `6022` (state commercial banks) |
| `limit` | integer | no | 50 | 1 to 500 |

```json
{"sic_code": "3674", "limit": 20}
```

This tool fetches the submissions record of each listed company until it has collected `limit` matches. At 110 ms per request it is slow, so keep `limit` small.

### Company information

#### edgar_company_submissions

Returns a company profile (name, SIC, category, fiscal year end, state of incorporation, business and mailing addresses) and its recent filings (accession number, filing and report dates, form, primary document).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | e.g. `0000320193` |
| `include_old_filings` | boolean | no | false | Accepted, but the current implementation returns only the SEC's "recent" filings block |

```json
{"cik": "0000320193"}
```

#### edgar_filing_details

Returns one filing by accession number, with its SEC viewer URL (`document_url`) and its archive URL (`filing_url`).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `accession_number` | string | yes | | With or without dashes: `0000320193-23-000077` |

```json
{"cik": "320193", "accession_number": "0000320193-23-000077"}
```

### Financial data (XBRL)

#### edgar_company_facts

Returns every XBRL fact the company has reported, across all taxonomies. The response is large: several MB for big filers. Use `edgar_company_concept` when you need one metric.

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `cik` | string | yes | |

```json
{"cik": "0000789019"}
```

#### edgar_company_concept

Returns the full history of one concept for one company, grouped by unit, with fiscal year, period, form and filing date for each value.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `concept` | string | yes | | e.g. `Revenues`, `Assets`, `NetIncomeLoss`, `EarningsPerShareBasic` |
| `taxonomy` | string | no | `us-gaap` | `us-gaap`, `ifrs-full`, `dei`, `srt` |

```json
{"cik": "0000320193", "concept": "NetIncomeLoss"}
```

#### edgar_financial_ratios

Computes ratios from the company's XBRL facts for one fiscal period:

- **Profitability:** gross, operating and net margin, ROA, ROE.
- **Liquidity:** current, quick and cash ratio.
- **Solvency:** debt-to-equity, debt-to-assets, equity multiplier.

A ratio is left out when any of its inputs is missing.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `fiscal_year` | integer | no | | 2009 to 2030 |
| `fiscal_period` | string | no | `FY` | `FY`, `Q1`, `Q2`, `Q3`, `Q4` |

```json
{"cik": "0000320193", "fiscal_year": 2023, "fiscal_period": "FY"}
```

#### edgar_frame_data

Returns one concept for every reporting company in one period (an XBRL frame). Use it for market-wide comparisons.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `concept` | string | yes | | e.g. `Revenues`, `Assets` |
| `year` | integer | yes | | 2009 to 2030 |
| `quarter` | string | no | `CY` | `Q1` to `Q4`, or `CY` for the full calendar year |
| `taxonomy` | string | no | `us-gaap` | `us-gaap`, `ifrs-full`, `dei`, `srt` |
| `unit` | string | no | `USD` | `USD`, `shares`, `pure` |

```json
{"concept": "Revenues", "year": 2023, "quarter": "CY"}
```

#### edgar_xbrl_frames_multi_concept

Same as `edgar_frame_data` for several concepts in one call. A concept that fails comes back with an `error` entry, and the other concepts are still returned.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `concepts` | array of string | yes | | e.g. `["Revenues", "NetIncomeLoss", "Assets"]` |
| `year` | integer | yes | | 2009 to 2030 |
| `quarter` | string | no | `CY` | `Q1` to `Q4`, `CY` |
| `taxonomy` | string | no | `us-gaap` | |
| `unit` | string | no | `USD` | `USD`, `shares`, `pure` |

```json
{"concepts": ["Assets", "Liabilities", "StockholdersEquity"], "year": 2023}
```

### Filings by type

Each tool in this group returns filing metadata: form, filing and report dates, accession number, primary document and an SEC viewer `document_url`. None of them parses the filing contents. To get the direct archive URL for a filing, pass its accession number to `edgar_filing_details`.

#### edgar_filings_by_form

The general-purpose filter. The specialised tools after it call this one with a fixed form type.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `form_type` | string | yes | | `10-K`, `10-Q`, `8-K`, `3`, `4`, `5`, `S-1`, `S-3`, `S-4`, `S-8`, `DEF 14A`, `13F-HR`, `13F-NT`, `20-F`, `6-K`, `40-F`, `424B2` to `424B5`, `SC 13D`, `SC 13G`, `SC 13G/A`, `144`, `N-Q`, `N-CSR`, `N-PORT`, `NPORT-P` |
| `start_date` | string | no | | `YYYY-MM-DD`, compared with the filing date |
| `end_date` | string | no | | `YYYY-MM-DD` |
| `limit` | integer | no | 50 | 1 to 500 |

```json
{"cik": "0001318605", "form_type": "10-Q", "start_date": "2023-01-01", "end_date": "2023-12-31"}
```

#### edgar_current_reports

Lists 8-K current reports, which disclose material events.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `start_date` / `end_date` | string | no | | `YYYY-MM-DD` |
| `limit` | integer | no | 50 | 1 to 200 |

```json
{"cik": "0000320193", "start_date": "2024-01-01"}
```

#### edgar_proxy_statements

Lists DEF 14A proxy statements, which cover executive compensation and shareholder votes.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `limit` | integer | no | 10 | 1 to 50 |

```json
{"cik": "0000789019", "limit": 3}
```

#### edgar_registration_statements

Lists securities registration statements, such as the S-1 for an IPO.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `form_type` | string | no | `S-1` | `S-1`, `S-3`, `S-4`, `S-8` |
| `limit` | integer | no | 10 | 1 to 50 |

```json
{"cik": "0001318605", "form_type": "S-1"}
```

#### edgar_foreign_issuers

Lists filings by foreign private issuers.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `form_type` | string | yes | `20-F` | `20-F` (annual), `6-K` (current), `40-F` (Canadian annual) |
| `limit` | integer | no | 20 | 1 to 100 |

```json
{"cik": "0001046179", "form_type": "20-F"}
```

#### edgar_amendments

Lists amended filings (10-K/A, 10-Q/A, 8-K/A), which flag corrections and restatements.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `limit` | integer | no | 20 | 1 to 100 |

```json
{"cik": "0000320193"}
```

### Ownership and holdings

#### edgar_insider_transactions

Lists Form 4 filings: trades by officers, directors and 10% owners.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | CIK of the company |
| `limit` | integer | no | 20 | 1 to 100 |

```json
{"cik": "0001318605", "limit": 10}
```

#### edgar_ownership_reports

Lists beneficial-ownership reports (SC 13D/13G) for holders of 5% or more.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | |
| `form_type` | string | no | `SC 13D` | `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A` |
| `limit` | integer | no | 20 | 1 to 100 |

```json
{"cik": "0000320193", "form_type": "SC 13G"}
```

#### edgar_institutional_holdings

Lists an investment manager's quarterly 13F-HR filings. Pass the **manager's** CIK, not the CIK of a company it holds.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | e.g. Berkshire Hathaway `0001067983` |
| `limit` | integer | no | 10 | 1 to 50 |

```json
{"cik": "0001067983", "limit": 4}
```

#### edgar_mutual_fund_holdings

Lists a mutual fund's monthly N-PORT portfolio filings.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` | string | yes | | CIK of the fund |
| `limit` | integer | no | 10 | 1 to 50 |

```json
{"cik": "0000036405", "limit": 3}
```

---

## SEC EDGAR tools (`sec_*`)

Every `sec_*` tool except `sec_search_company` takes **either** `cik` **or** `ticker`. Neither is required by the schema, but you must pass one of them, or the call fails with `Either 'cik' or 'ticker' is required`. A ticker is resolved through the SEC company-tickers file.

#### sec_search_company

Finds companies whose name or ticker contains the search term (case-insensitive substring match).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `search_term` | string | yes | | e.g. `Apple`, `AAPL` |
| `limit` | integer | no | 10 | 1 to 100 |

```json
{"search_term": "Tesla"}
```

#### sec_get_company_info

Returns the company profile: name, tickers, exchanges, SIC code and description, fiscal year end, state of incorporation, and business and mailing addresses.

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `cik` / `ticker` | string | one of them | |

```json
{"ticker": "MSFT"}
```

#### sec_get_company_filings

Lists recent filings, optionally filtered by form and filing-date range.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` / `ticker` | string | one of them | | |
| `filing_type` | string | no | | `10-K`, `10-Q`, `8-K`, `10-K/A`, `10-Q/A`, `S-1`, `S-3`, `S-4`, `13F-HR`, `4`, `DEF 14A`, `20-F`, `6-K`, `SC 13D`, `SC 13G` |
| `start_date` / `end_date` | string | no | | `YYYY-MM-DD` |
| `limit` | integer | no | 10 | 1 to 100 |

```json
{"ticker": "AAPL", "filing_type": "10-K", "limit": 5}
```

#### sec_get_company_facts

Returns every XBRL fact the company has reported. The response is large; prefer `sec_get_financial_data` for a single metric.

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `cik` / `ticker` | string | one of them | |

```json
{"cik": "0000320193"}
```

#### sec_get_financial_data

Returns one metric with all its reported values grouped by unit. Without `fact_type`, it returns the names of the facts available in each taxonomy, which is useful for discovering which tags a company uses.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` / `ticker` | string | one of them | | |
| `fact_type` | string | no | | `Assets`, `Liabilities`, `StockholdersEquity`, `Revenues`, `NetIncomeLoss`, `EarningsPerShare`, `Cash`, `OperatingIncome`, `GrossProfit`, `CurrentAssets`, `CurrentLiabilities`, `LongTermDebt` |

```json
{"ticker": "AAPL", "fact_type": "NetIncomeLoss"}
```

Companies differ in which tag they report. Apple, for example, reports revenue as `RevenueFromContractWithCustomerExcludingAssessedTax`, not `Revenues`. If a metric comes back empty, call the tool without `fact_type` to list the available facts, or use `edgar_company_concept`, which accepts any tag.

#### sec_get_insider_trading

Lists recent Form 4 insider filings.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` / `ticker` | string | one of them | | |
| `limit` | integer | no | 10 | 1 to 100 |

```json
{"ticker": "TSLA", "limit": 20}
```

#### sec_get_mutual_fund_holdings

Despite its name, this tool lists an institutional manager's **Form 13F-HR** filings, the same data as `edgar_institutional_holdings`. Pass the manager's CIK. For N-PORT fund holdings, use `edgar_mutual_fund_holdings`.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `cik` / `ticker` | string | one of them | | Use the CIK; managers rarely have a ticker |
| `limit` | integer | no | 5 | 1 to 20 |

```json
{"cik": "0001067983", "limit": 4}
```

---

## Choosing a tool

| Need | `edgar_*` | `sec_*` |
|------|-----------|---------|
| Find a company / CIK | `edgar_company_search` | `sec_search_company` |
| Company profile | `edgar_company_submissions` | `sec_get_company_info` |
| Filings list | `edgar_filings_by_form` and the form-specific tools | `sec_get_company_filings` |
| One filing by accession number | `edgar_filing_details` | |
| All XBRL facts | `edgar_company_facts` | `sec_get_company_facts` |
| One metric over time | `edgar_company_concept` (any tag) | `sec_get_financial_data` (fixed list) |
| Ratios | `edgar_financial_ratios` | |
| Cross-company comparison | `edgar_frame_data`, `edgar_xbrl_frames_multi_concept` | |
| Industry / exchange screening | `edgar_companies_by_sic`, `edgar_company_tickers_by_exchange` | |
| Insider trades (Form 4) | `edgar_insider_transactions` | `sec_get_insider_trading` |
| 13F holdings | `edgar_institutional_holdings` | `sec_get_mutual_fund_holdings` |
| N-PORT fund holdings | `edgar_mutual_fund_holdings` | |
| 13D/13G, proxies, registrations, 8-K, amendments, foreign issuers | the matching `edgar_*` tool | |

Use the `sec_*` tools when you start from a ticker. Use the `edgar_*` tools for form-specific or cross-company work.

---

## Workflows

**Fundamental snapshot from a ticker**

1. `sec_get_company_info` `{"ticker": "NVDA"}`: gives the CIK, SIC and fiscal year end.
2. `edgar_financial_ratios` `{"cik": "<cik>", "fiscal_year": 2024}`
3. `edgar_company_concept` `{"cik": "<cik>", "concept": "NetIncomeLoss"}`: gives the trend.

**Peer benchmark**

1. `edgar_companies_by_sic` `{"sic_code": "7372", "limit": 10}`
2. `edgar_xbrl_frames_multi_concept` `{"concepts": ["Revenues", "NetIncomeLoss"], "year": 2023}`, then filter on the peer CIKs.

**Event and governance monitoring**

1. `edgar_current_reports` with `start_date` set to the last check date.
2. `edgar_insider_transactions` and `edgar_ownership_reports` for the same CIK.
3. `edgar_amendments` to catch restatements.

**Institutional positioning**

1. `edgar_company_search` to find the manager (for example `Berkshire Hathaway`).
2. `edgar_institutional_holdings` with the manager's CIK.
3. `edgar_filing_details` with an accession number from step 2, then open `filing_url` for the holdings document.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Access forbidden. Ensure User-Agent header is properly set.` (HTTP 403) | The SEC rejected the request, usually because of the User-Agent policy or a temporary block | Wait and retry; check that outbound traffic is not rewritten by a proxy |
| `Rate limit exceeded` (HTTP 429) | More than 10 requests per second, often from parallel `sec_*` calls | Serialize calls or add delays |
| `Resource not found` / `Company not found: CIK …` | Wrong CIK, or no data of that kind (for example no XBRL facts) | Look up the CIK with a search tool; check that the company files 10-K/10-Q |
| `Ticker not found` | Delisted ticker, or a share-class ticker missing from the SEC file | Search by name and use the CIK |
| `Either 'cik' or 'ticker' is required` | A `sec_*` call with neither argument | Pass one of them |
| Empty `filings` list | No filings of that form in the SEC's recent-filings window, or a date range that excludes them | Widen the dates; very old filings are outside the recent window these tools read |
| Empty frame data or ratios | The concept tag is not used by any filer, or not for that period or unit | Try alternate tags (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`) or a different `unit` |
| Slow `edgar_companies_by_sic` | One request per company scanned | Lower `limit` |

All errors come back as standard tool errors; see the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for the error envelope.

---

## Quick reference

**Common CIKs:**

| Company | Ticker | CIK |
|---------|--------|-----|
| Apple | AAPL | 0000320193 |
| Microsoft | MSFT | 0000789019 |
| Alphabet | GOOGL | 0001652044 |
| Amazon | AMZN | 0001018724 |
| Tesla | TSLA | 0001318605 |
| Meta Platforms | META | 0001326801 |
| JPMorgan Chase | JPM | 0000019617 |
| Berkshire Hathaway (also a 13F filer) | BRK-B | 0001067983 |

**Common SIC codes:**

| SIC | Industry |
|-----|----------|
| 7372 | Prepackaged software |
| 3674 | Semiconductors |
| 6022 | State commercial banks |
| 2834 | Pharmaceutical preparations |
| 3711 | Motor vehicles |

**Common us-gaap concepts:** `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `NetIncomeLoss`, `Assets`, `Liabilities`, `StockholdersEquity`, `CashAndCashEquivalentsAtCarryingValue`, `EarningsPerShareBasic`, `OperatingIncomeLoss`.

**Common forms:**

| Form | What it is |
|------|------------|
| 10-K | Annual report |
| 10-Q | Quarterly report |
| 8-K | Current report |
| DEF 14A | Proxy statement |
| 3 / 4 / 5 | Insider ownership |
| 13F-HR | Institutional holdings |
| SC 13D / 13G | 5%+ ownership |
| S-1 | IPO registration |
| 20-F / 6-K / 40-F | Foreign issuers |
| N-PORT | Fund holdings |

SEC data is public-domain information provided by the U.S. Securities and Exchange Commission. Tool output is for research and is not investment advice. The SEC filing is always the authoritative source.

---

*Terms used in this guide are defined in the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
