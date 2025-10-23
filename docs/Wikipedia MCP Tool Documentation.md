# Wikipedia MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Wikipedia MCP Tool provides access to Wikipedia content including article search, summaries, full content, and metadata.

## Configuration
- No API key required
- Uses Wikipedia Python library
- Default language: English
- Access to millions of Wikipedia articles

## Available Methods

### 1. search_articles
Search for Wikipedia articles.

**Parameters:**
- `query`: Search query (required)
- `limit` (default: 10): Maximum number of results

**Returns:**
- List of matching article titles
- Result count

### 2. get_article_summary
Get article summary.

**Parameters:**
- `title`: Article title (required)
- `sentences` (default: 5): Number of sentences to return

**Returns:**
- Article title
- Summary text
- Wikipedia URL
- Page ID

**Error Handling:**
- Returns disambiguation options if multiple articles match
- Returns error if page not found

### 3. get_article_content
Get full article content.

**Parameters:**
- `title`: Article title (required)

**Returns:**
- Full article content (limited to 5000 characters)
- Article URL
- Page ID
- Revision ID

### 4. get_article_sections
Get article sections.

**Parameters:**
- `title`: Article title (required)

**Returns:**
- List of section headings
- Section count
- Hierarchical structure of article

### 5. get_random_article
Get a random Wikipedia article.

**Parameters:**
None

**Returns:**
- Random article summary (3 sentences)
- Article title and URL

### 6. get_article_links
Get links from an article.

**Parameters:**
- `title`: Article title (required)
- `limit` (default: 20): Maximum number of links

**Returns:**
- List of linked article titles
- Link count
- Internal Wikipedia links only

### 7. get_article_categories
Get article categories.

**Parameters:**
- `title`: Article title (required)

**Returns:**
- List of categories
- Category count
- Wikipedia category hierarchy

### 8. get_article_images
Get images from an article.

**Parameters:**
- `title`: Article title (required)
- `limit` (default: 10): Maximum number of images

**Returns:**
- List of image URLs
- Image count
- Direct links to Wikimedia Commons

## Example Usage
```python
# Search for articles
result = wiki_tool.handle_tool_call('search_articles', {
    'query': 'artificial intelligence',
    'limit': 5
})

# Get article summary
result = wiki_tool.handle_tool_call('get_article_summary', {
    'title': 'Machine learning',
    'sentences': 3
})

# Get full content
result = wiki_tool.handle_tool_call('get_article_content', {
    'title': 'Python (programming language)'
})

# Get article sections
result = wiki_tool.handle_tool_call('get_article_sections', {
    'title': 'United States'
})

# Get random article
result = wiki_tool.handle_tool_call('get_random_article', {})

# Get article links
result = wiki_tool.handle_tool_call('get_article_links', {
    'title': 'Computer science',
    'limit': 10
})
```

## Error Handling

### Disambiguation Pages
When a search term matches multiple articles, the tool returns disambiguation options:
```json
{
  "error": "Disambiguation page",
  "options": ["Python (programming language)", "Python (genus)", "Python (mythology)"]
}
```

### Page Not Found
```json
{
  "error": "Page 'NonexistentArticle' not found"
}
```

## Limitations

- Content limited to prevent overwhelming responses (5000 chars for full content)
- Images are URLs only, not downloaded
- Language currently set to English only
- Rate limiting may apply for excessive requests
- Some special pages may not be accessible


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.