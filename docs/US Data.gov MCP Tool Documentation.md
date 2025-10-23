# US Data.gov MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The US Data.gov MCP Tool provides access to the comprehensive US Government open data catalog through data.gov's CKAN API. Search, retrieve, and analyze datasets from federal, state, and local government agencies covering topics including health, education, climate, finance, and more.

## Configuration
- No API key required for basic access
- Uses data.gov CKAN API v3
- Rate limited: 100 requests per 10-second window
- Access to 200,000+ government datasets
- Real-time data updates

## Available Methods

### Dataset Search

#### 1. search_datasets
Search US government datasets on data.gov.

**Parameters:**
- `query`: Search query for datasets (required)
- `rows` (default: 10): Number of results to return (1-1000)
- `start` (default: 0): Starting position for pagination
- `sort` (default: 'score desc'): Sort field (score, metadata_modified, views_recent)

**Returns:**
- Search query used
- Total count of matching datasets
- Number of results returned
- Array of datasets with:
  - ID, name, title, description
  - Organization name and ID
  - Creation and modification dates
  - Author and maintainer
  - License information
  - Tags and resource count
  - Direct URL to dataset page

#### 2. get_dataset
Get detailed information about a specific dataset.

**Parameters:**
- `dataset_id`: Dataset ID or name (required)

**Returns:**
- Complete dataset information
- Organization details
- Author and maintainer contacts
- License information
- Tags and groups
- All resources (files, APIs) with:
  - Name, description, format
  - URL, size, creation date
- Direct access URL

#### 3. get_dataset_resources
Get all resources (files, APIs) for a dataset.

**Parameters:**
- `dataset_id`: Dataset ID or name (required)

**Returns:**
- Dataset identification
- Total resource count
- Detailed resource information:
  - ID, name, description
  - Format and MIME type
  - URL for download/access
  - File size and hash
  - Creation and modification dates

### Organization/Agency Methods

#### 4. list_organizations
List all US government organizations/agencies.

**Parameters:**
- `all_fields` (default: false): Return all fields for organizations
- `limit` (default: 100): Number of organizations to return

**Returns:**
- Total organization count
- Organizations with:
  - ID, name, title
  - Description
  - Image/logo URL
  - Dataset count
  - Creation date

#### 5. get_organization
Get information about a specific organization/agency.

**Parameters:**
- `org_id`: Organization ID or name (required)
- `include_datasets` (default: false): Include datasets from this organization

**Returns:**
- Organization details
- Package/dataset count
- Approval status
- Optional: List of all datasets

#### 6. search_by_organization
Search datasets by organization/agency.

**Parameters:**
- `org_name`: Organization name or ID (required)
- `rows` (default: 10): Number of results

**Returns:**
- Organization identifier
- Total matching datasets
- Array of datasets

### Group/Category Methods

#### 7. list_groups
List all dataset groups/categories.

**Parameters:**
- `all_fields` (default: false): Return all fields

**Returns:**
- Total group count
- Groups/categories with:
  - ID, name, title
  - Description
  - Dataset count

#### 8. get_group
Get information about a specific group/category.

**Parameters:**
- `group_id`: Group ID or name (required)

**Returns:**
- Group details
- Description
- Image URL
- Dataset count
- Creation date

### Specialized Search

#### 9. get_recent_datasets
Get recently updated datasets.

**Parameters:**
- `rows` (default: 10): Number of datasets to return

**Returns:**
- Count of datasets
- Datasets sorted by modification date

#### 10. get_popular_datasets
Get most popular/viewed datasets.

**Parameters:**
- `rows` (default: 10): Number of datasets to return

**Returns:**
- Count of datasets
- Datasets sorted by recent views

#### 11. search_by_tag
Search datasets by tag.

**Parameters:**
- `tag`: Tag to search for (required)
- `rows` (default: 10): Number of results

**Returns:**
- Tag searched
- Total matching count
- Array of datasets

#### 12. search_by_format
Search datasets by file format (CSV, JSON, XML, etc.).

**Parameters:**
- `format`: File format - CSV, JSON, XML, PDF, etc. (required)
- `rows` (default: 10): Number of results

**Returns:**
- Format searched
- Total matching count
- Array of datasets

