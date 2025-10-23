# Federal Reserve MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Federal Reserve MCP Tool provides comprehensive access to US economic and financial data through the FRED (Federal Reserve Economic Data) API.

## Configuration
- **Environment Variables:**
  - `FRED_API_KEY`: Required for accessing FRED data
- Over 800,000 economic time series available
- Historical data dating back to 1800s for some series

## Available Methods

### Interest Rates & Monetary Policy

#### 1. get_interest_rates
Get comprehensive Federal interest rates.
**Parameters:**
- `rate_type` (default: 'federal_funds'): 'federal_funds', 'federal_funds_target', 'prime', 'discount', 'sofr', 'obfr', 'iorb', 'ioer'

#### 2. get_real_interest_rates
Get real (inflation-adjusted) interest rates.
**Parameters:**
- `rate_type` (default: '10Y'): '5Y', '10Y', 'federal_funds'

#### 3. get_term_spreads
Get term spreads (yield curve indicators).
**Parameters:**
- `spread_type` (default: '10Y2Y'): '10Y2Y', '10Y3M', '5Y2Y', '30Y5Y'

#### 4. get_fomc_projections
Get FOMC economic projections.
**Parameters:**
- `projection_type` (default: 'federal_funds')

#### 5. get_fomc_statements
Get FOMC statements and minutes.

#### 6. get_policy_tools
Get Fed policy tools data.
**Parameters:**
- `tool_type` (default: 'balance_sheet'): 'balance_sheet', 'reserve_balances', 'securities_held'

#### 7. get_reverse_repo
Get reverse repo operations data.
**Parameters:**
- `data_type` (default: 'volume'): 'volume', 'rate', 'counterparties'

#### 8. get_standing_repo
Get standing repo facility data.

### Economic Indicators

#### 9. get_economic_series
Get any economic series data.
**Parameters:**
- `series_id`: FRED series identifier

#### 10. get_gdp_data
Get GDP data.
**Parameters:**
- `gdp_type` (default: 'real'): 'real' or 'nominal'

#### 11. get_gdp_components
Get GDP components breakdown.
**Parameters:**
- `component_type` (default: 'all'): 'all', 'consumption', 'investment', 'government', 'net_exports'

#### 12. get_inflation_data
Get inflation data.
**Parameters:**
- `inflation_type` (default: 'cpi'): 'cpi', 'cpi_yoy', 'pce', 'core_cpi', 'core_pce'

#### 13. get_inflation_expectations
Get inflation expectations.
**Parameters:**
- `horizon` (default: '5Y'): '1Y', '5Y', '10Y', 'michigan_1Y', 'michigan_5Y10'

#### 14. get_pce_components
Get PCE inflation components.
**Parameters:**
- `component` (default: 'core'): 'headline', 'core', 'goods', 'services', 'energy', 'food'

### Labor Market

#### 15. get_unemployment_data
Get unemployment data.

#### 16. get_employment_data
Get employment data by sector.
**Parameters:**
- `employment_type` (default: 'nonfarm'): 'nonfarm', 'private', 'government', 'manufacturing', 'construction', 'retail', etc.

#### 17. get_labor_force_participation
Get labor force participation rates.
**Parameters:**
- `demographic` (default: 'total'): 'total', 'prime_age', 'women', 'men', 'teens', 'over_55'

#### 18. get_job_openings
Get JOLTS job openings data.
**Parameters:**
- `data_type` (default: 'openings'): 'openings', 'hires', 'quits', 'layoffs'

#### 19. get_wage_growth
Get wage growth data.
**Parameters:**
- `wage_type` (default: 'average_hourly'): 'average_hourly', 'atlanta_fed_tracker', 'eci_total', 'eci_wages'

#### 20. get_initial_claims
Get unemployment claims data.
**Parameters:**
- `claims_type` (default: 'initial'): 'initial', 'continuing', '4week_average'

#### 21. get_productivity_data
Get labor productivity data.
**Parameters:**
- `measure` (default: 'productivity'): 'productivity', 'unit_labor_costs', 'output_per_hour'

### Financial Markets

#### 22. get_treasury_yields
Get Treasury yields.
**Parameters:**
- `maturity` (default: '10Y'): '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'

#### 23. get_yield_curve
Get complete yield curve.

