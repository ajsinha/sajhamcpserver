# Census.gov MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Census.gov MCP Tool provides access to US Census Bureau data including population, demographics, economic indicators, housing, and education statistics.

## Configuration
- **Environment Variables:**
  - `CENSUS_API_KEY`: Required for API access (get from census.gov)
- Access to American Community Survey (ACS) data
- Decennial Census data
- Population estimates

## Available Methods

### 1. get_population_data
Get population data.

**Parameters:**
- `year` (default: 2021): Data year
- `geography` (default: 'state'): 'state', 'county', 'place'
- `state` (default: '*'): State FIPS code or '*' for all

**Returns:**
- Population counts by geography
- Location names
- State and county codes

### 2. get_demographic_data
Get demographic data including age, race, ethnicity.

**Parameters:**
- `year` (default: 2021): Data year
- `state` (default: '06'): State FIPS code (06 = California)

**Returns:**
- Total population by gender
- Median age
- Race distribution (White, Black, Asian, etc.)
- Hispanic/Latino population

### 3. get_economic_data
Get economic data including income, poverty, employment.

**Parameters:**
- `year` (default: 2021): Data year
- `state` (default: '06'): State FIPS code

**Returns:**
- Median household income
- Population below poverty level
- Labor force statistics
- Unemployment count
- Median home value

### 4. get_housing_data
Get housing data.

**Parameters:**
- `year` (default: 2021): Data year
- `state` (default: '06'): State FIPS code

**Returns:**
- Total housing units
- Occupied vs vacant units
- Owner-occupied vs renter-occupied
- Median gross rent

### 5. get_education_data
Get education data.

**Parameters:**
- `year` (default: 2021): Data year
- `state` (default: '06'): State FIPS code

**Returns:**
- Population 25+ education levels
- High school graduates
- Bachelor's degrees
- Advanced degrees (Master's, Doctorate)

### 6. get_state_data
Get comprehensive data for all states.

**Parameters:**
- `year` (default: 2021): Data year

**Returns:**
- Population for all states
- State names and codes

### 7. get_county_data
Get data for counties.

**Parameters:**
- `year` (default: 2021): Data year
- `state` (default: '06'): State FIPS code

**Returns:**
- County-level population data
- County names and codes

### 8. search_datasets
Search available Census datasets.

**Parameters:**
- `keyword` (optional): Search keyword

**Returns:**
- Available datasets with descriptions
- Dataset codes
- Available years

## State FIPS Codes (Examples)

- 01: Alabama
- 02: Alaska
- 04: Arizona
- 05: Arkansas
- 06: California
- 08: Colorado
- 09: Connecticut
- 10: Delaware
- 11: District of Columbia
- 12: Florida
- 13: Georgia
- 15: Hawaii
- 16: Idaho
- 17: Illinois
- 18: Indiana
- 19: Iowa
- 20: Kansas
- 21: Kentucky
- 22: Louisiana
- 23: Maine
- 24: Maryland
- 25: Massachusetts
- 26: Michigan
- 27: Minnesota
- 28: Mississippi
- 29: Missouri
- 30: Montana
- 31: Nebraska
- 32: Nevada
- 33: New Hampshire
- 34: New Jersey
- 35: New Mexico
- 36: New York
- 37: North Carolina
- 38: North Dakota
- 39: Ohio
- 40: Oklahoma
- 41: Oregon
- 42: Pennsylvania
- 44: Rhode Island
- 45: South Carolina
- 46: South Dakota
- 47: Tennessee
- 48: Texas
- 49: Utah
- 50: Vermont
- 51: Virginia
- 53: Washington
- 54: West Virginia
- 55: Wisconsin
- 56: Wyoming

## Available Datasets

### American Community Survey (ACS)
- 5-Year Estimates (most detailed)
- 1-Year Estimates (large areas only)
- Covers demographics, economics, housing, social characteristics

### Decennial Census
- Complete population count
- Every 10 years (2000, 2010, 2020)
- Most comprehensive demographic data

### Population Estimates
- Annual population updates
- Between census years
- State, county, and city levels

### Economic Census
- Business and economic statistics
- Every 5 years (2017, 2022)

## Example Usage
```python
# Get population for all states
result = census_tool.handle_tool_call('get_population_data', {
    'year': 2021,
    'geography': 'state',
    'state': '*'
})

# Get California demographics
result = census_tool.handle_tool_call('get_demographic_data', {
    'year': 2021,
    'state': '06'  # California
})

# Get Texas economic data
result = census_tool.handle_tool_call('get_economic_data', {
    'year': 2021,
    'state': '48'  # Texas
})

# Get New York housing data
result = census_tool.handle_tool_call('get_housing_data', {
    'year': 2021,
    'state': '36'  # New York
})

# Get Florida education data
result = census_tool.handle_tool_call('get_education_data', {
    'year': 2021,
    'state': '12'  # Florida
})

# Get all counties in California
result = census_tool.handle_tool_call('get_county_data', {
    'year': 2021,
    'state': '06'
})

# Search for available datasets
result = census_tool.handle_tool_call('search_datasets', {
    'keyword': 'income'
})
```

## Data Variables

### Demographics (B-series codes)
- B01001: Sex by Age
- B01002: Median Age
- B02001: Race
- B03002: Hispanic or Latino Origin
- B15003: Educational Attainment

### Economics (B-series codes)
- B19013: Median Household Income
- B17001: Poverty Status
- B23025: Employment Status
- B25077: Median Home Value

### Housing (B-series codes)
- B25001: Housing Units
- B25002: Occupancy Status
- B25003: Tenure
- B25064: Median Gross Rent

## Response Format

### Population Data
```json
{
  "year": 2021,
  "geography": "state",
  "data": [
    {
      "name": "California",
      "population": 39538223,
      "state": "06"
    }
  ],
  "count": 50
}
```

### Demographic Data
```json
{
  "year": 2021,
  "state": "California",
  "demographics": {
    "total_population": 39538223,
    "male_population": 19737045,
    "female_population": 19801178,
    "median_age": 36.5,
    "white_alone": 14356081,
    "black_alone": 2171244,
    "asian_alone": 5736098,
    "hispanic_latino": 15540888
  }
}
```

## Error Handling

- API key required for all operations
- Returns error if API key not set
- Handles null/missing values in data
- Provides meaningful error messages

## Best Practices

1. Cache frequently accessed data
2. Use appropriate geography level
3. Be aware of data availability by year
4. Understand margin of error in ACS data
5. Use FIPS codes for precise location queries


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.