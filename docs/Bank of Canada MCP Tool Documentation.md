# Bank of Canada MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Bank of Canada MCP Tool provides access to Canadian economic and financial data through the Bank of Canada Valet API.

## Configuration
- No API key required
- Uses Bank of Canada Valet API
- Real-time exchange rates updated daily
- Historical data available from 1935 for some series

## Available Methods

### Interest Rates & Monetary Policy

#### 1. get_policy_rate
Gets Bank of Canada policy interest rate (target for overnight rate).

#### 2. get_overnight_rate
Gets overnight money market financing rate.

#### 3. get_bank_rate
Gets Bank of Canada bank rate.

#### 4. get_prime_rate
Gets chartered bank prime business rate.

#### 5. get_corra
Gets Canadian Overnight Repo Rate Average (CORRA).

#### 6. get_cdor
Gets Canadian Dollar Offered Rate (CDOR).
**Parameters:**
- `term` (default: '3M'): '1M', '2M', '3M', '6M', '12M'

#### 7. get_ba_rates
Gets Bankers' Acceptances rates.
**Parameters:**
- `term` (default: '3M'): '1M', '3M', '6M'

#### 8. get_treasury_bills
Gets Treasury Bill rates.
**Parameters:**
- `term` (default: '3M'): '1M', '3M', '6M', '12M'

#### 9. get_monetary_conditions
Gets monetary conditions index components.

#### 10. get_lvts_data
Gets Large Value Transfer System data.

### Economic Indicators

#### 11. get_gdp_data
Gets Canadian GDP data.
**Parameters:**
- `gdp_type` (default: 'monthly'): 'monthly', 'quarterly', 'real', 'nominal'

#### 12. get_gdp_by_industry
Gets GDP by industry.
**Parameters:**
- `industry` (default: 'all'): 'all', 'manufacturing', 'construction', 'retail', 'finance'

#### 13. get_cpi_data
Gets Consumer Price Index data.
**Parameters:**
- `cpi_type` (default: 'all_items'): 'all_items', 'ex_food_energy', 'goods', 'services'

#### 14. get_core_inflation
Gets Bank of Canada core inflation measures.
**Parameters:**
- `measure` (default: 'cpi_trim'): 'cpi_trim', 'cpi_median', 'cpi_common'

#### 15. get_inflation_targets
Gets inflation target information.

#### 16. get_output_gap
Gets output gap estimates.

#### 17. get_potential_output
Gets potential output estimates.

### Exchange Rates

#### 18. get_exchange_rates
Gets foreign exchange rates.
**Parameters:**
- `currency` (default: 'USD'): 'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'MXN', 'AUD', 'INR'

#### 19. get_cad_usd
Gets CAD/USD exchange rate with additional details.

#### 20. get_effective_exchange_rate
Gets Canadian-dollar effective exchange rate index (CERI).

#### 21. get_currency_cross_rates
Gets cross rates between major currencies.
**Parameters:**
- `cross` (default: 'EUR_USD'): 'EUR_USD', 'GBP_USD', 'USD_JPY'

#### 22. get_closing_rates
Gets closing exchange rates.
**Parameters:**
- `currency` (default: 'USD')

### Canadian Bonds & Securities

#### 23. get_government_bonds
Gets Government of Canada bond yields.
**Parameters:**
- `maturity` (default: '10Y'): '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '30Y'

#### 24. get_yield_curve
Gets complete Canadian yield curve.

#### 25. get_real_return_bonds
Gets Real Return Bond yields.

#### 26. get_provincial_bonds
Gets provincial bond yields.
**Parameters:**
- `province` (default: 'ON'): 'ON', 'QC', 'BC', 'AB'

#### 27. get_corporate_bonds
Gets corporate bond yields.

#### 28. get_bond_spreads
Gets bond spreads.
**Parameters:**
- `spread_type` (default: 'corporate_government')

### Labor Market

#### 29. get_employment_data
Gets employment data.

#### 30. get_unemployment_rate
Gets unemployment rate.

#### 31. get_job_vacancies
Gets job vacancy data.

#### 32. get_wage_growth
Gets wage growth data.
**Parameters:**
- `measure` (default: 'average_hourly'): 'average_hourly', 'seph', 'wage_common'

#### 33. get_hours_worked
Gets hours worked data.

#### 34. get_labour_force
Gets labour force statistics.

#### 35. get_employment_by_province
Gets employment by province.
**Parameters:**
- `province` (default: 'ON'): 'ON', 'QC', 'BC', 'AB', 'MB', 'SK', 'NS', 'NB', 'NL', 'PE'

#### 36. get_employment_by_industry
Gets employment by industry.
**Parameters:**
- `industry` (default: 'total'): 'total', 'goods', 'services', 'manufacturing', 'construction', 'retail', 'finance'

### Banking & Financial System

#### 37. get_chartered_bank_assets
Gets chartered bank assets.

#### 38. get_bank_deposits
Gets bank deposits.
**Parameters:**
- `deposit_type` (default: 'total'): 'total', 'personal', 'non_personal', 'demand', 'notice', 'fixed_term'

#### 39. get_bank_loans
Gets bank loans.
**Parameters:**
- `loan_type` (default: 'total'): 'total', 'business', 'residential_mortgage', 'consumer'

#### 40. get_mortgage_credit
Gets mortgage credit data.

#### 41. get_consumer_credit
Gets consumer credit data.

#### 42. get_business_credit
Gets business credit data.

#### 43. get_money_supply
Gets money supply data.
**Parameters:**
- `aggregate` (default: 'M2'): 'M1+', 'M1++', 'M2', 'M2+', 'M2++', 'M3'

#### 44. get_financial_institutions_data
Gets financial institutions data.