#### 24. get_tips_spreads
Get TIPS breakeven inflation rates.
**Parameters:**
- `maturity` (default: '10Y'): '5Y', '10Y', '30Y'

#### 25. get_corporate_spreads
Get corporate bond spreads.
**Parameters:**
- `grade` (default: 'investment_grade'): 'investment_grade', 'high_yield', 'bbb', 'ccc'

#### 26. get_stock_market_indicators
Get stock market indicators.
**Parameters:**
- `indicator` (default: 'sp500'): 'sp500', 'dow', 'nasdaq', 'russell2000', 'wilshire5000'

#### 27. get_volatility_indices
Get volatility indices.
**Parameters:**
- `index` (default: 'vix'): 'vix', 'vxn', 'rvx', 'move'

#### 28. get_exchange_rates
Get exchange rates.
**Parameters:**
- `currency` (default: 'eur'): 'eur', 'gbp', 'jpy', 'cny', 'cad', 'mxn', 'aud'

#### 29. get_dollar_index
Get US Dollar Index.
**Parameters:**
- `index_type` (default: 'trade_weighted'): 'trade_weighted', 'major_currencies', 'broad'

### Banking & Credit

#### 30. get_money_supply
Get money supply data.
**Parameters:**
- `supply_type` (default: 'm2'): 'm1' or 'm2'

#### 31. get_banking_statistics
Get banking statistics.
**Parameters:**
- `stat_type` (default: 'reserves'): 'reserves', 'loans', 'deposits', 'assets'

#### 32. get_bank_lending_standards
Get bank lending standards.
**Parameters:**
- `loan_type` (default: 'commercial'): 'commercial', 'consumer', 'mortgage', 'small_business'

#### 33. get_consumer_credit
Get consumer credit data.
**Parameters:**
- `credit_type` (default: 'total'): 'total', 'revolving', 'nonrevolving', 'auto', 'student'

#### 34. get_mortgage_rates
Get mortgage rates.
**Parameters:**
- `mortgage_type` (default: '30Y_fixed'): '30Y_fixed', '15Y_fixed', '5Y_arm', 'jumbo'

#### 35. get_credit_card_rates
Get credit card interest rates.

#### 36. get_auto_loan_rates
Get auto loan rates.

#### 37. get_commercial_paper
Get commercial paper rates.
**Parameters:**
- `paper_type` (default: 'financial'): 'financial', 'nonfinancial', 'asset_backed'

#### 38. get_bank_failures
Get bank failure data.

### Housing Market

#### 39. get_housing_starts
Get housing starts data.
**Parameters:**
- `data_type` (default: 'starts'): 'starts', 'permits', 'completions', 'under_construction'

#### 40. get_home_prices
Get home price indices.
**Parameters:**
- `index_type` (default: 'case_shiller'): 'case_shiller', 'fhfa', 'median_price', 'price_rent_ratio'

#### 41. get_existing_home_sales
Get existing home sales data.
**Parameters:**
- `metric` (default: 'sales'): 'sales', 'inventory', 'months_supply', 'median_days'

#### 42. get_new_home_sales
Get new home sales data.

#### 43. get_construction_spending
Get construction spending data.

#### 44. get_homeownership_rate
Get homeownership rate.

### Industrial & Manufacturing

#### 45. get_industrial_production
Get industrial production.
**Parameters:**
- `sector` (default: 'total'): 'total', 'manufacturing', 'mining', 'utilities', 'tech'

#### 46. get_capacity_utilization
Get capacity utilization.
**Parameters:**
- `sector` (default: 'total'): 'total', 'manufacturing', 'mining'

#### 47. get_manufacturing_data
Get manufacturing indicators.
**Parameters:**
- `indicator` (default: 'pmi'): 'pmi', 'new_orders', 'shipments'

#### 48. get_durable_goods
Get durable goods orders.

#### 49. get_factory_orders
Get factory orders.

#### 50. get_business_inventories
Get business inventories.

### Consumer & Retail

#### 51. get_retail_sales
Get retail sales data.
**Parameters:**
- `category` (default: 'total'): 'total', 'ex_auto', 'ex_gas', 'core', 'online', 'restaurants'

#### 52. get_consumer_sentiment
Get consumer sentiment.
**Parameters:**
- `survey` (default: 'michigan'): 'michigan', 'conference_board', 'expectations', 'current'

