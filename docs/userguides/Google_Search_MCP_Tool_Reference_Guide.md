# Google Search MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technical Details](#technical-details)
4. [Authentication & API Keys](#authentication--api-keys)
5. [Tool Description](#tool-description)
6. [Usage Examples](#usage-examples)
7. [Schema Reference](#schema-reference)
8. [Limitations](#limitations)
9. [Error Handling](#error-handling)
10. [Performance Considerations](#performance-considerations)

---

## Overview

The Google Search MCP Tool provides programmatic access to Google's powerful search technology through the Google Custom Search JSON API. This tool enables web and image searches across the internet with advanced filtering, site-specific searches, and date restrictions.

### Key Features

- **Web Search**: Search across billions of web pages
- **Image Search**: Find images with specific criteria
- **Site-Specific Search**: Restrict searches to specific domains
- **Date Filtering**: Find recent content (past week, month, year)
- **Safe Search**: Control content filtering
- **Language Support**: Search in multiple languages
- **Pagination**: Navigate through result pages
- **Demo Mode**: Test without API credentials

### Search Capabilities

- General web search
- News and article discovery
- Academic and research content
- Site-specific searches (Wikipedia, GitHub, etc.)
- Image search with metadata
- Recent content filtering
- Multi-language searches

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
│                 GoogleSearchTool                         │
├──────────────────────────────────────────────────────────┤
│  • API URL: googleapis.com/customsearch/v1              │
│  • API Key Management                                    │
│  • Search Engine ID Configuration                        │
│  • Demo Mode (when no credentials)                       │
│  • Query Building and Parameter Handling                 │
│  • HTTP Client (urllib)                                  │
│  • JSON Response Parser                                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTPS API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│         Google Custom Search JSON API                    │
│         https://www.googleapis.com/customsearch/v1       │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── GoogleSearchTool
            │
            ├── execute() - Main search execution
            ├── _search() - API interaction
            ├── _get_demo_results() - Demo mode data
            ├── get_input_schema() - Input validation
            └── get_output_schema() - Output structure
```

### Component Descriptions

#### GoogleSearchTool
Main class providing:
- Google Custom Search API integration
- API key and Search Engine ID management
- Query parameter building and validation
- Safe search and filtering controls
- Demo mode for testing without credentials
- Web and image search support
- Result parsing and formatting
- Error handling and logging

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
- ✗ Web Crawling
- ✗ Database Queries
- ✗ File System Access
- ✗ Selenium/Browser Automation

### API Communication

The tool communicates with Google Custom Search API using standard REST calls:

```python
# Base URL
https://www.googleapis.com/customsearch/v1

# Request Format
GET ?key={API_KEY}&cx={SEARCH_ENGINE_ID}&q={QUERY}&num={COUNT}&start={START}

# Example
GET ?key=AIzaSyAbc123&cx=012345678901234567890&q=artificial+intelligence&num=10
```

### HTTP Request Details

**Required Parameters**:
- `key`: Google API key
- `cx`: Custom Search Engine ID
- `q`: Search query

**Optional Parameters**:
- `num`: Number of results (1-10, default: 10)
- `start`: Starting index for pagination
- `safe`: Safe search level (off, medium, high)
- `searchType`: Type (image for image search)
- `dateRestrict`: Time filter (d7, m3, y1)
- `lr`: Language restriction (lang_en, lang_es, etc.)

**Request Headers**:
```python
{
    'User-Agent': 'Python urllib',
    'Accept': 'application/json'
}
```

**Timeout**: Standard urllib timeout

### Response Parsing

The Google Custom Search API returns JSON:

```json
{
  "searchInformation": {
    "totalResults": "1234567890",
    "searchTime": 0.234567
  },
  "items": [
    {
      "title": "Page Title",
      "link": "https://example.com/page",
      "snippet": "Page description or excerpt...",
      "displayLink": "example.com"
    }
  ]
}
```

For image searches:
```json
{
  "items": [
    {
      "title": "Image Title",
      "link": "https://example.com/image.jpg",
      "image": {
        "thumbnailLink": "https://...",
        "contextLink": "https://...",
        "height": 1024,
        "width": 768
      }
    }
  ]
}
```

### Demo Mode

When API credentials are not configured:
- Automatically activates demo mode
- Returns synthetic search results
- Uses query in mock result generation
- Includes disclaimer in response
- Useful for testing and development

---

## Authentication & API Keys

### Google Custom Search API Setup

The Google Custom Search API requires **two credentials**:

1. **API Key** - Google Cloud API key
2. **Search Engine ID (CX)** - Custom Search Engine identifier

Both are **required** for production use. Free tier available with limitations.

### Step 1: Create Google Cloud Project

1. Visit [Google Cloud Console](https://console.cloud.google.com)
2. Create new project or select existing
3. Navigate to "APIs & Services" → "Library"
4. Search for "Custom Search API"
5. Click "Enable"

### Step 2: Create API Key

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "API Key"
3. Copy the API key (starts with `AIza...`)
4. **Recommended**: Restrict key to Custom Search API only
5. **Recommended**: Add application restrictions (IP, HTTP referrer)

**API Key Example**: `AIzaSyAbc123def456ghi789jkl012mno345pqr678`

### Step 3: Create Custom Search Engine

1. Visit [Programmable Search Engine](https://programmablesearchengine.google.com)
2. Click "Add" to create new search engine
3. Configure settings:
   - **Sites to search**: Leave empty for entire web, or specify domains
   - **Language**: Select preferred language
   - **Name**: Give your search engine a name
4. Click "Create"
5. Go to "Setup" → Copy the "Search engine ID"

**Search Engine ID Example**: `012345678901234567890:abcdefghijk`

### Step 4: Configure Tool

```python
from tools.impl.google_search_tool_refactored import GoogleSearchTool

# With credentials (production)
config = {
    'api_key': 'AIzaSyAbc123def456ghi789jkl012mno345pqr678',
    'search_engine_id': '012345678901234567890:abcdefghijk'
}
tool = GoogleSearchTool(config)

# Demo mode (no credentials)
tool = GoogleSearchTool()  # Automatically uses demo mode
```

### Environment Variables (Recommended)

```python
import os

config = {
    'api_key': os.environ.get('GOOGLE_API_KEY'),
    'search_engine_id': os.environ.get('GOOGLE_SEARCH_ENGINE_ID')
}
tool = GoogleSearchTool(config)
```

### Security Best Practices

**API Key Security**:
- Never commit API keys to version control
- Store in environment variables or secure vaults
- Rotate keys periodically
- Use API key restrictions (IP, referrer)
- Monitor usage in Google Cloud Console

**Search Engine Configuration**:
- Restrict to specific sites if needed
- Enable/disable image search as required
- Configure safe search defaults
- Monitor query patterns

### Pricing & Quotas

**Free Tier**:
- 100 queries per day
- No credit card required
- Sufficient for development and testing

**Paid Tier**:
- $5 per 1,000 queries
- Up to 10,000 queries per day
- Automatic billing beyond free tier

**Rate Limits**:
- 100 queries per 100 seconds per user
- Recommended: 100 requests per hour per tool

### Demo Mode Features

Demo mode activates when credentials are missing:
- ✓ Returns realistic mock results
- ✓ Tests tool functionality
- ✓ No API costs
- ✓ Development and testing
- ✗ Real search results
- ✗ Actual URLs
- ✗ Real-time data

---

## Tool Description

### google_search

**Purpose**: Search the web using Google's powerful search technology

**Type**: Single tool with multiple search modes

**Input Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| query | string | Yes | - | Search query text |
| num_results | integer | No | 10 | Results to return (1-10) |
| start | integer | No | 1 | Starting index (pagination) |
| safe_search | string | No | medium | Content filtering (off, medium, high) |
| search_type | string | No | web | Search type (web, image) |
| site | string | No | - | Restrict to specific domain |
| date_restrict | string | No | - | Date filter (d7, m3, y1) |
| language | string | No | en | Result language (en, es, fr, de, ja) |

**Output Structure**:
```json
{
  "query": "search query",
  "totalResults": "1234567890",
  "searchTime": 0.234567,
  "count": 10,
  "results": [
    {
      "title": "Page Title",
      "link": "https://example.com",
      "snippet": "Description...",
      "displayLink": "example.com"
    }
  ]
}
```

### Search Types

#### 1. Web Search
Default search mode for web pages:
```python
result = tool.execute({
    'query': 'artificial intelligence',
    'num_results': 10
})
```

#### 2. Image Search
Search for images:
```python
result = tool.execute({
    'query': 'golden gate bridge',
    'search_type': 'image',
    'num_results': 5
})
```

#### 3. Site-Specific Search
Search within a specific domain:
```python
result = tool.execute({
    'query': 'machine learning',
    'site': 'wikipedia.org'
})
```

#### 4. Recent Content Search
Find recent content:
```python
result = tool.execute({
    'query': 'climate change news',
    'date_restrict': 'd7',  # Past 7 days
    'num_results': 5
})
```

### Safe Search Levels

| Level | Description | Use Case |
|-------|-------------|----------|
| off | No filtering | Research, unrestricted content |
| medium | Moderate filtering (default) | General use |
| high | Strict filtering | Educational, family-friendly |

### Date Restrict Options

| Format | Description | Example |
|--------|-------------|---------|
| dN | Past N days | d7 (past week) |
| wN | Past N weeks | w2 (past 2 weeks) |
| mN | Past N months | m3 (past 3 months) |
| yN | Past N years | y1 (past year) |

### Language Codes

| Code | Language | Code | Language |
|------|----------|------|----------|
| en | English | es | Spanish |
| fr | French | de | German |
| ja | Japanese | zh | Chinese |
| pt | Portuguese | ru | Russian |
| it | Italian | ko | Korean |

---

## Usage Examples

### Example 1: Basic Web Search

```python
from tools.impl.google_search_tool_refactored import GoogleSearchTool

# Configure with your credentials
config = {
    'api_key': 'your_api_key_here',
    'search_engine_id': 'your_search_engine_id_here'
}
tool = GoogleSearchTool(config)

# Perform search
result = tool.execute({
    'query': 'climate change impacts 2025'
})

print(f"Found {result['totalResults']} results in {result['searchTime']}s")
print(f"Returning top {result['count']} results:\n")

for i, item in enumerate(result['results'], 1):
    print(f"{i}. {item['title']}")
    print(f"   {item['link']}")
    print(f"   {item['snippet']}\n")
```

### Example 2: Site-Specific Academic Search

```python
# Search Wikipedia for information
result = tool.execute({
    'query': 'quantum computing',
    'site': 'wikipedia.org',
    'num_results': 5
})

print("Wikipedia Results:")
for item in result['results']:
    print(f"- {item['title']}")
    print(f"  {item['link']}\n")
```

### Example 3: Recent News Search

```python
# Find news from the past week
result = tool.execute({
    'query': 'artificial intelligence breakthroughs',
    'date_restrict': 'd7',  # Past 7 days
    'num_results': 10
})

print(f"Recent news from past 7 days:")
for item in result['results']:
    print(f"• {item['title']}")
    print(f"  Source: {item['displayLink']}")
    print(f"  {item['snippet'][:100]}...\n")
```

### Example 4: Image Search

```python
# Search for images
result = tool.execute({
    'query': 'sunset beach photography',
    'search_type': 'image',
    'num_results': 5,
    'safe_search': 'high'
})

print("Image Results:")
for item in result['results']:
    print(f"Title: {item['title']}")
    print(f"Image URL: {item['link']}")
    
    if 'image' in item:
        print(f"Thumbnail: {item['image']['thumbnailLink']}")
        print(f"Size: {item['image']['width']}x{item['image']['height']}")
    print()
```

### Example 5: Multilingual Search

```python
# Search in Spanish
result = tool.execute({
    'query': 'inteligencia artificial',
    'language': 'es',
    'num_results': 5
})

print("Resultados en español:")
for item in result['results']:
    print(f"• {item['title']}")
    print(f"  {item['link']}\n")
```

### Example 6: Pagination

```python
# Search with pagination
def search_multiple_pages(query, pages=3):
    """Search multiple pages of results"""
    all_results = []
    
    for page in range(pages):
        start_index = (page * 10) + 1
        
        result = tool.execute({
            'query': query,
            'num_results': 10,
            'start': start_index
        })
        
        all_results.extend(result['results'])
        print(f"Page {page + 1}: Retrieved {len(result['results'])} results")
    
    return all_results

# Get 30 results across 3 pages
results = search_multiple_pages('machine learning tutorials', pages=3)
print(f"\nTotal results retrieved: {len(results)}")
```

### Example 7: Safe Search for Education

```python
# Family-friendly search with strict filtering
result = tool.execute({
    'query': 'science experiments for kids',
    'safe_search': 'high',
    'site': 'edu',  # Educational domains
    'num_results': 10
})

print("Educational Resources (Safe Search: High):")
for item in result['results']:
    print(f"✓ {item['title']}")
    print(f"  {item['displayLink']}")
    print()
```

### Example 8: Research with Multiple Sites

```python
# Search across multiple academic sources
sites = ['wikipedia.org', 'scholar.google.com', 'arxiv.org']
query = 'neural networks deep learning'

for site in sites:
    result = tool.execute({
        'query': query,
        'site': site,
        'num_results': 3
    })
    
    print(f"\nResults from {site}:")
    for item in result['results']:
        print(f"- {item['title']}")
        print(f"  {item['link']}")
```

### Example 9: Demo Mode Testing

```python
# Test without API credentials
demo_tool = GoogleSearchTool()  # No config = demo mode

result = demo_tool.execute({
    'query': 'test search',
    'num_results': 3
})

print("Demo Mode Results:")
for item in result['results']:
    print(f"• {item['title']}")
    print(f"  {item['snippet']}")

if 'note' in result:
    print(f"\nNote: {result['note']}")
```

### Example 10: Error Handling

```python
def safe_search(query, **kwargs):
    """Search with error handling"""
    try:
        result = tool.execute({
            'query': query,
            **kwargs
        })
        return result
        
    except ValueError as e:
        error_msg = str(e)
        
        if 'quota exceeded' in error_msg.lower():
            print("❌ Daily quota exceeded. Try again tomorrow.")
        elif 'invalid' in error_msg.lower():
            print("❌ Invalid API credentials.")
        else:
            print(f"❌ Search error: {error_msg}")
        
        return None

# Usage
result = safe_search('python programming', num_results=5)
if result:
    print(f"Found {result['count']} results")
```

---

## Schema Reference

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query"
    },
    "num_results": {
      "type": "integer",
      "description": "Number of results (1-10)",
      "default": 10,
      "minimum": 1,
      "maximum": 10
    },
    "start": {
      "type": "integer",
      "description": "Starting index for pagination",
      "default": 1,
      "minimum": 1
    },
    "safe_search": {
      "type": "string",
      "description": "Safe search level",
      "enum": ["off", "medium", "high"],
      "default": "medium"
    },
    "search_type": {
      "type": "string",
      "description": "Type of search",
      "enum": ["web", "image"],
      "default": "web"
    },
    "site": {
      "type": "string",
      "description": "Restrict to specific site"
    },
    "date_restrict": {
      "type": "string",
      "description": "Date filter (d7, m3, y1)"
    },
    "language": {
      "type": "string",
      "description": "Result language (en, es, fr)",
      "default": "en"
    }
  },
  "required": ["query"]
}
```

### Output Schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query used"
    },
    "totalResults": {
      "type": "string",
      "description": "Estimated total results"
    },
    "searchTime": {
      "type": "number",
      "description": "Search time in seconds"
    },
    "count": {
      "type": "integer",
      "description": "Results in this response"
    },
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string",
            "description": "Page title"
          },
          "link": {
            "type": "string",
            "description": "Page URL"
          },
          "snippet": {
            "type": "string",
            "description": "Page description"
          },
          "displayLink": {
            "type": "string",
            "description": "Display domain"
          },
          "image": {
            "type": "object",
            "description": "Image data (image search only)",
            "properties": {
              "thumbnailLink": {"type": "string"},
              "contextLink": {"type": "string"},
              "height": {"type": "integer"},
              "width": {"type": "integer"}
            }
          }
        },
        "required": ["title", "link", "snippet"]
      }
    }
  },
  "required": ["query", "count", "results"]
}
```

---

## Limitations

### API Limitations

1. **Daily Quota**:
   - Free tier: 100 queries per day
   - Paid tier: 10,000 queries per day
   - Cannot exceed limits

2. **Results Per Query**:
   - Maximum 10 results per request
   - Use pagination for more results
   - Total accessible results may be limited

3. **Rate Limits**:
   - 100 queries per 100 seconds per user
   - Recommended: Space out requests

4. **Search Scope**:
   - Searches Google's index (not real-time)
   - Some content may not be indexed
   - Results depend on search engine configuration

### Technical Limitations

1. **Authentication**:
   - Requires valid API key
   - Requires Search Engine ID
   - Both must be properly configured

2. **Result Quality**:
   - Depends on search engine settings
   - May include ads or promoted content
   - Ranking algorithm is Google's

3. **Content Restrictions**:
   - Safe search may filter results
   - Some content may be geo-restricted
   - Copyright/legal restrictions apply

### Demo Mode Limitations

1. **Functionality**:
   - ✓ Returns mock results
   - ✓ Tests tool interface
   - ✗ Real search results
   - ✗ Actual URLs
   - ✗ Image metadata
   - ✗ Search analytics

2. **Use Cases**:
   - Development only
   - Interface testing
   - Not for production

### Search Engine Configuration

1. **Entire Web vs Specific Sites**:
   - Must choose scope at creation
   - "Entire web" = broad search
   - "Specific sites" = limited to domains

2. **Image Search**:
   - Must be enabled in search engine settings
   - May require additional configuration

---

## Error Handling

### Common Errors

#### 1. Invalid API Key
```python
ValueError: API key invalid or quota exceeded
```

**Causes**:
- Incorrect API key
- API key not activated
- Restrictions blocking request

**Solutions**:
- Verify API key in Google Cloud Console
- Check API key restrictions (IP, referrer)
- Ensure Custom Search API is enabled

#### 2. Quota Exceeded
```python
ValueError: API key invalid or quota exceeded
```

**Causes**:
- Daily query limit reached (100 free, 10,000 paid)
- Rate limit exceeded

**Solutions**:
- Wait until quota resets (midnight Pacific Time)
- Upgrade to paid tier
- Implement caching to reduce queries

#### 3. Invalid Parameters
```python
ValueError: Invalid search parameters
```

**Causes**:
- Invalid num_results (must be 1-10)
- Invalid date_restrict format
- Invalid search_type

**Solutions**:
- Validate parameters before calling
- Use schema constraints
- Check API documentation

#### 4. No Results
```python
{
  "count": 0,
  "results": []
}
```

**Causes**:
- Query too specific
- Site restriction too narrow
- Date filter too restrictive

**Solutions**:
- Broaden search terms
- Remove or adjust filters
- Try different query formulations

### Error Handling Best Practices

```python
import time
from typing import Optional, Dict

