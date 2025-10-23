# JSON Configuration Files Guide

## © 2025-2030 Ashutosh Sinha

## Overview
Three separate JSON configuration files for US Government Data MCP Tools.

---

## File Locations

```
project/
├── tools/
│   ├── hhs_mcp_tool.py
│   ├── usda_mcp_tool.py
│   └── fda_mcp_tool.py
└── config/
    ├── hhs_mcp_tool.json      ← HHS Configuration
    ├── usda_mcp_tool.json      ← USDA Configuration
    └── fda_mcp_tool.json       ← FDA Configuration
```

---

## 1. HHS Configuration (hhs_mcp_tool.json)

### Setup Instructions

**Step 1: Get API Key (Optional)**
- Visit: https://healthdata.gov/user/register
- Register for free account
- No API key needed for basic usage

**Step 2: Configure JSON**
```json
{
  "api_key": "",                              // Leave blank or add your key
  "base_url": "https://healthdata.gov/api/3", // Default endpoint
  "max_hits": 200,                            // Rate limit: 200 requests
  "max_hit_interval": 60                      // Per 60 seconds
}
```

### Available Methods (14 total)
- `search_datasets` - Search all HHS data
- `get_dataset` - Get specific dataset
- `search_hospitals` - Find hospitals
- `get_hospital_quality` - Quality ratings
- `get_medicare_data` - Medicare spending
- `get_public_health_stats` - Public health statistics
- `search_health_indicators` - Health indicators
- `get_disease_surveillance` - Disease tracking
- `get_healthcare_spending` - Healthcare costs
- `search_nursing_homes` - Nursing home finder
- `get_vaccination_data` - Vaccination rates
- `get_opioid_data` - Opioid statistics
- `search_community_health` - Health centers
- `get_health_disparities` - Disparity analysis

### Example Usage
```python
from tools.hhs_mcp_tool import HHSMCPTool

# Load configuration
config = load_json('config/hhs_mcp_tool.json')

# Initialize tool
hhs_tool = HHSMCPTool(config)

# Search hospitals
result = hhs_tool.handle_tool_call('search_hospitals', {
    'state': 'CA',
    'city': 'San Francisco'
})
```

---

## 2. USDA Configuration (usda_mcp_tool.json)

### Setup Instructions

**Step 1: Get API Key**
- FoodData Central: https://fdc.nal.usda.gov/api-key-signup.html
- NASS QuickStats: https://quickstats.nass.usda.gov/api
- Use "DEMO_KEY" for testing (limited requests)

**Step 2: Configure JSON**
```json
{
  "api_key": "YOUR_USDA_API_KEY",  // Replace with your key
  "max_hits": 200,
  "max_hit_interval": 60
}
```

### Available Methods (14 total)
- `search_foods` - Search food database
- `get_food_details` - Detailed nutrition
- `get_nutrients` - Specific nutrients
- `search_farmers_markets` - Find markets
- `get_crop_data` - Crop production
- `get_livestock_data` - Livestock data
- `search_organic_data` - Organic agriculture
- `get_food_prices` - Food prices
- `search_nutrition_programs` - SNAP, WIC, etc.
- `get_dietary_guidelines` - USDA guidelines
- `search_food_recalls` - USDA recalls
- `get_commodity_prices` - Commodity prices
- `search_agricultural_census` - Census data
- `get_soil_survey_data` - Soil surveys

### Example Usage
```python
from tools.usda_mcp_tool import USDAMCPTool

# Load configuration
config = load_json('config/usda_mcp_tool.json')

# Initialize tool
usda_tool = USDAMCPTool(config)

# Search for foods
result = usda_tool.handle_tool_call('search_foods', {
    'query': 'apple',
    'data_type': 'Foundation'
})

# Get detailed nutrition
nutrition = usda_tool.handle_tool_call('get_food_details', {
    'fdc_id': result['foods'][0]['fdc_id']
})
```

---

## 3. FDA Configuration (fda_mcp_tool.json)

### Setup Instructions

**Step 1: Get API Key (Optional)**
- Visit: https://open.fda.gov/apis/authentication/
- Free tier: 240 requests/minute, 120,000/day
- No key needed for basic usage

**Step 2: Configure JSON**
```json
{
  "api_key": "",           // Leave blank or add your key
  "max_hits": 200,
  "max_hit_interval": 60
}
```

### Available Methods (14 total)
- `search_drugs` - Search drug database
- `get_drug_label` - Drug label info
- `get_drug_adverse_events` - Adverse reactions
- `search_medical_devices` - Device search
- `get_device_recalls` - Device recalls
- `get_device_adverse_events` - Device events
- `search_food_recalls` - Food recalls
- `get_food_enforcement` - Enforcement actions
- `search_ndc_directory` - NDC lookup
- `get_drug_approvals` - Drug approvals
- `search_clinical_trials` - Clinical trials
- `get_generic_drugs` - Generic equivalents
- `search_510k_devices` - 510(k) clearances
- `get_drug_shortages` - Drug shortages

