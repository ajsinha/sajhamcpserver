# Yahoo Finance (yfinance) — Tool Reference Guide

**Version:** 3.1.0 · **Tools:** 35 · **API Key Required:** No (free)

---

## Overview

SAJHA provides 35 Yahoo Finance tools via the `yfinance` Python library, covering stock info, historical data, financial statements, dividends, options, analyst data, screeners, crypto, forex, and ETFs.

**No API key required** — yfinance accesses Yahoo Finance's free public data.

## Tool List (35 tools)

### Company Information (6 tools)

| Tool | Description |
|------|-------------|
| `yfinance_stock_info` | Full company info (sector, industry, market cap, employees, description) |
| `yfinance_fast_info` | Quick price and volume data |
| `yfinance_sustainability` | ESG scores and sustainability ratings |
| `yfinance_calendar` | Upcoming earnings dates, ex-dividend dates |
| `yfinance_news` | Latest company news articles |
| `yfinance_compare_stocks` | Side-by-side comparison of multiple tickers |

### Price & History (4 tools)

| Tool | Description |
|------|-------------|
| `yfinance_stock_history` | OHLCV historical data (1d to max) |
| `yfinance_multi_ticker_history` | Historical data for multiple symbols |
| `yfinance_forex_history` | Currency pair historical rates |
| `yfinance_index_history` | Index historical data (^GSPC, ^DJI, etc.) |

### Financial Statements (3 tools)

`yfinance_income_statement`, `yfinance_balance_sheet`, `yfinance_cash_flow`

### Dividends & Splits (3 tools)

`yfinance_dividends`, `yfinance_splits`, `yfinance_actions`

### Holders & Ownership (4 tools)

`yfinance_institutional_holders`, `yfinance_major_holders`, `yfinance_mutual_fund_holders`, `yfinance_shares_outstanding`

### Analyst & Insider (5 tools)

`yfinance_recommendations`, `yfinance_analyst_price_targets`, `yfinance_upgrades_downgrades`, `yfinance_insider_transactions`, `yfinance_insider_purchases`

### Earnings (2 tools)

`yfinance_earnings_history`, `yfinance_earnings_dates`

### Options (2 tools)

`yfinance_options_expiries`, `yfinance_options_chain`

### Market Overview (4 tools)

`yfinance_screener`, `yfinance_sector_performance`, `yfinance_trending_tickers`, `yfinance_market_summary`

### Crypto & ETF (2 tools)

`yfinance_crypto_info`, `yfinance_etf_info`

## Usage Example

```python
result = client.execute_tool("yfinance_stock_history", {
    "symbol": "AAPL", "period": "1y", "interval": "1d"
})

result = client.execute_tool("yfinance_options_chain", {
    "symbol": "TSLA", "expiration": "2025-06-20"
})
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
