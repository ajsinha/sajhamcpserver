# Zillow & Trulia MCP Tools Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
Comprehensive MCP tools for accessing Zillow and Trulia real estate data, including property searches, market trends, neighborhood information, and more. These tools provide programmatic access to millions of property listings and real estate data across the United States.

## Table of Contents
- [Configuration](#configuration)
- [Zillow Tool](#zillow-tool)
- [Trulia Tool](#trulia-tool)
- [Comparison Guide](#comparison-guide)
- [Complete Examples](#complete-examples)
- [Best Practices](#best-practices)

---

## Configuration

### API Key Setup
Both tools require a RapidAPI key for authentication. Sign up at [RapidAPI](https://rapidapi.com/) and subscribe to the respective APIs.

### Zillow Configuration
Edit `zillow_mcp_tool.json`:

```json
{
  "name": "zillow_tool",
  "api_key": "YOUR_RAPIDAPI_KEY_HERE",
  "max_hits": 300,
  "max_hit_interval": 60
}
```

### Trulia Configuration
Edit `trulia_mcp_tool.json`:

```json
{
  "name": "trulia_tool",
  "api_key": "YOUR_RAPIDAPI_KEY_HERE",
  "max_hits": 300,
  "max_hit_interval": 60
}
```

**Note:** You can use the same RapidAPI key for both tools if you've subscribed to both APIs.

---

## Zillow Tool

### Available Methods

#### 1. search_properties
Search for properties using various filters.

**Parameters:**
- `location` (required): City, state, ZIP code, or address
- `status`: "forSale", "forRent", or "recentlySold" (default: "forSale")
- `home_type`: "Houses", "Townhomes", "Condos", "Apartments"
- `min_price`: Minimum price
- `max_price`: Maximum price
- `bedrooms`: Number of bedrooms
- `bathrooms`: Number of bathrooms
- `sort`: "Homes_for_You", "Price_High_Low", "Price_Low_High", "Newest"
- `page`: Page number for pagination

**Example:**
```python
result = zillow_tool.handle_tool_call('search_properties', {
    'location': 'Seattle, WA',
    'status': 'forSale',
    'min_price': 400000,
    'max_price': 800000,
    'bedrooms': 3,
    'bathrooms': 2,
    'sort': 'Price_Low_High',
    'page': 1
})
```

**Response:**
```json
{
  "location": "Seattle, WA",
  "status": "forSale",
  "properties": [
    {
      "zpid": "48749425",
      "address": "123 Main St",
      "price": 650000,
      "bedrooms": 3,
      "bathrooms": 2.5,
      "livingArea": 2100,
      "imageUrl": "https://..."
    }
  ],
  "total_results": 1247,
  "page": 1
}
```

#### 2. get_property_details
Get comprehensive details for a specific property.

**Parameters:**
- `property_url` (required): Full Zillow property URL

**Example:**
```python
result = zillow_tool.handle_tool_call('get_property_details', {
    'property_url': 'https://www.zillow.com/homedetails/123-Main-St/48749425_zpid/'
})
```

**Response:**
```json
{
  "zpid": "48749425",
  "address": {
    "streetAddress": "123 Main St",
    "city": "Seattle",
    "state": "WA",
    "zipcode": "98101"
  },
  "price": 650000,
  "bedrooms": 3,
  "bathrooms": 2.5,
  "living_area": 2100,
  "lot_size": 5000,
  "year_built": 2015,
  "property_type": "Single Family",
  "description": "Beautiful home in prime location...",
  "zestimate": 675000,
  "rent_zestimate": 3200,
  "images": ["url1", "url2"],
  "url": "https://..."
}
```

#### 3. get_property_by_zpid
Retrieve property information using Zillow Property ID.

**Parameters:**
- `zpid` (required): Zillow Property ID

**Example:**
```python
result = zillow_tool.handle_tool_call('get_property_by_zpid', {
    'zpid': '48749425'
})
```

#### 4. get_zestimate
Get Zillow's estimated market value for a property.

**Parameters:**
- `zpid`: Zillow Property ID
- `property_url`: Property URL (alternative to ZPID)

**Example:**
```python
result = zillow_tool.handle_tool_call('get_zestimate', {
    'zpid': '48749425'
})
```

**Response:**
```json
{
  "zestimate": 675000,
  "value_change": 15000,
  "valuation_range": {
    "low": 642000,
    "high": 708000
  },
  "last_updated": "2025-10-15"
}
```

#### 5. search_by_address
Find a property by its exact address.

**Parameters:**
- `address` (required): Street address
- `city`: City name
- `state`: State abbreviation
- `zipcode`: ZIP code

**Example:**
```python
result = zillow_tool.handle_tool_call('search_by_address', {
    'address': '123 Main St',
    'city': 'Seattle',
    'state': 'WA',
    'zipcode': '98101'
})
```

#### 6. get_similar_properties
Find comparable properties (comps).

**Parameters:**
- `zpid` (required): Zillow Property ID

**Example:**
```python
result = zillow_tool.handle_tool_call('get_similar_properties', {
    'zpid': '48749425'
})
```

#### 7. get_property_images
Retrieve all images for a property.

**Parameters:**
- `zpid` (required): Zillow Property ID

#### 8. get_market_trends
Get market statistics for a location.

**Parameters:**
- `location` (required): Location name
- `region_type`: "city", "county", "zip", "neighborhood"

**Example:**
```python
result = zillow_tool.handle_tool_call('get_market_trends', {
    'location': 'Seattle, WA',
    'region_type': 'city'
})
```

**Response:**
```json
{
  "location": "Seattle, WA",
  "median_home_value": 825000,
  "median_rent": 2400,
  "value_change": 5.2,
  "price_per_sqft": 450,
  "inventory": 2847,
  "data_date": "2025-10-01"
}
```

#### 9. get_school_info
Get nearby school information.

**Parameters:**
- `zpid` (required): Zillow Property ID

#### 10. get_mortgage_calculator
Calculate mortgage payments.

**Parameters:**
- `price` (required): Property price
- `down_payment`: Down payment amount
- `interest_rate` (required): Annual interest rate (percentage)
- `loan_term`: Loan term in years (default: 30)

**Example:**
```python
result = zillow_tool.handle_tool_call('get_mortgage_calculator', {
    'price': 650000,
    'down_payment': 130000,
    'interest_rate': 6.5,
    'loan_term': 30
})
```

**Response:**
```json
{
  "price": 650000,
  "down_payment": 130000,
  "loan_amount": 520000,
  "interest_rate": 6.5,
  "loan_term_years": 30,
  "monthly_payment": 3287.48,
  "total_interest": 663094.40,
  "total_paid": 1183094.40
}
```

#### 11. search_agents
Find real estate agents.

**Parameters:**
- `location` (required): Search location
- `specialty`: "buyer", "seller", "rental"

#### 12. get_rent_estimate
Get Zillow's rent estimate (Rent Zestimate).

**Parameters:**
- `zpid` (required): Zillow Property ID

---

## Trulia Tool

### Available Methods

#### 1. search_properties
Search for properties with advanced filtering.

**Parameters:**
- `location` (required): City, state, or ZIP code
- `property_type`: "for_sale" or "for_rent"
- `home_type`: Array of types (Single_Family_Home, Condo, Townhome)
- `min_price`, `max_price`: Price range
- `min_beds`, `max_beds`: Bedroom range
- `min_baths`, `max_baths`: Bathroom range
- `min_sqft`, `max_sqft`: Square footage range
- `sort_by`: "relevance", "price_low", "price_high", "newest"
- `page`: Page number

**Example:**
```python
result = trulia_tool.handle_tool_call('search_properties', {
    'location': 'Austin, TX',
    'property_type': 'for_sale',
    'home_type': ['Single_Family_Home', 'Townhome'],
    'min_price': 300000,
    'max_price': 600000,
    'min_beds': 2,
    'max_beds': 4,
    'sort_by': 'price_low'
})
```

#### 2. get_property_details
Get detailed property information.

**Parameters:**
- `property_id`: Trulia property ID
- `property_url`: Trulia property URL

**Response includes:**
- Complete address
- Price and features
- Property description
- HOA fees
- Heating/cooling systems
- Virtual tour links
- Days on market
- Multiple photos

#### 3. search_by_coordinates
Search properties using GPS coordinates.

**Parameters:**
- `latitude` (required): Latitude
- `longitude` (required): Longitude
- `radius`: Search radius in miles (default: 5)
- `property_type`: "for_sale" or "for_rent"

**Example:**
```python
result = trulia_tool.handle_tool_call('search_by_coordinates', {
    'latitude': 47.6062,
    'longitude': -122.3321,
    'radius': 10,
    'property_type': 'for_sale'
})
```

#### 4. get_neighborhood_info
Get comprehensive neighborhood statistics.

**Parameters:**
- `location` (required): Neighborhood name

**Response:**
```json
{
  "location": "Queen Anne, Seattle",
  "name": "Queen Anne",
  "description": "Historic neighborhood with...",
  "median_home_value": 950000,
  "median_rent": 2800,
  "population": 28000,
  "demographics": {...},
  "walkability_score": 88,
  "transit_score": 75,
  "bike_score": 82,
  "nearby_neighborhoods": [...]
}
```

#### 5. get_crime_data
Get crime statistics for an area.

**Parameters:**
- `location` (required): Location name

**Response:**
```json
{
  "location": "Downtown Seattle",
  "overall_crime_grade": "B-",
  "violent_crime": "Below Average",
  "property_crime": "Average",
  "crime_rate": 32.5,
  "comparison_to_national": "15% higher",
  "yearly_trends": [...]
}
```

#### 6. get_school_ratings
Get school information and ratings.

**Parameters:**
- `location`: Location to search
- `property_id`: Property ID for nearby schools

**Response:**
```json
{
  "elementary_schools": [
    {
      "name": "Lincoln Elementary",
      "rating": 9,
      "distance": 0.5,
      "grades": "K-5",
      "students": 450
    }
  ],
  "middle_schools": [...],
  "high_schools": [...],
  "private_schools": [...],
  "district_rating": 8
}
```

#### 7. get_commute_time
Calculate commute time from property to work/destination.

**Parameters:**
- `property_location` (required): Property address
- `destination` (required): Destination address
- `travel_mode`: "driving", "transit", "walking", "bicycling"

**Example:**
```python
result = trulia_tool.handle_tool_call('get_commute_time', {
    'property_location': '123 Main St, Seattle, WA',
    'destination': 'Amazon HQ, Seattle, WA',
    'travel_mode': 'transit'
})
```

**Response:**
```json
{
  "from": "123 Main St, Seattle, WA",
  "to": "Amazon HQ, Seattle, WA",
  "travel_mode": "transit",
  "duration_minutes": 35,
  "distance_miles": 5.2,
  "traffic_condition": "moderate"
}
```

#### 8. search_rentals
Search specifically for rental properties.

**Parameters:**
- `location` (required): Search location
- `min_rent`, `max_rent`: Monthly rent range
- `bedrooms`: Number of bedrooms
- `bathrooms`: Number of bathrooms
- `pets_allowed`: Boolean for pet-friendly

**Example:**
```python
result = trulia_tool.handle_tool_call('search_rentals', {
    'location': 'San Francisco, CA',
    'min_rent': 2000,
    'max_rent': 4000,
    'bedrooms': 2,
    'pets_allowed': True
})
```

#### 9. get_local_amenities
Get nearby restaurants, shops, parks, etc.

**Parameters:**
- `location` (required): Property location
- `amenity_type`: "all", "restaurants", "shopping", "parks"
- `radius`: Search radius in miles

**Response:**
```json
{
  "location": "123 Main St",
  "amenity_type": "all",
  "radius_miles": 1,
  "restaurants": [
    {"name": "Italian Bistro", "distance": 0.3, "rating": 4.5}
  ],
  "shopping": [...],
  "parks": [...],
  "entertainment": [...],
  "healthcare": [...]
}
```

#### 10. get_price_history
View property price changes over time.

**Parameters:**
- `property_id` (required): Property ID

**Response:**
```json
{
  "property_id": "12345",
  "price_history": [
    {"date": "2025-10-01", "price": 650000, "event": "Listed"},
    {"date": "2025-09-15", "price": 675000, "event": "Price change"}
  ],
  "current_price": 650000,
  "original_list_price": 675000,
  "price_changes": 1
}
```

#### 11. get_tax_history
View property tax history.

**Parameters:**
- `property_id` (required): Property ID

#### 12. search_new_homes
Search for new construction homes.

**Parameters:**
- `location` (required): Search location
- `builder`: Builder name filter
- `min_price`, `max_price`: Price range

#### 13. get_open_houses
Find open house events.

**Parameters:**
- `location` (required): Search location
- `date`: Specific date (YYYY-MM-DD format)

**Example:**
```python
result = trulia_tool.handle_tool_call('get_open_houses', {
    'location': 'Portland, OR',
    'date': '2025-10-25'
})
```

#### 14. get_saved_searches
Retrieve saved search criteria (for authenticated users).

**Parameters:**
- `user_id` (required): User ID

---

## Comparison Guide

### When to Use Zillow

**Best for:**
- ✅ Zestimate valuations (Zillow's proprietary home value estimates)
- ✅ Comprehensive property data
- ✅ Mortgage calculators
- ✅ Agent search and connections
- ✅ Rent estimates
- ✅ Large inventory of listings

**Unique Features:**
- Zestimate algorithm
- Rent Zestimate
- Built-in mortgage calculator
- Agent ratings and reviews
- Market trend analysis

### When to Use Trulia

**Best for:**
- ✅ Neighborhood insights (walkability, transit, bike scores)
- ✅ Crime statistics and safety data
- ✅ School ratings and information
- ✅ Commute time calculations
- ✅ Local amenities discovery
- ✅ New construction homes

**Unique Features:**
- Walk Score, Transit Score, Bike Score
- Detailed crime data
- Commute time estimator
- Local amenities mapping
- Neighborhood character descriptions
- Open house schedules

### Feature Comparison Matrix

| Feature | Zillow | Trulia |
|---------|--------|--------|
| Property Search | ✅ | ✅ |
| Property Details | ✅ | ✅ |
| Price Estimates | ✅ (Zestimate) | ❌ |
| Market Trends | ✅ | ❌ |
| Neighborhood Info | ⚠️ Basic | ✅ Detailed |
| Crime Data | ❌ | ✅ |
| School Info | ✅ | ✅ |
| Commute Calculator | ❌ | ✅ |
| Mortgage Calculator | ✅ | ❌ |
| Agent Search | ✅ | ❌ |
| Rent Estimates | ✅ | ⚠️ Rental search |
| New Homes | ⚠️ | ✅ |
| Open Houses | ⚠️ | ✅ |
| Walkability Scores | ❌ | ✅ |

---

## Complete Examples

### Example 1: Finding the Perfect Home (Combined Approach)

```python
# Step 1: Search with Zillow for properties
zillow_results = zillow_tool.handle_tool_call('search_properties', {
    'location': 'Denver, CO',
    'status': 'forSale',
    'min_price': 400000,
    'max_price': 600000,
    'bedrooms': 3,
    'bathrooms': 2
})

# Step 2: Get Zestimate for top property
top_property_zpid = zillow_results['properties'][0]['zpid']
zestimate = zillow_tool.handle_tool_call('get_zestimate', {
    'zpid': top_property_zpid
})

# Step 3: Check neighborhood with Trulia
property_address = zillow_results['properties'][0]['address']
neighborhood = trulia_tool.handle_tool_call('get_neighborhood_info', {
    'location': f"{property_address['city']}, {property_address['state']}"
})

# Step 4: Check crime data
crime_data = trulia_tool.handle_tool_call('get_crime_data', {
    'location': f"{property_address['city']}, {property_address['state']}"
})

# Step 5: Calculate commute
commute = trulia_tool.handle_tool_call('get_commute_time', {
    'property_location': f"{property_address['streetAddress']}, {property_address['city']}",
    'destination': 'Downtown Denver',
    'travel_mode': 'driving'
})

# Step 6: Calculate mortgage
mortgage = zillow_tool.handle_tool_call('get_mortgage_calculator', {
    'price': zillow_results['properties'][0]['price'],
    'down_payment': 100000,
    'interest_rate': 6.5,
    'loan_term': 30
})

print(f"Property: {property_address['streetAddress']}")
print(f"Price: ${zillow_results['properties'][0]['price']:,}")
print(f"Zestimate: ${zestimate['zestimate']:,}")
print(f"Monthly Payment: ${mortgage['monthly_payment']:,}")
print(f"Walkability Score: {neighborhood['walkability_score']}")
print(f"Crime Grade: {crime_data['overall_crime_grade']}")
print(f"Commute to Work: {commute['duration_minutes']} minutes")
```

### Example 2: Investment Property Analysis

```python
# Search for investment properties
properties = zillow_tool.handle_tool_call('search_properties', {
    'location': 'Phoenix, AZ',
    'status': 'forSale',
    'min_price': 200000,
    'max_price': 350000,
    'property_type': 'Single Family'
})

for prop in properties['properties'][:5]:
    # Get rent estimate
    rent_estimate = zillow_tool.handle_tool_call('get_rent_estimate', {
        'zpid': prop['zpid']
    })
    
    # Calculate mortgage
    mortgage = zillow_tool.handle_tool_call('get_mortgage_calculator', {
        'price': prop['price'],
        'down_payment': prop['price'] * 0.25,
        'interest_rate': 7.0,
        'loan_term': 30
    })
    
    # Calculate cash flow
    estimated_rent = rent_estimate['rent_zestimate']
    monthly_payment = mortgage['monthly_payment']
    monthly_cashflow = estimated_rent - monthly_payment
    cap_rate = (estimated_rent * 12 - monthly_payment * 12) / prop['price'] * 100
    
    print(f"\nProperty: {prop['address']}")
    print(f"Price: ${prop['price']:,}")
    print(f"Estimated Rent: ${estimated_rent}/month")
    print(f"Mortgage: ${monthly_payment}/month")
    print(f"Monthly Cash Flow: ${monthly_cashflow}")
    print(f"Cap Rate: {cap_rate:.2f}%")
```

### Example 3: Market Research Report

```python
# Get market trends from Zillow
market_trends = zillow_tool.handle_tool_call('get_market_trends', {
    'location': 'Austin, TX',
    'region_type': 'city'
})

# Get neighborhood details from Trulia
neighborhoods = ['Downtown', 'South Congress', 'Hyde Park']
neighborhood_data = []

for neighborhood in neighborhoods:
    info = trulia_tool.handle_tool_call('get_neighborhood_info', {
        'location': f"{neighborhood}, Austin, TX"
    })
    
    crime = trulia_tool.handle_tool_call('get_crime_data', {
        'location': f"{neighborhood}, Austin, TX"
    })
    
    neighborhood_data.append({
        'name': neighborhood,
        'median_value': info['median_home_value'],
        'walkability': info['walkability_score'],
        'crime_grade': crime['overall_crime_grade']
    })

# Generate report
print("=== Austin, TX Market Report ===\n")
print(f"City-wide Median Home Value: ${market_trends['median_home_value']:,}")
print(f"Median Rent: ${market_trends['median_rent']:,}")
print(f"YoY Value Change: {market_trends['value_change']}%")
print(f"Price per Sq Ft: ${market_trends['price_per_sqft']}")
print(f"\nNeighborhood Comparison:")
for n in neighborhood_data:
    print(f"\n{n['name']}:")
    print(f"  Median Value: ${n['median_value']:,}")
    print(f"  Walkability: {n['walkability']}")
    print(f"  Crime Grade: {n['crime_grade']}")
```

### Example 4: Rental Property Search

```python
# Search rentals with Trulia
rentals = trulia_tool.handle_tool_call('search_rentals', {
    'location': 'San Diego, CA',
    'min_rent': 2000,
    'max_rent': 3500,
    'bedrooms': 2,
    'bathrooms': 2,
    'pets_allowed': True
})

for rental in rentals['rentals'][:10]:
    # Get property details
    details = trulia_tool.handle_tool_call('get_property_details', {
        'property_id': rental['property_id']
    })
    
    # Get local amenities
    amenities = trulia_tool.handle_tool_call('get_local_amenities', {
        'location': rental['address'],
        'amenity_type': 'all',
        'radius': 0.5
    })
    
    # Calculate commute
    commute = trulia_tool.handle_tool_call('get_commute_time', {
        'property_location': rental['address'],
        'destination': 'San Diego Downtown',
        'travel_mode': 'transit'
    })
    
    print(f"\nRental: {rental['address']}")
    print(f"Monthly Rent: ${rental['rent']}")
    print(f"Square Feet: {details['square_feet']}")
    print(f"Nearby Restaurants: {len(amenities['restaurants'])}")
    print(f"Commute to Downtown: {commute['duration_minutes']} min")
    print(f"Pet-Friendly: {'Yes' if details.get('pets_allowed') else 'No'}")
```

---

## Best Practices

### 1. Rate Limiting
Both tools have rate limits (300 requests per 60 seconds by default). For production use:

```python
import time

def search_with_rate_limit(tool, searches):
    results = []
    for search in searches:
        result = tool.handle_tool_call('search_properties', search)
        results.append(result)
        time.sleep(0.3)  # Prevent rate limiting
    return results
```

### 2. Error Handling
Always check for errors in responses:

```python
result = zillow_tool.handle_tool_call('search_properties', params)

if 'error' in result:
    print(f"Error: {result['error']}")
    # Handle error appropriately
else:
    # Process successful result
    properties = result['properties']
```

### 3. Data Validation
Validate user input before making API calls:

```python
def validate_search_params(params):
    if not params.get('location'):
        return False, "Location is required"
    
    if params.get('min_price', 0) > params.get('max_price', float('inf')):
        return False, "Min price cannot exceed max price"
    
    return True, None

valid, error = validate_search_params(search_params)
if not valid:
    print(f"Validation error: {error}")
else:
    result = zillow_tool.handle_tool_call('search_properties', search_params)
```

### 4. Caching Results
Cache frequently accessed data to reduce API calls:

```python
from functools import lru_cache
import hashlib
import json

@lru_cache(maxsize=100)
def cached_market_trends(location):
    return zillow_tool.handle_tool_call('get_market_trends', {
        'location': location,
        'region_type': 'city'
    })
```

### 5. Combining Data Sources
Leverage strengths of both platforms:

```python
def comprehensive_property_report(location, zpid=None, property_id=None):
    report = {}
    
    # Zillow: Get property and market data
    if zpid:
        report['zillow_details'] = zillow_tool.handle_tool_call('get_property_details', {'zpid': zpid})
        report['zestimate'] = zillow_tool.handle_tool_call('get_zestimate', {'zpid': zpid})
    
    report['market_trends'] = zillow_tool.handle_tool_call('get_market_trends', {'location': location})
    
    # Trulia: Get neighborhood and lifestyle data
    report['neighborhood'] = trulia_tool.handle_tool_call('get_neighborhood_info', {'location': location})
    report['crime_data'] = trulia_tool.handle_tool_call('get_crime_data', {'location': location})
    
    if property_id:
        report['schools'] = trulia_tool.handle_tool_call('get_school_ratings', {'property_id': property_id})
    
    return report
```

### 6. Pagination
Handle large result sets properly:

```python
def get_all_properties(location, max_pages=5):
    all_properties = []
    page = 1
    
    while page <= max_pages:
        result = zillow_tool.handle_tool_call('search_properties', {
            'location': location,
            'page': page
        })
        
        if 'error' in result or not result.get('properties'):
            break
        
        all_properties.extend(result['properties'])
        page += 1
    
    return all_properties
```

### 7. Price Conversion and Formatting
Standardize monetary values:

```python
def format_price(price):
    """Format price with thousands separator"""
    return f"${price:,.0f}"

def price_per_sqft(price, sqft):
    """Calculate price per square foot"""
    return price / sqft if sqft > 0 else 0
```

---

## Troubleshooting

### Common Issues

#### Issue: Rate Limit Exceeded
**Solution:** 
- Increase `max_hit_interval` in config
- Add delays between requests
- Implement request queuing

#### Issue: Invalid API Key
**Solution:**
- Verify API key in configuration
- Check RapidAPI subscription status
- Ensure correct API endpoint

#### Issue: No Results Found
**Solution:**
- Broaden search criteria
- Check location spelling
- Try different search parameters

#### Issue: Property Not Found
**Solution:**
- Verify ZPID or property ID
- Check if property is still listed
- Use alternative search method (by address)

---

## Security Considerations

### API Key Protection
- Never commit API keys to version control
- Use environment variables for sensitive data
- Rotate keys regularly
- Monitor API usage for anomalies

### Data Privacy
- Don't store personal information unnecessarily
- Follow data retention policies
- Comply with real estate data usage terms
- Respect user privacy preferences

---

## Support and Resources

### Official Documentation
- **Zillow API:** https://www.zillow.com/howto/api/
- **Trulia:** https://www.trulia.com/
- **RapidAPI:** https://rapidapi.com/

### Common Use Cases
- Real estate market analysis
- Investment property research
- Home buying decision support
- Rental property management
- Market trend reporting
- Neighborhood comparison

---

## Changelog

### Version 1.0.0 (2025-10-20)
- Initial release
- Zillow tool with 12 methods
- Trulia tool with 14 methods
- Comprehensive documentation
- Complete usage examples

---

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.