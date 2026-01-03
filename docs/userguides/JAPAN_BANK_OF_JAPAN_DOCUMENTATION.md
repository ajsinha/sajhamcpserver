# Bank of Japan (BoJ) MCP Tools - Complete Documentation


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

The Bank of Japan (BoJ) MCP Tools provide comprehensive access to Japanese economic and financial data through the Bank of Japan's Time-Series Data Search API. These tools enable you to retrieve:

- **Japanese Government Bond (JGB) Yields**: Access yield data for 2-year, 5-year, 10-year, and 30-year JGBs
- **Exchange Rates**: JPY exchange rates against USD, EUR, GBP, and CNY
- **Policy Rates**: BoJ policy interest rates and discount rates
- **Money Stock**: M1, M2, and M3 monetary aggregates
- **Price Indices**: Consumer Price Index (CPI) and Producer Price Index (PPI)

### Key Features

✅ **Real-time Data**: Access latest Japanese economic indicators
✅ **Historical Analysis**: Retrieve data with customizable date ranges
✅ **Flexible Queries**: Query by specific periods or recent observations
✅ **Standardized Format**: Consistent JSON output across all tools
✅ **High Reliability**: Built on official BoJ APIs

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
│  • boj_get_policy_rate   (Policy Balance Rate)           │
│  • boj_get_jgb_yield     (JGB Yields)                    │
│  • boj_get_exchange_rate (JPY Exchange Rates)            │
│  • boj_get_money_stock   (Money Stock M1/M2/M3)          │
│  • boj_get_price_index   (CPI/CGPI Data)                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│          BOJBaseTool (Shared Functionality)              │
├──────────────────────────────────────────────────────────┤
│  • BOJ Time-Series API Integration                       │
│  • Data Transformation & Parsing                         │
│  • Error Handling & Logging                              │
│  • Response Normalization                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│             Bank of Japan Statistics                     │
│         https://www.stat-search.boj.or.jp/               │
└──────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Request    │───▶│  Tool Layer  │───▶│   BOJ API    │
│  (series)    │    │  (validate)  │    │   (fetch)    │
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
from tools.impl.japan_central_bank import BANK_OF_JAPAN_TOOLS

# Initialize a tool
jgb_tool = BANK_OF_JAPAN_TOOLS['boj_get_jgb_yield']()

# Execute with arguments
result = jgb_tool.execute({
    'bond_term': '10y',
    'recent_periods': 30
})

