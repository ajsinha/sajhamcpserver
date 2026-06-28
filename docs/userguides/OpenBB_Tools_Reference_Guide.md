# OpenBB Platform — Tool Reference Guide

**Version:** 5.2.0 · **Tools:** 70 · **API Key Required:** No (SDK-based, providers may need keys)

---

## Overview

SAJHA provides 70 OpenBB tools that expose the OpenBB Platform SDK for equities, fixed income, commodities, crypto, forex, economics, ETFs, indices, options, and regulatory data. Tools use the `openbb` Python package and support multiple data providers (Yahoo Finance, FMP, Intrinio, Polygon, etc.) via a `provider` parameter.

**Installation:** `pip install "openbb[all]"` or select specific providers:
```bash
pip install "openbb[yfinance,fmp,fred,sec]"
```

## Architecture

25 named Python classes plus the `OpenBBGenericTool` auto-mapper. The generic tool maps tool names to OpenBB SDK paths: `openbb_equity_price` → `obb.equity.price.quote()`.

Adding a new OpenBB tool requires only a JSON config — `OpenBBGenericTool` handles the rest.

## Tool Categories

### Equity — Fundamentals & Pricing (20 tools)

| Tool | OpenBB Path | Description |
|------|-------------|-------------|
| `openbb_equity_price` | `equity.price.quote` | Real-time stock price |
| `openbb_equity_profile` | `equity.profile` | Company profile |
| `openbb_equity_search` | `equity.search` | Search for equities |
| `openbb_income_statement` | `equity.fundamental.income` | Income statement |
| `openbb_balance_sheet` | `equity.fundamental.balance` | Balance sheet |
| `openbb_cash_flow` | `equity.fundamental.cash` | Cash flow statement |
| `openbb_equity_fundamental_ratios` | `equity.fundamental.ratios` | Financial ratios |
| `openbb_equity_fundamental_overview` | `equity.fundamental.overview` | Company overview |
| `openbb_equity_metrics` | `equity.fundamental.metrics` | Key metrics |
| `openbb_equity_management` | `equity.fundamental.management` | Management team |
| `openbb_equity_revenue_geographic` | `equity.fundamental.revenue_geographic` | Revenue by geography |
| `openbb_equity_revenue_segment` | `equity.fundamental.revenue_segment` | Revenue by segment |
| `openbb_equity_price_performance` | `equity.price.performance` | Price performance |
| `openbb_equity_share_statistics` | `equity.fundamental.share_statistics` | Shares data |
| `openbb_equity_compare_peers` | `equity.compare.peers` | Peer comparison |
| `openbb_equity_screener` | `equity.screener` | Multi-criteria screener |
| `openbb_dividends` | `equity.fundamental.dividends` | Dividend history |
| `openbb_earnings` | `equity.fundamental.earnings` | Earnings data |
| `openbb_insider_trading` | `equity.ownership.insider_trading` | Insider transactions |
| `openbb_institutional_ownership` | `equity.ownership.institutional` | Institutional holders |

### Equity — Discovery & Calendar (8 tools)

`openbb_equity_discovery_active`, `openbb_equity_discovery_gainers`, `openbb_equity_discovery_losers`, `openbb_equity_calendar_dividend`, `openbb_equity_calendar_earnings`, `openbb_equity_estimates_consensus`, `openbb_company_news`, `openbb_market_news`

### Fixed Income (8 tools)

`openbb_fixedincome_sofr`, `openbb_fixedincome_effr`, `openbb_fixedincome_estr`, `openbb_fixedincome_iorb`, `openbb_fixedincome_moody`, `openbb_fixedincome_ice_bofa`, `openbb_fixedincome_treasury_auctions`, `openbb_treasury_rates`

### Economy (10 tools)

`openbb_economy_gdp`, `openbb_economy_cpi`, `openbb_economy_calendar`, `openbb_economy_interest_rate`, `openbb_economy_leading`, `openbb_economy_risk_premium`, `openbb_economy_available_indicators`, `openbb_economic_indicators`, `openbb_unemployment`, `openbb_yield_curve`

### ETFs (6 tools)

`openbb_etf_search`, `openbb_etf_info`, `openbb_etf_holdings`, `openbb_etf_sectors`, `openbb_etf_countries`, `openbb_etf_equity_exposure`

### Indices (4 tools)

`openbb_index_search`, `openbb_index_available`, `openbb_index_constituents`, `openbb_index_price_historical`

### Commodities (4 tools)

`openbb_commodity_price`, `openbb_commodity_search`, `openbb_commodity_lbma_gold`, `openbb_commodity_lbma_silver`

### Forex & Crypto (4 tools)

`openbb_forex_historical`, `openbb_currency_snapshots`, `openbb_crypto_price`, `openbb_crypto_search`

### Derivatives & Options (3 tools)

`openbb_options_chains`, `openbb_derivatives_futures_curve`, `openbb_derivatives_futures_historical`

### Regulatory (3 tools)

`openbb_regulators_sec_filings`, `openbb_regulators_sec_search`, `openbb_news_search`

## Provider Parameter

Most OpenBB tools accept a `provider` parameter to select the data source:

```json
{"symbol": "AAPL", "provider": "fmp"}
{"symbol": "AAPL", "provider": "yfinance"}
{"symbol": "AAPL", "provider": "intrinio"}
```

Available providers depend on which `openbb[provider]` extras are installed.

## Usage Example

```python
from sajhaclient import SajhaConfig, SajhaClient, ApiKeyAuth
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sk_live_..."))

# Get income statement from FMP provider
result = client.execute_tool("openbb_income_statement", {
    "symbol": "MSFT", "period": "annual", "provider": "fmp", "limit": 5
})

# Screen for large-cap tech stocks
result = client.execute_tool("openbb_equity_screener", {
    "mktcap_min": 100000000000, "sector": "Technology"
})
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
