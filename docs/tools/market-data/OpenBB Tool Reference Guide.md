# OpenBB Tool Reference Guide

## Overview

The OpenBB tools (prefix `openbb_`) expose the [OpenBB Platform](https://docs.openbb.co/platform) Python SDK (`obb`) for equities, fundamentals, ETFs, indexes, fixed income, economy, commodities, forex, crypto, derivatives, news and SEC data. Implementation: `sajha/tools/impl/openbb_tools.py`.

## Installation and Keys

The SDK is loaded lazily on the first call (it takes a few seconds to import); if it is missing
the tool returns an error asking you to install it. `requirements.txt` pins the OpenBB version
the tools are checked against (4.6) and the provider extras SAJHA uses:

```bash
pip install "openbb[alpha_vantage,ecb,nasdaq]"   # as in requirements.txt
pip install "openbb[all]"                         # every provider
```

Providers that need credentials get them in one of two ways:

- **Keys SAJHA already has.** When OpenBB loads, SAJHA copies `fmp.api.key`, `fred.api.key` and
  `alpha_vantage.api.key` (normally from the `FMP_API_KEY`, `FRED_API_KEY` and
  `ALPHA_VANTAGE_API_KEY` environment variables, see the
  [Configuration Reference](../../getting-started/Configuration%20Reference.md)) into OpenBB's session
  credentials (`fmp_api_key`, `fred_api_key`, `alpha_vantage_api_key`). OpenBB commands take no
  per-call credentials, so this is done once per process, and only for a credential that OpenBB's own
  settings leave empty.
- **Other providers** (benzinga, intrinio, polygon, tiingo, tradingeconomics) read their keys from
  OpenBB's own store, `~/.openbb_platform/user_settings.json` of the user SAJHA runs as:

```json
{"credentials": {"intrinio_api_key": "...", "polygon_api_key": "...", "benzinga_api_key": "..."}}
```

A key set in `user_settings.json` wins over SAJHA's. yfinance, federal_reserve, oecd, sec, nasdaq,
econdb, imf and government_us need no key. Each tool's description lists, for its own providers,
which need none, which use SAJHA's key and which need `user_settings.json`.

## The `provider` Argument

Every tool takes an optional `provider`, limited by its schema to the providers the installed
OpenBB offers for that command. When it is omitted the tool uses the schema's default, which is a
keyless provider wherever the command has one (yfinance, federal_reserve, oecd, sec, nasdaq, econdb,
government_us); commands that only exist for keyed providers default to fmp or fred, whose keys SAJHA
passes on. A provider the command does not offer is refused with the list of those it does.

## How a Call Runs

Each tool names one OpenBB command in `TOOL_COMMANDS` (`sajha/tools/impl/openbb_tools.py`), for
example `openbb_fixedincome_sofr` runs `obb.fixedincome.rate.sofr`. A few tools rename an argument
(`openbb_equity_screener` sends `market_cap_min` and `market_cap_max` as OpenBB's `mktcap_min` and
`mktcap_max`; `openbb_index_constituents` sends `index` as `symbol`). A call:

1. resolves the command in the installed OpenBB. If it is not there (an older or newer OpenBB), the
   tool answers with an error naming the command and raises the info notice
   `tools.openbb_command:<tool>` ([System Notices](../../architecture/System%20Notices.md));
2. sends only the arguments the command accepts for the chosen provider. Arguments that do not apply
   (for example `period` with yfinance metrics) are left out and listed in `ignored_arguments`;
3. returns every row with its date (OpenBB keeps dates in the DataFrame index, so rows are read from
   the result models);
4. caps the rows at `limit` (1 to 1000; each tool's schema has its default). A dated series in
   ascending order keeps its most recent rows; other results keep their first rows. `data_points`
   is the row count before the cap and `truncated` says whether rows were cut. `limit` is also sent to
   commands that accept one. The price-history tools (`openbb_equity_price`, `openbb_forex_historical`,
   `openbb_crypto_price`) return every row of their date range instead.

Errors from OpenBB (a missing credential, no data, a bad value) come back as `{"error": ...}`.
One exception: `openbb_economy_calendar` (`OpenBBEconomyCalendarTool`) treats a window with no events
(nasdaq's "No record found") as an empty result with a `note`, and without dates it asks for the past
7 days to the next 7, since the providers' own default is today only, which is empty on a weekend.
The answer echoes `start_date` and `end_date`.

**Network.** OpenBB's provider extensions fetch with their own HTTP clients, so the `openbb_` tools
bypass SAJHA's outbound fetch guard and `tools.outbound.proxy`; they connect only to their providers'
fixed hosts. Where SAJHA must reach the internet through a proxy, these tools work only if the network
lets the server reach those hosts directly (a known limit,
[Security Model](../../security/Security%20Model.md#8-known-limitations)).
Adding a tool needs a JSON config **and** an entry in `TOOL_COMMANDS`;
`tests/test_market_data_fixes.py` checks every shipped tool's command, provider list, default and
arguments against the installed OpenBB.

### Removed tools

These tools were removed ([CHANGELOG](../../../CHANGELOG.md)) because OpenBB 4.6 has no command for them: `openbb_commodity_lbma_gold` and
`openbb_commodity_lbma_silver` (use `openbb_derivatives_futures_historical` with `GC=F` or `SI=F`,
or `imf_get_data` with database `PCPS`, key `G001.PGOLD.USD.M` or `G001.PSILVER.USD.M`), `openbb_commodity_search` (`openbb_commodity_price`
lists its commodities), `openbb_index_search` (`openbb_index_available`),
`openbb_equity_fundamental_overview` (`openbb_equity_profile`, `openbb_equity_metrics`),
`openbb_fixedincome_moody` (`fred_custom_series` with `AAA` or `BAA`) and `openbb_news_search`,
whose command had no search parameter (`openbb_market_news`, `openbb_company_news`,
`tavily_news_search`).

## Tools

The tables below are generated from the tool configs (`python -m sajha.tools guides`); the live catalog in the app (Tools page, or `tools/list`) is authoritative. Defaults shown are the schema defaults.

<!-- generated:tools folder=openbb group=category -->
<!-- Generated by `python -m sajha.tools guides` from the tool configs in `config/tools/openbb/`; edit the configs, not this table. -->

### Analyst

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_estimates_consensus` | Analyst consensus price targets and recommendation for one stock through the OpenBB Platform (obb.equity.estimates.consensus). | `symbol` | `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Calendar

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_economy_calendar` | Economic events calendar (releases with actual, consensus and previous values) through the OpenBB Platform (obb.economy.calendar). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`nasdaq`) | read-only, idempotent, open-world |
| `openbb_equity_calendar_dividend` | Upcoming dividend events across the market through the OpenBB Platform (obb.equity.calendar.dividend). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`nasdaq`) | read-only, idempotent, open-world |
| `openbb_equity_calendar_earnings` | Upcoming earnings announcements across the market through the OpenBB Platform (obb.equity.calendar.earnings). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`nasdaq`) | read-only, idempotent, open-world |

### Commodities

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_commodity_price` | Energy spot prices (EIA series on FRED: crude oil, natural gas, fuels) through the OpenBB Platform (obb.commodity.price.spot). | — | `commodity` (`wti`), `start_date`, `end_date`, `limit` (`100`), `provider` (`fred`) | read-only, idempotent, open-world |

### Company Data

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_management` | Executives and key officers of one company (name, title, pay where available) through the OpenBB Platform (obb.equity.fundamental.management). | `symbol` | `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_profile` | Company profile for one stock through the OpenBB Platform (obb.equity.profile). | `symbol` | `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_share_statistics` | Share statistics for one stock (shares outstanding, float, short interest, ownership) through the OpenBB Platform (obb.equity.ownership.share_statistics). | `symbol` | `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Cryptocurrency

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_crypto_price` | Daily price history for one cryptocurrency pair through the OpenBB Platform (obb.crypto.price.historical). | — | `symbol` (`BTCUSD`), `start_date`, `end_date`, `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_crypto_search` | Search cryptocurrency symbols by name or ticker through the OpenBB Platform (obb.crypto.search). | `query` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |

### Derivatives

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_derivatives_futures_curve` | Futures term structure (price by expiration) for one commodity or financial future from Yahoo Finance through the OpenBB Platform (obb.derivatives.futures.curve). | — | `symbol` (`CL`), `date`, `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_derivatives_futures_historical` | Daily price history of a futures contract from Yahoo Finance through the OpenBB Platform (obb.derivatives.futures.historical). | — | `symbol` (`CL=F`), `start_date`, `end_date`, `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_options_chains` | Option chain for one underlying through the OpenBB Platform (obb.derivatives.options.chains). | `symbol` | `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Dividends

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_dividends` | Dividend history for one stock through the OpenBB Platform (obb.equity.fundamental.dividends). | `symbol` | `start_date`, `end_date`, `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Earnings

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_earnings` | Reported versus estimated EPS history for one company through the OpenBB Platform (obb.equity.fundamental.historical_eps). | `symbol` | `limit` (`8`), `provider` (`alpha_vantage`) | read-only, idempotent, open-world |

### Economics

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_economic_indicators` | One economic indicator series for a country through the OpenBB Platform (obb.economy.indicators). | — | `symbol` (`CPI`), `country` (`US`), `frequency` (`quarter`), `limit` (`100`), `provider` (`econdb`) | read-only, idempotent, open-world |
| `openbb_economy_available_indicators` | Catalogue of economic indicator codes and countries a provider offers, through the OpenBB Platform (obb.economy.available_indicators). | — | `query`, `limit` (`100`), `provider` (`econdb`) | read-only, idempotent, open-world |
| `openbb_economy_cpi` | Consumer price inflation for a country (year-on-year percent, monthly) through the OpenBB Platform (obb.economy.cpi). | — | `country` (`united_states`), `limit` (`100`), `provider` (`oecd`) | read-only, idempotent, open-world |
| `openbb_economy_gdp` | Nominal GDP for a country through the OpenBB Platform (obb.economy.gdp.nominal). | — | `country` (`united_states`), `limit` (`100`), `provider` (`oecd`) | read-only, idempotent, open-world |
| `openbb_economy_interest_rate` | Interest rates by country from the OECD (call money, 3-month or 10-year) through the OpenBB Platform (obb.economy.interest_rates). | — | `country` (`united_states`), `duration` (`short`), `start_date`, `end_date`, `limit` (`100`), `provider` (`oecd`) | read-only, idempotent, open-world |
| `openbb_economy_leading` | OECD composite leading indicator for a country (turning-point signal; 100 = long-term trend) through the OpenBB Platform (obb.economy.composite_leading_indicator). | — | `country` (`united_states`), `start_date`, `limit` (`100`), `provider` (`oecd`) | read-only, idempotent, open-world |
| `openbb_economy_risk_premium` | Equity market risk premium by country (total equity and country risk premium) through the OpenBB Platform (obb.economy.risk_premium). | — | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_unemployment` | Unemployment rate (percent) for a country from the OECD through the OpenBB Platform (obb.economy.unemployment). | — | `country` (`united_states`), `limit` (`100`), `provider` (`oecd`) | read-only, idempotent, open-world |

### ETFs

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_etf_countries` | Country weights of one ETF through the OpenBB Platform (obb.etf.countries). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_etf_equity_exposure` | ETFs that hold a given stock, with weight and market value through the OpenBB Platform (obb.etf.equity_exposure). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_etf_holdings` | Holdings of one ETF through the OpenBB Platform (obb.etf.holdings). | `symbol` | `limit` (`50`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_etf_info` | Fund facts for one ETF (issuer, inception, assets, expense ratio) through the OpenBB Platform (obb.etf.info). | `symbol` | `limit` (`100`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_etf_search` | Search ETFs by name or keyword through the OpenBB Platform (obb.etf.search). | `query` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_etf_sectors` | Sector weights of one ETF through the OpenBB Platform (obb.etf.sectors). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |

### Financial Analysis

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_compare_peers` | Peer companies of one stock (same sector and size) through the OpenBB Platform (obb.equity.compare.peers). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_equity_fundamental_ratios` | Financial ratios over several periods (valuation, profitability, liquidity, leverage) through the OpenBB Platform (obb.equity.fundamental.ratios). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_equity_metrics` | Key valuation and profitability metrics for one stock (P/E, P/B, EV/EBITDA, ROE, margins, growth, dividend yield) through the OpenBB Platform (obb.equity.fundamental.metrics). | `symbol` | `period`, `limit`, `provider` (`yfinance`) | read-only, idempotent, open-world |

### Financial Statements

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_balance_sheet` | Balance sheets (assets, liabilities, equity, cash, debt) for one company through the OpenBB Platform (obb.equity.fundamental.balance). | `symbol` | `period` (`annual`), `limit` (`5`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_cash_flow` | Cash flow statements (operating, investing, financing, free cash flow) for one company through the OpenBB Platform (obb.equity.fundamental.cash). | `symbol` | `period` (`annual`), `limit` (`5`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_revenue_geographic` | Revenue by geographic region for one company through the OpenBB Platform (obb.equity.fundamental.revenue_per_geography). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_equity_revenue_segment` | Revenue by business segment for one company through the OpenBB Platform (obb.equity.fundamental.revenue_per_segment). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_income_statement` | Income statements (revenue, gross profit, operating income, net income, EPS) for one company through the OpenBB Platform (obb.equity.fundamental.income). | `symbol` | `period` (`annual`), `limit` (`5`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Fixed Income

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_fixedincome_effr` | Effective federal funds rate (EFFR) history with target range and percentiles through the OpenBB Platform (obb.fixedincome.rate.effr); rates are decimals (0.0433 = 4.33%). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`federal_reserve`) | read-only, idempotent, open-world |
| `openbb_fixedincome_estr` | Euro short-term rate (ESTR) history from FRED through the OpenBB Platform (obb.fixedincome.rate.estr); rates are decimals (0.0433 = 4.33%). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`fred`) | read-only, idempotent, open-world |
| `openbb_fixedincome_ice_bofa` | ICE BofA bond index series (yield, yield to worst, total return or option-adjusted spread) from FRED through the OpenBB Platform (obb.fixedincome.bond_indices). | — | `category` (`us`), `index` (`corporate`), `index_type` (`yield`), `start_date`, `end_date`, `limit` (`100`), `provider` (`fred`) | read-only, idempotent, open-world |
| `openbb_fixedincome_iorb` | Interest rate on reserve balances (IORB) from FRED through the OpenBB Platform (obb.fixedincome.rate.iorb); rates are decimals (0.0433 = 4.33%). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`fred`) | read-only, idempotent, open-world |
| `openbb_fixedincome_sofr` | Secured Overnight Financing Rate (SOFR) history with percentiles and volume through the OpenBB Platform (obb.fixedincome.rate.sofr); rates are decimals (0.0433 = 4.33%). | — | `start_date`, `end_date`, `limit` (`100`), `provider` (`federal_reserve`) | read-only, idempotent, open-world |
| `openbb_fixedincome_treasury_auctions` | US Treasury auction results (CUSIP, term, dates, high yield or rate, bid-to-cover) from TreasuryDirect through the OpenBB Platform (obb.fixedincome.government.treasury_auctions). | — | `security_type` (`note`), `start_date`, `end_date`, `limit` (`100`), `provider` (`government_us`) | read-only, idempotent, open-world |
| `openbb_treasury_rates` | Daily US Treasury constant-maturity yields, one row per day with a column per maturity (month_1 to year_30), through the OpenBB Platform (obb.fixedincome.government.treasury_rates); rates are decimals (0.0417 = 4.17%). | — | `start_date`, `end_date`, `limit` (`260`), `provider` (`federal_reserve`) | read-only, idempotent, open-world |
| `openbb_yield_curve` | Treasury yield curve for one date (rate by maturity) through the OpenBB Platform (obb.fixedincome.government.yield_curve); rates are decimals. | — | `date`, `provider` (`federal_reserve`) | read-only, idempotent, open-world |

### Forex

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_currency_snapshots` | Snapshot of current exchange rates against a base currency through the OpenBB Platform (obb.currency.snapshots). | — | `base` (`usd`), `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_forex_historical` | Daily exchange-rate history for one currency pair through the OpenBB Platform (obb.currency.price.historical). | — | `symbol` (`EURUSD`), `start_date`, `end_date`, `provider` (`yfinance`) | read-only, idempotent, open-world |

### Indexes

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_index_available` | Market indices a provider covers (symbol, name and code) through the OpenBB Platform (obb.index.available). | — | `limit` (`500`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_index_constituents` | Members of the S&P 500, Nasdaq-100 or Dow Jones through the OpenBB Platform (obb.index.constituents, symbol sp500, nasdaq or dowjones). | — | `index` (`sp500`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_index_price_historical` | Daily price history for one market index through the OpenBB Platform (obb.index.price.historical). | `symbol` | `start_date`, `end_date`, `limit` (`260`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### Market Data

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_price` | Daily OHLCV price history for one stock through the OpenBB Platform (obb.equity.price.historical). | `symbol` | `start_date`, `end_date`, `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_price_performance` | Price returns of one stock over standard windows (1 day to 10 years, YTD) through the OpenBB Platform (obb.equity.price.performance). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |

### Market Performance

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_discovery_active` | Most actively traded US stocks today through the OpenBB Platform (obb.equity.discovery.active). | — | `limit` (`25`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_discovery_gainers` | Top gaining US stocks today through the OpenBB Platform (obb.equity.discovery.gainers). | — | `limit` (`25`), `provider` (`yfinance`) | read-only, idempotent, open-world |
| `openbb_equity_discovery_losers` | Top losing US stocks today through the OpenBB Platform (obb.equity.discovery.losers). | — | `limit` (`25`), `provider` (`yfinance`) | read-only, idempotent, open-world |

### News

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_company_news` | Recent news articles about one company through the OpenBB Platform (obb.news.company). | `symbol` | `limit` (`10`), `provider` (`fmp`) | read-only, idempotent, open-world |
| `openbb_market_news` | Latest general market and world news through the OpenBB Platform (obb.news.world). | — | `limit` (`10`), `provider` (`fmp`) | read-only, idempotent, open-world |

### Ownership

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_insider_trading` | Insider (officer, director, 10% owner) transactions from Form 4 filings through the OpenBB Platform (obb.equity.ownership.insider_trading). | `symbol` | `limit` (`20`), `provider` (`sec`) | read-only, idempotent, open-world |
| `openbb_institutional_ownership` | Institutional ownership summary for one stock from 13F data through the OpenBB Platform (obb.equity.ownership.institutional). | `symbol` | `limit` (`100`), `provider` (`fmp`) | read-only, idempotent, open-world |

### Search

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_search` | Search listed companies by name or ticker through the OpenBB Platform (obb.equity.search). | `query` | `limit` (`100`), `provider` (`sec`) | read-only, idempotent, open-world |

### SEC & Regulatory

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_regulators_sec_filings` | SEC filings for one company (form, dates, report URL) through the OpenBB Platform (obb.equity.fundamental.filings). | `symbol` | `form_type`, `limit` (`20`), `provider` (`sec`) | read-only, idempotent, open-world |
| `openbb_regulators_sec_search` | Search SEC-registered institutions (13F filers such as fund managers) by name through the OpenBB Platform (obb.regulators.sec.institutions_search); rows carry name and CIK. | `query` | `limit` (`100`), `provider` (`sec`) | read-only, idempotent, open-world |

### Stock Screening

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `openbb_equity_screener` | Stock screener through the OpenBB Platform (obb.equity.screener). | — | `sector`, `market_cap_min`, `market_cap_max`, `limit` (`25`), `provider` (`yfinance`) | read-only, idempotent, open-world |

<!-- /generated:tools -->

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "openbb_income_statement", "arguments": {"symbol": "MSFT", "provider": "yfinance"}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "openbb_income_statement", "arguments": {"symbol": "MSFT", "provider": "yfinance"}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("openbb_income_statement", symbol="MSFT", provider="yfinance")
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