#### 13. search_by_date_range
Search datasets modified within a date range.

**Parameters:**
- `start_date`: Start date in YYYY-MM-DD format (required)
- `end_date`: End date in YYYY-MM-DD format (required)
- `rows` (default: 10): Number of results

**Returns:**
- Date range used
- Total matching count
- Datasets sorted by modification date

#### 14. advanced_search
Advanced search with multiple filters.

**Parameters:**
- `query`: Search query (optional)
- `organization`: Filter by organization (optional)
- `tags`: Array of tags to filter by (optional)
- `format`: Filter by format (optional)
- `rows` (default: 10): Number of results

**Returns:**
- Query and filters used
- Total matching count
- Array of filtered datasets

### Metadata and Statistics

#### 15. get_dataset_metadata
Get comprehensive metadata for a dataset.

**Parameters:**
- `dataset_id`: Dataset ID or name (required)

**Returns:**
- Basic info (ID, name, title, type, state)
- Content (description, URL)
- Ownership (author, maintainer, organization)
- Licensing (license ID, title, URL)
- Temporal (creation/modification dates)
- Classification (tags, groups)
- Resources summary (count, formats)

#### 16. list_tags
List all available tags.

**Parameters:**
- `limit` (default: 100): Number of tags to return

**Returns:**
- Total tag count
- Tags with ID, name, display name

#### 17. get_dataset_statistics
Get statistics about data.gov datasets.

**Parameters:** None

**Returns:**
- Total dataset count
- Total organizations
- Total groups
- Data source and API version
- Current timestamp

## Data Format Examples

### Search Datasets Response
```json
{
  "query": "climate change",
  "count": 5420,
  "results_returned": 10,
  "datasets": [
    {
      "id": "abc123-def456-ghi789",
      "name": "climate-data-records",
      "title": "Climate Data Records",
      "notes": "Comprehensive climate data from NOAA...",
      "organization": "National Oceanic and Atmospheric Administration",
      "organization_id": "noaa-gov",
      "metadata_created": "2020-01-15T10:30:00",
      "metadata_modified": "2024-12-01T14:20:00",
      "author": "NOAA Climate Program Office",
      "maintainer": "Data Manager",
      "license_title": "Creative Commons CCZero",
      "tags": ["climate", "temperature", "precipitation", "weather"],
      "num_resources": 15,
      "num_tags": 8,
      "url": "https://catalog.data.gov/dataset/climate-data-records"
    }
  ]
}
```

### Get Dataset Response
```json
{
  "id": "abc123-def456-ghi789",
  "name": "climate-data-records",
  "title": "Climate Data Records",
  "notes": "Full description of the climate dataset...",
  "organization": {
    "title": "National Oceanic and Atmospheric Administration",
    "name": "noaa-gov",
    "description": "NOAA's mission is to understand and predict..."
  },
  "author": "NOAA Climate Program Office",
  "author_email": "climate.data@noaa.gov",
  "maintainer": "Data Manager",
  "maintainer_email": "data.manager@noaa.gov",
  "license_title": "Creative Commons CCZero",
  "license_url": "http://www.opendefinition.org/licenses/cc-zero",
  "metadata_created": "2020-01-15T10:30:00",
  "metadata_modified": "2024-12-01T14:20:00",
  "tags": ["climate", "temperature", "precipitation"],
  "groups": ["climate5434", "ecosystems9856"],
  "resources": [
    {
      "id": "res-001",
      "name": "Monthly Temperature Data",
      "description": "Monthly average temperatures 1950-2024",
      "format": "CSV",
      "url": "https://downloads.data.gov/climate/temperature.csv",
      "created": "2020-01-15T10:30:00",
      "size": "5242880"
    }
  ],
  "num_resources": 15,
  "url": "https://catalog.data.gov/dataset/climate-data-records"
}
```

### List Organizations Response
```json
{
  "count": 156,
  "organizations": [
    {
      "id": "org-001",
      "name": "noaa-gov",
      "title": "National Oceanic and Atmospheric Administration",
      "description": "NOAA's mission is to understand and predict...",
      "image_url": "https://www.noaa.gov/logo.png",
      "package_count": 542,
      "created": "2015-03-10T08:00:00"
    },
    {
      "id": "org-002",
      "name": "nasa-gov",
      "title": "National Aeronautics and Space Administration",
      "description": "NASA explores the unknown in air and space...",
      "image_url": "https://www.nasa.gov/logo.png",
      "package_count": 1234,
      "created": "2015-03-10T08:00:00"
    }
  ]
}
```

