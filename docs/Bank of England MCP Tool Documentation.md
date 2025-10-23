# Bank of England MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Bank of England MCP Tool provides access to UK economic data including interest rates, financial statistics, housing market data, and regional economic indicators.

## Configuration
- No API key required
- Uses Bank of England Statistical Interactive Database API
- Data available from 1694 for some historical series

## Available Methods

### Monetary Policy & Interest Rates

#### 1. get_bank_rate
Gets Bank of England Bank Rate (policy rate).

**Parameters:**
- `datefrom` (optional): Start date
- `dateto` (optional): End date
- `limit` (default: 30): Number of observations

#### 2. get_sonia
Gets Sterling Overnight Index Average (SONIA).

#### 3. get_repo_rate
Gets repo rate.

#### 4. get_term_sonia
Gets Term SONIA reference rates.
**Parameters:**
- `term` (default: '3M'): '1M', '3M', '6M', or '12M'

#### 5. get_swap_rates
Gets interest rate swap rates.
**Parameters:**
- `maturity` (default: '5Y'): '1Y', '2Y', '3Y', '5Y', '7Y', '10Y'

#### 6. get_overnight_index_swaps
Gets Overnight Index Swap rates.

#### 7. get_forward_rates
Gets forward interest rates.
**Parameters:**
- `horizon` (default: '1Y'): '1Y', '2Y', '5Y'

#### 8. get_real_interest_rates
Gets real (inflation-adjusted) interest rates.

### Economic Indicators

#### 9. get_inflation_data
Gets UK inflation data.
**Parameters:**
- `measure` (default: 'cpi'): 'cpi', 'cpih', 'rpi', 'core_cpi'

#### 10. get_cpi_data
Gets Consumer Price Index data.

#### 11. get_rpi_data
Gets Retail Price Index data.

#### 12. get_gdp_data
Gets UK GDP data.
**Parameters:**
- `gdp_type` (default: 'growth'): 'growth', 'level', 'per_capita'

#### 13. get_unemployment
Gets UK unemployment rate.

#### 14. get_wage_growth
Gets wage growth data.
**Parameters:**
- `measure` (default: 'average_weekly'): 'average_weekly', 'regular_pay', 'total_pay'

#### 15. get_productivity
Gets productivity data.

#### 16. get_output_gap
Gets output gap estimates.

#### 17. get_retail_sales
Gets retail sales data.

### Exchange Rates

#### 18. get_sterling_exchange_rates
Gets Sterling exchange rates.
**Parameters:**
- `currency` (default: 'USD'): 'USD', 'EUR', 'JPY', 'CHF', 'CAD', 'AUD', 'CNY'

#### 19. get_effective_exchange_rates
Gets Sterling effective exchange rates.
**Parameters:**
- `eer_type` (default: 'nominal'): 'nominal' or 'real'

#### 20. get_spot_rates
Gets spot exchange rates.

#### 21. get_forward_exchange_rates
Gets forward exchange rates.
**Parameters:**
- `currency` (default: 'USD')
- `tenor` (default: '1M')

#### 22. get_currency_volatility
Gets currency volatility measures.
**Parameters:**
- `currency` (default: 'USD')

### Government Securities & Gilts

#### 23. get_gilt_yields
Gets UK government bond (gilt) yields.
**Parameters:**
- `maturity` (default: '10Y'): '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'

#### 24. get_gilt_prices
Gets gilt prices.

#### 25. get_index_linked_gilts
Gets index-linked gilt yields.
**Parameters:**
- `maturity` (default: '10Y'): '5Y', '10Y', '20Y'

#### 26. get_gilt_issuance
Gets gilt issuance data.

#### 27. get_yield_curve
Gets complete UK yield curve with spreads.

#### 28. get_treasury_bills
Gets Treasury Bill rates.

### Banking & Financial System

#### 29. get_bank_lending
Gets bank lending data.

#### 30. get_mortgage_lending
Gets mortgage lending data.

