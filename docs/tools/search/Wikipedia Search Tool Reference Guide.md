# Wikipedia Search MCP Tool Reference Guide

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

The Wikipedia Search MCP Tool is a comprehensive suite of three specialized tools designed to interact with Wikipedia's vast knowledge base through the official Wikipedia API. This tool suite provides seamless access to Wikipedia content without requiring API keys, web scraping, or complex authentication mechanisms.

### Key Features

- **No API Key Required**: Free access to Wikipedia's public API
- **Multi-language Support**: Access Wikipedia in 300+ languages
- **Three Specialized Tools**: Search, full page retrieval, and quick summaries
- **Rate Limiting**: Built-in rate limiting (100 requests per hour)
- **Caching**: 3600-second TTL for improved performance
- **Type-Safe**: Complete JSON schema validation for inputs and outputs

### Tool Suite Components

1. **wiki_search** - Search Wikipedia articles by keyword
2. **wiki_get_page** - Retrieve complete article content with metadata
3. **wiki_get_summary** - Get concise article summaries quickly

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
│                   WikipediaBaseTool                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  - API endpoint configuration                            │  │
│  │  - HTTP request handling                                 │  │
│  │  - Error management                                      │  │
│  │  - Language support                                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────┬──────────────────┬────────────────┬────────────────┘
            │                  │                │
            │ inherits         │ inherits       │ inherits
            ↓                  ↓                ↓
  ┌─────────────────┐  ┌──────────────┐  ┌────────────────────┐
  │ WikiSearchTool  │  │WikiGetPageTool│  │WikiGetSummaryTool │
  │                 │  │               │  │                    │
  │ - Search by     │  │ - Full article│  │ - Quick summaries  │
  │   keyword       │  │   retrieval   │  │ - Lead sections    │
  │ - Result        │  │ - Images      │  │ - Thumbnails       │
  │   ranking       │  │ - Links       │  │ - Coordinates      │
  │ - Snippets      │  │ - Categories  │  │ - Descriptions     │
  └─────────────────┘  └──────────────┘  └────────────────────┘
            │                  │                │
            └──────────────────┴────────────────┘
                               │
                               ↓
              ┌────────────────────────────────┐
              │    Wikipedia API Endpoint      │
              │  https://{lang}.wikipedia.org  │
              │         /w/api.php             │
              └────────────────────────────────┘
```

### Component Hierarchy

```
BaseMCPTool (Abstract Base Class)
    │
    └── WikipediaBaseTool
            ├── _make_request()      # HTTP communication
            ├── api_base             # API endpoint template
            └── default_lang         # Language configuration
            │
            ├── WikiSearchTool
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            ├── WikiGetPageTool
            │       ├── get_input_schema()
            │       ├── get_output_schema()
            │       └── execute()
            │
            └── WikiGetSummaryTool
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
┌─────────────────┐
│  Tool Instance  │
│  (wiki_search/  │
│   wiki_get_page/│
│   wiki_get_     │
│   summary)      │
└────────┬────────┘
         │ 2. Validate input schema
         ↓
┌─────────────────────┐
│ WikipediaBaseTool   │
│  _make_request()    │
└──────────┬──────────┘
           │ 3. Build API URL & params
           ↓
┌─────────────────────────┐
│  HTTP Request           │
│  (urllib.request)       │
│  User-Agent: MCP-Tools  │
│  Timeout: 10s           │
└──────────┬──────────────┘
           │ 4. API call
           ↓
┌────────────────────────┐
│  Wikipedia API         │
│  (MediaWiki API)       │
│  - action=query        │
│  - format=json         │
└──────────┬─────────────┘
           │ 5. JSON response
           ↓
┌─────────────────────┐
│  Response Parser    │
│  - Extract data     │
│  - Format output    │
│  - Add metadata     │
└──────────┬──────────┘
           │ 6. Structured result
           ↓
┌──────────────────┐
│  Return to Client│
└──────────────────┘
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

