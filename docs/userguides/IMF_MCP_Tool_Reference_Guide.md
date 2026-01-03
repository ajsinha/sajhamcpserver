# IMF MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technical Details](#technical-details)
4. [Authentication & API Access](#authentication--api-access)
5. [IMF Databases](#imf-databases)
6. [Tool Descriptions](#tool-descriptions)
7. [Common Indicators](#common-indicators)
8. [Usage Examples](#usage-examples)
9. [Schema Reference](#schema-reference)
10. [Limitations](#limitations)
11. [Error Handling](#error-handling)
12. [Performance Considerations](#performance-considerations)

---

## Overview

The IMF MCP Tool Suite provides programmatic access to the International Monetary Fund's comprehensive economic databases. Access global economic statistics, financial indicators, and macroeconomic data for over 190 countries spanning decades of historical data.

### Key Features

- **8 Specialized Tools**: From database discovery to country profiling
- **10 Major Databases**: IFS, WEO, BOP, FSI, DOT, and more
- **190+ Countries**: Comprehensive global coverage
- **Historical Data**: Decades of economic time series
- **No Authentication**: Free public API access
- **Pre-configured Indicators**: 33+ common economic metrics
- **Multiple Frequencies**: Annual, quarterly, and monthly data

### Data Categories

- GDP and Economic Growth
- Inflation and Prices
- Employment and Unemployment
- Trade and Balance of Payments
- Fiscal and Public Debt
- Monetary and Financial Statistics
- Exchange Rates
- International Reserves
- Financial Soundness Indicators

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
│              MCP Tool Layer (8 Tools)                    │
├──────────────────────────────────────────────────────────┤
│  • imf_get_databases       • imf_get_ifs_data           │
│  • imf_get_dataflows       • imf_get_weo_data           │
│  • imf_get_data            • imf_get_bop_data           │
│  • imf_compare_countries   • imf_get_country_profile    │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│         IMFBaseTool (Shared Functionality)               │
├──────────────────────────────────────────────────────────┤
│  • API URL: dataservices.imf.org/REST/SDMX_JSON.svc     │
│  • Database Definitions (10 major databases)             │
│  • Common Indicator Mappings (33+ indicators)            │
│  • HTTP Client (urllib)                                  │
│  • JSON Parser                                           │
│  • Data Retrieval Methods                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│              IMF Data Services API                       │
│      http://dataservices.imf.org/REST/SDMX_JSON.svc     │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── IMFBaseTool
            │
            ├── IMFGetDatabasesTool
            ├── IMFGetDataflowsTool
            ├── IMFGetDataTool
            ├── IMFGetIFSDataTool
            ├── IMFGetWEODataTool
            ├── IMFGetBOPDataTool
            ├── IMFCompareCountriesTool
            └── IMFGetCountryProfileTool
```

### Component Descriptions

#### IMFBaseTool
Base class providing shared functionality:
- IMF API endpoint configuration
- Database definitions (10 major databases)
- Common indicator mappings:
  - 22 IFS (International Financial Statistics) indicators
  - 11 WEO (World Economic Outlook) indicators
- Country code mappings
- Core data retrieval method `_get_data()`
- HTTP request handling
- JSON response parsing
- Error handling and logging

#### Individual Tool Classes
Each tool specializes in specific data access patterns:
- Custom input/output schemas
- Specialized query building
- Domain-specific indicator shortcuts
- Tailored response formatting
- Specific error handling

---

## Technical Details

### Data Retrieval Method

**Type**: REST API Calls  
**Protocol**: HTTP  
**Method**: HTTP GET  
**Format**: JSON (SDMX-JSON)

**Not Used**:
- ✗ Web Scraping
- ✗ HTML Parsing
- ✗ Database Queries
- ✗ File System Access
- ✗ Authentication

### API Communication

The tools communicate with IMF Data Services using REST calls:

```python
# Base URL
http://dataservices.imf.org/REST/SDMX_JSON.svc

# Request Format
GET /CompactData/{DATABASE}/{FREQUENCY}.{COUNTRY}.{INDICATOR}?startPeriod={YEAR}&endPeriod={YEAR}

# Example
GET /CompactData/IFS/M.US.PCPI_IX?startPeriod=2020&endPeriod=2024
```

### HTTP Request Details

**URL Components**:
- `{DATABASE}`: Database code (IFS, WEO, BOP, etc.)
- `{FREQUENCY}`: A (Annual), Q (Quarterly), M (Monthly)
- `{COUNTRY}`: ISO 2-letter country code
- `{INDICATOR}`: Indicator code

**Query Parameters**:
- `startPeriod`: Start year (YYYY)
- `endPeriod`: End year (YYYY)

**Request Headers**:
```python
{
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json'
}
```

**No Authentication Required**: Public API, no API key needed

### Response Parsing

The IMF API returns SDMX-JSON format:

```json
{
  "CompactData": {
    "DataSet": {
      "Series": {
        "Obs": [
          {
            "@TIME_PERIOD": "2020",
            "@OBS_VALUE": "245.12"
          },
          {
            "@TIME_PERIOD": "2021",
            "@OBS_VALUE": "251.59"
          }
        ]
      }
    }
  }
}
```

The tools parse this structure and format it consistently:

```json
{
  "database": "IFS",
  "country_code": "US",
  "indicator_code": "PCPI_IX",
  "frequency": "M",
  "data": [
    {
      "period": "2020-01",
      "value": 245.12
    },
    {
      "period": "2020-02",
      "value": 246.35
    }
  ],
  "count": 2
}
```

---

## Authentication & API Access

### No Authentication Required

The IMF Data Services API is **completely public and free**:

- ✅ **No API Key Required**
- ✅ **No Registration Required**
- ✅ **No Cost**
- ✅ **No Rate Limits** (reasonable use)
- ✅ **Open Access**

### Configuration

```python
from tools.impl.imf_tool_refactored import IMFGetWEODataTool

# No configuration needed
tool = IMFGetWEODataTool()

# Optional configuration for logging, etc.
config = {
    'name': 'imf_get_weo_data',
    'enabled': True
}
tool = IMFGetWEODataTool(config)
```

### Fair Use Policy

While no explicit rate limits exist:
- Be respectful of server resources
- Cache results when possible
- Avoid excessive automated queries
- Space out large batch requests

---

## IMF Databases

### Available Databases

| Code | Name | Description | Update Frequency |
|------|------|-------------|------------------|
| **IFS** | International Financial Statistics | Financial and monetary statistics including exchange rates, interest rates, prices, and reserves | Monthly |
| **WEO** | World Economic Outlook | Macroeconomic indicators and forecasts including GDP, inflation, fiscal balances | Biannual (Apr, Oct) |
| **BOP** | Balance of Payments | Current account, capital account, trade balance, financial flows | Quarterly/Annual |
| **DOT** | Direction of Trade Statistics | Bilateral trade flows between countries | Monthly |
| **FSI** | Financial Soundness Indicators | Banking sector health indicators | Quarterly/Annual |
| **GFSR** | Global Financial Stability Report | Financial sector data and analysis | Biannual |
| **GFSMAB** | Government Finance Statistics | Fiscal data including revenues, expenditures, deficits | Annual |
| **CDIS** | Coordinated Direct Investment Survey | Foreign direct investment positions | Annual |
| **CPIS** | Coordinated Portfolio Investment Survey | Portfolio investment holdings | Annual |
| **WHDREO** | WEO Historical Database | Historical macroeconomic data | Annual |

### Database Selection Guide

| Need | Use Database |
|------|--------------|
| Exchange rates, interest rates, CPI | IFS |
| GDP growth, unemployment, forecasts | WEO |
| Trade balance, current account | BOP |
| Bilateral trade flows | DOT |
| Bank capital, NPLs | FSI |
| Government revenues, deficits | GFSMAB |
| FDI positions | CDIS |
| Portfolio investments | CPIS |

---

## Tool Descriptions

### 1. imf_get_databases

**Purpose**: List all available IMF databases

**Input**: None required

**Output**:
```json
{
  "databases": [
    {
      "code": "IFS",
      "name": "International Financial Statistics"
    },
    {
      "code": "WEO",
      "name": "World Economic Outlook"
    }
  ],
  "count": 10
}
```

**Use Cases**:
- Database discovery
- Understanding available data sources
- Research planning

---

### 2. imf_get_dataflows

**Purpose**: Get available dataflows and indicators for a specific database

**Input**:
```json
{
  "database": "IFS"
}
```

**Output**:
```json
{
  "database": "IFS",
  "dataflows": [
    {
      "id": "IFS",
      "name": "International Financial Statistics"
    }
  ],
  "count": 1
}
```

**Use Cases**:
- Indicator discovery
- Understanding database structure
- Research planning

---

### 3. imf_get_data

**Purpose**: Generic data retrieval from any IMF database

**Input**:
```json
{
  "database": "WEO",
  "country_code": "US",
  "indicator_code": "NGDP_RPCH",
  "start_year": 2020,
  "end_year": 2024,
  "frequency": "A"
}
```

**Output**:
```json
{
  "database": "WEO",
  "country_code": "US",
  "indicator_code": "NGDP_RPCH",
  "frequency": "A",
  "data": [
    {
      "period": "2020",
      "value": -3.4
    },
    {
      "period": "2021",
      "value": 5.7
    }
  ],
  "count": 2
}
```

**Use Cases**:
- Custom data retrieval
- Advanced research
- Specific indicator codes

---

### 4. imf_get_ifs_data

**Purpose**: Retrieve International Financial Statistics data

**Pre-configured Indicators** (22 total):
- Exchange rates (end period, average)
- Interest rates (policy, treasury, deposit, lending)
- Prices (CPI, core CPI, PPI)
- Money supply (M1, M2, M3, reserve money)
- Reserves (international, gold, foreign)
- GDP (current, constant)
- Industrial production
- Trade (exports, imports)
- Unemployment rate

**Input**:
```json
{
  "country_code": "JP",
  "indicator": "cpi",
  "start_year": 2023,
  "frequency": "M"
}
```

**Output**:
```json
{
  "database": "IFS",
  "country_code": "JP",
  "indicator_code": "PCPI_IX",
  "frequency": "M",
  "data": [
    {
      "period": "2023-01",
      "value": 104.3
    },
    {
      "period": "2023-02",
      "value": 104.7
    }
  ],
  "count": 2
}
```

**Use Cases**:
- Inflation monitoring
- Exchange rate analysis
- Interest rate tracking
- Reserve analysis
- Financial statistics

---

### 5. imf_get_weo_data

**Purpose**: Retrieve World Economic Outlook data with forecasts

**Pre-configured Indicators** (11 total):
- GDP growth
- GDP per capita
- Inflation (average, end-of-period)
- Unemployment
- Current account (% of GDP)
- Fiscal balance (% of GDP)
- Public debt (% of GDP)
- Exports/Imports volume growth
- Population

**Input**:
```json
{
  "country_code": "CN",
  "indicator": "gdp_growth",
  "start_year": 2020,
  "end_year": 2025
}
```

**Output**:
```json
{
  "database": "WEO",
  "country_code": "CN",
  "indicator_code": "NGDP_RPCH",
  "frequency": "A",
  "data": [
    {
      "period": "2020",
      "value": 2.3
    },
    {
      "period": "2021",
      "value": 8.1
    },
    {
      "period": "2024",
      "value": 4.5
    }
  ],
  "count": 3
}
```

**Use Cases**:
- GDP analysis
- Economic growth tracking
- Inflation monitoring
- Fiscal analysis
- Economic forecasting

---

### 6. imf_get_bop_data

**Purpose**: Retrieve Balance of Payments data

**Input**:
```json
{
  "country_code": "US",
  "indicator_code": "BCA_BP6_USD",
  "start_year": 2020,
  "frequency": "Q"
}
```

**Output**:
```json
{
  "database": "BOP",
  "country_code": "US",
  "indicator_code": "BCA_BP6_USD",
  "frequency": "Q",
  "data": [
    {
      "period": "2020-Q1",
      "value": -104523.4
    },
    {
      "period": "2020-Q2",
      "value": -98234.7
    }
  ],
  "count": 2
}
```

**Use Cases**:
- Trade balance analysis
- Current account monitoring
- Capital flow tracking
- External sector analysis

---

### 7. imf_compare_countries

**Purpose**: Compare economic indicators across multiple countries

**Input**:
```json
{
  "country_codes": ["US", "CN", "JP", "DE"],
  "database": "WEO",
  "indicator": "gdp_growth",
  "start_year": 2023,
  "frequency": "A"
}
```

**Output**:
```json
{
  "database": "WEO",
  "indicator_code": "NGDP_RPCH",
  "frequency": "A",
  "countries": [
    {
      "country_code": "US",
      "data": [
        {
          "period": "2023",
          "value": 2.5
        }
      ]
    },
    {
      "country_code": "CN",
      "data": [
        {
          "period": "2023",
          "value": 5.2
        }
      ]
    }
  ]
}
```

**Use Cases**:
- Cross-country analysis
- Benchmarking
- Regional comparisons
- Policy evaluation
- Investment research

---

### 8. imf_get_country_profile

**Purpose**: Get comprehensive economic profile with key indicators

**Input**:
```json
{
  "country_code": "IN"
}
```

**Output**:
```json
{
  "country_code": "IN",
  "country_name": "India",
  "indicators": {
    "GDP Growth": {
      "code": "NGDP_RPCH",
      "latest_value": 7.2,
      "latest_period": "2024",
      "recent_data": [
        {"period": "2022", "value": 7.0},
        {"period": "2023", "value": 6.7},
        {"period": "2024", "value": 7.2}
      ]
    },
    "Inflation": {
      "code": "PCPIPCH",
      "latest_value": 5.4,
      "latest_period": "2024"
    }
  }
}
```

**Includes**: GDP Growth, Inflation, Unemployment, Current Account, Public Debt

**Use Cases**:
- Country economic overview
- Quick assessment
- Investment research
- Executive summaries
- Dashboard creation

---

## Common Indicators

### IFS Indicators (22 total)

#### Exchange Rates
| Indicator | Code | Description |
|-----------|------|-------------|
| exchange_rate | ENDA_XDC_USD_RATE | End period exchange rate (LCU per USD) |
| exchange_rate_avg | EREA_XDC_USD_RATE | Period average exchange rate |

#### Interest Rates
| Indicator | Code | Description |
|-----------|------|-------------|
| policy_rate | FPOLM_PA | Central bank policy rate |
| treasury_bill_rate | FITB_PA | Treasury bill rate |
| deposit_rate | FDBR_PA | Deposit interest rate |
| lending_rate | FILR_PA | Lending interest rate |

#### Prices
| Indicator | Code | Description |
|-----------|------|-------------|
| cpi | PCPI_IX | Consumer Price Index |
| core_cpi | PCCOR_IX | Core CPI (excluding food & energy) |
| ppi | PPPI_IX | Producer Price Index |

#### Money Supply
| Indicator | Code | Description |
|-----------|------|-------------|
| money_supply_m1 | FM1_XDC | M1 money supply |
| money_supply_m2 | FM2_XDC | M2 money supply |
| money_supply_m3 | FM3_XDC | M3 money supply |
| reserve_money | FMRM_XDC | Reserve money (monetary base) |

#### Reserves
| Indicator | Code | Description |
|-----------|------|-------------|
| international_reserves | RAXG_USD | Total international reserves |
| gold_reserves | RAFZ_USD | Gold reserves |
| foreign_reserves | RAER_USD | Foreign exchange reserves |

#### Economic Activity
| Indicator | Code | Description |
|-----------|------|-------------|
| gdp_current | NGDP_XDC | GDP at current prices |
| gdp_constant | NGDP_R_XDC | GDP at constant prices |
| industrial_production | PINDUST_IX | Industrial production index |

#### Trade
| Indicator | Code | Description |
|-----------|------|-------------|
| exports | BXG_FOB_USD | Exports FOB |
| imports | BMG_BP6_USD | Imports CIF |

#### Labor
| Indicator | Code | Description |
|-----------|------|-------------|
| unemployment_rate | LUR_PT | Unemployment rate |

### WEO Indicators (11 total)

| Indicator | Code | Description | Unit |
|-----------|------|-------------|------|
| gdp_growth | NGDP_RPCH | Real GDP growth | Percent |
| gdp_per_capita | NGDPDPC | GDP per capita | USD |
| inflation_avg | PCPIPCH | Inflation, average | Percent |
| inflation_eop | PCPIEPCH | Inflation, end of period | Percent |
| unemployment | LUR | Unemployment rate | Percent |
| current_account | BCA_NGDPD | Current account balance | % of GDP |
| fiscal_balance | GGXCNL_NGDP | General government net lending | % of GDP |
| public_debt | GGXWDG_NGDP | General government gross debt | % of GDP |
| exports_volume | TXG_RPCH | Exports volume growth | Percent |
| imports_volume | TMG_RPCH | Imports volume growth | Percent |
| population | LP | Population | Millions |

---

## Usage Examples

### Example 1: Get US GDP Growth

```python
from tools.impl.imf_tool_refactored import IMFGetWEODataTool

tool = IMFGetWEODataTool()

# Using common indicator shorthand
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp_growth',
    'start_year': 2020,
    'end_year': 2024
})

print(f"US GDP Growth ({result['count']} observations):")
for obs in result['data']:
    print(f"  {obs['period']}: {obs['value']}%")
```

### Example 2: Compare G7 Inflation

```python
from tools.impl.imf_tool_refactored import IMFCompareCountriesTool

tool = IMFCompareCountriesTool()

result = tool.execute({
    'country_codes': ['US', 'CA', 'GB', 'FR', 'DE', 'IT', 'JP'],
    'database': 'WEO',
    'indicator': 'inflation_avg',
    'start_year': 2023
})

print("G7 Inflation Comparison:")
for country in result['countries']:
    if 'error' not in country:
        latest = country['data'][-1] if country['data'] else None
        if latest:
            print(f"  {country['country_code']}: {latest['value']}%")
```

### Example 3: Get Country Economic Profile

```python
from tools.impl.imf_tool_refactored import IMFGetCountryProfileTool

tool = IMFGetCountryProfileTool()

result = tool.execute({
    'country_code': 'CN'
})

print(f"Economic Profile: {result['country_name']} ({result['country_code']})")
print("\nKey Indicators:")

for name, data in result['indicators'].items():
    if 'error' not in data:
        print(f"\n{name}:")
        print(f"  Latest: {data['latest_value']} ({data['latest_period']})")
        print(f"  Code: {data['code']}")
```

### Example 4: Track Japan CPI (Monthly)

```python
from tools.impl.imf_tool_refactored import IMFGetIFSDataTool

tool = IMFGetIFSDataTool()

result = tool.execute({
    'country_code': 'JP',
    'indicator': 'cpi',
    'start_year': 2024,
    'frequency': 'M'
})

print(f"Japan CPI (Monthly, {result['count']} observations):")
for obs in result['data'][-12:]:  # Last 12 months
    print(f"  {obs['period']}: {obs['value']}")
```

### Example 5: Get Balance of Payments

```python
from tools.impl.imf_tool_refactored import IMFGetBOPDataTool

tool = IMFGetBOPDataTool()

result = tool.execute({
    'country_code': 'US',
    'indicator_code': 'BCA_BP6_USD',  # Current account balance
    'start_year': 2020,
    'frequency': 'Q'
})

print(f"US Current Account Balance (Quarterly):")
for obs in result['data']:
    print(f"  {obs['period']}: ${obs['value']:,.0f} million")
```

### Example 6: Discover Available Databases

```python
from tools.impl.imf_tool_refactored import IMFGetDatabasesTool

tool = IMFGetDatabasesTool()

result = tool.execute({})

print(f"Available IMF Databases ({result['count']}):\n")
for db in result['databases']:
    print(f"  {db['code']}: {db['name']}")
```

### Example 7: Generic Data Access

```python
from tools.impl.imf_tool_refactored import IMFGetDataTool

tool = IMFGetDataTool()

# Get specific indicator using direct code
result = tool.execute({
    'database': 'IFS',
    'country_code': 'GB',
    'indicator_code': 'FPOLM_PA',  # Policy rate
    'start_year': 2023,
    'frequency': 'M'
})

print(f"UK Policy Rate ({result['indicator_code']}):")
for obs in result['data']:
    print(f"  {obs['period']}: {obs['value']}%")
```

### Example 8: Emerging Markets Comparison

```python
from tools.impl.imf_tool_refactored import IMFCompareCountriesTool

tool = IMFCompareCountriesTool()

# Compare BRICS countries
result = tool.execute({
    'country_codes': ['BR', 'RU', 'IN', 'CN', 'ZA'],
    'database': 'WEO',
    'indicator': 'gdp_growth',
    'start_year': 2024
})

print("BRICS GDP Growth Comparison (2024):")
for country in result['countries']:
    if 'error' not in country and country['data']:
        latest = country['data'][-1]
        print(f"  {country['country_code']}: {latest['value']}%")
```

### Example 9: Multi-Year Analysis

```python
from tools.impl.imf_tool_refactored import IMFGetWEODataTool
import matplotlib.pyplot as plt

tool = IMFGetWEODataTool()

# Get 10 years of unemployment data
result = tool.execute({
    'country_code': 'US',
    'indicator': 'unemployment',
    'start_year': 2014,
    'end_year': 2024
})

# Extract data
years = [obs['period'] for obs in result['data']]
values = [obs['value'] for obs in result['data']]

# Plot
plt.figure(figsize=(12, 6))
plt.plot(years, values, marker='o', linewidth=2)
plt.title('US Unemployment Rate (2014-2024)')
plt.xlabel('Year')
plt.ylabel('Unemployment Rate (%)')
plt.grid(True)
plt.tight_layout()
plt.show()
```

### Example 10: Cross-Database Analysis

```python
# Combine IFS and WEO data for comprehensive analysis

from tools.impl.imf_tool_refactored import IMFGetIFSDataTool, IMFGetWEODataTool

ifs_tool = IMFGetIFSDataTool()
weo_tool = IMFGetWEODataTool()

country = 'DE'

# Get CPI from IFS (monthly)
cpi = ifs_tool.execute({
    'country_code': country,
    'indicator': 'cpi',
    'start_year': 2024,
    'frequency': 'M'
})

# Get GDP growth from WEO (annual)
gdp = weo_tool.execute({
    'country_code': country,
    'indicator': 'gdp_growth',
    'start_year': 2024
})

print(f"Germany Economic Analysis:")
print(f"\nCPI (Monthly): {len(cpi['data'])} observations")
print(f"GDP Growth: {gdp['data'][-1]['value']}% in {gdp['data'][-1]['period']}")
```

---

## Schema Reference

### Common Input Parameters

```json
{
  "country_code": {
    "type": "string",
    "description": "ISO 2-letter country code (e.g., 'US', 'CN', 'JP')"
  },
  "database": {
    "type": "string",
    "enum": ["IFS", "DOT", "BOP", "GFSR", "FSI", "WEO", "GFSMAB", "CDIS", "CPIS", "WHDREO"]
  },
  "indicator_code": {
    "type": "string",
    "description": "IMF indicator code"
  },
  "start_year": {
    "type": "integer",
    "minimum": 1950,
    "maximum": 2030
  },
  "end_year": {
    "type": "integer",
    "minimum": 1950,
    "maximum": 2030
  },
  "frequency": {
    "type": "string",
    "enum": ["A", "Q", "M"],
    "description": "A=Annual, Q=Quarterly, M=Monthly"
  }
}
```

### Common Output Format

```json
{
  "database": "string",
  "country_code": "string",
  "indicator_code": "string",
  "frequency": "string",
  "data": [
    {
      "period": "string (YYYY or YYYY-MM or YYYY-QN)",
      "value": "number or null"
    }
  ],
  "count": "integer"
}
```

### Country Comparison Output

```json
{
  "database": "string",
  "indicator_code": "string",
  "frequency": "string",
  "countries": [
    {
      "country_code": "string",
      "data": [
        {
          "period": "string",
          "value": "number or null"
        }
      ],
      "error": "string (if error occurred)"
    }
  ]
}
```

### Country Profile Output

```json
{
  "country_code": "string",
  "country_name": "string",
  "indicators": {
    "GDP Growth": {
      "code": "string",
      "latest_value": "number or null",
      "latest_period": "string",
      "recent_data": [
        {
          "period": "string",
          "value": "number or null"
        }
      ],
      "error": "string (if error)"
    }
  }
}
```

---

## Limitations

### API Limitations

1. **Data Availability**:
   - Historical data varies by country and indicator
   - Some indicators may not be available for all countries
   - Recent data may have revisions

2. **Update Frequency**:
   - WEO: Updated biannually (April, October)
   - IFS: Monthly updates
   - BOP: Quarterly/Annual updates
   - Other databases vary

3. **No Real-Time Limits**:
   - No explicit rate limits
   - Fair use policy applies
   - Large requests may be slow

4. **Data Coverage**:
   - Not all countries report all indicators
   - Data gaps common for developing countries
   - Historical coverage varies

### Technical Limitations

1. **Response Format**:
   - JSON only (SDMX-JSON)
   - Some complex queries may timeout
   - Large date ranges may be slow

2. **Error Handling**:
   - HTTP 404 for missing data
   - No data returns empty array
   - Network timeouts possible

3. **Country Codes**:
   - Must use ISO 2-letter codes
   - Some territories use different codes
   - Regional aggregates have special codes

### Data Interpretation Caveats

1. **Revisions**:
   - Economic data subject to revisions
   - Preliminary vs final releases
   - Historical values may change

2. **Forecasts**:
   - WEO includes forecasts for future years
   - Forecasts are estimates, not actuals
   - Updated biannually

3. **Methodology**:
   - Different countries may use different methods
   - Comparability may be limited
   - Read methodology notes

---

## Error Handling

### Common Errors

#### 1. Data Not Found (HTTP 404)
```python
ValueError: Data not found for US/INVALID_CODE in IFS
```

**Causes**:
- Invalid indicator code
- Country doesn't report this indicator
- Data not available for time period

**Solutions**:
- Use `imf_get_dataflows` to discover available indicators
- Check country data availability
- Try different time periods

#### 2. No Data Available
```json
{
  "data": [],
  "count": 0,
  "note": "No data available"
}
```

**Causes**:
- Time period outside data coverage
- Country doesn't report indicator
- Data not yet published

**Solutions**:
- Broaden date range
- Check data availability
- Try related indicators

#### 3. Network Timeout
```python
ValueError: Failed to get IMF data: timeout
```

**Causes**:
- Large date range
- Server busy
- Network issues

**Solutions**:
- Reduce date range
- Retry request
- Split into smaller requests

### Error Handling Best Practices

```python
from typing import Optional, Dict

def safe_imf_query(tool, arguments: Dict) -> Optional[Dict]:
    """
    Query IMF data with error handling
    
    Args:
        tool: IMF tool instance
        arguments: Query arguments
    
    Returns:
        Data or None if error
    """
    try:
        result = tool.execute(arguments)
        
        # Check if data is available
        if result.get('count', 0) == 0:
            print(f"⚠️  No data available")
            return None
        
        return result
        
    except ValueError as e:
        error_msg = str(e)
        
        if 'not found' in error_msg.lower():
            print(f"❌ Data not found: Check indicator code and country")
        elif 'timeout' in error_msg.lower():
            print(f"⚠️  Request timeout: Try reducing date range")
        else:
            print(f"❌ Error: {error_msg}")
        
        return None
    
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None

# Usage
result = safe_imf_query(tool, {
    'country_code': 'US',
    'indicator': 'gdp_growth',
    'start_year': 2020
})

if result:
    print(f"✓ Retrieved {result['count']} observations")
```

### Handling Missing Data

```python
def get_latest_value(data_result: Dict) -> Optional[float]:
    """
    Get latest non-null value from IMF data result
    
    Args:
        data_result: IMF tool result
    
    Returns:
        Latest value or None
    """
    if not data_result.get('data'):
        return None
    
    # Search backwards for non-null value
    for obs in reversed(data_result['data']):
        if obs['value'] is not None:
            return obs['value']
    
    return None

# Usage
result = tool.execute({'country_code': 'US', 'indicator': 'gdp_growth'})
latest = get_latest_value(result)

if latest:
    print(f"Latest GDP growth: {latest}%")
else:
    print("No data available")
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta
import hashlib
import json

class IMFCache:
    """Cache for IMF data queries"""
    
    def __init__(self, ttl_hours: int = 24):
        self.cache = {}
        self.ttl = timedelta(hours=ttl_hours)
    
    def _make_key(self, **kwargs) -> str:
        """Create cache key from arguments"""
        param_str = json.dumps(kwargs, sort_keys=True)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def get(self, **kwargs) -> Optional[Dict]:
        """Get cached result if available"""
        key = self._make_key(**kwargs)
        
        if key in self.cache:
            result, timestamp = self.cache[key]
            
            if datetime.now() - timestamp < self.ttl:
                return result
            else:
                del self.cache[key]
        
        return None
    
    def set(self, result: Dict, **kwargs):
        """Cache result"""
        key = self._make_key(**kwargs)
        self.cache[key] = (result, datetime.now())

# Usage
cache = IMFCache(ttl_hours=24)

def cached_query(tool, **kwargs):
    """Query with caching"""
    cached = cache.get(**kwargs)
    if cached:
        print("✓ Using cached result")
        return cached
    
    result = tool.execute(kwargs)
    cache.set(result, **kwargs)
    print("✓ Result cached")
    
    return result
```

### Batch Processing

```python
def batch_country_comparison(
    tool,
    countries: List[str],
    indicator: str,
    year: int,
    batch_size: int = 5
) -> Dict:
    """
    Compare countries in batches to avoid overload
    
    Args:
        tool: IMFCompareCountriesTool instance
        countries: List of country codes
        indicator: Indicator to compare
        year: Year to compare
        batch_size: Countries per batch
    
    Returns:
        Combined results
    """
    import time
    
    all_results = []
    
    # Process in batches
    for i in range(0, len(countries), batch_size):
        batch = countries[i:i+batch_size]
        
        print(f"Processing batch {i//batch_size + 1}...")
        
        result = tool.execute({
            'country_codes': batch,
            'indicator': indicator,
            'start_year': year
        })
        
        all_results.extend(result['countries'])
        
        # Brief pause between batches
        if i + batch_size < len(countries):
            time.sleep(1)
    
    return {
        'indicator': indicator,
        'year': year,
        'countries': all_results
    }
```

### Query Optimization

| Strategy | Benefit | Use Case |
|----------|---------|----------|
| Limit date range | Faster response | Recent data only |
| Use annual frequency | Smaller response | Long-term trends |
| Cache results | Avoid duplicate queries | Repeated access |
| Batch requests | Manage load | Multiple countries |

### Recommended Cache TTL

| Data Type | Update Frequency | Recommended TTL |
|-----------|------------------|-----------------|
| WEO forecasts | Biannual | 180 days |
| IFS monthly data | Monthly | 7 days |
| BOP quarterly | Quarterly | 30 days |
| Historical data (>2 years old) | Rarely changes | 90 days |

---

## Appendix A: Country Codes

### G7 Countries
| Code | Country |
|------|---------|
| US | United States |
| CA | Canada |
| GB | United Kingdom |
| FR | France |
| DE | Germany |
| IT | Italy |
| JP | Japan |

### G20 Countries
| Code | Country | Code | Country |
|------|---------|------|---------|
| AR | Argentina | KR | South Korea |
| AU | Australia | MX | Mexico |
| BR | Brazil | RU | Russia |
| CN | China | SA | Saudi Arabia |
| IN | India | TR | Turkey |
| ID | Indonesia | ZA | South Africa |

### BRICS
| Code | Country |
|------|---------|
| BR | Brazil |
| RU | Russia |
| IN | India |
| CN | China |
| ZA | South Africa |

---

## Appendix B: Quick Reference

### Tool Selection Guide

| Need | Use Tool |
|------|----------|
| List databases | imf_get_databases |
| Discover indicators | imf_get_dataflows |
| Generic access | imf_get_data |
| Financial statistics | imf_get_ifs_data |
| GDP, inflation, forecasts | imf_get_weo_data |
| Trade, current account | imf_get_bop_data |
| Compare countries | imf_compare_countries |
| Country overview | imf_get_country_profile |

### Common Workflows

**Workflow 1: Quick Country Assessment**
1. `imf_get_country_profile` - Get comprehensive overview
2. Analyze key indicators

**Workflow 2: Detailed Analysis**
1. `imf_get_databases` - Explore available databases
2. `imf_get_dataflows` - Find indicators
3. `imf_get_data` - Retrieve specific data

**Workflow 3: Cross-Country Study**
1. `imf_compare_countries` - Get comparative data
2. Analyze differences and patterns

### Frequency Codes

| Code | Meaning | Typical Use |
|------|---------|-------------|
| A | Annual | GDP, fiscal data |
| Q | Quarterly | BOP, growth rates |
| M | Monthly | CPI, rates, reserves |

---

## Appendix C: IMF Resources

### Official Resources

- **IMF Data**: https://data.imf.org
- **API Documentation**: http://datahelp.imf.org/knowledgebase/articles/667681
- **WEO Database**: https://www.imf.org/external/pubs/ft/weo/
- **IFS Database**: https://data.imf.org/?sk=4c514d48-b6ba-49ed-8ab9-52b0c1a0179b
- **BOP Database**: https://data.imf.org/?sk=7A51304B-6426-40C0-83DD-CA473CA1FD52

### Data Documentation

- **Metadata Explorer**: https://data.imf.org/regular.aspx?key=61545867
- **Country Notes**: Included in database documentation
- **Methodologies**: Available on IMF website

### Support

- **Data Questions**: data@imf.org
- **Technical Support**: Available through IMF Data Help Center

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025 | Initial release with 8 tools |

---

## Support & Contact

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Copyright**: © 2025-2030 All Rights Reserved

For issues, questions, or feature requests, please contact the author directly.

---

*End of IMF MCP Tool Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **IMF (International Monetary Fund)**: An international organization promoting global monetary cooperation and financial stability.

- **Balance of Payments**: A record of all economic transactions between residents of a country and the rest of the world.

- **Exchange Rate**: The price of one currency in terms of another. IMF provides official exchange rate data.

- **Special Drawing Rights (SDR)**: An international reserve asset created by the IMF to supplement member countries' official reserves.

- **World Economic Outlook (WEO)**: IMF's flagship publication with analysis and projections of the global economy.

- **Financial Soundness Indicators**: Statistics measuring the health of financial institutions and markets in a country.

- **Current Account**: Part of balance of payments recording trade in goods, services, income, and current transfers.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