#### 31. get_consumer_credit
Gets consumer credit data.

#### 32. get_deposit_rates
Gets deposit interest rates.
**Parameters:**
- `deposit_type` (default: 'household'): 'household', 'corporate', 'instant_access', 'fixed_rate'

#### 33. get_lending_rates
Gets lending interest rates.
**Parameters:**
- `loan_type` (default: 'mortgage'): 'mortgage', 'personal_loan', 'credit_card', 'overdraft'

#### 34. get_credit_conditions
Gets credit conditions from surveys.

#### 35. get_bank_capital_ratios
Gets bank capital ratios.
**Parameters:**
- `ratio_type` (default: 'tier1'): 'tier1', 'cet1', 'total_capital'

#### 36. get_bank_stress_tests
Gets bank stress test results.

### Money Supply & Credit

#### 37. get_money_supply
Gets money supply data.
**Parameters:**
- `aggregate` (default: 'M4'): 'M0', 'M4', 'M4_lending'

#### 38. get_broad_money
Gets broad money (M4) growth.

#### 39. get_credit_growth
Gets credit growth to private sector.

#### 40. get_sectoral_lending
Gets lending by sector.
**Parameters:**
- `sector` (default: 'household'): 'household', 'pnfc', 'financial', 'real_estate'

#### 41. get_lending_to_smes
Gets lending to small and medium enterprises.

### Financial Markets

#### 42. get_ftse_indices
Gets FTSE index data.
**Parameters:**
- `index` (default: 'ftse100'): 'ftse100', 'ftse250', 'ftse_all_share'

#### 43. get_equity_prices
Gets equity price indices.

#### 44. get_corporate_bond_spreads
Gets corporate bond spreads.
**Parameters:**
- `rating` (default: 'investment_grade'): 'investment_grade', 'high_yield', 'aaa'

#### 45. get_sterling_money_markets
Gets sterling money market data.

#### 46. get_derivatives_data
Gets derivatives market data.

### Housing Market

#### 47. get_house_prices
Gets UK house price indices.
**Parameters:**
- `index_type` (default: 'nationwide'): 'nationwide', 'halifax', 'land_registry'

#### 48. get_mortgage_approvals
Gets mortgage approval numbers.

#### 49. get_mortgage_rates
Gets mortgage interest rates.
**Parameters:**
- `mortgage_type` (default: 'variable'): 'variable', 'fixed_2y', 'fixed_3y', 'fixed_5y'

#### 50. get_buy_to_let
Gets buy-to-let mortgage data.

#### 51. get_housing_transactions
Gets housing transaction volumes.

#### 52. get_rental_yields
Gets rental yield data.

### External Sector

#### 53. get_current_account
Gets current account balance.

#### 54. get_trade_balance
Gets trade balance.

#### 55. get_exports
Gets export data.

#### 56. get_imports
Gets import data.

#### 57. get_foreign_investment
Gets foreign direct investment data.

#### 58. get_uk_investment_abroad
Gets UK investment abroad data.

### Regional Data

#### 59. get_regional_gdp
Gets regional GDP data.
**Parameters:**
- `region` (default: 'london')

#### 60. get_regional_unemployment
Gets regional unemployment rates.
**Parameters:**
- `region` (default: 'london'): london, southeast, southwest, eastanglia, eastmidlands, westmidlands, yorkshire, northwest, north, wales, scotland, ni

#### 61. get_regional_house_prices
Gets regional house price data.
**Parameters:**
- `region` (default: 'london')

#### 62. get_regional_lending
Gets regional lending data.
**Parameters:**
- `region` (default: 'london')

### Business Conditions

#### 63. get_agents_scores
Gets Bank of England Agents' summary scores.
**Parameters:**
- `indicator` (default: 'demand')

#### 64. get_business_investment
Gets business investment data.

#### 65. get_corporate_profitability
Gets corporate profitability indicators.

#### 66. get_company_liquidations
Gets company liquidation statistics.

