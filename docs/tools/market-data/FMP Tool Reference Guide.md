# FMP (Financial Modeling Prep) — Tool Reference Guide

**Version:** 5.3.0 · **Tools:** 100 · **API Key Required:** Yes (`fmp.api.key` in `config/application.yml`)

---

## Overview

SAJHA provides 100 FMP tools covering company fundamentals, market data, SEC filings, economic indicators, commodities, crypto, forex, ETFs, and technical analysis. Tools are split between 30 named Python classes and the `FMPGenericTool` auto-mapper that generates tools directly from JSON configs.

**API Key:** Get a free key at [financialmodelingprep.com](https://financialmodelingprep.com/developer/docs/). Set it in `config/application.yml`:

```yaml
fmp:
  api:
    key: ${FMP_API_KEY:your-key-here}
```

## Adding New FMP Tools

FMP uses the Generic Tool Pattern — add a JSON file to `config/tools/` and the tool appears automatically:

```json
{
  "name": "fmp_new_endpoint",
  "implementation": "sajha.tools.impl.fmp_tools.FMPGenericTool",
  "description": "Description of what this endpoint returns",
  "enabled": true,
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {"type": "string", "description": "Ticker symbol"}
    },
    "required": ["symbol"]
  },
  "api_key": "${fmp.api.key}"
}
```

No Python code needed — `FMPGenericTool` maps the tool name to the FMP API endpoint path.

## Tool Categories

### Company Fundamentals (25 tools)

| Tool | Description |
|------|-------------|
| `fmp_company_profile` | Company overview, sector, industry, market cap |
| `fmp_income_statement` | Revenue, expenses, net income |
| `fmp_balance_sheet` | Assets, liabilities, equity |
| `fmp_cash_flow` | Operating, investing, financing cash flows |
| `fmp_key_metrics` | PE, PB, ROE, ROA, and other metrics |
| `fmp_financial_growth` | YoY revenue, earnings growth rates |
| `fmp_financial_score` | Altman Z-score, Piotroski score |
| `fmp_enterprise_value` | EV, EV/EBITDA, EV/Revenue |
| `fmp_key_executives` | CEO, CFO, board members |
| `fmp_employee_count` | Historical employee counts |
| `fmp_exec_compensation` | Executive salary and stock grants |
| `fmp_company_peers` | Similar companies by sector/size |
| `fmp_stock_peers_bulk` | Bulk peer lookup |
| `fmp_dcf_valuation` | Discounted cash flow valuation |
| `fmp_levered_dcf` | Levered DCF model |
| `fmp_historical_dcf` | Historical DCF values |
| `fmp_owner_earnings` | Buffett-style owner earnings |
| `fmp_rating` | Consensus rating (buy/hold/sell) |
| `fmp_grade` | Analyst grade history |
| `fmp_esg_rating` | Environmental, social, governance scores |
| `fmp_revenue_by_geography` | Revenue breakdown by region |
| `fmp_revenue_by_product` | Revenue breakdown by segment |
| `fmp_share_float` | Public float and shares outstanding |
| `fmp_historical_market_cap` | Historical market capitalization |
| `fmp_market_cap` | Current market cap |

### Market Data (15 tools)

| Tool | Description |
|------|-------------|
| `fmp_stock_quote` | Real-time price, volume, change |
| `fmp_historical_price` | OHLCV historical data |
| `fmp_stock_list` | All available stock symbols |
| `fmp_stock_screener` | Multi-criteria stock screener |
| `fmp_market_gainers` | Top gainers |
| `fmp_market_losers` | Top losers |
| `fmp_most_active` | Most actively traded |
| `fmp_actively_trading` | Currently trading stocks |
| `fmp_sector_performance` | Sector returns |
| `fmp_market_hours` | Exchange trading hours |
| `fmp_market_risk_premium` | Equity risk premium |
| `fmp_symbol_search` | Search for tickers |
| `fmp_symbol_changes` | Ticker symbol changes |
| `fmp_stock_news` | Company news |
| `fmp_press_releases` | Company press releases |

### Analyst & Sentiment (8 tools)

`fmp_analyst_estimates`, `fmp_price_target`, `fmp_price_target_by_analyst`, `fmp_price_target_summary`, `fmp_upgrades_downgrades`, `fmp_upgrades_downgrades_consensus`, `fmp_social_sentiment`, `fmp_senate_trading`

### SEC & Filings (6 tools)

`fmp_sec_filings`, `fmp_13f_filing`, `fmp_cik_list`, `fmp_crowdfunding_rss`, `fmp_equity_offering`, `fmp_insider_trading`

### Institutional & Holders (2 tools)

`fmp_institutional_holders`, `fmp_mutual_fund_holders`

### ETFs (6 tools)

`fmp_etf_list`, `fmp_etf_holdings`, `fmp_etf_sector_weights`, `fmp_etf_country_weights`, `fmp_etf_stock_exposure`, `fmp_stock_split_calendar`

### Indices (5 tools)

`fmp_index_quote`, `fmp_index_historical`, `fmp_sp500_constituents`, `fmp_nasdaq_constituents`, `fmp_dowjones_constituents`, `fmp_available_indexes`

### Technical Indicators (13 tools)

`fmp_technical_sma`, `fmp_technical_ema`, `fmp_technical_dema`, `fmp_technical_tema`, `fmp_technical_wma`, `fmp_technical_rsi`, `fmp_technical_macd`, `fmp_technical_bbands`, `fmp_technical_adx`, `fmp_technical_stoch`, `fmp_technical_williams`, `fmp_technical_stddev`

### Commodities & Forex & Crypto (10 tools)

`fmp_commodity_list`, `fmp_commodity_quote`, `fmp_commodity_historical`, `fmp_forex_list`, `fmp_forex_quote`, `fmp_forex_historical`, `fmp_crypto_list`, `fmp_crypto_quote`, `fmp_crypto_historical`

### Economic & Calendar (8 tools)

`fmp_earnings_calendar`, `fmp_earnings_transcript`, `fmp_economic_calendar`, `fmp_dividend_calendar`, `fmp_ipo_calendar`, `fmp_treasury_rates`, `fmp_available_countries`, `fmp_available_exchanges`, `fmp_available_industries`, `fmp_available_sectors`

## Usage Examples

```python
# Via REST API
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"tool": "fmp_company_profile", "arguments": {"symbol": "AAPL"}}'

# Via MCP protocol
curl -X POST http://localhost:3002/mcp \
  -H "X-API-Key: YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"fmp_stock_screener","arguments":{"marketCapMoreThan":100000000000,"sector":"Technology","limit":10}}}'

# Via Python SDK
from sajhaclient import SajhaConfig, SajhaClient, ApiKeyAuth
client = SajhaClient(SajhaConfig(base_url="http://localhost:3002"), auth=ApiKeyAuth("sk_live_..."))
result = client.execute_tool("fmp_analyst_estimates", {"symbol": "TSLA", "period": "quarter"})
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
