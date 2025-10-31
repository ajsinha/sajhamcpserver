# Tavily Search MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**Version: 1.0.0**  
**Last Updated: October 31, 2025**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & API Keys](#authentication--api-keys)
5. [Tool Details](#tool-details)
6. [API Reference](#api-reference)
7. [Usage Examples](#usage-examples)
8. [Schema Specifications](#schema-specifications)
9. [Limitations](#limitations)
10. [Troubleshooting](#troubleshooting)
11. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The Tavily Search MCP Tool is a comprehensive AI-powered search solution that provides intelligent web search capabilities through the Tavily API. It offers four specialized tools for different search scenarios, from general web search to academic research, all enhanced with AI-generated summaries and relevance scoring.

### Key Features

- **AI-Powered Search**: Leverages Tavily's AI for intelligent results
- **Multiple Search Modes**: Web, news, research, and domain-specific search
- **Smart Summaries**: AI-generated answers synthesizing multiple sources
- **Relevance Scoring**: Each result includes a relevance score (0-1)
- **Domain Filtering**: Include or exclude specific domains
- **Demo Mode**: Works without API key for testing
- **MCP Compatible**: Fully compliant with Model Context Protocol

### How It Works

The tool operates through **external API calls to Tavily's search service**:

1. **API Request**: Tool sends search query to Tavily API endpoint
2. **AI Processing**: Tavily's AI processes query and searches the web
3. **Result Ranking**: Results are ranked by relevance using AI
4. **Answer Generation**: Optional AI-generated summary from results
5. **Response Formatting**: Structured JSON response with results

```
┌─────────────────┐
│  User Query     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Tavily MCP    │
│   Tool          │
└────────┬────────┘
         │
         ▼ HTTPS API Call
┌─────────────────┐
│   Tavily API    │
│   (External)    │
│ api.tavily.com  │
└────────┬────────┘
         │
         ▼ AI-Powered Search
┌─────────────────┐
│   Web Crawling  │
│   & Indexing    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AI Analysis &  │
│  Ranking        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON Response  │
└─────────────────┘
```

**Important:** This tool uses **external API calls** to Tavily, NOT web scraping or local database queries. All search operations are performed by Tavily's infrastructure.

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────┐
│                  Tavily Search MCP Tool                   │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │         TavilyBaseTool (Base Class)               │  │
│  │  - API Connection Management                      │  │
│  │  - Request/Response Handling                      │  │
│  │  - Demo Mode Support                              │  │
│  │  - Error Handling                                 │  │
│  └───────────────────┬────────────────────────────────┘  │
│                      │                                    │
│       ┌──────────────┼──────────────┐                    │
│       │              │              │                    │
│  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐                │
│  │   Web   │   │  News   │   │Research │                │
│  │  Search │   │ Search  │   │ Search  │                │
│  └─────────┘   └─────────┘   └─────────┘                │
│                      │                                    │
│                 ┌────▼────┐                               │
│                 │ Domain  │                               │
│                 │ Search  │                               │
│                 └─────────┘                               │
│                                                           │
└──────────────────────────────────────────────────────────┘
                         │
                         │ HTTPS
                         ▼
              ┌─────────────────┐
              │   Tavily API    │
              │ api.tavily.com  │
              └─────────────────┘
```

### Class Hierarchy

```python
BaseMCPTool (Abstract Base)
    │
    └── TavilyBaseTool
            │
            ├── TavilyWebSearchTool
            ├── TavilyNewsSearchTool
            ├── TavilyResearchSearchTool
            └── TavilyDomainSearchTool
```

### Core Components

#### 1. TavilyBaseTool (Base Class)

**Responsibilities:**
- Manage API endpoint and key
- Handle HTTP requests to Tavily API
- Format and validate responses
- Provide demo mode fallback
- Error handling and logging

**Key Methods:**
```python
__init__(config: Dict) -> None
_search(query, search_depth, topic, max_results, ...) -> Dict
_get_demo_results(query, search_depth, ...) -> Dict
```

**API Configuration:**
```python
self.api_url = "https://api.tavily.com/search"
self.api_key = config.get('api_key', '')
self.demo_mode = not self.api_key
```

#### 2. Tavily API Integration

**Endpoint:** `https://api.tavily.com/search`

**Request Method:** POST

**Request Format:**
```json
{
  "api_key": "tvly-xxxxx",
  "query": "search query",
  "search_depth": "basic|advanced",
  "topic": "general|news|science|finance",
  "max_results": 5,
  "include_answer": true,
  "include_raw_content": false,
  "include_images": false,
  "include_domains": ["domain1.com"],
  "exclude_domains": ["domain2.com"]
}
```

**Response Format:**
```json
{
  "query": "search query",
  "results": [
    {
      "title": "Result Title",
      "url": "https://...",
      "content": "Excerpt...",
      "score": 0.95,
      "published_date": "2024-10-31"
    }
  ],
  "answer": "AI-generated summary..."
}
```

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
- HTTPS access to api.tavily.com
- No proxy configuration needed (uses urllib)

### External Service
- **Tavily API**: External search service
- **No web scraping**: All searches performed by Tavily
- **No local data**: Results come from Tavily's infrastructure

---

## Authentication & API Keys

### API Key Requirements

**Production Use:** Requires Tavily API key

**How to Get API Key:**
1. Visit https://tavily.com
2. Sign up for an account
3. Navigate to API Keys section
4. Generate new API key
5. Copy key (format: `tvly-xxxxxxxxxxxxx`)

### Configuration

**Method 1: Config File**
```json
{
  "name": "tavily_web_search",
  "api_key": "tvly-xxxxxxxxxxxxx",
  "enabled": true
}
```

**Method 2: Environment Variable**
```bash
export TAVILY_API_KEY="tvly-xxxxxxxxxxxxx"
```

**Method 3: Direct in Code**
```python
config = {
    'api_key': 'tvly-xxxxxxxxxxxxx',
    'name': 'tavily_web_search'
}
tool = TavilyWebSearchTool(config)
```

### Demo Mode

**When No API Key Configured:**
- Tool operates in demo mode
- Returns mock/sample results
- Useful for testing and development
- Response includes note: "Demo mode - Configure Tavily API key for real results"

**Demo Mode Features:**
- No API calls made
- Instant responses
- Consistent sample data
- No rate limits
- No cost

### API Key Validation

The tool validates API keys on first request:
- **401 Error**: Invalid API key
- **429 Error**: Rate limit exceeded
- **400 Error**: Invalid parameters

---

## Tool Details

### 1. tavily_web_search

**Purpose:** General-purpose web search across the internet

**Input Schema:**
```json
{
  "query": "string (required)",
  "search_depth": "basic|advanced (default: basic)",
  "max_results": "integer 1-20 (default: 5)",
  "include_answer": "boolean (default: true)",
  "include_images": "boolean (default: false)"
}
```

**Output Schema:**
```json
{
  "query": "string",
  "search_depth": "string",
  "topic": "string",
  "results_count": "integer",
  "results": [
    {
      "title": "string",
      "url": "string",
      "content": "string",
      "score": "number (0-1)",
      "published_date": "string"
    }
  ],
  "answer": "string (optional)",
  "images": "array (optional)"
}
```

**Search Depth:**
- **basic**: Fast, top results (< 1 second)
- **advanced**: Comprehensive search (2-5 seconds)

**Use Cases:**
- General information retrieval
- Research and fact-checking
- Current events discovery
- Technical documentation search
- Educational content finding
- Product and service research

**Example:**
```python
result = tool.execute({
    'query': 'latest developments in quantum computing',
    'search_depth': 'advanced',
    'max_results': 10,
    'include_answer': True,
    'include_images': True
})
```

---

### 2. tavily_news_search

**Purpose:** Search recent news articles with recency weighting

**Input Schema:**
```json
{
  "query": "string (required)",
  "max_results": "integer 1-20 (default: 5)",
  "include_answer": "boolean (default: true)"
}
```

**Output Schema:**
```json
{
  "query": "string",
  "results_count": "integer",
  "results": [
    {
      "title": "string",
      "url": "string",
      "content": "string",
      "score": "number",
      "published_date": "string"
    }
  ],
  "answer": "string (optional)"
}
```

**Features:**
- Optimized for news articles
- Recency prioritization
- Publication date included
- AI-generated news summary

**Use Cases:**
- Breaking news monitoring
- Market and financial updates
- Political and policy tracking
- Technology news aggregation
- Industry trend analysis
- Event coverage and updates
- News briefing generation

**Example:**
```python
result = tool.execute({
    'query': 'artificial intelligence regulations',
    'max_results': 10,
    'include_answer': True
})
```

**Cache TTL:** 1800 seconds (30 minutes) - shorter for fresh news

---

### 3. tavily_research_search

**Purpose:** Comprehensive academic and professional research

**Input Schema:**
```json
{
  "query": "string (required)",
  "topic": "general|science|finance (default: general)",
  "max_results": "integer 5-20 (default: 10)",
  "include_raw_content": "boolean (default: false)"
}
```

**Output Schema:**
```json
{
  "query": "string",
  "search_depth": "string (always 'advanced')",
  "topic": "string",
  "results_count": "integer",
  "results": [
    {
      "title": "string",
      "url": "string",
      "content": "string",
      "score": "number",
      "published_date": "string",
      "raw_content": "string (optional)"
    }
  ],
  "answer": "string (always included)"
}
```

**Topic Categories:**
- **general**: Cross-domain research
- **science**: Academic and scientific content
- **finance**: Financial and market research

**Features:**
- Always uses advanced search depth
- Higher default result count (10)
- Optional full HTML content
- Comprehensive AI summary always included

**Use Cases:**
- Academic literature review
- Market research and analysis
- Competitive intelligence gathering
- Scientific research synthesis
- Policy and regulatory research
- Industry trend analysis
- Technical deep dives
- Investment research
- Patent and innovation research

**Example:**
```python
result = tool.execute({
    'query': 'transformer architecture in natural language processing',
    'topic': 'science',
    'max_results': 15,
    'include_raw_content': True
})
```

**Rate Limit:** 50 requests/minute (lower than other tools due to depth)

---

### 4. tavily_domain_search

**Purpose:** Search within or exclude specific domains

**Input Schema:**
```json
{
  "query": "string (required)",
  "include_domains": "array of strings (optional)",
  "exclude_domains": "array of strings (optional)",
  "max_results": "integer 1-20 (default: 5)",
  "include_answer": "boolean (default: true)"
}
```

**Note:** Must specify either `include_domains` OR `exclude_domains`

**Output Schema:**
```json
{
  "query": "string",
  "included_domains": "array (if used)",
  "excluded_domains": "array (if used)",
  "results_count": "integer",
  "results": [
    {
      "title": "string",
      "url": "string",
      "content": "string",
      "score": "number"
    }
  ],
  "answer": "string (optional)"
}
```

**Domain Filtering:**

**Include Domains** (whitelist):
```python
{
    'query': 'React hooks best practices',
    'include_domains': ['react.dev', 'github.com', 'stackoverflow.com']
}
```

**Exclude Domains** (blacklist):
```python
{
    'query': 'healthy meal prep ideas',
    'exclude_domains': ['pinterest.com', 'facebook.com', 'reddit.com']
}
```

**Use Cases:**
- Search trusted technical documentation
- Academic and research paper discovery
- Official source verification
- Developer documentation lookup
- Filter out low-quality or spam sites
- Brand-specific information retrieval
- Regulatory and compliance research
- Corporate knowledge base search
- Educational content from verified sources

**Example - Technical Documentation:**
```python
result = tool.execute({
    'query': 'PostgreSQL transaction isolation',
    'include_domains': ['postgresql.org', 'github.com'],
    'max_results': 10
})
```

**Example - Exclude Social Media:**
```python
result = tool.execute({
    'query': 'climate change research',
    'exclude_domains': ['pinterest.com', 'facebook.com', 'twitter.com'],
    'max_results': 15
})
```

---

## API Reference

### Base Class Methods

#### _search()
```python
def _search(
    self, 
    query: str, 
    search_depth: str,
    topic: str,
    max_results: int,
    include_answer: bool,
    include_raw_content: bool,
    include_images: bool,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None
) -> Dict:
    """
    Perform Tavily search with specified parameters
    
    Args:
        query: Search query string
        search_depth: 'basic' or 'advanced'
        topic: 'general', 'news', 'science', or 'finance'
        max_results: Number of results (1-20)
        include_answer: Include AI summary
        include_raw_content: Include full HTML
        include_images: Include image results
        include_domains: Whitelist domains
        exclude_domains: Blacklist domains
    
    Returns:
        Dict containing search results
    
    Raises:
        ValueError: Invalid parameters or API error
    """
```

#### _get_demo_results()
```python
def _get_demo_results(
    self, 
    query: str, 
    search_depth: str,
    topic: str,
    max_results: int,
    include_answer: bool,
    include_images: bool
) -> Dict:
    """
    Generate demo/mock results for testing without API key
    
    Returns:
        Dict with sample search results
    """
```

### Tool Instantiation

```python
from tavily_tool_refactored import TAVILY_TOOLS

# Get tool class
ToolClass = TAVILY_TOOLS['tavily_web_search']

# Create instance with config
tool = ToolClass(config={
    'api_key': 'tvly-xxxxxxxxxxxxx',
    'name': 'tavily_web_search',
    'enabled': True
})

# Execute search
result = tool.execute({
    'query': 'machine learning frameworks',
    'max_results': 10
})
```

### Error Handling

```python
try:
    result = tool.execute({'query': 'test query'})
except ValueError as e:
    if "Invalid API key" in str(e):
        print("API key is invalid")
    elif "Rate limit exceeded" in str(e):
        print("Too many requests")
    elif "Invalid search parameters" in str(e):
        print("Check parameters")
```

---

## Usage Examples

### Example 1: Basic Web Search

```python
from tavily_tool_refactored import TavilyWebSearchTool

# Initialize with API key
config = {'api_key': 'tvly-xxxxxxxxxxxxx'}
tool = TavilyWebSearchTool(config)

# Search
result = tool.execute({
    'query': 'Python async programming tutorial',
    'search_depth': 'basic',
    'max_results': 5,
    'include_answer': True
})

# Process results
print(f"Found {result['results_count']} results")
print(f"Answer: {result['answer']}")

for item in result['results']:
    print(f"- {item['title']}")
    print(f"  {item['url']}")
    print(f"  Score: {item['score']}")
```

### Example 2: News Search with Summary

```python
from tavily_tool_refactored import TavilyNewsSearchTool

tool = TavilyNewsSearchTool(config)

result = tool.execute({
    'query': 'stock market trends today',
    'max_results': 10,
    'include_answer': True
})

# Show AI summary
print("News Summary:")
print(result['answer'])
print("\nArticles:")

for article in result['results']:
    print(f"\n{article['title']}")
    print(f"Published: {article['published_date']}")
    print(f"Excerpt: {article['content'][:200]}...")
```

### Example 3: Academic Research

```python
from tavily_tool_refactored import TavilyResearchSearchTool

tool = TavilyResearchSearchTool(config)

result = tool.execute({
    'query': 'quantum entanglement experiments',
    'topic': 'science',
    'max_results': 15,
    'include_raw_content': False
})

# Research summary
print("Research Summary:")
print(result['answer'])

# High-scoring results
print("\nTop Sources:")
for item in sorted(result['results'], key=lambda x: x['score'], reverse=True)[:5]:
    print(f"\n{item['title']} (Score: {item['score']:.2f})")
    print(f"URL: {item['url']}")
```

### Example 4: Domain-Filtered Search

```python
from tavily_tool_refactored import TavilyDomainSearchTool

tool = TavilyDomainSearchTool(config)

# Search only official documentation
result = tool.execute({
    'query': 'React hooks best practices',
    'include_domains': ['react.dev', 'github.com', 'stackoverflow.com'],
    'max_results': 10,
    'include_answer': True
})

print(f"Searching domains: {result['included_domains']}")
print(f"\nAI Answer: {result['answer']}")

for item in result['results']:
    domain = item['url'].split('/')[2]
    print(f"\n[{domain}] {item['title']}")
```

### Example 5: Advanced Search with Images

```python
from tavily_tool_refactored import TavilyWebSearchTool

tool = TavilyWebSearchTool(config)

result = tool.execute({
    'query': 'machine learning architectures',
    'search_depth': 'advanced',
    'max_results': 10,
    'include_answer': True,
    'include_images': True
})

# Display answer
print("Summary:", result['answer'])

# Display images
if 'images' in result:
    print("\nRelated Images:")
    for img in result['images']:
        print(f"- {img['description']}: {img['url']}")

# Display top results
print("\nTop Results:")
for item in result['results'][:3]:
    print(f"\n{item['title']}")
    print(f"Relevance: {item['score']*100:.0f}%")
```

### Example 6: Demo Mode (No API Key)

```python
from tavily_tool_refactored import TavilyWebSearchTool

# No API key - demo mode
tool = TavilyWebSearchTool({})

result = tool.execute({
    'query': 'artificial intelligence',
    'max_results': 3
})

# Demo results
print("Demo Mode:", 'note' in result)
print(f"Results: {result['results_count']}")

for item in result['results']:
    print(f"\n{item['title']}")
    print(f"This is a demo result for: {result['query']}")
```

### Example 7: Error Handling

```python
from tavily_tool_refactored import TavilyWebSearchTool

tool = TavilyWebSearchTool(config)

def safe_search(query):
    try:
        result = tool.execute({
            'query': query,
            'max_results': 5
        })
        return result
    except ValueError as e:
        error_msg = str(e)
        if "Invalid API key" in error_msg:
            return {"error": "API key invalid or expired"}
        elif "Rate limit" in error_msg:
            return {"error": "Too many requests, try again later"}
        else:
            return {"error": f"Search failed: {error_msg}"}

result = safe_search("test query")
```

---

## Schema Specifications

### Common Response Fields

All tools return responses with these common fields:

```json
{
  "query": "string - The search query",
  "results_count": "integer - Number of results returned",
  "results": "array - Search results",
  "answer": "string - AI-generated summary (optional)"
}
```

### Result Object Structure

Each result in the `results` array contains:

```json
{
  "title": "string - Result title",
  "url": "string - Result URL",
  "content": "string - Content excerpt (200-500 chars)",
  "score": "number - Relevance score 0.0-1.0",
  "published_date": "string - ISO date or empty"
}
```

### Relevance Scoring

- **Score Range:** 0.0 - 1.0
- **0.9-1.0:** Highly relevant, exact match
- **0.7-0.9:** Very relevant
- **0.5-0.7:** Moderately relevant
- **0.3-0.5:** Somewhat relevant
- **0.0-0.3:** Low relevance

### Data Type Standards

| Field | Type | Format | Example |
|-------|------|--------|---------|
| query | string | UTF-8 | "machine learning" |
| score | number | float 0-1 | 0.95 |
| url | string | URL | "https://..." |
| published_date | string | ISO 8601 | "2024-10-31" |
| results_count | integer | positive | 10 |

---

## Limitations

### API Limitations

1. **Rate Limits** (depends on API plan)
   - Free tier: ~50 searches/day
   - Basic plan: ~500 searches/day
   - Pro plan: ~5000 searches/day
   - Enterprise: Custom limits

2. **Result Limits**
   - Maximum results per query: 20
   - Default results: 5
   - Minimum results: 1

3. **Query Constraints**
   - Maximum query length: ~500 characters
   - Minimum query length: 1 character
   - Special characters supported
   - Unicode supported

### Search Depth Impact

| Depth | Speed | Quality | Cost |
|-------|-------|---------|------|
| Basic | < 1s | Good | 1 credit |
| Advanced | 2-5s | Excellent | 2 credits |

### Network Requirements

1. **Connectivity**
   - Requires internet connection
   - HTTPS access to api.tavily.com
   - Port 443 must be open

2. **Response Times**
   - Basic search: 0.5-1.5 seconds
   - Advanced search: 2-5 seconds
   - News search: 1-2 seconds
   - Research search: 3-7 seconds

3. **Timeout Settings**
   - Default timeout: 30 seconds
   - Configurable via urllib

### Content Limitations

1. **No Real-Time Data**
   - Results may be hours to days old
   - Not suitable for second-by-second updates

2. **Language Support**
   - Primarily English
   - Other languages supported but may vary

3. **Content Types**
   - Primarily text-based
   - Images optional (separate request)
   - No video content in results
   - No audio content

### Technical Limitations

1. **No Query Chaining**
   - Each search is independent
   - No conversation context
   - No follow-up questions

2. **No Filtering After Search**
   - Domain filters must be set before search
   - Cannot re-filter results post-search

3. **No Result Caching**
   - Each search makes new API call
   - Implement client-side caching if needed

---

## Troubleshooting

### Common Issues

#### Issue 1: Invalid API Key

**Error:** `ValueError: Invalid API key`

**Causes:**
- API key not set in config
- API key format incorrect
- API key expired or revoked

**Solutions:**
```python
# Check API key format
assert api_key.startswith('tvly-'), "Invalid key format"

# Test with demo mode first
tool = TavilyWebSearchTool({})  # No key = demo mode
result = tool.execute({'query': 'test'})

# Verify key on Tavily dashboard
# Regenerate if necessary
```

#### Issue 2: Rate Limit Exceeded

**Error:** `ValueError: Rate limit exceeded`

**Solutions:**
- Wait before retrying (exponential backoff)
- Upgrade API plan
- Implement request queuing
- Cache results to reduce calls

```python
import time

def search_with_retry(tool, query, max_retries=3):
    for attempt in range(max_retries):
        try:
            return tool.execute({'query': query})
        except ValueError as e:
            if "Rate limit" in str(e):
                wait_time = 2 ** attempt  # Exponential backoff
                time.sleep(wait_time)
            else:
                raise
    raise Exception("Max retries exceeded")
```

#### Issue 3: No Results Returned

**Error:** `results_count: 0`

**Causes:**
- Query too specific
- Domain filters too restrictive
- Query contains typos

**Solutions:**
- Broaden query terms
- Remove or expand domain filters
- Check spelling
- Try different search depth

```python
# Try progressive relaxation
queries = [
    "exact phrase match here",
    "phrase match",
    "phrase"
]

for query in queries:
    result = tool.execute({'query': query})
    if result['results_count'] > 0:
        break
```

#### Issue 4: Slow Response Times

**Symptoms:** Searches taking >10 seconds

**Causes:**
- Using advanced search depth
- High max_results value
- Network latency
- Tavily API slow

**Solutions:**
```python
# Use basic search for speed
result = tool.execute({
    'query': 'fast query',
    'search_depth': 'basic',  # Faster
    'max_results': 5  # Lower count
})

# Set timeout
import socket
socket.setdefaulttimeout(10)  # 10 second timeout
```

#### Issue 5: Network Errors

**Error:** `URLError` or connection timeouts

**Causes:**
- No internet connection
- Firewall blocking HTTPS
- DNS issues
- Proxy configuration

**Solutions:**
```python
import urllib.error

try:
    result = tool.execute({'query': 'test'})
except urllib.error.URLError as e:
    print(f"Network error: {e}")
    # Check internet connectivity
    # Verify firewall settings
    # Check proxy configuration
```

#### Issue 6: Demo Mode Not Recognized

**Symptom:** Expecting demo results but getting API errors

**Cause:** API key set to empty string instead of None

**Solution:**
```python
# Wrong
config = {'api_key': ''}  # Still tries API

# Correct
config = {}  # No api_key key at all
# or
config = {'api_key': None}  # Explicitly None
```

### Debug Mode

Enable detailed logging:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Tool will now log all API calls
tool = TavilyWebSearchTool(config)
result = tool.execute({'query': 'debug test'})
```

### Testing Checklist

Before deploying:

- [ ] API key configured correctly
- [ ] Network connectivity verified
- [ ] Rate limits understood
- [ ] Error handling implemented
- [ ] Demo mode tested
- [ ] Production mode tested
- [ ] Response time acceptable
- [ ] Result quality satisfactory

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
│              Tavily Search MCP Tools                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │    Web     │  │    News    │  │  Research  │            │
│  │   Search   │  │   Search   │  │   Search   │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│                  ┌────────────┐                              │
│                  │   Domain   │                              │
│                  │   Search   │                              │
│                  └────────────┘                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTPS POST
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    Tavily API                                │
│              https://api.tavily.com/search                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              API Request Processing                     │ │
│  │  • Authentication  • Query Analysis  • Rate Limiting   │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ Internal Processing
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              Tavily Search Engine                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │    Web     │  │     AI     │  │  Content   │            │
│  │  Crawling  │  │  Analysis  │  │  Ranking   │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ JSON Response
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Formatted Results                           │
│            (Results + AI Answer + Metadata)                  │
└─────────────────────────────────────────────────────────────┘
```

### Request Flow Diagram

```
User Application
     │
     ├─→ [1] Create Tool Instance
     │        │
     │        └─→ Load config (API key, settings)
     │
     ├─→ [2] Call execute()
     │        │
     │        └─→ Validate input parameters
     │
     ├─→ [3] Check Demo Mode
     │        │
     │        ├─ Yes → Return mock results
     │        │
     │        └─ No → Continue to API call
     │
     ├─→ [4] Build API Request
     │        │
     │        ├─→ Format query parameters
     │        ├─→ Add API key
     │        └─→ Set search options
     │
     ├─→ [5] Make HTTPS POST Request
     │        │
     │        └─→ api.tavily.com/search
     │
     ├─→ [6] Handle Response
     │        │
     │        ├─ Success → Parse JSON
     │        ├─ 400 → Invalid parameters
     │        ├─ 401 → Invalid API key
     │        ├─ 429 → Rate limit
     │        └─ Other → General error
     │
     ├─→ [7] Format Results
     │        │
     │        ├─→ Extract results array
     │        ├─→ Add AI answer
     │        └─→ Include metadata
     │
     └─→ [8] Return to Application
              │
              └─→ JSON response with results
```

### Data Flow Architecture

```
┌──────────────────┐
│   User Query     │
│  "AI research"   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   Tool Layer     │
│  - Validation    │
│  - Config        │
└────────┬─────────┘
         │
         ▼ API Request
┌──────────────────┐
│  HTTP Transport  │
│  urllib.request  │
└────────┬─────────┘
         │
         ▼ HTTPS POST
┌──────────────────┐
│   Tavily API     │
│  Authentication  │
│  Rate Limiting   │
└────────┬─────────┘
         │
         ▼ Search Processing
┌──────────────────┐
│ Search Engine    │
│  - Web Crawl     │
│  - AI Analysis   │
│  - Ranking       │
└────────┬─────────┘
         │
         ▼ Results Generation
┌──────────────────┐
│  AI Answer       │
│  Generation      │
└────────┬─────────┘
         │
         ▼ JSON Response
┌──────────────────┐
│  Formatted Data  │
│  - Results[]     │
│  - Answer        │
│  - Metadata      │
└────────┬─────────┘
         │
         ▼
   Return to User
```

### Error Handling Flow

```
                  API Request
                       │
                       ▼
              ┌────────────────┐
              │  Try API Call  │
              └────────┬───────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌────────┐    ┌─────────┐    ┌─────────┐
   │Success │    │HTTPError│    │Exception│
   └───┬────┘    └────┬────┘    └────┬────┘
       │              │              │
       │         ┌────┴────┐         │
       │         │  Check  │         │
       │         │  Code   │         │
       │         └────┬────┘         │
       │              │              │
       │      ┌───────┼───────┐      │
       │      ▼       ▼       ▼      │
       │   ┌─────┐ ┌─────┐ ┌─────┐  │
       │   │ 400 │ │ 401 │ │ 429 │  │
       │   │Bad  │ │Auth │ │Rate │  │
       │   │Req  │ │Fail │ │Limit│  │
       │   └─────┘ └─────┘ └─────┘  │
       │      │       │       │      │
       └──────┴───────┴───────┴──────┘
                      │
                      ▼
              ┌────────────────┐
              │  Raise Error   │
              │  with Message  │
              └────────────────┘
```

---

## Performance Considerations

### Optimization Tips

1. **Use Appropriate Search Depth**
   ```python
   # Fast queries
   result = tool.execute({
       'query': 'quick lookup',
       'search_depth': 'basic'  # < 1 second
   })
   
   # Thorough research
   result = tool.execute({
       'query': 'comprehensive analysis',
       'search_depth': 'advanced'  # 2-5 seconds
   })
   ```

2. **Limit Results Appropriately**
   ```python
   # Quick overview
   result = tool.execute({
       'query': 'topic overview',
       'max_results': 3  # Faster
   })
   
   # Comprehensive research
   result = tool.execute({
       'query': 'detailed research',
       'max_results': 20  # Slower but thorough
   })
   ```

3. **Cache Results**
   ```python
   import json
   from datetime import datetime, timedelta
   
   class CachedSearch:
       def __init__(self, tool):
           self.tool = tool
           self.cache = {}
       
       def search(self, query, max_age_hours=1):
           if query in self.cache:
               cached_time, result = self.cache[query]
               if datetime.now() - cached_time < timedelta(hours=max_age_hours):
                   return result
           
           result = self.tool.execute({'query': query})
           self.cache[query] = (datetime.now(), result)
           return result
   ```

4. **Batch Processing**
   ```python
   import time
   
   def batch_search(tool, queries, delay=1.0):
       """Search multiple queries with rate limiting"""
       results = []
       for query in queries:
           result = tool.execute({'query': query})
           results.append(result)
           time.sleep(delay)  # Avoid rate limits
       return results
   ```

### Performance Metrics

| Operation | Typical Time | Factors |
|-----------|-------------|---------|
| Basic Web Search | 0.5-1.5s | Query complexity, results count |
| Advanced Web Search | 2-5s | Depth, domain filters |
| News Search | 1-2s | Recency filtering |
| Research Search | 3-7s | Advanced depth, topic analysis |
| Domain Search | 1-3s | Filter complexity |

---

## Best Practices

### 1. API Key Management

```python
# ✓ Good: Use environment variables
import os
api_key = os.getenv('TAVILY_API_KEY')

# ✗ Bad: Hardcode in source
api_key = 'tvly-xxxxxxxxxxxxx'  # Never commit this
```

### 2. Error Handling

```python
# ✓ Good: Comprehensive error handling
def safe_search(tool, query):
    try:
        return tool.execute({'query': query})
    except ValueError as e:
        logger.error(f"Search failed: {e}")
        return None
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        return None

# ✗ Bad: No error handling
result = tool.execute({'query': query})  # May crash
```

### 3. Query Formulation

```python
# ✓ Good: Clear, specific queries
queries = [
    "Python asyncio tutorial for beginners",
    "React hooks useState examples",
    "machine learning CNN architectures"
]

# ✗ Bad: Vague queries
queries = [
    "python",
    "react",
    "ml"
]
```

### 4. Result Processing

```python
# ✓ Good: Handle missing fields
for item in result['results']:
    title = item.get('title', 'Untitled')
    url = item.get('url', '')
    score = item.get('score', 0.0)

# ✗ Bad: Assume all fields present
for item in result['results']:
    print(item['title'])  # May KeyError
```

---

## Metadata

### Tool Registry

```python
TAVILY_TOOLS = {
    'tavily_web_search': TavilyWebSearchTool,
    'tavily_news_search': TavilyNewsSearchTool,
    'tavily_research_search': TavilyResearchSearchTool,
    'tavily_domain_search': TavilyDomainSearchTool
}
```

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-10-31 | Initial release |

### Rate Limits (Default)

| Tool | Requests/Min | Cache TTL |
|------|--------------|-----------|
| Web Search | 100 | 3600s (1 hour) |
| News Search | 100 | 1800s (30 min) |
| Research Search | 50 | 7200s (2 hours) |
| Domain Search | 100 | 3600s (1 hour) |

---

## Support & Resources

### Documentation
- **Tavily API Docs:** https://docs.tavily.com
- **API Dashboard:** https://tavily.com/dashboard
- **Pricing:** https://tavily.com/pricing

### Contact Information
- **Author:** Ashutosh Sinha
- **Email:** ajsinha@gmail.com

### External Resources
- **Tavily Website:** https://tavily.com
- **API Status:** https://status.tavily.com
- **Community:** https://community.tavily.com

---

## Legal

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**

This software and documentation are proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.

**Email:** ajsinha@gmail.com

### Third-Party Services

This tool uses the Tavily API service:
- **Service Provider:** Tavily
- **Terms of Service:** https://tavily.com/terms
- **Privacy Policy:** https://tavily.com/privacy
- **API Key:** Required for production use

### Data Privacy

- All searches are sent to Tavily's servers
- Tavily may log and analyze queries
- Results are not stored by this tool
- Review Tavily's privacy policy for details

---

*End of Reference Guide*