### Dataset Statistics Response
```json
{
  "total_datasets": 287654,
  "total_organizations": 156,
  "total_groups": 45,
  "data_source": "data.gov",
  "api_version": "3",
  "timestamp": "2025-01-15T14:30:00.123456"
}
```

## Example Usage

### Basic Search Examples

```python
# Example 1: Search for COVID-19 datasets
result = us_data_tool.handle_tool_call('search_datasets', {
    'query': 'COVID-19',
    'rows': 20,
    'sort': 'metadata_modified desc'
})

print(f"Found {result['count']} COVID-19 datasets")
for dataset in result['datasets']:
    print(f"  - {dataset['title']} ({dataset['organization']})")

# Example 2: Get specific dataset details
result = us_data_tool.handle_tool_call('get_dataset', {
    'dataset_id': 'climate-data-records'
})

print(f"Dataset: {result['title']}")
print(f"Organization: {result['organization']['title']}")
print(f"Resources: {result['num_resources']}")
print(f"License: {result['license_title']}")

# Example 3: Get dataset resources
result = us_data_tool.handle_tool_call('get_dataset_resources', {
    'dataset_id': 'climate-data-records'
})

print(f"Total resources: {result['total_resources']}")
for resource in result['resources']:
    print(f"  - {resource['name']} ({resource['format']})")
    print(f"    URL: {resource['url']}")
    print(f"    Size: {resource['size']} bytes")
```

### Organization Examples

```python
# Example 4: List all federal agencies
result = us_data_tool.handle_tool_call('list_organizations', {
    'all_fields': True,
    'limit': 50
})

print(f"Total organizations: {result['count']}")
for org in result['organizations'][:10]:
    print(f"  - {org['title']}: {org['package_count']} datasets")

# Example 5: Get NASA datasets
result = us_data_tool.handle_tool_call('search_by_organization', {
    'org_name': 'nasa-gov',
    'rows': 10
})

print(f"NASA has {result['count']} total datasets")
for dataset in result['datasets']:
    print(f"  - {dataset['title']}")

# Example 6: Get organization details with datasets
result = us_data_tool.handle_tool_call('get_organization', {
    'org_id': 'noaa-gov',
    'include_datasets': True
})

print(f"Organization: {result['title']}")
print(f"Description: {result['description']}")
print(f"Total datasets: {result['package_count']}")
```

### Specialized Search Examples

```python
# Example 7: Get recently updated datasets
result = us_data_tool.handle_tool_call('get_recent_datasets', {
    'rows': 15
})

print("Recently updated datasets:")
for dataset in result['datasets']:
    print(f"  - {dataset['title']}")
    print(f"    Modified: {dataset['metadata_modified']}")

# Example 8: Find popular datasets
result = us_data_tool.handle_tool_call('get_popular_datasets', {
    'rows': 10
})

print("Most popular datasets:")
for i, dataset in enumerate(result['datasets'], 1):
    print(f"  {i}. {dataset['title']} - {dataset['organization']}")

# Example 9: Search by tag
result = us_data_tool.handle_tool_call('search_by_tag', {
    'tag': 'education',
    'rows': 20
})

print(f"Found {result['count']} education datasets")

# Example 10: Search by format
result = us_data_tool.handle_tool_call('search_by_format', {
    'format': 'CSV',
    'rows': 25
})

print(f"Found {result['count']} datasets with CSV files")
for dataset in result['datasets'][:5]:
    print(f"  - {dataset['title']}")
```

### Advanced Search Examples