print(f"Latest 10-year JGB yield: {result['observations'][-1]['value']}%")
```

### Quick Example: Get Latest USD/JPY Exchange Rate

```python
fx_tool = BANK_OF_JAPAN_TOOLS['boj_get_exchange_rate']()
result = fx_tool.execute({
    'currency_pair': 'usd_jpy',
    'recent_periods': 1
})
print(f"USD/JPY: {result['observations'][0]['value']}")
```

---

## Available Tools

| Tool Name | Purpose | Key Parameters |
|-----------|---------|----------------|
| `boj_get_jgb_yield` | JGB yield curves | bond_term (2y, 5y, 10y, 30y) |
| `boj_get_exchange_rate` | JPY forex rates | currency_pair (usd_jpy, eur_jpy, etc.) |
| `boj_get_policy_rate` | BoJ policy rates | rate_type (policy_rate, discount_rate) |
| `boj_get_money_stock` | Monetary aggregates | aggregate (m1, m2, m3) |
| `boj_get_price_index` | Inflation data | index_type (cpi, core_cpi, ppi) |

---

## Detailed Tool Reference

### 1. boj_get_jgb_yield

**Purpose**: Retrieve Japanese Government Bond yields across different maturities.

**Input Parameters**:
```json
{
  "bond_term": "10y",        // Required: "2y", "5y", "10y", or "30y"
  "start_date": "2024-01-01", // Optional: YYYY-MM-DD format
  "end_date": "2024-12-31",   // Optional: YYYY-MM-DD format
  "recent_periods": 30        // Optional: 1-100 (default: 10)
}
```

**Output Schema**:
```json
{
  "series_code": "FM08_D_1_5_1",
  "label": "10-Year JGB Yield",
  "description": "Benchmark 10-year Japanese Government Bond yield",
  "unit": "Percentage",
  "observation_count": 30,
  "observations": [
    {
      "date": "2024-11-01",
      "value": 1.05
    }
  ]
}
```

**Series Codes**:
- 2-year: `FM08_D_1_3_1`
- 5-year: `FM08_D_1_4_1`
- 10-year: `FM08_D_1_5_1`
- 30-year: `FM08_D_1_9_1`

**Use Cases**:
- Yield curve analysis
- Fixed income portfolio management
- Carry trade strategy development
- Interest rate risk assessment
- Global macro trading

---

### 2. boj_get_exchange_rate

**Purpose**: Access JPY exchange rates against major global currencies.

**Input Parameters**:
```json
{
  "currency_pair": "usd_jpy",  // Required: "usd_jpy", "eur_jpy", "gbp_jpy", "cny_jpy"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Output Schema**:
```json
{
  "series_code": "FM02_D_1_1",
  "label": "USD/JPY Exchange Rate",
  "observation_count": 10,
  "observations": [
    {
      "date": "2024-11-01",
      "value": 150.25
    }
  ]
}
```

**Currency Pairs**:
- USD/JPY: US Dollar per Japanese Yen
- EUR/JPY: Euro per Japanese Yen
- GBP/JPY: British Pound per Japanese Yen
- CNY/JPY: Chinese Yuan (100 yuan) per Japanese Yen

**Use Cases**:
- Currency trading and analysis
- International portfolio valuation
- Hedging foreign exchange risk
- Trade flow analysis
- Tourism and travel planning

---

### 3. boj_get_policy_rate

**Purpose**: Retrieve Bank of Japan policy interest rates.

**Input Parameters**:
```json
{
  "rate_type": "policy_rate",  // Required: "policy_rate" or "discount_rate"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Rate Types**:
- **policy_rate**: Uncollateralized overnight call rate (main policy tool)
- **discount_rate**: Basic discount rate and basic loan rate

**Use Cases**:
- Monetary policy analysis
- Interest rate forecasting
- Bond trading strategies
- Economic research
- Financial planning

---

### 4. boj_get_money_stock

**Purpose**: Access Japanese money supply aggregates.

**Input Parameters**:
```json
{
  "aggregate": "m2",  // Required: "m1", "m2", or "m3"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Aggregates**:
- **M1**: Currency in circulation + Demand deposits
- **M2**: M1 + Quasi-money + CDs
- **M3**: M2 + Deposits at post offices + Other

**Use Cases**:
- Monetary policy evaluation
- Inflation forecasting
- Economic growth analysis
- Banking sector research
- Credit conditions assessment

---

### 5. boj_get_price_index

**Purpose**: Retrieve Japanese inflation and price data.

**Input Parameters**:
```json
{
  "index_type": "cpi",  // Required: "cpi", "core_cpi", or "ppi"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Index Types**:
- **cpi**: Consumer Price Index (nationwide, all items)
- **core_cpi**: CPI excluding fresh food
- **ppi**: Producer Price Index

**Use Cases**:
- Inflation tracking
- Real return calculations
- Purchasing power analysis
- Wage negotiation research
- Economic policy evaluation

---

## Code Examples

### Example 1: Yield Curve Analysis

```python
from tools.impl.japan_central_bank import BANK_OF_JAPAN_TOOLS
import matplotlib.pyplot as plt

# Initialize tool
jgb_tool = BANK_OF_JAPAN_TOOLS['boj_get_jgb_yield']()

# Get yields for all maturities
maturities = ['2y', '5y', '10y', '30y']
yields = []

for maturity in maturities:
    result = jgb_tool.execute({
        'bond_term': maturity,
        'recent_periods': 1
    })
    yields.append(result['observations'][0]['value'])

# Plot yield curve
plt.figure(figsize=(10, 6))
plt.plot([2, 5, 10, 30], yields, marker='o')
plt.title('Japanese Government Bond Yield Curve')
plt.xlabel('Maturity (Years)')
plt.ylabel('Yield (%)')
plt.grid(True)
plt.show()
```

### Example 2: Historical Exchange Rate Analysis

```python
from tools.impl.japan_central_bank import BANK_OF_JAPAN_TOOLS
import pandas as pd

fx_tool = BANK_OF_JAPAN_TOOLS['boj_get_exchange_rate']()

# Get 1 year of USD/JPY data
result = fx_tool.execute({
    'currency_pair': 'usd_jpy',
    'start_date': '2023-11-01',
    'end_date': '2024-10-31'
})

# Convert to pandas DataFrame
df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df.set_index('date', inplace=True)

# Calculate statistics
print(f"Average: {df['value'].mean():.2f}")
print(f"Volatility (std): {df['value'].std():.2f}")
print(f"Range: {df['value'].min():.2f} - {df['value'].max():.2f}")
```

### Example 3: Policy Rate Impact Study

```python
from tools.impl.japan_central_bank import BANK_OF_JAPAN_TOOLS
from datetime import datetime, timedelta

policy_tool = BANK_OF_JAPAN_TOOLS['boj_get_policy_rate']()
jgb_tool = BANK_OF_JAPAN_TOOLS['boj_get_jgb_yield']()

# Get policy rate changes over past 5 years
end_date = datetime.now()
start_date = end_date - timedelta(days=5*365)

policy_data = policy_tool.execute({
    'rate_type': 'policy_rate',
    'start_date': start_date.strftime('%Y-%m-%d'),
    'end_date': end_date.strftime('%Y-%m-%d')
})

jgb_data = jgb_tool.execute({
    'bond_term': '10y',
    'start_date': start_date.strftime('%Y-%m-%d'),
    'end_date': end_date.strftime('%Y-%m-%d')
})

# Analyze correlation
# (Implementation depends on your analysis needs)
```

### Example 4: Inflation Monitoring Dashboard

```python
from tools.impl.japan_central_bank import BANK_OF_JAPAN_TOOLS

price_tool = BANK_OF_JAPAN_TOOLS['boj_get_price_index']()

# Get latest inflation data
cpi_data = price_tool.execute({
    'index_type': 'cpi',
    'recent_periods': 12
})

core_cpi_data = price_tool.execute({
    'index_type': 'core_cpi',
    'recent_periods': 12
})

# Calculate YoY inflation
latest_cpi = cpi_data['observations'][-1]['value']
year_ago_cpi = cpi_data['observations'][0]['value']
inflation_rate = ((latest_cpi / year_ago_cpi) - 1) * 100

print(f"Current CPI: {latest_cpi}")
print(f"YoY Inflation: {inflation_rate:.2f}%")
```

---

## API Reference

### Common Parameters

All tools support these common parameters:

- **start_date** (string, optional): Start date in YYYY-MM-DD format
- **end_date** (string, optional): End date in YYYY-MM-DD format
- **recent_periods** (integer, optional): Number of recent observations (1-100, default: 10)

### Common Response Format

All tools return data in this structure:

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

Tools may raise these exceptions:

- **ValueError**: Invalid parameters or series not found
- **ConnectionError**: Network issues accessing BoJ API
- **TimeoutError**: API request timeout (30 seconds)

Example error handling:

```python
try:
    result = jgb_tool.execute({'bond_term': '10y'})
except ValueError as e:
    print(f"Invalid parameter: {e}")
except ConnectionError as e:
    print(f"Network error: {e}")
```

---

## Common Use Cases

### 1. Carry Trade Analysis

**Objective**: Evaluate USD/JPY carry trade opportunities

```python
# Get policy rates and exchange rates
policy_tool = BANK_OF_JAPAN_TOOLS['boj_get_policy_rate']()
fx_tool = BANK_OF_JAPAN_TOOLS['boj_get_exchange_rate']()

boj_rate = policy_tool.execute({
    'rate_type': 'policy_rate',
    'recent_periods': 1
})

usd_jpy = fx_tool.execute({
    'currency_pair': 'usd_jpy',
    'recent_periods': 1
})

# Calculate potential carry (need to add Fed rate for complete analysis)
print(f"BoJ Rate: {boj_rate['observations'][0]['value']}%")
print(f"USD/JPY: {usd_jpy['observations'][0]['value']}")
```

### 2. Fixed Income Portfolio Management

**Objective**: Monitor JGB portfolio performance

```python
# Track multiple maturities
portfolio = {
    '2y': 1000000,  # JPY amounts
    '10y': 5000000,
    '30y': 2000000
}

jgb_tool = BANK_OF_JAPAN_TOOLS['boj_get_jgb_yield']()
total_value = 0

for maturity, amount in portfolio.items():
    result = jgb_tool.execute({
        'bond_term': maturity,
        'recent_periods': 1
    })
    yield_value = result['observations'][0]['value']
    # Calculate bond value based on yield
    # (Simplified - actual calculation would use duration)
    print(f"{maturity}: {yield_value}% yield on ¥{amount:,}")
```

### 3. Monetary Policy Research

**Objective**: Study relationship between money supply and inflation

```python
money_tool = BANK_OF_JAPAN_TOOLS['boj_get_money_stock']()
price_tool = BANK_OF_JAPAN_TOOLS['boj_get_price_index']()

# Get 5 years of data
m2_data = money_tool.execute({
    'aggregate': 'm2',
    'start_date': '2019-11-01',
    'end_date': '2024-10-31'
})

cpi_data = price_tool.execute({
    'index_type': 'cpi',
    'start_date': '2019-11-01',
    'end_date': '2024-10-31'
})

# Analyze correlation
# (Implementation depends on statistical library used)
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: "Series not found" error

**Solution**: Verify the series code or indicator name matches the BoJ API specification. Check for typos in bond_term, currency_pair, etc.

#### Issue: Empty observations returned

**Solution**: 
- Check if the date range is valid
- Verify that data exists for the requested period
- Some series may have gaps or delays in publishing

#### Issue: API timeout

**Solution**:
- Check your network connection
- The BoJ API may be temporarily unavailable
- Try reducing the date range for large queries

#### Issue: Rate limit exceeded

**Solution**: 
- The BoJ API has rate limits (120 requests/hour by default)
- Implement caching for frequently accessed data
- Space out your requests

### Best Practices

1. **Cache Results**: Store frequently accessed data locally to reduce API calls
2. **Error Handling**: Always wrap API calls in try-except blocks
3. **Date Validation**: Validate date formats before making requests
4. **Reasonable Ranges**: Don't request more data than needed
5. **Monitor Metrics**: Use the tool's metrics functionality to track usage

```python
# Check tool metrics
metrics = jgb_tool.get_metrics()
print(f"Executions: {metrics['execution_count']}")
print(f"Avg time: {metrics['average_execution_time']:.2f}s")
```

---

## Support and Resources

### Official Resources

- **Bank of Japan Website**: https://www.boj.or.jp/en/
- **Time-Series Data Search**: https://www.stat-search.boj.or.jp/
- **BoJ Statistics**: https://www.boj.or.jp/en/statistics/index.htm

### Technical Support

For technical issues or questions:
- Email: ajsinha@gmail.com
- GitHub Issues: [Project Repository]

### Additional Documentation

- [Bank of Canada Tools Documentation](CANADA_BANK_DOCUMENTATION.md)
- [MCP Base Tool Reference](BASE_MCP_TOOL_REFERENCE.md)
- [API Integration Guide](API_INTEGRATION_GUIDE.md)

---

## Version History

- **v1.0.0** (2025-11-01): Initial release with 5 core tools

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


---

## Page Glossary

**Key terms referenced in this document:**

- **Bank of Japan (BoJ)**: Japan's central bank, responsible for monetary policy and currency issuance.

- **JGB (Japanese Government Bond)**: Debt securities issued by the Japanese government. SAJHA provides JGB yield data.

- **JPY (Japanese Yen)**: The official currency of Japan.

- **FRED API**: Federal Reserve Economic Data API. SAJHA's BoJ tools use FRED for Japanese economic data.

- **Policy Rate**: The BoJ's target interest rate, historically near zero or negative as part of monetary easing.

- **Quantitative Easing**: BoJ's policy of purchasing assets to increase money supply and stimulate the economy.

- **Yield Curve Control**: BoJ's policy of targeting specific yields for government bonds.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
