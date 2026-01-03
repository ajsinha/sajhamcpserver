# Yahoo Finance MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & API Keys](#authentication--api-keys)
5. [Tool Details](#tool-details)
6. [Technical Implementation](#technical-implementation)
7. [Schema Specifications](#schema-specifications)
8. [Usage Examples](#usage-examples)
9. [Limitations & Best Practices](#limitations--best-practices)
10. [Error Handling](#error-handling)
11. [Appendix](#appendix)

---

## Overview

The Yahoo Finance MCP Tool is a comprehensive suite of three specialized financial data tools designed to interact with Yahoo Finance's public API. This tool suite provides seamless access to real-time stock quotes, historical price data, and symbol search capabilities without requiring API keys or complex authentication.

### Key Features

- **No API Key Required**: Free access to Yahoo Finance's public API
- **Real-Time Data**: Current stock prices and market statistics
- **Historical Data**: OHLCV data with configurable time periods and intervals
- **Symbol Search**: Find ticker symbols by company name or keyword
- **Multi-Asset Support**: Stocks, ETFs, indices, mutual funds, cryptocurrencies
- **Corporate Actions**: Dividend and stock split events tracking
- **Rate Limiting**: Built-in rate limiting (60 requests per hour)
- **Caching**: Variable TTL for improved performance (60-3600 seconds)

### Tool Suite Components

1. **yahoo_get_quote** - Real-time stock quotes with market statistics
2. **yahoo_get_history** - Historical OHLCV data with corporate events
3. **yahoo_search_symbols** - Symbol and company search

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Tool Framework                          │
│                    (BaseMCPTool Interface)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ inherits
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                   YahooFinanceBaseTool                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  - API endpoint configuration                            │  │
│  │  - HTTP request handling                                 │  │
│  │  - Error management                                      │  │
│  │  - Header configuration                                  │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────┬──────────────────┬────────────────┬────────────────┘
            │                  │                │
            │ inherits         │ inherits       │ inherits
            ↓                  ↓                ↓
  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────┐
  │YahooGetQuoteTool │  │YahooGetHistory  │  │YahooSearch       │
  │                  │  │Tool             │  │SymbolsTool       │
  │ - Real-time      │  │                 │  │                  │
  │   quotes         │  │ - Historical    │  │ - Symbol search  │
  │ - Market stats   │  │   OHLCV data    │  │ - Company lookup │
  │ - PE ratio       │  │ - Dividends     │  │ - Exchange filter│
  │ - Market cap     │  │ - Stock splits  │  │ - Type filter    │
  │ - 52-week range  │  │ - Multi-periods │  │ - Sector/industry│
  └──────────────────┘  └─────────────────┘  └──────────────────┘
            │                  │                │
            └──────────────────┴────────────────┘
                               │
                               ↓
              ┌────────────────────────────────┐
              │    Yahoo Finance API           │
              │  query2.finance.yahoo.com      │
              │  - /v10/finance/quoteSummary   │
              │  - /v8/finance/chart           │
              │  - /v1/finance/search          │
              └────────────────────────────────┘
```

### Component Hierarchy

```
BaseMCPTool (Abstract Base Class)
    │
    └── YahooFinanceBaseTool
            ├── _make_request()      # HTTP communication
            ├── base_url             # API endpoint
            └── headers              # Request headers
            │
            ├── YahooGetQuoteTool
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            ├── YahooGetHistoryTool
            │       ├── period_map           # Period conversions
            │       ├── interval_map         # Interval mappings
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            └── YahooSearchSymbolsTool
                    ├── get_input_schema()
                    ├── get_output_schema()
                    └── execute()
```

### Data Flow Diagram

```
┌──────────┐
│  Client  │
└─────┬────┘
      │ 1. Request with parameters
      ↓
┌─────────────────────┐
│  Tool Instance      │
│  (yahoo_get_quote/  │
│   yahoo_get_history/│
│   yahoo_search_     │
│   symbols)          │
└──────────┬──────────┘
           │ 2. Validate input schema
           ↓
┌─────────────────────────┐
│ YahooFinanceBaseTool    │
│  _make_request()        │
└──────────┬──────────────┘
           │ 3. Build API URL & params
           ↓
┌──────────────────────────┐
│  HTTP Request            │
│  (urllib.request)        │
│  User-Agent: Mozilla/5.0 │
│  Timeout: 10s            │
└──────────┬───────────────┘
           │ 4. API call
           ↓
┌─────────────────────────┐
│  Yahoo Finance API      │
│  - Quote data           │
│  - Historical charts    │
│  - Symbol search        │
└──────────┬──────────────┘
           │ 5. JSON response
           ↓
┌─────────────────────┐
│  Response Parser    │
│  - Extract data     │
│  - Format output    │
│  - Add metadata     │
│  - Handle nulls     │
└──────────┬──────────┘
           │ 6. Structured result
           ↓
┌──────────────────┐
│  Return to Client│
└──────────────────┘
```

### Request Flow for Each Tool

#### Quote Request Flow
```
Client → yahoo_get_quote(symbol="AAPL")
    ↓
Build URL: query2.finance.yahoo.com/v10/finance/quoteSummary/AAPL
    ↓
Modules: price,summaryDetail,defaultKeyStatistics
    ↓
Parse: regularMarketPrice, marketCap, PE ratio, etc.
    ↓
Return: Complete quote data with statistics
```

#### History Request Flow
```
Client → yahoo_get_history(symbol="AAPL", period="1y", interval="1d")
    ↓
Convert period to timestamps (period1, period2)
    ↓
Build URL: query2.finance.yahoo.com/v8/finance/chart/AAPL
    ↓
Parse: OHLCV data, dividends, splits
    ↓
Return: Historical data array with events
```

#### Search Request Flow
```
Client → yahoo_search_symbols(query="Apple", limit=10)
    ↓
Build URL: query2.finance.yahoo.com/v1/finance/search
    ↓
Parameters: q="Apple", quotesCount=10
    ↓
Parse: Symbol list with metadata
    ↓
Return: Search results with company info
```

---

## System Requirements

### Python Dependencies

```python
# Core Python libraries (stdlib only - no external dependencies)
import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
```

### Minimum Requirements

- **Python Version**: 3.7+
- **Network**: Internet connectivity required
- **Dependencies**: None (uses standard library only)
- **Platform**: Cross-platform (Windows, macOS, Linux)
- **Market Hours**: Real-time data available during market hours; delayed otherwise

### Optional Dependencies

- Custom logging framework (if extending BaseMCPTool)
- Testing framework: pytest (for running test suite)
- Data analysis: pandas, numpy (for processing historical data)

---

## Authentication & API Keys

### No Authentication Required ✓

The Yahoo Finance MCP Tool uses **public Yahoo Finance API**, which:

- ✅ **No API key needed**
- ✅ **No registration required**
- ✅ **No OAuth or authentication**
- ✅ **Free for all users**
- ✅ **No rate limit authentication**

### User-Agent Requirement

Yahoo Finance requires a User-Agent header to identify the application:

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
```

**Best Practice**: The tool uses a standard browser User-Agent to ensure compatibility.

### Important Notes

⚠️ **Terms of Service**: Yahoo Finance API is unofficial and provided as-is. Users should:
- Respect rate limits
- Use data responsibly
- Not redistribute data commercially without proper licensing
- Be aware that API structure may change without notice

---

## Tool Details

### 1. YahooGetQuoteTool (yahoo_get_quote)

**Purpose**: Retrieve real-time stock quote data including current price, volume, market cap, and key financial statistics.

**When to Use**:
- Portfolio monitoring
- Real-time price tracking
- Market research
- Investment decisions
- Price alerts

**Input Parameters**:

| Parameter | Type   | Required | Default | Description                              |
|-----------|--------|----------|---------|------------------------------------------|
| symbol    | string | Yes      | -       | Ticker symbol (e.g., AAPL, ^GSPC)        |

**Symbol Format**:
- **Stocks**: AAPL, GOOGL, MSFT, TSLA
- **Indices**: ^GSPC (S&P 500), ^DJI (Dow Jones), ^IXIC (NASDAQ)
- **ETFs**: SPY, QQQ, VOO
- **International**: Add exchange suffix (e.g., NESN.SW for Nestlé)

**Output Structure**:

```json
{
  "symbol": "string",
  "name": "string",
  "price": "number or null",
  "currency": "string",
  "change": "number or null",
  "change_percent": "number or null",
  "volume": "integer or null",
  "avg_volume": "integer or null",
  "market_cap": "number or null",
  "pe_ratio": "number or null",
  "dividend_yield": "number or null",
  "fifty_two_week_high": "number or null",
  "fifty_two_week_low": "number or null",
  "day_high": "number or null",
  "day_low": "number or null",
  "open": "number or null",
  "previous_close": "number or null",
  "last_updated": "string (ISO)"
}
```

**Rate Limiting**: 60 requests/hour  
**Cache TTL**: 60 seconds

---

### 2. YahooGetHistoryTool (yahoo_get_history)

**Purpose**: Retrieve historical OHLCV (Open, High, Low, Close, Volume) data with corporate events for technical analysis and backtesting.

**When to Use**:
- Technical analysis
- Backtesting trading strategies
- Chart generation
- Trend analysis
- Performance tracking
- Dividend analysis

**Input Parameters**:

| Parameter       | Type    | Required | Default | Description                           |
|-----------------|---------|----------|---------|---------------------------------------|
| symbol          | string  | Yes      | -       | Ticker symbol                         |
| period          | string  | No       | "1mo"   | Time period (1d, 5d, 1mo, 3mo, etc.)  |
| interval        | string  | No       | "1d"    | Data interval (1m, 5m, 1h, 1d, etc.)  |
| include_events  | boolean | No       | true    | Include dividends and splits          |

**Period Options**:
- `1d` - 1 day
- `5d` - 5 days
- `1mo` - 1 month
- `3mo` - 3 months
- `6mo` - 6 months
- `1y` - 1 year
- `2y` - 2 years
- `5y` - 5 years
- `10y` - 10 years
- `ytd` - Year to date
- `max` - Maximum available

**Interval Options**:

| Interval | Description      | Best For                |
|----------|------------------|-------------------------|
| 1m, 2m   | 1-2 minutes      | Day trading             |
| 5m, 15m  | 5-15 minutes     | Intraday analysis       |
| 30m, 1h  | 30 min - 1 hour  | Short-term trading      |
| 1d       | Daily            | Long-term analysis      |
| 1wk      | Weekly           | Medium-term trends      |
| 1mo      | Monthly          | Long-term trends        |

**Output Structure**:

```json
{
  "symbol": "string",
  "period": "string",
  "interval": "string",
  "data_points": "integer",
  "history": [
    {
      "date": "string (ISO)",
      "open": "number or null",
      "high": "number or null",
      "low": "number or null",
      "close": "number or null",
      "volume": "integer or null",
      "adjusted_close": "number or null"
    }
  ],
  "dividends": [
    {
      "date": "string (ISO)",
      "amount": "number"
    }
  ],
  "splits": [
    {
      "date": "string (ISO)",
      "ratio": "string"
    }
  ],
  "currency": "string",
  "last_updated": "string (ISO)"
}
```

**Rate Limiting**: 60 requests/hour  
**Cache TTL**: 300 seconds (5 minutes)

**Important Constraints**:
- Intraday data (1m-1h) available for last 30 days only
- Maximum data points vary by interval
- Adjusted close accounts for splits and dividends

---

### 3. YahooSearchSymbolsTool (yahoo_search_symbols)

**Purpose**: Search for stock symbols, ETFs, and other securities by company name, ticker, or keyword.

**When to Use**:
- Symbol discovery
- Company research
- Building watchlists
- Sector exploration
- Competitor analysis

**Input Parameters**:

| Parameter | Type    | Required | Default | Description                           |
|-----------|---------|----------|---------|---------------------------------------|
| query     | string  | Yes      | -       | Search term (1-100 characters)        |
| limit     | integer | No       | 10      | Max results (1-50)                    |
| exchange  | string  | No       | "all"   | Exchange filter                       |

**Exchange Options**:
- `NYSE` - New York Stock Exchange
- `NASDAQ` - NASDAQ Exchange
- `AMEX` - American Stock Exchange
- `LSE` - London Stock Exchange
- `TSX` - Toronto Stock Exchange
- `all` - All exchanges

**Output Structure**:

```json
{
  "query": "string",
  "result_count": "integer",
  "results": [
    {
      "symbol": "string",
      "name": "string",
      "exchange": "string",
      "type": "string",
      "sector": "string or null",
      "industry": "string or null",
      "market_cap": "number or null",
      "description": "string or null"
    }
  ],
  "last_updated": "string (ISO)"
}
```

**Security Types**:
- `EQUITY` - Common stocks
- `ETF` - Exchange-traded funds
- `INDEX` - Market indices
- `MUTUALFUND` - Mutual funds
- `CRYPTOCURRENCY` - Digital currencies
- `FUTURE` - Futures contracts
- `CURRENCY` - Currency pairs

**Rate Limiting**: 60 requests/hour  
**Cache TTL**: 3600 seconds (1 hour)

---

## Technical Implementation

### How It Works

The Yahoo Finance MCP Tool suite uses **HTTP REST API calls** to Yahoo Finance's unofficial public API, not web scraping or database queries.

#### Method: REST API Calls

```
┌─────────────────────────────────────────────────────────────┐
│                    Implementation Method                    │
├─────────────────────────────────────────────────────────────┤
│  ✓ API Calls      (Yahoo Finance REST API)                 │
│  ✗ Web Scraping   (Not used)                               │
│  ✗ Web Crawling   (Not used)                               │
│  ✗ Database Query (Not used)                               │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoints

**Base URL**: `https://query2.finance.yahoo.com`

**Endpoint Details**:

1. **Quote Summary**: `/v10/finance/quoteSummary/{symbol}`
   - Modules: price, summaryDetail, defaultKeyStatistics
   - Returns: Real-time quote data

2. **Chart Data**: `/v8/finance/chart/{symbol}`
   - Parameters: period1, period2, interval, events
   - Returns: Historical OHLCV data

3. **Search**: `/v1/finance/search`
   - Parameters: q (query), quotesCount, newsCount
   - Returns: Symbol search results

### Request Flow

```python
# 1. Build API endpoint
url = f"{self.base_url}/v10/finance/quoteSummary/{symbol}"

# 2. Prepare parameters
params = {
    'modules': 'price,summaryDetail,defaultKeyStatistics'
}

# 3. Encode URL
full_url = url + '?' + urllib.parse.urlencode(params)

# 4. Set headers
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 5. Make request
request = urllib.request.Request(full_url, headers=headers)
response = urllib.request.urlopen(request, timeout=10)

# 6. Parse JSON
data = json.loads(response.read().decode('utf-8'))
```

### Yahoo Finance API Operations

#### 1. Get Quote (yahoo_get_quote)

```python
url = f"{base_url}/v10/finance/quoteSummary/{symbol}"
params = {
    'modules': 'price,summaryDetail,defaultKeyStatistics'
}

# Response structure:
{
    "quoteSummary": {
        "result": [{
            "price": {
                "regularMarketPrice": {"raw": 150.25},
                "marketCap": {"raw": 2500000000000}
            },
            "summaryDetail": {
                "trailingPE": {"raw": 28.5},
                "dividendYield": {"raw": 0.0055}
            }
        }]
    }
}
```

#### 2. Get History (yahoo_get_history)

```python
url = f"{base_url}/v8/finance/chart/{symbol}"
params = {
    'period1': start_timestamp,
    'period2': end_timestamp,
    'interval': '1d',
    'events': 'div,split'
}

# Response structure:
{
    "chart": {
        "result": [{
            "timestamp": [1698739200, 1698825600, ...],
            "indicators": {
                "quote": [{
                    "open": [150.0, 151.2, ...],
                    "high": [152.5, 153.0, ...],
                    "low": [149.8, 150.5, ...],
                    "close": [151.0, 152.0, ...],
                    "volume": [50000000, 55000000, ...]
                }]
            },
            "events": {
                "dividends": {...},
                "splits": {...}
            }
        }]
    }
}
```

#### 3. Search Symbols (yahoo_search_symbols)

```python
url = f"{base_url}/v1/finance/search"
params = {
    'q': query,
    'quotesCount': limit,
    'newsCount': 0,
    'enableFuzzyQuery': 'false'
}

# Response structure:
{
    "quotes": [
        {
            "symbol": "AAPL",
            "shortname": "Apple Inc.",
            "longname": "Apple Inc.",
            "exchange": "NASDAQ",
            "quoteType": "EQUITY",
            "sector": "Technology",
            "industry": "Consumer Electronics"
        }
    ]
}
```

### Error Handling

```python
try:
    response = urllib.request.urlopen(request, timeout=10)
    data = json.loads(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    if e.code == 404:
        raise ValueError("Symbol or resource not found")
    else:
        raise ValueError(f"Failed to fetch data: HTTP {e.code}")
except Exception as e:
    raise ValueError(f"Failed to fetch data: {str(e)}")
```

### Timeout Configuration

- **Request Timeout**: 10 seconds
- **Prevents**: Hanging connections
- **Configurable**: Can be adjusted in `_make_request()` method

### Data Extraction Pattern

Yahoo Finance returns nested dictionary structures with `raw` and `fmt` values:

```python
def get_value(data_dict, key):
    """Safely extract value from nested dict"""
    val = data_dict.get(key, {})
    if isinstance(val, dict):
        return val.get('raw')  # Extract raw numeric value
    return val
```

---

## Schema Specifications

### Input Schema Pattern

All tools follow a consistent input schema pattern with JSON Schema validation:

```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Stock ticker symbol",
      "pattern": "^[A-Z^.]{1,10}$"
    }
  },
  "required": ["symbol"]
}
```

### Output Schema Pattern

All tools return structured data with these common patterns:

```json
{
  "type": "object",
  "properties": {
    "symbol": {"type": "string"},
    "last_updated": {"type": "string"}
  },
  "required": ["symbol"]
}
```

### Validation Rules

1. **Symbol Format**: 1-10 uppercase characters, may include ^ and .
2. **Period Validation**: Must match enum values (1d, 5d, 1mo, etc.)
3. **Interval Validation**: Must match enum values (1m, 5m, 1d, etc.)
4. **Limit Ranges**: 1-50 for search results
5. **Query Length**: 1-100 characters for search queries
6. **Nullable Fields**: Most financial metrics can be null if unavailable

---

## Usage Examples

### Example 1: Get Real-Time Quote

```python
# Initialize the quote tool
quote_tool = YahooGetQuoteTool()

# Get Apple stock quote
result = quote_tool.execute({
    'symbol': 'AAPL'
})

# Output
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "price": 178.72,
  "currency": "USD",
  "change": 2.45,
  "change_percent": 1.39,
  "volume": 52341890,
  "avg_volume": 55234567,
  "market_cap": 2789456123000,
  "pe_ratio": 28.94,
  "dividend_yield": 0.0054,
  "fifty_two_week_high": 199.62,
  "fifty_two_week_low": 164.08,
  "day_high": 179.23,
  "day_low": 177.45,
  "open": 177.89,
  "previous_close": 176.27,
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 2: Get Historical Data

```python
# Initialize the history tool
history_tool = YahooGetHistoryTool()

# Get 1 year of daily data for Tesla
result = history_tool.execute({
    'symbol': 'TSLA',
    'period': '1y',
    'interval': '1d',
    'include_events': True
})

# Output
{
  "symbol": "TSLA",
  "period": "1y",
  "interval": "1d",
  "data_points": 252,
  "history": [
    {
      "date": "2024-10-31T00:00:00",
      "open": 242.50,
      "high": 248.30,
      "low": 241.20,
      "close": 246.80,
      "volume": 95234567,
      "adjusted_close": 246.80
    }
    // ... more data points
  ],
  "dividends": [],
  "splits": [],
  "currency": "USD",
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 3: Intraday Trading Data

```python
# Get 5-minute interval data for today
result = history_tool.execute({
    'symbol': 'GOOGL',
    'period': '1d',
    'interval': '5m'
})

# Returns 78 data points (6.5 trading hours * 12 intervals/hour)
```

### Example 4: Search for Symbols

```python
# Initialize the search tool
search_tool = YahooSearchSymbolsTool()

# Search for electric vehicle companies
result = search_tool.execute({
    'query': 'electric vehicle',
    'limit': 10
})

# Output
{
  "query": "electric vehicle",
  "result_count": 10,
  "results": [
    {
      "symbol": "TSLA",
      "name": "Tesla, Inc.",
      "exchange": "NASDAQ",
      "type": "EQUITY",
      "sector": "Consumer Cyclical",
      "industry": "Auto Manufacturers",
      "market_cap": 789456123000,
      "description": null
    },
    {
      "symbol": "RIVN",
      "name": "Rivian Automotive, Inc.",
      "exchange": "NASDAQ",
      "type": "EQUITY",
      "sector": "Consumer Cyclical",
      "industry": "Auto Manufacturers",
      "market_cap": 12345678900,
      "description": null
    }
    // ... more results
  ],
  "last_updated": "2025-10-31T15:30:45.123456"
}
```

### Example 5: Market Index Quote

```python
# Get S&P 500 index data
result = quote_tool.execute({
    'symbol': '^GSPC'
})

# Get NASDAQ Composite
result = quote_tool.execute({
    'symbol': '^IXIC'
})

# Get Dow Jones Industrial Average
result = quote_tool.execute({
    'symbol': '^DJI'
})
```

### Example 6: ETF Data

```python
# Search for tech ETFs
result = search_tool.execute({
    'query': 'technology ETF',
    'limit': 5
})

# Get ETF quote
result = quote_tool.execute({
    'symbol': 'QQQ'  # Invesco QQQ Trust
})
```

### Example 7: Complete Analysis Workflow

```python
# Step 1: Search for companies in a sector
search_tool = YahooSearchSymbolsTool()
companies = search_tool.execute({
    'query': 'semiconductor',
    'exchange': 'NASDAQ',
    'limit': 20
})

# Step 2: Get current quotes for top companies
quote_tool = YahooGetQuoteTool()
quotes = []
for company in companies['results'][:5]:
    quote = quote_tool.execute({
        'symbol': company['symbol']
    })
    quotes.append(quote)

# Step 3: Get historical data for technical analysis
history_tool = YahooGetHistoryTool()
historical_data = {}
for company in companies['results'][:5]:
    history = history_tool.execute({
        'symbol': company['symbol'],
        'period': '1y',
        'interval': '1d'
    })
    historical_data[company['symbol']] = history

# Step 4: Analyze performance
for symbol, data in historical_data.items():
    first_close = data['history'][0]['close']
    last_close = data['history'][-1]['close']
    performance = ((last_close - first_close) / first_close) * 100
    print(f"{symbol}: {performance:.2f}% annual return")
```

### Example 8: Dividend Analysis

```python
# Get historical data with dividend events
result = history_tool.execute({
    'symbol': 'AAPL',
    'period': '5y',
    'interval': '1d',
    'include_events': True
})

# Analyze dividends
print(f"Total dividends paid: {len(result['dividends'])}")
total_dividend = sum(div['amount'] for div in result['dividends'])
print(f"Total dividend amount: ${total_dividend:.2f}")
```

### Example 9: Stock Split Tracking

```python
# Track stock splits
result = history_tool.execute({
    'symbol': 'TSLA',
    'period': 'max',
    'interval': '1d',
    'include_events': True
})

# Display splits
for split in result['splits']:
    print(f"Split on {split['date']}: {split['ratio']}")
```

### Example 10: Multi-Exchange Search

```python
# Search across specific exchanges
exchanges = ['NYSE', 'NASDAQ', 'AMEX']

all_results = []
for exchange in exchanges:
    result = search_tool.execute({
        'query': 'technology',
        'exchange': exchange,
        'limit': 10
    })
    all_results.extend(result['results'])

print(f"Found {len(all_results)} technology companies across {len(exchanges)} exchanges")
```

---

## Limitations & Best Practices

### Rate Limiting

**Configured Limits**:
- **Rate Limit**: 60 requests per hour (all tools)
- **Quote Cache TTL**: 60 seconds
- **History Cache TTL**: 300 seconds (5 minutes)
- **Search Cache TTL**: 3600 seconds (1 hour)
- **Timeout**: 10 seconds per request

**Best Practices**:
```python
import time

def rate_limited_quotes(symbols, delay=1.0):
    """Fetch quotes with rate limiting"""
    quotes = []
    for symbol in symbols:
        quote = quote_tool.execute({'symbol': symbol})
        quotes.append(quote)
        time.sleep(delay)  # Prevent rate limiting
    return quotes
```

### Yahoo Finance API Limitations

1. **Intraday Data**: Only last 30 days available for minute intervals
2. **Data Accuracy**: Prices may be delayed by 15-20 minutes outside market hours
3. **Historical Range**: Maximum available data varies by symbol
4. **Null Values**: Many metrics may be null for certain securities
5. **API Stability**: Unofficial API may change without notice
6. **Symbol Coverage**: Not all international symbols supported

### Content Limitations

- **Real-time vs Delayed**: Data may be delayed outside market hours
- **Symbol Format**: Must use correct Yahoo Finance symbol format
- **Corporate Actions**: Historical data adjusted for splits/dividends
- **Missing Data**: Some securities lack complete fundamental data
- **Index Data**: Indices may have limited historical data

### Best Practices

#### 1. Error Handling

```python
try:
    result = tool.execute(params)
except ValueError as e:
    if "not found" in str(e):
        print(f"Symbol not found: {params['symbol']}")
    else:
        print(f"Error: {e}")
    # Implement retry logic or fallback
```

#### 2. Input Validation

```python
def validate_symbol(symbol):
    """Validate stock symbol format"""
    import re
    pattern = r'^[A-Z^.]{1,10}$'
    if not re.match(pattern, symbol.upper()):
        raise ValueError(f"Invalid symbol format: {symbol}")
    return symbol.upper()
```

#### 3. Null Handling

```python
def safe_get(data, field, default=0):
    """Safely get value with default"""
    value = data.get(field)
    return value if value is not None else default

# Usage
price = safe_get(quote, 'price', 0)
pe_ratio = safe_get(quote, 'pe_ratio', None)
```

#### 4. Caching Results

```python
from functools import lru_cache
from datetime import datetime, timedelta

cache_expiry = {}

def cached_quote(symbol, ttl=60):
    """Cache quote data for TTL seconds"""
    key = f"quote_{symbol}"
    
    if key in cache_expiry:
        if datetime.now() < cache_expiry[key]['expiry']:
            return cache_expiry[key]['data']
    
    data = quote_tool.execute({'symbol': symbol})
    cache_expiry[key] = {
        'data': data,
        'expiry': datetime.now() + timedelta(seconds=ttl)
    }
    return data
```

#### 5. Batch Processing

```python
def batch_get_quotes(symbols, batch_size=5, delay=1.0):
    """Fetch quotes in batches with rate limiting"""
    quotes = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        for symbol in batch:
            try:
                quote = quote_tool.execute({'symbol': symbol})
                quotes.append(quote)
            except ValueError as e:
                print(f"Error fetching {symbol}: {e}")
        if i + batch_size < len(symbols):
            time.sleep(delay * batch_size)
    return quotes
```

#### 6. Period Selection for Historical Data

```python
# Choose appropriate period and interval combinations
period_interval_map = {
    '1d': ['1m', '2m', '5m', '15m', '30m', '1h'],
    '5d': ['5m', '15m', '30m', '1h'],
    '1mo': ['30m', '1h', '1d'],
    '3mo': ['1d'],
    '1y': ['1d', '1wk'],
    '5y': ['1d', '1wk', '1mo'],
    'max': ['1d', '1wk', '1mo']
}

def get_valid_interval(period):
    """Get valid intervals for a period"""
    return period_interval_map.get(period, ['1d'])
```

### Performance Optimization

1. **Cache Frequently Accessed Data**: Store quote data for reuse
2. **Batch Requests**: Group similar queries
3. **Use Appropriate Intervals**: Match interval to analysis needs
4. **Filter Results**: Use exchange filters in search
5. **Connection Pooling**: Reuse HTTP connections

---

## Error Handling

### Error Types

#### 1. HTTP Errors

```python
urllib.error.HTTPError
- 404: Symbol not found
- 429: Too many requests (rate limit)
- 500: Yahoo Finance server error
- 503: Service temporarily unavailable
```

#### 2. Validation Errors

```python
ValueError
- Invalid symbol format
- Invalid period or interval
- Symbol not found in database
- No data available for requested period
```

#### 3. Network Errors

```python
urllib.error.URLError
- Connection timeout
- DNS resolution failure
- Network unreachable
```

### Error Response Format

```python
{
    "error": {
        "type": "ValueError",
        "message": "Symbol or resource not found",
        "code": "SYMBOL_NOT_FOUND"
    }
}
```

### Handling Examples

```python
# Example 1: Handle invalid symbol
try:
    result = quote_tool.execute({'symbol': 'INVALID123'})
except ValueError as e:
    if "not found" in str(e):
        # Try searching for the symbol
        search_results = search_tool.execute({'query': 'INVALID123'})
        if search_results['result_count'] > 0:
            correct_symbol = search_results['results'][0]['symbol']
            result = quote_tool.execute({'symbol': correct_symbol})

# Example 2: Handle timeout
try:
    result = tool.execute(params)
except urllib.error.URLError as e:
    if "timeout" in str(e):
        print("Request timed out. Retrying...")
        time.sleep(2)
        result = tool.execute(params)

# Example 3: Handle rate limiting
def execute_with_backoff(tool, params, max_retries=3):
    """Execute with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return tool.execute(params)
        except ValueError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"Attempt {attempt + 1} failed. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    
# Example 4: Handle missing data gracefully
def safe_quote(symbol):
    """Get quote with fallback for missing data"""
    try:
        quote = quote_tool.execute({'symbol': symbol})
        return {
            'symbol': quote['symbol'],
            'price': quote.get('price', 0),
            'change_percent': quote.get('change_percent', 0),
            'volume': quote.get('volume', 0)
        }
    except ValueError:
        return {
            'symbol': symbol,
            'price': None,
            'change_percent': None,
            'volume': None,
            'error': 'Data not available'
        }
```

---

## Appendix

### A. Symbol Format Examples

| Type              | Symbol    | Description                    |
|-------------------|-----------|--------------------------------|
| US Stocks         | AAPL      | Apple Inc.                     |
| US Stocks         | BRK-A     | Berkshire Hathaway Class A     |
| Indices           | ^GSPC     | S&P 500                        |
| Indices           | ^DJI      | Dow Jones Industrial Average   |
| Indices           | ^IXIC     | NASDAQ Composite               |
| ETFs              | SPY       | SPDR S&P 500 ETF               |
| ETFs              | QQQ       | Invesco QQQ Trust              |
| International     | NESN.SW   | Nestlé (Swiss)                 |
| International     | 7203.T    | Toyota (Tokyo)                 |
| Cryptocurrency    | BTC-USD   | Bitcoin USD                    |
| Currency          | EURUSD=X  | Euro/USD                       |
| Futures           | ES=F      | E-mini S&P 500 Futures         |

### B. Period and Interval Compatibility

| Period | Compatible Intervals                      | Max Data Points |
|--------|-------------------------------------------|-----------------|
| 1d     | 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h      | 390 (1m)        |
| 5d     | 5m, 15m, 30m, 1h, 1d                     | 390 (5m)        |
| 1mo    | 30m, 1h, 1d                               | ~390 (30m)      |
| 3mo    | 1h, 1d                                    | ~390 (1h)       |
| 6mo    | 1d, 1wk                                   | ~126 (1d)       |
| 1y     | 1d, 1wk                                   | ~252 (1d)       |
| 5y     | 1d, 1wk, 1mo                              | ~1260 (1d)      |
| max    | 1d, 1wk, 1mo                              | Varies          |

### C. Market Hours

| Market        | Trading Hours (Local) | Trading Hours (UTC)    |
|---------------|-----------------------|------------------------|
| NYSE/NASDAQ   | 9:30 AM - 4:00 PM ET  | 14:30 - 21:00 UTC      |
| LSE           | 8:00 AM - 4:30 PM GMT | 8:00 - 16:30 UTC       |
| TSX           | 9:30 AM - 4:00 PM ET  | 14:30 - 21:00 UTC      |
| Tokyo Stock   | 9:00 AM - 3:00 PM JST | 0:00 - 6:00 UTC        |

### D. Tool Registry

```python
YAHOO_FINANCE_TOOLS = {
    'yahoo_get_quote': YahooGetQuoteTool,
    'yahoo_get_history': YahooGetHistoryTool,
    'yahoo_search_symbols': YahooSearchSymbolsTool
}

# Dynamic tool instantiation
tool_name = 'yahoo_get_quote'
tool_class = YAHOO_FINANCE_TOOLS[tool_name]
tool_instance = tool_class()
```

### E. Configuration Options

```python
# Default configuration
config = {
    'name': 'yahoo_get_quote',
    'description': 'Retrieve real-time stock quotes',
    'version': '1.0.0',
    'enabled': True,
    'rate_limit': 60,         # requests per hour
    'cache_ttl': 60,          # seconds
    'timeout': 10             # seconds
}

# Initialize with custom config
tool = YahooGetQuoteTool(config)
```

### F. Common Use Cases

**Portfolio Monitoring**:
```python
portfolio = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
for symbol in portfolio:
    quote = quote_tool.execute({'symbol': symbol})
    print(f"{symbol}: ${quote['price']} ({quote['change_percent']:.2f}%)")
```

**Technical Analysis**:
```python
# Get historical data
data = history_tool.execute({
    'symbol': 'AAPL',
    'period': '1y',
    'interval': '1d'
})

# Calculate moving averages
closes = [point['close'] for point in data['history'] if point['close']]
ma_50 = sum(closes[-50:]) / 50
ma_200 = sum(closes[-200:]) / 200

print(f"50-day MA: ${ma_50:.2f}")
print(f"200-day MA: ${ma_200:.2f}")
```

**Sector Comparison**:
```python
sectors = ['technology', 'healthcare', 'finance']
for sector in sectors:
    results = search_tool.execute({
        'query': sector,
        'limit': 10
    })
    print(f"{sector.title()}: {results['result_count']} companies found")
```

### G. Testing Checklist

- [ ] Real-time quote retrieval
- [ ] Historical data with various periods
- [ ] Historical data with various intervals
- [ ] Intraday minute data
- [ ] Dividend event extraction
- [ ] Stock split event extraction
- [ ] Symbol search functionality
- [ ] Exchange filtering
- [ ] Index quote retrieval
- [ ] ETF data retrieval
- [ ] Error handling (invalid symbols)
- [ ] Timeout handling
- [ ] Rate limiting compliance
- [ ] Null value handling

### H. Troubleshooting Guide

**Problem**: "Symbol not found" error
- **Solution**: Verify symbol format, try search tool first, check exchange suffix

**Problem**: Request timeout
- **Solution**: Check internet connection, retry with backoff, increase timeout

**Problem**: No intraday data available
- **Solution**: Check if requesting data older than 30 days, use daily interval

**Problem**: Missing fundamental data (PE ratio, market cap)
- **Solution**: Some securities don't have all metrics, handle nulls appropriately

**Problem**: Rate limit exceeded
- **Solution**: Implement delays between requests, use caching

### I. Version History

- **v1.0.0** (2025): Initial release
  - Three core tools implemented
  - Multi-period and interval support
  - Corporate events tracking
  - Comprehensive error handling

### J. Contributing

For bugs, feature requests, or contributions:
- **Email**: ajsinha@gmail.com
- **Copyright**: © 2025-2030 Ashutosh Sinha
- **License**: All Rights Reserved

### K. Legal Disclaimer

⚠️ **Important**: This tool uses Yahoo Finance's unofficial API. Users should:

- Use data for personal/educational purposes
- Respect rate limits and terms of service
- Not redistribute data commercially
- Verify data accuracy for financial decisions
- Be aware that API may change without notice

The tool author is not responsible for:
- Data accuracy or completeness
- Financial losses from using this data
- API availability or changes
- Terms of service violations

**For commercial use, obtain proper data licenses from official providers.**

---

## Conclusion

The Yahoo Finance MCP Tool provides a robust, efficient, and easy-to-use interface to Yahoo Finance's financial data. With no authentication requirements, comprehensive error handling, and support for multiple asset types, it's an ideal solution for applications requiring stock market data.

**Key Strengths**:
- ✅ No API key required
- ✅ Real-time and historical data
- ✅ Corporate actions tracking
- ✅ Multi-asset type support
- ✅ Flexible time periods and intervals
- ✅ Comprehensive error handling

**Best For**:
- Portfolio monitoring applications
- Trading strategy backtesting
- Financial research tools
- Market analysis dashboards
- Educational projects

For questions, support, or feature requests, please contact:

**Ashutosh Sinha**  
Email: ajsinha@gmail.com

**Copyright © 2025-2030 All Rights Reserved**

---

*End of Document*

---

## Page Glossary

**Key terms referenced in this document:**

- **Stock Quote**: Current price and trading information for a security. Yahoo Finance tool provides real-time and delayed quotes.

- **Historical Data**: Past price and volume information for securities. Available in daily, weekly, and monthly intervals.

- **Market Capitalization**: Total market value of a company's outstanding shares. Calculated as share price times shares outstanding.

- **P/E Ratio (Price-to-Earnings)**: Stock price divided by earnings per share. A common valuation metric.

- **Dividend Yield**: Annual dividend payment divided by stock price. Expressed as a percentage.

- **Options Chain**: List of all available options for a security. Includes calls and puts at various strikes and expirations.

- **Ticker Symbol**: A unique abbreviation identifying a publicly traded security (e.g., AAPL for Apple Inc.).

- **ETF (Exchange-Traded Fund)**: A fund traded on exchanges like stocks. Yahoo Finance tool supports ETF data retrieval.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