### Optional Dependencies

- Custom logging framework (if extending BaseMCPTool)
- Testing framework: pytest (for running test suite)

---

## Authentication & API Keys

### No Authentication Required ✓

The Wikipedia MCP Tool uses the **public Wikipedia API**, which:

- ✅ **No API key needed**
- ✅ **No registration required**
- ✅ **No OAuth or authentication**
- ✅ **Free for all users**
- ✅ **No rate limit authentication**

### User-Agent Requirement

Wikipedia requires a User-Agent header to identify the application:

```python
headers = {
    'User-Agent': 'Mozilla/5.0 (compatible; MCP-Tools/1.0)'
}
```

**Best Practice**: Customize the User-Agent with your project name and contact information:

```python
'User-Agent': 'YourProjectName/1.0 (your-email@example.com)'
```

---

## Tool Details

### 1. WikiSearchTool (wiki_search)

**Purpose**: Search Wikipedia articles by keyword or phrase and return a list of matching articles.

**When to Use**:
- Finding articles on a specific topic
- Discovering related content
- Initial research phase
- Topic exploration

**Input Parameters**:

| Parameter | Type    | Required | Default | Description                          |
|-----------|---------|----------|---------|--------------------------------------|
| query     | string  | Yes      | -       | Search term (1-300 characters)       |
| limit     | integer | No       | 5       | Max results (1-20)                   |
| language  | string  | No       | "en"    | Language code (e.g., 'en', 'es')     |

**Output Structure**:

```json
{
  "query": "string",
  "language": "string",
  "result_count": "integer",
  "results": [
    {
      "title": "string",
      "page_id": "integer",
      "snippet": "string",
      "url": "string",
      "timestamp": "string (ISO)",
      "word_count": "integer"
    }
  ],
  "suggestion": "string or null",
  "last_updated": "string (ISO)"
}
```

**Use Cases**:
- Article discovery
- Topic exploration
- Research starting points
- Finding related articles
- General knowledge queries

---

### 2. WikiGetPageTool (wiki_get_page)

**Purpose**: Retrieve complete Wikipedia article content including text, images, links, and metadata.

**When to Use**:
- In-depth research
- Content analysis
- Knowledge extraction
- Full article archiving
- Detailed fact-checking

**Input Parameters**:

| Parameter          | Type    | Required | Default | Description                              |
|--------------------|---------|----------|---------|------------------------------------------|
| query              | string  | Either*  | -       | Article title (1-300 characters)         |
| page_id            | integer | Either*  | -       | Wikipedia page ID                        |
| language           | string  | No       | "en"    | Language code                            |
| redirect           | boolean | No       | true    | Follow redirects                         |
| include_images     | boolean | No       | true    | Include image URLs                       |
| include_links      | boolean | No       | true    | Include links                            |
| include_references | boolean | No       | false   | Include references (requires HTML parse) |

\*Either `query` or `page_id` must be provided

**Output Structure**:

```json
{
  "title": "string",
  "page_id": "integer",
  "url": "string",
  "language": "string",
  "content": "string (full text)",
  "html_content": "string",
  "summary": "string",
  "sections": [
    {
      "title": "string",
      "level": "integer",
      "content": "string"
    }
  ],
  "images": [
    {
      "url": "string",
      "title": "string",
      "description": "string or null"
    }
  ],
  "links": {
    "internal": ["string"],
    "external": ["string"]
  },
  "references": [],
  "categories": ["string"],
  "last_modified": "string (ISO)",
  "last_modified_by": "string",
  "revision_id": "integer",
  "word_count": "integer",
  "last_updated": "string (ISO)"
}
```

**Use Cases**:
- In-depth research
- Content analysis
- Knowledge extraction
- Fact-checking
- Educational content creation
- Article archiving

---

### 3. WikiGetSummaryTool (wiki_get_summary)

**Purpose**: Retrieve concise article summaries (lead section only) for quick overviews.

