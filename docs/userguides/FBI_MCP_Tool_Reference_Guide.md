# FBI Crime Data Explorer MCP Tool Reference Guide

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
6. [Offense Types](#offense-types)
7. [Usage Examples](#usage-examples)
8. [Schema Reference](#schema-reference)
9. [ORI Codes](#ori-codes)
10. [Limitations](#limitations)
11. [Error Handling](#error-handling)
12. [Performance Considerations](#performance-considerations)

---

## Overview

The FBI Crime Data Explorer MCP Tool Suite is a comprehensive collection of 9 specialized tools designed to access crime statistics from the FBI's Uniform Crime Reporting (UCR) program. These tools provide programmatic access to national, state, and agency-level crime data spanning decades of historical information.

### Key Features

- **Comprehensive Coverage**: Access national, state, and agency-level crime statistics
- **Historical Analysis**: Analyze crime trends from 1960 to present
- **Multiple Offense Types**: Track 10 major crime categories
- **Comparative Analysis**: Compare crime rates across states and agencies
- **Agency Discovery**: Search for law enforcement agencies by name or location
- **Participation Tracking**: Monitor data quality and reporting coverage

### Supported Crime Categories

- Violent Crime (aggregate)
- Homicide/Murder
- Rape/Sexual Assault
- Robbery
- Aggravated Assault
- Property Crime (aggregate)
- Burglary
- Larceny-Theft
- Motor Vehicle Theft
- Arson

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
│              MCP Tool Layer (9 Tools)                    │
├──────────────────────────────────────────────────────────┤
│  • fbi_get_national_statistics                           │
│  • fbi_get_state_statistics                              │
│  • fbi_get_agency_statistics                             │
│  • fbi_search_agencies                                   │
│  • fbi_get_agency_details                                │
│  • fbi_get_offense_data                                  │
│  • fbi_get_participation_rate                            │
│  • fbi_get_crime_trend                                   │
│  • fbi_compare_states                                    │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│          FBIBaseTool (Shared Functionality)              │
├──────────────────────────────────────────────────────────┤
│  • API URL: api.usa.gov/crime/fbi/cde                   │
│  • Offense Code Mapping (10 types)                       │
│  • State Name Mapping (51 states/territories)            │
│  • HTTP Client (urllib)                                  │
│  • JSON Parser                                           │
│  • Per Capita Calculator                                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│         FBI Crime Data Explorer API                      │
│         https://api.usa.gov/crime/fbi/cde                │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── FBIBaseTool
            │
            ├── FBIGetNationalStatisticsTool
            ├── FBIGetStateStatisticsTool
            ├── FBIGetAgencyStatisticsTool
            ├── FBISearchAgenciesTool
            ├── FBIGetAgencyDetailsTool
            ├── FBIGetOffenseDataTool
            ├── FBIGetParticipationRateTool
            ├── FBIGetCrimeTrendTool
            └── FBICompareStatesTool
```

### Component Descriptions

#### FBIBaseTool
Base class providing:
- API endpoint configuration (`https://api.usa.gov/crime/fbi/cde`)
- Offense type to API code mapping
- State abbreviation to full name mapping (51 entries)
- Shared HTTP request handling via `_make_api_request()` method
- Per capita rate calculation (per 100,000 population)
- JSON response parsing
- Error handling and logging

#### Individual Tool Classes
Each tool specializes in a specific data retrieval pattern:
- Custom input/output schemas
- Domain-specific validation (ORI codes, state abbreviations)
- Specialized query parameter handling
- Tailored response formatting with comparative analysis

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

The tools communicate with the FBI Crime Data Explorer API using standard REST API calls:

```python
# Base URL
https://api.usa.gov/crime/fbi/cde

# Request Formats
GET /statistics/national/{offense_code}?year={year}
GET /statistics/state/{state}/{offense_code}?year={year}
GET /statistics/agency/{ori}/{offense_code}?year={year}
GET /agencies/search?name={agency_name}&state={state}

# Example
GET /statistics/national/violent-crime?year=2022
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
- `year`: Year for statistics (1960-2024)
- `state`: State abbreviation (e.g., CA, NY, TX)
- `ori`: Originating Agency Identifier code
- Various filtering parameters per tool

**Timeout**: 30 seconds per request

### Response Parsing

The FBI API returns data in JSON format:

```json
{
  "total_incidents": 1234567,
  "population": 331000000,
  "rate_per_100k": 373.0,
  "reporting_agencies": 15764,
  "population_covered": 325000000
}
```

The tools parse this structure and enrich it with:
- Per capita calculations
- Comparative analysis (state vs national)
- Rankings and percentiles
- Trend analysis

---

## Authentication & API Keys

### No API Key Required

The FBI Crime Data Explorer API accessed through `api.usa.gov` is a **public API** that does **not require**:
- API Keys
- OAuth tokens
- Username/Password
- Registration
- Rate limit authentication

### Access Control

- **Open Access**: Anyone can access the API
- **Fair Use**: Users should implement reasonable caching
- **Rate Limiting**: May be enforced at the API gateway level (not documented)

### Recommended Rate Limit

The tools implement a suggested rate limit of **120 requests per hour** per tool, though this is not strictly enforced by the API.

### Cache Strategy

- **cacheTTL**: 3600 seconds (1 hour) for statistical data
- Crime statistics are typically updated annually, so longer caching is appropriate

---

## Tool Descriptions

### 1. fbi_get_national_statistics

**Purpose**: Retrieve nationwide US crime statistics

**Use Cases**:
- National crime trend monitoring
- Baseline comparisons
- Annual crime reports
- Policy analysis

**Input Parameters**:
```json
{
  "offense_type": "violent_crime",  // Required
  "year": 2022,                     // Optional (defaults to most recent)
  "per_capita": false               // Optional (default: false)
}
```

**Output**:
```json
{
  "offense_type": "violent_crime",
  "year": 2022,
  "national_data": {
    "total_incidents": 1234567,
    "rate_per_100k": 373.0,
    "population": 331000000,
    "reporting_agencies": 15764,
    "population_covered": 325000000
  },
  "metadata": {
    "data_source": "FBI UCR",
    "last_updated": "2024-10-31T14:30:00.000Z"
  }
}
```

---

### 2. fbi_get_state_statistics

**Purpose**: Retrieve crime statistics for a specific US state

**Supported States**: All 50 states plus DC (51 total)

**Input Parameters**:
```json
{
  "state": "CA",                    // Required (2-letter code)
  "offense_type": "violent_crime",  // Required
  "year": 2022,                     // Optional
  "per_capita": false               // Optional
}
```

**Output**:
```json
{
  "state": "CA",
  "state_name": "California",
  "offense_type": "violent_crime",
  "year": 2022,
  "state_data": {
    "total_incidents": 123456,
    "rate_per_100k": 312.5,
    "state_population": 39500000,
    "reporting_agencies": 723,
    "national_rank": 15
  },
  "comparison": {
    "national_rate": 373.0,
    "percent_of_national": 83.8
  }
}
```

**Use Cases**:
- State-specific crime analysis
- State vs national comparisons
- Regional policy evaluation
- Resource allocation planning

---

### 3. fbi_get_agency_statistics

**Purpose**: Retrieve crime statistics for a specific law enforcement agency

**Agency Identification**: Uses ORI (Originating Agency Identifier) codes

**Input Parameters**:
```json
{
  "ori": "CA0190000",               // Required (9-char code)
  "offense_type": "violent_crime",  // Required
  "year": 2022,                     // Optional
  "per_capita": false               // Optional
}
```

**Output**:
```json
{
  "ori": "CA0190000",
  "agency_name": "Los Angeles Police Department",
  "agency_type": "city",
  "state": "CA",
  "offense_type": "violent_crime",
  "year": 2022,
  "agency_data": {
    "total_incidents": 12345,
    "rate_per_100k": 308.6,
    "jurisdiction_population": 4000000,
    "months_reported": 12
  },
  "comparison": {
    "state_rate": 312.5,
    "national_rate": 373.0
  }
}
```

**Common ORI Codes**:
- `CA0190000` - Los Angeles Police Department (LAPD)
- `NY0300000` - New York City Police Department (NYPD)
- `IL0160000` - Chicago Police Department
- `TX2210000` - Houston Police Department
- `AZ0070000` - Phoenix Police Department

**Use Cases**:
- Agency-specific crime tracking
- Local law enforcement analysis
- Jurisdiction comparisons
- Performance monitoring

---

### 4. fbi_search_agencies

**Purpose**: Search for law enforcement agencies to find their ORI codes

**Input Parameters**:
```json
{
  "agency_name": "police",          // Required (min 3 chars)
  "state": "CA",                    // Optional filter
  "agency_type": "city",            // Optional filter
  "limit": 20                       // Optional (default: 20, max: 100)
}
```

**Agency Types**:
- `city` - City/municipal police departments
- `county` - County sheriff departments
- `state` - State police/highway patrol
- `federal` - Federal law enforcement
- `tribal` - Tribal police
- `university` - Campus police
- `all` - All types

**Output**:
```json
{
  "search_query": "police",
  "total_results": 723,
  "agencies": [
    {
      "ori": "CA0190000",
      "agency_name": "Los Angeles Police Department",
      "agency_type": "city",
      "state": "CA",
      "state_name": "California",
      "city": "Los Angeles",
      "county": "Los Angeles",
      "population": 4000000
    }
  ]
}
```

**Use Cases**:
- ORI code discovery
- Agency directory browsing
- Multi-agency analysis setup
- Jurisdictional research

---

### 5. fbi_get_agency_details

**Purpose**: Retrieve detailed information about a specific law enforcement agency

**Input Parameters**:
```json
{
  "ori": "CA0190000"                // Required
}
```

**Output**:
```json
{
  "ori": "CA0190000",
  "agency_name": "Los Angeles Police Department",
  "agency_type": "city",
  "location": {
    "state": "CA",
    "state_name": "California",
    "city": "Los Angeles",
    "county": "Los Angeles",
    "region": "West"
  },
  "jurisdiction": {
    "population": 4000000,
    "square_miles": 469.0
  },
  "personnel": {
    "total_officers": 9974,
    "total_civilians": 2820,
    "officers_per_1000": 2.49
  },
  "reporting_status": {
    "participates_in_ucr": true,
    "participates_in_nibrs": true,
    "last_reported_year": 2022
  }
}
```

**Use Cases**:
- Agency capability assessment
- Resource analysis
- Reporting compliance tracking
- Jurisdictional profiling

---

### 6. fbi_get_offense_data

**Purpose**: Retrieve detailed offense breakdown and subcategories

**Input Parameters**:
```json
{
  "offense_type": "violent_crime",  // Required
  "state": "CA",                    // Optional
  "year": 2022,                     // Optional
  "include_subcategories": true     // Optional (default: true)
}
```

**Output**:
```json
{
  "offense_type": "violent_crime",
  "year": 2022,
  "scope": "national",
  "total_offenses": 1234567,
  "subcategories": [
    {
      "subcategory": "aggravated_assault",
      "total_incidents": 765432,
      "percentage_of_total": 62.0
    },
    {
      "subcategory": "robbery",
      "total_incidents": 234567,
      "percentage_of_total": 19.0
    }
  ],
  "demographics": {
    "by_location_type": {
      "residential": 45.2,
      "commercial": 32.1,
      "public": 22.7
    },
    "by_weapon": {
      "firearm": 38.5,
      "knife": 12.3,
      "other": 49.2
    },
    "clearance_rate": 45.5
  }
}
```

**Use Cases**:
- Detailed crime composition analysis
- Subcategory trend tracking
- Weapon/location pattern analysis
- Clearance rate monitoring

---

### 7. fbi_get_participation_rate

**Purpose**: Monitor agency participation and data quality

**Input Parameters**:
```json
{
  "state": "CA",                    // Optional
  "year": 2022                      // Optional
}
```

**Output**:
```json
{
  "scope": "state",
  "state": "CA",
  "year": 2022,
  "participation_data": {
    "total_agencies": 723,
    "reporting_agencies": 698,
    "participation_rate": 96.5,
    "population_covered": 38500000,
    "total_population": 39500000,
    "population_coverage_rate": 97.5
  },
  "reporting_quality": {
    "full_year_reporters": 690,
    "partial_year_reporters": 8,
    "zero_reporters": 25
  }
}
```

**Use Cases**:
- Data quality assessment
- Coverage gap identification
- Reporting compliance monitoring
- Data reliability evaluation

---

### 8. fbi_get_crime_trend

**Purpose**: Analyze crime trends over time with statistical analysis

**Input Parameters**:
```json
{
  "offense_type": "violent_crime",  // Required
  "start_year": 2010,               // Required
  "end_year": 2022,                 // Required
  "state": "CA",                    // Optional (for state-level)
  "ori": "CA0190000",               // Optional (for agency-level)
  "per_capita": true                // Optional (default: true)
}
```

**Output**:
```json
{
  "offense_type": "violent_crime",
  "scope": "national",
  "time_period": {
    "start_year": 2010,
    "end_year": 2022,
    "years_analyzed": 13
  },
  "time_series": [
    {
      "year": 2010,
      "total_incidents": 1246248,
      "rate_per_100k": 404.5,
      "percent_change": 0
    },
    {
      "year": 2011,
      "total_incidents": 1203564,
      "rate_per_100k": 386.3,
      "percent_change": -4.5
    }
  ],
  "trend_analysis": {
    "overall_change": -15.2,
    "average_annual_change": -1.2,
    "direction": "decreasing",
    "peak_year": 2016,
    "lowest_year": 2014,
    "volatility": "low"
  }
}
```

**Trend Direction**:
- `increasing`: Overall change > +5%
- `decreasing`: Overall change < -5%
- `stable`: Overall change between -5% and +5%

**Volatility Levels**:
- `high`: Average annual change > 10%
- `medium`: Average annual change > 5%
- `low`: Average annual change ≤ 5%

**Use Cases**:
- Historical trend analysis
- Pattern recognition
- Policy impact assessment
- Forecasting and prediction

---

### 9. fbi_compare_states

**Purpose**: Compare crime statistics across multiple states

**Input Parameters**:
```json
{
  "states": ["CA", "TX", "FL", "NY"],  // Required (2-10 states)
  "offense_type": "violent_crime",     // Required
  "year": 2022,                        // Optional
  "per_capita": true,                  // Optional (default: true)
  "include_national_average": true     // Optional (default: true)
}
```

**Output**:
```json
{
  "offense_type": "violent_crime",
  "year": 2022,
  "comparison_type": "per_capita",
  "states_compared": [
    {
      "state": "CA",
      "state_name": "California",
      "total_incidents": 123456,
      "rate_per_100k": 312.5,
      "state_population": 39500000,
      "rank": 3,
      "percent_of_national": 83.8
    }
  ],
  "national_reference": {
    "total_incidents": 1234567,
    "rate_per_100k": 373.0
  },
  "comparison_summary": {
    "highest_state": "FL",
    "lowest_state": "NY",
    "range": 125.3,
    "average_of_compared": 340.2
  }
}
```

**Use Cases**:
- Multi-state comparisons
- Regional analysis
- Best/worst practice identification
- Policy benchmarking

---

## Offense Types

### Complete Offense Type Reference

| Offense Type | API Code | Description | UCR Category |
|--------------|----------|-------------|--------------|
| **violent_crime** | violent-crime | Aggregate of all violent crimes | Part I |
| **homicide** | homicide | Murder and non-negligent manslaughter | Part I |
| **rape** | rape | Rape (revised definition) | Part I |
| **robbery** | robbery | Taking property by force or threat | Part I |
| **aggravated_assault** | aggravated-assault | Attack with weapon or serious injury | Part I |
| **property_crime** | property-crime | Aggregate of all property crimes | Part I |
| **burglary** | burglary | Unlawful entry to commit theft/felony | Part I |
| **larceny** | larceny | Theft (excluding motor vehicles) | Part I |
| **motor_vehicle_theft** | motor-vehicle-theft | Theft of motor vehicles | Part I |
| **arson** | arson | Willful burning of property | Part I |

### Offense Categories

**Violent Crimes** (crimes against persons):
- Homicide
- Rape
- Robbery
- Aggravated Assault

**Property Crimes** (crimes against property):
- Burglary
- Larceny-Theft
- Motor Vehicle Theft
- Arson

### UCR Part I vs Part II

The tools focus on **Part I (Index) Crimes**, which are:
- More serious offenses
- More reliably reported
- Used for national crime statistics
- Tracked consistently across jurisdictions

---

## Usage Examples

### Example 1: Get National Crime Statistics

```python
from tools.impl.fbi_tool_refactored import FBIGetNationalStatisticsTool

tool = FBIGetNationalStatisticsTool()
result = tool.execute({
    "offense_type": "violent_crime",
    "year": 2022,
    "per_capita": True
})

print(f"National violent crime rate: {result['national_data']['rate_per_100k']} per 100,000")
print(f"Total incidents: {result['national_data']['total_incidents']:,}")
```

### Example 2: Compare Crime Across States

```python
from tools.impl.fbi_tool_refactored import FBICompareStatesTool

tool = FBICompareStatesTool()
result = tool.execute({
    "states": ["CA", "TX", "FL", "NY"],
    "offense_type": "homicide",
    "year": 2022,
    "per_capita": True
})

print("State Rankings (Homicide Rate per 100,000):")
for state in result['states_compared']:
    print(f"{state['rank']}. {state['state_name']}: {state['rate_per_100k']}")
```

### Example 3: Analyze Crime Trends

```python
from tools.impl.fbi_tool_refactored import FBIGetCrimeTrendTool
import matplotlib.pyplot as plt

tool = FBIGetCrimeTrendTool()
result = tool.execute({
    "offense_type": "violent_crime",
    "start_year": 2010,
    "end_year": 2022,
    "per_capita": True
})

# Extract data for plotting
years = [item['year'] for item in result['time_series']]
rates = [item['rate_per_100k'] for item in result['time_series']]

# Create visualization
plt.figure(figsize=(12, 6))
plt.plot(years, rates, marker='o')
plt.title('US Violent Crime Rate Trend (2010-2022)')
plt.xlabel('Year')
plt.ylabel('Rate per 100,000')
plt.grid(True)
plt.show()

# Print analysis
print(f"Overall change: {result['trend_analysis']['overall_change']}%")
print(f"Direction: {result['trend_analysis']['direction']}")
print(f"Peak year: {result['trend_analysis']['peak_year']}")
```

### Example 4: Find and Analyze Agency

```python
from tools.impl.fbi_tool_refactored import (
    FBISearchAgenciesTool,
    FBIGetAgencyStatisticsTool
)

# Step 1: Search for agency
search_tool = FBISearchAgenciesTool()
search_result = search_tool.execute({
    "agency_name": "Los Angeles",
    "state": "CA",
    "limit": 5
})

print(f"Found {search_result['total_results']} agencies")
lapd = search_result['agencies'][0]
print(f"ORI: {lapd['ori']} - {lapd['agency_name']}")

# Step 2: Get statistics
stats_tool = FBIGetAgencyStatisticsTool()
stats_result = stats_tool.execute({
    "ori": lapd['ori'],
    "offense_type": "robbery",
    "year": 2022
})

print(f"\n{lapd['agency_name']} Robbery Statistics:")
print(f"Total incidents: {stats_result['agency_data']['total_incidents']}")
print(f"Rate: {stats_result['agency_data']['rate_per_100k']} per 100,000")
```

### Example 5: State Crime Profile

```python
from tools.impl.fbi_tool_refactored import FBIGetStateStatisticsTool

tool = FBIGetStateStatisticsTool()

state = "CA"
offenses = [
    "violent_crime", "homicide", "robbery", 
    "aggravated_assault", "property_crime"
]

print(f"California Crime Profile (2022)")
print("=" * 60)

for offense in offenses:
    result = tool.execute({
        "state": state,
        "offense_type": offense,
        "year": 2022,
        "per_capita": True
    })
    
    print(f"\n{offense.replace('_', ' ').title()}:")
    print(f"  Rate: {result['state_data']['rate_per_100k']} per 100,000")
    print(f"  National Rank: #{result['state_data']['national_rank']}")
    print(f"  vs National: {result['comparison']['percent_of_national']}%")
```

### Example 6: Check Data Quality

```python
from tools.impl.fbi_tool_refactored import FBIGetParticipationRateTool

tool = FBIGetParticipationRateTool()
result = tool.execute({
    "state": "CA",
    "year": 2022
})

print("California Crime Data Quality Assessment")
print(f"Participation Rate: {result['participation_data']['participation_rate']}%")
print(f"Reporting Agencies: {result['participation_data']['reporting_agencies']}")
print(f"Population Coverage: {result['participation_data']['population_coverage_rate']}%")

quality = result['reporting_quality']
print(f"\nReporting Quality:")
print(f"  Full Year: {quality['full_year_reporters']} agencies")
print(f"  Partial Year: {quality['partial_year_reporters']} agencies")
print(f"  Zero Reports: {quality['zero_reporters']} agencies")
```

---

## Schema Reference

### Common Input Schema Elements

#### State Parameter
```json
{
  "state": {
    "type": "string",
    "pattern": "^[A-Z]{2}$",
    "description": "US State abbreviation (e.g., CA, NY, TX)"
  }
}
```

#### Offense Type
```json
{
  "offense_type": {
    "type": "string",
    "enum": [
      "violent_crime", "homicide", "rape", "robbery",
      "aggravated_assault", "property_crime", "burglary",
      "larceny", "motor_vehicle_theft", "arson"
    ]
  }
}
```

#### Year Parameter
```json
{
  "year": {
    "type": "integer",
    "minimum": 1960,
    "maximum": 2024,
    "description": "Year for crime statistics"
  }
}
```

#### ORI Code
```json
{
  "ori": {
    "type": "string",
    "pattern": "^[A-Z]{2}[0-9]{7}$",
    "description": "Originating Agency Identifier (9 characters)"
  }
}
```

### Common Output Schema Elements

#### Statistics Data
```json
{
  "total_incidents": {
    "type": "integer",
    "description": "Total number of reported incidents"
  },
  "rate_per_100k": {
    "type": "number",
    "description": "Crime rate per 100,000 population"
  },
  "population": {
    "type": "integer",
    "description": "Population base for calculations"
  }
}
```

#### Comparison Data
```json
{
  "comparison": {
    "type": "object",
    "properties": {
      "national_rate": {
        "type": "number"
      },
      "state_rate": {
        "type": "number"
      },
      "percent_of_national": {
        "type": "number"
      }
    }
  }
}
```

---

## ORI Codes

### What is an ORI Code?

An **Originating Agency Identifier (ORI)** is a unique 9-character code assigned by the FBI to each law enforcement agency in the United States.

**Format**: `SSXXXXXXX`
- First 2 characters: State abbreviation (e.g., CA, NY)
- Next 7 characters: Unique agency number

### Major Agency ORI Codes

#### Top 10 Largest Police Departments

| Agency | City | State | ORI Code | Population Served |
|--------|------|-------|----------|-------------------|
| NYPD | New York City | NY | NY0300000 | ~8.3M |
| Chicago PD | Chicago | IL | IL0160000 | ~2.7M |
| LAPD | Los Angeles | CA | CA0190000 | ~4.0M |
| Philadelphia PD | Philadelphia | PA | PA1820000 | ~1.6M |
| Houston PD | Houston | TX | TX2210000 | ~2.3M |
| Phoenix PD | Phoenix | AZ | AZ0070000 | ~1.7M |
| San Antonio PD | San Antonio | TX | TX2220000 | ~1.5M |
| Dallas PD | Dallas | TX | TX2200000 | ~1.3M |
| San Diego PD | San Diego | CA | CA0370000 | ~1.4M |
| San Jose PD | San Jose | CA | CA0380000 | ~1.0M |

#### State Police Agencies

| Agency | State | ORI Code |
|--------|-------|----------|
| California Highway Patrol | CA | CA0010000 |
| Texas DPS | TX | TX0010000 |
| Florida Highway Patrol | FL | FL0010000 |
| New York State Police | NY | NY0010000 |
| Pennsylvania State Police | PA | PA0010000 |

### Finding ORI Codes

Use the `fbi_search_agencies` tool to find ORI codes:

```python
tool = FBISearchAgenciesTool()
result = tool.execute({
    "agency_name": "police department name",
    "state": "XX"
})
```

---

## Limitations

### API Limitations

1. **Data Availability**:
   - Historical data from 1960 to present
   - Most recent complete year is typically 2 years behind current
   - Preliminary data may be available for recent years

2. **Update Frequency**:
   - Annual updates (typically published in fall for previous year)
   - No real-time or monthly updates
   - Agencies submit data on different schedules

3. **Coverage Gaps**:
   - Not all agencies participate in UCR reporting
   - Some agencies report partial year data
   - Participation rates vary by state

4. **Data Quality Issues**:
   - Voluntary reporting system
   - Reporting standards vary by agency
   - Definition changes over time (e.g., rape definition in 2013)

### Technical Limitations

1. **Rate Limiting**:
   - Recommended: 120 requests/hour
   - No documented hard limits
   - Excessive use may result in throttling

2. **Request Size**:
   - No explicit limits documented
   - Trend analysis limited to reasonable time spans

3. **Timeout**:
   - 30-second timeout per request
   - Network issues may cause failures

### Tool-Specific Limitations

1. **fbi_compare_states**:
   - Maximum 10 states per comparison
   - All states must have data for the specified year

2. **fbi_get_crime_trend**:
   - Practical limit on time span (recommend < 30 years)
   - Missing years may create gaps in trend analysis

3. **fbi_search_agencies**:
   - Maximum 100 results per search
   - Fuzzy matching not supported
   - Case-sensitive searches

### Data Interpretation Caveats

1. **Reporting Variations**:
   - UCR vs NIBRS reporting methods
   - Jurisdictional differences
   - Definition changes over time

2. **Dark Figure of Crime**:
   - Only reported crimes are counted
   - Reporting rates vary by crime type
   - Not all crimes are discovered or reported

3. **Per Capita Calculations**:
   - Based on residential population
   - Doesn't account for commuters, tourists
   - Urban vs rural differences

---

## Error Handling

### Common Errors

#### 1. Invalid State Code
```python
ValueError: Invalid state code: XX
```

**Cause**: State abbreviation not in valid list  
**Solution**: Use 2-letter uppercase state codes (e.g., CA, NY, TX)

#### 2. Data Not Found
```python
ValueError: Data not found: statistics/state/CA/violent-crime
```

**Cause**: Data not available for specified parameters  
**Solution**: Check year availability, verify offense type

#### 3. Invalid ORI Code
```python
ValueError: Invalid ORI format
```

**Cause**: ORI code doesn't match pattern `^[A-Z]{2}[0-9]{7}$`  
**Solution**: Use `fbi_search_agencies` to find correct ORI

#### 4. API Request Failure
```python
ValueError: API request failed: HTTP 503
```

**Cause**: API temporarily unavailable  
**Solution**: Implement retry logic with exponential backoff

### Error Handling Best Practices

```python
import time
from typing import Optional

def fetch_with_retry(tool, arguments, max_retries=3) -> Optional[Dict]:
    """Fetch FBI data with retry logic"""
    for attempt in range(max_retries):
        try:
            result = tool.execute(arguments)
            return result
            
        except ValueError as e:
            error_msg = str(e)
            
            # Don't retry for client errors
            if "Invalid" in error_msg or "not found" in error_msg:
                print(f"Client error: {error_msg}")
                return None
            
            # Retry for server errors
            if attempt == max_retries - 1:
                print(f"Failed after {max_retries} attempts: {error_msg}")
                return None
                
            wait_time = 2 ** attempt
            print(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
            time.sleep(wait_time)
            
    return None
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=128)
def get_state_stats_cached(state: str, offense: str, year: int):
    """Cache state statistics for 1 hour"""
    tool = FBIGetStateStatisticsTool()
    return tool.execute({
        'state': state,
        'offense_type': offense,
        'year': year
    })
```

### Batch Operations

**Inefficient** - Sequential state queries:
```python
# BAD: N separate API calls
states = ['CA', 'TX', 'FL', 'NY']
results = []
for state in states:
    result = get_state_stats(state, 'violent_crime', 2022)
    results.append(result)
```

**Efficient** - Single comparison call:
```python
# GOOD: 1 API call for comparison
tool = FBICompareStatesTool()
result = tool.execute({
    'states': ['CA', 'TX', 'FL', 'NY'],
    'offense_type': 'violent_crime',
    'year': 2022
})
```

### Response Size Considerations

| Tool | Avg Response Size | Typical API Calls |
|------|-------------------|-------------------|
| fbi_get_national_statistics | ~1 KB | 1 |
| fbi_get_state_statistics | ~1 KB | 1 |
| fbi_get_agency_statistics | ~1 KB | 1 |
| fbi_search_agencies | ~2-10 KB | 1 |
| fbi_get_agency_details | ~2 KB | 1 |
| fbi_get_crime_trend | ~5-20 KB | N (years) |
| fbi_compare_states | ~3-8 KB | N (states) + 1 |
| fbi_get_offense_data | ~3-10 KB | 1 |
| fbi_get_participation_rate | ~1 KB | 1 |

### Recommended Cache TTL

| Data Type | Update Frequency | Recommended Cache TTL |
|-----------|------------------|----------------------|
| Annual statistics | Yearly | 30 days |
| Agency directory | Rarely | 90 days |
| Participation rates | Yearly | 30 days |
| Historical trends | Never changes | 90 days |

---

## Appendix A: State Abbreviation Reference

### All US States and Territories

| Code | State | Code | State | Code | State |
|------|-------|------|-------|------|-------|
| AL | Alabama | KY | Kentucky | ND | North Dakota |
| AK | Alaska | LA | Louisiana | OH | Ohio |
| AZ | Arizona | ME | Maine | OK | Oklahoma |
| AR | Arkansas | MD | Maryland | OR | Oregon |
| CA | California | MA | Massachusetts | PA | Pennsylvania |
| CO | Colorado | MI | Michigan | RI | Rhode Island |
| CT | Connecticut | MN | Minnesota | SC | South Carolina |
| DE | Delaware | MS | Mississippi | SD | South Dakota |
| FL | Florida | MO | Missouri | TN | Tennessee |
| GA | Georgia | MT | Montana | TX | Texas |
| HI | Hawaii | NE | Nebraska | UT | Utah |
| ID | Idaho | NV | Nevada | VT | Vermont |
| IL | Illinois | NH | New Hampshire | VA | Virginia |
| IN | Indiana | NJ | New Jersey | WA | Washington |
| IA | Iowa | NM | New Mexico | WV | West Virginia |
| KS | Kansas | NY | New York | WI | Wisconsin |
|  |  | NC | North Carolina | WY | Wyoming |
|  |  |  |  | DC | District of Columbia |

---

## Appendix B: Quick Reference

### Tool Selection Guide

| Need | Use Tool |
|------|----------|
| National crime statistics | fbi_get_national_statistics |
| State-level statistics | fbi_get_state_statistics |
| Agency-specific data | fbi_get_agency_statistics |
| Find agency ORI code | fbi_search_agencies |
| Agency details/info | fbi_get_agency_details |
| Detailed offense breakdown | fbi_get_offense_data |
| Data quality assessment | fbi_get_participation_rate |
| Historical trend analysis | fbi_get_crime_trend |
| Multi-state comparison | fbi_compare_states |

### Common Workflows

**Workflow 1: New Jurisdiction Analysis**
1. `fbi_search_agencies` - Find agency ORI
2. `fbi_get_agency_details` - Get jurisdiction info
3. `fbi_get_agency_statistics` - Get crime data

**Workflow 2: State Comparison**
1. `fbi_compare_states` - Compare multiple states
2. `fbi_get_state_statistics` - Detailed state analysis
3. `fbi_get_participation_rate` - Verify data quality

**Workflow 3: Trend Analysis**
1. `fbi_get_crime_trend` - Historical analysis
2. `fbi_get_national_statistics` - Current year baseline
3. `fbi_get_offense_data` - Detailed breakdown

---

## Appendix C: FBI UCR Reference

### UCR Program Overview

The **Uniform Crime Reporting (UCR) Program** is a nationwide, cooperative statistical effort of nearly 18,000 law enforcement agencies voluntarily reporting data on crimes brought to their attention.

### NIBRS vs UCR

| Aspect | UCR (Traditional) | NIBRS (Modern) |
|--------|------------------|----------------|
| Crimes | 8 Part I offenses | 46+ offense types |
| Detail | Summary counts | Incident-based |
| Context | Limited | Extensive (victim, offender, property) |
| Adoption | Universal | Transitioning (mandatory 2021+) |

### Resources

- **FBI CDE Website**: https://crime-data-explorer.fr.cloud.gov
- **API Documentation**: https://crime-data-explorer.fr.cloud.gov/api
- **UCR Handbook**: https://ucr.fbi.gov/additional-ucr-publications
- **Data Downloads**: https://crime-data-explorer.fr.cloud.gov/pages/downloads

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025 | Initial release with 9 tools |

---

## Support & Contact

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Copyright**: © 2025-2030 All Rights Reserved

For issues, questions, or feature requests, please contact the author directly.

---

*End of FBI Crime Data Explorer MCP Tool Reference Guide*

---

## Page Glossary

**Key terms referenced in this document:**

- **FBI (Federal Bureau of Investigation)**: The U.S. federal law enforcement and intelligence agency.

- **UCR (Uniform Crime Reporting)**: The FBI's program for collecting crime statistics from law enforcement agencies nationwide.

- **Crime Statistics**: Quantitative data on criminal offenses. FBI provides national, state, and local crime data.

- **NIBRS (National Incident-Based Reporting System)**: A detailed crime data collection system replacing summary UCR reporting.

- **Violent Crime**: Offenses involving force or threat of force (murder, assault, robbery, rape).

- **Property Crime**: Offenses involving taking property without force (burglary, theft, motor vehicle theft, arson).

- **Crime Rate**: Number of crimes per 100,000 population. Allows comparison across areas of different sizes.

- **ORI (Originating Agency Identifier)**: A unique code identifying law enforcement agencies in FBI databases.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