#### 45. get_payment_systems
Gets payment systems data.
**Parameters:**
- `system` (default: 'lvts'): 'lvts', 'acss', 'lynx'

### Housing Market

#### 46. get_housing_starts
Gets housing starts data.

#### 47. get_housing_prices
Gets housing price indices.
**Parameters:**
- `index_type` (default: 'new_house'): 'new_house', 'crea_hpi', 'teranet'

#### 48. get_mls_data
Gets MLS home sales data.

#### 49. get_mortgage_rates
Gets mortgage interest rates.
**Parameters:**
- `mortgage_type` (default: '5Y_fixed'): '1Y_fixed', '3Y_fixed', '5Y_fixed', 'variable'

#### 50. get_housing_affordability
Gets housing affordability index.

#### 51. get_rental_market
Gets rental market data.

#### 52. get_construction_data
Gets construction activity data.

### Trade & International

#### 53. get_trade_balance
Gets trade balance data.

#### 54. get_exports
Gets export data.

#### 55. get_imports
Gets import data.

#### 56. get_current_account
Gets current account data.

#### 57. get_international_investment
Gets international investment position.

#### 58. get_commodity_prices
Gets Bank of Canada commodity price index.
**Parameters:**
- `commodity` (default: 'total'): 'total', 'energy', 'non_energy', 'metals', 'forestry', 'agriculture'

#### 59. get_energy_prices
Gets energy price data.
**Parameters:**
- `energy_type` (default: 'oil'): 'oil', 'natural_gas', 'electricity'

### Business & Industry

#### 60. get_business_outlook_survey
Gets Business Outlook Survey indicators.
**Parameters:**
- `indicator` (default: 'future_sales'): 'future_sales', 'investment', 'employment', 'inflation'

#### 61. get_senior_loan_officer_survey
Gets Senior Loan Officer Survey results.

#### 62. get_capacity_utilization
Gets capacity utilization rates.

#### 63. get_industrial_production
Gets industrial production index.

#### 64. get_manufacturing_sales
Gets manufacturing sales.

#### 65. get_retail_sales
Gets retail sales data.

#### 66. get_wholesale_trade
Gets wholesale trade data.

#### 67. get_business_investment
Gets business investment data.

### Consumer & Household

#### 68. get_consumer_confidence
Gets consumer confidence index.

#### 69. get_household_debt
Gets household debt data.

#### 70. get_household_wealth
Gets household net worth data.

#### 71. get_savings_rate
Gets household savings rate.

#### 72. get_disposable_income
Gets household disposable income.

#### 73. get_consumer_spending
Gets consumer spending data.

### Provincial & Regional Data

#### 74. get_provincial_gdp
Gets provincial GDP data.
**Parameters:**
- `province` (default: 'ON'): 'ON', 'QC', 'BC', 'AB'

#### 75. get_provincial_employment
Gets provincial employment data.

#### 76. get_provincial_cpi
Gets provincial CPI data.
**Parameters:**
- `province` (default: 'ON')

#### 77. get_provincial_retail
Gets provincial retail sales.
**Parameters:**
- `province` (default: 'ON')

#### 78. get_major_cities_data
Gets economic data for major cities.
**Parameters:**
- `city` (default: 'toronto'): 'toronto', 'montreal', 'vancouver', 'calgary'
- `data_type` (default: 'cpi')

### Financial Markets

#### 79. get_tsx_data
Gets TSX index data.

#### 80. get_equity_indices
Gets Canadian equity indices.
**Parameters:**
- `index` (default: 'tsx_composite'): 'tsx_composite', 'tsx_60', 'tsx_venture'

#### 81. get_derivatives_data
Gets derivatives market data.

#### 82. get_foreign_exchange_volume
Gets foreign exchange trading volume.

### Financial Stability

#### 83. get_financial_system_review
Gets Financial System Review information.

#### 84. get_systemic_risk_indicators
Gets systemic risk indicators.

#### 85. get_credit_conditions
Gets credit conditions assessment.

#### 86. get_financial_stress_index
Gets Canadian financial stress index.

### Surveys & Projections

#### 87. get_monetary_policy_report
Gets Monetary Policy Report information.

#### 88. get_consumer_expectations
Gets Canadian Survey of Consumer Expectations.
**Parameters:**
- `indicator` (default: 'inflation_1y'): 'inflation_1y', 'inflation_2y', 'inflation_5y'

#### 89. get_market_expectations
Gets market expectations for policy rate.

#### 90. get_staff_projections
Gets Bank of Canada staff economic projections.

### Historical Data

#### 91. get_historical_statistics
Gets historical statistics.
**Parameters:**
- `statistic` (default: 'policy_rate'): 'policy_rate', 'inflation', 'gdp'
- `start_date` (default: '1935-01-01')

#### 92. get_historical_exchange_rates
Gets historical exchange rates.
**Parameters:**
- `start_date` (default: '1950-01-01')

#### 93. get_historical_interest_rates
Gets historical interest rates.
**Parameters:**
- `start_date` (default: '1935-01-01')

### Search & Metadata

#### 94. search_series
Searches for Bank of Canada data series.
**Parameters:**
- `search_term`: Search query

#### 95. get_series_metadata
Gets metadata for a specific series.
**Parameters:**
- `series_name`: Series identifier

#### 96. get_data_availability
Gets information about data availability.

## Example Usage
```python
# Get policy rate
result = boc_tool.handle_tool_call('get_policy_rate', {})

# Get CAD/USD exchange rate
result = boc_tool.handle_tool_call('get_cad_usd', {})

# Get housing data
result = boc_tool.handle_tool_call('get_housing_starts', {})
```


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.