### Example Usage
```python
from tools.fda_mcp_tool import FDAMCPTool

# Load configuration
config = load_json('config/fda_mcp_tool.json')

# Initialize tool
fda_tool = FDAMCPTool(config)

# Search for drug
result = fda_tool.handle_tool_call('search_drugs', {
    'query': 'ibuprofen',
    'limit': 5
})

# Get drug label
label = fda_tool.handle_tool_call('get_drug_label', {
    'drug_name': 'Advil'
})

# Check adverse events
events = fda_tool.handle_tool_call('get_drug_adverse_events', {
    'drug_name': 'Advil'
})
```

---

## Configuration Helper Function

```python
import json

def load_json(filepath):
    """Load JSON configuration file"""
    with open(filepath, 'r') as f:
        return json.load(f)

def initialize_all_tools():
    """Initialize all government data tools"""
    tools = {}
    
    # HHS Tool
    hhs_config = load_json('config/hhs_mcp_tool.json')
    tools['hhs'] = HHSMCPTool(hhs_config)
    
    # USDA Tool
    usda_config = load_json('config/usda_mcp_tool.json')
    tools['usda'] = USDAMCPTool(usda_config)
    
    # FDA Tool
    fda_config = load_json('config/fda_mcp_tool.json')
    tools['fda'] = FDAMCPTool(fda_config)
    
    return tools

# Usage
tools = initialize_all_tools()
hospitals = tools['hhs'].handle_tool_call('search_hospitals', {...})
foods = tools['usda'].handle_tool_call('search_foods', {...})
drugs = tools['fda'].handle_tool_call('search_drugs', {...})
```

---

## Rate Limiting Configuration

Each tool has built-in rate limiting configured in the JSON files:

```json
{
  "max_hits": 200,        // Maximum requests
  "max_hit_interval": 60  // Time window in seconds
}
```

This means:
- **200 requests per 60 seconds** (per tool)
- Exceeding this triggers rate limit error
- Adjust based on your API key limits

### Recommended Settings

**Development/Testing:**
```json
{
  "max_hits": 50,
  "max_hit_interval": 60
}
```

**Production (with API key):**
```json
{
  "max_hits": 1000,
  "max_hit_interval": 60
}
```

---

## Environment Variables (Recommended)

Instead of hardcoding API keys in JSON, use environment variables:

**Step 1: Create .env file**
```bash
HHS_API_KEY=your_hhs_key_here
USDA_API_KEY=your_usda_key_here
FDA_API_KEY=your_fda_key_here
```

**Step 2: Load in Python**
```python
import os
from dotenv import load_dotenv

load_dotenv()

# Update config with environment variables
config['api_key'] = os.getenv('USDA_API_KEY', 'DEMO_KEY')
```

**Step 3: Update JSON files**
```json
{
  "api_key": "${USDA_API_KEY}",  // Reference environment variable
  ...
}
```

---

## Validation Script

```python
def validate_config(config_path, required_fields):
    """Validate JSON configuration"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Check required fields
        for field in required_fields:
            if field not in config:
                print(f"❌ Missing required field: {field}")
                return False
        
        # Check rate limiting
        if config['max_hits'] < 1:
            print("❌ max_hits must be positive")
            return False
        
        if config['max_hit_interval'] < 1:
            print("❌ max_hit_interval must be positive")
            return False
        
        print(f"✅ {config_path} is valid")
        return True
    
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return False
    except FileNotFoundError:
        print(f"❌ File not found: {config_path}")
        return False

# Validate all configs
required = ['name', 'module', 'max_hits', 'max_hit_interval', 'api_key']

validate_config('config/hhs_mcp_tool.json', required)
validate_config('config/usda_mcp_tool.json', required)
validate_config('config/fda_mcp_tool.json', required)
```

---

## Quick Reference Table

| Tool | API Key Required | Rate Limit (No Key) | Rate Limit (With Key) | Best For |
|------|------------------|---------------------|----------------------|----------|
| **HHS** | No | Unlimited | Higher limits | Healthcare data, hospitals, Medicare |
| **USDA** | Yes | 30/min | 1000/hour | Nutrition, agriculture, food data |
| **FDA** | No | 240/min | 240/min | Drug safety, recalls, medical devices |

---

## Troubleshooting

### Common Issues

**1. "API key is invalid"**
- Verify key in JSON config
- Check key hasn't expired
- Ensure correct API for each tool

**2. "Rate limit exceeded"**
- Reduce `max_hits` in JSON
- Add delays between requests
- Get API key for higher limits

**3. "Module not found"**
- Check `module` path in JSON
- Ensure Python files are in correct location
- Verify import statements

**4. "Connection timeout"**
- Check internet connection
- Verify `base_url` is correct
- Try increasing timeout in code

---

## Next Steps

1. ✅ Copy the three JSON files to your `config/` directory
2. ✅ Update API keys (at minimum, get USDA key)
3. ✅ Run validation script
4. ✅ Test each tool with simple queries
5. ✅ Adjust rate limits based on usage
6. ✅ Set up environment variables for production

---

## Support

- **HHS**: https://healthdata.gov/
- **USDA**: https://fdc.nal.usda.gov/api-guide.html
- **FDA**: https://open.fda.gov/

---

© 2025 - 2030 Ashutosh Sinha. All rights reserved.