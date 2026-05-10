# FRED (Federal Reserve Economic Data) — Tool Reference Guide

**Version:** 3.1.0 · **Tools:** 55 · **API Key Required:** Yes (`fred.api.key` in `config/application.yml`)

---

## Overview

SAJHA provides 55 FRED tools covering interest rates, Treasury yields, inflation, GDP, employment, housing, commodities, money supply, and more. 30 named tools map to specific FRED series IDs, plus `fred_custom_series` for querying any FRED series by ID.

**API Key:** Get a free key at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html). Set in `config/application.yml`:

```yaml
fred:
  api:
    key: ${FRED_API_KEY:your-key-here}
```

## Tool Categories

### Interest Rates & Yields (8 tools)

`fred_fed_funds_rate`, `fred_prime_rate`, `fred_2yr_treasury`, `fred_5yr_treasury`, `fred_10yr_treasury`, `fred_30yr_treasury`, `fred_30yr_mortgage`, `fred_real_interest_rate`

### GDP & Growth (3 tools)

`fred_gdp`, `fred_gdp_growth`, `fred_real_gdp_per_capita`

### Inflation & Prices (3 tools)

`fred_cpi`, `fred_core_cpi`, `fred_pce`, `fred_ppi`

### Employment (4 tools)

`fred_unemployment`, `fred_nonfarm_payrolls`, `fred_initial_claims`, `fred_continuing_claims`, `fred_labor_force`, `fred_avg_hourly_earnings`

### Commodities (7 tools)

`fred_oil_price`, `fred_natural_gas`, `fred_gold_price`, `fred_silver_price`, `fred_copper_price`, `fred_corn_price`, `fred_wheat_price`

### Market Indicators (5 tools)

`fred_sp500`, `fred_vix`, `fred_dollar_index`, `fred_high_yield_spread`, `fred_credit_spread`, `fred_breakeven_inflation`, `fred_yield_spread`

### Economic Indicators (10 tools)

`fred_industrial_production`, `fred_capacity_utilization`, `fred_retail_sales`, `fred_durable_goods`, `fred_consumer_sentiment`, `fred_consumer_credit`, `fred_personal_income`, `fred_real_personal_income`, `fred_trade_balance`, `fred_leading_index`, `fred_pmi`

### Housing (3 tools)

`fred_housing_starts`, `fred_building_permits`, `fred_existing_home_sales`, `fred_new_home_sales`

### Monetary (3 tools)

`fred_m2_money_supply`, `fred_national_debt`, `fred_auto_sales`, `fred_business_inventories`

### Custom Series (1 tool)

`fred_custom_series` — Query any FRED series by its series ID:

```json
{"series_id": "UNRATE", "start_date": "2020-01-01", "end_date": "2024-12-31"}
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
