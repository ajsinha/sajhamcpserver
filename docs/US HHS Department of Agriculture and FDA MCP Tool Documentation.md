# US Government Data Tools Documentation
## HHS, USDA, and FDA MCP Tools

## © 2025-2030 Ashutosh Sinha


## Overview
Comprehensive MCP tools providing access to critical US government health, nutrition, and safety data from three major agencies:
- **HHS (Health and Human Services)** - Healthcare data, hospitals, public health
- **USDA (Department of Agriculture)** - Nutrition, food composition, agriculture
- **FDA (Food and Drug Administration)** - Drug safety, medical devices, food recalls

---

## Table of Contents
1. [Configuration](#configuration)
2. [HHS Tool](#hhs-tool)
3. [USDA Tool](#usda-tool)
4. [FDA Tool](#fda-tool)
5. [Complete Examples](#complete-examples)
6. [Best Practices](#best-practices)

---

## Configuration

### API Key Setup

#### HHS - HealthData.gov
No API key required for basic access. For higher rate limits, register at:
https://healthdata.gov/user/register

```json
{
  "api_key": "",
  "base_url": "https://healthdata.gov/api/3"
}
```

#### USDA - FoodData Central & NASS
Register for API key at:
- FoodData Central: https://fdc.nal.usda.gov/api-key-signup.html
- NASS QuickStats: https://quickstats.nass.usda.gov/api

```json
{
  "api_key": "YOUR_USDA_API_KEY"
}
```

#### FDA - openFDA
No API key required for up to 240 requests/minute. For higher limits:
https://open.fda.gov/apis/authentication/

```json
{
  "api_key": ""
}
```

---

## HHS Tool

### Available Methods

#### 1. search_datasets
Search across all HHS open data.

**Parameters:**
- `query` (required): Search term
- `limit`: Number of results (default: 20)
- `offset`: Starting position (default: 0)

**Example:**
```python
result = hhs_tool.handle_tool_call('search_datasets', {
    'query': 'COVID-19 cases',
    'limit': 10
})
```

**Response:**
```json
{
  "query": "COVID-19 cases",
  "datasets": [
    {
      "id": "dataset_123",
      "name": "covid-19-state-data",
      "title": "COVID-19 State-Level Data"
    }
  ],
  "count": 10
}
```

#### 2. search_hospitals
Find hospitals by location and type.

**Parameters:**
- `state`: State abbreviation
- `city`: City name
- `hospital_type`: Type of hospital
- `limit`: Max results (default: 50)

**Example:**
```python
result = hhs_tool.handle_tool_call('search_hospitals', {
    'state': 'CA',
    'city': 'Los Angeles',
    'hospital_type': 'Acute Care',
    'limit': 25
})
```

#### 3. get_hospital_quality
Get quality ratings and performance measures.

**Parameters:**
- `hospital_id` (required): Hospital provider ID
- `measure_type`: mortality, safety, readmission, patient_experience, or all

**Example:**
```python
result = hhs_tool.handle_tool_call('get_hospital_quality', {
    'hospital_id': '050146',
    'measure_type': 'mortality'
})
```

#### 4. get_medicare_data
Get Medicare spending and utilization.

**Parameters:**
- `state`: State abbreviation
- `year`: Year of data
- `category`: inpatient, outpatient, prescription

**Example:**
```python
result = hhs_tool.handle_tool_call('get_medicare_data', {
    'state': 'NY',
    'year': '2023',
    'category': 'inpatient'
})
```

**Response:**
```json
{
  "state": "NY",
  "year": "2023",
  "category": "inpatient",
  "records": [...],
  "total_spending": 15678900000,
  "count": 150
}
```

#### 5. get_disease_surveillance
Track disease outbreaks and trends.

**Parameters:**
- `disease` (required): Disease name
- `state`: State filter
- `start_date`: Start date (YYYY-MM-DD)
- `end_date`: End date (YYYY-MM-DD)

**Example:**
```python
result = hhs_tool.handle_tool_call('get_disease_surveillance', {
    'disease': 'influenza',
    'state': 'TX',
    'start_date': '2024-01-01',
    'end_date': '2024-12-31'
})
```

#### 6. get_vaccination_data
Get vaccination coverage rates.

**Parameters:**
- `vaccine_type`: Vaccine name
- `state`: State abbreviation
- `age_group`: Age group category
- `year`: Year of data

**Example:**
```python
result = hhs_tool.handle_tool_call('get_vaccination_data', {
    'vaccine_type': 'COVID-19',
    'state': 'FL',
    'age_group': '18-64',
    'year': '2024'
})
```

#### 7. get_opioid_data
Get opioid prescription and overdose statistics.

**Parameters:**
- `state`: State abbreviation
- `year`: Year of data
- `data_type`: prescriptions, overdoses, treatment, or all

**Example:**
```python
result = hhs_tool.handle_tool_call('get_opioid_data', {
    'state': 'OH',
    'year': '2023',
    'data_type': 'overdoses'
})
```

#### 8. search_nursing_homes
Find nursing homes with quality ratings.

**Parameters:**
- `state`: State abbreviation
- `city`: City name
- `min_rating`: Minimum star rating (1-5)
- `limit`: Max results

**Example:**
```python
result = hhs_tool.handle_tool_call('search_nursing_homes', {
    'state': 'IL',
    'city': 'Chicago',
    'min_rating': 4,
    'limit': 20
})
```

#### 9. get_health_disparities
Analyze health disparities by demographics.

**Parameters:**
- `indicator` (required): Health indicator
- `demographic`: race, income, education
- `state`: State filter

**Example:**
```python
result = hhs_tool.handle_tool_call('get_health_disparities', {
    'indicator': 'diabetes',
    'demographic': 'income',
    'state': 'GA'
})
```

---

## USDA Tool

### Available Methods

#### 1. search_foods
Search USDA's comprehensive food database.

**Parameters:**
- `query` (required): Food name or description
- `data_type`: Foundation, SR Legacy, Branded
- `page_size`: Results per page (default: 50)
- `page_number`: Page number (default: 1)

**Example:**
```python
result = usda_tool.handle_tool_call('search_foods', {
    'query': 'apple',
    'data_type': 'Foundation',
    'page_size': 25
})
```

**Response:**
```json
{
  "query": "apple",
  "data_type": "Foundation",
  "foods": [
    {
      "fdc_id": "171688",
      "description": "Apple, raw",
      "brand_owner": null,
      "data_type": "Foundation",
      "published_date": "2019-04-01"
    }
  ],
  "total_hits": 245,
  "current_page": 1,
  "total_pages": 10
}
```

#### 2. get_food_details
Get complete nutrition information for a food.

**Parameters:**
- `fdc_id` (required): FoodData Central ID

**Example:**
```python
result = usda_tool.handle_tool_call('get_food_details', {
    'fdc_id': '171688'
})
```

**Response:**
```json
{
  "fdc_id": "171688",
  "description": "Apple, raw",
  "serving_size": 100,
  "serving_size_unit": "g",
  "nutrients": [
    {"name": "Energy", "amount": 52, "unit": "kcal"},
    {"name": "Protein", "amount": 0.26, "unit": "g"},
    {"name": "Total lipid (fat)", "amount": 0.17, "unit": "g"},
    {"name": "Carbohydrate", "amount": 13.81, "unit": "g"},
    {"name": "Fiber", "amount": 2.4, "unit": "g"},
    {"name": "Sugars", "amount": 10.39, "unit": "g"},
    {"name": "Vitamin C", "amount": 4.6, "unit": "mg"}
  ],
  "category": "Fruits and Fruit Juices"
}
```

#### 3. get_nutrients
Get specific nutrients for multiple foods.

**Parameters:**
- `fdc_ids` (required): Array of FDC IDs
- `nutrients`: Array of nutrient names to filter

**Example:**
```python
result = usda_tool.handle_tool_call('get_nutrients', {
    'fdc_ids': ['171688', '171687', '171686'],
    'nutrients': ['Energy', 'Protein', 'Vitamin C']
})
```

#### 4. search_farmers_markets
Find local farmers markets.

**Parameters:**
- `location`: City and state
- `zipcode`: ZIP code

**Example:**
```python
result = usda_tool.handle_tool_call('search_farmers_markets', {
    'zipcode': '94102'
})
```

**Response:**
```json
{
  "search_location": "94102",
  "farmers_markets": [
    {
      "id": "1001234",
      "name": "Civic Center Farmers Market"
    },
    {
      "id": "1001235",
      "name": "Ferry Plaza Farmers Market"
    }
  ],
  "count": 2
}
```

#### 5. get_crop_data
Get crop production and yield statistics.

**Parameters:**
- `commodity` (required): Crop name (CORN, WHEAT, SOYBEANS, etc.)
- `state`: State name
- `year`: Year of data

**Example:**
```python
result = usda_tool.handle_tool_call('get_crop_data', {
    'commodity': 'CORN',
    'state': 'IOWA',
    'year': '2023'
})
```

**Response:**
```json
{
  "commodity": "CORN",
  "state": "IOWA",
  "year": "2023",
  "crop_data": [
    {
      "year": "2023",
      "state": "IOWA",
      "value": "2450000000",
      "unit": "BU"
    }
  ],
  "count": 1
}
```

#### 6. get_livestock_data
Get livestock inventory and production.

**Parameters:**
- `animal_type` (required): CATTLE, HOGS, CHICKENS, etc.
- `state`: State name
- `year`: Year of data

**Example:**
```python
result = usda_tool.handle_tool_call('get_livestock_data', {
    'animal_type': 'CATTLE',
    'state': 'TEXAS',
    'year': '2023'
})
```

#### 7. search_organic_data
Get organic agriculture statistics.

**Parameters:**
- `commodity`: Crop name
- `state`: State name
- `year`: Year of data

**Example:**
```python
result = usda_tool.handle_tool_call('search_organic_data', {
    'commodity': 'CORN',
    'state': 'CALIFORNIA',
    'year': '2023'
})
```

#### 8. get_food_prices
Get commodity price data.

**Parameters:**
- `commodity` (required): Commodity name
- `year`: Year of data

**Example:**
```python
result = usda_tool.handle_tool_call('get_food_prices', {
    'commodity': 'WHEAT',
    'year': '2024'
})
```

**Response:**
```json
{
  "commodity": "WHEAT",
  "year": "2024",
  "price_data": [
    {
      "year": "2024",
      "period": "JAN",
      "price": "6.45",
      "unit": "$ / BU"
    }
  ],
  "average_price": 6.52,
  "count": 12
}
```

#### 9. get_dietary_guidelines
Get USDA dietary recommendations.

**Parameters:**
- `category`: vegetables, fruits, grains, protein, dairy
- `age_group`: Age group

**Example:**
```python
result = usda_tool.handle_tool_call('get_dietary_guidelines', {
    'category': 'fruits',
    'age_group': 'adults'
})
```

---

## FDA Tool

### Available Methods

#### 1. search_drugs
Search FDA drug database.

**Parameters:**
- `query` (required): Drug name
- `limit`: Max results (default: 10)

**Example:**
```python
result = fda_tool.handle_tool_call('search_drugs', {
    'query': 'ibuprofen',
    'limit': 5
})
```

**Response:**
```json
{
  "query": "ibuprofen",
  "drugs": [
    {
      "brand_name": "Advil",
      "generic_name": "Ibuprofen",
      "manufacturer": "Pfizer",
      "product_type": "HUMAN OTC DRUG",
      "route": ["ORAL"],
      "substance_name": ["IBUPROFEN"]
    }
  ],
  "total": 128,
  "count": 5
}
```

#### 2. get_drug_label
Get complete drug labeling information.

**Parameters:**
- `drug_name` (required): Drug brand or generic name

**Example:**
```python
result = fda_tool.handle_tool_call('get_drug_label', {
    'drug_name': 'Lipitor'
})
```

**Response:**
```json
{
  "drug_name": "Lipitor",
  "brand_name": ["Lipitor"],
  "generic_name": ["Atorvastatin Calcium"],
  "manufacturer": ["Pfizer"],
  "indications_and_usage": ["Treatment of high cholesterol..."],
  "dosage_and_administration": ["Initial dose 10-20mg..."],
  "warnings": ["Liver enzyme changes...", "Muscle problems..."],
  "adverse_reactions": ["Headache", "Myalgia", "Diarrhea"],
  "drug_interactions": ["Cyclosporine", "Gemfibrozil"],
  "active_ingredient": ["Atorvastatin calcium 10.85mg..."]
}
```

#### 3. get_drug_adverse_events
Get reported adverse reactions.

**Parameters:**
- `drug_name` (required): Drug name
- `limit`: Max reports (default: 100)

**Example:**
```python
result = fda_tool.handle_tool_call('get_drug_adverse_events', {
    'drug_name': 'Aspirin',
    'limit': 50
})
```

**Response:**
```json
{
  "drug_name": "Aspirin",
  "adverse_events": [
    {"reaction": "Gastrointestinal haemorrhage", "count": 1247},
    {"reaction": "Nausea", "count": 892},
    {"reaction": "Vomiting", "count": 654}
  ],
  "total_reports": 15234
}
```

#### 4. search_medical_devices
Search medical device database.

**Parameters:**
- `query` (required): Device name
- `device_class`: 1, 2, or 3
- `limit`: Max results

**Example:**
```python
result = fda_tool.handle_tool_call('search_medical_devices', {
    'query': 'insulin pump',
    'device_class': '2',
    'limit': 10
})
```

#### 5. search_food_recalls
Search food safety recalls.

**Parameters:**
- `product`: Product name
- `reason`: Recall reason
- `classification`: Class I, II, or III
- `start_date`: Start date (YYYYMMDD)
- `limit`: Max results

**Example:**
```python
result = fda_tool.handle_tool_call('search_food_recalls', {
    'product': 'lettuce',
    'reason': 'Salmonella',
    'start_date': '20240101',
    'limit': 25
})
```

**Response:**
```json
{
  "product": "lettuce",
  "reason": "Salmonella",
  "recalls": [
    {
      "product_description": "Organic Romaine Lettuce",
      "reason_for_recall": "Potential Salmonella contamination",
      "classification": "Class I",
      "recall_number": "F-2024-1234",
      "recall_initiation_date": "20240215",
      "distribution_pattern": "Nationwide",
      "recalling_firm": "Fresh Produce Inc."
    }
  ],
  "count": 3
}
```

#### 6. get_device_recalls
Get medical device recalls.

**Parameters:**
- `device_name`: Device name
- `classification`: Class I, II, or III
- `start_date`: Start date
- `limit`: Max results

**Example:**
```python
result = fda_tool.handle_tool_call('get_device_recalls', {
    'device_name': 'pacemaker',
    'classification': 'Class I',
    'limit': 20
})
```

#### 7. search_ndc_directory
Search National Drug Code directory.

**Parameters:**
- `ndc_code`: NDC code
- `brand_name`: Brand name
- `limit`: Max results

**Example:**
```python
result = fda_tool.handle_tool_call('search_ndc_directory', {
    'brand_name': 'Tylenol',
    'limit': 10
})
```

#### 8. get_drug_approvals
Get drug approval information.

**Parameters:**
- `application_number`: FDA application number
- `sponsor_name`: Sponsor/manufacturer name
- `limit`: Max results

**Example:**
```python
result = fda_tool.handle_tool_call('get_drug_approvals', {
    'sponsor_name': 'Pfizer',
    'limit': 5
})
```

#### 9. get_generic_drugs
Find generic equivalents for brand-name drugs.

**Parameters:**
- `brand_name` (required): Brand drug name

**Example:**
```python
result = fda_tool.handle_tool_call('get_generic_drugs', {
    'brand_name': 'Prozac'
})
```

**Response:**
```json
{
  "brand_name": "Prozac",
  "generic_equivalents": [
    "Fluoxetine",
    "Fluoxetine Hydrochloride"
  ],
  "count": 2
}
```

---

## Complete Examples

### Example 1: Comprehensive Health Report

```python
# Get hospital quality in area
hospitals = hhs_tool.handle_tool_call('search_hospitals', {
    'state': 'MA',
    'city': 'Boston',
    'limit': 10
})

# Get vaccination rates
vax_data = hhs_tool.handle_tool_call('get_vaccination_data', {
    'vaccine_type': 'COVID-19',
    'state': 'MA',
    'year': '2024'
})

# Check disease surveillance
flu_data = hhs_tool.handle_tool_call('get_disease_surveillance', {
    'disease': 'influenza',
    'state': 'MA',
    'start_date': '2024-01-01'
})

# Generate report
print("=== Boston Healthcare Report ===")
print(f"\nHospitals Found: {len(hospitals['hospitals'])}")
print(f"COVID-19 Vaccination Rate: {vax_data['average_coverage']}%")
print(f"Flu Cases This Year: {flu_data['total_cases']}")
```

### Example 2: Nutrition Analysis

```python
# Search for food
foods = usda_tool.handle_tool_call('search_foods', {
    'query': 'chicken breast',
    'data_type': 'Foundation'
})

# Get detailed nutrition
fdc_id = foods['foods'][0]['fdc_id']
nutrition = usda_tool.handle_tool_call('get_food_details', {
    'fdc_id': fdc_id
})

# Get dietary guidelines
guidelines = usda_tool.handle_tool_call('get_dietary_guidelines', {
    'category': 'protein'
})

print("=== Nutrition Analysis: Chicken Breast ===")
print(f"\nServing Size: {nutrition['serving_size']}{nutrition['serving_size_unit']}")
print("\nKey Nutrients:")
for nutrient in nutrition['nutrients'][:10]:
    print(f"  {nutrient['name']}: {nutrient['amount']}{nutrient['unit']}")
print(f"\nUSDA Guideline: {guidelines['guideline']}")
```

### Example 3: Drug Safety Check

```python
# Search for drug
drugs = fda_tool.handle_tool_call('search_drugs', {
    'query': 'metformin',
    'limit': 1
})

# Get drug label
label = fda_tool.handle_tool_call('get_drug_label', {
    'drug_name': 'metformin'
})

# Check adverse events
adverse = fda_tool.handle_tool_call('get_drug_adverse_events', {
    'drug_name': 'metformin',
    'limit': 100
})

# Find generic alternatives
generics = fda_tool.handle_tool_call('get_generic_drugs', {
    'brand_name': 'Glucophage'
})

print("=== Drug Safety Report: Metformin ===")
print(f"\nBrand Names: {', '.join(label['brand_name'])}")
print(f"Manufacturer: {', '.join(label['manufacturer'])}")
print(f"\nIndications: {label['indications_and_usage'][0][:100]}...")
print(f"\nTop Adverse Events:")
for event in adverse['adverse_events'][:5]:
    print(f"  {event['reaction']}: {event['count']} reports")
print(f"\nGeneric Equivalents: {', '.join(generics['generic_equivalents'])}")
```

### Example 4: Agricultural Market Analysis

```python
# Get crop production
corn_data = usda_tool.handle_tool_call('get_crop_data', {
    'commodity': 'CORN',
    'state': 'IOWA',
    'year': '2023'
})

# Get commodity prices
corn_prices = usda_tool.handle_tool_call('get_food_prices', {
    'commodity': 'CORN',
    'year': '2024'
})

# Get organic data
organic_corn = usda_tool.handle_tool_call('search_organic_data', {
    'commodity': 'CORN',
    'state': 'IOWA',
    'year': '2023'
})

# Get livestock data
cattle_data = usda_tool.handle_tool_call('get_livestock_data', {
    'animal_type': 'CATTLE',
    'state': 'IOWA',
    'year': '2023'
})

print("=== Iowa Agricultural Report 2023-2024 ===")
print(f"\nCorn Production: {corn_data['crop_data'][0]['value']} bushels")
print(f"Average Corn Price 2024: ${corn_prices['average_price']}/bushel")
print(f"Organic Corn Production: {organic_corn['count']} operations")
print(f"Cattle Inventory: {cattle_data['livestock_data'][0]['count']} head")
```

### Example 5: Food Safety Monitoring

```python
# Search food recalls
recalls = fda_tool.handle_tool_call('search_food_recalls', {
    'product': '',
    'classification': 'Class I',
    'start_date': '20240101',
    'limit': 50
})

# Get enforcement actions
enforcement = fda_tool.handle_tool_call('get_food_enforcement', {
    'product_type': 'Food',
    'limit': 50
})

# Search USDA food recalls
usda_recalls = usda_tool.handle_tool_call('search_food_recalls', {
    'keyword': 'contamination',
    'start_date': '2024-01-01'
})

print("=== Food Safety Alert: 2024 ===")
print(f"\nClass I FDA Recalls: {recalls['count']}")
print(f"FDA Enforcement Actions: {enforcement['count']}")
print("\nRecent High-Priority Recalls:")
for recall in recalls['recalls'][:5]:
    print(f"\n  Product: {recall['product_description']}")
    print(f"  Reason: {recall['reason_for_recall']}")
    print(f"  Date: {recall['recall_initiation_date']}")
    print(f"  Firm: {recall['recalling_firm']}")
```

---

## Best Practices

### 1. Rate Limiting
All three APIs have rate limits. Implement delays:

```python
import time

def batch_lookup(tool, method, items):
    results = []
    for item in items:
        result = tool.handle_tool_call(method, item)
        results.append(result)
        time.sleep(0.5)  # Prevent rate limiting
    return results
```

### 2. Error Handling

```python
def safe_api_call(tool, method, params):
    try:
        result = tool.handle_tool_call(method, params)
        
        if 'error' in result:
            print(f"API Error: {result['error']}")
            return None
        
        return result
    except Exception as e:
        print(f"Exception: {str(e)}")
        return None
```

### 3. Data Caching

```python
from functools import lru_cache
import json

@lru_cache(maxsize=200)
def cached_food_details(fdc_id):
    return usda_tool.handle_tool_call('get_food_details', {
        'fdc_id': fdc_id
    })
```

### 4. Combining Data Sources

```python
def comprehensive_drug_report(drug_name):
    # FDA data
    fda_label = fda_tool.handle_tool_call('get_drug_label', {
        'drug_name': drug_name
    })
    
    fda_events = fda_tool.handle_tool_call('get_drug_adverse_events', {
        'drug_name': drug_name
    })
    
    # HHS data (if available)
    # Could include Medicare spending on this drug
    
    return {
        'fda_label': fda_label,
        'adverse_events': fda_events,
        'safety_score': calculate_safety_score(fda_events)
    }

def calculate_safety_score(events):
    # Custom scoring logic
    total_reports = events.get('total_reports', 0)
    serious_events = sum(1 for e in events.get('adverse_events', []) 
                        if 'death' in e.get('reaction', '').lower())
    return max(0, 100 - (serious_events / total_reports * 100))
```

### 5. Data Validation

```python
def validate_state(state):
    valid_states = ['AL', 'AK', 'AZ', ...]  # All US states
    return state.upper() in valid_states

def validate_date(date_str):
    try:
        from datetime import datetime
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False
```

---

## Security and Privacy

### Data Usage Guidelines
- **HHS**: Public health data - follow HIPAA guidelines when applicable
- **USDA**: Public agricultural data - no restrictions
- **FDA**: Public safety data - cite FDA as source when publishing

### API Key Protection
```python
import os

# Use environment variables
HHS_API_KEY = os.getenv('HHS_API_KEY', '')
USDA_API_KEY = os.getenv('USDA_API_KEY', 'DEMO_KEY')
FDA_API_KEY = os.getenv('FDA_API_KEY', '')
```

---

## Troubleshooting

### Common Issues

**Issue: Rate limit exceeded**
- Solution: Add delays between requests
- Use API key for higher limits
- Cache frequently accessed data

**Issue: No results found**
- Check spelling and capitalization
- Verify date formats (YYYY-MM-DD or YYYYMMDD)
- Broaden search criteria

**Issue: Incomplete data**
- Some datasets may have missing values
- Always check for None/null values
- Use .get() with defaults

**Issue: API timeout**
- Increase timeout setting
- Break large requests into smaller batches
- Try during off-peak hours

---

## Resources

### Official Documentation
- **HHS**: https://healthdata.gov/
- **USDA FoodData**: https://fdc.nal.usda.gov/api-guide.html
- **USDA NASS**: https://quickstats.nass.usda.gov/api
- **FDA openFDA**: https://open.fda.gov/

### Data Update Frequency
- **HHS**: Varies by dataset (daily to annually)
- **USDA Food**: Quarterly updates
- **USDA NASS**: Weekly to annually
- **FDA**: Daily updates for recalls and adverse events

---

## Changelog

### Version 1.0.0 (2025-10-20)
- Initial release
- HHS tool with 14 methods
- USDA tool with 14 methods
- FDA tool with 14 methods
- Comprehensive documentation
- Complete usage examples

---

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.