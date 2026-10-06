# OpenBB Tool Reference Guide

## Overview

The OpenBB tools (prefix `openbb_`) expose the [OpenBB Platform](https://docs.openbb.co/platform) Python SDK (`obb`) for equities, fundamentals, ETFs, indexes, fixed income, economy, commodities, forex, crypto, derivatives, news and SEC data. Implementation: `sajha/tools/impl/openbb_tools.py`.

## Installation and Keys

The SDK is loaded lazily on first call; if it is missing the tool returns an error asking you to install it:

```bash
pip install openbb                       # core
pip install "openbb[yfinance,fmp,fred]"  # or pick provider extensions
```

There is no SAJHA config key for OpenBB: the `openbb_` tool configs carry no `api_key`. Providers that need credentials (FMP, Intrinio, Polygon, ...) read them from OpenBB's own credential store (`~/.openbb_platform/user_settings.json` or `obb.user.credentials`), not from `config/application.yml`.

## The `provider` Argument

Most tools accept an optional `provider` (e.g. `yfinance`, `fmp`, `fred`, `sec`, `intrinio`). When omitted, generic tools use `yfinance` (or the config's `default_provider`, which no shipped config sets); several named tools fall back to their own provider in code instead (`fmp`, `fred`, `oecd`, `federal_reserve`, `benzinga` or `cboe`, e.g. `cboe` for `openbb_options_chains` and `fmp` for `openbb_equity_screener`). Note that generic tools pass an omitted `provider` as `yfinance` even where the schema default shows another provider, so pass `provider` explicitly when it matters. Which providers work depends on the installed OpenBB extensions.

## Named and Generic Tools

Some tools have a dedicated class (for example `openbb_equity_price` calls `obb.equity.price.historical`). The rest use `OpenBBGenericTool`, which strips the `openbb_` prefix and looks the remainder up in a fixed mapping in `OpenBBGenericTool._resolve_command` (for example `openbb_fixedincome_sofr` calls `obb.fixedincome.rate.sofr`). All other arguments are passed straight through to the SDK call. Adding a generic tool therefore needs a JSON config **and** an entry in that mapping; a config alone returns "No OpenBB command mapping".

## Tools

The tables below are generated from the tool configs in `config/tools/`; the live catalog in the app (Tools page, or `tools/list`) is authoritative. Parameters marked *(required)* must be supplied. Defaults shown are the schema defaults.

### Analyst

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_estimates_consensus` | Get analyst consensus estimates via OpenBB | `symbol` (required); `provider`, default `fmp` |

### Calendar

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_economy_calendar` | Get economic events calendar via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_equity_calendar_dividend` | Get dividend calendar via OpenBB — upcoming dividend payments | `symbol`; `provider`, default `fmp` |
| `openbb_equity_calendar_earnings` | Get earnings calendar via OpenBB — upcoming earnings announcements | `symbol`; `provider`, default `fmp` |

### Commodities

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_commodity_lbma_gold` | Get LBMA gold fixing prices via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_commodity_lbma_silver` | Get LBMA silver fixing prices via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_commodity_price` | Get commodity price history via OpenBB — gold, silver, oil, natural gas, copper, wheat, corn, etc. | `symbol` (required); `start_date`; `provider`, default `yfinance` |
| `openbb_commodity_search` | Search for commodities via OpenBB | `query` (required), default `gold`; `provider`, default `yfinance` |

### Company Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_fundamental_overview` | Get company fundamental overview via OpenBB — all-in-one snapshot | `symbol`; `provider`, default `fmp` |
| `openbb_equity_management` | Get company management team via OpenBB — executives and directors | `symbol` (required); `provider`, default `fmp` |
| `openbb_equity_profile` | Get company profile via OpenBB — name, sector, industry, market cap, employees, description, CEO, headquarters | `symbol` (required); `provider`, default `yfinance` |
| `openbb_equity_share_statistics` | Get share statistics via OpenBB — float, outstanding, insider ownership | `symbol` (required); `provider`, default `fmp` |

### Cryptocurrency

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_crypto_price` | Get historical cryptocurrency prices via OpenBB — daily OHLCV for BTC, ETH, SOL, and other crypto assets | `symbol` (required), default `BTCUSD`; `start_date`; `end_date`; `provider`, default `yfinance` |
| `openbb_crypto_search` | Search for cryptocurrencies via OpenBB | `query` (required); `provider`, default `fmp` |

### Derivatives

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_derivatives_futures_curve` | Get futures curve via OpenBB — forward curve for commodities/futures | `symbol` (required), default `CL`; `provider`, default `yfinance` |
| `openbb_derivatives_futures_historical` | Get historical futures prices via OpenBB | `symbol` (required), default `CL=F`; `provider`, default `yfinance` |
| `openbb_options_chains` | Get options chain data via OpenBB — calls and puts with strike, bid, ask, volume, open interest, Greeks | `symbol` (required); `provider`, default `cboe` |

### Dividends

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_dividends` | Get dividend history via OpenBB — ex-date, payment date, amount, frequency for any stock | `symbol` (required); `provider`, default `yfinance` |

### ETFs

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_etf_countries` | Get ETF country allocation via OpenBB | `symbol` (required); `provider`, default `fmp` |
| `openbb_etf_equity_exposure` | Get a stock's exposure across ETFs via OpenBB | `symbol` (required); `provider`, default `fmp` |
| `openbb_etf_holdings` | Get ETF holdings breakdown via OpenBB — top holdings, portfolio weights, sectors for SPY, QQQ, VTI, and other ETFs | `symbol` (required), default `SPY`; `provider`, default `fmp` |
| `openbb_etf_info` | Get ETF information via OpenBB — inception date, AUM, expense ratio | `symbol` (required); `provider`, default `fmp` |
| `openbb_etf_search` | Search for ETFs via OpenBB — find ETFs by name or keyword | `query` (required); `provider`, default `fmp` |
| `openbb_etf_sectors` | Get ETF sector allocation via OpenBB | `symbol` (required); `provider`, default `fmp` |

### Earnings

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_earnings` | Get earnings history and calendar via OpenBB — EPS estimates vs actuals, revenue surprises | `symbol` (required); `provider`, default `yfinance` |

### Economics

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_economic_indicators` | Get economic indicators via OpenBB — unemployment rate, industrial production, retail sales, housing starts | `country`, default `united_states`; `symbol`; `provider`, default `fred` |
| `openbb_economy_available_indicators` | Get list of available economic indicators via OpenBB | `provider`, default `fred` |
| `openbb_economy_cpi` | Get Consumer Price Index (CPI) data via OpenBB — inflation trends, CPI values over time from FRED or other providers | `country`, default `united_states`; `provider`, default `fred` |
| `openbb_economy_gdp` | Get nominal GDP data via OpenBB — GDP values and growth rates for countries worldwide from OECD or World Bank | `country`, default `united_states`; `provider`, default `oecd` |
| `openbb_economy_interest_rate` | Get short-term interest rates via OpenBB by country | `country`, default `united_states`; `provider`, default `oecd` |
| `openbb_economy_leading` | Get Composite Leading Indicator via OpenBB — economic outlook signal | `country`, default `united_states`; `provider`, default `oecd` |
| `openbb_economy_risk_premium` | Get market risk premium via OpenBB by country | `provider`, default `fmp` |
| `openbb_unemployment` | Get unemployment rate data via OpenBB — historical unemployment rates by country from OECD | `country`, default `united_states`; `provider`, default `oecd` |

### Financial Analysis

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_compare_peers` | Compare peer companies via OpenBB — stocks in same sector | `symbol` (required); `provider`, default `fmp` |
| `openbb_equity_fundamental_ratios` | Get financial ratios via OpenBB — PE, PB, ROE, current ratio, quick ratio | `symbol` (required); `provider`, default `fmp` |
| `openbb_equity_metrics` | Get key fundamental metrics via OpenBB — PE, PB, EV/EBITDA, ROE, ROA, margins, growth rates, dividend info | `symbol` (required); `period`: annual / quarter, default `annual`; `provider`, default `fmp`; `limit`, default `5` |

### Financial Statements

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_balance_sheet` | Get balance sheet via OpenBB — assets, liabilities, equity, cash, debt from Yahoo Finance, FMP, or Intrinio | `symbol` (required); `period`: annual / quarter, default `annual`; `provider`, default `yfinance`; `limit`, default `5` |
| `openbb_cash_flow` | Get cash flow statement via OpenBB — operating, investing, financing cash flows, free cash flow from multiple providers | `symbol` (required); `period`: annual / quarter, default `annual`; `provider`, default `yfinance`; `limit`, default `5` |
| `openbb_equity_revenue_geographic` | Get revenue by geography via OpenBB — revenue breakdown by region | `symbol` (required); `provider`, default `fmp` |
| `openbb_equity_revenue_segment` | Get revenue by business segment via OpenBB | `symbol` (required); `provider`, default `fmp` |
| `openbb_income_statement` | Get income statement via OpenBB — revenue, COGS, gross profit, operating income, net income, EPS from multiple providers | `symbol` (required); `period`: annual / quarter, default `annual`; `provider`, default `yfinance`; `limit`, default `5` |

### Fixed Income

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_fixedincome_effr` | Get Effective Federal Funds Rate via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_fixedincome_estr` | Get Euro Short-Term Rate (ESTR) via OpenBB | `provider`, default `federal_reserve` |
| `openbb_fixedincome_ice_bofa` | Get ICE BofA corporate bond indices via OpenBB | `provider`, default `fred` |
| `openbb_fixedincome_iorb` | Get Interest on Reserve Balances via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_fixedincome_moody` | Get Moody's corporate bond yields via OpenBB — AAA, BAA spreads | `provider`, default `fred` |
| `openbb_fixedincome_sofr` | Get SOFR (Secured Overnight Financing Rate) via OpenBB | `provider`, default `federal_reserve` |
| `openbb_fixedincome_treasury_auctions` | Get US Treasury auction results via OpenBB | `provider`, default `federal_reserve` |
| `openbb_treasury_rates` | Get US Treasury and Federal Funds rate data via OpenBB — daily effective federal funds rate from the Federal Reserve | `start_date`; `end_date`; `provider`, default `federal_reserve` |
| `openbb_yield_curve` | Get US Treasury yield curve via OpenBB — rates across all maturities (1mo to 30yr) for a given date | `date`; `provider`, default `federal_reserve` |

### Forex

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_currency_snapshots` | Get currency market snapshots via OpenBB — live forex rates overview | `provider`, default `fmp` |
| `openbb_forex_historical` | Get historical forex exchange rates via OpenBB — any currency pair (EURUSD, GBPJPY, etc.) with daily OHLCV data | `symbol` (required), default `EURUSD`; `start_date`; `end_date`; `provider`, default `yfinance` |

### Indexes

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_index_available` | Get all available indexes via OpenBB | `provider`, default `fmp` |
| `openbb_index_constituents` | Get index constituents via OpenBB — list of stocks in S&P 500, NASDAQ-100, Dow Jones, FTSE, etc. | `index` (required), default `sp500`; `provider`, default `yfinance` |
| `openbb_index_price_historical` | Get historical index prices via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_index_search` | Search for market indexes via OpenBB | `query` (required), default `S&P`; `provider`, default `fmp` |

### Market Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_price` | Get historical equity prices via OpenBB — daily OHLCV data from Yahoo Finance, FMP, or Intrinio. Supports global stocks. | `symbol` (required); `start_date`; `end_date`; `provider`: yfinance / fmp / intrinio, default `yfinance` |
| `openbb_equity_price_performance` | Get stock price performance via OpenBB — 1d, 1w, 1m, 3m, 6m, 1y, YTD returns | `symbol` (required); `provider`, default `fmp` |

### Market Performance

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_discovery_active` | Get most actively traded stocks via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_equity_discovery_gainers` | Get top stock gainers via OpenBB | `symbol`; `provider`, default `fmp` |
| `openbb_equity_discovery_losers` | Get top stock losers via OpenBB | `symbol`; `provider`, default `fmp` |

### News

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_company_news` | Get company-specific news via OpenBB — headlines, summaries for a specific stock from Benzinga, FMP, or others | `symbol` (required); `limit`, default `5`; `provider`, default `benzinga` |
| `openbb_market_news` | Get latest market and world news via OpenBB — aggregated headlines from Benzinga, FMP, and other providers | `limit`, default `10`; `provider`: benzinga / fmp / biztoc, default `benzinga` |
| `openbb_news_search` | Search financial news via OpenBB — filtered by keywords | `query` (required); `provider`, default `benzinga`; `limit`, default `20` |

### Ownership

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_insider_trading` | Get insider trading activity via OpenBB — officer/director buys and sells from SEC Form 4 filings | `symbol` (required); `provider`, default `fmp`; `limit`, default `5` |
| `openbb_institutional_ownership` | Get institutional ownership via OpenBB — major fund holders, shares held, changes from SEC 13F filings | `symbol` (required); `provider`, default `fmp` |

### SEC & Regulatory

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_regulators_sec_filings` | Get SEC filings via OpenBB — 10-K, 10-Q, 8-K regulatory filings | `symbol` (required); `provider`, default `sec` |
| `openbb_regulators_sec_search` | Search SEC EDGAR via OpenBB — find companies and filings | `query` (required); `provider`, default `sec` |

### Search

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_search` | Search for stocks via OpenBB — find by name or partial symbol | `query` (required); `provider`, default `fmp` |

### Stock Screening

| Tool | Description | Parameters |
|------|-------------|------------|
| `openbb_equity_screener` | Screen stocks via OpenBB — filter by market cap, sector, industry, region from Yahoo Finance or FMP | `provider`, default `fmp`; `market_cap_min`; `market_cap_max`; `sector`; `country`; `limit`, default `5` |

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
