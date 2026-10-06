# FMP Tool Reference Guide

## Overview

The Financial Modeling Prep tools (prefix `fmp_`) wrap the [FMP stable API](https://site.financialmodelingprep.com/developer/docs): company fundamentals, statements and valuation, market data and screening, analyst data, ownership and SEC filings, ETFs, indexes, commodities, forex, crypto, calendars and technical indicators. Implementation: `sajha/tools/impl/fmp_tools.py`.

## API Key

All `fmp_` configs use `"api_key": "${fmp.api.key}"`. In `config/application.yml` that key is bound to the `FMP_API_KEY` environment variable:

```yaml
fmp:
  api:
    key: ${FMP_API_KEY:}
```

Without a key the tools run in demo mode and return a placeholder response naming the endpoint that would have been called. Get a key at [financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs). See the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

## Adding FMP Tools Without Code

Many FMP tools use `sajha.tools.impl.fmp_tools.FMPGenericTool`, which derives the FMP endpoint from the tool name: it strips the `fmp_` prefix, looks the remainder up in `FMPGenericTool.ENDPOINT_MAP`, and otherwise replaces `_` with `-` (so `fmp_key_executives` calls `/stable/key-executives`). Arguments are passed through as query parameters (`from_date`/`to_date` become `from`/`to`). A new endpoint therefore usually needs only a JSON config in `config/tools/`:

```json
{
  "name": "fmp_new_endpoint",
  "implementation": "sajha.tools.impl.fmp_tools.FMPGenericTool",
  "description": "What this endpoint returns",
  "enabled": true,
  "inputSchema": {
    "type": "object",
    "properties": {"symbol": {"type": "string", "description": "Ticker symbol"}},
    "required": ["symbol"]
  },
  "api_key": "${fmp.api.key}"
}
```

## Tools

The tables below are generated from the tool configs in `config/tools/`; the live catalog in the app (Tools page, or `tools/list`) is authoritative. Parameters marked *(required)* must be supplied. Defaults shown are the schema defaults.

### Analyst

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_price_target` | Get analyst price targets from FMP — target price, analyst name, firm, published date for a stock | `symbol` (required); `limit`, default `5` |
| `fmp_upgrades_downgrades` | Get analyst upgrades and downgrades from FMP — rating changes, firm, previous/new grade for a stock | `symbol` (required); `limit`, default `5` |

### Calendar

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_dividend_calendar` | Get upcoming dividend payments from FMP — ex-date, payment date, record date, dividend amount, yield | `from_date`; `to_date` |
| `fmp_earnings_calendar` | Get upcoming and recent earnings announcements from FMP — dates, EPS estimates vs actuals, revenue estimates | `from_date`; `to_date`; `symbol` |
| `fmp_ipo_calendar` | Get upcoming and recent IPOs from FMP — company name, expected date, price range, shares offered, exchange | `from_date`; `to_date` |
| `fmp_stock_split_calendar` | Get upcoming stock splits from FMP | `from_date`; `to_date` |

### Commodities

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_commodity_historical` | Get historical commodity prices from FMP | `symbol` (required), default `GCUSD` |
| `fmp_commodity_list` | Get available commodities from FMP | — |
| `fmp_commodity_quote` | Get commodity quote from FMP — gold, oil, silver, etc. | `symbol` (required), default `GCUSD` |

### Company Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_company_peers` | Get peer companies from FMP — stocks in the same sector with similar market cap for competitive analysis | `symbol` (required) |
| `fmp_company_profile` | Get comprehensive company profile from FMP — market cap, sector, industry, CEO, description, financial summary, and stock info | `symbol` (required) |
| `fmp_employee_count` | Get company employee count from FMP | `symbol` (required) |
| `fmp_exec_compensation` | Get executive compensation data from FMP — salary, bonus, stock awards, total pay for company officers | `symbol` (required) |
| `fmp_historical_market_cap` | Get historical market cap data from FMP | `symbol` (required); `limit`, default `20` |
| `fmp_key_executives` | Get key executives from FMP — CEO, CFO, CTO with titles and pay | `symbol` (required) |
| `fmp_market_cap` | Get current market capitalization from FMP | `symbol` (required) |
| `fmp_share_float` | Get share float data from FMP — free float, shares outstanding | `symbol` (required) |
| `fmp_stock_peers_bulk` | Get stock peers in bulk from FMP | — |

### Cryptocurrency

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_crypto_historical` | Get historical crypto prices from FMP | `symbol` (required), default `BTCUSD` |
| `fmp_crypto_list` | Get all available cryptocurrencies from FMP | — |
| `fmp_crypto_quote` | Get real-time crypto quote from FMP — BTC, ETH, etc. | `symbol` (required), default `BTCUSD` |

### Derivatives

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_commitment_of_traders` | Get Commitment of Traders report from FMP — COT futures positioning | `symbol` (required), default `ES` |

### ESG

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_esg_rating` | Get ESG rating from FMP — environmental, social, governance scores | `symbol` (required) |

### ETFs

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_etf_country_weights` | Get ETF country weightings from FMP | `symbol` (required) |
| `fmp_etf_holdings` | Get ETF holdings from FMP — constituent stocks, weights, shares held for any ETF (SPY, QQQ, IWM, etc.) | `symbol` (required) |
| `fmp_etf_sector_weights` | Get ETF sector weightings from FMP | `symbol` (required) |
| `fmp_etf_stock_exposure` | Get a stock's exposure across all ETFs from FMP | `symbol` (required) |

### Earnings

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_earnings_transcript` | Get earnings call transcript from FMP — full text of quarterly earnings call | `symbol` (required); `quarter`, default `1`; `year`, default `2025` |

### Economics

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_economic_calendar` | Get economic events calendar from FMP — GDP releases, jobs reports, CPI, Fed meetings, PMI with estimates vs actuals | `from_date`; `to_date` |
| `fmp_market_risk_premium` | Get market risk premium by country from FMP | — |

### Financial Analysis

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_analyst_estimates` | Get analyst consensus estimates from FMP — estimated revenue, EPS, EBITDA, net income, and SGA for upcoming periods | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |
| `fmp_enterprise_value` | Get enterprise value from FMP — EV, market cap, net debt | `symbol` (required) |
| `fmp_financial_growth` | Get financial growth metrics from FMP — revenue, earnings, cash flow growth rates | `symbol` (required); `period`, default `annual`; `limit`, default `20` |
| `fmp_financial_score` | Get Piotroski F-Score from FMP — financial health score 0-9 | `symbol` (required) |
| `fmp_grade` | Get company investment grade from FMP — overall financial grade | `symbol` (required) |
| `fmp_key_metrics` | Get key financial ratios from FMP — PE, PB, PS, EV/EBITDA, ROE, ROA, current ratio, debt/equity, dividend yield, profit margins | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |
| `fmp_levered_dcf` | Get levered DCF valuation from FMP | `symbol` (required) |
| `fmp_owner_earnings` | Get owner earnings from FMP — Buffett's preferred metric | `symbol` (required) |
| `fmp_price_target_by_analyst` | Get individual analyst price targets from FMP | `symbol` (required) |
| `fmp_price_target_summary` | Get price target consensus summary from FMP — avg, high, low | `symbol` (required) |
| `fmp_rating` | Get company financial rating from FMP — overall rating and score | `symbol` (required) |
| `fmp_revenue_by_geography` | Get revenue breakdown by geography from FMP | `symbol` (required) |
| `fmp_revenue_by_product` | Get revenue breakdown by product/segment from FMP | `symbol` (required) |
| `fmp_upgrades_downgrades_consensus` | Get upgrades/downgrades consensus from FMP | `symbol` (required) |

### Financial Statements

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_balance_sheet` | Get balance sheet from FMP — total assets, liabilities, equity, cash, short/long-term debt, retained earnings | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |
| `fmp_cash_flow` | Get cash flow statement from FMP — operating, investing, and financing cash flows, free cash flow, capex, dividends paid | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |
| `fmp_income_statement` | Get income statement from FMP — revenue, cost of revenue, gross profit, operating expenses, EBITDA, net income, EPS | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |

### Fixed Income

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_treasury_rates` | Get US Treasury rates from FMP — yield curve data across 1mo, 3mo, 6mo, 1yr, 2yr, 5yr, 10yr, 30yr maturities | `from_date`; `to_date` |

### Forex

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_forex_historical` | Get historical forex rates from FMP — daily OHLCV for currency pairs | `symbol` (required), default `EURUSD`; `from_date`; `to_date` |
| `fmp_forex_list` | Get list of all available forex pairs from FMP | — |
| `fmp_forex_quote` | Get real-time forex quote from FMP — bid, ask, spread for currency pairs | `symbol` (required), default `EURUSD` |

### Indexes

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_available_indexes` | Get list of all available market indexes from FMP | — |
| `fmp_dowjones_constituents` | Get Dow Jones Industrial Average constituents from FMP | — |
| `fmp_index_historical` | Get historical index data from FMP | `symbol` (required), default `^GSPC` |
| `fmp_index_quote` | Get market index quote from FMP — S&P 500, NASDAQ, Dow Jones | `symbol` (required), default `^GSPC` |
| `fmp_nasdaq_constituents` | Get NASDAQ-100 constituents from FMP | — |
| `fmp_sp500_constituents` | Get current S&P 500 constituents from FMP — all 500 stocks | — |

### Market Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_historical_price` | Get historical daily stock prices from FMP — open, high, low, close, volume, adjusted close for any date range | `symbol` (required); `from_date`; `to_date` |
| `fmp_market_hours` | Get market trading hours from FMP — open/close times for exchanges | — |
| `fmp_stock_quote` | Get real-time stock quote from FMP — current price, change, volume, day high/low, 52-week range, market cap, PE ratio | `symbol` (required) |

### Market Performance

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_market_gainers` | Get today's biggest stock market gainers from FMP — top performing stocks by percentage change | `limit`, default `5` |
| `fmp_market_losers` | Get today's biggest stock market losers from FMP — worst performing stocks by percentage change | `limit`, default `5` |
| `fmp_most_active` | Get most actively traded stocks from FMP — highest volume stocks today | `limit`, default `5` |
| `fmp_sector_performance` | Get sector performance summary from FMP — percentage change by sector (Technology, Healthcare, Finance, etc.) | — |

### News

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_press_releases` | Get company press releases from FMP | `symbol` (required); `limit`, default `20` |
| `fmp_social_sentiment` | Get social media sentiment for a stock from FMP | `symbol` (required) |
| `fmp_stock_news` | Get latest stock market news from FMP — headlines, summaries, sources, sentiment for specific stocks or the broader market | `symbol`; `limit`, default `10` |

### Ownership

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_13f_filing` | Get 13F institutional holdings filing from FMP — hedge fund positions | `cik` (required) |
| `fmp_institutional_holders` | Get institutional holders from FMP — major fund holders, shares held, portfolio weight, change in holdings | `symbol` (required) |
| `fmp_mutual_fund_holders` | Get mutual fund holders from FMP | `symbol` (required) |

### Ownership & Insider

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_insider_trading` | Get insider trading activity from FMP — buys, sells, and option exercises by company officers, directors, and major shareholders | `symbol` (required); `limit`, default `20` |
| `fmp_senate_trading` | Get US Senate stock trading disclosures from FMP — senator name, transaction type, amount, asset, date | `symbol`; `limit`, default `5` |

### SEC & Regulatory

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_crowdfunding_rss` | Get latest crowdfunding filings RSS from FMP | — |
| `fmp_equity_offering` | Get equity offering filings from FMP — Reg D, Reg A+ offerings | — |
| `fmp_sec_filings` | Get SEC filings from FMP — 10-K, 10-Q, 8-K, S-1 and other regulatory filings with links and dates | `symbol` (required); `type`; `limit`, default `5` |

### Stock Directory

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_actively_trading` | Get currently actively trading stocks from FMP | — |
| `fmp_available_countries` | Get all available countries from FMP | — |
| `fmp_available_exchanges` | Get all available stock exchanges from FMP | — |
| `fmp_available_industries` | Get all available industries from FMP | — |
| `fmp_available_sectors` | Get all available market sectors from FMP | — |
| `fmp_cik_list` | Get list of SEC CIK numbers from FMP | `limit`, default `20` |
| `fmp_etf_list` | Get full list of all available ETFs from FMP | `limit`, default `20` |
| `fmp_stock_list` | Get full list of all tradeable stocks from FMP | `limit`, default `20` |
| `fmp_symbol_changes` | Get recent stock symbol changes from FMP — mergers, renames | — |
| `fmp_symbol_search` | Search for stock symbols by name from FMP | `query` |

### Stock Screening

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_stock_screener` | Screen stocks using FMP filters — market cap range, sector, industry, price, beta, dividend yield, volume, country, exchange | `marketCapMoreThan`; `marketCapLowerThan`; `sector`; `industry`; `country`; `exchange`; `dividendMoreThan`; `betaMoreThan`; `betaLowerThan`; `priceMoreThan`; `priceLowerThan`; `volumeMoreThan`; `limit`, default `20` |

### Technical Indicators

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_technical_adx` | Get Average Directional Index from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_bbands` | Get Bollinger Bands from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_dema` | Get Double EMA from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_ema` | Get Exponential Moving Average from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_macd` | Get MACD from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_rsi` | Get RSI technical indicator from FMP for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_sma` | Get SMA technical indicator from FMP for a stock | `symbol` (required); `period`, default `20` |
| `fmp_technical_stddev` | Get Standard Deviation from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_stoch` | Get Stochastic Oscillator from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_tema` | Get Triple EMA from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_williams` | Get Williams %R from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |
| `fmp_technical_wma` | Get Weighted Moving Average from FMP technical indicator for a stock | `symbol` (required); `period`, default `14` |

### Valuation

| Tool | Description | Parameters |
|------|-------------|------------|
| `fmp_dcf_valuation` | Get discounted cash flow valuation from FMP — DCF per share, stock price, and date for intrinsic value analysis | `symbol` (required) |
| `fmp_historical_dcf` | Get historical DCF valuations from FMP — track intrinsic value changes over time for a stock | `symbol` (required); `period`: annual / quarter, default `annual`; `limit`, default `5` |

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "fmp_stock_screener", "arguments": {"marketCapMoreThan": 100000000000, "sector": "Technology", "limit": 10}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "fmp_stock_screener", "arguments": {"marketCapMoreThan": 100000000000, "sector": "Technology", "limit": 10}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("fmp_stock_screener", marketCapMoreThan=100000000000, sector="Technology", limit=10)
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
