# Central Banks MCP Tools Suite - Comprehensive Documentation

## © 2025-2030 Ashutosh Sinha

## Overview

We have built a comprehensive suite of MCP (Model Context Protocol) tools for accessing economic and financial data from four major central banks:

1. **Federal Reserve (Fed)** - United States
2. **Bank of Canada (BoC)** - Canada  
3. **European Central Bank (ECB)** - Eurozone
4. **Bank of England (BoE)** - United Kingdom

## Tool Statistics

| Central Bank | Number of Tools | Data Categories | API Used | API Key Required |
|-------------|-----------------|-----------------|----------|------------------|
| Federal Reserve | 68 tools | 12 categories | FRED API | Yes (FRED_API_KEY) |
| Bank of Canada | 67 tools | 11 categories | Valet API | No |
| European Central Bank | 63 tools | 14 categories | SDW API | No |
| Bank of England | 65 tools | 15 categories | IADB API | No |

## Comparative Tool Mapping

### 1. Policy Interest Rates

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_interest_rates` | `get_policy_rate` | `get_key_interest_rates` | `get_bank_rate` |
| Federal Funds Rate | Overnight Rate | Deposit Facility Rate | Bank Rate |
| SOFR | CORRA | €STR | SONIA |
| | CDOR | EURIBOR | Term SONIA |

### 2. Inflation Measures

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_inflation_data` | `get_cpi_data` | `get_hicp_inflation` | `get_inflation_data` |
| CPI | CPI | HICP | CPI/CPIH/RPI |
| PCE | Core CPI | Core HICP | Core CPI |
| `get_inflation_expectations` | `get_consumer_expectations` | `get_inflation_expectations` | `get_inflation_expectations` |

### 3. GDP & Economic Growth

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_gdp_data` | `get_gdp_data` | `get_gdp_data` | `get_gdp_data` |
| `get_gdp_components` | `get_gdp_by_industry` | `get_country_gdp` | `get_regional_gdp` |
| Real/Nominal GDP | Monthly/Quarterly GDP | Growth Rate/Level | Growth/Level/Per Capita |

### 4. Labor Market

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_unemployment_data` | `get_unemployment_rate` | `get_unemployment` | `get_unemployment` |
| `get_employment_data` | `get_employment_data` | `get_employment_data` | `get_wage_growth` |
| `get_job_openings` (JOLTS) | `get_job_vacancies` | `get_job_vacancies` | `get_productivity` |
| `get_wage_growth` | `get_wage_growth` | `get_wage_growth` | |

### 5. Exchange Rates

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_exchange_rates` | `get_exchange_rates` | `get_euro_exchange_rates` | `get_sterling_exchange_rates` |
| `get_dollar_index` | `get_cad_usd` | `get_effective_exchange_rates` | `get_effective_exchange_rates` |
| Trade-weighted | CERI | Nominal/Real EER | Nominal/Real EER |

### 6. Government Bonds & Yields

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_treasury_yields` | `get_government_bonds` | `get_government_bond_yields` | `get_gilt_yields` |
| `get_yield_curve` | `get_yield_curve` | `get_yield_curve_euro_area` | `get_yield_curve` |
| TIPS | Real Return Bonds | Index-linked bonds | Index-linked gilts |
| `get_term_spreads` | `get_bond_spreads` | `get_sovereign_spreads` | |

### 7. Money Supply & Credit

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_money_supply` | `get_money_supply` | `get_monetary_aggregates` | `get_money_supply` |
| M1/M2 | M1+/M2/M3 | M1/M2/M3 | M0/M4 |
| `get_credit_growth` | `get_credit_growth` | `get_credit_growth` | `get_credit_growth` |

### 8. Banking System

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_bank_lending_standards` | `get_senior_loan_officer_survey` | `get_bank_lending_survey` | `get_credit_conditions_survey` |
| `get_banking_statistics` | `get_chartered_bank_assets` | `get_bank_balance_sheets` | `get_bank_capital_ratios` |
| `get_consumer_credit` | `get_consumer_credit` | `get_bank_lending_rates` | `get_consumer_credit` |

### 9. Housing Market

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_housing_starts` | `get_housing_starts` | `get_house_prices` | `get_house_prices` |
| `get_home_prices` | `get_housing_prices` | `get_residential_property` | `get_mortgage_approvals` |
| `get_mortgage_rates` | `get_mortgage_rates` | | `get_mortgage_rates` |

### 10. Financial Stability

| Federal Reserve | Bank of Canada | ECB | Bank of England |
|----------------|----------------|-----|-----------------|
| `get_financial_stress_index` | `get_financial_stress_index` | `get_systemic_risk_indicators` | `get_systemic_risk_survey` |
| `get_systemic_risk_indicators` | `get_systemic_risk_indicators` | `get_financial_stress_index` | `get_countercyclical_buffer` |
| | | `get_macroprudential_measures` | `get_leverage_ratio` |

## Unique Features by Central Bank

### Federal Reserve
- **FOMC Tools**: Projections, dot plots, meeting minutes
- **Regional Fed Data**: All 12 Federal Reserve districts
- **Historical Data**: Some series from 1954
- **Specialized**: Taylor Rule, Natural Rate (r-star)

### Bank of Canada
- **Provincial Data**: All 10 provinces coverage
- **Business Outlook Survey**: Quarterly business conditions
- **Commodity Price Index**: Bank's own commodity index
- **Payment Systems**: LVTS, Lynx, ACSS

### European Central Bank
- **Multi-country**: Individual Eurozone country data
- **Banking Union**: Comprehensive banking supervision data
- **TARGET2**: Cross-border payment system statistics
- **Climate Finance**: Green bonds and ESG indicators

### Bank of England
- **Historical Depth**: Data from 1694 for some series
- **Brexit Indicators**: Uncertainty indices and trade impacts
- **Agents' Scores**: Regional economic intelligence
- **Asset Purchase Facility**: Detailed QE program data

## Cross-Central Bank Analysis Examples

### 1. Global Policy Rate Comparison
```python
# Compare policy rates across all major central banks
fed_rate = fed_tool.handle_tool_call("get_interest_rates", {"rate_type": "federal_funds"})
boc_rate = boc_tool.handle_tool_call("get_policy_rate", {})
ecb_rate = ecb_tool.handle_tool_call("get_deposit_facility_rate", {})
boe_rate = boe_tool.handle_tool_call("get_bank_rate", {})
```

### 2. Inflation Comparison
```python
# Compare inflation across regions
us_cpi = fed_tool.handle_tool_call("get_inflation_data", {"inflation_type": "cpi"})
can_cpi = boc_tool.handle_tool_call("get_cpi_data", {})
euro_hicp = ecb_tool.handle_tool_call("get_hicp_inflation", {})
uk_cpi = boe_tool.handle_tool_call("get_cpi_data", {})
```

### 3. Yield Curve Analysis
```python
# Get yield curves from all regions
us_curve = fed_tool.handle_tool_call("get_yield_curve", {})
can_curve = boc_tool.handle_tool_call("get_yield_curve", {})
euro_curve = ecb_tool.handle_tool_call("get_yield_curve_euro_area", {})
uk_curve = boe_tool.handle_tool_call("get_yield_curve", {})
```

### 4. Exchange Rate Triangulation
```python
# USD as base
eur_usd = ecb_tool.handle_tool_call("get_euro_exchange_rates


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.