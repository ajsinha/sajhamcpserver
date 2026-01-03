# United Nations MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**Version: 2.2.0**  
**Last Updated: October 31, 2025**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & API Access](#authentication--api-access)
5. [Tool Details](#tool-details)
6. [API Reference](#api-reference)
7. [Usage Examples](#usage-examples)
8. [Schema Specifications](#schema-specifications)
9. [Limitations](#limitations)
10. [Troubleshooting](#troubleshooting)
11. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The United Nations MCP Tool provides access to official UN data through two major data sources: Sustainable Development Goals (SDG) statistics and Comtrade international trade data. It offers nine specialized tools for accessing global statistics, tracking development progress, and analyzing international trade patterns.

### Key Features

- **SDG Data Access**: Track progress on all 17 Sustainable Development Goals
- **Trade Statistics**: Access comprehensive international trade data
- **Official UN Data**: Direct access to authoritative global statistics
- **No API Key Required** (SDG data): Most SDG tools work without authentication
- **Comprehensive Coverage**: 1962-2030 trade data, 2000-2030 SDG data
- **Country-Level Analysis**: Data for 200+ countries and territories
- **MCP Compatible**: Fully compliant with Model Context Protocol

### How It Works

The tool operates through **external API calls to UN data services**:

1. **API Request**: Tool sends requests to UN API endpoints
2. **Data Retrieval**: UN servers process and return official statistics
3. **Response Formatting**: Data is structured into standardized JSON format
4. **Result Delivery**: Clean, formatted data ready for analysis

```
┌─────────────────┐
│  User Query     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   UN MCP Tool   │
└────────┬────────┘
         │
         ▼ HTTPS API Call
┌─────────────────┐
│   UN SDG API    │
│unstats.un.org   │
│  (No auth)      │
└─────────────────┘
         │
┌─────────────────┐
│ UN Comtrade API │
│comtradeapi.un   │
│  .org           │
│ (Requires auth) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON Response  │
└─────────────────┘
```

**Important:** This tool uses **external API calls** to UN servers, NOT web scraping or local database queries.

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────┐
│               United Nations MCP Tool                     │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │    UnitedNationsBaseTool (Base Class)             │  │
│  │  - API Endpoint Management                        │  │
│  │  - SDG Definitions (17 Goals)                     │  │
│  │  - Trade Classifications                          │  │
│  │  - Shared Utilities                               │  │
│  └───────────────────┬────────────────────────────────┘  │
│                      │                                    │
│       ┌──────────────┴──────────────┐                    │
│       │                             │                    │
│  ┌────▼────────┐             ┌─────▼──────┐             │
│  │  SDG Tools  │             │Trade Tools │             │
│  │  (6 tools)  │             │  (3 tools) │             │
│  └─────────────┘             └────────────┘             │
│                                                           │
│  SDG Tools:                  Trade Tools:                │
│  • un_get_sdgs               • un_get_trade_data         │
│  • un_get_sdg_indicators     • un_get_country_trade      │
│  • un_get_sdg_data           • un_get_trade_balance      │
│  • un_get_sdg_targets        • un_compare_trade          │
│  • un_get_sdg_progress                                   │
│                                                           │
└──────────────────────────────────────────────────────────┘
                         │
                         │ HTTPS
                         ▼
              ┌─────────────────┐
              │    UN APIs      │
              │  • SDG API      │
              │  • Comtrade API │
              └─────────────────┘
```

### Class Hierarchy

```python
BaseMCPTool (Abstract Base)
    │
    └── UnitedNationsBaseTool
            │
            ├── UNGetSDGsTool
            ├── UNGetSDGIndicatorsTool
            ├── UNGetSDGDataTool
            ├── UNGetSDGTargetsTool
            ├── UNGetSDGProgressTool
            ├── UNGetTradeDataTool
            ├── UNGetCountryTradeTool
            ├── UNGetTradeBalanceTool
            └── UNCompareCountryTradeTool
```

### Core Components

#### 1. UnitedNationsBaseTool (Base Class)

**Responsibilities:**
- Manage API endpoints
- Define SDG and trade classifications
- Handle API requests
- Format responses
- Error handling

**API Endpoints:**
```python
self.comtrade_url = "https://comtradeapi.un.org/data/v1"
self.sdg_url = "https://unstats.un.org/sdgapi/v1/sdg"
```

**SDG Definitions:**
```python
self.sdgs = {
    '1': 'No Poverty',
    '2': 'Zero Hunger',
    '3': 'Good Health and Well-being',
    '4': 'Quality Education',
    '5': 'Gender Equality',
    '6': 'Clean Water and Sanitation',
    '7': 'Affordable and Clean Energy',
    '8': 'Decent Work and Economic Growth',
    '9': 'Industry, Innovation and Infrastructure',
    '10': 'Reduced Inequalities',
    '11': 'Sustainable Cities and Communities',
    '12': 'Responsible Consumption and Production',
    '13': 'Climate Action',
    '14': 'Life Below Water',
    '15': 'Life on Land',
    '16': 'Peace, Justice and Strong Institutions',
    '17': 'Partnerships for the Goals'
}
```

**Trade Classifications:**
```python
self.trade_flows = {
    'export': 'X',
    'import': 'M',
    're_export': 'RX',
    're_import': 'RM'
}
```

#### 2. UN API Integration

**SDG API Endpoint:** `https://unstats.un.org/sdgapi/v1/sdg`

**Available Endpoints:**
- `/Goal/List` - List all SDGs
- `/Indicator/List` - List all indicators
- `/Indicator/Data` - Get indicator time series
- `/Target/List` - List all targets

**Request Format:**
```http
GET /sdgapi/v1/sdg/Goal/List HTTP/1.1
Host: unstats.un.org
User-Agent: Mozilla/5.0
Accept: application/json
```

**Comtrade API Endpoint:** `https://comtradeapi.un.org/data/v1`

**Authentication:** Required for Comtrade (not implemented in base version)

---

## System Requirements

### Dependencies

```python
# Core Dependencies
import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool
```

### Python Version
- Python 3.7 or higher

### Network Requirements
- Internet connectivity required
- HTTPS access to unstats.un.org
- HTTPS access to comtradeapi.un.org (for trade data)
- Port 443 must be open

### External Services
- **UN SDG API**: Publicly accessible, no authentication
- **UN Comtrade API**: Requires registration and API key
- **No web scraping**: All data via official APIs
- **No local data**: Results come from UN servers

---

## Authentication & API Access

### SDG Tools - No Authentication Required

**UN SDG API is publicly accessible:**
- No API key needed
- No registration required
- Rate limits apply (reasonable use)
- Free for all users

**Example Request:**
```python
url = "https://unstats.un.org/sdgapi/v1/sdg/Goal/List"
headers = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json'
}
```

### Comtrade Tools - Authentication Required

**UN Comtrade API requires registration:**

**How to Get Access:**
1. Visit https://comtradeapi.un.org
2. Register for a free account
3. Verify email address
4. Login to get API subscription key
5. Use key in API requests

**API Key Usage:**
```python
headers = {
    'Ocp-Apim-Subscription-Key': 'your-api-key-here',
    'Accept': 'application/json'
}
```

**Note:** Current implementation has placeholder for Comtrade authentication. Full implementation would require API key configuration.

### Configuration

**Method 1: Config File**
```json
{
  "name": "un_get_trade_data",
  "comtrade_api_key": "your-key-here",
  "enabled": true
}
```

**Method 2: Environment Variable**
```bash
export UN_COMTRADE_API_KEY="your-key-here"
```

---

## Tool Details

### SDG Tools (No Authentication Required)

### 1. un_get_sdgs

**Purpose:** Retrieve list of all 17 Sustainable Development Goals

**Input Schema:**
```json
{
  "include_details": "boolean (default: false)"
}
```

**Output Schema:**
```json
{
  "sdgs": [
    {
      "code": "1",
      "title": "No Poverty",
      "description": "string (if requested)",
      "color": "#E5243B",
      "uri": "string"
    }
  ],
  "count": 17
}
```

**Use Cases:**
- Display SDG overview
- Select SDG for detailed analysis
- Build SDG navigation menus
- Educational resources
- Dashboard visualization

**Example:**
```python
result = tool.execute({
    'include_details': True
})

for sdg in result['sdgs']:
    print(f"SDG {sdg['code']}: {sdg['title']}")
```

---

### 2. un_get_sdg_indicators

**Purpose:** Retrieve all indicators for a specific SDG

**Input Schema:**
```json
{
  "sdg_code": "string (1-17, required)"
}
```

**Output Schema:**
```json
{
  "sdg_code": "1",
  "sdg_title": "No Poverty",
  "indicators": [
    {
      "code": "1.1.1",
      "description": "Proportion of population below poverty line",
      "tier": "Tier I",
      "uri": "string"
    }
  ],
  "count": 14
}
```

**Indicator Tiers:**
- **Tier I**: Established methodology and data widely available
- **Tier II**: Established methodology, limited data
- **Tier III**: No established methodology yet

**Use Cases:**
- Explore measurable targets within an SDG
- Select indicators for data analysis
- Understand SDG measurement methodology
- Research and reporting
- Policy planning

**Example:**
```python
# Get indicators for SDG 13 (Climate Action)
result = tool.execute({
    'sdg_code': '13'
})

print(f"SDG 13 has {result['count']} indicators")
for indicator in result['indicators']:
    print(f"  {indicator['code']}: {indicator['description']}")
```

---

### 3. un_get_sdg_data

**Purpose:** Retrieve historical time series data for a specific SDG indicator

**Input Schema:**
```json
{
  "indicator_code": "string (required, e.g., '1.1.1')",
  "country_code": "string (optional, ISO3 code)",
  "start_year": "integer (optional, 2000-2030)",
  "end_year": "integer (optional, 2000-2030)"
}
```

**Output Schema:**
```json
{
  "indicator_code": "1.1.1",
  "indicator_description": "Poverty headcount ratio",
  "country_code": "IND",
  "country_name": "India",
  "data": [
    {
      "year": 2015,
      "value": 21.9,
      "unit": "%"
    },
    {
      "year": 2020,
      "value": 16.4,
      "unit": "%"
    }
  ],
  "count": 2
}
```

**Data Availability:**
- Most indicators updated annually
- Data typically 1-2 years behind current year
- Coverage varies by country and indicator
- Some indicators updated less frequently

**Use Cases:**
- Track country progress on specific indicators
- Compare historical trends
- Generate data visualizations
- Research and policy analysis
- Report generation
- Academic studies

**Example:**
```python
# Get poverty data for India from 2015-2023
result = tool.execute({
    'indicator_code': '1.1.1',
    'country_code': 'IND',
    'start_year': 2015,
    'end_year': 2023
})

# Plot trend
for point in result['data']:
    print(f"{point['year']}: {point['value']}{point['unit']}")
```

---

### 4. un_get_sdg_targets

**Purpose:** Retrieve all specific targets for an SDG

**Input Schema:**
```json
{
  "sdg_code": "string (1-17, required)"
}
```

**Output Schema:**
```json
{
  "sdg_code": "1",
  "sdg_title": "No Poverty",
  "targets": [
    {
      "code": "1.1",
      "title": "Eradicate extreme poverty",
      "description": "By 2030, eradicate extreme poverty...",
      "uri": "string"
    }
  ],
  "count": 7
}
```

**Target Structure:**
- Each SDG has 5-12 targets
- Targets are numbered (e.g., 1.1, 1.2, ...)
- Each target has specific measurable objectives
- Targets break down goals into actionable items

**Use Cases:**
- Understand specific objectives within an SDG
- Policy planning and alignment
- Project goal setting
- Progress reporting
- Educational resources
- Strategic planning

**Example:**
```python
# Get targets for SDG 7 (Affordable Clean Energy)
result = tool.execute({
    'sdg_code': '7'
})

print(f"SDG 7 has {result['count']} targets:")
for target in result['targets']:
    print(f"\nTarget {target['code']}: {target['title']}")
    print(f"  {target['description']}")
```

---

### 5. un_get_sdg_progress

**Purpose:** Track a country's progress towards SDGs with latest indicator values

**Input Schema:**
```json
{
  "country_code": "string (required, ISO3 code)",
  "sdg_code": "string (optional, 1-17)"
}
```

**Output Schema:**
```json
{
  "country_code": "IND",
  "country_name": "India",
  "sdg_code": "1",
  "sdg_title": "No Poverty",
  "indicators": [
    {
      "indicator_code": "1.1.1",
      "description": "Poverty headcount ratio",
      "latest_data": {
        "year": 2020,
        "value": 16.4,
        "unit": "%"
      },
      "trend": "improving"
    }
  ],
  "overall_progress": "on track"
}
```

**Progress Assessment:**
- **improving**: Values moving toward target
- **declining**: Values moving away from target
- **stable**: Little change over time
- **insufficient_data**: Not enough data to assess

**Use Cases:**
- National development monitoring
- Policy impact assessment
- International development reporting
- Funding allocation decisions
- Comparative country analysis
- Academic research
- Progress dashboards

**Example:**
```python
# Track India's progress on SDG 1 (No Poverty)
result = tool.execute({
    'country_code': 'IND',
    'sdg_code': '1'
})

print(f"Progress on {result['sdg_title']}:")
for indicator in result['indicators']:
    latest = indicator['latest_data']
    print(f"\n{indicator['description']}")
    print(f"  Latest: {latest['value']}{latest['unit']} ({latest['year']})")
    print(f"  Trend: {indicator['trend']}")
```

---

### Trade Tools (Comtrade - Authentication Required)

### 6. un_get_trade_data

**Purpose:** Retrieve bilateral trade data from UN Comtrade database

**Input Schema:**
```json
{
  "reporter_code": "string (required, ISO3 code)",
  "partner_code": "string (default: 'all')",
  "trade_flow": "enum: export|import|re_export|re_import (default: export)",
  "commodity_code": "string or enum (default: 'all')",
  "year": "integer 1962-2030"
}
```

**Commodity Groups:**
- `all` - All commodities (TOTAL)
- `agricultural` - Agricultural products (HS 01-24)
- `mineral` - Mineral products (HS 25-27)
- `chemicals` - Chemicals (HS 28-38)
- `plastics_rubber` - Plastics and rubber (HS 39-40)
- `textiles` - Textiles (HS 50-63)
- `footwear` - Footwear (HS 64-67)
- `metals` - Base metals (HS 72-83)
- `machinery` - Machinery and electrical (HS 84-85)
- `vehicles` - Transport equipment (HS 86-89)
- `optical_instruments` - Optical instruments (HS 90-92)

**Output Schema:**
```json
{
  "reporter": "USA",
  "partner": "CHN",
  "trade_flow": "export",
  "commodity": "machinery",
  "year": 2022,
  "data": [
    {
      "trade_value": 120000000000,
      "quantity": 50000000,
      "commodity_description": "Machinery and equipment"
    }
  ],
  "note": "Requires UN Comtrade authentication"
}
```

**Use Cases:**
- Bilateral trade analysis
- Trade policy research
- Supply chain analysis
- Economic forecasting
- Trade balance calculations
- Market research
- Tariff impact analysis

**Example:**
```python
# Get US exports to China in machinery sector
result = tool.execute({
    'reporter_code': 'USA',
    'partner_code': 'CHN',
    'trade_flow': 'export',
    'commodity_code': 'machinery',
    'year': 2022
})
```

---

### 7. un_get_country_trade

**Purpose:** Retrieve comprehensive trade summary (imports and exports) for a country

**Input Schema:**
```json
{
  "country_code": "string (required, ISO3 code)",
  "year": "integer (optional, defaults to previous year)"
}
```

**Output Schema:**
```json
{
  "country_code": "USA",
  "year": 2022,
  "exports": {
    "total_value": 2100000000000,
    "top_partners": [
      {"country": "CAN", "value": 300000000000},
      {"country": "MEX", "value": 250000000000}
    ],
    "top_commodities": ["machinery", "vehicles", "chemicals"]
  },
  "imports": {
    "total_value": 3200000000000,
    "top_partners": [
      {"country": "CHN", "value": 500000000000},
      {"country": "MEX", "value": 400000000000}
    ],
    "top_commodities": ["machinery", "vehicles", "electronics"]
  },
  "trade_balance": -1100000000000,
  "note": "Requires authentication"
}
```

**Use Cases:**
- Country trade profile analysis
- Economic overview for research
- Trade dependency assessment
- Partner country identification
- Trade policy evaluation
- Economic competitiveness analysis

**Example:**
```python
# Get Germany's complete trade overview for 2022
result = tool.execute({
    'country_code': 'DEU',
    'year': 2022
})

print(f"Germany Trade Summary {result['year']}:")
print(f"Exports: ${result['exports']['total_value']:,.0f}")
print(f"Imports: ${result['imports']['total_value']:,.0f}")
print(f"Balance: ${result['trade_balance']:,.0f}")
```

---

### 8. un_get_trade_balance

**Purpose:** Calculate trade balance (exports minus imports) for a country

**Input Schema:**
```json
{
  "country_code": "string (required, ISO3 code)",
  "partner_code": "string (optional, default: 'all')",
  "year": "integer (optional, defaults to previous year)"
}
```

**Output Schema:**
```json
{
  "country_code": "USA",
  "partner_code": "CHN",
  "year": 2022,
  "data": {
    "exports": 150000000000,
    "imports": 550000000000,
    "balance": -400000000000
  },
  "interpretation": "Trade deficit of $400 billion",
  "note": "Negative balance indicates deficit, positive indicates surplus"
}
```

**Trade Balance Interpretation:**
- **Positive (Surplus)**: Exports > Imports
- **Negative (Deficit)**: Imports > Exports
- **Zero (Balanced)**: Exports = Imports

**Use Cases:**
- Economic competitiveness analysis
- Trade policy evaluation
- Bilateral trade relationship assessment
- Currency valuation analysis
- Economic forecasting
- Policy impact studies

**Example:**
```python
# Get US-China bilateral trade balance
result = tool.execute({
    'country_code': 'USA',
    'partner_code': 'CHN',
    'year': 2022
})

balance = result['data']['balance']
if balance > 0:
    print(f"Trade surplus of ${balance:,.0f}")
else:
    print(f"Trade deficit of ${-balance:,.0f}")
```

---

### 9. un_compare_trade

**Purpose:** Compare trade statistics across multiple countries

**Input Schema:**
```json
{
  "country_codes": "array (required, 2-10 ISO3 codes)",
  "trade_flow": "enum: export|import (default: export)",
  "year": "integer (optional)"
}
```

**Output Schema:**
```json
{
  "trade_flow": "export",
  "year": 2022,
  "countries": [
    {
      "country_code": "CHN",
      "country_name": "China",
      "total_value": 3500000000000,
      "rank": 1,
      "top_partners": ["USA", "JPN", "KOR"]
    },
    {
      "country_code": "USA",
      "country_name": "United States",
      "total_value": 2100000000000,
      "rank": 2,
      "top_partners": ["CAN", "MEX", "CHN"]
    }
  ],
  "summary": {
    "highest": {"code": "CHN", "value": 3500000000000},
    "lowest": {"code": "BRA", "value": 280000000000}
  }
}
```

**Use Cases:**
- Regional trade analysis
- Competitive benchmarking
- Economic bloc comparison (EU, ASEAN, BRICS)
- Trade policy impact assessment
- Market opportunity identification
- Economic rankings
- Comparative studies

**Example:**
```python
# Compare exports among BRICS countries
result = tool.execute({
    'country_codes': ['BRA', 'RUS', 'IND', 'CHN', 'ZAF'],
    'trade_flow': 'export',
    'year': 2022
})

print("BRICS Export Rankings:")
for country in sorted(result['countries'], key=lambda x: x['rank']):
    print(f"{country['rank']}. {country['country_code']}: "
          f"${country['total_value']:,.0f}")
```

---

## API Reference

### Base Class Methods

#### _fetch_sdg_api()
```python
def _fetch_sdg_api(self, endpoint: str) -> List:
    """
    Fetch data from UN SDG API
    
    Args:
        endpoint: API endpoint path (e.g., 'Goal/List')
    
    Returns:
        List of result objects
    
    Raises:
        Exception: If API request fails
    """
```

### Tool Instantiation

```python
from united_nations_tool_refactored import UNITED_NATIONS_TOOLS

# Get tool class
ToolClass = UNITED_NATIONS_TOOLS['un_get_sdgs']

# Create instance
tool = ToolClass(config={
    'name': 'un_get_sdgs',
    'enabled': True
})

# Execute
result = tool.execute({})
```

---

## Usage Examples

### Example 1: List All SDGs

```python
from united_nations_tool_refactored import UNGetSDGsTool

tool = UNGetSDGsTool({})

result = tool.execute({
    'include_details': True
})

print(f"Total SDGs: {result['count']}")
for sdg in result['sdgs']:
    print(f"\nSDG {sdg['code']}: {sdg['title']}")
    print(f"Color: {sdg['color']}")
    if 'description' in sdg:
        print(f"Description: {sdg['description'][:100]}...")
```

### Example 2: Track Country's SDG Progress

```python
from united_nations_tool_refactored import UNGetSDGProgressTool

tool = UNGetSDGProgressTool({})

# Get India's progress on SDG 3 (Health)
result = tool.execute({
    'country_code': 'IND',
    'sdg_code': '3'
})

print(f"{result['country_code']} - {result['sdg_title']}")
print(f"Found {len(result['indicators'])} indicators")

for indicator in result['indicators']:
    print(f"\n{indicator['indicator_code']}: {indicator['description']}")
    latest = indicator.get('latest_data', {})
    if latest:
        print(f"  Latest: {latest.get('value')} ({latest.get('year')})")
        print(f"  Trend: {indicator.get('trend', 'unknown')}")
```

### Example 3: Get SDG Indicator Time Series

```python
from united_nations_tool_refactored import UNGetSDGDataTool

tool = UNGetSDGDataTool({})

# Get poverty data for Brazil
result = tool.execute({
    'indicator_code': '1.1.1',
    'country_code': 'BRA',
    'start_year': 2015,
    'end_year': 2023
})

print(f"Indicator: {result['indicator_description']}")
print(f"Country: {result['country_name']}")
print(f"\nData points: {result['count']}")

for point in result['data']:
    print(f"  {point['year']}: {point['value']}{point['unit']}")
```

### Example 4: Get SDG Targets

```python
from united_nations_tool_refactored import UNGetSDGTargetsTool

tool = UNGetSDGTargetsTool({})

# Get targets for SDG 13 (Climate Action)
result = tool.execute({
    'sdg_code': '13'
})

print(f"{result['sdg_title']}")
print(f"Total targets: {result['count']}\n")

for target in result['targets']:
    print(f"Target {target['code']}: {target['title']}")
    print(f"  {target['description']}\n")
```

### Example 5: Compare Trade Across Countries

```python
from united_nations_tool_refactored import UNCompareCountryTradeTool

tool = UNCompareCountryTradeTool({})

# Compare exports in G7 countries
result = tool.execute({
    'country_codes': ['USA', 'CAN', 'GBR', 'FRA', 'DEU', 'ITA', 'JPN'],
    'trade_flow': 'export',
    'year': 2022
})

print(f"G7 Export Comparison ({result['year']})")
print(f"Trade Flow: {result['trade_flow']}\n")

for country in result['countries']:
    value = country.get('total_value')
    if value:
        print(f"{country['country_code']}: ${value:,.0f}")
    else:
        print(f"{country['country_code']}: {country.get('note', 'N/A')}")
```

### Example 6: Calculate Bilateral Trade Balance

```python
from united_nations_tool_refactored import UNGetTradeBalanceTool

tool = UNGetTradeBalanceTool({})

# Get US-China trade balance
result = tool.execute({
    'country_code': 'USA',
    'partner_code': 'CHN',
    'year': 2022
})

print(f"Trade Balance Analysis ({result['year']})")
print(f"{result['country_code']} with {result['partner_code']}")
print(f"\nExports: ${result['data']['exports']:,.0f}")
print(f"Imports: ${result['data']['imports']:,.0f}")
print(f"Balance: ${result['data']['balance']:,.0f}")

if result['data']['balance'] > 0:
    print("\nResult: Trade Surplus")
else:
    print("\nResult: Trade Deficit")
```

---

## Schema Specifications

### Common Response Fields

**Success Response:**
```json
{
  "sdg_code": "string",
  "count": "integer",
  "data": "array or object",
  "... tool-specific fields"
}
```

**Error Response:**
```json
{
  "error": "string",
  "note": "string"
}
```

### ISO3 Country Codes

Common country codes used in tools:
- USA - United States
- CHN - China
- IND - India
- DEU - Germany
- JPN - Japan
- GBR - United Kingdom
- FRA - France
- BRA - Brazil
- RUS - Russia
- KOR - South Korea
- CAN - Canada
- MEX - Mexico
- ZAF - South Africa

### Data Standards

| Field | Type | Format | Example |
|-------|------|--------|---------|
| year | integer | YYYY | 2022 |
| value | number/null | float | 16.4 |
| code | string | X.Y.Z | "1.1.1" |
| country_code | string | ISO3 | "USA" |
| trade_value | number | USD | 1500000000000 |

---

## Limitations

### API Limitations

1. **Rate Limits**
   - SDG API: Reasonable use (no hard limit published)
   - Comtrade API: Depends on subscription tier
   - Recommended: < 100 requests/minute

2. **Data Availability**
   - SDG data: Typically 1-2 years behind current
   - Trade data: Usually 1-2 year lag
   - Some indicators updated less frequently
   - Not all countries report all indicators

3. **Historical Data**
   - SDG data: Generally 2000-present
   - Trade data: 1962-present (varies by country)
   - Older data may be incomplete

### Authentication Limitations

1. **SDG Tools**
   - Fully functional without authentication
   - Public access to all SDG data
   - No registration needed

2. **Comtrade Tools**
   - Requires API key for production use
   - Free tier available with limits
   - Registration required
   - Current implementation: placeholder only

### Data Quality

1. **Consistency**
   - Data quality varies by country
   - Reporting standards may differ
   - Definitions may change over time

2. **Completeness**
   - Not all indicators available for all countries
   - Missing data common, especially for:
     - Small island nations
     - Conflict-affected countries
     - Recent years

3. **Updates**
   - Annual updates typical
   - Some indicators updated biennially
   - Publication delays vary

### Technical Limitations

1. **Network Dependency**
   - Requires active internet connection
   - UN server availability required
   - No offline mode

2. **Response Times**
   - API calls typically 1-5 seconds
   - Large data requests may take longer
   - Network latency varies

3. **No Caching**
   - Each call makes fresh API request
   - Implement client-side caching if needed

---

## Troubleshooting

### Common Issues

#### Issue 1: No Data Returned

**Symptoms:** Empty data array

**Causes:**
- Indicator not available for country
- No data for specified time period
- Country code incorrect

**Solutions:**
```python
# Check if data exists
result = tool.execute({
    'indicator_code': '1.1.1',
    'country_code': 'USA',
    'start_year': 2015
})

if result['count'] == 0:
    print("No data available for this indicator/country/period")
    print("Try different parameters or check UN SDG database")
```

#### Issue 2: API Connection Error

**Error:** `Failed to fetch from SDG API`

**Causes:**
- No internet connection
- UN servers down
- Firewall blocking
- DNS issues

**Solutions:**
```python
try:
    result = tool.execute({'sdg_code': '1'})
except Exception as e:
    print(f"API Error: {e}")
    # Check internet connectivity
    # Verify unstats.un.org is accessible
    # Check firewall settings
```

#### Issue 3: Invalid Country Code

**Error:** No results or error message

**Cause:** Using incorrect ISO3 country code

**Solution:**
```python
# Common mistakes:
# Wrong: 'US' (ISO2) - Use 'USA' (ISO3)
# Wrong: 'UK' - Use 'GBR'
# Wrong: 'CN' - Use 'CHN'

# Correct usage
result = tool.execute({
    'country_code': 'USA'  # Use ISO3 format
})
```

#### Issue 4: Comtrade Authentication Required

**Message:** `Requires UN Comtrade authentication`

**Cause:** Comtrade tools need API key

**Solution:**
1. Register at https://comtradeapi.un.org
2. Obtain API subscription key
3. Configure in tool (when implemented)

#### Issue 5: Year Out of Range

**Error:** Invalid year parameter

**Solutions:**
```python
# SDG data: 2000-2030
result = tool.execute({
    'indicator_code': '1.1.1',
    'start_year': 2000,  # Don't go before 2000
    'end_year': 2024
})

# Trade data: 1962-2030
result = tool.execute({
    'reporter_code': 'USA',
    'year': 2022  # Within valid range
})
```

### Debug Mode

Enable detailed logging:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Tool will now log all API calls and responses
tool = UNGetSDGDataTool({})
result = tool.execute({'indicator_code': '1.1.1'})
```

---

## Architecture Diagrams

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│                   (MCP Tool Consumer)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ MCP Protocol
                       │
┌──────────────────────▼──────────────────────────────────────┐
│            United Nations MCP Tools                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              SDG Tools (6)                           │   │
│  │  • get_sdgs          • get_sdg_data                  │   │
│  │  • get_indicators    • get_targets                   │   │
│  │  • get_progress                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Trade Tools (3)                            │   │
│  │  • get_trade_data    • get_country_trade             │   │
│  │  • get_trade_balance • compare_trade                 │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTPS API Calls
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    UN Data APIs                              │
│  ┌────────────────────────┐  ┌────────────────────────┐     │
│  │    UN SDG API          │  │   UN Comtrade API      │     │
│  │  unstats.un.org        │  │  comtradeapi.un.org    │     │
│  │  • No Auth Required    │  │  • Auth Required       │     │
│  │  • Public Access       │  │  • Subscription Key    │     │
│  └────────────────────────┘  └────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Request Flow - SDG Data

```
User Application
     │
     ├─→ [1] Select SDG Tool
     │        │
     │        └─→ [2] Provide Parameters
     │                 │
     │                 └─→ [3] Tool Validates Input
     │                          │
     │                          └─→ [4] Build API URL
     │                                   │
     │                                   └─→ [5] Make HTTPS Request
     │                                            │
     │                                            └─→ unstats.un.org
     │                                                      │
     │                                                      ▼
     │                                               [6] UN Server
     │                                                  Processes
     │                                                      │
     │                                                      ▼
     │                                               [7] Return JSON
     │                                                      │
     │                                                      ▼
     │                                               [8] Format Data
     │                                                      │
     └──────────────────────────────────────────────────────┴─→ JSON Response
```

### Data Flow Architecture

```
┌──────────────────┐
│   User Query     │
│  SDG or Trade    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Tool Layer     │
│  - Validation    │
│  - URL Building  │
└────────┬─────────┘
         │
         ▼ API Request
┌──────────────────┐
│  HTTP Transport  │
│  urllib.request  │
└────────┬─────────┘
         │
         ▼ HTTPS GET
┌──────────────────┐
│   UN API Server  │
│  • SDG API       │
│  • Comtrade API  │
└────────┬─────────┘
         │
         ▼ Database Query
┌──────────────────┐
│  UN Databases    │
│  • SDG DB        │
│  • Comtrade DB   │
└────────┬─────────┘
         │
         ▼ JSON Response
┌──────────────────┐
│  Formatted Data  │
│  - Results       │
│  - Metadata      │
│  - Counts        │
└────────┬─────────┘
         │
         ▼
   Return to User
```

---

## Best Practices

### 1. Error Handling

```python
# ✓ Good: Handle missing data gracefully
try:
    result = tool.execute({
        'indicator_code': '1.1.1',
        'country_code': 'USA'
    })
    
    if result.get('error'):
        print(f"API Error: {result['error']}")
    elif result['count'] == 0:
        print("No data available")
    else:
        # Process data
        pass
        
except Exception as e:
    print(f"Unexpected error: {e}")
```

### 2. Parameter Validation

```python
# ✓ Good: Validate before API call
def get_sdg_data(sdg_code):
    if not sdg_code.isdigit() or int(sdg_code) not in range(1, 18):
        return {"error": "Invalid SDG code. Must be 1-17"}
    
    tool = UNGetSDGIndicatorsTool({})
    return tool.execute({'sdg_code': sdg_code})
```

### 3. Data Caching

```python
# ✓ Good: Cache static data
from functools import lru_cache
from datetime import timedelta

@lru_cache(maxsize=128)
def get_sdgs_cached():
    tool = UNGetSDGsTool({})
    return tool.execute({'include_details': True})

# SDGs don't change, safe to cache indefinitely
sdgs = get_sdgs_cached()
```

### 4. Batch Processing

```python
# ✓ Good: Process multiple countries efficiently
import time

def get_progress_for_countries(country_codes, sdg_code):
    tool = UNGetSDGProgressTool({})
    results = []
    
    for country_code in country_codes:
        result = tool.execute({
            'country_code': country_code,
            'sdg_code': sdg_code
        })
        results.append(result)
        time.sleep(0.1)  # Rate limiting
    
    return results
```

---

## Performance Considerations

### Optimization Tips

1. **Cache Static Data**
   ```python
   # Cache SDG lists, indicators, targets (rarely change)
   cached_sdgs = None
   
   def get_sdgs():
       global cached_sdgs
       if cached_sdgs is None:
           tool = UNGetSDGsTool({})
           cached_sdgs = tool.execute({})
       return cached_sdgs
   ```

2. **Batch Requests**
   ```python
   # Get multiple years at once
   result = tool.execute({
       'indicator_code': '1.1.1',
       'country_code': 'IND',
       'start_year': 2015,
       'end_year': 2023  # Get range instead of individual years
   })
   ```

3. **Limit Data Range**
   ```python
   # Request only needed years
   result = tool.execute({
       'indicator_code': '1.1.1',
       'start_year': 2020,  # Don't request all historical data
       'end_year': 2023
   })
   ```

### Performance Metrics

| Operation | Typical Time | Factors |
|-----------|-------------|---------|
| Get SDGs | 0.5-2s | Network latency |
| Get Indicators | 1-3s | Number of indicators |
| Get SDG Data | 1-5s | Date range, country filter |
| Get Targets | 1-3s | Number of targets |
| Trade Data | 2-10s | Authentication, data size |

---

## Metadata

### Tool Registry

```python
UNITED_NATIONS_TOOLS = {
    'un_get_sdgs': UNGetSDGsTool,
    'un_get_sdg_indicators': UNGetSDGIndicatorsTool,
    'un_get_sdg_data': UNGetSDGDataTool,
    'un_get_sdg_targets': UNGetSDGTargetsTool,
    'un_get_sdg_progress': UNGetSDGProgressTool,
    'un_get_trade_data': UNGetTradeDataTool,
    'un_get_country_trade': UNGetCountryTradeTool,
    'un_get_trade_balance': UNGetTradeBalanceTool,
    'un_compare_trade': UNCompareCountryTradeTool
}
```

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-10-31 | Initial release |

### Rate Limits (Recommended)

| Tool Category | Requests/Min | Cache TTL |
|---------------|--------------|-----------|
| SDG Tools | 60 | 3600s (1 hour) |
| Trade Tools | 60 | 3600s (1 hour) |

---

## Support & Resources

### Documentation
- **UN SDG Platform:** https://unstats.un.org/sdgs/
- **UN Comtrade:** https://comtradeapi.un.org
- **SDG Indicators:** https://unstats.un.org/sdgs/indicators/database
- **SDG API Docs:** https://unstats.un.org/sdgapi/swagger/

### Contact Information
- **Author:** Ashutosh Sinha
- **Email:** ajsinha@gmail.com

### External Resources
- **UN Statistics Division:** https://unstats.un.org
- **SDG Knowledge Platform:** https://sustainabledevelopment.un.org
- **Comtrade Documentation:** https://comtradedeveloper.un.org

---

## Legal

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**

This software and documentation are proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.

**Email:** ajsinha@gmail.com

### Third-Party Services

This tool uses UN data services:
- **Service Provider:** United Nations
- **Data Sources:** UN Statistics Division, UN Comtrade
- **Terms:** https://www.un.org/en/about-us/terms-of-use
- **API Access:** Free for SDG data; Registration required for Comtrade

### Data Usage

- All data sourced from official UN databases
- Data subject to UN terms and conditions
- Proper attribution to UN required for publications
- Review UN data policies for commercial use

---

*End of Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **United Nations (UN)**: An international organization promoting peace, security, and cooperation among nations.

- **UN Data**: The United Nations Statistics Division's data portal providing access to statistical databases.

- **SDG (Sustainable Development Goals)**: The UN's 17 global goals for sustainable development by 2030.

- **UNSD (United Nations Statistics Division)**: The UN body responsible for compiling and disseminating global statistics.

- **Country Code**: ISO standard codes for countries. Required for UN data queries.

- **Indicator**: A specific measurable value tracked over time (e.g., literacy rate, life expectancy).

- **Treaty**: A formal agreement between nations. UN maintains databases of international treaties.

- **Human Development Index (HDI)**: A composite index measuring average achievement in health, education, and income.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