```python
# Example 11: Search with date range
result = us_data_tool.handle_tool_call('search_by_date_range', {
    'start_date': '2024-01-01',
    'end_date': '2024-12-31',
    'rows': 50
})

print(f"Datasets updated in 2024: {result['count']}")

# Example 12: Advanced multi-filter search
result = us_data_tool.handle_tool_call('advanced_search', {
    'query': 'climate',
    'organization': 'noaa-gov',
    'tags': ['temperature', 'precipitation'],
    'format': 'JSON',
    'rows': 10
})

print(f"Found {result['count']} matching datasets")
print(f"Filters: {result['filters']}")

# Example 13: Get comprehensive metadata
result = us_data_tool.handle_tool_call('get_dataset_metadata', {
    'dataset_id': 'climate-data-records'
})

print("Basic Info:", result['basic_info'])
print("Ownership:", result['ownership'])
print("Licensing:", result['licensing'])
print("Classification:", result['classification'])
```

### Category and Tag Examples

```python
# Example 14: List all categories
result = us_data_tool.handle_tool_call('list_groups', {
    'all_fields': True
})

print(f"Total categories: {result['count']}")
for group in result['groups'][:10]:
    print(f"  - {group['title']}: {group['package_count']} datasets")

# Example 15: Get category details
result = us_data_tool.handle_tool_call('get_group', {
    'group_id': 'climate5434'
})

print(f"Category: {result['title']}")
print(f"Description: {result['description']}")

# Example 16: List popular tags
result = us_data_tool.handle_tool_call('list_tags', {
    'limit': 50
})

print(f"Total tags: {result['count']}")
for tag in result['tags'][:20]:
    print(f"  - {tag}")
```

### Statistics and Analytics Examples

```python
# Example 17: Get overall statistics
result = us_data_tool.handle_tool_call('get_dataset_statistics', {})

print(f"Total datasets on data.gov: {result['total_datasets']:,}")
print(f"Total organizations: {result['total_organizations']}")
print(f"Total categories: {result['total_groups']}")

# Example 18: Analyze organization dataset counts
orgs_result = us_data_tool.handle_tool_call('list_organizations', {
    'all_fields': True,
    'limit': 200
})

orgs_sorted = sorted(orgs_result['organizations'], 
                     key=lambda x: x['package_count'], 
                     reverse=True)

print("Top 10 organizations by dataset count:")
for i, org in enumerate(orgs_sorted[:10], 1):
    print(f"  {i}. {org['title']}: {org['package_count']:,} datasets")

# Example 19: Find datasets by multiple formats
formats = ['CSV', 'JSON', 'XML', 'API']
format_counts = {}

for fmt in formats:
    result = us_data_tool.handle_tool_call('search_by_format', {
        'format': fmt,
        'rows': 1
    })
    format_counts[fmt] = result['count']

print("Datasets by format:")
for fmt, count in sorted(format_counts.items(), key=lambda x: x[1], reverse=True):
    print(f"  {fmt}: {count:,}")
```

### Real-World Use Cases

```python
# Example 20: Health Data Research
# Find COVID-19 testing data from CDC
result = us_data_tool.handle_tool_call('advanced_search', {
    'query': 'COVID-19 testing',
    'organization': 'cdc-gov',
    'tags': ['covid-19', 'testing'],
    'format': 'CSV'
})

print("CDC COVID-19 Testing Datasets:")
for dataset in result['datasets']:
    print(f"\n{dataset['title']}")
    print(f"  Updated: {dataset['metadata_modified']}")
    print(f"  URL: {dataset['url']}")

# Example 21: Climate Change Analysis
# Find NOAA climate datasets with APIs
climate_search = us_data_tool.handle_tool_call('search_datasets', {
    'query': 'temperature precipitation climate',
    'rows': 50
})

api_datasets = []
for dataset_info in climate_search['datasets']:
    if dataset_info['organization_id'] == 'noaa-gov':
        resources = us_data_tool.handle_tool_call('get_dataset_resources', {
            'dataset_id': dataset_info['id']
        })
        
        has_api = any(r['format'].upper() in ['API', 'JSON'] 
                      for r in resources['resources'])
        if has_api:
            api_datasets.append(dataset_info['title'])

print(f"Found {len(api_datasets)} NOAA climate datasets with APIs")

# Example 22: Education Data Portal
# Build education data catalog
edu_result = us_data_tool.handle_tool_call('search_by_tag', {
    'tag': 'education',
    'rows': 100
})

catalog = {}
for dataset in edu_result['datasets']:
    org = dataset['organization']
    if org not in catalog:
        catalog[org] = []
    catalog[org].append({
        'title': dataset['title'],
        'url': dataset['url'],
        'resources': dataset['num_resources']
    })

print("Education Data Catalog by Organization:")
for org, datasets in sorted(catalog.items()):
    print(f"\n{org} ({len(datasets)} datasets):")
    for ds in datasets[:3]:
        print(f"  - {ds['title']} ({ds['resources']} resources)")

# Example 23: Economic Indicators Dashboard
# Gather economic data from multiple agencies
economic_terms = ['employment', 'GDP', 'inflation', 'wages']
economic_data = {}

for term in economic_terms:
    result = us_data_tool.handle_tool_call('search_datasets', {
        'query': term,
        'rows': 5,
        'sort': 'metadata_modified desc'
    })
    economic_data[term] = result['datasets']

print("Economic Indicators Dashboard:")
for indicator, datasets in economic_data.items():
    print(f"\n{indicator.upper()}:")
    for ds in datasets:
        print(f"  - {ds['title']} ({ds['organization']})")

# Example 24: Geospatial Data Discovery
# Find mapping datasets with specific formats
geo_formats = ['GeoJSON', 'KML', 'Shapefile']
geo_datasets = []

for fmt in geo_formats:
    result = us_data_tool.handle_tool_call('search_by_format', {
        'format': fmt,
        'rows': 10
    })
    geo_datasets.extend(result['datasets'])

print(f"Found {len(geo_datasets)} geospatial datasets")
for ds in geo_datasets[:10]:
    print(f"  - {ds['title']}")
```

