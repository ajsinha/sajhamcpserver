# World Bank MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**Version: 2.3.0**  
**Last Updated: October 31, 2025**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & API Access](#authentication--api-access)
5. [Tool Details](#tool-details)
6. [Common Indicators Reference](#common-indicators-reference)
7. [API Reference](#api-reference)
8. [Usage Examples](#usage-examples)
9. [Schema Specifications](#schema-specifications)
10. [Limitations](#limitations)
11. [Troubleshooting](#troubleshooting)
12. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The World Bank MCP Tool provides comprehensive access to World Bank Open Data API, offering development indicators, economic data, and social statistics for 200+ countries from 1960 to present. It includes 10 specialized tools covering everything from country metadata to cross-country comparisons.

### Key Features

- **16,000+ Development Indicators**: Access comprehensive economic, social, environmental data
- **200+ Countries Coverage**: Data for all World Bank member countries and regions
- **60+ Years of Data**: Historical data from 1960 onwards
- **No API Key Required**: Free, open access to all World Bank data
- **Common Indicator Shortcuts**: 40+ predefined shortcuts for frequently used indicators
- **Multiple Query Methods**: Search by country, indicator, topic, region, or income level
- **Cross-Country Comparisons**: Compare up to 10 countries simultaneously
- **MCP Compatible**: Fully compliant with Model Context Protocol

### How It Works

The tool operates through **direct API calls to World Bank Open Data API**:

1. **API Request**: Tool constructs request to World Bank v2 API
2. **Data Retrieval**: World Bank servers return official statistics in JSON format
3. **Response Processing**: Data is parsed and formatted into standardized structure
4. **Result Delivery**: Clean, structured data ready for analysis

```
┌─────────────────┐
│  User Query     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ World Bank Tool │
└────────┬────────┘
         │
         ▼ HTTPS API Call
┌─────────────────┐
│  World Bank API │
│ api.worldbank   │
│   .org/v2       │
│  (Public API)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON Response  │
└─────────────────┘
```

**Important:** This tool uses **external API calls** to World Bank servers, NOT web scraping or local database queries.

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────┐
│               World Bank MCP Tool Suite                  │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │    WorldBankBaseTool (Base Class)                 │  │
│  │  - API Endpoint: api.worldbank.org/v2             │  │
│  │  - 40+ Common Indicator Mappings                  │  │
│  │  - Request Handler                                │  │
│  │  - Response Parser                                │  │
│  └───────────────────┬────────────────────────────────┘  │
│                      │                                    │
│       ┌──────────────┴──────────────┐                    │
│       │                             │                    │
│  ┌────▼──────────┐           ┌─────▼──────────┐         │
│  │  Metadata     │           │  Data Query    │         │
│  │  Tools (4)    │           │  Tools (6)     │         │
│  └───────────────┘           └────────────────┘         │
│                                                           │
│  Metadata Tools:             Data Query Tools:           │
│  • wb_get_countries          • wb_get_country_data       │
│  • wb_get_indicators         • wb_get_indicator_data     │
│  • wb_get_income_levels      • wb_compare_countries      │
│  • wb_get_lending_types      • wb_search_indicators      │
│  • wb_get_regions            • wb_get_topic_indicators   │
│                                                           │
└──────────────────────────────────────────────────────────┘
                         │
                         │ HTTPS
                         ▼
              ┌─────────────────┐
              │ World Bank API  │
              │    (v2)         │
              │  • Countries    │
              │  • Indicators   │
              │  • Data Series  │
              └─────────────────┘
```

### Class Hierarchy

```python
BaseMCPTool (Abstract Base)
    │
    └── WorldBankBaseTool
            │
            ├── WBGetCountriesTool
            ├── WBGetIndicatorsTool
            ├── WBGetCountryDataTool
            ├── WBGetIndicatorDataTool
            ├── WBSearchIndicatorsTool
            ├── WBCompareCountriesTool
            ├── WBGetIncomeLevelsTool
            ├── WBGetLendingTypesTool
            ├── WBGetRegionsTool
            └── WBGetTopicIndicatorsTool
```

### Core Components

#### 1. WorldBankBaseTool (Base Class)

**Responsibilities:**
- Manage World Bank API v2 endpoint
- Map common indicator shortcuts to codes
- Handle HTTP requests and errors
- Format responses
- Parse JSON data

**API Endpoint:**
```python
self.api_url = "https://api.worldbank.org/v2"
```

**Common Indicator Mappings (40+ shortcuts):**
```python
self.indicator_map = {
    # Economic Indicators
    'gdp': 'NY.GDP.MKTP.CD',                    # GDP (current US$)
    'gdp_per_capita': 'NY.GDP.PCAP.CD',         # GDP per capita
    'gdp_growth': 'NY.GDP.MKTP.KD.ZG',          # GDP growth (annual %)
    'gdp_ppp': 'NY.GDP.MKTP.PP.CD',             # GDP, PPP
    'inflation': 'FP.CPI.TOTL.ZG',              # Inflation, consumer prices
    
    # Population & Demographics
    'population': 'SP.POP.TOTL',                # Total population
    'population_growth': 'SP.POP.GROW',         # Population growth
    'urban_population': 'SP.URB.TOTL.IN.ZS',    # Urban population %
    'life_expectancy': 'SP.DYN.LE00.IN',        # Life expectancy at birth
    'birth_rate': 'SP.DYN.CBRT.IN',             # Birth rate
    'death_rate': 'SP.DYN.CDRT.IN',             # Death rate
    
    # Social Indicators
    'poverty_rate': 'SI.POV.DDAY',              # Poverty headcount $1.90/day
    'gini_index': 'SI.POV.GINI',                # Gini index
    'literacy_rate': 'SE.ADT.LITR.ZS',          # Literacy rate
    'primary_enrollment': 'SE.PRM.NENR',        # Primary school enrollment
    'secondary_enrollment': 'SE.SEC.NENR',      # Secondary enrollment
    'tertiary_enrollment': 'SE.TER.ENRR',       # Tertiary enrollment
    
    # Health Indicators
    'infant_mortality': 'SP.DYN.IMRT.IN',       # Infant mortality rate
    'maternal_mortality': 'SH.STA.MMRT',        # Maternal mortality ratio
    'health_expenditure': 'SH.XPD.CHEX.GD.ZS',  # Health expenditure % GDP
    'hospital_beds': 'SH.MED.BEDS.ZS',          # Hospital beds per 1,000
    
    # Labor & Employment
    'unemployment': 'SL.UEM.TOTL.ZS',           # Unemployment total %
    'labor_force': 'SL.TLF.TOTL.IN',            # Labor force total
    'female_labor_force': 'SL.TLF.CACT.FE.ZS',  # Female labor force %
    
    # Trade & Finance
    'exports': 'NE.EXP.GNFS.CD',                # Exports of goods/services
    'imports': 'NE.IMP.GNFS.CD',                # Imports of goods/services
    'trade_gdp': 'NE.TRD.GNFS.ZS',              # Trade % of GDP
    'fdi_inflow': 'BX.KLT.DINV.CD.WD',          # FDI net inflows
    'external_debt': 'DT.DOD.DECT.CD',          # External debt stocks
    
    # Environment
    'co2_emissions': 'EN.ATM.CO2E.KT',          # CO2 emissions (kt)
    'co2_per_capita': 'EN.ATM.CO2E.PC',         # CO2 per capita
    'renewable_energy': 'EG.FEC.RNEW.ZS',       # Renewable energy %
    'electricity_access': 'EG.ELC.ACCS.ZS',     # Access to electricity %
    'forest_area': 'AG.LND.FRST.ZS',            # Forest area % land
    
    # Technology & Infrastructure
    'internet_users': 'IT.NET.USER.ZS',         # Internet users %
    'mobile_subscriptions': 'IT.CEL.SETS.P2',   # Mobile subscriptions
    'roads_paved': 'IS.ROD.PAVE.ZP'             # Roads paved %
}
```

#### 2. Request Handler

**Method: _make_request()**
```python
def _make_request(self, endpoint: str, params: Dict = None) -> List:
    """
    Make API request to World Bank
    
    Args:
        endpoint: API endpoint path (e.g., 'country', 'indicator')
        params: Query parameters (filters, pagination, etc.)
        
    Returns:
        Parsed JSON response as list [metadata, data]
    
    Raises:
        ValueError: If API request fails or resource not found
    """
```

**Response Format:**
World Bank API returns data in format: `[metadata, data_array]`
- Index 0: Metadata (pagination, totals)
- Index 1: Array of data records

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
- No external packages required (uses standard library)

### Network Requirements
- Internet connectivity required
- HTTPS access to api.worldbank.org
- Port 443 must be open
- Timeout: 15 seconds per request

### External Services
- **World Bank Open Data API v2**: Publicly accessible
- **No registration required**
- **No API key needed**
- **Free unlimited access**
- **No rate limits published** (reasonable use recommended)

---

## Authentication & API Access

### No Authentication Required

**World Bank Open Data API is completely open:**
- No API key needed
- No registration required
- No authentication headers
- Free unlimited access
- No rate limits (use responsibly)

**Example Request:**
```python
url = "https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.CD"
params = {
    'format': 'json',
    'per_page': 100,
    'date': '2010:2023'
}
```

### Rate Limiting Best Practices

While no formal rate limits exist:
- Recommended: < 120 requests/minute
- Cache results when possible
- Use pagination efficiently
- Avoid unnecessary requests

### Data Freshness

- **Economic data**: Updated quarterly
- **Social indicators**: Updated annually
- **Environmental data**: Varies by indicator
- **Typical lag**: 1-2 years for most indicators
- **Real-time data**: Not available

---

## Tool Details

### Metadata Tools

### 1. wb_get_countries

**Purpose:** Retrieve list of all countries and regions with metadata

**Input Schema:**
```json
{
  "income_level": "string (HIC|UMC|LMC|LIC|all, default: all)",
  "region": "string (EAS|ECS|LCN|MEA|NAC|SAS|SSF|WLD|all, default: all)",
  "lending_type": "string (IBD|IDB|IDX|LNX|all, default: all)",
  "per_page": "integer (1-500, default: 300)"
}
```

**Income Levels:**
- **HIC**: High Income Countries
- **UMC**: Upper Middle Income Countries
- **LMC**: Lower Middle Income Countries
- **LIC**: Low Income Countries

**Regions:**
- **EAS**: East Asia & Pacific
- **ECS**: Europe & Central Asia
- **LCN**: Latin America & Caribbean
- **MEA**: Middle East & North Africa
- **NAC**: North America
- **SAS**: South Asia
- **SSF**: Sub-Saharan Africa
- **WLD**: World

**Lending Types:**
- **IBD**: IBRD (International Bank for Reconstruction and Development)
- **IDB**: Blend (IBRD and IDA)
- **IDX**: IDA (International Development Association)
- **LNX**: Not classified

**Output Schema:**
```json
{
  "total_countries": "integer",
  "filters_applied": {
    "income_level": "string",
    "region": "string",
    "lending_type": "string"
  },
  "countries": [
    {
      "id": "US",
      "iso3": "USA",
      "name": "United States",
      "capital": "Washington D.C.",
      "region": {"id": "NAC", "value": "North America"},
      "income_level": {"id": "HIC", "value": "High income"},
      "lending_type": {"id": "LNX", "value": "Not classified"},
      "longitude": "-77.0369",
      "latitude": "38.8951"
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Country discovery and selection
- Regional analysis planning
- Income classification research
- Geographic data enrichment
- Building country filters
- Comparative studies setup

**Example:**
```python
# Get all South Asian countries
result = tool.execute({
    'region': 'SAS'
})

# Get high-income countries only
result = tool.execute({
    'income_level': 'HIC',
    'per_page': 100
})
```

---

### 2. wb_get_indicators

**Purpose:** Browse World Bank's comprehensive catalog of 16,000+ development indicators

**Input Schema:**
```json
{
  "topic_id": "integer (1-21, optional)",
  "source": "integer (1-100, optional)",
  "per_page": "integer (1-1000, default: 100)",
  "page": "integer (min: 1, default: 1)"
}
```

**Topics:**
1. Agriculture & Rural Development
2. Aid Effectiveness
3. Economy & Growth
4. Education
5. Energy & Mining
6. Environment
7. Financial Sector
8. Health
9. Infrastructure
10. Social Protection & Labor
11. Poverty
12. Private Sector
13. Public Sector
14. Science & Technology
15. Social Development
16. Urban Development
17. Gender
18. Trade
19. Climate Change
20. External Debt
21. Millennium Development Goals

**Output Schema:**
```json
{
  "total_indicators": 16820,
  "page": 1,
  "per_page": 100,
  "total_pages": 169,
  "indicators": [
    {
      "id": "NY.GDP.MKTP.CD",
      "name": "GDP (current US$)",
      "source": {"id": "2", "value": "World Development Indicators"},
      "source_note": "Detailed methodology...",
      "source_organization": "World Bank national accounts data",
      "topics": [
        {"id": "3", "value": "Economy & Growth"}
      ]
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Indicator discovery
- Research planning
- Data catalog exploration
- Topic-based analysis
- Methodology review
- Finding appropriate metrics

**Example:**
```python
# Get first 100 indicators
result = tool.execute({
    'per_page': 100
})

# Get health-related indicators
result = tool.execute({
    'topic_id': 8,
    'per_page': 50
})

# Navigate to page 2
result = tool.execute({
    'page': 2,
    'per_page': 100
})
```

---

### 3. wb_get_income_levels

**Purpose:** Retrieve income level classifications and descriptions

**Input Schema:**
```json
{
  "per_page": "integer (1-100, default: 50)"
}
```

**Output Schema:**
```json
{
  "total_levels": 4,
  "income_levels": [
    {
      "id": "HIC",
      "iso2code": "XD",
      "value": "High income"
    },
    {
      "id": "UMC",
      "iso2code": "XT",
      "value": "Upper middle income"
    },
    {
      "id": "LMC",
      "iso2code": "XN",
      "value": "Lower middle income"
    },
    {
      "id": "LIC",
      "iso2code": "XM",
      "value": "Low income"
    }
  ],
  "descriptions": {
    "HIC": "High income countries (GNI per capita > $13,845)",
    "UMC": "Upper middle income countries (GNI $4,516 - $13,845)",
    "LMC": "Lower middle income countries (GNI $1,136 - $4,515)",
    "LIC": "Low income countries (GNI per capita ≤ $1,135)"
  },
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Understanding income classifications
- Building filtered queries
- Country categorization
- Development research
- Policy analysis

---

### 4. wb_get_lending_types

**Purpose:** Retrieve World Bank lending type classifications

**Input Schema:**
```json
{
  "per_page": "integer (1-100, default: 50)"
}
```

**Output Schema:**
```json
{
  "total_types": 4,
  "lending_types": [
    {
      "id": "IBD",
      "iso2code": "XI",
      "value": "IBRD"
    },
    {
      "id": "IDB",
      "iso2code": "XF",
      "value": "Blend"
    },
    {
      "id": "IDX",
      "iso2code": "XH",
      "value": "IDA"
    },
    {
      "id": "LNX",
      "iso2code": "XX",
      "value": "Not classified"
    }
  ],
  "descriptions": {
    "IBD": "IBRD only - countries with higher per capita income",
    "IDB": "Blend - countries eligible for both IBRD and IDA",
    "IDX": "IDA only - poorest countries",
    "LNX": "Not classified"
  },
  "last_updated": "2025-10-31T12:00:00"
}
```

---

### 5. wb_get_regions

**Purpose:** Retrieve geographic region classifications

**Input Schema:**
```json
{
  "per_page": "integer (1-100, default: 50)"
}
```

**Output Schema:**
```json
{
  "total_regions": 8,
  "regions": [
    {"id": "EAS", "value": "East Asia & Pacific"},
    {"id": "ECS", "value": "Europe & Central Asia"},
    {"id": "LCN", "value": "Latin America & Caribbean"},
    {"id": "MEA", "value": "Middle East & North Africa"},
    {"id": "NAC", "value": "North America"},
    {"id": "SAS", "value": "South Asia"},
    {"id": "SSF", "value": "Sub-Saharan Africa"},
    {"id": "WLD", "value": "World"}
  ],
  "descriptions": {
    "EAS": "East Asia & Pacific region",
    "ECS": "Europe & Central Asia region",
    "LCN": "Latin America & Caribbean region",
    "MEA": "Middle East & North Africa region",
    "NAC": "North America region",
    "SAS": "South Asia region",
    "SSF": "Sub-Saharan Africa region",
    "WLD": "World aggregate"
  },
  "last_updated": "2025-10-31T12:00:00"
}
```

---

### Data Query Tools

### 6. wb_get_country_data

**Purpose:** Retrieve time series data for a specific indicator and country

**Input Schema:**
```json
{
  "country_code": "string (required, ISO2/ISO3, e.g., 'US', 'USA')",
  "indicator": "string (shorthand, e.g., 'gdp', 'population')",
  "indicator_code": "string (direct code, e.g., 'NY.GDP.MKTP.CD')",
  "start_year": "integer (1960-2030, optional)",
  "end_year": "integer (1960-2030, optional)",
  "per_page": "integer (1-1000, default: 100)"
}
```

**Note:** Must provide either `indicator` OR `indicator_code`

**Output Schema:**
```json
{
  "country": {
    "id": "US",
    "name": "United States"
  },
  "indicator": {
    "id": "NY.GDP.MKTP.CD",
    "name": "GDP (current US$)"
  },
  "data_points": 54,
  "data": [
    {
      "year": 2023,
      "value": 27360935000000.0,
      "unit": "current US$",
      "decimal": 0
    },
    {
      "year": 2022,
      "value": 25464475000000.0,
      "unit": "current US$",
      "decimal": 0
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Country-specific analysis
- Time series forecasting
- Historical trend analysis
- Economic research
- Policy impact studies
- Country profiles

**Example:**
```python
# Get US GDP 2010-2023 using shorthand
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp',
    'start_year': 2010,
    'end_year': 2023
})

# Get India population using direct code
result = tool.execute({
    'country_code': 'IND',
    'indicator_code': 'SP.POP.TOTL',
    'start_year': 2000,
    'end_year': 2023
})

# Get all available data for China CO2 emissions
result = tool.execute({
    'country_code': 'CHN',
    'indicator': 'co2_emissions'
})
```

---

### 7. wb_get_indicator_data

**Purpose:** Retrieve cross-country data for a specific indicator

**Input Schema:**
```json
{
  "indicator": "string (shorthand, e.g., 'gdp_per_capita')",
  "indicator_code": "string (direct code)",
  "year": "integer (1960-2030, specific year)",
  "start_year": "integer (1960-2030, for range)",
  "end_year": "integer (1960-2030, for range)",
  "income_level": "string (HIC|UMC|LMC|LIC, optional filter)",
  "region": "string (EAS|ECS|LCN|MEA|NAC|SAS|SSF, optional filter)",
  "per_page": "integer (1-1000, default: 100)"
}
```

**Output Schema:**
```json
{
  "indicator": {
    "id": "NY.GDP.PCAP.CD",
    "name": "GDP per capita (current US$)"
  },
  "year_filter": 2023,
  "filters_applied": {
    "income_level": "HIC",
    "region": null
  },
  "country_count": 78,
  "data": [
    {
      "country": {"id": "US", "name": "United States"},
      "year": 2023,
      "value": 76398.59,
      "unit": "current US$"
    },
    {
      "country": {"id": "CHE", "name": "Switzerland"},
      "year": 2023,
      "value": 92434.65,
      "unit": "current US$"
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Cross-country comparisons
- Global rankings
- Regional analysis
- Income group analysis
- Benchmarking
- Finding outliers

**Example:**
```python
# Compare GDP per capita across all countries in 2023
result = tool.execute({
    'indicator': 'gdp_per_capita',
    'year': 2023
})

# Get life expectancy for high-income countries
result = tool.execute({
    'indicator': 'life_expectancy',
    'income_level': 'HIC',
    'year': 2022
})

# Compare CO2 emissions in South Asia over time
result = tool.execute({
    'indicator': 'co2_emissions',
    'region': 'SAS',
    'start_year': 2000,
    'end_year': 2023
})
```

---

### 8. wb_compare_countries

**Purpose:** Side-by-side comparison of multiple countries for a specific indicator

**Input Schema:**
```json
{
  "country_codes": "array (required, 2-10 ISO codes)",
  "indicator": "string (shorthand)",
  "indicator_code": "string (direct code)",
  "start_year": "integer (1960-2030, optional)",
  "end_year": "integer (1960-2030, optional)",
  "most_recent_year": "boolean (default: false)"
}
```

**Output Schema:**
```json
{
  "indicator": {
    "id": "NY.GDP.PCAP.CD",
    "name": "GDP per capita (current US$)"
  },
  "year_range": {
    "start": 2010,
    "end": 2023
  },
  "countries": [
    {
      "country": {"id": "US", "name": "United States"},
      "data": [
        {"year": 2023, "value": 76398.59},
        {"year": 2022, "value": 76348.48}
      ],
      "latest_value": 76398.59,
      "latest_year": 2023,
      "average": 68234.56,
      "min": 48450.23,
      "max": 76398.59
    },
    {
      "country": {"id": "CHN", "name": "China"},
      "data": [
        {"year": 2023, "value": 12720.24},
        {"year": 2022, "value": 12556.33}
      ],
      "latest_value": 12720.24,
      "latest_year": 2023,
      "average": 8567.34,
      "min": 4516.78,
      "max": 12720.24
    }
  ],
  "summary": {
    "highest_country": {"id": "US", "value": 76398.59},
    "lowest_country": {"id": "IND", "value": 2410.37},
    "average_across_countries": 30509.73
  },
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Country benchmarking
- Peer group analysis
- Regional comparisons
- Performance tracking
- Policy evaluation
- Competitive analysis

**Example:**
```python
# Compare GDP per capita of BRICS countries
result = tool.execute({
    'country_codes': ['BRA', 'RUS', 'IND', 'CHN', 'ZAF'],
    'indicator': 'gdp_per_capita',
    'start_year': 2010,
    'end_year': 2023
})

# Compare life expectancy in G7 countries
result = tool.execute({
    'country_codes': ['US', 'CA', 'GB', 'FR', 'DE', 'IT', 'JP'],
    'indicator': 'life_expectancy',
    'most_recent_year': True
})

# Compare latest CO2 emissions
result = tool.execute({
    'country_codes': ['US', 'CHN', 'IND', 'RUS'],
    'indicator': 'co2_per_capita',
    'most_recent_year': True
})
```

---

### 9. wb_search_indicators

**Purpose:** Search for indicators by keyword

**Input Schema:**
```json
{
  "search_term": "string (required, 2-100 chars)",
  "topic_id": "integer (1-21, optional filter)",
  "per_page": "integer (1-500, default: 50)",
  "page": "integer (min: 1, default: 1)"
}
```

**Output Schema:**
```json
{
  "search_term": "renewable energy",
  "total_results": 45,
  "page": 1,
  "per_page": 50,
  "results": [
    {
      "id": "EG.FEC.RNEW.ZS",
      "name": "Renewable energy consumption (% of total)",
      "source_note": "Renewable energy consumption is...",
      "source_organization": "World Bank",
      "topics": [
        {"id": "5", "value": "Energy & Mining"},
        {"id": "6", "value": "Environment"}
      ],
      "relevance_score": 1.0
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Relevance Scoring:**
- Match in name: +0.6
- Match in description: +0.4
- Results sorted by relevance (highest first)

**Use Cases:**
- Indicator discovery
- Research planning
- Finding relevant metrics
- Exploring data availability
- Topic-based searches

**Example:**
```python
# Search for education indicators
result = tool.execute({
    'search_term': 'school enrollment'
})

# Find renewable energy indicators in Energy topic
result = tool.execute({
    'search_term': 'renewable',
    'topic_id': 5,
    'per_page': 20
})

# Search for gender-related indicators
result = tool.execute({
    'search_term': 'female participation',
    'topic_id': 17
})
```

---

### 10. wb_get_topic_indicators

**Purpose:** Retrieve all indicators for a specific development topic

**Input Schema:**
```json
{
  "topic_id": "integer (required, 1-21)",
  "per_page": "integer (1-1000, default: 100)",
  "page": "integer (min: 1, default: 1)"
}
```

**Output Schema:**
```json
{
  "topic": {
    "id": 8,
    "name": "Health",
    "description": "Indicators related to Health"
  },
  "total_indicators": 234,
  "page": 1,
  "per_page": 100,
  "total_pages": 3,
  "indicators": [
    {
      "id": "SH.STA.MMRT",
      "name": "Maternal mortality ratio",
      "source_note": "Maternal mortality ratio is...",
      "source_organization": "WHO, UNICEF, UNFPA, World Bank",
      "source": {"id": "2", "value": "World Development Indicators"}
    }
  ],
  "last_updated": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Thematic research
- Comprehensive topic analysis
- Finding related indicators
- Research scoping
- Topic-based data discovery

**Example:**
```python
# Get all health indicators
result = tool.execute({
    'topic_id': 8,
    'per_page': 100
})

# Get education indicators
result = tool.execute({
    'topic_id': 4,
    'per_page': 50
})

# Get climate change indicators
result = tool.execute({
    'topic_id': 19,
    'per_page': 100
})
```

---

## Common Indicators Reference

### Quick Reference Table

| Category | Indicator | Shorthand | Code |
|----------|-----------|-----------|------|
| **Economic** | GDP (current US$) | `gdp` | NY.GDP.MKTP.CD |
| | GDP per capita | `gdp_per_capita` | NY.GDP.PCAP.CD |
| | GDP growth | `gdp_growth` | NY.GDP.MKTP.KD.ZG |
| | GDP, PPP | `gdp_ppp` | NY.GDP.MKTP.PP.CD |
| | Inflation | `inflation` | FP.CPI.TOTL.ZG |
| **Population** | Total population | `population` | SP.POP.TOTL |
| | Population growth | `population_growth` | SP.POP.GROW |
| | Urban population % | `urban_population` | SP.URB.TOTL.IN.ZS |
| | Life expectancy | `life_expectancy` | SP.DYN.LE00.IN |
| | Birth rate | `birth_rate` | SP.DYN.CBRT.IN |
| | Death rate | `death_rate` | SP.DYN.CDRT.IN |
| **Social** | Poverty rate $1.90/day | `poverty_rate` | SI.POV.DDAY |
| | Gini index | `gini_index` | SI.POV.GINI |
| | Literacy rate | `literacy_rate` | SE.ADT.LITR.ZS |
| | Primary enrollment | `primary_enrollment` | SE.PRM.NENR |
| | Secondary enrollment | `secondary_enrollment` | SE.SEC.NENR |
| | Tertiary enrollment | `tertiary_enrollment` | SE.TER.ENRR |
| **Health** | Infant mortality | `infant_mortality` | SP.DYN.IMRT.IN |
| | Maternal mortality | `maternal_mortality` | SH.STA.MMRT |
| | Health expenditure % GDP | `health_expenditure` | SH.XPD.CHEX.GD.ZS |
| | Hospital beds per 1,000 | `hospital_beds` | SH.MED.BEDS.ZS |
| **Labor** | Unemployment % | `unemployment` | SL.UEM.TOTL.ZS |
| | Labor force total | `labor_force` | SL.TLF.TOTL.IN |
| | Female labor force % | `female_labor_force` | SL.TLF.CACT.FE.ZS |
| **Trade** | Exports | `exports` | NE.EXP.GNFS.CD |
| | Imports | `imports` | NE.IMP.GNFS.CD |
| | Trade % GDP | `trade_gdp` | NE.TRD.GNFS.ZS |
| | FDI inflows | `fdi_inflow` | BX.KLT.DINV.CD.WD |
| | External debt | `external_debt` | DT.DOD.DECT.CD |
| **Environment** | CO2 emissions (kt) | `co2_emissions` | EN.ATM.CO2E.KT |
| | CO2 per capita | `co2_per_capita` | EN.ATM.CO2E.PC |
| | Renewable energy % | `renewable_energy` | EG.FEC.RNEW.ZS |
| | Electricity access % | `electricity_access` | EG.ELC.ACCS.ZS |
| | Forest area % | `forest_area` | AG.LND.FRST.ZS |
| **Technology** | Internet users % | `internet_users` | IT.NET.USER.ZS |
| | Mobile subscriptions | `mobile_subscriptions` | IT.CEL.SETS.P2 |
| | Roads paved % | `roads_paved` | IS.ROD.PAVE.ZP |

---

## API Reference

### Base Class Methods

#### _make_request()
```python
def _make_request(self, endpoint: str, params: Dict = None) -> List:
    """
    Make API request to World Bank
    
    Args:
        endpoint: API endpoint path
        params: Query parameters
    
    Returns:
        [metadata, data_array]
    
    Raises:
        ValueError: If request fails
    """
```

### Tool Instantiation

```python
from world_bank_tool import WORLD_BANK_TOOLS

# Get tool class
ToolClass = WORLD_BANK_TOOLS['wb_get_country_data']

# Create instance
tool = ToolClass(config={
    'name': 'wb_get_country_data',
    'enabled': True
})

# Execute
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp',
    'start_year': 2010,
    'end_year': 2023
})
```

---

## Usage Examples

### Example 1: Get Country List with Filters

```python
from world_bank_tool import WBGetCountriesTool

tool = WBGetCountriesTool({})

# Get all South Asian countries
result = tool.execute({
    'region': 'SAS'
})

print(f"Found {result['total_countries']} countries in South Asia:")
for country in result['countries']:
    print(f"  {country['name']} ({country['id']})")
    print(f"    Capital: {country['capital']}")
    print(f"    Income: {country['income_level']['value']}")
```

### Example 2: Track Country Economic Indicators

```python
from world_bank_tool import WBGetCountryDataTool

tool = WBGetCountryDataTool({})

# Get India's GDP growth 2010-2023
result = tool.execute({
    'country_code': 'IND',
    'indicator': 'gdp_growth',
    'start_year': 2010,
    'end_year': 2023
})

print(f"{result['country']['name']} - {result['indicator']['name']}")
print(f"Data points: {result['data_points']}\n")

for point in result['data']:
    print(f"{point['year']}: {point['value']:.2f}%")
```

### Example 3: Compare Multiple Countries

```python
from world_bank_tool import WBCompareCountriesTool

tool = WBCompareCountriesTool({})

# Compare CO2 per capita in major economies
result = tool.execute({
    'country_codes': ['US', 'CHN', 'IND', 'DEU', 'JPN'],
    'indicator': 'co2_per_capita',
    'start_year': 2010,
    'end_year': 2022
})

print(f"Comparing: {result['indicator']['name']}")
print(f"Period: {result['year_range']['start']}-{result['year_range']['end']}\n")

print("Summary:")
highest = result['summary']['highest_country']
lowest = result['summary']['lowest_country']
print(f"Highest: {highest['id']} - {highest['value']:.2f}")
print(f"Lowest: {lowest['id']} - {lowest['value']:.2f}")
print(f"Average: {result['summary']['average_across_countries']:.2f}\n")

print("By Country:")
for country_data in result['countries']:
    country = country_data['country']
    latest = country_data['latest_value']
    avg = country_data['average']
    print(f"{country['name']}:")
    print(f"  Latest: {latest:.2f} ({country_data['latest_year']})")
    print(f"  Average: {avg:.2f}")
```

### Example 4: Search for Indicators

```python
from world_bank_tool import WBSearchIndicatorsTool

tool = WBSearchIndicatorsTool({})

# Search for education-related indicators
result = tool.execute({
    'search_term': 'school enrollment',
    'per_page': 10
})

print(f"Found {result['total_results']} indicators matching 'school enrollment'\n")

for indicator in result['results']:
    print(f"{indicator['name']}")
    print(f"  Code: {indicator['id']}")
    print(f"  Relevance: {indicator['relevance_score']:.1f}")
    if indicator.get('topics'):
        topics = ', '.join([t['value'] for t in indicator['topics']])
        print(f"  Topics: {topics}")
    print()
```

### Example 5: Get Cross-Country Rankings

```python
from world_bank_tool import WBGetIndicatorDataTool

tool = WBGetIndicatorDataTool({})

# Get GDP per capita for high-income countries in 2023
result = tool.execute({
    'indicator': 'gdp_per_capita',
    'income_level': 'HIC',
    'year': 2023,
    'per_page': 200
})

print(f"{result['indicator']['name']}")
print(f"Income Level: {result['filters_applied']['income_level']}")
print(f"Year: {result['year_filter']}")
print(f"Countries: {result['country_count']}\n")

# Sort by value and show top 10
sorted_data = sorted(result['data'], 
                     key=lambda x: x['value'] if x['value'] else 0, 
                     reverse=True)

print("Top 10 Countries:")
for i, item in enumerate(sorted_data[:10], 1):
    print(f"{i:2d}. {item['country']['name']}: ${item['value']:,.2f}")
```

### Example 6: Topic-Based Analysis

```python
from world_bank_tool import WBGetTopicIndicatorsTool

tool = WBGetTopicIndicatorsTool({})

# Get all climate change indicators
result = tool.execute({
    'topic_id': 19,  # Climate Change
    'per_page': 50
})

print(f"Topic: {result['topic']['name']}")
print(f"Total Indicators: {result['total_indicators']}")
print(f"Showing {len(result['indicators'])} indicators\n")

# Group by source organization
from collections import defaultdict
by_org = defaultdict(list)

for ind in result['indicators']:
    org = ind.get('source_organization', 'Unknown')
    by_org[org].append(ind['name'])

print("Indicators by Source Organization:")
for org, indicators in sorted(by_org.items()):
    print(f"\n{org} ({len(indicators)} indicators):")
    for name in indicators[:3]:  # Show first 3
        print(f"  • {name}")
    if len(indicators) > 3:
        print(f"  ... and {len(indicators) - 3} more")
```

---

## Schema Specifications

### Common Response Fields

**Success Response:**
```json
{
  "// tool-specific data fields": "...",
  "last_updated": "2025-10-31T12:00:00Z"
}
```

**Error Response:**
```python
# Raises ValueError with descriptive message
raise ValueError("World Bank API request failed: HTTP 404")
raise ValueError("Unknown indicator: xyz")
```

### Country Codes

**ISO2 Format:**
- US, CN, IN, GB, FR, DE, JP, BR, RU, CA, etc.

**ISO3 Format:**
- USA, CHN, IND, GBR, FRA, DEU, JPN, BRA, RUS, CAN, etc.

**Both formats accepted** in country_code parameters

### Year Ranges

- **Minimum**: 1960
- **Maximum**: 2030
- **Format**: Integer (YYYY)
- **Range notation**: "2010:2023"

### Data Standards

| Field | Type | Format | Example |
|-------|------|--------|---------|
| year | integer | YYYY | 2023 |
| value | float/null | numeric | 76398.59 |
| country code | string | ISO2/ISO3 | "US" or "USA" |
| indicator code | string | WB code | "NY.GDP.MKTP.CD" |
| timestamp | string | ISO 8601 | "2025-10-31T12:00:00Z" |

---

## Limitations

### API Limitations

1. **Data Availability**
   - Not all indicators available for all countries
   - Typical data lag: 1-2 years
   - Some indicators less frequent (biennial, quinquennial)
   - Historical data varies by indicator

2. **Data Quality**
   - Quality varies by country
   - Methodologies may change over time
   - Revisions to historical data
   - Gaps in time series common

3. **Response Times**
   - Typical: 1-3 seconds
   - Large queries: up to 10 seconds
   - Network latency varies
   - 15 second timeout

### Rate Limiting

1. **No Official Limits**
   - World Bank API has no published rate limits
   - Reasonable use policy applies
   - Recommended: < 120 requests/minute

2. **Best Practices**
   - Cache results when possible
   - Use pagination efficiently
   - Batch requests when appropriate
   - Implement client-side throttling

### Data Coverage

1. **Geographic**
   - 200+ countries and territories
   - Regional aggregates available
   - Income group aggregates
   - World totals

2. **Temporal**
   - Most data: 1960-present
   - Some indicators: limited historical data
   - Annual frequency typical
   - Quarterly for some economic indicators

3. **Indicator**
   - 16,000+ indicators total
   - Core indicators: 1,500+
   - Coverage varies by topic
   - Some indicators discontinued

### Technical Limitations

1. **No Real-Time Data**
   - No live/streaming data
   - Batch updates (quarterly/annually)
   - No WebSocket support

2. **Pagination**
   - Max per_page: 1000 for data, 500 for metadata
   - Must paginate for large datasets
   - No bulk download via API

3. **Filtering**
   - Limited to predefined filters
   - No complex queries
   - No custom aggregations

---

## Troubleshooting

### Common Issues

#### Issue 1: No Data Returned

**Symptoms:** Empty data array

**Causes:**
- Indicator not available for country
- No data for specified time period
- Country code incorrect
- Indicator code invalid

**Solutions:**
```python
result = tool.execute({
    'country_code': 'IND',
    'indicator': 'gdp',
    'start_year': 2010
})

if result['data_points'] == 0:
    print("No data available. Try:")
    print("1. Different time period")
    print("2. Check indicator code")
    print("3. Verify country code")
```

#### Issue 2: HTTP Errors

**Error:** `ValueError: World Bank API request failed: HTTP 404`

**Causes:**
- Invalid endpoint
- Wrong country code
- Invalid indicator code

**Solutions:**
```python
try:
    result = tool.execute({
        'country_code': 'XYZ',  # Invalid
        'indicator': 'gdp'
    })
except ValueError as e:
    print(f"API Error: {e}")
    # Use wb_get_countries to find valid codes
    # Use wb_search_indicators to find valid indicators
```

#### Issue 3: Timeout Errors

**Error:** Request timeout after 15 seconds

**Causes:**
- Large date range
- Slow network
- World Bank server load

**Solutions:**
```python
# Reduce date range
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp',
    'start_year': 2020,  # Smaller range
    'end_year': 2023
})

# Use pagination for large queries
result = tool.execute({
    'indicator': 'population',
    'year': 2023,
    'per_page': 50  # Smaller page size
})
```

#### Issue 4: Invalid Country Code

**Symptoms:** No results or 404 error

**Cause:** Using wrong ISO format

**Solution:**
```python
# Wrong: 'UK', 'Germany', 'China'
# Correct: Use ISO2 or ISO3

# Check valid codes
countries_tool = WBGetCountriesTool({})
countries = countries_tool.execute({})

# Find your country
for c in countries['countries']:
    if 'united kingdom' in c['name'].lower():
        print(f"Use: {c['id']} or {c['iso3']}")
```

#### Issue 5: Unknown Indicator

**Error:** `ValueError: Unknown indicator: xyz`

**Solutions:**
```python
# Option 1: Use search
search_tool = WBSearchIndicatorsTool({})
results = search_tool.execute({
    'search_term': 'unemployment'
})

# Option 2: Browse by topic
topic_tool = WBGetTopicIndicatorsTool({})
results = topic_tool.execute({
    'topic_id': 10  # Social Protection & Labor
})

# Option 3: Use direct indicator code
result = tool.execute({
    'country_code': 'US',
    'indicator_code': 'SL.UEM.TOTL.ZS'  # Direct code
})
```

### Debug Mode

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Tool will now log all API calls
tool = WBGetCountryDataTool({})
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp'
})
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
│            World Bank MCP Tools (10 Tools)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         Metadata Tools (5)                           │   │
│  │  • wb_get_countries     • wb_get_income_levels       │   │
│  │  • wb_get_indicators    • wb_get_lending_types       │   │
│  │  • wb_get_regions                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         Data Query Tools (5)                         │   │
│  │  • wb_get_country_data   • wb_compare_countries      │   │
│  │  • wb_get_indicator_data • wb_search_indicators      │   │
│  │  • wb_get_topic_indicators                           │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTPS API Calls
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                World Bank Open Data API v2                   │
│                  api.worldbank.org/v2                        │
│  ┌────────────────────────┐  ┌────────────────────────┐     │
│  │  Metadata Endpoints    │  │  Data Endpoints        │     │
│  │  • /country            │  │  • /country/{id}/      │     │
│  │  • /indicator          │  │    indicator/{code}    │     │
│  │  • /incomelevel        │  │  • /countries/all/     │     │
│  │  • /lendingtype        │  │    indicators/{code}   │     │
│  │  • /region             │  │                        │     │
│  │  • /topic              │  │                        │     │
│  └────────────────────────┘  └────────────────────────┘     │
│                                                              │
│  • No Authentication Required                                │
│  • Public Access                                             │
│  • JSON Format                                               │
│  • 16,000+ Indicators                                        │
│  • 200+ Countries                                            │
│  • 1960-Present Data                                         │
└──────────────────────────────────────────────────────────────┘
```

### Request Flow

```
User Application
     │
     ├─→ [1] Select World Bank Tool
     │        │
     │        └─→ [2] Provide Parameters
     │                 │
     │                 └─→ [3] Tool Validates Input
     │                          │
     │                          └─→ [4] Map Indicator Shorthand
     │                                   │
     │                                   └─→ [5] Build API URL
     │                                            │
     │                                            └─→ [6] Make HTTPS Request
     │                                                     │
     │                                                     └─→ api.worldbank.org
     │                                                              │
     │                                                              ▼
     │                                                       [7] WB Server
     │                                                          Processes
     │                                                              │
     │                                                              ▼
     │                                                       [8] Return JSON
     │                                                          [metadata, data]
     │                                                              │
     │                                                              ▼
     │                                                       [9] Parse Response
     │                                                              │
     │                                                              ▼
     │                                                       [10] Format Data
     │                                                              │
     └──────────────────────────────────────────────────────────────┴─→ JSON Response
```

### Data Flow Architecture

```
┌──────────────────┐
│   User Query     │
│  Country + Year  │
│   + Indicator    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Tool Layer     │
│  - Validation    │
│  - Mapping       │
│  - URL Building  │
└────────┬─────────┘
         │
         ▼ API Request
┌──────────────────┐
│  HTTP Transport  │
│  urllib.request  │
│  Timeout: 15s    │
└────────┬─────────┘
         │
         ▼ HTTPS GET
┌──────────────────┐
│ World Bank API   │
│  • Countries DB  │
│  • Indicators DB │
│  • Time Series   │
└────────┬─────────┘
         │
         ▼ JSON Response
         │ [metadata, data]
┌──────────────────┐
│  Response Parser │
│  - Extract data  │
│  - Format values │
│  - Add metadata  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Formatted Data  │
│  - Country info  │
│  - Indicator info│
│  - Time series   │
│  - Statistics    │
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
        'country_code': 'IND',
        'indicator': 'gdp',
        'start_year': 2010,
        'end_year': 2023
    })
    
    if result['data_points'] == 0:
        print("No data available for this period")
    else:
        # Process data
        for point in result['data']:
            print(f"{point['year']}: {point['value']}")
            
except ValueError as e:
    print(f"API Error: {e}")
    # Handle appropriately
```

### 2. Use Indicator Shortcuts

```python
# ✓ Good: Use convenient shortcuts
result = tool.execute({
    'country_code': 'US',
    'indicator': 'gdp_per_capita',  # Easy to remember
    'start_year': 2010,
    'end_year': 2023
})

# ✗ Harder: Remember cryptic codes
result = tool.execute({
    'country_code': 'US',
    'indicator_code': 'NY.GDP.PCAP.CD',  # Have to look up
    'start_year': 2010,
    'end_year': 2023
})
```

### 3. Cache Metadata

```python
# ✓ Good: Cache countries, regions, income levels
from functools import lru_cache

@lru_cache(maxsize=128)
def get_countries_cached():
    tool = WBGetCountriesTool({})
    return tool.execute({})

# Metadata doesn't change frequently
countries = get_countries_cached()
```

### 4. Efficient Pagination

```python
# ✓ Good: Request only what you need
result = tool.execute({
    'indicator': 'gdp_per_capita',
    'year': 2023,
    'per_page': 50  # Reasonable size
})

# ✗ Inefficient: Always max
result = tool.execute({
    'indicator': 'gdp_per_capita',
    'year': 2023,
    'per_page': 1000  # May be slow
})
```

### 5. Use Filters

```python
# ✓ Good: Filter at API level
result = tool.execute({
    'indicator': 'life_expectancy',
    'income_level': 'HIC',  # Filter high-income
    'year': 2023
})

# ✗ Inefficient: Get all, filter client-side
result = tool.execute({
    'indicator': 'life_expectancy',
    'year': 2023
})
# Then filter in Python...
```

---

## Performance Considerations

### Optimization Tips

1. **Use Appropriate Date Ranges**
   ```python
   # Good: Specific range
   result = tool.execute({
       'country_code': 'US',
       'indicator': 'gdp',
       'start_year': 2015,  # Only recent data
       'end_year': 2023
   })
   ```

2. **Leverage Comparison Tool**
   ```python
   # Good: Single call for multiple countries
   result = tool.execute({
       'country_codes': ['US', 'CHN', 'IND'],
       'indicator': 'gdp',
       'start_year': 2020,
       'end_year': 2023
   })
   
   # Avoid: Multiple separate calls
   ```

3. **Search Before Browsing**
   ```python
   # Good: Targeted search
   search_result = search_tool.execute({
       'search_term': 'renewable energy',
       'topic_id': 5
   })
   
   # Avoid: Browsing all 16,000+ indicators
   ```

### Performance Metrics

| Operation | Typical Time | Factors |
|-----------|-------------|---------|
| Get Countries | 0.5-2s | Network, filters |
| Get Indicators (page) | 1-3s | Page size, topic filter |
| Get Country Data | 1-5s | Date range, indicator |
| Get Indicator Data | 2-8s | Year range, filters |
| Compare Countries | 3-10s | Number of countries, range |
| Search Indicators | 2-6s | Search term, topic |

---

## Metadata

### Tool Registry

```python
WORLD_BANK_TOOLS = {
    'wb_get_countries': WBGetCountriesTool,
    'wb_get_indicators': WBGetIndicatorsTool,
    'wb_get_country_data': WBGetCountryDataTool,
    'wb_get_indicator_data': WBGetIndicatorDataTool,
    'wb_search_indicators': WBSearchIndicatorsTool,
    'wb_compare_countries': WBCompareCountriesTool,
    'wb_get_income_levels': WBGetIncomeLevelsTool,
    'wb_get_lending_types': WBGetLendingTypesTool,
    'wb_get_regions': WBGetRegionsTool,
    'wb_get_topic_indicators': WBGetTopicIndicatorsTool
}
```

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-10-31 | Initial release |

### Rate Limits (Recommended)

| Tool Category | Requests/Min | Cache TTL |
|---------------|--------------|-----------|
| Metadata Tools | 120 | 86400s (24h) |
| Data Tools | 120 | 3600s (1h) |

---

## Support & Resources

### Documentation
- **World Bank Open Data:** https://data.worldbank.org
- **API Documentation:** https://datahelpdesk.worldbank.org/knowledgebase/topics/125589
- **Indicator Catalog:** https://data.worldbank.org/indicator
- **Country Profiles:** https://data.worldbank.org/country

### Contact Information
- **Author:** Ashutosh Sinha
- **Email:** ajsinha@gmail.com

### External Resources
- **World Bank Data Blog:** https://blogs.worldbank.org/opendata
- **Data Help Desk:** https://datahelpdesk.worldbank.org
- **API Query Builder:** https://datahelpdesk.worldbank.org/knowledgebase/articles/898599

---

## Legal

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**

This software and documentation are proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.

**Email:** ajsinha@gmail.com

### Third-Party Services

This tool uses World Bank Open Data API:
- **Service Provider:** The World Bank Group
- **Data Source:** World Bank Open Data
- **API Version:** v2
- **Terms:** https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets
- **License:** Creative Commons Attribution 4.0 (CC BY 4.0)

### Data Usage

- All data sourced from World Bank Open Data
- Data subject to World Bank terms and conditions
- Attribution required for publications: "Data from World Bank Open Data"
- Free to use for commercial and non-commercial purposes
- Review World Bank data policies for specific requirements

---

*End of Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **World Bank**: An international financial institution providing loans and grants for development. SAJHA provides World Bank data tools.

- **World Development Indicators (WDI)**: The World Bank's primary database of development indicators covering economics, health, education, and more.

- **Country Code**: ISO standard codes identifying countries (e.g., USA, CHN, IND). Required for World Bank API queries.

- **Indicator Code**: Unique identifiers for specific data series (e.g., NY.GDP.MKTP.CD for GDP).

- **Time Series**: Sequential data points indexed by time. World Bank provides annual time series for most indicators.

- **GDP (Gross Domestic Product)**: Total value of goods and services produced by a country. A key indicator in World Bank data.

- **Poverty Rate**: Percentage of population living below the poverty line. Available at various thresholds ($1.90, $3.20, $5.50/day).

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