**When to Use**:
- Quick information lookup
- Overview generation
- Chatbot responses
- Content previews
- Research starting points

**Input Parameters**:

| Parameter      | Type    | Required | Default | Description                              |
|----------------|---------|----------|---------|------------------------------------------|
| query          | string  | Either*  | -       | Article title (1-300 characters)         |
| page_id        | integer | Either*  | -       | Wikipedia page ID                        |
| language       | string  | No       | "en"    | Language code                            |
| sentences      | integer | No       | 3       | Number of sentences (1-10)               |
| redirect       | boolean | No       | true    | Follow redirects                         |
| include_image  | boolean | No       | true    | Include thumbnail                        |

\*Either `query` or `page_id` must be provided

**Output Structure**:

```json
{
  "title": "string",
  "page_id": "integer",
  "url": "string",
  "language": "string",
  "summary": "string",
  "extract": "string",
  "extract_html": "string",
  "thumbnail": {
    "url": "string",
    "width": "integer",
    "height": "integer"
  },
  "original_image": {
    "url": "string",
    "width": "integer",
    "height": "integer"
  },
  "coordinates": {
    "latitude": "number",
    "longitude": "number"
  },
  "last_modified": "string (ISO)",
  "description": "string",
  "content_type": "string",
  "last_updated": "string (ISO)"
}
```

**Use Cases**:
- Quick information lookup
- Overview generation
- Fact verification
- Chatbot responses
- Content previews
- Educational quick facts

---

## Technical Implementation

### How It Works

The Wikipedia MCP Tool suite uses **API calls** to Wikipedia's official MediaWiki API, not web scraping or database queries.

#### Method: REST API Calls

```
┌─────────────────────────────────────────────────────────────┐
│                    Implementation Method                    │
├─────────────────────────────────────────────────────────────┤
│  ✓ API Calls      (MediaWiki API)                          │
│  ✗ Web Scraping   (Not used)                               │
│  ✗ Web Crawling   (Not used)                               │
│  ✗ Database Query (Not used)                               │
└─────────────────────────────────────────────────────────────┘
```

### API Endpoint

**Base URL**: `https://{language}.wikipedia.org/w/api.php`

**Examples**:
- English: `https://en.wikipedia.org/w/api.php`
- Spanish: `https://es.wikipedia.org/w/api.php`
- French: `https://fr.wikipedia.org/w/api.php`
- German: `https://de.wikipedia.org/w/api.php`

### Request Flow

```python
# 1. Build API endpoint
url = f"https://{language}.wikipedia.org/w/api.php"

# 2. Prepare parameters
params = {
    'action': 'query',
    'format': 'json',
    # ... tool-specific parameters
}

# 3. Encode URL
full_url = url + '?' + urllib.parse.urlencode(params)

# 4. Set headers
headers = {
    'User-Agent': 'Mozilla/5.0 (compatible; MCP-Tools/1.0)'
}

# 5. Make request
request = urllib.request.Request(full_url, headers=headers)
response = urllib.request.urlopen(request, timeout=10)

# 6. Parse JSON
data = json.loads(response.read().decode('utf-8'))
```

### Wikipedia API Actions Used

#### 1. Search (wiki_search)

```python
params = {
    'action': 'query',
    'list': 'search',
    'srsearch': query,              # Search term
    'srlimit': limit,               # Number of results
    'srprop': 'snippet|titlesnippet|timestamp|wordcount'
}
```

#### 2. Get Page (wiki_get_page)

```python
params = {
    'action': 'query',
    'prop': 'extracts|info|images|links|categories|revisions',
    'titles': query,                # Page title
    'explaintext': True,            # Plain text
    'exsectionformat': 'plain',
    'inprop': 'url',
    'redirects': 1,
    'imlimit': 50,                  # Image limit
    'pllimit': 100,                 # Link limit
    'cllimit': 100,                 # Category limit
    'rvprop': 'timestamp|user|ids'
}
```

