# Banque de France / ECB MCP Tools - Complete Documentation


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

The Banque de France / ECB MCP Tools provide comprehensive access to French and Eurozone economic and financial data through the Banque de France Webstat API and ECB Statistical Data Warehouse. These tools enable you to retrieve:

- **French Government Bond (OAT) Yields**: Obligations Assimilables du Trésor yields for 2, 5, 10, and 30-year maturities
- **ECB Policy Rates**: Main refinancing rate, deposit facility rate, and marginal lending rate
- **Exchange Rates**: EUR exchange rates against USD, GBP, JPY, and CNY
- **French Economic Indicators**: CPI, GDP, and unemployment specific to France
- **Eurozone Aggregates**: Eurozone-wide CPI, GDP, and M3 money supply

### Key Features

✅ **Dual Coverage**: French-specific and Eurozone-wide data
✅ **ECB Policy**: Access to European Central Bank monetary policy rates
✅ **OAT Bonds**: Track French sovereign debt yields
✅ **Euro Exchange Rates**: Monitor EUR forex movements
✅ **Comprehensive**: Both national and currency union statistics

### Important Context

**France and the Eurozone**: France is a member of the Eurozone, so monetary policy is set by the European Central Bank (ECB) rather than Banque de France. These tools provide:
- ECB policy rates (applicable to all Eurozone countries)
- French-specific economic data
- Eurozone aggregate statistics
- French government bond (OAT) yields

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
│  • bdf_get_ecb_policy_rate   (ECB Interest Rates)        │
│  • bdf_get_oat_yield         (OAT Bond Yields)           │
│  • bdf_get_exchange_rate     (EUR Exchange Rates)        │
│  • bdf_get_french_indicator  (French Economic Data)      │
│  • bdf_get_eurozone_indicator (Eurozone Statistics)      │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│          BDFBaseTool (Shared Functionality)              │
├──────────────────────────────────────────────────────────┤
│  • Banque de France API Integration                      │
│  • ECB Data Warehouse Connection                         │
│  • Data Transformation & Parsing                         │
│  • Response Normalization                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│           Banque de France / ECB Data Portal             │
│    https://www.banque-france.fr/ | https://sdw.ecb.eu/   │
└──────────────────────────────────────────────────────────┘
```

### Data Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Request    │───▶│  Tool Layer  │───▶│  BdF/ECB API │
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
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS

# Initialize a tool
oat_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_oat_yield']()

# Execute with arguments
result = oat_tool.execute({
    'bond_term': '10y',
    'recent_periods': 30
})

print(f"Latest 10-year OAT yield: {result['observations'][-1]['value']}%")
```

### Quick Example: Get Latest ECB Policy Rate

```python
ecb_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_ecb_policy_rate']()
result = ecb_tool.execute({
    'rate_type': 'ecb_main_refi',
    'recent_periods': 1
})
print(f"ECB Main Refinancing Rate: {result['observations'][0]['value']}%")
```

---

## Available Tools

| Tool Name | Purpose | Key Parameters |
|-----------|---------|----------------|
| `bdf_get_oat_yield` | French OAT yields | bond_term (2y, 5y, 10y, 30y) |
| `bdf_get_ecb_policy_rate` | ECB policy rates | rate_type (main_refi, deposit, marginal_lending) |
| `bdf_get_exchange_rate` | EUR forex rates | currency_pair (eur_usd, eur_gbp, etc.) |
| `bdf_get_french_indicator` | French economics | indicator (fr_cpi, fr_gdp, fr_unemployment) |
| `bdf_get_eurozone_indicator` | Eurozone aggregates | indicator (ez_cpi, ez_gdp, m3) |

---

## Detailed Tool Reference

### 1. bdf_get_oat_yield

**Purpose**: Retrieve French Government Bond (OAT) yields across different maturities.

**OAT Background**: Obligations Assimilables du Trésor (OATs) are French government bonds, considered among the safest assets in Europe alongside German Bunds.

**Input Parameters**:
```json
{
  "bond_term": "10y",         // Required: "2y", "5y", "10y", or "30y"
  "start_date": "2024-01-01", // Optional: YYYY-MM-DD format
  "end_date": "2024-12-31",   // Optional: YYYY-MM-DD format
  "recent_periods": 30        // Optional: 1-100 (default: 10)
}
```

