# People's Bank of China (PBoC) MCP Tools - Complete Documentation


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

The People's Bank of China (PBoC) MCP Tools provide comprehensive access to Chinese economic and financial data through official PBoC data APIs. These tools enable you to retrieve:

- **China Government Bond (CGB) Yields**: Access yield data for 1-year, 5-year, 10-year, and 30-year CGBs
- **Loan Prime Rate (LPR)**: China's benchmark lending rate for 1-year and 5-year tenors
- **Exchange Rates**: CNY exchange rates against USD, EUR, JPY, and HKD
- **Money Supply**: M0, M1, and M2 monetary aggregates
- **Foreign Exchange Reserves**: Track China's massive forex and gold reserves

### Key Features

✅ **Official Data**: Direct access to PBoC statistical data
✅ **LPR Tracking**: Monitor China's key lending benchmark
✅ **Comprehensive Coverage**: Wide range of monetary indicators
✅ **Historical Analysis**: Retrieve data with customizable date ranges
✅ **Global Impact**: Access data from world's second-largest economy

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
│  • pboc_get_cgb_yield     (Government Bond Yields)       │
│  • pboc_get_lpr           (Loan Prime Rate)              │
│  • pboc_get_exchange_rate (CNY Exchange Rates)           │
│  • pboc_get_money_supply  (M0, M1, M2 Aggregates)        │
│  • pboc_get_forex_reserves (Forex/Gold Reserves)         │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│        PBOCBaseTool (Shared Functionality)               │
├──────────────────────────────────────────────────────────┤
│  • API Configuration & Endpoints                         │
│  • Data Transformation & Parsing                         │
│  • Error Handling & Logging                              │
│  • Response Normalization                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│         People's Bank of China Data Portal               │
│              http://www.pbc.gov.cn/                      │
└──────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Request    │───▶│  Tool Layer  │───▶│   PBoC API   │
│  (bond_term) │    │  (validate)  │    │   (fetch)    │
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
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS

# Initialize a tool
cgb_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_cgb_yield']()

# Execute with arguments
result = cgb_tool.execute({
    'bond_term': '10y',
    'recent_periods': 30
})

print(f"Latest 10-year CGB yield: {result['observations'][-1]['value']}%")
```

### Quick Example: Get Latest LPR

```python
lpr_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_lpr']()
result = lpr_tool.execute({
    'tenor': '1y',
    'recent_periods': 1
})
print(f"1-Year LPR: {result['observations'][0]['value']}%")
```

---

## Available Tools

| Tool Name | Purpose | Key Parameters |
|-----------|---------|----------------|
| `pboc_get_cgb_yield` | CGB yield curves | bond_term (1y, 5y, 10y, 30y) |
| `pboc_get_lpr` | Loan Prime Rate | tenor (1y, 5y) |
| `pboc_get_exchange_rate` | CNY forex rates | currency_pair (usd_cny, eur_cny, etc.) |
| `pboc_get_money_supply` | Monetary aggregates | aggregate (m0, m1, m2) |
| `pboc_get_forex_reserves` | Forex/gold reserves | reserve_type (forex_reserves, gold_reserves) |

---

## Detailed Tool Reference

### 1. pboc_get_cgb_yield

**Purpose**: Retrieve China Government Bond yields across different maturities.

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
  "series_code": "CGB_10Y",
  "label": "10-Year China Government Bond Yield",
  "description": "Benchmark 10-year CGB yield",
  "unit": "Percentage",
  "observation_count": 30,
  "observations": [
    {
      "date": "2024-11-01",
      "value": 2.65
    }
  ]
}
```

**Use Cases**:
- Fixed income investment in China
- Sovereign debt analysis
- Yield curve construction
- Interest rate policy assessment
- Global bond portfolio allocation

---

### 2. pboc_get_lpr

**Purpose**: Access China's Loan Prime Rate, the benchmark for bank lending rates.

