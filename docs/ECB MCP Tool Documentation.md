# ECB MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The ECB MCP Tool provides comprehensive access to European Central Bank data including monetary policy rates, economic indicators, exchange rates, and financial statistics for the Euro area.

## Configuration
- No API key required
- Uses ECB Statistical Data Warehouse (SDW) REST API
- Automatic data formatting and aggregation

## Available Methods

### Monetary Policy & Interest Rates

#### 1. get_key_interest_rates
Retrieves all ECB key interest rates.

**Returns:**
- Main refinancing operations rate
- Deposit facility rate
- Marginal lending facility rate
- Current date

#### 2. get_deposit_facility_rate
Gets ECB deposit facility rate history.

**Parameters:**
- `lastNObservations` (optional): Number of recent observations
- `startPeriod` (optional): Start date
- `endPeriod` (optional): End date

#### 3. get_main_refinancing_rate
Gets main refinancing operations rate.

**Parameters:**
- Same as deposit facility rate

#### 4. get_marginal_lending_rate
Gets marginal lending facility rate.

**Parameters:**
- Same as deposit facility rate

#### 5. get_euribor
Gets EURIBOR rates for various tenors.

**Parameters:**
- `tenor` (default: '3M'): '1W', '1M', '3M', '6M', or '12M'
- Standard date parameters

#### 6. get_ester
Gets €STR (Euro short-term rate).

**Parameters:**
- Standard date parameters

#### 7. get_money_market_rates
Gets various money market rates.

**Parameters:**
- `rate_type` (default: 'overnight'): 'overnight', 'tom_next', 'spot_next', '1_week', '1_month'

#### 8. get_yield_curves
Gets Euro area yield curves.

**Parameters:**
- `curve_type` (default: 'spot'): 'spot', 'forward', or 'par'

**Returns:**
- Yields for maturities from 1Y to 30Y

#### 9. get_forward_rates
Gets forward interest rates.

### Economic Indicators

#### 10. get_hicp_inflation
Gets Harmonised Index of Consumer Prices (HICP).

**Parameters:**
- `component` (default: 'all_items'): 'all_items', 'energy', 'food', 'core', 'services'
- Standard date parameters

#### 11. get_core_inflation
Gets core inflation excluding energy and unprocessed food.

#### 12. get_gdp_data
Gets Euro area GDP data.

**Parameters:**
- `gdp_type` (default: 'growth_rate'): 'growth_rate', 'level', 'per_capita'

#### 13. get_unemployment
Gets Euro area unemployment rate.

**Parameters:**
- `demographic` (default: 'total'): 'total', 'youth', 'male', 'female'

#### 14. get_industrial_production
Gets industrial production index.

**Parameters:**
- `sector` (default: 'total'): 'total', 'manufacturing', 'energy', 'construction'

#### 15. get_retail_sales
Gets retail sales data.

#### 16. get_confidence_indicators
Gets confidence indicators.

**Parameters:**
- `indicator` (default: 'consumer'): 'consumer', 'business', 'economic_sentiment'

#### 17. get_economic_sentiment
Gets Economic Sentiment Indicator.

### Exchange Rates

#### 18. get_euro_exchange_rates
Gets EUR exchange rates against major currencies.

**Parameters:**
- `currency` (default: 'USD'): 'USD', 'GBP', 'JPY', 'CHF', 'CNY', 'AUD', 'CAD'

#### 19. get_effective_exchange_rates
Gets Euro effective exchange rates.

**Parameters:**
- `eer_type` (default: 'nominal'): 'nominal', 'real_cpi', 'real_ppi'

#### 20. get_reference_rates
Gets ECB reference exchange rates for multiple currencies.

#### 21. get_currency_cross_rates
Gets cross rates between major currencies.

**Parameters:**
- `cross` (default: 'GBP_USD'): 'GBP_USD', 'USD_JPY', 'GBP_JPY'

### Government Securities & Bonds

#### 22. get_government_bond_yields
Gets government bond yields for Euro area countries.

**Parameters:**
- `country` (default: 'DE'): Country code
- `maturity` (default: '10Y'): Bond maturity

#### 23. get_sovereign_spreads
Gets sovereign spreads vs German Bunds.

**Parameters:**
- `country` (default: 'IT'): Country code

#### 24. get_yield_curve_euro_area
Gets Euro area AAA-rated yield curve.

**Returns:**
- Yields from 3M to 30Y maturities
- AAA rating specification

#### 25. get_corporate_bond_yields
Gets corporate bond yields by rating.

**Parameters:**
- `rating` (default: 'AA'): 'AAA', 'AA', 'A', 'BBB'

### Banking & Financial System

#### 26. get_bank_balance_sheets
Gets aggregated bank balance sheet data.

**Parameters:**
- `item` (default: 'total_assets'): 'total_assets', 'loans', 'deposits', 'equity'

#### 27. get_bank_lending_rates
Gets bank lending rates.

**Parameters:**
- `loan_type` (default: 'corporate'): 'corporate', 'household_mortgage', 'consumer'

#### 28. get_bank_deposit_rates
Gets bank deposit rates.

**Parameters:**
- `deposit_type` (default: 'household'): 'household', 'corporate', 'overnight'

#### 29. get_bank_lending_survey
Gets Bank Lending Survey results.

**Parameters:**
- `indicator` (default: 'credit_standards'): 'credit_standards', 'demand', 'terms_conditions'

#### 30. get_monetary_aggregates
Gets monetary aggregates (M1, M2, M3).