#### 3. Get Summary (wiki_get_summary)

```python
params = {
    'action': 'query',
    'prop': 'extracts|info|pageimages|description|coordinates',
    'exintro': True,                # Intro section only
    'explaintext': True,            # Plain text
    'exsentences': sentences,       # Number of sentences
    'inprop': 'url',
    'redirects': 1,
    'pithumbsize': 500             # Thumbnail size
}
```

### Error Handling

```python
try:
    response = urllib.request.urlopen(request, timeout=10)
    data = json.loads(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    if e.code == 404:
        raise ValueError("Wikipedia resource not found")
    else:
        raise ValueError(f"Wikipedia API request failed: HTTP {e.code}")
except Exception as e:
    raise ValueError(f"Wikipedia API request failed: {str(e)}")
```

### Timeout Configuration

- **Request Timeout**: 10 seconds
- **Prevents**: Hanging connections
- **Configurable**: Can be adjusted in `_make_request()` method

---

## Schema Specifications

### Input Schema Pattern

All tools follow a consistent input schema pattern:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search or article identifier",
      "minLength": 1,
      "maxLength": 300
    },
    "language": {
      "type": "string",
      "description": "Wikipedia language edition",
      "pattern": "^[a-z]{2,3}$",
      "default": "en"
    }
  },
  "required": ["query"]
}
```

### Output Schema Pattern

All tools return structured data with these common fields:

```json
{
  "type": "object",
  "properties": {
    "title": {"type": "string"},
    "page_id": {"type": "integer"},
    "url": {"type": "string"},
    "language": {"type": "string"},
    "last_updated": {"type": "string"}
  },
  "required": ["title", "page_id", "url"]
}
```

### Validation Rules

1. **String Length**: 1-300 characters for queries
2. **Integer Ranges**: Positive integers for page_id, limits, etc.
3. **Language Codes**: 2-3 lowercase letters (ISO 639-1/639-2)
4. **Boolean Flags**: true/false for optional features
5. **Required Fields**: At least one identifier (query or page_id)

---

## Usage Examples

### Example 1: Basic Search

```python
# Initialize the search tool
search_tool = WikiSearchTool()

# Search for articles about "Artificial Intelligence"
result = search_tool.execute({
    'query': 'Artificial Intelligence',
    'limit': 5
})

# Output
{
  "query": "Artificial Intelligence",
  "language": "en",
  "result_count": 5,
  "results": [
    {
      "title": "Artificial intelligence",
      "page_id": 1234567,
      "snippet": "Artificial intelligence (AI) is intelligence demonstrated by machines...",
      "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
      "timestamp": "2025-10-15T12:30:45Z",
      "word_count": 15234
    },
    // ... more results
  ],
  "suggestion": null,
  "last_updated": "2025-10-31T10:15:30.123456"
}
```

### Example 2: Get Complete Article

```python
# Initialize the get page tool
page_tool = WikiGetPageTool()

# Get the full article about "Machine Learning"
result = page_tool.execute({
    'query': 'Machine Learning',
    'include_images': True,
    'include_links': True
})

# Output includes full content, sections, images, links, categories
{
  "title": "Machine learning",
  "page_id": 233488,
  "url": "https://en.wikipedia.org/wiki/Machine_learning",
  "content": "Machine learning (ML) is a field of study in artificial intelligence...",
  "summary": "Machine learning is a field of study...",
  "sections": [
    {
      "title": "Overview",
      "level": 2,
      "content": "Machine learning is a method..."
    }
  ],
  "images": [
    {
      "url": "https://upload.wikimedia.org/...",
      "title": "Machine_learning_diagram.png"
    }
  ],
  "word_count": 12450
}
```

### Example 3: Quick Summary

```python
# Initialize the summary tool
summary_tool = WikiGetSummaryTool()