#### 67. get_credit_availability
Gets credit availability indicators.

### Financial Stability

#### 68. get_systemic_risk_survey
Gets Systemic Risk Survey results.

#### 69. get_financial_stability_indicators
Gets financial stability indicators.

#### 70. get_countercyclical_buffer
Gets countercyclical capital buffer rate.

#### 71. get_leverage_ratio
Gets leverage ratio requirements.

#### 72. get_liquidity_coverage
Gets liquidity coverage ratio data.

### Surveys & Expectations

#### 73. get_inflation_expectations
Gets inflation expectations from various sources.
**Parameters:**
- `source` (default: 'market'): 'market', 'survey', 'professional'

#### 74. get_inflation_attitudes_survey
Gets Inflation Attitudes Survey results.

#### 75. get_credit_conditions_survey
Gets Credit Conditions Survey results.

#### 76. get_bank_liabilities_survey
Gets Bank Liabilities Survey results.

#### 77. get_mpc_minutes
Gets Monetary Policy Committee meeting minutes.

### Quantitative Easing & Balance Sheet

#### 78. get_asset_purchase_facility
Gets Asset Purchase Facility data.

#### 79. get_qe_holdings
Gets quantitative easing holdings.
**Parameters:**
- `asset_type` (default: 'gilts'): 'gilts', 'corporate_bonds'

#### 80. get_bank_reserves
Gets bank reserves at Bank of England.

#### 81. get_balance_sheet
Gets Bank of England balance sheet.
**Parameters:**
- `item` (default: 'total_assets'): 'total_assets', 'liabilities', 'notes_in_circulation', 'reserve_balances'

#### 82. get_term_funding_scheme
Gets Term Funding Scheme data.

### Historical Data

#### 83. get_historical_bank_rate
Gets historical Bank Rate from 1694.
**Parameters:**
- `datefrom` (default: '1694-01-01')

#### 84. get_historical_exchange_rates
Gets historical exchange rates.
**Parameters:**
- `datefrom` (default: '1975-01-01')

#### 85. get_historical_inflation
Gets historical inflation data.
**Parameters:**
- `datefrom` (default: '1988-01-01')

#### 86. get_long_run_data
Gets long-run economic data (centuries).
**Parameters:**
- `dataset` (default: 'interest_rates'): 'interest_rates', 'prices', 'gdp', 'money_supply'

### Payment Systems

#### 87. get_chaps_volumes
Gets CHAPS payment system volumes.

#### 88. get_faster_payments
Gets Faster Payments Service statistics.

#### 89. get_rtgs_statistics
Gets RTGS (Real-Time Gross Settlement) statistics.

#### 90. get_payment_statistics
Gets payment system statistics.
**Parameters:**
- `system` (default: 'all'): 'all', 'chaps', 'faster_payments'

### Brexit & EU

#### 91. get_brexit_uncertainty_index
Gets Brexit uncertainty index.

#### 92. get_eu_trade_statistics
Gets EU trade statistics.

#### 93. get_financial_services_trade
Gets financial services trade statistics.

### Climate & ESG

#### 94. get_climate_risk_indicators
Gets climate-related financial risk indicators.

#### 95. get_green_bonds
Gets green bond issuance and holdings.

#### 96. get_transition_indicators
Gets climate transition risk indicators.

### Search & Metadata

#### 97. search_series
Searches for Bank of England data series.
**Parameters:**
- `search_term`: Search query

#### 98. get_series_metadata
Gets metadata for specific series.
**Parameters:**
- `series_code`: Series identifier

#### 99. get_data_availability
Gets information about data availability.

## Example Usage
```python
# Get Bank Rate
result = boe_tool.handle_tool_call('get_bank_rate', {
    'limit': 10
})

# Get gilt yields
result = boe_tool.handle_tool_call('get_gilt_yields', {
    'maturity': '10Y'
})

# Get regional unemployment
result = boe_tool.handle_tool_call('get_regional_unemployment', {
    'region': 'london'
})
```


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.