## Popular Dataset Categories

### Health & Medicine
- COVID-19 data and statistics
- Medicare and Medicaid data
- Disease surveillance
- Hospital quality metrics
- Drug safety reports

### Climate & Environment
- Weather observations
- Climate models and projections
- Air and water quality
- Endangered species
- Environmental regulations

### Education
- School performance data
- College scorecard
- Student demographics
- Education spending
- Test scores

### Economy & Finance
- Economic indicators
- Employment statistics
- Federal spending
- Tax data
- International trade

### Public Safety
- Crime statistics
- Emergency response data
- Traffic accidents
- Fire incidents
- Consumer complaints

### Transportation
- Flight delays
- Traffic data
- Transit statistics
- Highway safety
- Vehicle recalls

## Best Practices

### Search Optimization

```python
# Use specific queries for better results
result = us_data_tool.handle_tool_call('search_datasets', {
    'query': 'unemployment rate monthly statistics',  # Specific
    'rows': 10
})

# Instead of
# 'query': 'jobs'  # Too broad
```

### Pagination for Large Results

```python
# Get results in batches
all_datasets = []
start = 0
batch_size = 100

while start < 500:  # Limit total results
    result = us_data_tool.handle_tool_call('search_datasets', {
        'query': 'climate',
        'rows': batch_size,
        'start': start
    })
    
    all_datasets.extend(result['datasets'])
    
    if len(result['datasets']) < batch_size:
        break  # No more results
    
    start += batch_size

print(f"Retrieved {len(all_datasets)} total datasets")
```

### Efficient Resource Discovery

```python
# First get dataset, then resources separately
dataset = us_data_tool.handle_tool_call('get_dataset', {
    'dataset_id': 'my-dataset'
})

if dataset['num_resources'] > 0:
    resources = us_data_tool.handle_tool_call('get_dataset_resources', {
        'dataset_id': 'my-dataset'
    })
    
    # Filter for CSV files
    csv_files = [r for r in resources['resources'] 
                 if r['format'].upper() == 'CSV']
```

### Advanced Filtering

```python
# Combine multiple search criteria
result = us_data_tool.handle_tool_call('advanced_search', {
    'query': 'air quality',
    'organization': 'epa-gov',
    'tags': ['pollution', 'air'],
    'format': 'CSV',
    'rows': 50
})

# Then filter results by date
recent_datasets = [
    ds for ds in result['datasets']
    if ds['metadata_modified'] >= '2024-01-01'
]
```

## Limitations

