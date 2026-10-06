# Alpha Vantage Tool Reference Guide

## Overview

The Alpha Vantage tools (prefix `av_`) wrap the [Alpha Vantage](https://www.alphavantage.co/documentation/) REST API: stock quotes and time series, company fundamentals, technical indicators, forex, crypto and US economic data. Implementation: `sajha/tools/impl/alphavantage_tools.py`.

## API Key

All `av_` tool configs read their key from the config key `alpha_vantage.api.key` (`"api_key": "${alpha_vantage.api.key}"`). This key is **not** defined in the shipped `config/application.yml`, so add it alongside the other external API keys:

```yaml
alpha_vantage:
  api:
    key: ${ALPHA_VANTAGE_API_KEY:}
```

Get a free key at [alphavantage.co](https://www.alphavantage.co/support/#api-key) (the free tier is rate-limited to a small number of requests per day). See the [Configuration Reference](../../getting-started/Configuration%20Reference.md) for how config keys and environment variables are resolved.

## Tools

The tables below are generated from the tool configs in `config/tools/`; the live catalog in the app (Tools page, or `tools/list`) is authoritative. Parameters marked *(required)* must be supplied. Defaults shown are the schema defaults.

### Company Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_company_overview` | Get company fundamentals overview from Alpha Vantage — PE, EPS, dividend, market cap, sector, description | `symbol` (required) |

### Cryptocurrency

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_crypto_daily` | Get daily crypto prices from Alpha Vantage — BTC, ETH, etc. | `symbol` (required), default `BTC`; `market`, default `USD` |
| `av_crypto_weekly` | Get weekly crypto prices from Alpha Vantage | `symbol` (required), default `BTC`; `market`, default `USD` |

### Earnings

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_earnings` | Get earnings data from Alpha Vantage — annual and quarterly EPS | `symbol` (required) |

### Economics

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_cpi` | Get US Consumer Price Index from Alpha Vantage | `interval`, default `monthly` |
| `av_fed_funds_rate` | Get Federal Funds Rate from Alpha Vantage | `interval`, default `monthly` |
| `av_gdp` | Get US Real GDP from Alpha Vantage — quarterly and annual | `interval`: annual / quarterly, default `annual` |
| `av_inflation` | Get US inflation rate from Alpha Vantage | — |
| `av_unemployment` | Get US unemployment rate from Alpha Vantage | — |

### Financial Statements

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_balance_sheet` | Get balance sheet from Alpha Vantage — assets, liabilities, equity | `symbol` (required) |
| `av_cash_flow` | Get cash flow from Alpha Vantage — operating, investing, financing | `symbol` (required) |
| `av_income_statement` | Get income statement from Alpha Vantage — revenue, expenses, net income | `symbol` (required) |

### Fixed Income

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_treasury_yield` | Get Treasury Yield from Alpha Vantage — 2yr, 5yr, 7yr, 10yr, 30yr | `maturity`: 3month / 2year / 5year / 7year / 10year / 30year, default `10year` |

### Forex

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_forex_daily` | Get daily forex rates from Alpha Vantage — historical exchange rates | `from`, default `EUR`; `to`, default `USD` |
| `av_forex_rate` | Get real-time forex exchange rate from Alpha Vantage — any currency pair | `from`, default `EUR`; `to`, default `USD` |
| `av_forex_weekly` | Get weekly forex rates from Alpha Vantage | `from`, default `EUR`; `to`, default `USD` |

### Market Data

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_stock_daily` | Get daily stock prices from Alpha Vantage — OHLCV time series | `symbol` (required); `outputsize`: compact / full, default `compact` |
| `av_stock_intraday` | Get intraday stock prices from Alpha Vantage — 1min, 5min, 15min, 30min, 60min intervals | `symbol` (required); `interval`: 1min / 5min / 15min / 30min / 60min, default `5min` |
| `av_stock_monthly` | Get monthly stock prices from Alpha Vantage | `symbol` (required) |
| `av_stock_quote` | Get real-time stock quote from Alpha Vantage — price, change, volume | `symbol` (required) |
| `av_stock_weekly` | Get weekly stock prices from Alpha Vantage | `symbol` (required) |

### Technical Indicators

| Tool | Description | Parameters |
|------|-------------|------------|
| `av_ad_line` | Get Accumulation/Distribution Line from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_adx` | Get Average Directional Index from Alpha Vantage — trend strength | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_aroon` | Get Aroon Indicator from Alpha Vantage — trend detection | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_atr` | Get Average True Range from Alpha Vantage — volatility measure | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_bbands` | Get Bollinger Bands from Alpha Vantage — volatility bands | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_cci` | Get Commodity Channel Index from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_ema` | Get Exponential Moving Average from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_macd` | Get MACD from Alpha Vantage — trend and momentum | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_obv` | Get On-Balance Volume from Alpha Vantage — volume-price trend | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_rsi` | Get Relative Strength Index from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_sma` | Get Simple Moving Average from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_stoch` | Get Stochastic Oscillator from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_vwap` | Get Volume Weighted Average Price from Alpha Vantage | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |
| `av_williams_r` | Get Williams %R from Alpha Vantage — overbought/oversold | `symbol` (required); `interval`, default `daily`; `time_period`, default `14` |

### Implementation notes

- `av_macd`, `av_stoch`, `av_obv`, `av_ad_line` and `av_vwap` advertise `time_period` in their schema, but the implementation does not forward it to Alpha Vantage (these indicators use the provider's defaults).
- `av_treasury_yield` also accepts an undocumented `interval` argument (default `monthly`) that is not in its schema.
- For indicators that do forward `time_period`, the server-side fallback when it is omitted is 20 for SMA, EMA, BBANDS and CCI, and 14 for RSI, ADX, AROON, ATR and Williams %R (schema defaults are not applied server-side).
- `av_vwap` falls back to `interval` = `15min` when omitted (VWAP is intraday-only at Alpha Vantage); pass an intraday interval explicitly.

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "av_rsi", "arguments": {"symbol": "AAPL", "interval": "daily", "time_period": 14}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "av_rsi", "arguments": {"symbol": "AAPL", "interval": "daily", "time_period": 14}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("av_rsi", symbol="AAPL", interval="daily", time_period=14)
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
