# European Central Bank MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technical Details](#technical-details)
4. [Authentication & API Keys](#authentication--api-keys)
5. [Tool Descriptions](#tool-descriptions)
6. [Data Flow Identifiers](#data-flow-identifiers)
7. [Usage Examples](#usage-examples)
8. [Schema Reference](#schema-reference)
9. [Limitations](#limitations)
10. [Error Handling](#error-handling)
11. [Performance Considerations](#performance-considerations)

---

## Overview

The European Central Bank (ECB) MCP Tool Suite is a comprehensive collection of 8 specialized tools designed to retrieve economic and financial data from the European Central Bank's Statistical Data Warehouse. These tools provide programmatic access to critical Euro Area economic indicators including exchange rates, interest rates, bond yields, inflation metrics, and monetary aggregates.

### Key Features

- **No Authentication Required**: Public API access without API keys
- **Real-time Data**: Access to the latest Euro Area economic indicators
- **Historical Data**: Retrieve time series data with flexible date ranges
- **Specialized Tools**: Purpose-built tools for specific data categories
- **Batch Operations**: Retrieve multiple indicators in a single call
- **Discovery Tools**: Search and explore available data series

### Supported Data Categories

- Foreign Exchange Rates (EUR pairs)
- ECB Policy Interest Rates
- Government Bond Yields
- HICP Inflation Measures
- GDP & Unemployment
- Monetary Aggregates (M1, M2, M3)

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
│  • ecb_get_series                                        │
│  • ecb_get_exchange_rate                                 │
│  • ecb_get_interest_rate                                 │
│  • ecb_get_bond_yield                                    │
│  • ecb_get_inflation                                     │
│  • ecb_get_latest                                        │
│  • ecb_search_series                                     │
│  • ecb_get_common_indicators                             │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│   EuropeanCentralBankBaseTool (Shared Functionality)    │
├──────────────────────────────────────────────────────────┤
│  • API URL: data-api.ecb.europa.eu/service/data         │
│  • Common Series Definitions (21 indicators)             │
│  • HTTP Client (urllib)                                  │
│  • JSON Parser                                           │
│  • Date Range Calculator                                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│         ECB Statistical Data Warehouse API               │
│         https://data-api.ecb.europa.eu                   │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── EuropeanCentralBankBaseTool
            │
            ├── ECBGetSeriesTool
            ├── ECBGetExchangeRateTool
            ├── ECBGetInterestRateTool
            ├── ECBGetBondYieldTool
            ├── ECBGetInflationTool
            ├── ECBGetLatestTool
            ├── ECBSearchSeriesTool
            └── ECBGetCommonIndicatorsTool
```

### Component Descriptions

#### EuropeanCentralBankBaseTool
Base class providing:
- API endpoint configuration
- Common series definitions (21 pre-configured indicators)
- Shared HTTP request handling via `_fetch_series()` method
- JSON response parsing
- Error handling and logging

#### Individual Tool Classes
Each tool specializes in a specific data retrieval pattern:
- Custom input/output schemas
- Domain-specific validation
- Specialized query parameter handling
- Tailored response formatting

---

## Technical Details

### Data Retrieval Method

**Type**: REST API Calls  
**Protocol**: HTTPS  
**Method**: HTTP GET  
**Format**: JSON

**Not Used**:
- ✗ Web Scraping
- ✗ HTML Parsing
- ✗ Database Queries
- ✗ File System Access
- ✗ WebSocket Streaming

### API Communication

The tools communicate with the ECB Statistical Data Warehouse using standard REST API calls:

```python
# Base URL
https://data-api.ecb.europa.eu/service/data

# Request Format
GET /{flow}/{key}?format=jsondata&detail=dataonly&startPeriod={date}&endPeriod={date}

# Example
GET /EXR/D.USD.EUR.SP00.A?format=jsondata&detail=dataonly&startPeriod=2024-01-01
```

### HTTP Request Details

**Headers**:
```python
{
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json'
}
```

**Parameters**:
- `format=jsondata`: JSON response format
- `detail=dataonly`: Minimal metadata, focus on observations
- `startPeriod`: Start date (YYYY-MM-DD)
- `endPeriod`: End date (YYYY-MM-DD)

**Timeout**: 30 seconds per request

### Response Parsing

The ECB API returns data in a nested JSON structure:

```json
{
  "dataSets": [{
    "series": {
      "0:0:0:0:0": {
        "observations": {
          "0": [1.0845],
          "1": [1.0832],
          "2": [1.0820]
        }
      }
    }
  }],
  "structure": {
    "dimensions": {
      "observation": [{
        "values": [
          {"id": "2024-01-01"},
          {"id": "2024-01-02"},
          {"id": "2024-01-03"}
        ]
      }]
    }
  }
}
```

The tools parse this structure to extract date-value pairs.

---

## Authentication & API Keys

### No Authentication Required

The ECB Statistical Data Warehouse is a **public API** that does **not require**:
- API Keys
- OAuth tokens
- Username/Password
- Registration
- Rate limit authentication

### Access Control

- **Open Access**: Anyone can access the API
- **Rate Limiting**: Enforced at the API gateway level (not user-specific)
- **Fair Use**: Users should implement reasonable caching and avoid excessive requests

### Recommended Rate Limit

The tools implement a suggested rate limit of **120 requests per hour** per tool, though this is not strictly enforced by the API.

### Cache Strategy

- **cacheTTL**: 3600 seconds (1 hour) for real-time data
- **cacheTTL**: 86400 seconds (24 hours) for metadata (search_series)

---

## Tool Descriptions

### 1. ecb_get_series

**Purpose**: Generic time series retrieval for any ECB data series

**Use Cases**:
- Retrieve any ECB time series by flow/key combination
- Custom date range analysis
- Access to 21 pre-configured common indicators

**Input Parameters**:
```json
{
  "flow": "EXR",           // Optional if using indicator
  "key": "D.USD.EUR.SP00.A",  // Optional if using indicator
  "indicator": "eur_usd",   // Optional shorthand
  "start_date": "2024-01-01",  // Optional
  "end_date": "2024-12-31",    // Optional
  "recent_periods": 10      // Default: 10
}
```

**Output**:
```json
{
  "flow": "EXR",
  "key": "D.USD.EUR.SP00.A",
  "series_name": "USD/EUR Exchange Rate",
  "description": "EUR/USD Exchange Rate Daily",
  "observation_count": 252,
  "observations": [
    {"date": "2024-01-01", "value": 1.0845},
    {"date": "2024-01-02", "value": 1.0832}
  ]
}
```

---

### 2. ecb_get_exchange_rate

**Purpose**: Specialized tool for foreign exchange rates

**Supported Currency Pairs**:
- EUR/USD (eur_usd)
- EUR/GBP (eur_gbp)
- EUR/JPY (eur_jpy)
- EUR/CNY (eur_cny)
- EUR/CHF (eur_chf)

**Input Parameters**:
```json
{
  "currency_pair": "EUR/USD",  // OR use indicator
  "indicator": "eur_usd",      // Shorthand option
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Use Cases**:
- Currency trading analysis
- FX risk management
- International business planning
- Currency hedging strategies

---

### 3. ecb_get_interest_rate

**Purpose**: Retrieve ECB policy rates and money market rates

**Available Rate Types**:
1. **main_refinancing_rate** - Primary ECB policy rate
2. **deposit_facility_rate** - Floor for overnight rates
3. **marginal_lending_rate** - Ceiling for overnight rates
4. **eonia** - Euro OverNight Index Average (legacy)
5. **ester** - Euro Short-Term Rate (€STR, replaced EONIA)

**Input Parameters**:
```json
{
  "rate_type": "main_refinancing_rate",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Note**: €STR replaced EONIA as the official overnight reference rate in 2022.

---

### 4. ecb_get_bond_yield

**Purpose**: Euro Area government bond yields for yield curve analysis

**Bond Maturities**:
- **2y** - 2-Year benchmark
- **5y** - 5-Year benchmark
- **10y** - 10-Year benchmark (most widely watched)

**Input Parameters**:
```json
{
  "bond_term": "10y",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 10
}
```

**Use Cases**:
- Yield curve analysis
- Fixed income trading
- Monetary policy research
- Investment portfolio management
- Economic forecasting
- Risk assessment

**Note**: Yields are GDP-weighted averages across Euro Area countries.

---

### 5. ecb_get_inflation

**Purpose**: HICP (Harmonised Index of Consumer Prices) inflation measures

**Inflation Types**:
1. **overall** - HICP All Items (headline inflation)
2. **core** - HICP excluding energy and food (underlying inflation)
3. **energy** - HICP Energy component only (most volatile)

**Input Parameters**:
```json
{
  "inflation_type": "overall",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "recent_periods": 12
}
```

**Output Format**:
- Values represent annual rate of change (%)
- Monthly frequency
- ECB targets 2% inflation

**Use Cases**:
- Inflation tracking
- Monetary policy analysis
- Real return calculations
- Economic forecasting

---

### 6. ecb_get_latest

**Purpose**: Retrieve only the most recent observation for any series

**Optimization**: Minimal payload size (~200 bytes vs ~2KB for time series)

**Input Parameters**:
```json
{
  "flow": "EXR",              // Option 1: Use flow/key
  "key": "D.USD.EUR.SP00.A",
  // OR
  "indicator": "eur_usd"      // Option 2: Use shorthand
}
```

**Output**:
```json
{
  "flow": "EXR",
  "key": "D.USD.EUR.SP00.A",
  "series_name": "USD/EUR Exchange Rate",
  "description": "EUR/USD Exchange Rate Daily",
  "date": "2024-10-31",
  "value": 1.0845
}
```

**Use Cases**:
- Real-time dashboards
- Status displays
- Trading terminals
- Mobile apps (bandwidth-conscious)
- Alerting systems

---

### 7. ecb_search_series

**Purpose**: Discovery tool to explore available data series

**Input Parameters**:
```json
{
  "category": "Exchange Rates"  // Optional filter
}
```

**Available Categories**:
- Exchange Rates (5 series)
- Interest Rates (5 series)
- Bond Yields (3 series)
- Inflation (HICP) (3 series)
- Economic Indicators (2 series)
- Money Supply (3 series)

**Output**:
```json
{
  "categories": {
    "Exchange Rates": [
      {
        "indicator": "eur_usd",
        "flow": "EXR",
        "key": "D.USD.EUR.SP00.A",
        "description": "EUR/USD Exchange Rate Daily"
      }
    ]
  },
  "total_series": 21
}
```

**Use Cases**:
- Initial API exploration
- Documentation generation
- Building UI selection dropdowns
- Understanding available indicators

**Note**: This tool returns metadata only, no actual economic data.

---

### 8. ecb_get_common_indicators

**Purpose**: Batch retrieval of multiple indicators with consistent timestamp

**Default Indicators** (if none specified):
1. eur_usd - EUR/USD exchange rate
2. main_refinancing_rate - Primary ECB policy rate
3. bond_10y - 10-year government bond yield
4. hicp_overall - Headline inflation
5. unemployment_rate - Labor market indicator

**Input Parameters**:
```json
{
  "indicators": [
    "eur_usd",
    "main_refinancing_rate",
    "bond_10y",
    "hicp_overall",
    "gdp",
    "unemployment_rate"
  ]
}
```

**Output**:
```json
{
  "indicators": {
    "eur_usd": {
      "flow": "EXR",
      "key": "D.USD.EUR.SP00.A",
      "description": "EUR/USD Exchange Rate Daily",
      "value": 1.0845,
      "date": "2024-10-31"
    },
    "main_refinancing_rate": {
      "flow": "FM",
      "key": "B.U2.EUR.4F.KR.MRR_FR.LEV",
      "description": "Main Refinancing Operations Rate",
      "value": 4.25,
      "date": "2024-09-18"
    }
  },
  "last_updated": "2024-10-31T14:30:00.000Z"
}
```

**Use Cases**:
- Economic dashboards
- Market overview displays
- Morning briefing reports
- Executive summaries
- Email alerts with multiple metrics

**Performance**: Makes N API calls for N indicators but returns unified response with consistent timestamp.

---

## Data Flow Identifiers

Understanding ECB data flows is essential for using the generic `ecb_get_series` tool:

| Flow | Name | Description |
|------|------|-------------|
| **EXR** | Exchange Rates | Foreign exchange rates, EUR vs other currencies |
| **FM** | Financial Markets | Interest rates, money market rates, policy rates |
| **YC** | Yield Curves | Government bond yields, various maturities |
| **ICP** | HICP | Harmonised Index of Consumer Prices (inflation) |
| **MNA** | National Accounts | GDP, economic output measures |
| **BSI** | Balance Sheet Items | Monetary aggregates (M1, M2, M3) |
| **LFSI** | Labour Force Survey | Unemployment, employment statistics |

### Flow-Key Examples

```
EXR/D.USD.EUR.SP00.A
│   │ │   │   │    │
│   │ │   │   │    └─ A = Average
│   │ │   │   └────── SP00 = Spot rate
│   │ │   └────────── EUR = Euro (quote currency)
│   │ └────────────── USD = US Dollar (base currency)
│   └──────────────── D = Daily frequency
└──────────────────── Exchange Rate flow

FM/B.U2.EUR.4F.KR.MRR_FR.LEV
│  │ │  │   │  │  │       │
│  │ │  │   │  │  │       └─ LEV = Level
│  │ │  │   │  │  └───────── MRR_FR = Main Refinancing Rate
│  │ │  │   │  └──────────── KR = Key rate
│  │ │  │   └─────────────── 4F = Financial corporations
│  │ │  └─────────────────── EUR = Euro
│  │ └────────────────────── U2 = Euro Area 19
│  └──────────────────────── B = Business (month-end)
└─────────────────────────── Financial Markets flow
```

---

## Usage Examples

### Example 1: Get Latest EUR/USD Rate

```python
from tools.impl.european_central_bank_tool_refactored import ECBGetLatestTool

tool = ECBGetLatestTool()
result = tool.execute({
    "indicator": "eur_usd"
})

print(f"EUR/USD: {result['value']} on {result['date']}")
# Output: EUR/USD: 1.0845 on 2024-10-31
```

### Example 2: Analyze Yield Curve

```python
from tools.impl.european_central_bank_tool_refactored import ECBGetBondYieldTool

tool = ECBGetBondYieldTool()

# Get 2-year yield
yield_2y = tool.execute({
    "bond_term": "2y",
    "recent_periods": 1
})

# Get 10-year yield
yield_10y = tool.execute({
    "bond_term": "10y",
    "recent_periods": 1
})

spread = yield_10y['observations'][-1]['value'] - yield_2y['observations'][-1]['value']
print(f"2s10s Spread: {spread:.2f}%")
```

### Example 3: Create Economic Dashboard

```python
from tools.impl.european_central_bank_tool_refactored import ECBGetCommonIndicatorsTool

tool = ECBGetCommonIndicatorsTool()
result = tool.execute({
    "indicators": [
        "eur_usd",
        "main_refinancing_rate",
        "bond_10y",
        "hicp_overall",
        "unemployment_rate"
    ]
})

print("Euro Area Economic Dashboard")
print(f"Last Updated: {result['last_updated']}")
print("=" * 50)

for indicator, data in result['indicators'].items():
    if 'error' not in data:
        print(f"{data['description']}: {data['value']} ({data['date']})")
```

### Example 4: Historical Inflation Analysis

```python
from tools.impl.european_central_bank_tool_refactored import ECBGetInflationTool
import matplotlib.pyplot as plt

tool = ECBGetInflationTool()
result = tool.execute({
    "inflation_type": "overall",
    "start_date": "2020-01-01",
    "end_date": "2024-10-31"
})

dates = [obs['date'] for obs in result['observations']]
values = [obs['value'] for obs in result['observations']]

plt.figure(figsize=(12, 6))
plt.plot(dates, values)
plt.axhline(y=2.0, color='r', linestyle='--', label='ECB Target (2%)')
plt.title('Euro Area HICP Inflation')
plt.xlabel('Date')
plt.ylabel('Annual Rate (%)')
plt.legend()
plt.grid(True)
plt.show()
```

### Example 5: Compare Interest Rates

```python
from tools.impl.european_central_bank_tool_refactored import ECBGetInterestRateTool

tool = ECBGetInterestRateTool()

rates = {}
for rate_type in ['main_refinancing_rate', 'deposit_facility_rate', 'marginal_lending_rate']:
    result = tool.execute({
        "rate_type": rate_type,
        "recent_periods": 1
    })
    rates[rate_type] = result['observations'][-1]['value']

print("ECB Interest Rate Corridor:")
print(f"Marginal Lending: {rates['marginal_lending_rate']}%")
print(f"Main Refinancing: {rates['main_refinancing_rate']}%")
print(f"Deposit Facility: {rates['deposit_facility_rate']}%")
```

### Example 6: Discover Available Series

```python
from tools.impl.european_central_bank_tool_refactored import ECBSearchSeriesTool

tool = ECBSearchSeriesTool()
result = tool.execute({
    "category": "Exchange Rates"
})

print(f"Available Exchange Rate Series: {len(result['categories']['Exchange Rates'])}")
for series in result['categories']['Exchange Rates']:
    print(f"- {series['indicator']}: {series['description']}")
```

---

## Schema Reference

### Common Input Schema Elements

#### Date Parameters
```json
{
  "start_date": {
    "type": "string",
    "format": "YYYY-MM-DD",
    "example": "2024-01-01"
  },
  "end_date": {
    "type": "string",
    "format": "YYYY-MM-DD",
    "example": "2024-12-31"
  }
}
```

#### Recent Periods
```json
{
  "recent_periods": {
    "type": "integer",
    "minimum": 1,
    "maximum": 100,
    "default": 10,
    "description": "Number of most recent observations"
  }
}
```

#### Indicator Shortcuts
```json
{
  "indicator": {
    "type": "string",
    "enum": [
      "eur_usd", "eur_gbp", "eur_jpy", "eur_cny", "eur_chf",
      "main_refinancing_rate", "deposit_facility_rate", "marginal_lending_rate",
      "eonia", "ester",
      "bond_2y", "bond_5y", "bond_10y",
      "hicp_overall", "hicp_core", "hicp_energy",
      "gdp", "unemployment_rate",
      "m1", "m2", "m3"
    ]
  }
}
```

### Common Output Schema Elements

#### Time Series Response
```json
{
  "flow": "string",
  "key": "string",
  "series_name": "string",
  "description": "string",
  "observation_count": "integer",
  "observations": [
    {
      "date": "YYYY-MM-DD",
      "value": "number | null"
    }
  ]
}
```

#### Latest Value Response
```json
{
  "flow": "string",
  "key": "string",
  "series_name": "string",
  "description": "string",
  "date": "YYYY-MM-DD",
  "value": "number | null"
}
```

#### Error Response
```json
{
  "flow": "string",
  "key": "string",
  "error": "string",
  "observation_count": 0,
  "observations": []
}
```

---

## Limitations

### API Limitations

1. **Data Availability**:
   - Only publicly released ECB data
   - Some series may have publication delays
   - Historical data depth varies by series

2. **Update Frequency**:
   - Daily: Exchange rates, money market rates
   - Weekly/Monthly: Policy rates (changed at ECB meetings)
   - Monthly: Inflation, unemployment
   - Quarterly: GDP

3. **Data Gaps**:
   - Weekends and holidays (for daily series)
   - Series may have null values for specific dates
   - Publication schedules vary by indicator

### Technical Limitations

1. **Rate Limiting**:
   - Recommended: 120 requests/hour per tool
   - No hard enforcement, but excessive use discouraged
   - Consider implementing local caching

2. **Request Size**:
   - Maximum 100 recent periods per request
   - Large date ranges may return substantial data
   - Response size varies by series frequency

3. **Timeout**:
   - 30-second timeout per request
   - Network issues may cause failures
   - Retry logic recommended for production use

4. **Data Format**:
   - JSON only (no XML support)
   - Values are numbers or null (missing data)
   - Dates in ISO format (YYYY-MM-DD or YYYY-MM)

### Tool-Specific Limitations

1. **ecb_get_exchange_rate**:
   - Limited to 5 major currency pairs
   - EUR as base currency only
   - Daily frequency only

2. **ecb_get_bond_yield**:
   - Only 2Y, 5Y, 10Y maturities
   - Euro Area aggregate only (not individual countries)
   - GDP-weighted averages

3. **ecb_get_inflation**:
   - HICP only (no national CPIs)
   - Three types only (overall, core, energy)
   - Monthly frequency only

4. **ecb_search_series**:
   - Limited to 21 pre-configured series
   - Does not search entire ECB database
   - Static catalog (updated with tool releases)

---

## Error Handling

### Common Errors

#### 1. No Data Available
```json
{
  "error": "No data available",
  "observation_count": 0,
  "observations": []
}
```

**Causes**:
- Series not yet published for requested period
- Invalid flow/key combination
- Date range before series start date

**Solution**: Check ECB data calendar, verify flow/key, adjust date range

#### 2. Network Timeout
```python
urllib.error.URLError: <urlopen error timed out>
```

**Causes**:
- Network connectivity issues
- ECB API temporary unavailability
- Firewall blocking requests

**Solution**: Implement retry logic with exponential backoff

#### 3. Invalid Date Format
```json
{
  "error": "Invalid date format. Use YYYY-MM-DD"
}
```

**Solution**: Ensure dates follow ISO format YYYY-MM-DD

#### 4. Unknown Indicator
```json
{
  "error": "Unknown indicator: xyz"
}
```

**Solution**: Use `ecb_search_series` to find valid indicators

### Error Handling Best Practices

```python
def fetch_with_retry(tool, arguments, max_retries=3):
    """Fetch data with retry logic"""
    for attempt in range(max_retries):
        try:
            result = tool.execute(arguments)
            if 'error' in result:
                print(f"API Error: {result['error']}")
                return None
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Failed after {max_retries} attempts: {e}")
                return None
            print(f"Attempt {attempt + 1} failed, retrying...")
            time.sleep(2 ** attempt)  # Exponential backoff
    return None
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=128)
def get_latest_cached(indicator: str, cache_minutes: int = 60):
    """Cache latest values for specified duration"""
    tool = ECBGetLatestTool()
    result = tool.execute({"indicator": indicator})
    return result
```

### Batch Operations

**Inefficient** - Multiple individual calls:
```python
# BAD: 5 separate API calls
eur_usd = get_latest("eur_usd")
rate = get_latest("main_refinancing_rate")
bond = get_latest("bond_10y")
inflation = get_latest("hicp_overall")
unemployment = get_latest("unemployment_rate")
```

**Efficient** - Single batch call:
```python
# GOOD: 1 tool call (still 5 API calls, but unified response)
tool = ECBGetCommonIndicatorsTool()
dashboard = tool.execute({
    "indicators": ["eur_usd", "main_refinancing_rate", "bond_10y", 
                   "hicp_overall", "unemployment_rate"]
})
```

### Response Size Optimization

| Tool | Avg Response Size | Use When |
|------|-------------------|----------|
| ecb_get_latest | ~200 bytes | Need single current value |
| ecb_get_series (10 obs) | ~1 KB | Need short time series |
| ecb_get_series (100 obs) | ~8 KB | Need historical analysis |
| ecb_get_common_indicators | ~2 KB | Need multiple current values |

### Recommended Cache TTL

| Data Type | Update Frequency | Recommended Cache TTL |
|-----------|------------------|----------------------|
| Exchange Rates | Daily | 1 hour |
| Policy Rates | Meeting dates | 24 hours |
| Bond Yields | Daily | 1 hour |
| Inflation | Monthly | 24 hours |
| GDP | Quarterly | 7 days |
| Metadata (search) | Static | 30 days |

---

## Appendix A: Complete Indicator Reference

### Exchange Rates (EXR Flow)

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| eur_usd | EUR/USD Exchange Rate Daily | EXR | D.USD.EUR.SP00.A |
| eur_gbp | EUR/GBP Exchange Rate Daily | EXR | D.GBP.EUR.SP00.A |
| eur_jpy | EUR/JPY Exchange Rate Daily | EXR | D.JPY.EUR.SP00.A |
| eur_cny | EUR/CNY Exchange Rate Daily | EXR | D.CNY.EUR.SP00.A |
| eur_chf | EUR/CHF Exchange Rate Daily | EXR | D.CHF.EUR.SP00.A |

### Interest Rates (FM Flow)

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| main_refinancing_rate | Main Refinancing Operations Rate | FM | B.U2.EUR.4F.KR.MRR_FR.LEV |
| deposit_facility_rate | Deposit Facility Rate | FM | B.U2.EUR.4F.KR.DFR.LEV |
| marginal_lending_rate | Marginal Lending Facility Rate | FM | B.U2.EUR.4F.KR.MLFR.LEV |
| eonia | Euro OverNight Index Average | FM | D.U2.EUR.4F.KR.EON.LEV |
| ester | Euro Short-Term Rate (€STR) | FM | D.U2.EUR.4F.KR.ESTER.LEV |

### Bond Yields (YC Flow)

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| bond_2y | 2-Year Euro Area Government Bond Yield | YC | B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y |
| bond_5y | 5-Year Euro Area Government Bond Yield | YC | B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y |
| bond_10y | 10-Year Euro Area Government Bond Yield | YC | B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y |

### Inflation (ICP Flow)

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| hicp_overall | HICP - Overall Index | ICP | M.U2.N.000000.4.ANR |
| hicp_core | HICP - All items excluding energy and food | ICP | M.U2.N.XEF000.4.ANR |
| hicp_energy | HICP - Energy | ICP | M.U2.N.NRG000.4.ANR |

### Economic Indicators

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| gdp | GDP at market prices | MNA | Q.Y.I8.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N |
| unemployment_rate | Unemployment Rate - Total | LFSI | M.U2.N.S.UNEH.RTT000.4.AV3 |

### Money Supply (BSI Flow)

| Indicator | Description | Flow | Key |
|-----------|-------------|------|-----|
| m1 | Monetary aggregate M1 | BSI | M.U2.Y.V.M10.X.1.U2.2300.Z01.E |
| m2 | Monetary aggregate M2 | BSI | M.U2.Y.V.M20.X.1.U2.2300.Z01.E |
| m3 | Monetary aggregate M3 | BSI | M.U2.Y.V.M30.X.1.U2.2300.Z01.E |

---

## Appendix B: Quick Reference

### Tool Selection Guide

| Need | Use Tool |
|------|----------|
| Latest single value | ecb_get_latest |
| Multiple latest values | ecb_get_common_indicators |
| Time series (any series) | ecb_get_series |
| FX rates specifically | ecb_get_exchange_rate |
| Interest rates specifically | ecb_get_interest_rate |
| Bond yields specifically | ecb_get_bond_yield |
| Inflation specifically | ecb_get_inflation |
| Explore available data | ecb_search_series |

### URL Reference

- **ECB Homepage**: https://www.ecb.europa.eu
- **Statistical Data Warehouse**: https://sdw.ecb.europa.eu
- **API Documentation**: https://data.ecb.europa.eu
- **Data Portal**: https://data-api.ecb.europa.eu

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

*End of European Central Bank MCP Tool Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **ECB (European Central Bank)**: The central bank of the Eurozone, responsible for monetary policy for the euro.

- **Eurozone**: The group of European Union countries that have adopted the euro as their currency.

- **Main Refinancing Rate**: The ECB's primary policy rate for providing liquidity to the banking system.

- **HICP (Harmonised Index of Consumer Prices)**: The inflation measure used by the ECB for monetary policy.

- **TARGET2**: The real-time gross settlement system owned and operated by the Eurosystem.

- **Deposit Facility Rate**: The interest rate banks receive for depositing money with the ECB overnight.

- **Quantitative Easing (QE)**: A monetary policy where a central bank purchases securities to increase money supply.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