def search_with_retry(
    tool: GoogleSearchTool,
    query: str,
    max_retries: int = 3,
    **kwargs
) -> Optional[Dict]:
    """
    Search with automatic retry logic
    
    Args:
        tool: GoogleSearchTool instance
        query: Search query
        max_retries: Maximum retry attempts
        **kwargs: Additional search parameters
    
    Returns:
        Search results or None if all retries fail
    """
    for attempt in range(max_retries):
        try:
            result = tool.execute({
                'query': query,
                **kwargs
            })
            return result
            
        except ValueError as e:
            error_msg = str(e)
            
            # Don't retry for quota/auth errors
            if 'quota exceeded' in error_msg.lower():
                print(f"❌ Daily quota exceeded")
                return None
            
            if 'invalid' in error_msg.lower() and 'key' in error_msg.lower():
                print(f"❌ Invalid API credentials")
                return None
            
            # Retry for temporary errors
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"⚠️  Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ All {max_retries} attempts failed: {error_msg}")
                return None
    
    return None

# Usage
result = search_with_retry(tool, 'artificial intelligence', num_results=5)
if result:
    print(f"✓ Found {result['count']} results")
```

### Quota Management

```python
class QuotaManager:
    """Manage daily search quota"""
    
    def __init__(self, daily_limit: int = 100):
        self.daily_limit = daily_limit
        self.queries_today = 0
        self.last_reset = datetime.now().date()
    
    def check_quota(self) -> bool:
        """Check if quota available"""
        today = datetime.now().date()
        
        # Reset counter if new day
        if today > self.last_reset:
            self.queries_today = 0
            self.last_reset = today
        
        return self.queries_today < self.daily_limit
    
    def use_quota(self):
        """Record query usage"""
        self.queries_today += 1
    
    def remaining(self) -> int:
        """Get remaining quota"""
        return max(0, self.daily_limit - self.queries_today)

