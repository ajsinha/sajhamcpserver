# Federal Reserve MCP Tool Reference Guide

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
6. [Common Indicators](#common-indicators)
7. [Usage Examples](#usage-examples)
8. [Schema Reference](#schema-reference)
9. [Limitations](#limitations)
10. [Error Handling](#error-handling)
11. [Performance Considerations](#performance-considerations)

---

## Overview

The Federal Reserve MCP Tool Suite provides programmatic access to the Federal Reserve Economic Data (FRED) database - the premier source for US economic statistics. These 4 specialized tools enable retrieval of over 800,000 economic time series covering US and international economic data.

### Key Features

- **Comprehensive Coverage**: Access to 800,000+ economic time series
- **Historical Data**: Decades of historical economic indicators
- **12 Common Indicators**: Pre-configured shortcuts for key metrics
- **Search Functionality**: Discover data series by keyword
- **Dashboard Support**: Batch retrieval of multiple indicators
- **Demo Mode**: Test without API key (limited functionality)

### Data Categories

- GDP and Economic Growth
- Employment and Labor
- Inflation and Prices
- Interest Rates and Yields
- Stock Market Indices
- Housing and Construction
- Retail and Consumer Spending
- Industrial Production
- Monetary Aggregates
- International Data

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
│              MCP Tool Layer (4 Tools)                    │
├──────────────────────────────────────────────────────────┤
│  • fed_get_series                                        │
│  • fed_get_latest                                        │
│  • fed_search_series                                     │
│  • fed_get_common_indicators                             │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│      FedReserveBaseTool (Shared Functionality)           │
├──────────────────────────────────────────────────────────┤
│  • API URL: api.stlouisfed.org/fred                     │
│  • API Key Management (optional/demo mode)               │
│  • Common Series Definitions (12 indicators)             │
│  • HTTP Client (urllib)                                  │
│  • JSON Parser                                           │
│  • Demo Data Generator                                   │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│         Federal Reserve FRED API                         │
│         https://api.stlouisfed.org/fred                  │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── FedReserveBaseTool
            │
            ├── FedGetSeriesTool
            ├── FedGetLatestTool
            ├── FedSearchSeriesTool
            └── FedGetCommonIndicatorsTool
```

### Component Descriptions

#### FedReserveBaseTool
Base class providing:
- FRED API endpoint configuration (`https://api.stlouisfed.org/fred`)
- API key management with optional demo mode
- Common indicator shortcuts (12 pre-configured series)
- Shared HTTP request handling via `_get_series_data()` method
- Demo data generation for testing without API key
- JSON response parsing
- Error handling and logging

#### Individual Tool Classes
Each tool specializes in a specific data retrieval pattern:
- Custom input/output schemas
- Specialized query parameter handling
- Tailored response formatting
- Specific error handling

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

The tools communicate with the FRED API using standard REST API calls:

```python
# Base URL
https://api.stlouisfed.org/fred

# Request Formats
GET /series/observations?series_id={id}&api_key={key}&file_type=json
GET /series?series_id={id}&api_key={key}&file_type=json
GET /series/search?search_text={query}&api_key={key}&file_type=json

# Example
GET /series/observations?series_id=GDP&api_key=abc123&file_type=json&limit=10
```

### HTTP Request Details

**Parameters**:
- `series_id`: FRED series identifier (e.g., GDP, UNRATE, DGS10)
- `api_key`: FRED API key (required for production)
- `file_type`: Response format (always 'json')
- `limit`: Maximum number of observations
- `observation_start`: Start date (YYYY-MM-DD)
- `observation_end`: End date (YYYY-MM-DD)
- `search_text`: Search query string

**Timeout**: Standard urllib timeout (default)

### Response Parsing

The FRED API returns data in JSON format:

```json
{
  "observations": [
    {
      "date": "2024-01-01",
      "value": "27610.1"
    },
    {
      "date": "2024-04-01",
      "value": "27742.3"
    }
  ]
}

{
  "seriess": [
    {
      "id": "GDP",
      "title": "Gross Domestic Product",
      "units": "Billions of Dollars",
      "frequency": "Quarterly",
      "last_updated": "2024-10-30 07:47:06-05"
    }
  ]
}
```

The tools parse this structure and format it consistently.

### Demo Mode

For testing without an API key, the tools include a demo mode that generates synthetic data:
- Automatically activated when `api_key='demo'` or not configured
- Returns realistic mock time series data
- Supports all tool operations
- Includes disclaimer in responses

---

## Authentication & API Keys

### API Key Required for Production

The FRED API **requires an API key** for production use but offers:
- **Free Registration**: Create account at https://fred.stlouisfed.org
- **Free API Key**: No cost for standard usage
- **Demo Mode**: Test tools without registration

### Obtaining an API Key

**Step 1: Register**
1. Visit https://fred.stlouisfed.org
2. Click "My Account" → "Register"
3. Complete registration form

**Step 2: Request API Key**
1. Log in to your FRED account
2. Navigate to "API Keys"
3. Click "Request API Key"
4. Accept terms and conditions
5. Copy your API key (32-character string)

**Step 3: Configure Tool**
```python
from tools.impl.fed_reserve_tool_refactored import FedGetSeriesTool

# With API key
tool = FedGetSeriesTool(config={'api_key': 'your_api_key_here'})

# Demo mode (no API key)
tool = FedGetSeriesTool()  # Uses demo mode
```

### API Key Security

**Best Practices**:
- Store API keys in environment variables, not code
- Never commit API keys to version control
- Rotate keys periodically
- Use different keys for dev/prod environments

**Example**:
```python
import os

config = {
    'api_key': os.environ.get('FRED_API_KEY', 'demo')
}
tool = FedGetSeriesTool(config=config)
```

### Rate Limits

FRED API has generous rate limits:
- **Standard**: 120 requests per minute
- **No daily limit** for standard usage
- **Fair use policy**: Avoid excessive automated queries

### Demo Mode Limitations

Demo mode provides:
- ✓ Testing tool functionality
- ✓ Understanding response formats
- ✓ Development without API key
- ✗ Real economic data
- ✗ Historical accuracy
- ✗ Search functionality (limited results)

---

## Tool Descriptions

### 1. fed_get_series

**Purpose**: Retrieve time series economic data from FRED database

**Use Cases**:
- Historical economic analysis
- Financial modeling
- Investment research
- Policy analysis
- Academic studies

**Input Parameters**:
```json
{
  "series_id": "GDP",              // Option 1: Direct FRED ID
  // OR
  "indicator": "gdp",              // Option 2: Shorthand
  
  "start_date": "2020-01-01",      // Optional
  "end_date": "2024-12-31",        // Optional
  "limit": 100                     // Optional (default: 100, max: 1000)
}
```

**Output**:
```json
{
  "series_id": "GDP",
  "title": "Gross Domestic Product",
  "units": "Billions of Dollars",
  "frequency": "Quarterly",
  "last_updated": "2024-10-30T07:47:06",
  "observation_count": 4,
  "observations": [
    {
      "date": "2024-01-01",
      "value": 27610.1
    },
    {
      "date": "2024-04-01",
      "value": 27742.3
    }
  ]
}
```

**Common Series IDs**:
- GDP - Gross Domestic Product
- UNRATE - Unemployment Rate
- CPIAUCSL - Consumer Price Index
- DFF - Federal Funds Rate
- DGS10 - 10-Year Treasury Rate
- SP500 - S&P 500 Index

---

### 2. fed_get_latest

**Purpose**: Retrieve only the most recent observation for a series

**Optimization**: Minimal payload - perfect for dashboards

**Input Parameters**:
```json
{
  "series_id": "UNRATE",           // Option 1: Direct FRED ID
  // OR
  "indicator": "unemployment"      // Option 2: Shorthand
}
```

**Output**:
```json
{
  "series_id": "UNRATE",
  "title": "Unemployment Rate",
  "units": "Percent",
  "frequency": "Monthly",
  "date": "2024-10-01",
  "value": 4.1,
  "last_updated": "2024-11-01T07:30:00"
}
```

**Use Cases**:
- Real-time dashboards
- Economic monitors
- Status displays
- Quick fact checking
- Alert systems

---

### 3. fed_search_series

**Purpose**: Search FRED database to find series by keyword

**Input Parameters**:
```json
{
  "query": "unemployment rate",    // Required
  "limit": 20                      // Optional (default: 20, max: 100)
}
```

**Output**:
```json
{
  "query": "unemployment rate",
  "count": 2,
  "results": [
    {
      "id": "UNRATE",
      "title": "Unemployment Rate",
      "units": "Percent",
      "frequency": "Monthly",
      "popularity": 95,
      "observation_start": "1948-01-01",
      "observation_end": "2024-10-01"
    },
    {
      "id": "UNEMPLOY",
      "title": "Unemployed",
      "units": "Thousands of Persons",
      "frequency": "Monthly",
      "popularity": 87,
      "observation_start": "1948-01-01",
      "observation_end": "2024-10-01"
    }
  ]
}
```

**Search Tips**:
- Use specific keywords (e.g., "consumer price index" not "inflation")
- Results sorted by popularity
- Try different variations (GDP vs gross domestic product)
- Check units and frequency to find right series

**Use Cases**:
- Data discovery
- Finding specific indicators
- Exploring available data
- Research planning
- Alternative measure identification

---

### 4. fed_get_common_indicators

**Purpose**: Batch retrieval of multiple key economic indicators

**Default Indicators** (if none specified):
All 12 common indicators

**Input Parameters**:
```json
{
  "indicators": [                  // Optional
    "gdp",
    "unemployment",
    "inflation",
    "fed_rate",
    "treasury_10y"
  ]
}
```

**Output**:
```json
{
  "indicators": {
    "gdp": {
      "series_id": "GDP",
      "title": "Gross Domestic Product",
      "value": 27742.3,
      "date": "2024-07-01",
      "units": "Billions of Dollars"
    },
    "unemployment": {
      "series_id": "UNRATE",
      "title": "Unemployment Rate",
      "value": 4.1,
      "date": "2024-10-01",
      "units": "Percent"
    }
  },
  "last_updated": "2024-10-31T14:30:00.000Z"
}
```

**Use Cases**:
- Economic dashboards
- Market overview reports
- Quick economic health checks
- Morning briefings
- Executive summaries
- Portfolio context

---

## Common Indicators

### Complete Indicator Reference

| Indicator | FRED ID | Description | Units | Frequency |
|-----------|---------|-------------|-------|-----------|
| **gdp** | GDP | Gross Domestic Product | Billions of Dollars | Quarterly |
| **unemployment** | UNRATE | Unemployment Rate | Percent | Monthly |
| **inflation** | CPIAUCSL | Consumer Price Index | Index 1982-84=100 | Monthly |
| **fed_rate** | DFF | Federal Funds Effective Rate | Percent | Daily |
| **treasury_10y** | DGS10 | 10-Year Treasury Constant Maturity Rate | Percent | Daily |
| **treasury_2y** | DGS2 | 2-Year Treasury Constant Maturity Rate | Percent | Daily |
| **sp500** | SP500 | S&P 500 Index | Index | Daily |
| **housing** | HOUST | Housing Starts | Thousands of Units | Monthly |
| **retail** | RSXFS | Advance Retail Sales | Millions of Dollars | Monthly |
| **industrial** | INDPRO | Industrial Production Index | Index 2017=100 | Monthly |
| **m2** | M2SL | M2 Money Stock | Billions of Dollars | Weekly |
| **pce** | PCEPI | Personal Consumption Expenditures Price Index | Index 2017=100 | Monthly |

### Indicator Categories

**Growth & Output**:
- gdp - Overall economic output
- industrial - Manufacturing production
- retail - Consumer spending

**Labor Market**:
- unemployment - Unemployment rate

**Inflation**:
- inflation - Consumer price changes (CPI)
- pce - Fed's preferred inflation measure

**Monetary Policy**:
- fed_rate - Federal Reserve target rate
- treasury_10y - Long-term benchmark
- treasury_2y - Short-term benchmark
- m2 - Money supply

**Financial Markets**:
- sp500 - Stock market performance

**Housing**:
- housing - New housing construction

---

## Usage Examples

### Example 1: Get Current Unemployment Rate

```python
from tools.impl.fed_reserve_tool_refactored import FedGetLatestTool

# Configure with API key
config = {'api_key': 'your_api_key_here'}
tool = FedGetLatestTool(config)

# Get latest value
result = tool.execute({
    "indicator": "unemployment"
})

print(f"Unemployment Rate: {result['value']}% as of {result['date']}")
# Output: Unemployment Rate: 4.1% as of 2024-10-01
```

### Example 2: Analyze GDP Trend

```python
from tools.impl.fed_reserve_tool_refactored import FedGetSeriesTool
import matplotlib.pyplot as plt

config = {'api_key': 'your_api_key_here'}
tool = FedGetSeriesTool(config)

# Get 5 years of GDP data
result = tool.execute({
    "indicator": "gdp",
    "start_date": "2019-01-01",
    "end_date": "2024-12-31"
})

# Extract data
dates = [obs['date'] for obs in result['observations']]
values = [obs['value'] for obs in result['observations']]

# Plot
plt.figure(figsize=(12, 6))
plt.plot(dates, values, marker='o')
plt.title('US GDP Trend (2019-2024)')
plt.xlabel('Date')
plt.ylabel(f"GDP ({result['units']})")
plt.xticks(rotation=45)
plt.grid(True)
plt.tight_layout()
plt.show()

print(f"GDP Growth: {values[0]:.1f}B → {values[-1]:.1f}B")
```

### Example 3: Search for Housing Data

```python
from tools.impl.fed_reserve_tool_refactored import FedSearchSeriesTool

config = {'api_key': 'your_api_key_here'}
tool = FedSearchSeriesTool(config)

# Search for housing-related series
result = tool.execute({
    "query": "housing price index",
    "limit": 10
})

print(f"Found {result['count']} series related to 'housing price index':\n")

for series in result['results']:
    print(f"{series['id']}: {series['title']}")
    print(f"  Frequency: {series['frequency']}")
    print(f"  Popularity: {series['popularity']}")
    print()
```

### Example 4: Create Economic Dashboard

```python
from tools.impl.fed_reserve_tool_refactored import FedGetCommonIndicatorsTool

config = {'api_key': 'your_api_key_here'}
tool = FedGetCommonIndicatorsTool(config)

# Get key economic indicators
result = tool.execute({
    "indicators": [
        "gdp",
        "unemployment",
        "inflation",
        "fed_rate",
        "treasury_10y",
        "sp500"
    ]
})

print("US Economic Dashboard")
print("=" * 60)
print(f"Last Updated: {result['last_updated']}\n")

for indicator, data in result['indicators'].items():
    if 'error' not in data:
        print(f"{data['title']}:")
        print(f"  Value: {data['value']} {data['units']}")
        print(f"  As of: {data['date']}")
        print()
```

### Example 5: Compare Yield Curve

```python
from tools.impl.fed_reserve_tool_refactored import FedGetLatestTool

config = {'api_key': 'your_api_key_here'}
tool = FedGetLatestTool(config)

# Get multiple treasury rates
rates = {}
for indicator in ['treasury_2y', 'treasury_10y']:
    result = tool.execute({'indicator': indicator})
    rates[indicator] = result['value']

# Calculate spread
spread = rates['treasury_10y'] - rates['treasury_2y']

print("Treasury Yield Curve")
print(f"2-Year: {rates['treasury_2y']:.2f}%")
print(f"10-Year: {rates['treasury_10y']:.2f}%")
print(f"Spread: {spread:.2f}%")

if spread < 0:
    print("⚠️  Inverted yield curve detected!")
elif spread < 0.5:
    print("⚠️  Flat yield curve")
else:
    print("✓ Normal yield curve")
```

### Example 6: Historical Inflation Analysis

```python
from tools.impl.fed_reserve_tool_refactored import FedGetSeriesTool

config = {'api_key': 'your_api_key_here'}
tool = FedGetSeriesTool(config)

# Get 10 years of CPI data
result = tool.execute({
    "indicator": "inflation",
    "start_date": "2014-01-01",
    "end_date": "2024-12-31"
})

# Calculate year-over-year changes
observations = result['observations']

print("Inflation Analysis (CPI)")
print("=" * 40)

for i in range(12, len(observations), 12):
    current = observations[i]
    year_ago = observations[i-12]
    
    if current['value'] and year_ago['value']:
        yoy_change = ((current['value'] - year_ago['value']) / year_ago['value']) * 100
        print(f"{current['date']}: {yoy_change:.2f}% YoY")
```

### Example 7: Demo Mode Testing

```python
from tools.impl.fed_reserve_tool_refactored import FedGetSeriesTool

# No API key - uses demo mode
tool = FedGetSeriesTool()

# Still works, returns demo data
result = tool.execute({
    "indicator": "gdp",
    "limit": 5
})

print("Demo Mode Example:")
print(f"Series: {result['title']}")
print(f"Observations: {len(result['observations'])}")

if 'note' in result:
    print(f"\nNote: {result['note']}")
```

---

## Schema Reference

### Common Input Schema Elements

#### Series Identifier
```json
{
  "series_id": {
    "type": "string",
    "description": "FRED series ID (e.g., 'GDP', 'UNRATE', 'DGS10')"
  },
  "indicator": {
    "type": "string",
    "enum": ["gdp", "unemployment", "inflation", "fed_rate", 
             "treasury_10y", "treasury_2y", "sp500", "housing", 
             "retail", "industrial", "m2", "pce"]
  }
}
```

#### Date Parameters
```json
{
  "start_date": {
    "type": "string",
    "format": "YYYY-MM-DD",
    "description": "Start date for time series"
  },
  "end_date": {
    "type": "string",
    "format": "YYYY-MM-DD",
    "description": "End date for time series"
  }
}
```

#### Limit Parameter
```json
{
  "limit": {
    "type": "integer",
    "minimum": 1,
    "maximum": 1000,
    "default": 100,
    "description": "Maximum number of observations"
  }
}
```

### Common Output Schema Elements

#### Time Series Response
```json
{
  "series_id": "string",
  "title": "string",
  "units": "string",
  "frequency": "string",
  "last_updated": "string",
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
  "series_id": "string",
  "title": "string",
  "units": "string",
  "frequency": "string",
  "date": "YYYY-MM-DD",
  "value": "number | null",
  "last_updated": "string"
}
```

#### Search Results Response
```json
{
  "query": "string",
  "count": "integer",
  "results": [
    {
      "id": "string",
      "title": "string",
      "units": "string",
      "frequency": "string",
      "popularity": "integer",
      "observation_start": "YYYY-MM-DD",
      "observation_end": "YYYY-MM-DD"
    }
  ]
}
```

---

## Limitations

### API Limitations

1. **Rate Limits**:
   - 120 requests per minute per API key
   - No daily limit for standard usage
   - Excessive use may result in temporary blocks

2. **Data Availability**:
   - Historical data varies by series
   - Some series updated daily, others monthly/quarterly
   - Recent data may have revisions

3. **Series Limits**:
   - Maximum 1000 observations per request
   - Use pagination for larger datasets
   - Some series have limited history

### Demo Mode Limitations

1. **Functionality**:
   - ✓ All tools operational
   - ✓ Correct response formats
   - ✗ Real economic data
   - ✗ Actual historical values
   - ✗ Complete search results

2. **Data Quality**:
   - Synthetic/mock data
   - Simplified patterns
   - Not suitable for analysis
   - Testing/development only

### Technical Limitations

1. **Request Size**:
   - No explicit size limits
   - Large date ranges may be slow
   - Consider breaking into smaller requests

2. **Response Format**:
   - JSON only
   - No XML support
   - Values may be null (missing data)

3. **Network**:
   - Standard urllib timeouts
   - No automatic retries
   - Network errors require handling

### Data Interpretation Caveats

1. **Revisions**:
   - Economic data subject to revisions
   - Preliminary vs final releases
   - Historical values may change

2. **Frequency**:
   - Daily: Business days only (no weekends/holidays)
   - Monthly: Released on specific schedules
   - Quarterly: Significant delays

3. **Seasonal Adjustment**:
   - Many series have SA (seasonally adjusted) versions
   - SA vs NSA (not seasonally adjusted)
   - Different series IDs for each

---

## Error Handling

### Common Errors

#### 1. Invalid API Key
```python
ValueError: Failed to get series data: HTTP 400 Bad Request
```

**Cause**: Invalid or missing API key  
**Solution**: Check API key, register at fred.stlouisfed.org

#### 2. Series Not Found
```python
ValueError: Failed to get series data: Series does not exist
```

**Cause**: Invalid series ID  
**Solution**: Use `fed_search_series` to find correct ID

#### 3. Rate Limit Exceeded
```python
ValueError: Failed to get series data: HTTP 429 Too Many Requests
```

**Cause**: Exceeded 120 requests/minute  
**Solution**: Implement rate limiting, add delays between requests

#### 4. No Data Available
```json
{
  "observations": []
}
```

**Cause**: No data for specified date range  
**Solution**: Check series observation dates, adjust date range

#### 5. Missing Indicator
```json
{
  "error": "Unknown indicator: xyz"
}
```

**Solution**: Use valid indicator from common_series list

### Error Handling Best Practices

```python
import time
from typing import Optional

def fetch_with_retry(tool, arguments, max_retries=3) -> Optional[Dict]:
    """Fetch FRED data with retry logic"""
    for attempt in range(max_retries):
        try:
            result = tool.execute(arguments)
            return result
            
        except ValueError as e:
            error_msg = str(e)
            
            # Don't retry for client errors
            if "Series does not exist" in error_msg:
                print(f"Invalid series ID")
                return None
            
            if "Bad Request" in error_msg:
                print(f"Check API key")
                return None
            
            # Retry for rate limits and server errors
            if "429" in error_msg or "500" in error_msg:
                if attempt == max_retries - 1:
                    print(f"Failed after {max_retries} attempts")
                    return None
                
                wait_time = 2 ** attempt
                print(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            # Unknown error
            print(f"Error: {error_msg}")
            return None
    
    return None

# Usage
config = {'api_key': 'your_key'}
tool = FedGetSeriesTool(config)
result = fetch_with_retry(tool, {'indicator': 'gdp'})
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=128)
def get_latest_cached(indicator: str, cache_minutes: int = 30):
    """Cache latest values for specified duration"""
    # Note: lru_cache doesn't support TTL, this is conceptual
    tool = FedGetLatestTool(config={'api_key': 'your_key'})
    result = tool.execute({"indicator": indicator})
    return result
```

### Batch Operations

**Inefficient** - Multiple individual calls:
```python
# BAD: 5 separate API calls
gdp = get_latest("gdp")
unemployment = get_latest("unemployment")
inflation = get_latest("inflation")
fed_rate = get_latest("fed_rate")
treasury = get_latest("treasury_10y")
```

**Efficient** - Single batch call:
```python
# GOOD: 1 tool call (still N API calls to FRED, but optimized)
tool = FedGetCommonIndicatorsTool(config={'api_key': 'your_key'})
dashboard = tool.execute({
    "indicators": ["gdp", "unemployment", "inflation", "fed_rate", "treasury_10y"]
})
```

### Response Size Optimization

| Tool | Avg Response Size | Typical API Calls |
|------|-------------------|-------------------|
| fed_get_latest | ~300 bytes | 1 |
| fed_get_series (10 obs) | ~800 bytes | 2 |
| fed_get_series (100 obs) | ~5 KB | 2 |
| fed_search_series | ~2-5 KB | 1 |
| fed_get_common_indicators | ~2-4 KB | N (indicators) |

### Recommended Cache TTL

| Data Type | Update Frequency | Recommended Cache TTL |
|-----------|------------------|----------------------|
| Daily series (rates, stocks) | Daily | 1 hour |
| Monthly series (CPI, unemployment) | Monthly | 24 hours |
| Quarterly series (GDP) | Quarterly | 7 days |
| Annual series | Yearly | 30 days |
| Search results | Static | 7 days |

### Rate Limiting Implementation

```python
import time
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, requests_per_minute=120):
        self.requests_per_minute = requests_per_minute
        self.requests = []
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        now = datetime.now()
        
        # Remove requests older than 1 minute
        self.requests = [
            r for r in self.requests 
            if now - r < timedelta(minutes=1)
        ]
        
        # Check if at limit
        if len(self.requests) >= self.requests_per_minute:
            oldest = min(self.requests)
            wait_until = oldest + timedelta(minutes=1)
            wait_seconds = (wait_until - now).total_seconds()
            
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        
        # Record this request
        self.requests.append(now)

# Usage
limiter = RateLimiter(requests_per_minute=120)
tool = FedGetLatestTool(config={'api_key': 'your_key'})

for indicator in ['gdp', 'unemployment', 'inflation']:
    limiter.wait_if_needed()
    result = tool.execute({'indicator': indicator})
```

---

## Appendix A: Popular FRED Series

### Key Economic Indicators

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| GDP | Gross Domestic Product | Quarterly |
| GDPC1 | Real GDP | Quarterly |
| UNRATE | Unemployment Rate | Monthly |
| PAYEMS | Nonfarm Payrolls | Monthly |
| CPIAUCSL | Consumer Price Index | Monthly |
| PCEPI | PCE Price Index | Monthly |
| DFF | Fed Funds Rate | Daily |
| DGS10 | 10-Year Treasury | Daily |
| DGS2 | 2-Year Treasury | Daily |

### Financial Markets

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| SP500 | S&P 500 | Daily |
| DCOILWTICO | WTI Oil Price | Daily |
| DEXUSEU | USD/EUR Exchange Rate | Daily |
| VIXCLS | VIX Volatility Index | Daily |
| BAMLH0A0HYM2 | High Yield Spread | Daily |

### Housing

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| HOUST | Housing Starts | Monthly |
| PERMIT | Building Permits | Monthly |
| CSUSHPISA | Case-Shiller Home Price Index | Monthly |
| MORTGAGE30US | 30-Year Mortgage Rate | Weekly |

### Consumer & Retail

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| RSXFS | Retail Sales | Monthly |
| PCE | Personal Consumption | Monthly |
| UMCSENT | Consumer Sentiment | Monthly |
| TOTALSA | Vehicle Sales | Monthly |

---

## Appendix B: Quick Reference

### Tool Selection Guide

| Need | Use Tool |
|------|----------|
| Latest single value | fed_get_latest |
| Multiple latest values | fed_get_common_indicators |
| Historical time series | fed_get_series |
| Find series by keyword | fed_search_series |

### Common Workflows

**Workflow 1: Quick Dashboard**
1. `fed_get_common_indicators` - Get all key metrics
2. Display in dashboard UI

**Workflow 2: Detailed Analysis**
1. `fed_search_series` - Find relevant series
2. `fed_get_series` - Get historical data
3. Perform analysis

**Workflow 3: Monitoring**
1. `fed_get_latest` - Get current values
2. Compare to thresholds
3. Generate alerts

### Frequency Codes

| Code | Meaning |
|------|---------|
| D | Daily |
| W | Weekly |
| BW | Bi-Weekly |
| M | Monthly |
| Q | Quarterly |
| SA | Semi-Annual |
| A | Annual |

### Units Common Patterns

| Pattern | Meaning |
|---------|---------|
| Percent | % (rates, ratios) |
| Billions of Dollars | $ in billions |
| Thousands of Units | Count in thousands |
| Index YYYY=100 | Index normalized to base year |
| Percent Change | % change from prior period |

---

## Appendix C: FRED Resources

### Official Resources

- **FRED Website**: https://fred.stlouisfed.org
- **API Documentation**: https://fred.stlouisfed.org/docs/api/fred/
- **Series Search**: https://fred.stlouisfed.org/search
- **Release Calendar**: https://fred.stlouisfed.org/releases/calendar
- **Blog**: https://fredblog.stlouisfed.org

### API Endpoints

- **Series Info**: `/fred/series`
- **Observations**: `/fred/series/observations`
- **Search**: `/fred/series/search`
- **Categories**: `/fred/category`
- **Releases**: `/fred/releases`

### Support

- **API Forum**: https://fred.stlouisfed.org/forum
- **Email**: api@stlouisfed.org
- **Twitter**: @stlouisfed

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025 | Initial release with 4 tools |

---

## Support & Contact

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Copyright**: © 2025-2030 All Rights Reserved

For issues, questions, or feature requests, please contact the author directly.

---

*End of Federal Reserve MCP Tool Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **FRED (Federal Reserve Economic Data)**: A comprehensive database of economic data maintained by the Federal Reserve Bank of St. Louis. SAJHA's Fed tools use the FRED API.

- **API Key**: A unique identifier for authenticating API requests. FRED API requires a free API key available at fred.stlouisfed.org.

- **Time Series**: A sequence of data points indexed by time. FRED provides economic time series data like GDP, inflation, and interest rates.

- **Federal Funds Rate**: The interest rate at which banks lend reserves to each other overnight. A key monetary policy tool tracked in FRED.

- **Treasury Yield**: The return on U.S. government debt securities. Available in multiple maturities (3-month, 2-year, 10-year, 30-year).

- **Economic Indicator**: A statistic about economic activity. FRED provides thousands of indicators including GDP, unemployment, and inflation.

- **JSON-RPC**: The protocol used for MCP tool calls. All Fed tool requests use JSON-RPC 2.0 format.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