- **No API Key**: Basic access, but rate limits apply
- **Rate Limiting**: 100 requests per 10 seconds
- **Result Limits**: Maximum 1000 results per search
- **Data Freshness**: Varies by agency and dataset
- **No Write Access**: Read-only API (cannot create/modify datasets)
- **Resource Availability**: Some resources may have broken links
- **Metadata Quality**: Varies by publishing organization
- **Search Accuracy**: Depends on dataset tagging and descriptions

## Error Handling

```python
# Always check for errors
result = us_data_tool.handle_tool_call('search_datasets', {
    'query': 'health data'
})

if 'error' in result:
    print(f"Error: {result['error']}")
    if result.get('status') == 429:
        print("Rate limit exceeded - wait and retry")
else:
    # Process results
    print(f"Found {result['count']} datasets")
```

## Data Quality Tips

1. **Check Metadata Dates**: Prefer recently updated datasets
2. **Verify Resources**: Ensure download URLs are accessible
3. **Review Licenses**: Understand usage restrictions
4. **Contact Maintainers**: Use provided contact information for questions
5. **Check Organization**: Prefer primary source agencies
6. **Review Documentation**: Many datasets have detailed documentation

## API Performance

- **Average Response Time**: 200-500ms
- **Peak Hours**: Slower during business hours (EST)
- **Cache Results**: API results are cached for 5 minutes
- **Batch Operations**: Use advanced_search for complex queries
- **Connection Pooling**: Tool uses session pooling for efficiency


# US Data.gov MCP Tool

Access 200,000+ US Government open datasets through a comprehensive MCP tool interface.

## Quick Start

### Installation

1. **Place the files in your tools directory:**
   ```
   tools/
   ├── us_data_mcp_tool.py
   └── config/tools/
       └── us_data_mcp_tool.json
   ```

2. **Install dependencies:**
   ```bash
   pip install requests
   ```

3. **Restart your MCP server** to load the tool

### Basic Usage

```python
from tools.us_data_mcp_tool import USDataMCPTool

# Initialize tool
tool = USDataMCPTool()

# Search for datasets
result = tool.handle_tool_call('search_datasets', {
    'query': 'climate change',
    'rows': 10
})

print(f"Found {result['count']} datasets")
```

## Features

### 17 Powerful Tools

✅ **Dataset Search** - Search 200,000+ government datasets
✅ **Organization Lookup** - Find data by federal agency
✅ **Category Browsing** - Explore datasets by topic
✅ **Recent Updates** - Get newly updated datasets
✅ **Popular Datasets** - Find most-viewed data
✅ **Format Filtering** - Search by file type (CSV, JSON, etc.)
✅ **Advanced Search** - Multi-criteria filtering
✅ **Tag Search** - Find datasets by tags
✅ **Date Range** - Filter by update date
✅ **Statistics** - Get catalog metrics

### Key Capabilities

- **No API Key Required** - Free public access
- **Comprehensive Coverage** - Federal, state, and local data
- **Real-time Updates** - Live catalog access
- **Rich Metadata** - Detailed dataset information
- **Resource Discovery** - Find downloadable files and APIs
- **Organization Data** - 150+ government agencies

## Quick Examples

### Search for COVID-19 Data
```python
result = tool.handle_tool_call('search_datasets', {
    'query': 'COVID-19',
    'rows': 20
})
```

### Get NASA Datasets
```python
result = tool.handle_tool_call('search_by_organization', {
    'org_name': 'nasa-gov',
    'rows': 10
})
```

### Find Recent Climate Data
```python
result = tool.handle_tool_call('advanced_search', {
    'query': 'climate temperature',
    'organization': 'noaa-gov',
    'format': 'CSV',
    'rows': 10
})
```

### List All Agencies
```python
result = tool.handle_tool_call('list_organizations', {
    'all_fields': True,
    'limit': 100
})
```

## Popular Use Cases

### 🏥 Health Research
- COVID-19 statistics
- Medicare data
- Disease surveillance
- Hospital quality metrics

### 🌍 Climate Analysis
- Weather observations
- Climate models
- Air quality data
- Environmental regulations

### 📚 Education Studies
- School performance
- College data
- Test scores
- Education spending

### 💼 Economic Analysis
- Employment statistics
- GDP data
- Federal spending
- Trade data

### 🚔 Public Safety
- Crime statistics
- Emergency response
- Traffic accidents
- Safety recalls