**Output Schema**:
```json
{
  "series_code": "IRS.M.FR.L.L40.CI.0000.EUR.N.Z",
  "label": "10-Year OAT Yield",
  "description": "French 10-year Government Bond yield",
  "unit": "Percentage",
  "observation_count": 30,
  "observations": [
    {
      "date": "2024-11-01",
      "value": 3.15
    }
  ]
}
```

**Use Cases**:
- French sovereign debt analysis
- Eurozone yield curve comparison
- Fixed income portfolio management
- Credit spread analysis (vs German Bunds)
- European fiscal policy assessment

---

### 2. bdf_get_ecb_policy_rate

**Purpose**: Access European Central Bank policy interest rates.

**Input Parameters**:
```json
{
  "rate_type": "ecb_main_refi",  // Required: see options below
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Rate Types**:
- **ecb_main_refi**: Main refinancing operations rate (primary policy tool)
- **ecb_deposit**: Deposit facility rate (floor for overnight rates)
- **ecb_marginal_lending**: Marginal lending facility rate (ceiling for overnight rates)

**ECB Context**: These rates apply to all 20 Eurozone countries. The ECB's Governing Council sets these rates based on Eurozone-wide conditions.

**Use Cases**:
- Eurozone monetary policy analysis
- Interest rate forecasting
- Banking sector profitability assessment
- Fixed income strategy
- Economic research

---

### 3. bdf_get_exchange_rate

**Purpose**: Access EUR exchange rates against major global currencies.

**Input Parameters**:
```json
{
  "currency_pair": "eur_usd",  // Required: "eur_usd", "eur_gbp", "eur_jpy", "eur_cny"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Currency Pairs**:
- **EUR/USD**: Euro per US Dollar (most liquid forex pair)
- **EUR/GBP**: Euro per British Pound
- **EUR/JPY**: Euro per Japanese Yen
- **EUR/CNY**: Euro per Chinese Yuan

**Use Cases**:
- Currency trading and hedging
- International trade pricing
- Cross-border investment valuation
- Tourism and travel planning
- Purchasing power parity analysis

---

### 4. bdf_get_french_indicator

**Purpose**: Retrieve France-specific economic indicators.

**Input Parameters**:
```json
{
  "indicator": "fr_cpi",       // Required: "fr_cpi", "fr_gdp", "fr_unemployment"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Indicators**:
- **fr_cpi**: French Consumer Price Index
- **fr_gdp**: French Gross Domestic Product
- **fr_unemployment**: French unemployment rate

**Use Cases**:
- French economic performance tracking
- Regional policy analysis
- Labor market research
- Fiscal policy evaluation
- Comparative European analysis

---

### 5. bdf_get_eurozone_indicator

**Purpose**: Retrieve Eurozone-wide economic indicators.

**Input Parameters**:
```json
{
  "indicator": "ez_cpi",       // Required: "ez_cpi", "ez_gdp", "m3"
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Indicators**:
- **ez_cpi**: Eurozone Consumer Price Index (HICP)
- **ez_gdp**: Eurozone Gross Domestic Product
- **m3**: Eurozone M3 money supply (broad money)

**Use Cases**:
- Eurozone-wide policy analysis
- ECB decision forecasting
- Currency area economic health assessment
- Cross-country comparison
- Monetary transmission analysis

---

## Code Examples

### Example 1: OAT vs Bund Spread Analysis

```python
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS
# Note: Would need German Bund tool for complete analysis

oat_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_oat_yield']()

# Get French OAT yields across curve
maturities = ['2y', '5y', '10y', '30y']
oat_yields = []

for maturity in maturities:
    result = oat_tool.execute({
        'bond_term': maturity,
        'recent_periods': 1
    })
    oat_yields.append(result['observations'][0]['value'])

print("French OAT Yield Curve")
print("=" * 40)
for mat, yld in zip(maturities, oat_yields):
    print(f"{mat:5s}: {yld:.3f}%")

# Calculate curve steepness
steepness_2_10 = oat_yields[2] - oat_yields[0]
steepness_10_30 = oat_yields[3] - oat_yields[2]

print(f"\n2Y-10Y Spread: {steepness_2_10:.2f}%")
print(f"10Y-30Y Spread: {steepness_10_30:.2f}%")
```

### Example 2: ECB Policy Corridor

```python
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS

ecb_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_ecb_policy_rate']()

# Get all three policy rates
rates = {}
rate_types = ['ecb_main_refi', 'ecb_deposit', 'ecb_marginal_lending']

for rate_type in rate_types:
    result = ecb_tool.execute({
        'rate_type': rate_type,
        'recent_periods': 1
    })
    rates[rate_type] = result['observations'][0]['value']

print("ECB INTEREST RATE CORRIDOR")
print("=" * 50)
print(f"Marginal Lending (Ceiling): {rates['ecb_marginal_lending']:.3f}%")
print(f"Main Refinancing (Mid):      {rates['ecb_main_refi']:.3f}%")
print(f"Deposit Facility (Floor):    {rates['ecb_deposit']:.3f}%")
print("=" * 50)

corridor_width = rates['ecb_marginal_lending'] - rates['ecb_deposit']
print(f"Corridor Width: {corridor_width:.2f}%")
```

### Example 3: EUR/USD Historical Volatility

```python
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS
import pandas as pd
import numpy as np

fx_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_exchange_rate']()

# Get 1 year of EUR/USD data
result = fx_tool.execute({
    'currency_pair': 'eur_usd',
    'start_date': '2023-11-01',
    'end_date': '2024-10-31'
})

df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df['value'] = pd.to_numeric(df['value'])
df['returns'] = df['value'].pct_change()

# Calculate statistics
volatility = df['returns'].std() * np.sqrt(252) * 100  # Annualized

print(f"EUR/USD Analysis (12 Months)")
print(f"Average Rate: {df['value'].mean():.4f}")
print(f"Current Rate: {df['value'].iloc[-1]:.4f}")
print(f"High: {df['value'].max():.4f}")
print(f"Low: {df['value'].min():.4f}")
print(f"Annualized Volatility: {volatility:.2f}%")
```

### Example 4: France vs Eurozone Inflation

```python
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS
import pandas as pd
import matplotlib.pyplot as plt

french_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_french_indicator']()
eurozone_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_eurozone_indicator']()

# Get French and Eurozone CPI
fr_cpi = french_tool.execute({
    'indicator': 'fr_cpi',
    'recent_periods': 24
})

ez_cpi = eurozone_tool.execute({
    'indicator': 'ez_cpi',
    'recent_periods': 24
})

# Convert to DataFrames
df_fr = pd.DataFrame(fr_cpi['observations'])
df_ez = pd.DataFrame(ez_cpi['observations'])

df_fr['date'] = pd.to_datetime(df_fr['date'])
df_ez['date'] = pd.to_datetime(df_ez['date'])

# Plot comparison
plt.figure(figsize=(12, 6))
plt.plot(df_fr['date'], df_fr['value'], label='France CPI', marker='o')
plt.plot(df_ez['date'], df_ez['value'], label='Eurozone CPI', marker='s')
plt.title('France vs Eurozone Inflation Comparison')
plt.xlabel('Date')
plt.ylabel('CPI Index')
plt.legend()
plt.grid(True, alpha=0.3)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

### Example 5: Eurozone M3 Money Supply Tracking

```python
from tools.impl.france_central_bank import BANQUE_DE_FRANCE_TOOLS
import pandas as pd

eurozone_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_eurozone_indicator']()

# Get M3 money supply data
result = eurozone_tool.execute({
    'indicator': 'm3',
    'recent_periods': 24
})

df = pd.DataFrame(result['observations'])
df['date'] = pd.to_datetime(df['date'])
df['value'] = pd.to_numeric(df['value'])

# Calculate YoY growth
current_m3 = df['value'].iloc[-1]
year_ago_m3 = df['value'].iloc[-13]
growth_rate = ((current_m3 / year_ago_m3) - 1) * 100

print(f"Eurozone M3 Money Supply")
print(f"Current: €{current_m3/1e12:.2f} trillion")
print(f"YoY Growth: {growth_rate:.2f}%")

# ECB targets ~4.5% M3 growth
print(f"\nDeviation from ECB reference: {(growth_rate - 4.5):.2f}%")
```

---

## Common Use Cases

### 1. Fixed Income Portfolio Allocation

**Objective**: Compare French OATs with other Eurozone sovereigns

```python
oat_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_oat_yield']()

# Get 10-year OAT yield
oat_10y = oat_tool.execute({'bond_term': '10y', 'recent_periods': 1})
oat_yield = oat_10y['observations'][0]['value']

# Assume German Bund at 2.50% (would get from separate source)
bund_yield = 2.50
spread = (oat_yield - bund_yield) * 100  # in basis points

print(f"10-Year OAT Yield: {oat_yield:.3f}%")
print(f"10-Year Bund Yield: {bund_yield:.3f}%")
print(f"France-Germany Spread: {spread:.1f} bps")

if spread > 50:
    print("\nInterpretation: French bonds offer significant premium")
elif spread < 30:
    print("\nInterpretation: Minimal risk premium for French debt")
```

### 2. ECB Policy Impact Analysis

**Objective**: Correlate ECB rate changes with OAT yields

```python
ecb_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_ecb_policy_rate']()
oat_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_oat_yield']()

# Get historical data
ecb_rates = ecb_tool.execute({
    'rate_type': 'ecb_main_refi',
    'start_date': '2022-01-01',
    'end_date': '2024-10-31'
})

oat_yields = oat_tool.execute({
    'bond_term': '10y',
    'start_date': '2022-01-01',
    'end_date': '2024-10-31'
})

# Analyze correlation
# (Statistical analysis implementation depends on your needs)
print("ECB Rate vs OAT Yield Correlation Analysis")
# Would typically use pandas correlation or scipy
```

### 3. EUR/USD Trading Strategy

**Objective**: Use economic differentials for forex trading

```python
fx_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_exchange_rate']()
eurozone_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_eurozone_indicator']()
ecb_tool = BANQUE_DE_FRANCE_TOOLS['bdf_get_ecb_policy_rate']()

# Get latest data
eur_usd = fx_tool.execute({'currency_pair': 'eur_usd', 'recent_periods': 1})
ez_cpi = eurozone_tool.execute({'indicator': 'ez_cpi', 'recent_periods': 12})
ecb_rate = ecb_tool.execute({'rate_type': 'ecb_main_refi', 'recent_periods': 1})

# Calculate real rate
latest_cpi = ez_cpi['observations'][-1]['value']
year_ago_cpi = ez_cpi['observations'][0]['value']
inflation = ((latest_cpi / year_ago_cpi) - 1) * 100

nominal_rate = ecb_rate['observations'][0]['value']
real_rate = nominal_rate - inflation

print(f"EUR/USD: {eur_usd['observations'][0]['value']:.4f}")
print(f"ECB Rate: {nominal_rate:.2f}%")
print(f"Inflation: {inflation:.2f}%")
print(f"Real Rate: {real_rate:.2f}%")
print("\nNote: Compare with US Fed rate for carry trade analysis")
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
    result = oat_tool.execute({'bond_term': '10y'})
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

1. **ECB Data Delays**
   - ECB data published with slight delays
   - Check ECB website for data release calendar
   - Some series updated monthly, others daily

2. **API Rate Limits**
   - Default: 120 requests/hour
   - Cache frequently accessed data
   - Implement exponential backoff for retries

3. **Holiday Schedules**
   - Be aware of European/French holidays
   - ECB closed on EU holidays
   - Bond markets closed on French holidays

### Best Practices

1. **Caching Strategy**
   ```python
   # Example caching implementation
   import functools
   import time
   
   @functools.lru_cache(maxsize=100)
   def cached_oat_yield(bond_term, date_str):
       # Fetch data only if not in cache
       pass
   ```

2. **Error Handling**
   ```python
   def robust_fetch(tool, params, max_retries=3):
       for attempt in range(max_retries):
           try:
               return tool.execute(params)
           except ConnectionError:
               if attempt < max_retries - 1:
                   time.sleep(2 ** attempt)
               else:
                   raise
   ```

3. **Data Validation**
   ```python
   def validate_date_range(start_date, end_date):
       from datetime import datetime
       start = datetime.strptime(start_date, '%Y-%m-%d')
       end = datetime.strptime(end_date, '%Y-%m-%d')
       if start >= end:
           raise ValueError("Start date must be before end date")
       return True
   ```

---

## Support and Resources

### Official Resources

- **Banque de France**: https://www.banque-france.fr/
- **ECB Website**: https://www.ecb.europa.eu/
- **ECB Statistical Data Warehouse**: https://sdw.ecb.europa.eu/
- **Webstat BdF**: https://webstat.banque-france.fr/

### Key Publications

- ECB Economic Bulletin (monthly)
- ECB Monetary Policy Decisions
- Banque de France Conjoncture (economic outlook)

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

