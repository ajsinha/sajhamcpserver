# FRED Tool Reference Guide

## Overview

The FRED tools (prefix `fred_`) read series observations from the St. Louis Fed's [FRED API](https://fred.stlouisfed.org/docs/api/fred/). Each named tool fetches one well-known series; `fred_custom_series` fetches any FRED series by ID. Implementation: `sajha/tools/impl/fred_tools.py`.

## API Key

All `fred_` configs use `"api_key": "${fred.api.key}"`, which `config/application.yml` binds to the `FRED_API_KEY` environment variable:

```yaml
fred:
  api:
    key: ${FRED_API_KEY:}
```

Get a free key at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html). See the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

## Parameters

There are two kinds of FRED tool:

- **Fixed-series tools** (Kind = fixed below; a dedicated class per series, e.g. `fred_gdp`, `fred_unemployment`) accept one optional argument, `limit` (number of observations).
- **Series-ID tools** (Kind = series-ID below, e.g. `fred_5yr_treasury`, `fred_gold_price`, `fred_custom_series`) are implemented by `FREDCustomSeriesTool` and accept `series_id` and `limit`. Their configs give `series_id` a default (the series named in the table), but schema defaults are not applied server-side, so **pass `series_id` explicitly**. For `fred_custom_series` it is required.