**Input Parameters**:
```json
{
  "tenor": "1y",              // Required: "1y" or "5y"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**LPR Tenors**:
- **1y LPR**: One-year Loan Prime Rate (for short-term loans)
- **5y LPR**: Five-year Loan Prime Rate (for mortgages)

**Background**: The LPR was reformed in 2019 to be more market-oriented. It's quoted by 18 banks and published monthly by the PBoC.

**Use Cases**:
- Mortgage rate forecasting
- Corporate lending cost analysis
- Monetary policy research
- Real estate market analysis
- Credit market assessment

---

### 3. pboc_get_exchange_rate

**Purpose**: Access CNY exchange rates against major global currencies.

**Input Parameters**:
```json
{
  "currency_pair": "usd_cny",  // Required: "usd_cny", "eur_cny", "jpy_cny", "hkd_cny"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Currency Pairs**:
- **USD/CNY**: US Dollar per Chinese Yuan
- **EUR/CNY**: Euro per Chinese Yuan
- **JPY/CNY**: Japanese Yen (100 yen) per Chinese Yuan
- **HKD/CNY**: Hong Kong Dollar per Chinese Yuan

**Use Cases**:
- Currency trading strategies
- Import/export pricing
- International investment valuation
- Capital flow analysis
- Trade balance research

---

### 4. pboc_get_money_supply

**Purpose**: Track Chinese monetary aggregates.

**Input Parameters**:
```json
{
  "aggregate": "m2",           // Required: "m0", "m1", or "m2"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Aggregates**:
- **M0**: Currency in circulation
- **M1**: M0 + Corporate demand deposits + Personal demand deposits
- **M2**: M1 + Time deposits + Savings deposits + Other deposits

**Use Cases**:
- Monetary policy analysis
- Liquidity conditions assessment
- Inflation forecasting
- Credit growth tracking
- Economic stimulus evaluation

---

### 5. pboc_get_forex_reserves

**Purpose**: Track China's foreign exchange and gold reserves.

**Input Parameters**:
```json
{
  "reserve_type": "forex_reserves",  // Required: "forex_reserves" or "gold_reserves"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Reserve Types**:
- **forex_reserves**: Total foreign exchange reserves (USD)
- **gold_reserves**: Gold holdings (troy ounces)

**Significance**: China holds the world's largest forex reserves, critical for understanding global capital flows and currency stability.

**Use Cases**:
- External sector analysis
- Currency stability assessment
- Global liquidity monitoring
- Trade surplus tracking
- Geopolitical risk analysis

---

## Code Examples

### Example 1: LPR Spread Analysis

```python
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS
import pandas as pd

lpr_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_lpr']()

# Get both 1Y and 5Y LPR
lpr_1y = lpr_tool.execute({'tenor': '1y', 'recent_periods': 12})
lpr_5y = lpr_tool.execute({'tenor': '5y', 'recent_periods': 12})

# Convert to DataFrames
df_1y = pd.DataFrame(lpr_1y['observations'])
df_5y = pd.DataFrame(lpr_5y['observations'])

# Calculate spread
df_1y['date'] = pd.to_datetime(df_1y['date'])
df_5y['date'] = pd.to_datetime(df_5y['date'])

# Merge on date
merged = pd.merge(df_1y, df_5y, on='date', suffixes=('_1y', '_5y'))
merged['spread'] = merged['value_5y'] - merged['value_1y']

print("LPR Spread Analysis (5Y - 1Y)")
print(f"Average Spread: {merged['spread'].mean():.2f} bps")
print(f"Current Spread: {merged['spread'].iloc[-1]:.2f} bps")
```

### Example 2: Yield Curve Construction

```python
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS
import matplotlib.pyplot as plt

cgb_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_cgb_yield']()

maturities = ['1y', '5y', '10y', '30y']
maturity_years = [1, 5, 10, 30]
yields = []

for maturity in maturities:
    result = cgb_tool.execute({
        'bond_term': maturity,
        'recent_periods': 1
    })
    yields.append(result['observations'][0]['value'])

# Plot yield curve
plt.figure(figsize=(10, 6))
plt.plot(maturity_years, yields, marker='o', linewidth=2, markersize=8)
plt.title('China Government Bond Yield Curve', fontsize=14, fontweight='bold')
plt.xlabel('Maturity (Years)')
plt.ylabel('Yield (%)')
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

print("CGB Yield Curve:")
for mat, yld in zip(maturities, yields):
    print(f"{mat:5s}: {yld:.3f}%")
```

### Example 3: Money Supply Growth Analysis

```python
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS
import pandas as pd

money_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_money_supply']()

# Get M2 data for past 24 months
result = money_tool.execute({
    'aggregate': 'm2',
    'recent_periods': 24
})

df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df['value'] = pd.to_numeric(df['value'])

# Calculate YoY growth
current_m2 = df['value'].iloc[-1]
year_ago_m2 = df['value'].iloc[-13]  # 13 months ago for YoY
growth_rate = ((current_m2 / year_ago_m2) - 1) * 100

print(f"M2 Money Supply Analysis")
print(f"Current M2: ¥{current_m2/1e12:.2f} trillion")
print(f"YoY Growth: {growth_rate:.2f}%")
print(f"MoM Change: {((df['value'].iloc[-1]/df['value'].iloc[-2])-1)*100:.2f}%")
```

### Example 4: Forex Reserves Tracking

```python
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS
import pandas as pd

reserves_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_forex_reserves']()

# Get forex reserves for past year
forex_data = reserves_tool.execute({
    'reserve_type': 'forex_reserves',
    'recent_periods': 12
})

df = pd.DataFrame(forex_data['observations'])
df['value'] = pd.to_numeric(df['value']) / 1e9  # Convert to billions

print(f"China Foreign Exchange Reserves (USD Billion)")
print(f"Current: ${df['value'].iloc[-1]:.2f}B")
print(f"Peak (12M): ${df['value'].max():.2f}B")
print(f"Low (12M): ${df['value'].min():.2f}B")
print(f"Change (YoY): ${(df['value'].iloc[-1] - df['value'].iloc[0]):.2f}B")
print(f"Volatility: ${df['value'].std():.2f}B")
```

### Example 5: Currency Basket Monitoring

```python
from tools.impl.china_central_bank import PEOPLES_BANK_OF_CHINA_TOOLS

fx_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_exchange_rate']()

# Track multiple currencies
currencies = {
    'usd_cny': 'USD/CNY',
    'eur_cny': 'EUR/CNY',
    'jpy_cny': 'JPY/CNY (per 100)',
    'hkd_cny': 'HKD/CNY'
}

print("CHINESE YUAN EXCHANGE RATES")
print("=" * 50)

for pair, label in currencies.items():
    result = fx_tool.execute({
        'currency_pair': pair,
        'recent_periods': 1
    })
    rate = result['observations'][0]['value']
    print(f"{label:20s}: {rate:10.4f}")
```

---

## Common Use Cases

### 1. Mortgage Rate Forecasting

**Objective**: Track 5Y LPR for mortgage cost projections

```python
lpr_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_lpr']()

# Get historical 5Y LPR
result = lpr_tool.execute({
    'tenor': '5y',
    'start_date': '2023-01-01',
    'end_date': '2024-10-31'
})

df = pd.DataFrame(result['observations'])
df['value'] = pd.to_numeric(df['value'])

# Calculate average and trend
avg_rate = df['value'].mean()
current_rate = df['value'].iloc[-1]

print(f"5-Year LPR Analysis for Mortgage Planning")
print(f"Current Rate: {current_rate:.3f}%")
print(f"Average (24M): {avg_rate:.3f}%")
print(f"Difference: {(current_rate - avg_rate):.3f}%")

# Mortgage cost example
loan_amount = 2000000  # ¥2 million
monthly_rate = current_rate / 100 / 12
months = 360  # 30 years

monthly_payment = loan_amount * (monthly_rate * (1 + monthly_rate)**months) / \
                  ((1 + monthly_rate)**months - 1)

print(f"\nMortgage Example (¥{loan_amount:,})")
print(f"Monthly Payment: ¥{monthly_payment:,.2f}")
```

### 2. China Fixed Income Strategy

**Objective**: Compare CGB yields with LPR for investment decisions

```python
cgb_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_cgb_yield']()
lpr_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_lpr']()

# Get 10Y CGB and 5Y LPR
cgb_10y = cgb_tool.execute({'bond_term': '10y', 'recent_periods': 1})
lpr_5y = lpr_tool.execute({'tenor': '5y', 'recent_periods': 1})

cgb_yield = cgb_10y['observations'][0]['value']
lpr_rate = lpr_5y['observations'][0]['value']

spread = cgb_yield - lpr_rate

print(f"Fixed Income Analysis")
print(f"10Y CGB Yield: {cgb_yield:.3f}%")
print(f"5Y LPR:        {lpr_rate:.3f}%")
print(f"Spread:        {spread:.3f}%")

if spread > 0:
    print("\nInterpretation: CGBs offer premium over lending rate")
else:
    print("\nInterpretation: Lending more attractive than government bonds")
```

### 3. Trade Balance Indicator

**Objective**: Use forex reserves to gauge trade surplus trends

```python
reserves_tool = PEOPLES_BANK_OF_CHINA_TOOLS['pboc_get_forex_reserves']()

# Get 24 months of reserves data
result = reserves_tool.execute({
    'reserve_type': 'forex_reserves',
    'recent_periods': 24
})

df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df['value'] = pd.to_numeric(df['value'])

# Calculate changes
latest = df['value'].iloc[-1]
six_months_ago = df['value'].iloc[-7]
year_ago = df['value'].iloc[-13]

change_6m = latest - six_months_ago
change_12m = latest - year_ago

print(f"Forex Reserves Trend Analysis")
print(f"Current: ${latest/1e9:.2f}B")
print(f"Change (6M): ${change_6m/1e9:+.2f}B")
print(f"Change (12M): ${change_12m/1e9:+.2f}B")

if change_12m > 0:
    print("\nInterpretation: Likely positive trade balance or capital inflows")
else:
    print("\nInterpretation: Possible trade deficit or capital outflows")
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
    result = cgb_tool.execute({'bond_term': '10y'})
except ValueError as e:
    print(f"Invalid parameter: {e}")
except ConnectionError as e:
    print(f"Network error: {e}")
except TimeoutError as e:
    print(f"Request timeout: {e}")
```

---

## Troubleshooting

### Common Issues

1. **Data Availability**
   - LPR is published monthly (around 20th)
   - Some series may have delays
   - Check PBoC website for schedules

2. **Rate Limits**
   - Default: 120 requests/hour
   - Implement caching for efficiency
   - Space out requests appropriately

3. **Date Formatting**
   - Always use YYYY-MM-DD format
   - Validate dates before requests
   - Be aware of Chinese holidays

### Best Practices

1. Cache frequently accessed data
2. Handle exceptions gracefully
3. Validate input parameters
4. Monitor API usage metrics
5. Use appropriate date ranges
6. Consider time zone differences (China uses CST/UTC+8)

---

## Support and Resources

### Official Resources

- **PBoC Website**: http://www.pbc.gov.cn/
- **Statistical Data**: http://www.pbc.gov.cn/diaochatongjisi/
- **LPR Announcements**: http://www.pbc.gov.cn/zhengcehuobisi/

### Technical Support

- Email: ajsinha@gmail.com
- GitHub: [Project Repository]

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

- **PBoC (People's Bank of China)**: China's central bank, responsible for monetary policy and financial regulation.

- **CNY/RMB (Chinese Yuan/Renminbi)**: China's official currency.

- **LPR (Loan Prime Rate)**: China's benchmark lending rate for banks, replaced the previous lending rate system.

- **CGB (Chinese Government Bond)**: Debt securities issued by the Chinese government.

- **Reserve Requirement Ratio (RRR)**: The percentage of deposits banks must hold in reserve. A PBoC policy tool.

- **M2 Money Supply**: A measure of money supply including cash, checking deposits, and easily convertible near-money.

- **FRED API**: Federal Reserve Economic Data API used by SAJHA for Chinese economic data.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