# Usage
quota = QuotaManager(daily_limit=100)

def managed_search(query: str, **kwargs):
    """Search with quota management"""
    if not quota.check_quota():
        print(f"❌ Daily quota exhausted. Resets tomorrow.")
        return None
    
    result = tool.execute({'query': query, **kwargs})
    quota.use_quota()
    
    print(f"📊 Quota: {quota.remaining()}/{quota.daily_limit} remaining")
    return result
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta
import hashlib
import json

class SearchCache:
    """Simple search result cache"""
    
    def __init__(self, ttl_minutes: int = 60):
        self.cache = {}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def _make_key(self, query: str, **kwargs) -> str:
        """Create cache key from query parameters"""
        params = {'query': query, **kwargs}
        param_str = json.dumps(params, sort_keys=True)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def get(self, query: str, **kwargs) -> Optional[Dict]:
        """Get cached result if available and fresh"""
        key = self._make_key(query, **kwargs)
        
        if key in self.cache:
            result, timestamp = self.cache[key]
            
            # Check if still fresh
            if datetime.now() - timestamp < self.ttl:
                return result
            else:
                # Expired, remove from cache
                del self.cache[key]
        
        return None
    
    def set(self, result: Dict, query: str, **kwargs):
        """Cache search result"""
        key = self._make_key(query, **kwargs)
        self.cache[key] = (result, datetime.now())
    
    def clear(self):
        """Clear all cached results"""
        self.cache.clear()