Every tool returns the **most recent** `limit` observations, **newest first**: the request sends `sort_order=desc` (FRED's own default is ascending, where `limit` would return the oldest observations, e.g. GDP from 1947). Reverse the list for a chronological chart. When `limit` is omitted the tool's own default applies (40 for `fred_gdp`, `fred_gdp_growth` and `fred_national_debt`, 60 otherwise; the configs' schema default of 30 is not applied server-side).

## Tools

The tables below are generated from the tool configs in `config/tools/`; the live catalog in the app (Tools page, or `tools/list`) is authoritative.

### Any Series

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_custom_series` | any (`series_id` required) | series-ID | Fetch ANY of 800,000+ FRED data series by ID — the universal economic data tool |

### Commodities

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_copper_price` | `PCOPPUSDM` | series-ID | Get Copper Price from FRED (series: PCOPPUSDM) |
| `fred_corn_price` | `PMAIZMTUSDM` | series-ID | Get Corn Price from FRED (series: PMAIZMTUSDM) |
| `fred_gold_price` | `GOLDAMGBD228NLBM` | series-ID | Get Gold Price (London Fix) from FRED (series: GOLDAMGBD228NLBM) |
| `fred_oil_price` | `DCOILWTICO` | fixed | Get WTI Crude Oil Price from FRED |
| `fred_silver_price` | `SLVPRUSD` | series-ID | Get Silver Price from FRED (series: SLVPRUSD) |
| `fred_wheat_price` | `PWHEAMTUSDM` | series-ID | Get Wheat Price from FRED (series: PWHEAMTUSDM) |

### Economics

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_auto_sales` | `TOTALSA` | series-ID | Get US Auto Sales from FRED — vehicle unit sales (series: TOTALSA) |
| `fred_avg_hourly_earnings` | `CES0500000003` | series-ID | Get US Average Hourly Earnings from FRED (series: CES0500000003) |
| `fred_business_inventories` | `BUSINV` | series-ID | Get US Business Inventories from FRED (series: BUSINV) |
| `fred_capacity_utilization` | `TCU` | fixed | Get US Capacity Utilization Rate from FRED |
| `fred_consumer_credit` | `TOTALSL` | series-ID | Get US Total Consumer Credit from FRED (series: TOTALSL) |
| `fred_consumer_sentiment` | `UMCSENT` | fixed | Get Michigan Consumer Sentiment Index from FRED |
| `fred_continuing_claims` | `CCSA` | fixed | Get Continuing Jobless Claims from FRED |
| `fred_core_cpi` | `CPILFESL` | series-ID | Get US Core CPI (excluding food & energy) from FRED (series: CPILFESL) |
| `fred_cpi` | `CPIAUCSL` | fixed | Get US Consumer Price Index (CPIAUCSL) from FRED |
| `fred_durable_goods` | `DGORDER` | series-ID | Get US Durable Goods Orders from FRED (series: DGORDER) |
| `fred_fed_funds_rate` | `FEDFUNDS` | fixed | Get Federal Funds Effective Rate from FRED |
| `fred_gdp` | `GDP` | fixed | Get US Gross Domestic Product from FRED |
| `fred_gdp_growth` | `A191RL1Q225SBEA` | fixed | Get US GDP Growth Rate from FRED — quarterly annualized |
| `fred_industrial_production` | `INDPRO` | fixed | Get US Industrial Production Index from FRED |
| `fred_initial_claims` | `ICSA` | fixed | Get Initial Jobless Claims (weekly) from FRED |
| `fred_labor_force` | `CLF16OV` | series-ID | Get US Civilian Labor Force from FRED (series: CLF16OV) |
| `fred_leading_index` | `USSLIND` | series-ID | Get Conference Board Leading Economic Index from FRED (series: USSLIND) |
| `fred_m2_money_supply` | `M2SL` | fixed | Get M2 Money Supply from FRED |
| `fred_national_debt` | `GFDEBTN` | fixed | Get US Federal Debt Total from FRED |
| `fred_nonfarm_payrolls` | `PAYEMS` | series-ID | Get US Nonfarm Payrolls from FRED — monthly jobs report (series: PAYEMS) |
| `fred_pce` | `PCE` | fixed | Get US Personal Consumption Expenditures from FRED |
| `fred_personal_income` | `PI` | fixed | Get US Personal Income from FRED |
| `fred_pmi` | `MANEMP` | fixed | Get Manufacturing Employment (proxy for PMI) from FRED |
| `fred_ppi` | `PPIACO` | series-ID | Get US Producer Price Index from FRED (series: PPIACO) |
| `fred_prime_rate` | `DPRIME` | fixed | Get US Bank Prime Loan Rate from FRED |
| `fred_real_gdp_per_capita` | `A939RX0Q048SBEA` | series-ID | Get US Real GDP Per Capita from FRED (series: A939RX0Q048SBEA) |
| `fred_real_personal_income` | `DSPIC96` | series-ID | Get US Real Disposable Personal Income from FRED (series: DSPIC96) |
| `fred_retail_sales` | `RSAFS` | fixed | Get US Retail Sales from FRED |
| `fred_trade_balance` | `BOPGSTB` | fixed | Get US Trade Balance (Goods & Services) from FRED |
| `fred_unemployment` | `UNRATE` | fixed | Get US Unemployment Rate (UNRATE) from FRED |

### Fixed Income

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_10yr_treasury` | `DGS10` | fixed | Get 10-Year Treasury Yield (DGS10) from FRED |
| `fred_2yr_treasury` | `DGS2` | fixed | Get 2-Year Treasury Yield (DGS2) from FRED |
| `fred_30yr_mortgage` | `MORTGAGE30US` | fixed | Get 30-Year Fixed Mortgage Rate from FRED |
| `fred_30yr_treasury` | `DGS30` | series-ID | Get 30-Year Treasury Yield from FRED (series: DGS30) |
| `fred_5yr_treasury` | `DGS5` | series-ID | Get 5-Year Treasury Yield from FRED (series: DGS5) |
| `fred_breakeven_inflation` | `T10YIE` | series-ID | Get 10-Year Breakeven Inflation Rate from FRED (series: T10YIE) |
| `fred_credit_spread` | `BAMLC0A0CM` | series-ID | Get ICE BofA US Corporate Bond Spread from FRED (series: BAMLC0A0CM) |
| `fred_high_yield_spread` | `BAMLH0A0HYM2` | series-ID | Get ICE BofA High Yield Spread from FRED (series: BAMLH0A0HYM2) |
| `fred_natural_gas` | `DHHNGSP` | series-ID | Get Henry Hub Natural Gas Spot Price from FRED (series: DHHNGSP) |
| `fred_real_interest_rate` | `REAINTRATREARAT10Y` | series-ID | Get 10-Year Real Interest Rate from FRED (series: REAINTRATREARAT10Y) |
| `fred_yield_spread` | `T10Y2Y` | series-ID | Get 10Y-2Y Treasury Yield Spread from FRED — recession indicator (series: T10Y2Y) |

### Forex

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_dollar_index` | `DTWEXBGS` | fixed | Get Trade Weighted US Dollar Index from FRED |

### Market Data

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_sp500` | `SP500` | fixed | Get S&P 500 Index from FRED |
| `fred_vix` | `VIXCLS` | fixed | Get CBOE Volatility Index (VIX) from FRED |

### Real Estate

| Tool | FRED series | Kind | Description |
|------|-------------|------|-------------|
| `fred_building_permits` | `PERMIT` | fixed | Get US Building Permits from FRED |
| `fred_existing_home_sales` | `EXHOSLUSM495S` | fixed | Get US Existing Home Sales from FRED |
| `fred_housing_starts` | `HOUST` | fixed | Get US Housing Starts from FRED |
| `fred_new_home_sales` | `HSN1F` | fixed | Get US New Home Sales from FRED |


## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "fred_custom_series", "arguments": {"series_id": "UNRATE", "limit": 24}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "fred_custom_series", "arguments": {"series_id": "UNRATE", "limit": 24}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("fred_custom_series", series_id="UNRATE", limit=24)
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