## API Methods

### Search Methods
- `search_datasets` - General search
- `search_by_organization` - Agency-specific
- `search_by_tag` - Tag-based search
- `search_by_format` - File format search
- `search_by_date_range` - Date filtering
- `advanced_search` - Multi-criteria

### Dataset Methods
- `get_dataset` - Full dataset details
- `get_dataset_resources` - Files and APIs
- `get_dataset_metadata` - Comprehensive metadata
- `get_recent_datasets` - Recent updates
- `get_popular_datasets` - Most viewed

### Organization Methods
- `list_organizations` - All agencies
- `get_organization` - Agency details

### Category Methods
- `list_groups` - All categories
- `get_group` - Category details
- `list_tags` - All tags

### Statistics
- `get_dataset_statistics` - Catalog stats

## Configuration

**Rate Limiting:**
- 100 requests per 10 seconds
- Built-in rate limit protection

**Defaults:**
- Results per page: 10
- Max results: 1000 per query
- Timeout: 30 seconds

**Endpoints:**
- API Base: `https://catalog.data.gov/api/3`
- Web Portal: `https://catalog.data.gov`

## Response Format

All methods return JSON with:

```json
{
  "count": 1234,
  "datasets": [
    {
      "id": "...",
      "title": "...",
      "organization": "...",
      "url": "...",
      "tags": [...],
      "resources": [...]
    }
  ]
}
```

## Error Handling

```python
result = tool.handle_tool_call('search_datasets', {
    'query': 'health'
})

if 'error' in result:
    print(f"Error: {result['error']}")
    if result.get('status') == 429:
        print("Rate limit - wait 10 seconds")
else:
    # Process results
    for dataset in result['datasets']:
        print(dataset['title'])
```

## Data Coverage

### 200,000+ Datasets From:

**Major Agencies:**
- Department of Health and Human Services
- Department of Commerce (NOAA, Census)
- National Aeronautics and Space Administration
- Environmental Protection Agency
- Department of Education
- Department of Transportation
- Department of Energy
- Department of Agriculture
- And 140+ more agencies

**Topics:**
- Agriculture
- Climate & Weather
- Consumer Safety
- Economics & Finance
- Education
- Energy
- Environment
- Health
- Public Safety
- Science & Research
- Transportation

## Best Practices

### 1. Use Specific Queries
```python
# Good
'query': 'monthly unemployment statistics 2024'

# Too broad
'query': 'jobs'
```

### 2. Paginate Large Results
```python
start = 0
while start < 500:
    result = tool.handle_tool_call('search_datasets', {
        'query': 'climate',
        'rows': 100,
        'start': start
    })
    # Process results
    start += 100
```

### 3. Use Advanced Search
```python
result = tool.handle_tool_call('advanced_search', {
    'query': 'air quality',
    'organization': 'epa-gov',
    'tags': ['pollution'],
    'format': 'CSV'
})
```

### 4. Check Data Freshness
```python
for dataset in result['datasets']:
    if dataset['metadata_modified'] >= '2024-01-01':
        # Use recent data
        print(dataset['title'])
```

## Troubleshooting

### Rate Limit Exceeded
**Solution:** Wait 10 seconds before next request

### No Results Found
**Solutions:**
- Try broader search terms
- Remove filters
- Check spelling
- Use `advanced_search` with fewer filters

### Timeout Errors
**Solutions:**
- Reduce `rows` parameter
- Use more specific queries
- Retry with pagination

### Invalid Dataset ID
**Solution:** Use exact dataset name or ID from search results

## Resources

- **Documentation:** [Full Documentation](US%20Data.gov%20MCP%20Tool%20Documentation.md)
- **API Reference:** https://catalog.data.gov/dataset/api
- **Data Portal:** https://catalog.data.gov
- **GitHub Issues:** Report tool issues

## Performance

- **Average Response:** 200-500ms
- **Connection Pooling:** Enabled
- **Session Management:** Automatic
- **Cache:** 5-minute API cache



## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.

---

**Data Source**: data.gov - The home of the U.S. Government's open data
**API Documentation**: https://catalog.data.gov/dataset/api
**Last Updated**: January 2025
**Version**: 1.0.0