**Parameters:**
- `aggregate` (default: 'M3'): 'M1', 'M2', 'M3'

#### 31. get_credit_growth
Gets credit growth to private sector.

**Parameters:**
- `sector` (default: 'total'): 'total', 'households', 'corporations'

#### 32. get_npl_ratios
Gets non-performing loans ratios.

#### 33. get_bank_profitability
Gets bank profitability indicators.

**Parameters:**
- `indicator` (default: 'roe'): 'roe', 'roa', 'cost_income'

### Financial Markets

#### 34. get_equity_indices
Gets Euro area equity indices.

**Parameters:**
- `index` (default: 'eurostoxx50'): 'eurostoxx50', 'eurostoxx600', 'dax', 'cac40', 'ftse_mib'

#### 35. get_stock_market_data
Gets stock market data by country.

**Parameters:**
- `market` (default: 'euro_area'): 'euro_area', 'germany', 'france', 'italy', 'spain'

#### 36. get_securities_issues
Gets securities issuance data.

**Parameters:**
- `security_type` (default: 'bonds'): 'bonds', 'equities', 'short_term'

### Country-Specific Data

#### 37. get_country_inflation
Gets inflation data for specific Euro area country.

**Parameters:**
- `country` (default: 'DE'): Country code

#### 38. get_country_gdp
Gets GDP data for specific country.

#### 39. get_country_unemployment
Gets unemployment rate for specific country.

#### 40. get_country_debt
Gets government debt for specific country.

#### 41. get_country_deficit
Gets government deficit for specific country.

#### 42. get_country_current_account
Gets current account for specific country.

### Labor Market

#### 43. get_employment_data
Gets Euro area employment data.

#### 44. get_wage_growth
Gets wage growth data.

#### 45. get_unit_labor_costs
Gets unit labor costs.

#### 46. get_productivity
Gets labor productivity data.

#### 47. get_job_vacancies
Gets job vacancy rate.

### Trade & Balance of Payments

#### 48. get_trade_balance
Gets trade balance data.

#### 49. get_exports
Gets export data.

#### 50. get_imports
Gets import data.

#### 51. get_current_account
Gets current account balance.

#### 52. get_foreign_direct_investment
Gets foreign direct investment data.

#### 53. get_portfolio_investment
Gets portfolio investment data.

### Housing & Real Estate

#### 54. get_house_prices
Gets house price indices.

#### 55. get_residential_property
Gets residential property price indices.

#### 56. get_commercial_property
Gets commercial property price indices.

#### 57. get_construction_output
Gets construction output data.

#### 58. get_building_permits
Gets building permits data.

### Fiscal Policy

#### 59. get_government_debt
Gets government debt statistics.

#### 60. get_budget_balance
Gets government budget balance.

#### 61. get_government_expenditure
Gets government expenditure data.

#### 62. get_tax_revenue
Gets tax revenue data.

### Financial Stability

#### 63. get_systemic_risk_indicators
Gets systemic risk indicators.

#### 64. get_financial_stress_index
Gets financial stress index.

#### 65. get_macroprudential_measures
Gets macroprudential policy measures.

### Surveys & Expectations

#### 66. get_survey_of_professional_forecasters
Gets Survey of Professional Forecasters results.

**Parameters:**
- `variable` (default: 'inflation'): 'inflation', 'gdp', 'unemployment'

#### 67. get_consumer_expectations
Gets consumer expectations survey data.

#### 68. get_inflation_expectations
Gets inflation expectations from various sources.

**Parameters:**
- `source` (default: 'market'): 'market' or 'survey'

### Climate & Sustainable Finance

#### 69. get_green_bonds
Gets green bond statistics.

#### 70. get_climate_indicators
Gets climate-related financial indicators.

### Historical Data & Research

#### 71. get_historical_statistics
Gets historical economic statistics.

**Parameters:**
- `series`: Series identifier
- `dataset`: Dataset identifier
- `startPeriod` (optional): Start date (default: 1999-01)

#### 72. get_long_term_statistics
Gets long-term statistical series.

**Parameters:**
- `series_type` (default: 'interest_rates'): 'interest_rates', 'inflation', 'gdp', 'unemployment'

#### 73. search_series
Searches for ECB data series.

**Parameters:**
- `search_term`: Search query

#### 74. get_series_metadata
Gets metadata for specific series.

**Parameters:**
- `dataset`: Dataset identifier
- `series_key`: Series identifier

## Data Structure

All methods return standardized response format:
```json
{
  "dataset": "dataset_identifier",
  "series_key": "series_identifier", 
  "metadata": {
    "name": "Series name",
    "dimensions": {...}
  },
  "latest_value": 1.23,
  "latest_period": "2024-01",
  "observations": [
    {"period": "2024-01", "value": 1.23}
  ],
  "changes": [
    {"period": "2024-01", "change_pct": 0.5}
  ],
  "count": 100
}
```

## Country Codes
- DE: Germany
- FR: France
- IT: Italy
- ES: Spain
- NL: Netherlands
- BE: Belgium
- AT: Austria
- PT: Portugal
- GR: Greece
- IE: Ireland
- FI: Finland

## Example Usage
```python
# Get key ECB rates
result = ecb_tool.handle_tool_call('get_key_interest_rates', {})

# Get inflation data
result = ecb_tool.handle_tool_call('get_hicp_inflation', {
    'component': 'core',
    'lastNObservations': 12
})

# Get country-specific data
result = ecb_tool.handle_tool_call('get_country_gdp', {
    'country': 'DE',
    'startPeriod': '2020-01'
})
```


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.