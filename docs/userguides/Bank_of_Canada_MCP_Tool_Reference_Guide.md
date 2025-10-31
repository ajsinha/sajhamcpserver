# Bank of Canada MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030 Ashutosh Sinha**  
**Email: ajsinha@gmail.com**

**Version:** 1.0.0  
**Last Updated:** October 31, 2025

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)  
3. [API Access & Authentication](#api-access--authentication)
4. [Tool Catalog](#tool-catalog)
5. [Installation & Setup](#installation--setup)
6. [Code Examples](#code-examples)
7. [Error Handling](#error-handling)
8. [Best Practices](#best-practices)
9. [Appendix](#appendix)

---

## Overview

The Bank of Canada MCP Tool Suite provides a comprehensive interface to access Canadian economic data through the Bank of Canada's Valet API. This toolset enables retrieval of exchange rates, interest rates, bond yields, and key economic indicators with a clean, object-oriented architecture.

### Key Features

- **7 Specialized Tools** for different data access patterns
- **15+ Economic Indicators** covering FX, rates, bonds, and macro data
- **Flexible Time Ranges** with support for date ranges and recent periods
- **Zero Authentication** required - public API access
- **Type-Safe Schemas** with JSON Schema validation
- **Performance Tracking** built-in metrics for all operations
- **Error Resilience** with graceful degradation

### Use Cases

- Financial dashboards and trading terminals
- Economic research and analysis
- Automated reporting and alerts
- Investment portfolio management
- Educational applications
- API integration and microservices

---

## Architecture

### System Architecture Diagram

```
┌───────────────────────────────────────────────────────────┐
│                  MCP Tool Framework                        │
└───────────────────────────────────────────────────────────┘
                          │
                          │
                          ▼
┌───────────────────────────────────────────────────────────┐
│                  BaseMCPTool                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Abstract Base Class                             │    │
│  │  - Tool lifecycle management                     │    │
│  │  - Input/Output schema validation                │    │
│  │  - Performance tracking & metrics                │    │
│  │  - Configuration management                      │    │
│  └─────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
                          │
                          │ Inherits
                          ▼
┌───────────────────────────────────────────────────────────┐
│            BankOfCanadaBaseTool                            │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Shared BoC Functionality                        │    │
│  │  - API endpoint configuration                    │    │
│  │  - Common series mapping (15 indicators)         │    │
│  │  - Shared _fetch_series() method                 │    │
│  │  - Error handling & retry logic                  │    │
│  └─────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
                          │
                          │ Inherits
      ┌───────────────────┴───────────────────┐
      │                                       │
      ▼                                       ▼
┌─────────────────┐                 ┌─────────────────┐
│ BoCGetSeries    │                 │ BoCGetLatest    │
│ Tool            │                 │ Tool            │
└─────────────────┘                 └─────────────────┘
      │                                       │
      ▼                                       ▼
┌─────────────────┐                 ┌─────────────────┐
│ BoCGetExchange  │                 │ BoCSearchSeries │
│ RateTool        │                 │ Tool            │
└─────────────────┘                 └─────────────────┘
      │                                       │
      ▼                                       ▼
┌─────────────────┐                 ┌─────────────────┐
│ BoCGetInterest  │                 │ BoCGetCommon    │
│ RateTool        │                 │ IndicatorsTool  │
└─────────────────┘                 └─────────────────┘
      │
      ▼
┌─────────────────┐
│ BoCGetBondYield │
│ Tool            │
└─────────────────┘
```

### Component Overview

#### 1. BaseMCPTool (Abstract Base Class)

The foundation class providing core MCP tool functionality.

**Key Responsibilities:**
- Tool registration and discovery
- Input/output schema management
- Argument validation
- Execution tracking and metrics
- Enable/disable functionality
- Configuration loading

**Key Methods:**
- `execute(arguments)` - Abstract method for tool execution
- `get_input_schema()` - Returns JSON schema for inputs
- `get_output_schema()` - Returns JSON schema for outputs
- `execute_with_tracking()` - Executes with performance metrics
- `validate_arguments()` - Validates input against schema
- `get_metrics()` - Returns execution statistics
- `to_mcp_format()` - Converts to MCP protocol format

#### 2. BankOfCanadaBaseTool (Base Implementation)

Shared functionality for all Bank of Canada tools.

**API Configuration:**
```python
api_url = "https://www.bankofcanada.ca/valet"
```

**Common Series Mapping:**
```python
common_series = {
    # Exchange Rates (5)
    'usd_cad': 'FXUSDCAD',
    'eur_cad': 'FXEURCAD',
    'gbp_cad': 'FXGBPCAD',
    'jpy_cad': 'FXJPYCAD',
    'cny_cad': 'FXCNYCAD',
    
    # Interest Rates (3)
    'policy_rate': 'POLICY_RATE',
    'overnight_rate': 'CORRA',
    'prime_rate': 'V122530',
    
    # Bond Yields (4)
    'bond_2y': 'V122531',
    'bond_5y': 'V122533',
    'bond_10y': 'V122539',
    'bond_30y': 'V122546',
    
    # Economic Indicators (3)
    'cpi': 'V41690973',
    'core_cpi': 'V41690914',
    'gdp': 'V65201210'
}
```

---

## API Access & Authentication

### Bank of Canada Valet API

**Base URL:** `https://www.bankofcanada.ca/valet`

### Authentication

**✓ No API Key Required**

The Bank of Canada Valet API is a public API that does not require authentication. All endpoints are freely accessible without registration or API keys.

### Rate Limits

- **Default Limit:** 120 requests per minute per IP address
- **Recommended Cache TTL:** 3600 seconds (1 hour)
- **Best Practice:** Implement client-side caching for frequently accessed data

### API Endpoints

**Observations Endpoint:**
```
GET /observations/{series_name}/json
```

**Query Parameters:**
- `start_date` - Start date (YYYY-MM-DD)
- `end_date` - End date (YYYY-MM-DD)
- `recent` - Number of recent observations

**Example Request:**
```
https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=10
```

**Response Format:**
```json
{
  "seriesDetail": {
    "FXUSDCAD": {
      "label": "US dollar, noon spot rate, Canadian dollar, daily",
      "description": "Canadian dollars per 1 United States dollar",
      "dimension": {"key": "d", "name": "Date"}
    }
  },
  "observations": [
    {
      "d": "2024-10-31",
      "FXUSDCAD": {"v": "1.3825"}
    }
  ]
}
```

---

## Tool Catalog

### Overview of All Tools

| Tool | Purpose | Key Use Case |
|------|---------|-------------|
| `boc_get_series` | Time series data | Historical analysis |
| `boc_get_latest` | Latest value only | Real-time dashboards |
| `boc_get_exchange_rate` | FX rates | Currency trading |
| `boc_get_interest_rate` | Interest rates | Monetary policy |
| `boc_get_bond_yield` | Bond yields | Fixed income |
| `boc_search_series` | Discovery | API exploration |
| `boc_get_common_indicators` | Multi-indicator | Dashboards |


### 1. boc_get_series

**Purpose:** Retrieve time series economic data with flexible date ranges.

**Input Parameters:**
- `series_name` (string, required*) - BoC series identifier (e.g., 'FXUSDCAD')
- `indicator` (string, required*) - Shorthand indicator (e.g., 'usd_cad')
- `start_date` (string, optional) - Start date (YYYY-MM-DD)
- `end_date` (string, optional) - End date (YYYY-MM-DD)
- `recent_periods` (integer, optional) - Recent observations (1-100, default: 10)

*Either series_name or indicator required

**Output:** Time series with observations array

### 2. boc_get_latest

**Purpose:** Get the most recent value for any indicator - optimized for speed.

**Input Parameters:**
- `series_name` (string, required*) - BoC series identifier
- `indicator` (string, required*) - Shorthand indicator

**Output:** Single latest observation with date and value

### 3. boc_get_exchange_rate

**Purpose:** Specialized tool for foreign exchange rate queries.

**Input Parameters:**
- `currency_pair` (string, required*) - Format 'XXX/CAD' (e.g., 'USD/CAD')
- `indicator` (string, required*) - Predefined pair ('usd_cad', 'eur_cad', etc.)
- `start_date` (string, optional) - Start date
- `end_date` (string, optional) - End date
- `recent_periods` (integer, optional) - Recent observations (1-100)

**Supported Currency Pairs:**
- USD/CAD, EUR/CAD, GBP/CAD, JPY/CAD, CNY/CAD

### 4. boc_get_interest_rate

**Purpose:** Retrieve Bank of Canada interest rates and monetary policy data.

**Input Parameters:**
- `rate_type` (string, required) - Type: 'policy_rate', 'overnight_rate', 'prime_rate'
- `start_date` (string, optional) - Start date
- `end_date` (string, optional) - End date
- `recent_periods` (integer, optional) - Recent observations

### 5. boc_get_bond_yield

**Purpose:** Retrieve Government of Canada benchmark bond yields.

**Input Parameters:**
- `bond_term` (string, required) - Maturity: '2y', '5y', '10y', '30y'
- `start_date` (string, optional) - Start date
- `end_date` (string, optional) - End date
- `recent_periods` (integer, optional) - Recent observations (1-100)

### 6. boc_search_series

**Purpose:** Discover and explore available data series organized by category.

**Input Parameters:**
- `category` (string, optional) - Filter: 'Exchange Rates', 'Interest Rates', 'Bond Yields', 'Economic Indicators', or 'all'

**Output:** Categorized list of all available series with descriptions

### 7. boc_get_common_indicators

**Purpose:** Retrieve multiple indicators in a single call with consistent timestamp.

**Input Parameters:**
- `indicators` (array, optional) - List of indicators (default: ['usd_cad', 'policy_rate', 'bond_10y', 'cpi'])

**Output:** Dictionary of indicators with their latest values

---

## Installation & Setup

### Prerequisites

- Python 3.8 or higher
- No external dependencies (uses standard library only: json, urllib, logging)

### Installation Steps

1. **Download the tool files:**
   ```bash
   # Core files needed
   base_mcp_tool.py
   bank_of_canada_tool_refactored.py
   
   # Optional configuration files
   boc_*.json
   ```

2. **Directory structure:**
   ```
   project/
   ├── tools/
   │   ├── __init__.py
   │   ├── base_mcp_tool.py
   │   └── impl/
   │       ├── __init__.py
   │       └── bank_of_canada_tool_refactored.py
   └── config/
       └── boc_*.json
   ```

3. **Import and use:**
   ```python
   from tools.impl.bank_of_canada_tool_refactored import (
       BoCGetSeriesTool,
       BoCGetLatestTool,
       BoCGetExchangeRateTool,
       BoCGetInterestRateTool,
       BoCGetBondYieldTool,
       BoCSearchSeriesTool,
       BoCGetCommonIndicatorsTool,
       BANK_OF_CANADA_TOOLS
   )
   ```

---

## Code Examples

### Example 1: Get Latest USD/CAD Rate

```python
from tools.impl.bank_of_canada_tool_refactored import BoCGetLatestTool

# Create tool instance
tool = BoCGetLatestTool()

# Get latest USD/CAD
result = tool.execute({'indicator': 'usd_cad'})

print(f"Current rate: {result['value']:.4f} as of {result['date']}")
# Output: Current rate: 1.3825 as of 2024-10-31
```

### Example 2: Historical Exchange Rate Analysis

```python
from tools.impl.bank_of_canada_tool_refactored import BoCGetExchangeRateTool

tool = BoCGetExchangeRateTool()

# Get 30 days of USD/CAD data
result = tool.execute({
    'indicator': 'usd_cad',
    'recent_periods': 30
})

print(f"Retrieved {result['observation_count']} observations")

# Calculate average
values = [obs['value'] for obs in result['observations'] if obs['value']]
avg_rate = sum(values) / len(values)

print(f"30-day average rate: {avg_rate:.4f}")
```

### Example 3: Yield Curve Analysis

```python
from tools.impl.bank_of_canada_tool_refactored import BoCGetBondYieldTool

tool = BoCGetBondYieldTool()

# Get yields for all maturities
maturities = ['2y', '5y', '10y', '30y']
curve = {}

for term in maturities:
    result = tool.execute({
        'bond_term': term,
        'recent_periods': 1
    })
    if result['observations']:
        curve[term] = result['observations'][0]['value']

print("Current Yield Curve:")
for term, yield_value in curve.items():
    print(f"  {term}: {yield_value:.2f}%")
    
# Calculate 2-10 spread
spread_2_10 = curve['10y'] - curve['2y']
print(f"\n2-10 Spread: {spread_2_10:.2f}%")
```

### Example 4: Economic Dashboard

```python
from tools.impl.bank_of_canada_tool_refactored import BoCGetCommonIndicatorsTool

tool = BoCGetCommonIndicatorsTool()

# Get key economic indicators
result = tool.execute({
    'indicators': ['usd_cad', 'policy_rate', 'bond_10y', 'cpi']
})

print("Canadian Economic Snapshot")
print(f"Last updated: {result['last_updated']}")
print("-" * 50)

for indicator, data in result['indicators'].items():
    if 'error' not in data:
        print(f"{indicator:15} {data['value']:>10} (as of {data['date']})")
```

### Example 5: Policy Rate Change Tracking

```python
from tools.impl.bank_of_canada_tool_refactored import BoCGetInterestRateTool
from datetime import datetime, timedelta

tool = BoCGetInterestRateTool()

# Get policy rate for past year
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

result = tool.execute({
    'rate_type': 'policy_rate',
    'start_date': start_date,
    'end_date': end_date
})

# Find rate changes
observations = result['observations']
changes = []

for i in range(1, len(observations)):
    if observations[i]['value'] != observations[i-1]['value']:
        changes.append({
            'date': observations[i]['date'],
            'from': observations[i-1]['value'],
            'to': observations[i]['value'],
            'change': observations[i]['value'] - observations[i-1]['value']
        })

print(f"Policy Rate Changes in Past Year:")
for change in changes:
    direction = "↑" if change['change'] > 0 else "↓"
    print(f"  {change['date']}: {change['from']}% → {change['to']}% "
          f"({direction} {abs(change['change']):.2f}%)")
```

### Example 6: Discover Available Series

```python
from tools.impl.bank_of_canada_tool_refactored import BoCSearchSeriesTool

tool = BoCSearchSeriesTool()

# Get all available series
result = tool.execute({})

print(f"Total available series: {result['total_series']}\n")

for category, series_list in result['categories'].items():
    print(f"{category} ({len(series_list)} series):")
    for series in series_list:
        print(f"  - {series['indicator']:15} {series['series_name']:15} {series['description']}")
    print()
```

---

## Error Handling

### Common Error Scenarios

#### 1. Series Not Found (404)

```python
try:
    tool = BoCGetLatestTool()
    result = tool.execute({'series_name': 'INVALID_SERIES'})
except ValueError as e:
    if 'Series not found' in str(e):
        print("The requested series does not exist")
        # Use boc_search_series to find valid series
```

#### 2. Network Errors

```python
import urllib.error

try:
    tool = BoCGetLatestTool()
    result = tool.execute({'indicator': 'usd_cad'})
except urllib.error.URLError as e:
    print(f"Network error: {e}")
    # Implement retry with exponential backoff
```

#### 3. Missing Required Parameters

```python
try:
    tool = BoCGetSeriesTool()
    result = tool.execute({})  # Missing required params
except ValueError as e:
    print(f"Missing required parameter: {e}")
    # Check input schema
    schema = tool.get_input_schema()
    print(f"Required fields: {schema.get('required', [])}")
```

#### 4. Disabled Tool

```python
tool = BoCGetLatestTool()
tool.disable()

try:
    result = tool.execute_with_tracking({'indicator': 'usd_cad'})
except RuntimeError as e:
    print(f"Tool is disabled: {e}")
    tool.enable()  # Re-enable if needed
```

### Comprehensive Error Handling Pattern

```python
def safe_execute_tool(tool, arguments):
    """Safely execute tool with comprehensive error handling"""
    try:
        # Check if tool is enabled
        if not tool.enabled:
            return {'success': False, 'error': 'Tool is disabled'}
        
        # Execute with tracking
        result = tool.execute_with_tracking(arguments)
        
        return {'success': True, 'data': result}
        
    except ValueError as e:
        # Validation or series errors
        return {
            'success': False,
            'error': str(e),
            'error_type': 'validation'
        }
        
    except urllib.error.HTTPError as e:
        # HTTP errors from API
        return {
            'success': False,
            'error': f"HTTP {e.code}: {e.reason}",
            'error_type': 'http'
        }
        
    except urllib.error.URLError as e:
        # Network errors
        return {
            'success': False,
            'error': f"Network error: {e.reason}",
            'error_type': 'network'
        }
        
    except Exception as e:
        # Unexpected errors
        return {
            'success': False,
            'error': str(e),
            'error_type': 'unknown'
        }

# Usage
tool = BoCGetLatestTool()
result = safe_execute_tool(tool, {'indicator': 'usd_cad'})

if result['success']:
    print(f"Value: {result['data']['value']}")
else:
    print(f"Error ({result['error_type']}): {result['error']}")
```

---

## Best Practices

### 1. Caching Strategy

```python
import time
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_latest(indicator, cache_key):
    """Cache latest values with time-based invalidation"""
    tool = BoCGetLatestTool()
    return tool.execute({'indicator': indicator})

def get_latest_with_cache(indicator, cache_ttl=3600):
    """Get latest with automatic cache invalidation"""
    cache_key = int(time.time() / cache_ttl)
    return get_cached_latest(indicator, cache_key)

# Usage: Automatically refreshes every hour
rate = get_latest_with_cache('usd_cad')
```

### 2. Batch Processing

```python
def batch_fetch_indicators(indicators, batch_size=5):
    """Fetch multiple indicators with rate limiting"""
    tool = BoCGetLatestTool()
    results = {}
    
    for i in range(0, len(indicators), batch_size):
        batch = indicators[i:i + batch_size]
        
        for indicator in batch:
            try:
                results[indicator] = tool.execute({'indicator': indicator})
            except Exception as e:
                results[indicator] = {'error': str(e)}
        
        # Rate limiting: wait between batches
        if i + batch_size < len(indicators):
            time.sleep(0.5)
    
    return results
```

### 3. Retry Logic with Exponential Backoff

```python
import time

def fetch_with_retry(tool, arguments, max_retries=3):
    """Fetch data with retry logic"""
    for attempt in range(max_retries):
        try:
            return tool.execute(arguments)
            
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Retry in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
```

### 4. Performance Monitoring

```python
tool = BoCGetSeriesTool()

# Execute some operations
for indicator in ['usd_cad', 'policy_rate', 'bond_10y']:
    tool.execute_with_tracking({
        'indicator': indicator,
        'recent_periods': 10
    })

# Check metrics
metrics = tool.get_metrics()
print(f"Total executions: {metrics['execution_count']}")
print(f"Average time: {metrics['average_execution_time']:.3f}s")
```

### 5. Data Validation

```python
def validate_observation(obs):
    """Validate observation data"""
    if obs['value'] is None:
        return False, "Missing value"
    
    if not obs['date']:
        return False, "Missing date"
    
    try:
        datetime.strptime(obs['date'], '%Y-%m-%d')
    except ValueError:
        return False, "Invalid date format"
    
    return True, None
```

---

## Appendix

### A. Complete Series Reference

#### Exchange Rates (5 series)

| Indicator | Series Name | Description | Frequency |
|-----------|-------------|-------------|-----------|
| usd_cad | FXUSDCAD | US Dollar to CAD | Daily |
| eur_cad | FXEURCAD | Euro to CAD | Daily |
| gbp_cad | FXGBPCAD | British Pound to CAD | Daily |
| jpy_cad | FXJPYCAD | Japanese Yen to CAD | Daily |
| cny_cad | FXCNYCAD | Chinese Yuan to CAD | Daily |

#### Interest Rates (3 series)

| Indicator | Series Name | Description | Frequency |
|-----------|-------------|-------------|-----------|
| policy_rate | POLICY_RATE | BoC Policy Rate | Daily |
| overnight_rate | CORRA | Canadian Overnight Repo Rate | Daily |
| prime_rate | V122530 | Prime Business Rate | Daily |

#### Bond Yields (4 series)

| Indicator | Series Name | Description | Frequency |
|-----------|-------------|-------------|-----------|
| bond_2y | V122531 | 2-Year Bond Yield | Daily |
| bond_5y | V122533 | 5-Year Bond Yield | Daily |
| bond_10y | V122539 | 10-Year Bond Yield | Daily |
| bond_30y | V122546 | 30-Year Bond Yield | Daily |

#### Economic Indicators (3 series)

| Indicator | Series Name | Description | Frequency |
|-----------|-------------|-------------|-----------|
| cpi | V41690973 | Consumer Price Index | Monthly |
| core_cpi | V41690914 | CPI Common (Core) | Monthly |
| gdp | V65201210 | Gross Domestic Product | Quarterly |

### B. Tool Selection Guide

| Use Case | Recommended Tool | Reason |
|----------|------------------|--------|
| Real-time dashboard | boc_get_latest | Minimal payload, fastest |
| Historical analysis | boc_get_series | Full time series data |
| Multi-indicator dashboard | boc_get_common_indicators | Batch retrieval |
| FX trading | boc_get_exchange_rate | Currency-specific |
| Yield curve | boc_get_bond_yield | Bond-specific |
| Rate tracking | boc_get_interest_rate | Interest rate focus |
| API exploration | boc_search_series | Discovery |

### C. Performance Optimization

**Response Times:**
- `boc_get_latest`: ~150-200ms
- `boc_get_series` (10 periods): ~200-300ms
- `boc_get_series` (100 periods): ~400-600ms
- `boc_get_common_indicators` (4 indicators): ~600-800ms

**Optimization Tips:**
1. Use `boc_get_latest` for single current values
2. Implement client-side caching (1-hour TTL)
3. Batch requests with `boc_get_common_indicators`
4. Request only needed time periods
5. Consider async/parallel requests for multiple series

### D. Additional Resources

**Bank of Canada Resources:**
- Valet API Documentation: https://www.bankofcanada.ca/valet/docs
- Economic Data Portal: https://www.bankofcanada.ca/rates/
- Statistical Releases: https://www.bankofcanada.ca/rates/statistical-releases/

**Support:**
- Email: ajsinha@gmail.com
- GitHub Issues: (if applicable)
- Documentation: This guide

### E. Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│        BANK OF CANADA MCP TOOLS CHEAT SHEET             │
└─────────────────────────────────────────────────────────┘

IMPORT:
  from tools.impl.bank_of_canada_tool_refactored import *

TOOLS:
  boc_get_series            → Full time series data
  boc_get_latest            → Latest value only
  boc_get_exchange_rate     → FX rates
  boc_get_interest_rate     → Interest rates
  boc_get_bond_yield        → Bond yields
  boc_search_series         → Discover series
  boc_get_common_indicators → Multi-indicator batch

QUICK EXAMPLES:
  # Get latest USD/CAD
  tool = BoCGetLatestTool()
  result = tool.execute({'indicator': 'usd_cad'})
  
  # Get 10-year yield history
  tool = BoCGetBondYieldTool()
  result = tool.execute({
      'bond_term': '10y',
      'start_date': '2024-01-01',
      'end_date': '2024-10-31'
  })
  
  # Economic dashboard
  tool = BoCGetCommonIndicatorsTool()
  result = tool.execute({
      'indicators': ['usd_cad', 'policy_rate', 'bond_10y', 'cpi']
  })

API: https://www.bankofcanada.ca/valet
AUTH: None required ✓
RATE LIMIT: 120 req/min
```

---

**End of Reference Guide**

