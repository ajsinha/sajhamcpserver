# Yahoo Finance Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & API Keys](#authentication--api-keys)
5. [Tool Details](#tool-details)
6. [yfinance Library Tools (yf_)](#yfinance-library-tools-yf_)
7. [Calling the Tools](#calling-the-tools)
8. [Technical Implementation](#technical-implementation)
9. [Schema Specifications](#schema-specifications)
10. [Usage Examples](#usage-examples)
11. [Limitations & Best Practices](#limitations--best-practices)
12. [Error Handling](#error-handling)
13. [Appendix](#appendix)

---

## Overview

SAJHA ships two families of Yahoo Finance tools. Neither needs an API key.

| Family | Prefix | Implementation | How it gets data |
|--------|--------|----------------|------------------|
| Direct API tools | `yahoo_` | `sajha/tools/impl/yahoo_finance_tool.py` | Calls Yahoo Finance's public chart and search endpoints with the Python standard library; `yahoo_get_quote` goes through `yfinance` |
| yfinance tools | `yf_` | `sajha/tools/impl/yfinance_tools.py` | Uses the [`yfinance`](https://pypi.org/project/yfinance/) library |

The `yahoo_` tools cover quotes, price history with corporate events, and symbol search; most of this guide (architecture, implementation, examples) describes them. The `yf_` tools add fundamentals, statements, holders, analyst data, options, screeners, ETFs, crypto, forex and indexes; they are listed in [yfinance Library Tools (yf_)](#yfinance-library-tools-yf_). The live catalog in the app (Tools page, or `tools/list`) is authoritative.

### Key Features (`yahoo_` tools)

- **No API Key Required**: Free access to Yahoo Finance's public API
- **Real-Time Data**: Current stock prices and market statistics
- **Historical Data**: OHLCV data with configurable time periods and intervals
- **Symbol Search**: Find ticker symbols by company name or keyword
- **Multi-Asset Support**: Stocks, ETFs, indices, mutual funds, cryptocurrencies
- **Corporate Actions**: Dividend and stock split events tracking

### Tool Suite Components (`yahoo_` tools)

1. **yahoo_get_quote** - Real-time stock quotes with market statistics
2. **yahoo_get_history** - Historical OHLCV data with corporate events
3. **yahoo_search_symbols** - Symbol and company search

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Tool Framework                          │
│                    (BaseMCPTool Interface)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ inherits
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                   YahooFinanceBaseTool                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  - API endpoint configuration                            │  │
│  │  - HTTP request handling                                 │  │
│  │  - Error management                                      │  │
│  │  - Header configuration                                  │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────┬──────────────────┬────────────────┬────────────────┘
            │                  │                │
            │ inherits         │ inherits       │ inherits
            ↓                  ↓                ↓
  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐
  │YahooGetQuoteTool │  │YahooGetHistory  │  │YahooSearch       │
  │                  │  │Tool             │  │SymbolsTool       │
  │ - Real-time      │  │                 │  │                  │
  │   quotes         │  │ - Historical    │  │ - Symbol search  │
  │ - Market stats   │  │   OHLCV data    │  │ - Company lookup │
  │ - PE ratio       │  │ - Dividends     │  │ - Exchange filter│
  │ - Market cap     │  │ - Stock splits  │  │ - Type filter    │
  │ - 52-week range  │  │ - Multi-periods │  │ - Sector/industry│
  └──────────────────┘  └─────────────────┘  └──────────────────┘
            │                  │                │
            └──────────────────┴────────────────┘
                               │
                               ↓
              ┌────────────────────────────────┐
              │    Yahoo Finance API           │
              │  query2.finance.yahoo.com      │
              │  (quote: through yfinance)     │
              │  - /v8/finance/chart           │
              │  - /v1/finance/search          │
              └────────────────────────────────┘
```

### Component Hierarchy

```
BaseMCPTool (Abstract Base Class)
    │
    └── YahooFinanceBaseTool
            ├── _make_request()      # HTTP communication
            ├── base_url             # API endpoint
            └── headers              # Request headers
            │
            ├── YahooGetQuoteTool
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            ├── YahooGetHistoryTool
            │       ├── period_map           # Period conversions
            │       ├── interval_map         # Interval mappings
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            └── YahooSearchSymbolsTool
                    ├── get_input_schema()
                    ├── get_output_schema()
                    └── execute()
```

### Data Flow Diagram

```
┌──────────┐
│  Client  │
└─────┬────┘
      │ 1. Request with parameters
      ↓
┌─────────────────────┐
│  Tool Instance      │
│  (yahoo_get_quote/  │
│   yahoo_get_history/│
│   yahoo_search_     │
│   symbols)          │
└──────────┬──────────┘
           │ 2. Validate input schema
           ↓
┌─────────────────────────┐
│ YahooFinanceBaseTool    │
│  _make_request()        │
└──────────┬──────────────┘
           │ 3. Build API URL & params
           ↓
┌──────────────────────────┐
│  HTTP Request            │
│  (urllib.request)        │
│  User-Agent: Mozilla/5.0 │
│  Timeout: 10s            │
└──────────┬───────────────┘
           │ 4. API call
           ↓
┌─────────────────────────┐
│  Yahoo Finance API      │
│  - Quote data           │
│  - Historical charts    │
│  - Symbol search        │
└──────────┬──────────────┘
           │ 5. JSON response
           ↓
┌─────────────────────┐
│  Response Parser    │
│  - Extract data     │
│  - Format output    │
│  - Add metadata     │
│  - Handle nulls     │
└──────────┬──────────┘
           │ 6. Structured result
           ↓
┌──────────────────┐
│  Return to Client│
└──────────────────┘
```

### Request Flow for Each Tool

#### Quote Request Flow
```
Client → yahoo_get_quote(symbol="AAPL")
    ↓
yfinance.Ticker("AAPL").info   (yfinance fetches Yahoo's cookie and crumb;
    ↓                           a plain quoteSummary request gets HTTP 401)
Parse: regularMarketPrice, marketCap, trailingPE, etc.
    ↓
Unknown symbol (no price) → error
    ↓
Return: Complete quote data with statistics
```

#### History Request Flow
```
Client → yahoo_get_history(symbol="AAPL", period="1y", interval="1d")
    ↓
Convert period to timestamps (period1, period2)
    ↓
Build URL: query2.finance.yahoo.com/v8/finance/chart/AAPL
    ↓
Parse: OHLCV data, dividends, splits
    ↓
Return: Historical data array with events
```

#### Search Request Flow
```
Client → yahoo_search_symbols(query="Apple", limit=10)
    ↓
Build URL: query2.finance.yahoo.com/v1/finance/search
    ↓
Parameters: q="Apple", quotesCount=10
    ↓
Parse: Symbol list with metadata
    ↓
Return: Search results with company info
```

---

## System Requirements

### Python Dependencies

```python
# yahoo_get_history and yahoo_search_symbols: standard library only
# yahoo_get_quote and the yf_ tools: the yfinance package (requirements.txt)
import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
```

### Minimum Requirements

- **Python Version**: 3.7+
- **Network**: Internet connectivity required
- **Dependencies**: `yfinance` for `yahoo_get_quote` and the `yf_` tools; the other `yahoo_` tools use the standard library
- **Platform**: Cross-platform (Windows, macOS, Linux)
- **Market Hours**: Real-time data available during market hours; delayed otherwise

### Optional Dependencies

- Custom logging framework (if extending BaseMCPTool)
- Testing framework: pytest (for running test suite)
- Data analysis: pandas, numpy (for processing historical data)

---

## Authentication & API Keys

### No Authentication Required ✓

The Yahoo Finance MCP Tool uses **public Yahoo Finance API**, which:

- ✅ **No API key needed**
- ✅ **No registration required**
- ✅ **No OAuth or authentication**
- ✅ **Free for all users**
- ✅ **No rate limit authentication**

### User-Agent Requirement

Yahoo Finance requires a User-Agent header to identify the application:

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
```

**Best Practice**: The tool uses a standard browser User-Agent to ensure compatibility.

### Important Notes

⚠️ **Terms of Service**: Yahoo Finance API is unofficial and provided as-is. Users should:
- Respect rate limits
- Use data responsibly
- Not redistribute data commercially without proper licensing
- Be aware that API structure may change without notice

### Outbound fetch guard and proxy

`yahoo_get_history`, `yahoo_search_symbols` and `yf_trending_tickers` fetch through SAJHA's outbound
fetch guard, so they honour `tools.outbound.proxy`. `yahoo_get_quote` and the other `yf_` tools call
the yfinance package, which opens its own connections to Yahoo's hosts: they bypass the guard and the
proxy (a known limit, [Security Model](../../security/Security%20Model.md#8-known-limitations)). Where
SAJHA must reach the internet through a proxy, these tools work only if the network lets the server
reach Yahoo directly.

`yf_sustainability` was removed in 8.14.0: Yahoo no longer serves ESG scores (every symbol answers
"No fundamentals data found"), so the tool could only return nothing.

---

## Tool Details

### 1. YahooGetQuoteTool (yahoo_get_quote)

**Purpose**: Retrieve real-time stock quote data including current price, volume, market cap, and key financial statistics.

**When to Use**:
- Portfolio monitoring
- Real-time price tracking
- Market research
- Investment decisions
- Price alerts

**Input Parameters**:

| Parameter | Type   | Required | Default | Description                              |
|-----------|--------|----------|---------|------------------------------------------|
| symbol    | string | Yes      | -       | Ticker symbol (e.g., AAPL, ^GSPC)        |

**Symbol Format**:
- **Stocks**: AAPL, GOOGL, MSFT, TSLA
- **Indices**: ^GSPC (S&P 500), ^DJI (Dow Jones), ^IXIC (NASDAQ)
- **ETFs**: SPY, QQQ, VOO
- **International**: Add exchange suffix (e.g., NESN.SW for Nestlé)

**Output Structure**:

```json
{
  "symbol": "string",
  "name": "string",
  "price": "number or null",
  "currency": "string",
  "change": "number or null",
  "change_percent": "number or null",
  "volume": "integer or null",
  "avg_volume": "integer or null",
  "market_cap": "number or null",
  "pe_ratio": "number or null",
  "dividend_yield": "number or null",
  "fifty_two_week_high": "number or null",
  "fifty_two_week_low": "number or null",
  "day_high": "number or null",
  "day_low": "number or null",
  "open": "number or null",
  "previous_close": "number or null",
  "last_updated": "string (ISO)"
}
```


---

### 2. YahooGetHistoryTool (yahoo_get_history)

**Purpose**: Retrieve historical OHLCV (Open, High, Low, Close, Volume) data with corporate events for technical analysis and backtesting.

**When to Use**:
- Technical analysis
- Backtesting trading strategies
- Chart generation
- Trend analysis
- Performance tracking
- Dividend analysis

**Input Parameters**:

| Parameter       | Type    | Required | Default | Description                           |
|-----------------|---------|----------|---------|---------------------------------------|
| symbol          | string  | Yes      | -       | Ticker symbol                         |
| period          | string  | No       | "1mo"   | Time period (1d, 5d, 1mo, 3mo, etc.)  |
| interval        | string  | No       | "1d"    | Data interval (1m, 5m, 1h, 1d, etc.)  |
| include_events  | boolean | No       | true    | Include dividends and splits          |

**Period Options**:
- `1d` - 1 day
- `5d` - 5 days
- `1mo` - 1 month
- `3mo` - 3 months
- `6mo` - 6 months
- `1y` - 1 year
- `2y` - 2 years
- `5y` - 5 years
- `10y` - 10 years
- `ytd` - Year to date
- `max` - Maximum available

**Interval Options**:

| Interval | Description      | Best For                |
|----------|------------------|-------------------------|
| 1m, 2m   | 1-2 minutes      | Day trading             |
| 5m, 15m  | 5-15 minutes     | Intraday analysis       |
| 30m, 1h  | 30 min - 1 hour  | Short-term trading      |
| 1d       | Daily            | Long-term analysis      |
| 1wk      | Weekly           | Medium-term trends      |
| 1mo      | Monthly          | Long-term trends        |

**Output Structure**:

```json
{
  "symbol": "string",
  "period": "string",
  "interval": "string",
  "data_points": "integer",
  "history": [
    {
      "date": "string (ISO)",
      "open": "number or null",
      "high": "number or null",
      "low": "number or null",
      "close": "number or null",
      "volume": "integer or null",
      "adjusted_close": "number or null"
    }
  ],
  "dividends": [
    {
      "date": "string (ISO)",
      "amount": "number"
    }
  ],
  "splits": [
    {
      "date": "string (ISO)",
      "ratio": "string"
    }
  ],
  "currency": "string",
  "last_updated": "string (ISO)"
}
```


**Important Constraints**:
- Intraday data (1m-1h) available for last 30 days only
- Maximum data points vary by interval
- `close` is adjusted for splits only; `adjusted_close` is Yahoo's `adjclose` series (requested with `includeAdjustedClose=true`), which also adjusts for dividends; it is `null` where Yahoo sends none (intraday intervals)

---

### 3. YahooSearchSymbolsTool (yahoo_search_symbols)

**Purpose**: Search for stock symbols, ETFs, and other securities by company name, ticker, or keyword.

**When to Use**:
- Symbol discovery
- Company research
- Building watchlists
- Sector exploration
- Competitor analysis

**Input Parameters**:

| Parameter | Type    | Required | Default | Description                           |
|-----------|---------|----------|---------|---------------------------------------|
| query     | string  | Yes      | -       | Search term (1-100 characters)        |
| limit     | integer | No       | 10      | Max results (1-50)                    |
| exchange  | string  | No       | "all"   | Exchange filter                       |

**Exchange Options**:
- `NYSE` - New York Stock Exchange
- `NASDAQ` - NASDAQ Exchange
- `AMEX` - American Stock Exchange
- `LSE` - London Stock Exchange
- `TSX` - Toronto Stock Exchange
- `all` - All exchanges

> **Note**: Yahoo reports its own exchange codes, so the tool maps each name to them: `NYSE` = `NYQ`; `NASDAQ` = `NMS`, `NGM`, `NCM`, `NAS`; `AMEX` = `ASE`; `LSE` = `LSE`, `IOB`; `TSX` = `TOR`. With a filter the tool asks Yahoo for more matches (four times `limit`, at least 25, at most 100) and keeps up to `limit` of those on the exchange, so a broad query can still return fewer than `limit`. Each result carries the code (`exchange`) and Yahoo's display name (`exchange_name`).

**Output Structure**:

```json
{
  "query": "string",
  "result_count": "integer",
  "results": [
    {
      "symbol": "string",
      "name": "string",
      "exchange": "string",
      "type": "string",
      "sector": "string or null",
      "industry": "string or null",
      "market_cap": "number or null",
      "description": "string or null"
    }
  ],
  "last_updated": "string (ISO)"
}
```

**Security Types**:
- `EQUITY` - Common stocks
- `ETF` - Exchange-traded funds
- `INDEX` - Market indices
- `MUTUALFUND` - Mutual funds
- `CRYPTOCURRENCY` - Digital currencies
- `FUTURE` - Futures contracts
- `CURRENCY` - Currency pairs


---

## yfinance Library Tools (yf_)

These tools use the `yfinance` package (installed with SAJHA's requirements). Each one wraps a `yfinance.Ticker` property or a yfinance helper. The tables are generated from the tool configs (`python -m sajha.tools guides`); defaults shown are schema defaults, which SAJHA fills in before the call.

<!-- generated:tools folder=yahoo group=category include=yf_* -->
<!-- Generated by `python -m sajha.tools guides` from the tool configs in `config/tools/yahoo/`; edit the configs, not this table. -->

### Analyst

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_analyst_price_targets` | Analyst 12-month price targets for one stock from Yahoo Finance (yfinance analyst_price_targets). | `symbol` | — | read-only, idempotent, open-world |
| `yf_recommendations` | Analyst recommendation counts for one stock from Yahoo Finance (yfinance recommendations). | `symbol` | — | read-only, idempotent, open-world |
| `yf_upgrades_downgrades` | Analyst rating changes for one stock from Yahoo Finance (yfinance upgrades_downgrades), newest first. | `symbol` | `limit` (`30`) | read-only, idempotent, open-world |

### Calendar

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_calendar` | Upcoming earnings and dividend events for one ticker from Yahoo Finance (yfinance calendar). | `symbol` | — | read-only, idempotent, open-world |
| `yf_earnings_dates` | Past and upcoming earnings announcement dates for one company from Yahoo Finance (yfinance earnings_dates). | `symbol` | `limit` (`12`) | read-only, idempotent, open-world |

### Company Data

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_shares_outstanding` | Shares outstanding over time (about the last 18 months) for one ticker from Yahoo Finance (yfinance get_shares_full). | `symbol` | `limit` (`100`) | read-only, idempotent, open-world |
| `yf_stock_info` | Full Yahoo Finance profile and statistics for one ticker (yfinance Ticker.info). | `symbol` | — | read-only, idempotent, open-world |

### Corporate Actions

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_actions` | Corporate actions (dividends and stock splits together) for one ticker from Yahoo Finance (yfinance actions). | `symbol` | `limit` (`100`) | read-only, idempotent, open-world |
| `yf_splits` | Stock split history for one ticker from Yahoo Finance (yfinance splits). | `symbol` | `limit` (`100`) | read-only, idempotent, open-world |

### Cryptocurrency

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_crypto_info` | Profile and market statistics for one cryptocurrency pair from Yahoo Finance (yfinance Ticker.info). | — | `symbol` (`BTC-USD`) | read-only, idempotent, open-world |

### Derivatives

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_options_chain` | Option chain (calls and puts) for one underlying and expiry from Yahoo Finance (yfinance option_chain). | `symbol` | `expiry`, `limit` (`50`) | read-only, idempotent, open-world |
| `yf_options_expiries` | Listed option expiration dates for one underlying from Yahoo Finance (yfinance options). | `symbol` | — | read-only, idempotent, open-world |

### Dividends

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_dividends` | Dividend payment history for one ticker from Yahoo Finance (yfinance dividends). | `symbol` | `limit` (`100`) | read-only, idempotent, open-world |

### Earnings

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_earnings_history` | Last four quarters of reported versus estimated EPS for one company from Yahoo Finance (yfinance earnings_history). | `symbol` | — | read-only, idempotent, open-world |

### ETFs

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_etf_info` | Key fund facts for one ETF or mutual fund from Yahoo Finance (a subset of yfinance Ticker.info). | `symbol` | — | read-only, idempotent, open-world |

### Financial Analysis

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_compare_stocks` | Side-by-side valuation snapshot for up to 10 tickers from Yahoo Finance (yfinance Ticker.info per symbol). | `symbols` | — | read-only, idempotent, open-world |

### Financial Statements

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_balance_sheet` | Balance sheets (total assets, liabilities, equity, cash, debt and more) for one company from Yahoo Finance (yfinance balance_sheet). | `symbol` | `quarterly` (`false`) | read-only, idempotent, open-world |
| `yf_cash_flow` | Cash flow statements (operating, investing and financing cash flow, free cash flow, capex and more) for one company from Yahoo Finance (yfinance cashflow). | `symbol` | `quarterly` (`false`) | read-only, idempotent, open-world |
| `yf_income_statement` | Income statements (revenue, gross profit, operating income, net income, EBITDA, EPS and more) for one company from Yahoo Finance (yfinance income_stmt). | `symbol` | `quarterly` (`false`) | read-only, idempotent, open-world |

### Forex

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_forex_history` | Daily exchange-rate history for one currency pair from Yahoo Finance. | — | `pair` (`EURUSD=X`), `period` (`3mo`), `limit` (`100`) | read-only, idempotent, open-world |

### Indexes

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_index_history` | Daily history for one market index from Yahoo Finance. | — | `index` (`^GSPC`), `period` (`1y`), `limit` (`260`) | read-only, idempotent, open-world |

### Market Data

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_fast_info` | Quick price snapshot for one ticker from Yahoo Finance (yfinance fast_info), lighter than yf_stock_info. | `symbol` | — | read-only, idempotent, open-world |
| `yf_market_summary` | Latest levels of major US market gauges from Yahoo Finance: S&P 500 (^GSPC), Dow Jones (^DJI), NASDAQ (^IXIC), Russell 2000 (^RUT), VIX (^VIX) and the 10-year Treasury yield index (^TNX). | — | — | read-only, idempotent, open-world |
| `yf_multi_ticker_history` | Daily price history for several tickers in one call from Yahoo Finance (yfinance download). | `symbols` | `period` (`1mo`), `limit` (`30`) | read-only, idempotent, open-world |
| `yf_stock_history` | Historical OHLCV bars for one ticker from Yahoo Finance (yfinance Ticker.history, prices adjusted for splits and dividends). | `symbol` | `period` (`1y`), `interval` (`1d`), `limit` (`500`) | read-only, idempotent, open-world |

### Market Performance

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_sector_performance` | Latest prices of the 11 SPDR sector ETFs from Yahoo Finance (XLK, XLF, XLV, XLY, XLP, XLE, XLI, XLB, XLU, XLRE, XLC). | — | — | read-only, idempotent, open-world |
| `yf_trending_tickers` | Tickers trending on Yahoo Finance for a region (Yahoo's trending endpoint, which needs no cookie). | — | `region` (`US`), `limit` (`20`) | read-only, idempotent, open-world |

### News

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_news` | Recent news items about one ticker from Yahoo Finance (yfinance Ticker.news, falling back to Yahoo search news when that is empty). | `symbol` | `limit` (`10`) | read-only, idempotent, open-world |

### Ownership

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_insider_purchases` | Six-month summary of insider buying and selling for one stock from Yahoo Finance (yfinance insider_purchases). | `symbol` | — | read-only, idempotent, open-world |
| `yf_insider_transactions` | Recent insider (officer and director) transactions in one stock from Yahoo Finance (yfinance insider_transactions). | `symbol` | — | read-only, idempotent, open-world |
| `yf_institutional_holders` | Largest institutional holders of one stock from Yahoo Finance (yfinance institutional_holders), usually the top 10. | `symbol` | — | read-only, idempotent, open-world |
| `yf_major_holders` | Ownership breakdown for one stock from Yahoo Finance (yfinance major_holders). | `symbol` | — | read-only, idempotent, open-world |
| `yf_mutual_fund_holders` | Largest mutual fund holders of one stock from Yahoo Finance (yfinance mutualfund_holders), usually the top 10. | `symbol` | — | read-only, idempotent, open-world |

### Stock Screening

| Tool | Description | Required | Optional (schema default) | Annotations |
|---|---|---|---|---|
| `yf_screener` | Yahoo Finance predefined stock screens (day gainers, losers, most active, most shorted and others), through yfinance's screen function. | — | `screen_type` (`day_gainers`), `limit` (`25`) | read-only, idempotent, open-world |

<!-- /generated:tools -->

Notes:

- **Row limits.** Tools that return a time series (`yf_stock_history`, `yf_index_history`, `yf_forex_history`, `yf_multi_ticker_history`, `yf_dividends`, `yf_splits`, `yf_actions`, `yf_shares_outstanding`) take a `limit` and return the **most recent** `limit` rows, oldest first, with `data_points` (all rows in the period) and `truncated`. Lists Yahoo sends newest first (`yf_upgrades_downgrades`, `yf_earnings_dates`) keep their first `limit` rows. `yf_options_chain` caps each side at `limit` and reports `total_calls`, `total_puts` and `truncated`.
- `yf_compare_stocks` takes `symbols` as a comma-separated string (`"AAPL,MSFT,GOOGL"`, up to 10); `yf_multi_ticker_history` takes up to 10 tickers separated by spaces or commas (more is an error).
- `yf_options_chain` takes `expiry` as `YYYY-MM-DD`; list valid dates with `yf_options_expiries` first. When omitted, the nearest expiry is used.
- `yf_forex_history` takes `EURUSD`, `EUR/USD` or `EURUSD=X` (`=X` is appended); `yf_index_history` takes an index symbol such as `^GSPC`.
- `yf_crypto_info` appends `-USD` only to a symbol without a dash (`ETH` becomes `ETH-USD`; `ETH-EUR` is kept).
- `yf_screener` uses `yfinance.screen` with Yahoo's predefined screens (yfinance 0.2.54 or later). `yf_trending_tickers` reads Yahoo's trending endpoint (`query1.finance.yahoo.com/v1/finance/trending/<region>`), which yfinance does not wrap, and returns symbols only.
- `yf_news` falls back to Yahoo's search news when `Ticker.news` comes back empty, which it has done for long periods.

---

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "yahoo_get_history", "arguments": {"symbol": "AAPL", "period": "1y", "interval": "1d"}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "yahoo_get_history", "arguments": {"symbol": "AAPL", "period": "1y", "interval": "1d"}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("yahoo_get_history", symbol="AAPL", period="1y", interval="1d")
```

The Python examples later in this guide call the tool classes directly (for example `YahooGetQuoteTool().execute(Ellipsis)`), which is handy in tests and notebooks; through the server, use one of the forms above.

---

## Technical Implementation

### How It Works

The Yahoo Finance MCP Tool suite uses **HTTP REST API calls** to Yahoo Finance's unofficial public API, not web scraping or database queries.

#### Method: REST API Calls

```
┌─────────────────────────────────────────────────────────────┐
│                    Implementation Method                    │
├─────────────────────────────────────────────────────────────┤
│  ✓ API Calls      (Yahoo Finance REST API)                 │
│  ✗ Web Scraping   (Not used)                               │
│  ✗ Web Crawling   (Not used)                               │
│  ✗ Database Query (Not used)                               │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoints

**Base URL**: `https://query2.finance.yahoo.com`

**Endpoint Details**:

1. **Quote**: not called directly. Yahoo's `/v10/finance/quoteSummary` and `/v7/finance/quote`
   answer HTTP 401 without a browser cookie and crumb, so `yahoo_get_quote` reads
   `yfinance.Ticker(symbol).info`, which obtains them.

2. **Chart Data**: `/v8/finance/chart/{symbol}`
   - Parameters: period1, period2, interval, events, includeAdjustedClose
   - Returns: Historical OHLCV data

3. **Search**: `/v1/finance/search`
   - Parameters: q (query), quotesCount, newsCount
   - Returns: Symbol search results

### Request Flow

```python
# yahoo_get_history (yahoo_search_symbols is the same with /v1/finance/search)
url = f"{self.base_url}/v8/finance/chart/{symbol}"
params = {'period1': start, 'period2': end, 'interval': '1d',
          'events': 'div,split', 'includeAdjustedClose': 'true'}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers=headers)
response = urllib.request.urlopen(request, timeout=10)
data = json.loads(response.read().decode('utf-8'))
```

### Yahoo Finance API Operations

#### 1. Get Quote (yahoo_get_quote)

```python
import yfinance as yf
info = yf.Ticker(symbol).info      # yfinance handles Yahoo's cookie and crumb
price = info.get('regularMarketPrice') or info.get('currentPrice')   # none: unknown symbol, an error
# mapped to: name, price, currency, change, change_percent, volume, avg_volume, market_cap,
# pe_ratio (trailingPE), dividend_yield (percent, as Yahoo gives it), 52-week high and low,
# day high and low, open, previous_close, exchange, market_time (UTC)
```

#### 2. Get History (yahoo_get_history)

```python
url = f"{base_url}/v8/finance/chart/{symbol}"
params = {
    'period1': start_timestamp,
    'period2': end_timestamp,
    'interval': '1d',
    'events': 'div,split'
}

# Response structure:
{
    "chart": {
        "result": [{
            "timestamp": [1698739200, 1698825600, ...],
            "indicators": {
                "quote": [{
                    "open": [150.0, 151.2, ...],
                    "high": [152.5, 153.0, ...],
                    "low": [149.8, 150.5, ...],
                    "close": [151.0, 152.0, ...],
                    "volume": [50000000, 55000000, ...]
                }]
            },
            "events": {
                "dividends": {...},
                "splits": {...}
            }
        }]
    }
}
```

#### 3. Search Symbols (yahoo_search_symbols)

```python
url = f"{base_url}/v1/finance/search"
params = {
    'q': query,
    'quotesCount': limit,
    'newsCount': 0,
    'enableFuzzyQuery': 'false'
}

# Response structure:
{
    "quotes": [
        {
            "symbol": "AAPL",
            "shortname": "Apple Inc.",
            "longname": "Apple Inc.",
            "exchange": "NASDAQ",
            "quoteType": "EQUITY",
            "sector": "Technology",
            "industry": "Consumer Electronics"
        }
    ]
}
```

### Error Handling

```python
try:
    response = urllib.request.urlopen(request, timeout=10)
    data = json.loads(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    if e.code == 404:
        raise ValueError("Symbol or resource not found")
    else:
        raise ValueError(f"Failed to fetch data: HTTP {e.code}")
except Exception as e:
    raise ValueError(f"Failed to fetch data: {str(e)}")
```

### Timeout Configuration

- **Request Timeout**: 10 seconds
- **Prevents**: Hanging connections
- **Configurable**: Can be adjusted in `_make_request()` method

### Data Extraction Pattern

Yahoo Finance returns nested dictionary structures with `raw` and `fmt` values:

```python
def get_value(data_dict, key):
    """Safely extract value from nested dict"""
    val = data_dict.get(key, {})
    if isinstance(val, dict):
        return val.get('raw')  # Extract raw numeric value
    return val
```

---

## Schema Specifications

### Input Schema Pattern

The `symbol` parameter of `yahoo_get_quote` and `yahoo_get_history` advertises this schema:

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Stock ticker symbol",
      "pattern": "^[A-Za-z0-9^.=-]{1,20}$"
    }
  },
  "required": ["symbol"]
}
```

The server validates every call against this schema (a mismatch is refused before the tool runs; see "Argument validation" in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md)). The pattern admits letters (either case; the tool upper-cases the symbol), digits, `^`, `.`, `=` and `-`, up to 20 characters, so every form in the [Symbol Format Examples](#a-symbol-format-examples) is accepted: `BRK-A`, `BTC-USD`, `7203.T`, `EURUSD=X`, `ES=F`, `^GSPC`.

### Output Schema Pattern

All tools return structured data with these common patterns:

```json
{
  "type": "object",
  "properties": {
    "symbol": {"type": "string"},
    "last_updated": {"type": "string"}
  },
  "required": ["symbol"]
}
```

### Validation Rules

1. **Symbol Format**: 1-10 uppercase characters, may include ^ and .
2. **Period Validation**: Must match enum values (1d, 5d, 1mo, etc.)
3. **Interval Validation**: Must match enum values (1m, 5m, 1d, etc.)
4. **Limit Ranges**: 1-50 for search results
5. **Query Length**: 1-100 characters for search queries
6. **Nullable Fields**: Most financial metrics can be null if unavailable

---

## Usage Examples

### Example 1: Get Real-Time Quote

```python
# Initialize the quote tool
quote_tool = YahooGetQuoteTool()

# Get Apple stock quote
result = quote_tool.execute({
    'symbol': 'AAPL'
})

# Output
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "price": 178.72,
  "currency": "USD",
  "change": 2.45,
  "change_percent": 1.39,
  "volume": 52341890,
  "avg_volume": 55234567,
  "market_cap": 2789456123000,
  "pe_ratio": 28.94,
  "dividend_yield": 0.0054,
  "fifty_two_week_high": 199.62,
  "fifty_two_week_low": 164.08,
  "day_high": 179.23,
  "day_low": 177.45,
  "open": 177.89,
  "previous_close": 176.27,
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 2: Get Historical Data

```python
# Initialize the history tool
history_tool = YahooGetHistoryTool()

# Get 1 year of daily data for Tesla
result = history_tool.execute({
    'symbol': 'TSLA',
    'period': '1y',
    'interval': '1d',
    'include_events': True
})

# Output
{
  "symbol": "TSLA",
  "period": "1y",
  "interval": "1d",
  "data_points": 252,
  "history": [
    {
      "date": "2024-10-31T00:00:00",
      "open": 242.50,
      "high": 248.30,
      "low": 241.20,
      "close": 246.80,
      "volume": 95234567,
      "adjusted_close": 246.80
    }
    // ... more data points
  ],
  "dividends": [],
  "splits": [],
  "currency": "USD",
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 3: Intraday Trading Data

```python
# Get 5-minute interval data for today
result = history_tool.execute({
    'symbol': 'GOOGL',
    'period': '1d',
    'interval': '5m'
})

# Returns 78 data points (6.5 trading hours * 12 intervals/hour)
```

### Example 4: Search for Symbols

```python
# Initialize the search tool
search_tool = YahooSearchSymbolsTool()

# Search for electric vehicle companies
result = search_tool.execute({
    'query': 'electric vehicle',
    'limit': 10
})

# Output
{
  "query": "electric vehicle",
  "result_count": 10,
  "results": [
    {
      "symbol": "TSLA",
      "name": "Tesla, Inc.",
      "exchange": "NASDAQ",
      "type": "EQUITY",
      "sector": "Consumer Cyclical",
      "industry": "Auto Manufacturers",
      "market_cap": 789456123000,
      "description": null
    },
    {
      "symbol": "RIVN",
      "name": "Rivian Automotive, Inc.",
      "exchange": "NASDAQ",
      "type": "EQUITY",
      "sector": "Consumer Cyclical",
      "industry": "Auto Manufacturers",
      "market_cap": 12345678900,
      "description": null
    }
    // ... more results
  ],
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 5: Market Index Quote

```python
# Get S&P 500 index data
result = quote_tool.execute({
    'symbol': '^GSPC'
})

# Get NASDAQ Composite
result = quote_tool.execute({
    'symbol': '^IXIC'
})

# Get Dow Jones Industrial Average
result = quote_tool.execute({
    'symbol': '^DJI'
})
```

### Example 6: ETF Data

```python
# Search for tech ETFs
result = search_tool.execute({
    'query': 'technology ETF',
    'limit': 5
})

# Get ETF quote
result = quote_tool.execute({
    'symbol': 'QQQ'  # Invesco QQQ Trust
})
```

### Example 7: Complete Analysis Workflow

```python
# Step 1: Search for companies in a sector
search_tool = YahooSearchSymbolsTool()
companies = search_tool.execute({
    'query': 'semiconductor',
    'exchange': 'NASDAQ',
    'limit': 20
})

# Step 2: Get current quotes for top companies
quote_tool = YahooGetQuoteTool()
quotes = []
for company in companies['results'][:5]:
    quote = quote_tool.execute({
        'symbol': company['symbol']
    })
    quotes.append(quote)

# Step 3: Get historical data for technical analysis
history_tool = YahooGetHistoryTool()
historical_data = {}
for company in companies['results'][:5]:
    history = history_tool.execute({
        'symbol': company['symbol'],
        'period': '1y',
        'interval': '1d'
    })
    historical_data[company['symbol']] = history

# Step 4: Analyze performance
for symbol, data in historical_data.items():
    first_close = data['history'][0]['close']
    last_close = data['history'][-1]['close']
    performance = ((last_close - first_close) / first_close) * 100
    print(f"{symbol}: {performance:.2f}% annual return")
```

### Example 8: Dividend Analysis

```python
# Get historical data with dividend events
result = history_tool.execute({
    'symbol': 'AAPL',
    'period': '5y',
    'interval': '1d',
    'include_events': True
})

# Analyze dividends
print(f"Total dividends paid: {len(result['dividends'])}")
total_dividend = sum(div['amount'] for div in result['dividends'])
print(f"Total dividend amount: ${total_dividend:.2f}")
```

### Example 9: Stock Split Tracking

```python
# Track stock splits
result = history_tool.execute({
    'symbol': 'TSLA',
    'period': 'max',
    'interval': '1d',
    'include_events': True
})

# Display splits
for split in result['splits']:
    print(f"Split on {split['date']}: {split['ratio']}")
```

### Example 10: Multi-Exchange Search

```python
# Search across specific exchanges
exchanges = ['NYSE', 'NASDAQ', 'AMEX']

all_results = []
for exchange in exchanges:
    result = search_tool.execute({
        'query': 'technology',
        'exchange': exchange,
        'limit': 10
    })
    all_results.extend(result['results'])

print(f"Found {len(all_results)} technology companies across {len(exchanges)} exchanges")
```

---

## Limitations & Best Practices

### Rate Limiting and Caching

**Server-side behaviour**:
- The `yahoo_` and `yf_` tools do not rate-limit or cache by themselves. Caching is opt-in per tool: add `"cache_ttl": <seconds>` to a tool's JSON config in `config/tools/` (none of the shipped Yahoo configs set it).
- **Timeout**: 10 seconds per request (`yahoo_` tools)
- Yahoo throttles heavy unauthenticated use (HTTP 429), so space out bulk requests.

**Best Practices**:
```python
import time

def rate_limited_quotes(symbols, delay=1.0):
    """Fetch quotes with rate limiting"""
    quotes = []
    for symbol in symbols:
        quote = quote_tool.execute({'symbol': symbol})
        quotes.append(quote)
        time.sleep(delay)  # Prevent rate limiting
    return quotes
```

### Yahoo Finance API Limitations

1. **Intraday Data**: Only last 30 days available for minute intervals
2. **Data Accuracy**: Prices may be delayed by 15-20 minutes outside market hours
3. **Historical Range**: Maximum available data varies by symbol
4. **Null Values**: Many metrics may be null for certain securities
5. **API Stability**: Unofficial API may change without notice
6. **Symbol Coverage**: Not all international symbols supported

### Content Limitations

- **Real-time vs Delayed**: Data may be delayed outside market hours
- **Symbol Format**: Must use correct Yahoo Finance symbol format
- **Corporate Actions**: Historical data adjusted for splits/dividends
- **Missing Data**: Some securities lack complete fundamental data
- **Index Data**: Indices may have limited historical data

### Best Practices

#### 1. Error Handling

```python
try:
    result = tool.execute(params)
except ValueError as e:
    if "not found" in str(e):
        print(f"Symbol not found: {params['symbol']}")
    else:
        print(f"Error: {e}")
    # Implement retry logic or fallback
```

#### 2. Input Validation

```python
def validate_symbol(symbol):
    """Validate stock symbol format"""
    import re
    pattern = r'^[A-Za-z0-9^.=-]{1,20}$'     # the tool's own inputSchema pattern
    if not re.match(pattern, symbol.upper()):
        raise ValueError(f"Invalid symbol format: {symbol}")
    return symbol.upper()
```

#### 3. Null Handling

```python
def safe_get(data, field, default=0):
    """Safely get value with default"""
    value = data.get(field)
    return value if value is not None else default

# Usage
price = safe_get(quote, 'price', 0)
pe_ratio = safe_get(quote, 'pe_ratio', None)
```

#### 4. Caching Results

```python
from functools import lru_cache
from datetime import datetime, timedelta

cache_expiry = {}

def cached_quote(symbol, ttl=60):
    """Cache quote data for TTL seconds"""
    key = f"quote_{symbol}"
    
    if key in cache_expiry:
        if datetime.now() < cache_expiry[key]['expiry']:
            return cache_expiry[key]['data']
    
    data = quote_tool.execute({'symbol': symbol})
    cache_expiry[key] = {
        'data': data,
        'expiry': datetime.now() + timedelta(seconds=ttl)
    }
    return data
```

#### 5. Batch Processing

```python
def batch_get_quotes(symbols, batch_size=5, delay=1.0):
    """Fetch quotes in batches with rate limiting"""
    quotes = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        for symbol in batch:
            try:
                quote = quote_tool.execute({'symbol': symbol})
                quotes.append(quote)
            except ValueError as e:
                print(f"Error fetching {symbol}: {e}")
        if i + batch_size < len(symbols):
            time.sleep(delay * batch_size)
    return quotes
```

#### 6. Period Selection for Historical Data

```python
# Choose appropriate period and interval combinations
period_interval_map = {
    '1d': ['1m', '2m', '5m', '15m', '30m', '1h'],
    '5d': ['5m', '15m', '30m', '1h'],
    '1mo': ['30m', '1h', '1d'],
    '3mo': ['1d'],
    '1y': ['1d', '1wk'],
    '5y': ['1d', '1wk', '1mo'],
    'max': ['1d', '1wk', '1mo']
}

def get_valid_interval(period):
    """Get valid intervals for a period"""
    return period_interval_map.get(period, ['1d'])
```

### Performance Optimization

1. **Cache Frequently Accessed Data**: Store quote data for reuse
2. **Batch Requests**: Group similar queries
3. **Use Appropriate Intervals**: Match interval to analysis needs
4. **Filter Results**: Use exchange filters in search
5. **Connection Pooling**: Reuse HTTP connections

---

## Error Handling

### Error Types

#### 1. HTTP Errors

```python
urllib.error.HTTPError
- 404: Symbol not found
- 429: Too many requests (rate limit)
- 500: Yahoo Finance server error
- 503: Service temporarily unavailable
```

#### 2. Validation Errors

```python
ValueError
- Invalid symbol format
- Invalid period or interval
- Symbol not found in database
- No data available for requested period
```

#### 3. Network Errors

```python
urllib.error.URLError
- Connection timeout
- DNS resolution failure
- Network unreachable
```

### Error Response Format

The tools raise `ValueError` with a message such as `Symbol or resource not found` or `Failed to get quote for XYZ: ...`. Over REST (`POST /api/tools/execute`) that becomes HTTP 500 with `{"success": false, "error": "<message>"}`; over MCP it is a `tools/call` result with `isError: true` and the message as text content.

### Handling Examples

```python
# Example 1: Handle invalid symbol
try:
    result = quote_tool.execute({'symbol': 'INVALID123'})
except ValueError as e:
    if "not found" in str(e):
        # Try searching for the symbol
        search_results = search_tool.execute({'query': 'INVALID123'})
        if search_results['result_count'] > 0:
            correct_symbol = search_results['results'][0]['symbol']
            result = quote_tool.execute({'symbol': correct_symbol})

# Example 2: Handle timeout
try:
    result = tool.execute(params)
except urllib.error.URLError as e:
    if "timeout" in str(e):
        print("Request timed out. Retrying...")
        time.sleep(2)
        result = tool.execute(params)

# Example 3: Handle rate limiting
def execute_with_backoff(tool, params, max_retries=3):
    """Execute with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return tool.execute(params)
        except ValueError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Attempt {attempt + 1} failed. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    
# Example 4: Handle missing data gracefully
def safe_quote(symbol):
    """Get quote with fallback for missing data"""
    try:
        quote = quote_tool.execute({'symbol': symbol})
        return {
            'symbol': quote['symbol'],
            'price': quote.get('price', 0),
            'change_percent': quote.get('change_percent', 0),
            'volume': quote.get('volume', 0)
        }
    except ValueError:
        return {
            'symbol': symbol,
            'price': None,
            'change_percent': None,
            'volume': None,
            'error': 'Data not available'
        }
```

---

## Appendix

### A. Symbol Format Examples

| Type              | Symbol    | Description                    |
|-------------------|-----------|--------------------------------|
| US Stocks         | AAPL      | Apple Inc.                     |
| US Stocks         | BRK-A     | Berkshire Hathaway Class A     |
| Indices           | ^GSPC     | S&P 500                        |
| Indices           | ^DJI      | Dow Jones Industrial Average   |
| Indices           | ^IXIC     | NASDAQ Composite               |
| ETFs              | SPY       | SPDR S&P 500 ETF               |
| ETFs              | QQQ       | Invesco QQQ Trust              |
| International     | NESN.SW   | Nestlé (Swiss)                 |
| International     | 7203.T    | Toyota (Tokyo)                 |
| Cryptocurrency    | BTC-USD   | Bitcoin USD                    |
| Currency          | EURUSD=X  | Euro/USD                       |
| Futures           | ES=F      | E-mini S&P 500 Futures         |

### B. Period and Interval Compatibility

| Period | Compatible Intervals                      | Max Data Points |
|--------|-------------------------------------------|-----------------|
| 1d     | 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h      | 390 (1m)        |
| 5d     | 5m, 15m, 30m, 1h, 1d                     | 390 (5m)        |
| 1mo    | 30m, 1h, 1d                               | ~390 (30m)      |
| 3mo    | 1h, 1d                                    | ~390 (1h)       |
| 6mo    | 1d, 1wk                                   | ~126 (1d)       |
| 1y     | 1d, 1wk                                   | ~252 (1d)       |
| 5y     | 1d, 1wk, 1mo                              | ~1260 (1d)      |
| max    | 1d, 1wk, 1mo                              | Varies          |

### C. Market Hours

| Market        | Trading Hours (Local) | Trading Hours (UTC)    |
|---------------|-----------------------|------------------------|
| NYSE/NASDAQ   | 9:30 AM - 4:00 PM ET  | 14:30 - 21:00 UTC      |
| LSE           | 8:00 AM - 4:30 PM GMT | 8:00 - 16:30 UTC       |
| TSX           | 9:30 AM - 4:00 PM ET  | 14:30 - 21:00 UTC      |
| Tokyo Stock   | 9:00 AM - 3:00 PM JST | 0:00 - 6:00 UTC        |

### D. Tool Registry

```python
YAHOO_FINANCE_TOOLS = {
    'yahoo_get_quote': YahooGetQuoteTool,
    'yahoo_get_history': YahooGetHistoryTool,
    'yahoo_search_symbols': YahooSearchSymbolsTool
}

# Dynamic tool instantiation
tool_name = 'yahoo_get_quote'
tool_class = YAHOO_FINANCE_TOOLS[tool_name]
tool_instance = tool_class()
```

### E. Common Use Cases

**Portfolio Monitoring**:
```python
portfolio = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
for symbol in portfolio:
    quote = quote_tool.execute({'symbol': symbol})
    print(f"{symbol}: ${quote['price']} ({quote['change_percent']:.2f}%)")
```

**Technical Analysis**:
```python
# Get historical data
data = history_tool.execute({
    'symbol': 'AAPL',
    'period': '1y',
    'interval': '1d'
})

# Calculate moving averages
closes = [point['close'] for point in data['history'] if point['close']]
ma_50 = sum(closes[-50:]) / 50
ma_200 = sum(closes[-200:]) / 200

print(f"50-day MA: ${ma_50:.2f}")
print(f"200-day MA: ${ma_200:.2f}")
```

**Sector Comparison**:
```python
sectors = ['technology', 'healthcare', 'finance']
for sector in sectors:
    results = search_tool.execute({
        'query': sector,
        'limit': 10
    })
    print(f"{sector.title()}: {results['result_count']} companies found")
```

### F. Troubleshooting Guide

**Problem**: "Symbol not found" error
- **Solution**: Verify symbol format, try search tool first, check exchange suffix

**Problem**: Request timeout
- **Solution**: Check internet connection, retry with backoff, increase timeout

**Problem**: No intraday data available
- **Solution**: Check if requesting data older than 30 days, use daily interval

**Problem**: Missing fundamental data (PE ratio, market cap)
- **Solution**: Some securities don't have all metrics, handle nulls appropriately

**Problem**: Rate limit exceeded (HTTP 429 from Yahoo)
- **Solution**: Implement delays between requests, or set `cache_ttl` in the tool config

### G. Legal Disclaimer

⚠️ **Important**: This tool uses Yahoo Finance's unofficial API. Users should:

- Use data for personal/educational purposes
- Respect rate limits and terms of service
- Not redistribute data commercially
- Verify data accuracy for financial decisions
- Be aware that API may change without notice

The tool author is not responsible for:
- Data accuracy or completeness
- Financial losses from using this data
- API availability or changes
- Terms of service violations

**For commercial use, obtain proper data licenses from official providers.**

---

*Terms used in this guide are defined in the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