# Get a 3-sentence summary of "Quantum Computing"
result = summary_tool.execute({
    'query': 'Quantum Computing',
    'sentences': 3,
    'include_image': True
})

# Output
{
  "title": "Quantum computing",
  "page_id": 25965,
  "url": "https://en.wikipedia.org/wiki/Quantum_computing",
  "summary": "Quantum computing is the use of quantum phenomena...",
  "thumbnail": {
    "url": "https://upload.wikimedia.org/...",
    "width": 500,
    "height": 375
  },
  "description": "Use of quantum mechanics for computation"
}
```

### Example 4: Multi-language Support

```python
# Search in Spanish Wikipedia
result = search_tool.execute({
    'query': 'Inteligencia Artificial',
    'language': 'es',
    'limit': 3
})

# Get summary in French
result = summary_tool.execute({
    'query': 'Intelligence artificielle',
    'language': 'fr',
    'sentences': 5
})
```

### Example 5: Using Page ID

```python
# Retrieve page by ID instead of title
result = page_tool.execute({
    'page_id': 5043734,  # Page ID for "Deep Learning"
    'language': 'en'
})
```

### Example 6: Complete Workflow

```python
# Step 1: Search for relevant articles
search_tool = WikiSearchTool()
search_results = search_tool.execute({
    'query': 'Neural Networks',
    'limit': 10
})

# Step 2: Get summary for quick overview
summary_tool = WikiGetSummaryTool()
for article in search_results['results'][:3]:
    summary = summary_tool.execute({
        'page_id': article['page_id'],
        'sentences': 2
    })
    print(f"{summary['title']}: {summary['summary']}")

# Step 3: Get full article for detailed analysis
page_tool = WikiGetPageTool()
full_article = page_tool.execute({
    'page_id': search_results['results'][0]['page_id'],
    'include_images': True,
    'include_links': True
})
```

---

## Limitations & Best Practices

### Rate Limiting

**Configured Limits**:
- **Rate Limit**: 100 requests per hour
- **Cache TTL**: 3600 seconds (1 hour)
- **Timeout**: 10 seconds per request

**Best Practices**:
```python
# Implement request throttling
import time

def rate_limited_search(queries, delay=1.0):
    results = []
    for query in queries:
        result = search_tool.execute({'query': query})
        results.append(result)
        time.sleep(delay)  # Prevent rate limiting
    return results
```

### Wikipedia API Limitations

1. **No Full HTML**: HTML content requires separate API calls
2. **No References**: Reference parsing requires HTML parsing
3. **Image Limit**: Maximum 50 images per page request
4. **Link Limit**: Maximum 100 links per page request
5. **Search Limit**: Maximum 20 search results per query

### Content Limitations

- **Real-time Data**: Wikipedia content may be outdated
- **Article Quality**: Varies by topic and language
- **Disambiguation**: Some queries may return disambiguation pages
- **Redirects**: Automatic redirect handling may affect results

### Best Practices

#### 1. Error Handling

```python
try:
    result = tool.execute(params)
except ValueError as e:
    print(f"Error: {e}")
    # Implement retry logic or fallback
```

#### 2. Input Validation

```python
def validate_query(query):
    if not query or len(query) < 1 or len(query) > 300:
        raise ValueError("Query must be 1-300 characters")
    return query.strip()
```

#### 3. Language Handling

```python
# Supported language codes
SUPPORTED_LANGUAGES = ['en', 'es', 'fr', 'de', 'zh', 'ja', 'ru', ...]

def validate_language(lang):
    if lang not in SUPPORTED_LANGUAGES:
        return 'en'  # Default to English
    return lang
```

#### 4. Caching Results

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_search(query, language='en'):
    return search_tool.execute({'query': query, 'language': language})
```

#### 5. Batch Processing

```python
def batch_get_summaries(page_ids, batch_size=5):
    summaries = []
    for i in range(0, len(page_ids), batch_size):
        batch = page_ids[i:i+batch_size]
        for page_id in batch:
            summary = summary_tool.execute({'page_id': page_id})
            summaries.append(summary)
        time.sleep(1)  # Rate limiting
    return summaries
```