# Usage
cache = SearchCache(ttl_minutes=60)

def cached_search(query: str, **kwargs):
    """Search with caching"""
    # Try cache first
    cached = cache.get(query, **kwargs)
    if cached:
        print("✓ Using cached result")
        return cached
    
    # Perform search
    result = tool.execute({'query': query, **kwargs})
    
    # Cache result
    cache.set(result, query, **kwargs)
    print("✓ Result cached")
    
    return result
```

### Response Time Optimization

| Strategy | Benefit | Use Case |
|----------|---------|----------|
| Reduce num_results | Faster response | Quick lookups |
| Use caching | Avoid duplicate queries | Common searches |
| Async requests | Parallel searches | Multiple queries |
| Demo mode | Instant response | Development |

### Recommended Practices

1. **Query Optimization**:
   - Be specific in queries
   - Use site restrictions when possible
   - Avoid overly broad searches

2. **Result Management**:
   - Request only needed results (num_results)
   - Implement pagination carefully
   - Cache common queries

3. **Quota Conservation**:
   - Cache frequently accessed results
   - Batch related searches
   - Use demo mode for development

4. **Error Recovery**:
   - Implement retry logic
   - Handle quota gracefully
   - Provide fallback options

---

## Appendix A: Common Use Cases

### 1. Academic Research

```python
# Search academic sources
result = tool.execute({
    'query': 'climate change research papers',
    'site': 'scholar.google.com',
    'date_restrict': 'y1',  # Past year
    'num_results': 10
})
```

### 2. News Monitoring

```python
# Track recent news
result = tool.execute({
    'query': 'technology industry news',
    'date_restrict': 'd1',  # Today
    'num_results': 10
})
```

### 3. Competitive Intelligence

```python
# Monitor competitor mentions
competitor = 'CompanyName'
result = tool.execute({
    'query': f'{competitor} product launch',
    'date_restrict': 'm1',
    'num_results': 10
})
```

### 4. Content Discovery

```python
# Find content on specific topics
result = tool.execute({
    'query': 'machine learning tutorials beginners',
    'site': 'youtube.com',
    'num_results': 5
})
```

### 5. Image Research

```python
# Find reference images
result = tool.execute({
    'query': 'modern architecture buildings',
    'search_type': 'image',
    'safe_search': 'high',
    'num_results': 10
})
```

---

## Appendix B: Quick Reference

### Parameter Quick Reference

| Parameter | Values | Example |
|-----------|--------|---------|
| query | Any text | "artificial intelligence" |
| num_results | 1-10 | 5 |
| start | 1+ | 11 (for page 2) |
| safe_search | off, medium, high | "high" |
| search_type | web, image | "image" |
| site | Domain | "wikipedia.org" |
| date_restrict | d/w/m/y + number | "d7", "m3", "y1" |
| language | Language code | "en", "es", "fr" |

### Common Site Restrictions

| Purpose | Site |
|---------|------|
| Encyclopedia | wikipedia.org |
| Code/Development | github.com |
| Academic Papers | scholar.google.com |
| News | news.google.com |
| Videos | youtube.com |
| Social Media | twitter.com |
| E-commerce | amazon.com |

---

## Appendix C: Google Resources

### Official Documentation

- **Custom Search JSON API**: https://developers.google.com/custom-search/v1/overview
- **Get Started Guide**: https://developers.google.com/custom-search/v1/introduction
- **API Reference**: https://developers.google.com/custom-search/v1/reference/rest
- **Pricing**: https://developers.google.com/custom-search/v1/overview#pricing

### Tools & Consoles

- **Google Cloud Console**: https://console.cloud.google.com
- **Programmable Search Engine**: https://programmablesearchengine.google.com
- **API Dashboard**: https://console.cloud.google.com/apis/dashboard

### Support

- **Stack Overflow**: Tagged with `google-custom-search`
- **Google Cloud Support**: https://cloud.google.com/support
- **Issue Tracker**: https://issuetracker.google.com

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025 | Initial release |

---

## Support & Contact

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Copyright**: © 2025-2030 All Rights Reserved

For issues, questions, or feature requests, please contact the author directly.

---

*End of Google Search MCP Tool Reference Guide*
