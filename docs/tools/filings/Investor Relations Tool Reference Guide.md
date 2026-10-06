# Investor Relations Tool Reference Guide

The Investor Relations (IR) tools fetch documents from public company IR websites: annual reports, earnings and investor presentations, proxy statements, press releases and ESG reports. They scrape the company's IR pages. When scraping finds nothing and the company's CIK is known, they fall back to SEC EDGAR filings.

The tools are implemented in `sajha/tools/impl/investor_relations_tool_refactored.py`, which builds on the scrapers in `sajha/ir/`. Each tool is defined in `config/tools/ir_*.json`, and the `inputSchema` there is authoritative. No API key is needed.

---

## Table of Contents

1. [Calling the tools](#calling-the-tools)
2. [Supported companies](#supported-companies)
3. [Tools](#tools)
4. [Document types and result shape](#document-types-and-result-shape)
5. [Workflows](#workflows)
6. [Limitations](#limitations)
7. [Troubleshooting](#troubleshooting)

---

## Calling the tools

MCP `tools/call` on `POST /mcp`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {"name": "ir_get_latest_earnings", "arguments": {"ticker": "MSFT"}}
}
```

REST:

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"tool": "ir_get_annual_reports", "arguments": {"ticker": "JPM", "limit": 3}}'
```

A successful call returns `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. For protocol details, see the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md). For server settings, see the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

---

## Supported companies

The tools serve only companies in the IR company database (`sajha/ir/company_database.py`). Its built-in entries are:

| Ticker | Company |
|--------|---------|
| AAPL | Apple Inc. |
| MSFT | Microsoft Corporation |
| GOOGL | Alphabet Inc. |
| AMZN | Amazon.com Inc. |
| NVDA | NVIDIA Corporation |
| TSLA | Tesla Inc. |
| JPM | JPMorgan Chase & Co. |
| GS | Goldman Sachs Group Inc. |
| BAC | Bank of America Corporation |
| WMT | Walmart Inc. |

Call `ir_list_supported_companies` for the live list. Any other ticker fails with `Ticker XYZ is not supported. Supported tickers: ...`.

`config/ir/sp500_companies.json` holds a larger company list in the same format, but the MCP tools do not load it. Only the standalone demo in `sajha/ir/demo.py` reads it.

---

## Tools

Every tool except `ir_list_supported_companies` requires `ticker`, matched case-insensitively. Each successful result includes `"success": true`.

### ir_list_supported_companies

Lists the supported companies. It takes no parameters. The result has `total_supported`, `supported_tickers`, `companies_with_cik`, `platforms`, and a `scrapers` array that gives each company's name, IR page URL, IR platform and whether SEC fallback is available.

```json
{}
```

### ir_find_page

Returns the company's IR page URL as `ir_page_url`.

| Parameter | Type | Required |
|-----------|------|----------|
| `ticker` | string | yes |

```json
{"ticker": "TSLA"}
```

### ir_get_documents

Returns documents of one type, or of all types, optionally for one year.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `ticker` | string | yes | | |
| `document_type` | string | no | `all` | `annual_report`, `quarterly_report`, `earnings_presentation`, `investor_presentation`, `proxy_statement`, `press_release`, `esg_report`, `all` |
| `year` | integer | no | | 2000 to 2030 |
| `limit` | integer | no | 10 | 1 to 50 |

```json
{"ticker": "JPM", "document_type": "earnings_presentation", "year": 2024, "limit": 5}
```

### ir_get_latest_earnings

Returns the newest earnings-presentation document as `latest_earnings` and up to four earlier ones as `previous_earnings`. If no earnings documents are found, `latest_earnings` is `null` and a `message` is included.

| Parameter | Type | Required |
|-----------|------|----------|
| `ticker` | string | yes |

```json
{"ticker": "MSFT"}
```

### ir_get_annual_reports

Returns annual reports as `annual_reports`, with a `count`.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `ticker` | string | yes | | |
| `year` | integer | no | | 2000 to 2030 |
| `limit` | integer | no | 5 | 1 to 20 |

```json
{"ticker": "GS", "year": 2023}
```

### ir_get_presentations

Returns investor and earnings presentations together as `presentations`, with duplicate URLs removed.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `ticker` | string | yes | | |
| `limit` | integer | no | 10 | 1 to 30 |

```json
{"ticker": "NVDA", "limit": 5}
```

### ir_get_all_resources

Returns everything in one call: `ir_page`, `annual_reports` (up to 3), `latest_earnings`, and `presentations` (up to 5). It makes several scraping passes, so it is the slowest tool.

| Parameter | Type | Required |
|-----------|------|----------|
| `ticker` | string | yes |

```json
{"ticker": "AAPL"}
```

### Choosing a tool

| Need | Tool |
|------|------|
| Which tickers work | `ir_list_supported_companies` |
| IR page URL | `ir_find_page` |
| Filter by type or year | `ir_get_documents` |
| Latest quarter | `ir_get_latest_earnings` |
| Annual reports only | `ir_get_annual_reports` |
| Slide decks | `ir_get_presentations` |
| Everything at once | `ir_get_all_resources` |

---

## Document types and result shape

| Type | Contents |
|------|----------|
| `annual_report` | Annual report or 10-K |
| `quarterly_report` | Quarterly report or 10-Q |
| `earnings_presentation` | Earnings-call slides and releases |
| `investor_presentation` | Strategy, investor-day and conference decks |
| `proxy_statement` | Annual meeting proxy materials (DEF 14A) |
| `press_release` | News and earnings releases |
| `esg_report` | Sustainability / ESG report |
| `all` | Every type above |

Each document object has the following fields:

```json
{
  "title": "FY2024 Annual Report",
  "url": "https://.../annual-report-2024.pdf",
  "type": "annual_report",
  "year": 2024,
  "quarter": null,
  "date": null,
  "description": null,
  "ticker": "MSFT",
  "is_pdf": true,
  "context": "..."
}
```

The scraper infers `year` and `quarter` from the link text and URL when the page does not state them, so both can be `null`.

---

## Workflows

**Latest results for a company**

1. `ir_list_supported_companies` to confirm the ticker.
2. `ir_get_latest_earnings` `{"ticker": "JPM"}`

**Multi-year annual reports**

1. `ir_get_annual_reports` `{"ticker": "MSFT", "limit": 5}`
2. Fetch the PDF URLs, or pair them with XBRL numbers from the [SEC EDGAR tools](SEC%20EDGAR%20Tool%20Reference%20Guide.md).

**Peer comparison**

Call `ir_get_latest_earnings` for each ticker (for example `JPM`, `GS`, `BAC`). Run the calls one after another, because each one throttles its own requests.

---

## Limitations

- **Coverage.** Only tickers in the company database are served.
- **Scraping.** Results depend on the current layout of each IR site. A site redesign, a bot-protection page or a login wall can return fewer documents, or none.
- **Speed.** The HTTP client waits 2 to 5 seconds between requests to the same site and retries up to 3 times with a 30-second timeout. Expect calls to take several seconds, and longer for `ir_get_all_resources`.
- **Completeness.** Older documents may be archived elsewhere on the site and missed. The SEC fallback returns filings, not slide decks.
- **Etiquette.** Respect each site's terms of use and robots.txt. Cache results on your side instead of polling.

---

## Troubleshooting

| Error / symptom | Cause | Fix |
|-----------------|-------|-----|
| `Ticker XYZ is not supported. Supported tickers: ...` | The ticker is not in the company database | Use a listed ticker |
| `Failed to create scraper for ticker: XYZ` | The scraper could not be built from the company entry | Check the server log; the company entry may be incomplete |
| `Failed to get documents: ...` (or `annual reports`, `latest earnings`, and so on) | A network error, timeout, or blocked request during scraping | Retry later; check outbound access to the IR site |
| Empty list or `latest_earnings: null` | The page layout matched no links of that type, and the SEC fallback found nothing | Try `document_type: "all"` or `ir_find_page` and open the page directly |

---

*Terms used in this guide are defined in the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