### Performance Optimization

1. **Use Summaries First**: Quick overview before full page retrieval
2. **Cache Results**: Store frequently accessed articles
3. **Batch Requests**: Group similar queries
4. **Selective Properties**: Only request needed data (images, links)
5. **Connection Pooling**: Reuse HTTP connections

---

## Error Handling

### Error Types

#### 1. HTTP Errors

```python
urllib.error.HTTPError
- 404: Page not found
- 429: Too many requests (rate limit)
- 500: Wikipedia server error
- 503: Service temporarily unavailable
```

#### 2. Validation Errors

```python
ValueError
- Invalid query (empty or too long)
- Invalid page_id (not found or negative)
- Invalid language code
- Missing required parameters
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
        "message": "Wikipedia resource not found",
        "code": "RESOURCE_NOT_FOUND"
    }
}
```

### Handling Examples

```python
# Example 1: Handle page not found
try:
    result = page_tool.execute({'query': 'NonExistentPage123'})
except ValueError as e:
    if "not found" in str(e):
        print("Article doesn't exist. Trying search...")
        search_results = search_tool.execute({'query': 'NonExistentPage123'})

# Example 2: Handle timeout
try:
    result = tool.execute(params)
except urllib.error.URLError as e:
    if "timeout" in str(e):
        print("Request timed out. Retrying...")
        # Implement retry logic

# Example 3: Handle rate limiting
import time

def execute_with_retry(tool, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            return tool.execute(params)
        except ValueError as e:
            if "rate limit" in str(e).lower():
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    raise ValueError("Max retries exceeded")
```

---

## Appendix

### A. Language Codes

Common Wikipedia language editions:

| Code | Language   | Code | Language    |
|------|------------|------|-------------|
| en   | English    | de   | German      |
| es   | Spanish    | fr   | French      |
| zh   | Chinese    | ja   | Japanese    |
| ru   | Russian    | it   | Italian     |
| pt   | Portuguese | ar   | Arabic      |
| hi   | Hindi      | ko   | Korean      |
| nl   | Dutch      | pl   | Polish      |
| sv   | Swedish    | tr   | Turkish     |

### B. MediaWiki API Reference

- **Official Documentation**: https://www.mediawiki.org/wiki/API:Main_page
- **Query API**: https://www.mediawiki.org/wiki/API:Query
- **Search API**: https://www.mediawiki.org/wiki/API:Search
- **Properties**: https://www.mediawiki.org/wiki/API:Properties

### C. Tool Registry

```python
WIKIPEDIA_TOOLS = {
    'wiki_search': WikiSearchTool,
    'wiki_get_page': WikiGetPageTool,
    'wiki_get_summary': WikiGetSummaryTool
}

# Dynamic tool instantiation
tool_name = 'wiki_search'
tool_class = WIKIPEDIA_TOOLS[tool_name]
tool_instance = tool_class()
```

### D. Configuration Options

```python
# Default configuration
config = {
    'name': 'wiki_search',
    'description': 'Search Wikipedia articles',
    'version': '1.0.0',
    'enabled': True,
    'rate_limit': 100,        # requests per hour
    'cache_ttl': 3600,        # seconds
    'timeout': 10,            # seconds
    'language': 'en'
}

# Initialize with custom config
tool = WikiSearchTool(config)
```

### E. Testing Checklist

- [ ] Basic search functionality
- [ ] Multi-language support
- [ ] Page retrieval by title
- [ ] Page retrieval by ID
- [ ] Summary generation
- [ ] Image handling
- [ ] Link extraction
- [ ] Error handling
- [ ] Rate limiting
- [ ] Timeout handling
- [ ] Redirect following
- [ ] Disambiguation handling

### F. Troubleshooting Guide

