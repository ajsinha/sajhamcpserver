# Tavily MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Tavily MCP Tool provides advanced web search capabilities including news search, entity search, and content extraction with AI-optimized results.

## Configuration
- **Environment Variables:**
  - `TAVILY_API_KEY`: Required for API access
- AI-optimized search results
- Real-time web data access

## Available Methods

### 1. tavily_search
Perform a comprehensive Tavily search.

**Parameters:**
- `query`: Search query (required)
- `search_depth` (default: 'basic'): 'basic' or 'advanced'
- `max_results` (default: 10): Maximum number of results
- `include_images` (default: False): Include image results
- `include_answer` (default: False): Include AI-generated answer
- `include_raw_content` (default: False): Include raw page content
- `include_domains` (optional): List of domains to search within
- `exclude_domains` (optional): List of domains to exclude

**Returns:**
- Search results with titles, URLs, snippets
- AI-generated answer (if requested)
- Image results (if requested)
- Raw content (if requested)

### 2. tavily_news_search
Search for news articles about entities or topics.

**Parameters:**
- `query`: Search query (required)
- `days_back` (default: 7): Number of days to look back
- `topic` (optional): Specific topic (e.g., 'technology', 'politics', 'business')
- `max_results` (default: 20): Maximum results

**Returns:**
- News articles from major outlets
- Date filtering applied
- Source attribution

**Default News Sources:**
- Reuters, Bloomberg, WSJ, New York Times
- Washington Post, BBC, CNN, AP News
- The Guardian, Forbes, Business Insider

### 3. tavily_entity_search
Search for information about specific entities (companies, people, places).

**Parameters:**
- `entity_name`: Name of entity (required)
- `entity_type` (optional): 'company', 'person', 'place', 'organization'
- `include_social` (default: False): Include social media information
- `include_financial` (default: False): Include financial data
- `max_results` (default: 15): Maximum results

**Returns:**
- Entity-specific information
- Contextual results based on entity type
- Social media presence (if requested)
- Financial information (if requested)

### 4. tavily_context_search
Search with context for more relevant results.

**Parameters:**
- `query`: Search query (required)
- `context` (optional): Additional context for the search
- `previous_queries` (optional): List of previous queries for continuity
- `max_results` (default: 10): Maximum results

**Returns:**
- Context-aware search results
- Enhanced relevance based on context
- Query continuity from previous searches

### 5. tavily_extract
Extract content from specific URLs.

**Parameters:**
- `urls`: List of URLs to extract from (required, max 5)

**Returns for each URL:**
- Page title
- Extracted content
- Author information
- Publication date
- Extraction status

## Search Depth Options

### Basic Search
- Faster response time
- Standard result quality
- Good for general queries

### Advanced Search
- Deeper analysis
- More comprehensive results
- Better for research queries
- May take longer to process

## Example Usage
```python
# Basic search
result = tavily_tool.handle_tool_call('tavily_search', {
    'query': 'artificial intelligence trends 2024',
    'search_depth': 'basic',
    'max_results': 10,
    'include_answer': True
})

# News search
result = tavily_tool.handle_tool_call('tavily_news_search', {
    'query': 'OpenAI',
    'days_back': 7,
    'topic': 'technology',
    'max_results': 15
})

# Entity search for a company
result = tavily_tool.handle_tool_call('tavily_entity_search', {
    'entity_name': 'Tesla Inc',
    'entity_type': 'company',
    'include_financial': True,
    'max_results': 10
})

# Context-aware search
result = tavily_tool.handle_tool_call('tavily_context_search', {
    'query': 'latest developments',
    'context': 'quantum computing research',
    'previous_queries': ['quantum computers', 'IBM quantum'],
    'max_results': 10
})

# Extract content from URLs
result = tavily_tool.handle_tool_call('tavily_extract', {
    'urls': [
        'https://example.com/article1',
        'https://example.com/article2'
    ]
})
```

## Response Format

### Search Results
```json
{
  "query": "search query",
  "results": [
    {
      "title": "Result Title",
      "url": "https://example.com",
      "snippet": "Brief description...",
      "published_date": "2024-01-15"
    }
  ],
  "answer": "AI-generated answer if requested",
  "images": ["image_url1", "image_url2"],
  "count": 10
}
```

### Entity Search Results
```json
{
  "entity_name": "Tesla Inc",
  "entity_type": "company",
  "results": [
    {
      "title": "Tesla Company Information",
      "url": "https://example.com",
      "snippet": "Details about Tesla...",
      "relevance_score": 0.95
    }
  ],
  "financial_data": {...},
  "social_presence": {...}
}
```

## Error Handling

- API key not configured: Returns error message
- Failed API requests: Returns status code and error
- URL extraction failures: Returns error per URL

## Best Practices

1. Use advanced search depth for research queries
2. Include domains for targeted searches
3. Use entity search for people, companies, places
4. Leverage context search for follow-up queries
5. Extract content for detailed analysis
6. Set appropriate days_back for news searches


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.