#### 53. get_personal_income
Get personal income data.
**Parameters:**
- `component` (default: 'total'): 'total', 'wages', 'disposable', 'real_disposable'

#### 54. get_personal_spending
Get personal consumption expenditures.
**Parameters:**
- `category` (default: 'total'): 'total', 'goods', 'services', 'durable', 'nondurable'

#### 55. get_savings_rate
Get personal savings rate.

#### 56. get_household_debt
Get household debt data.
**Parameters:**
- `debt_type` (default: 'total'): 'total', 'mortgage', 'consumer'

### Trade & International

#### 57. get_trade_balance
Get trade balance data.
**Parameters:**
- `measure` (default: 'balance'): 'balance', 'goods', 'services'

#### 58. get_exports
Get export data.

#### 59. get_imports
Get import data.

#### 60. get_current_account
Get current account data.

#### 61. get_foreign_holdings
Get foreign holdings of US securities.

### Regional Fed Data

#### 62. get_regional_fed_data
Get regional Federal Reserve data.
**Parameters:**
- `region` (default: 'new_york'): 'boston', 'new_york', 'philadelphia', 'cleveland', etc.
- `data_type` (default: 'activity_index')

#### 63. get_beige_book
Get Beige Book information.

#### 64. get_state_unemployment
Get state-level unemployment data.
**Parameters:**
- `state` (default: 'CA'): State code

#### 65. get_metro_area_data
Get metropolitan area economic data.
**Parameters:**
- `metro` (default: 'NYC'): 'NYC', 'LA', 'CHI'
- `data_type` (default: 'unemployment')

### Financial Stability

#### 66. get_financial_stress_index
Get financial stress indices.
**Parameters:**
- `index_type` (default: 'stlfsi'): 'stlfsi', 'nfci', 'vix', 'move'

#### 67. get_systemic_risk_indicators
Get systemic risk indicators.
**Parameters:**
- `indicator` (default: 'srisk')

#### 68. get_leverage_ratios
Get financial sector leverage ratios.

#### 69. get_liquidity_indicators
Get market liquidity indicators.
**Parameters:**
- `indicator` (default: 'bid_ask')

### Historical & Research

#### 70. search_series
Search for economic series.
**Parameters:**
- `search_text`: Search query

#### 71. get_series_metadata
Get detailed series metadata.
**Parameters:**
- `series_id`: Series identifier

#### 72. get_vintage_data
Get vintage data for a series.
**Parameters:**
- `series_id`: Series identifier
- `vintage_date`: Vintage date

#### 73. get_recession_dates
Get NBER recession dates.

#### 74. get_historical_rates
Get historical interest rates.
**Parameters:**
- `rate_type` (default: 'federal_funds'): 'federal_funds', 'discount', '10Y_treasury'
- `start_date` (default: '1954-07-01')

### Specialized Indicators

#### 75. get_term_premia
Get term premium estimates.
**Parameters:**
- `maturity` (default: '10Y'): '5Y', '10Y'

#### 76. get_natural_rate
Get natural rate of interest (r-star).

#### 77. get_output_gap
Get output gap estimates.

#### 78. get_taylor_rule
Get Taylor Rule implied rate.
**Parameters:**
- `version` (default: 'original')

#### 79. get_financial_conditions
Get financial conditions indices.
**Parameters:**
- `index` (default: 'nfci'): 'nfci', 'anfci', 'nfci_leverage', 'nfci_credit'

#### 80. get_credit_spreads
Get various credit spreads.
**Parameters:**
- `spread_type` (default: 'baa_treasury'): 'baa_treasury', 'aaa_treasury', 'ted_spread'

#### 81. get_commodity_prices
Get commodity price indices.
**Parameters:**
- `commodity` (default: 'all'): 'all', 'energy', 'metals', 'agriculture', 'gold', 'oil'

#### 82. get_energy_prices
Get energy price data.
**Parameters:**
- `energy_type` (default: 'oil'): 'oil', 'gas', 'natural_gas', 'electricity'

## Example Usage
```python
# Get federal funds rate
result = fed_tool.handle_tool_call('get_interest_rates', {
    'rate_type': 'federal_funds'
})

# Get GDP components
result = fed_tool.handle_tool_call('get_gdp_components', {
    'component_type': 'all'
})

# Search for series
result = fed_tool.handle_tool_call('search_series', {
    'search_text': 'unemployment rate'
})
```


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.