**Problem**: "Page not found" error
- **Solution**: Check spelling, try search first, verify language code

**Problem**: Request timeout
- **Solution**: Check internet connection, increase timeout, retry

**Problem**: Empty results
- **Solution**: Verify query, check if article exists, try different language

**Problem**: Rate limit exceeded
- **Solution**: Implement delay between requests, use caching

**Problem**: Missing images
- **Solution**: Set `include_images=True`, check if article has images

### G. Version History

- **v1.0.0** (2025): Initial release
  - Three core tools implemented
  - Multi-language support
  - Complete schema definitions
  - Error handling framework

### H. Contributing

For bugs, feature requests, or contributions:
- **Email**: ajsinha@gmail.com
- **Copyright**: © 2025-2030 Ashutosh Sinha
- **License**: All Rights Reserved

### I. Sample Response Structures

#### Search Result Example
```json
{
  "query": "Python programming",
  "language": "en",
  "result_count": 5,
  "results": [
    {
      "title": "Python (programming language)",
      "page_id": 23862,
      "snippet": "Python is a high-level, interpreted programming language...",
      "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
      "timestamp": "2025-10-15T10:30:00Z",
      "word_count": 12500
    }
  ],
  "suggestion": null,
  "last_updated": "2025-10-31T10:15:30.123456"
}
```

#### Page Content Example
```json
{
  "title": "Machine learning",
  "page_id": 233488,
  "url": "https://en.wikipedia.org/wiki/Machine_learning",
  "language": "en",
  "content": "Full article text...",
  "summary": "Lead section summary...",
  "sections": [
    {
      "title": "History",
      "level": 2,
      "content": "Section content..."
    }
  ],
  "images": [
    {
      "url": "https://upload.wikimedia.org/...",
      "title": "ML_diagram.png",
      "description": "Machine learning diagram"
    }
  ],
  "links": {
    "internal": ["Artificial intelligence", "Deep learning"],
    "external": ["https://example.com"]
  },
  "categories": ["Machine learning", "Artificial intelligence"],
  "word_count": 12450,
  "last_modified": "2025-10-20T15:45:00Z",
  "revision_id": 1234567890
}
```

#### Summary Example
```json
{
  "title": "Artificial intelligence",
  "page_id": 1234,
  "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
  "language": "en",
  "summary": "Artificial intelligence (AI) is intelligence demonstrated by machines...",
  "extract": "Same as summary...",
  "thumbnail": {
    "url": "https://upload.wikimedia.org/...",
    "width": 500,
    "height": 375
  },
  "coordinates": null,
  "description": "Intelligence of machines",
  "last_modified": "2025-10-25T12:00:00Z"
}
```

---

## Conclusion

The Wikipedia Search MCP Tool provides a robust, efficient, and easy-to-use interface to Wikipedia's vast knowledge base. With no authentication requirements, comprehensive error handling, and support for 300+ languages, it's an ideal solution for applications requiring encyclopedic knowledge retrieval.

For questions, support, or feature requests, please contact:

**Ashutosh Sinha**  
Email: ajsinha@gmail.com

**Copyright © 2025-2030 All Rights Reserved**

---

*End of Document*

---

## Page Glossary

**Key terms referenced in this document:**

- **Wikipedia API**: The MediaWiki API that provides programmatic access to Wikipedia content. SAJHA's Wikipedia tool uses this API.

- **Full-Text Search**: Searching through article content for keywords. The Wikipedia tool supports content search across articles.

- **Article Summary**: A brief extract from a Wikipedia article. The tool can return summaries for quick information retrieval.

- **Disambiguation**: Wikipedia pages that list multiple articles with similar titles. The tool handles disambiguation automatically.

- **Multi-Language Support**: Ability to access content in different languages. Wikipedia tool supports language parameter for international content.

- **Rate Limiting**: Restricting request frequency to prevent API overload. Wikipedia API has rate limits that SAJHA respects.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
