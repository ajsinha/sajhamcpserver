# Reserve Bank of India (RBI) MCP Tools - Complete Documentation


**Copyright All rights reserved 2025-2030 Ashutosh Sinha**  
**Email: ajsinha@gmail.com**


## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Available Tools](#available-tools)
5. [Detailed Tool Reference](#detailed-tool-reference)
6. [Code Examples](#code-examples)
7. [API Reference](#api-reference)
8. [Common Use Cases](#common-use-cases)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The Reserve Bank of India (RBI) MCP Tools provide comprehensive access to Indian economic and financial data through the RBI's Database on Indian Economy (DBIE) API. These tools enable you to retrieve:

- **Government Securities (G-Sec) Yields**: Access yield data for 1-year, 5-year, 10-year, and 30-year bonds
- **Policy Rates**: Repo rate, reverse repo rate, bank rate, CRR, and SLR
- **Exchange Rates**: INR exchange rates against USD, EUR, GBP, and JPY
- **Inflation Data**: CPI, WPI, and core CPI
- **Foreign Exchange Reserves**: India's forex reserves tracking

### Key Features

✅ **Real-time Data**: Access latest Indian economic indicators
✅ **Policy Insights**: Track RBI monetary policy decisions
✅ **Comprehensive Coverage**: Wide range of economic data
✅ **Historical Analysis**: Retrieve data with customizable date ranges
✅ **Standardized Format**: Consistent JSON output across all tools

---


## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Client Application                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ MCP Protocol
                     │
┌────────────────────▼────────────────────────────────────┐
│              MCP Tool Layer (5 Tools)                    │
├──────────────────────────────────────────────────────────┤
│  • rbi_get_policy_rate    (Repo/Reverse Repo Rates)      │
│  • rbi_get_inflation      (CPI/WPI Data)                 │
│  • rbi_get_exchange_rate  (INR Exchange Rates)           │
│  • rbi_get_gsec_yield     (G-Sec Bond Yields)            │
│  • rbi_get_forex_reserves (Foreign Exchange Reserves)    │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│          RBIBaseTool (Shared Functionality)              │
├──────────────────────────────────────────────────────────┤
│  • RBI Database Integration                              │
│  • Data Transformation & Parsing                         │
│  • Error Handling & Logging                              │
│  • Response Normalization                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│          Reserve Bank of India Data Portal               │
│           https://www.rbi.org.in/                        │
└──────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Request    │───▶│  Tool Layer  │───▶│   RBI API    │
│  (indicator) │    │  (validate)  │    │   (fetch)    │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                    │
                           ▼                    │
                    ┌──────────────┐            │
                    │   Response   │◀───────────┘
                    │  (normalize) │
                    └──────────────┘
```

---

## Quick Start

### Installation

```python
from tools.impl.india_central_bank import RESERVE_BANK_OF_INDIA_TOOLS

# Initialize a tool
gsec_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_gsec_yield']()

# Execute with arguments
result = gsec_tool.execute({
    'bond_term': '10y',
    'recent_periods': 30
})

print(f"Latest 10-year G-Sec yield: {result['observations'][-1]['value']}%")
```

### Quick Example: Get Latest Repo Rate

```python
policy_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_policy_rate']()
result = policy_tool.execute({
    'rate_type': 'repo_rate',
    'recent_periods': 1
})
print(f"Repo Rate: {result['observations'][0]['value']}%")
```

---

## Available Tools

| Tool Name | Purpose | Key Parameters |
|-----------|---------|----------------|
| `rbi_get_gsec_yield` | G-Sec yield curves | bond_term (1y, 5y, 10y, 30y) |
| `rbi_get_policy_rate` | RBI policy rates | rate_type (repo_rate, reverse_repo_rate, etc.) |
| `rbi_get_exchange_rate` | INR forex rates | currency_pair (usd_inr, eur_inr, etc.) |
| `rbi_get_inflation` | Inflation indices | index_type (cpi, wpi, core_cpi) |
| `rbi_get_forex_reserves` | Forex reserves | N/A (time series only) |

---

## Detailed Tool Reference

### 1. rbi_get_gsec_yield

**Purpose**: Retrieve Indian Government Securities yields across different maturities.

**Input Parameters**:
```json
{
  "bond_term": "10y",         // Required: "1y", "5y", "10y", or "30y"
  "start_date": "2024-01-01", // Optional: YYYY-MM-DD format
  "end_date": "2024-12-31",   // Optional: YYYY-MM-DD format
  "recent_periods": 30        // Optional: 1-100 (default: 10)
}
```

**Output Schema**:
```json
{
  "series_code": "GSEC_10Y",
  "label": "10-Year Government Securities Yield",
  "description": "Benchmark 10-year G-Sec yield",
  "unit": "Percentage",
  "observation_count": 30,
  "observations": [
    {
      "date": "2024-11-01",
      "value": 7.15
    }
  ]
}
```

**Use Cases**:
- Fixed income investment decisions
- Sovereign debt analysis
- Yield curve construction
- Interest rate forecasting
- Economic policy assessment

---

### 2. rbi_get_policy_rate

**Purpose**: Access RBI's key policy rates and reserve requirements.

**Input Parameters**:
```json
{
  "rate_type": "repo_rate",   // Required: see options below
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Rate Types**:
- **repo_rate**: Repurchase rate (main policy rate)
- **reverse_repo_rate**: Reverse repurchase rate
- **bank_rate**: Bank lending rate
- **crr**: Cash Reserve Ratio
- **slr**: Statutory Liquidity Ratio

**Use Cases**:
- Monetary policy analysis
- Banking sector research
- Credit market forecasting
- Investment strategy planning
- Economic commentary

---

### 3. rbi_get_exchange_rate

**Purpose**: Access INR exchange rates against major global currencies.

**Input Parameters**:
```json
{
  "currency_pair": "usd_inr",  // Required: "usd_inr", "eur_inr", "gbp_inr", "jpy_inr"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Currency Pairs**:
- **USD/INR**: US Dollar per Indian Rupee
- **EUR/INR**: Euro per Indian Rupee
- **GBP/INR**: British Pound per Indian Rupee
- **JPY/INR**: Japanese Yen per Indian Rupee

**Use Cases**:
- Foreign exchange trading
- Import/export cost analysis
- International investment valuation
- Remittance planning
- Currency hedging strategies

---

### 4. rbi_get_inflation

**Purpose**: Retrieve Indian inflation and price indices.

**Input Parameters**:
```json
{
  "index_type": "cpi",         // Required: "cpi", "wpi", or "core_cpi"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Index Types**:
- **cpi**: Consumer Price Index (all items)
- **wpi**: Wholesale Price Index (all commodities)
- **core_cpi**: Core CPI (excluding food and fuel)

**Use Cases**:
- Inflation tracking and forecasting
- Real return calculations
- Wage negotiations
- Policy evaluation
- Investment strategy adjustments

---

### 5. rbi_get_forex_reserves

**Purpose**: Track India's foreign exchange reserves.

**Input Parameters**:
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 52  // Weekly data
}
```

**Use Cases**:
- External sector monitoring
- Currency stability assessment
- Import cover analysis
- Sovereign credit analysis
- Macroeconomic research

---

## Code Examples

### Example 1: Monetary Policy Dashboard

```python
from tools.impl.india_central_bank import RESERVE_BANK_OF_INDIA_TOOLS
import pandas as pd

# Initialize tools
policy_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_policy_rate']()
gsec_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_gsec_yield']()

# Get latest policy rates
repo = policy_tool.execute({'rate_type': 'repo_rate', 'recent_periods': 1})
reverse_repo = policy_tool.execute({'rate_type': 'reverse_repo_rate', 'recent_periods': 1})
crr = policy_tool.execute({'rate_type': 'crr', 'recent_periods': 1})
slr = policy_tool.execute({'rate_type': 'slr', 'recent_periods': 1})

# Get 10-year G-Sec yield
gsec_10y = gsec_tool.execute({'bond_term': '10y', 'recent_periods': 1})

# Display dashboard
print("=" * 50)
print("RBI MONETARY POLICY DASHBOARD")
print("=" * 50)
print(f"Repo Rate:         {repo['observations'][0]['value']}%")
print(f"Reverse Repo Rate: {reverse_repo['observations'][0]['value']}%")
print(f"CRR:               {crr['observations'][0]['value']}%")
print(f"SLR:               {slr['observations'][0]['value']}%")
print(f"10Y G-Sec Yield:   {gsec_10y['observations'][0]['value']}%")
print("=" * 50)
```

### Example 2: Inflation Analysis

```python
from tools.impl.india_central_bank import RESERVE_BANK_OF_INDIA_TOOLS
import matplotlib.pyplot as plt
import pandas as pd

inflation_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_inflation']()

# Get 2 years of CPI and WPI data
cpi_data = inflation_tool.execute({
    'index_type': 'cpi',
    'start_date': '2022-11-01',
    'end_date': '2024-10-31'
})

wpi_data = inflation_tool.execute({
    'index_type': 'wpi',
    'start_date': '2022-11-01',
    'end_date': '2024-10-31'
})

# Convert to DataFrames
cpi_df = pd.DataFrame(cpi_data['observations'])
wpi_df = pd.DataFrame(wpi_data['observations'])

# Plot comparison
plt.figure(figsize=(12, 6))
plt.plot(pd.to_datetime(cpi_df['date']), cpi_df['value'], label='CPI', marker='o')
plt.plot(pd.to_datetime(wpi_df['date']), wpi_df['value'], label='WPI', marker='s')
plt.title('India Inflation Trends: CPI vs WPI')
plt.xlabel('Date')
plt.ylabel('Index Value')
plt.legend()
plt.grid(True)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

### Example 3: Currency Basket Tracking

```python
from tools.impl.india_central_bank import RESERVE_BANK_OF_INDIA_TOOLS
import pandas as pd

fx_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_exchange_rate']()

# Track multiple currencies
currencies = ['usd_inr', 'eur_inr', 'gbp_inr', 'jpy_inr']
latest_rates = {}

for currency in currencies:
    result = fx_tool.execute({
        'currency_pair': currency,
        'recent_periods': 1
    })
    latest_rates[currency] = result['observations'][0]['value']

# Display currency basket
print("\nINDIAN RUPEE EXCHANGE RATES")
print("-" * 40)
for pair, rate in latest_rates.items():
    print(f"{pair.upper():15s}: {rate:10.4f}")
```

### Example 4: Forex Reserves Monitoring

```python
from tools.impl.india_central_bank import RESERVE_BANK_OF_INDIA_TOOLS
import pandas as pd

reserves_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_forex_reserves']()

# Get 1 year of weekly data
result = reserves_tool.execute({
    'start_date': '2023-11-01',
    'end_date': '2024-10-31'
})

# Convert to DataFrame
df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df['value'] = df['value'] / 1000  # Convert to billions

# Calculate statistics
print(f"Forex Reserves Analysis (in USD Billion)")
print(f"Average: ${df['value'].mean():.2f}B")
print(f"Current: ${df['value'].iloc[-1]:.2f}B")
print(f"Peak:    ${df['value'].max():.2f}B")
print(f"Low:     ${df['value'].min():.2f}B")
print(f"Change (YoY): ${(df['value'].iloc[-1] - df['value'].iloc[0]):.2f}B")
```

---

## Common Use Cases

### 1. Bond Investment Strategy

**Objective**: Evaluate G-Sec investment opportunities across yield curve

```python
gsec_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_gsec_yield']()

maturities = ['1y', '5y', '10y', '30y']
yields = []

for maturity in maturities:
    result = gsec_tool.execute({'bond_term': maturity, 'recent_periods': 1})
    yields.append(result['observations'][0]['value'])

# Calculate spreads
spread_5y_1y = yields[1] - yields[0]
spread_10y_5y = yields[2] - yields[1]

print(f"5Y-1Y Spread: {spread_5y_1y:.2f} bps")
print(f"10Y-5Y Spread: {spread_10y_5y:.2f} bps")
```

### 2. Real Interest Rate Calculation

**Objective**: Calculate real returns after inflation

```python
policy_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_policy_rate']()
inflation_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_inflation']()

# Get repo rate and CPI
repo = policy_tool.execute({'rate_type': 'repo_rate', 'recent_periods': 1})
cpi = inflation_tool.execute({'index_type': 'cpi', 'recent_periods': 12})

# Calculate YoY inflation
latest_cpi = cpi['observations'][-1]['value']
year_ago_cpi = cpi['observations'][0]['value']
inflation_rate = ((latest_cpi / year_ago_cpi) - 1) * 100

# Calculate real rate
nominal_rate = repo['observations'][0]['value']
real_rate = nominal_rate - inflation_rate

print(f"Nominal Repo Rate: {nominal_rate:.2f}%")
print(f"Inflation Rate: {inflation_rate:.2f}%")
print(f"Real Interest Rate: {real_rate:.2f}%")
```

### 3. Import Cost Analysis

**Objective**: Track USD/INR for import planning

```python
fx_tool = RESERVE_BANK_OF_INDIA_TOOLS['rbi_get_exchange_rate']()

# Get 6 months of USD/INR data
result = fx_tool.execute({
    'currency_pair': 'usd_inr',
    'start_date': '2024-05-01',
    'end_date': '2024-10-31'
})

df = pd.DataFrame(result['observations'])
df['value'] = pd.to_numeric(df['value'])

# Import cost calculation
import_value_usd = 1000000  # $1 million
avg_rate = df['value'].mean()
total_cost_inr = import_value_usd * avg_rate

print(f"Import Value: ${import_value_usd:,.0f}")
print(f"Average USD/INR: {avg_rate:.4f}")
print(f"Total Cost: ₹{total_cost_inr:,.2f}")
print(f"Rate Volatility: {df['value'].std():.4f}")
```

---

## API Reference

### Common Response Format

```json
{
  "series_code": "string",
  "label": "string",
  "description": "string",
  "unit": "string",
  "frequency": "string",
  "observation_count": integer,
  "observations": [
    {
      "date": "YYYY-MM-DD",
      "value": number or null
    }
  ]
}
```

### Error Handling

```python
try:
    result = gsec_tool.execute({'bond_term': '10y'})
except ValueError as e:
    print(f"Invalid parameter: {e}")
except ConnectionError as e:
    print(f"Network error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## Troubleshooting

### Common Issues

1. **Rate Limit Exceeded**
   - Solution: Implement caching and space out requests
   - Default limit: 120 requests/hour

2. **Data Not Available**
   - Some series may have publishing delays
   - Check RBI website for data release schedules

3. **Date Format Errors**
   - Always use YYYY-MM-DD format
   - Validate dates before making requests

### Best Practices

1. Cache frequently accessed data
2. Handle exceptions gracefully
3. Validate input parameters
4. Monitor API usage metrics
5. Use appropriate date ranges

---

## Support and Resources

### Official Resources

- **RBI Website**: https://www.rbi.org.in/
- **Database on Indian Economy**: https://dbie.rbi.org.in/
- **RBI Publications**: https://www.rbi.org.in/Scripts/Publications.aspx

### Technical Support

- Email: ajsinha@gmail.com
- GitHub: [Project Repository]

---
---
# Legal Notice & License

### Copyright

**Copyright © 2025-2030 Ashutosh Sinha. All Rights Reserved.**

This software and documentation are protected by copyright law. Unauthorized reproduction or distribution of this software, or any portion of it, may result in severe civil and criminal penalties, and will be prosecuted to the maximum extent possible under law.

### License Terms

This software is provided "as is" without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement.

**Permitted Use:**
- ✅ Personal research and analysis
- ✅ Academic research
- ✅ Internal business use
- ✅ Non-commercial applications

**Restrictions:**
- ❌ Redistribution without permission
- ❌ Commercial sale or licensing
- ❌ Modification without attribution
- ❌ Removal of copyright notices

### Disclaimer

**THIS TOOLKIT IS FOR INFORMATIONAL AND RESEARCH PURPOSES ONLY.**

The author and contributors:
- ❌ Do NOT provide investment advice
- ❌ Do NOT provide financial advice
- ❌ Do NOT provide legal advice
- ❌ Do NOT provide accounting advice
- ❌ Make NO warranties about data accuracy
- ❌ Accept NO liability for investment decisions

**Users acknowledge:**
- All investment decisions are their own responsibility
- Data may contain errors or be outdated
- Professional advice should be sought for important decisions
- SEC filings are the authoritative source
- This toolkit is a convenience tool, not a substitute for due diligence

