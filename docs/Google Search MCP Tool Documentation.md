# Google Search MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Google Search MCP Tool provides Google search capabilities including web search, image search, news search, and site-specific searches.

## Configuration
- **Optional Environment Variables:**
  - `GOOGLE_API_KEY`: Google Custom Search API key
  - `GOOGLE_CSE_ID`: Custom Search Engine ID
- Falls back to web scraping if API keys not provided
- Limited functionality without API keys

## Available Methods

### 1. google_search
Perform a standard Google search.

**Parameters:**
- `query`: Search query (required)
- `num_results` (default: 10): Number of results to return
- `language` (default: 'en'): Search language
- `safe` (default: 'off'): Safe search setting

**Returns:**
- Search results with titles, URLs, snippets
- Result count

**API vs Scraping:**
- With API: Full snippets and metadata
- Without API: URLs and basic titles only

### 2. google_image_search
Perform Google Image search.

**Parameters:**
- `query`: Search query (required)
- `num_results` (default: 10): Number of results
- `size` (default: 'medium'): 'icon', 'small', 'medium', 'large', 'xlarge', 'xxlarge', 'huge'
- `type` (default: 'photo'): 'clipart', 'face', 'lineart', 'stock', 'photo', 'animated'

**Returns:**
- Image URLs
- Thumbnails
- Image dimensions
- Source context

**Note:** Requires API keys for functionality

### 3. google_news_search
Perform Google News search.

**Parameters:**
- `query`: Search query (required)
- `num_results` (default: 10): Number of results
- `date_restrict` (default: 'd7'): Time restriction
  - Format: 'd[number]' for days
  - Format: 'w[number]' for weeks
  - Format: 'm[number]' for months

**Returns:**
- News articles
- Publication sources
- Published dates
- Article snippets

### 4. google_scholar_search
Perform Google Scholar search (limited functionality).

**Parameters:**
- `query`: Search query (required)
- `year_from` (optional): Start year for results
- `year_to` (optional): End year for results

**Returns:**
- Academic paper results
- Limited metadata

**Note:** No official API; uses workarounds

### 5. google_site_search
Perform site-specific Google search.

**Parameters:**
- `query`: Search query (required)
- `site`: Website domain (required)
- `num_results` (default: 10): Number of results

**Returns:**
- Results from specific website only
- Page titles and URLs
- Snippets (if API available)

## API Configuration

### Setting Up Google Custom Search API
1. Create a Google Cloud project
2. Enable Custom Search API
3. Create API credentials
4. Set up Custom Search Engine
5. Configure environment variables

### Rate Limits
- With API: 100 queries/day (free tier)
- Without API: Subject to scraping limitations

## Example Usage
```python
# Standard web search
result = google_tool.handle_tool_call('google_search', {
    'query': 'machine learning tutorials',
    'num_results': 10,
    'language': 'en'
})

# Image search (requires API)
result = google_tool.handle_tool_call('google_image_search', {
    'query': 'sunset photography',
    'num_results': 5,
    'size': 'large',
    'type': 'photo'
})

# News search
result = google_tool.handle_tool_call('google_news_search', {
    'query': 'artificial intelligence',
    'num_results': 10,
    'date_restrict': 'd7'  # Last 7 days
})

# Scholar search
result = google_tool.handle_tool_call('google_scholar_search', {
    'query': 'quantum computing',
    'year_from': '2020',
    'year_to': '2024'
})

# Site-specific search
result = google_tool.handle_tool_call('google_site_search', {
    'query': 'python tutorials',
    'site': 'stackoverflow.com',
    'num_results': 5
})
```

## Response Format

### Search Results
```json
{
  "query": "search query",
  "results": [
    {
      "title": "Page Title",
      "url": "https://example.com",
      "snippet": "Brief description of the page content..."
    }
  ],
  "count": 10
}
```

### Image Search Results
```json
{
  "query": "image query",
  "type": "image",
  "results": [
    {
      "title": "Image Title",
      "url": "https://example.com/image.jpg",
      "thumbnail": "https://example.com/thumb.jpg",
      "context": "example.com",
      "width": 1920,
      "height": 1080
    }
  ],
  "count": 5
}
```

## Limitations

### Without API Keys
- Limited to basic web search
- No image search functionality
- Reduced metadata in results
- Subject to rate limiting
- May be blocked by Google

### With API Keys
- Daily query limits (free tier)
- Some advanced features unavailable
- Scholar search still limited

## Best Practices

1. Use API keys for production environments
2. Implement caching for repeated searches
3. Respect rate limits
4. Use site search for domain-specific queries
5. Combine with other tools for comprehensive results


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.