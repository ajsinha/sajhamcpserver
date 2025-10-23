# Web Crawler MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Web Crawler MCP Tool provides comprehensive web scraping and crawling capabilities with advanced redirect handling. Extract content, links, documents, metadata, and structured data from websites with built-in rate limiting and intelligent pattern detection.

## Configuration
- No API key required
- Uses requests and BeautifulSoup4 libraries
- Built-in rate limiting (100 requests per 10 seconds)
- Maximum crawl depth: 3 levels
- Maximum pages per crawl: 100
- Request timeout: 10 seconds
- Automatic redirect handling (up to 10 redirects)

## Available Methods

### Website Crawling

#### 1. crawl_website
Crawl an entire website starting from a URL, exploring up to 3 levels deep with redirect tracking.

**Parameters:**
- `url`: Starting URL to crawl (required)
- `max_depth` (default: 3): Maximum depth to crawl (1-3)
- `max_pages` (default: 50): Maximum number of pages to crawl (1-100)
- `same_domain_only` (default: true): Only crawl pages within the same domain
- `include_external_links` (default: false): Include external links in results
- `extract_metadata` (default: true): Extract page metadata
- `follow_redirects` (default: true): Follow HTTP redirects
- `track_redirects` (default: true): Track and report redirect information

**Returns:**
- Crawl summary (pages crawled, links found)
- Page-by-page results with text content
- Metadata for each page
- Internal and external links
- Redirect summary (total redirects, permanent/temporary counts, redirect chains)

#### 2. crawl_single_page
Crawl a single page and extract its content with redirect tracking.

**Parameters:**
- `url`: URL of the page to crawl (required)
- `extract_links` (default: true): Extract all links from the page
- `extract_metadata` (default: true): Extract page metadata
- `follow_redirects` (default: true): Follow HTTP redirects
- `track_redirects` (default: true): Track redirect information

**Returns:**
- Page text content
- Metadata (title, description, keywords)
- All links with anchor text
- Redirect information if applicable
- Final URL after redirects

### Link Extraction

#### 3. extract_all_links
Extract all hyperlinks from a given page.

**Parameters:**
- `url`: URL to extract links from (required)
- `absolute_urls` (default: true): Convert relative URLs to absolute
- `filter_domain` (optional): Filter links by specific domain
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of links
- List of links with URL, anchor text, and title
- Final URL after redirects
- Duplicate links removed

#### 4. extract_all_document_links
Extract all document links (PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX, TXT) from a page.

**Parameters:**
- `url`: URL to extract document links from (required)
- `document_types` (optional): Filter by specific document types (e.g., ["pdf", "xlsx"])
- `absolute_urls` (default: true): Return absolute URLs
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of documents found
- Document links grouped by type
- Document metadata (URL, type, anchor text, title)
- Final URL after redirects

### Content Extraction

#### 5. extract_images
Extract all images from a page with their attributes.

**Parameters:**
- `url`: URL to extract images from (required)
- `include_alt_text` (default: true): Include alt text for images
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of images
- Image URLs (absolute)
- Alt text and title attributes
- Width and height attributes
- Final page URL after redirects

#### 6. extract_headings
Extract all headings (H1-H6) from a page.

**Parameters:**
- `url`: URL to extract headings from (required)
- `include_hierarchy` (default: true): Organize headings by hierarchy
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of headings
- Headings with level, text, and ID
- Hierarchy organization (H1, H2, H3, etc.)
- Final URL after redirects

#### 7. extract_tables
Extract all tables from a page as structured data.

**Parameters:**
- `url`: URL to extract tables from (required)
- `format` (default: 'json'): Output format - 'json', 'csv', or 'text'
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of tables
- Table data in specified format
- Headers and row data
- Table index for each table

#### 8. get_page_metadata
Extract comprehensive metadata from a page.

**Parameters:**
- `url`: URL to extract metadata from (required)
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Page title
- Meta description
- Meta keywords
- Author information
- Open Graph tags (og:title, og:description, og:image)
- Twitter Card tags
- Viewport settings
- Redirect information

### Search and Analysis

#### 9. search_text_in_page
Search for specific text or patterns within a page.

**Parameters:**
- `url`: URL to search in (required)
- `search_term`: Text or pattern to search for (required)
- `case_sensitive` (default: false): Case sensitive search
- `context_chars` (default: 100): Characters of context around matches
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Total number of matches
- Match position and context
- Matched text
- Limited to 50 matches

### Site Information

#### 10. get_sitemap
Fetch and parse the sitemap.xml of a website.

**Parameters:**
- `url`: Base URL of the website (required)
- `sitemap_url` (optional): Specific sitemap URL
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- Sitemap URL (auto-detected or provided)
- Total URLs in sitemap
- List of URLs from sitemap
- Redirect information if sitemap was redirected

#### 11. get_robots_txt
Fetch and parse the robots.txt file of a website.

**Parameters:**
- `url`: Base URL of the website (required)
- `follow_redirects` (default: true): Follow HTTP redirects

**Returns:**
- robots.txt content
- Parsed rules (user agents, disallowed paths, allowed paths)
- Sitemap references
- Crawl delay if specified
- Redirect information if robots.txt was redirected

### URL Analysis

#### 12. check_url_accessibility
Check if a URL is accessible with enhanced redirect tracking.

**Parameters:**
- `url`: URL to check (required)
- `follow_redirects` (default: true): Follow redirects
- `max_redirects` (default: 10): Maximum number of redirects to follow

**Returns:**
- Accessibility status
- HTTP status code
- Response headers
- Final URL after redirects
- Redirect information (count, chain, pattern)
- Redirect type (301, 302, etc.)

#### 13. trace_redirects
Trace all redirects for a URL and provide detailed analysis.

**Parameters:**
- `url`: URL to trace redirects for (required)
- `max_redirects` (default: 10): Maximum number of redirects to follow

**Returns:**
- Original and final URLs
- Total redirect count
- Redirect pattern (http_to_https, add_www, remove_www, chain, loop_detected)
- Redirect chain details
- Performance metrics (total time in ms)
- Analysis and recommendations

#### 14. get_redirect_chain
Get detailed redirect chain showing each step in the redirect process.

**Parameters:**
- `url`: URL to get redirect chain for (required)
- `include_headers` (default: false): Include HTTP headers for each step
- `max_redirects` (default: 10): Maximum redirects to follow

**Returns:**
- Original and final URLs
- Total number of redirects
- Step-by-step redirect chain
- Status codes and redirect types for each step
- Permanent vs temporary redirect indicators
- Total time in milliseconds

## Data Format Examples

### Crawl Website Response
```json
{
  "start_url": "https://example.com",
  "crawl_date": "2025-10-20T10:30:00",
  "max_depth": 3,
  "pages_crawled": 42,
  "total_internal_links": 156,
  "total_external_links": 23,
  "redirect_summary": {
    "total_redirects": 15,
    "permanent_redirects": 10,
    "temporary_redirects": 5,
    "redirect_chains": [
      {
        "original": "http://example.com/page1",
        "final": "https://www.example.com/page1",
        "steps": 2,
        "pattern": "http_to_https"
      }
    ],
    "redirect_loops": []
  },
  "pages": [
    {
      "url": "https://example.com",
      "final_url": "https://www.example.com",
      "depth": 0,
      "status": 200,
      "text_length": 5678,
      "text_content": "Page content here...",
      "metadata": {
        "title": "Example Domain",
        "description": "Example website for demonstrations"
      },
      "links_found": 12,
      "internal_links": ["https://www.example.com/about", "..."],
      "redirect_info": {
        "was_redirected": true,
        "redirect_count": 1,
        "redirect_pattern": "add_www"
      }
    }
  ]
}
```

### Single Page Crawl Response
```json
{
  "url": "https://example.com/article",
  "final_url": "https://example.com/article",
  "status": 200,
  "text_length": 3456,
  "text_content": "Full article text content...",
  "metadata": {
    "title": "Article Title",
    "description": "Article description",
    "keywords": "keyword1, keyword2",
    "author": "John Doe",
    "og:title": "Article Title",
    "og:image": "https://example.com/image.jpg"
  },
  "links": [
    {
      "url": "https://example.com/related",
      "text": "Related Article",
      "title": "Read more"
    }
  ],
  "link_count": 23
}
```

### Document Links Response
```json
{
  "url": "https://example.com/resources",
  "final_url": "https://example.com/resources",
  "status": 200,
  "total_documents": 12,
  "documents": [
    {
      "url": "https://example.com/files/report.pdf",
      "type": "pdf",
      "text": "Annual Report 2024",
      "title": "Download Report"
    }
  ],
  "by_type": {
    "pdf": [
      {
        "url": "https://example.com/files/report.pdf",
        "type": "pdf",
        "text": "Annual Report 2024",
        "title": "Download Report"
      }
    ],
    "xlsx": [
      {
        "url": "https://example.com/files/data.xlsx",
        "type": "xlsx",
        "text": "Financial Data",
        "title": "Download Spreadsheet"
      }
    ]
  }
}
```

### Trace Redirects Response
```json
{
  "original_url": "http://example.com",
  "final_url": "https://www.example.com",
  "status_code": 200,
  "total_time_ms": 234,
  "redirect_info": {
    "was_redirected": true,
    "redirect_count": 2,
    "redirect_pattern": "http_to_https",
    "permanent_redirect": true,
    "redirect_types": ["Moved Permanently", "Moved Permanently"],
    "redirect_chain": [
      {
        "step": 1,
        "from_url": "http://example.com",
        "to_url": "https://example.com",
        "status_code": 301,
        "redirect_type": "Moved Permanently",
        "is_permanent": true
      },
      {
        "step": 2,
        "from_url": "https://example.com",
        "to_url": "https://www.example.com",
        "status_code": 301,
        "redirect_type": "Moved Permanently",
        "is_permanent": true
      }
    ]
  },
  "analysis": {
    "redirect_count": 2,
    "redirect_pattern": "http_to_https",
    "has_permanent_redirect": true,
    "redirect_types": ["Moved Permanently", "Moved Permanently"]
  },
  "recommendations": [
    "Good: HTTPS redirect is in place",
    "Update links to point to final URL"
  ]
}
```

### Table Extraction Response (JSON format)
```json
{
  "url": "https://example.com/data",
  "status": 200,
  "total_tables": 2,
  "tables": [
    {
      "table_index": 0,
      "headers": ["Name", "Age", "City"],
      "data": [
        {"Name": "John", "Age": "30", "City": "NYC"},
        {"Name": "Jane", "Age": "25", "City": "LA"}
      ],
      "row_count": 2
    }
  ]
}
```

## Example Usage

### Basic Crawling Examples

```python
# Example 1: Crawl a small website
result = crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'max_depth': 2,
    'max_pages': 25,
    'same_domain_only': True
})

print(f"Crawled {result['pages_crawled']} pages")
print(f"Found {result['total_internal_links']} internal links")

# Example 2: Crawl with redirect tracking
result = crawler.handle_tool_call('crawl_website', {
    'url': 'http://example.com',  # Note: HTTP
    'max_depth': 1,
    'track_redirects': True
})

summary = result['redirect_summary']
print(f"Total redirects: {summary['total_redirects']}")
print(f"Permanent: {summary['permanent_redirects']}")
print(f"Temporary: {summary['temporary_redirects']}")
```

### Single Page Extraction Examples

```python
# Example 3: Extract content from a single page
result = crawler.handle_tool_call('crawl_single_page', {
    'url': 'https://example.com/article'
})

print(f"Title: {result['metadata']['title']}")
print(f"Word count: {result['text_length']}")
print(f"Links: {result['link_count']}")

# Example 4: Get page without following redirects
result = crawler.handle_tool_call('crawl_single_page', {
    'url': 'http://example.com',
    'follow_redirects': False,
    'track_redirects': True
})

if result['redirect_info']['was_redirected']:
    print(f"Page redirects to: {result['final_url']}")
```

### Link Extraction Examples

```python
# Example 5: Extract all links from a page
result = crawler.handle_tool_call('extract_all_links', {
    'url': 'https://example.com',
    'filter_domain': 'example.com'
})

print(f"Found {result['total_links']} links")
for link in result['links'][:5]:  # First 5 links
    print(f"  {link['text']}: {link['url']}")

# Example 6: Find all downloadable documents
result = crawler.handle_tool_call('extract_all_document_links', {
    'url': 'https://example.com/resources',
    'document_types': ['pdf', 'xlsx', 'docx']
})

print(f"Total documents: {result['total_documents']}")
for doc_type, docs in result['by_type'].items():
    print(f"\n{doc_type.upper()} files: {len(docs)}")
    for doc in docs[:3]:  # First 3 of each type
        print(f"  - {doc['text']}: {doc['url']}")
```

### Content Analysis Examples

```python
# Example 7: Extract and analyze page structure
result = crawler.handle_tool_call('extract_headings', {
    'url': 'https://example.com/article',
    'include_hierarchy': True
})

print("Document Structure:")
for level, headings in result['hierarchy'].items():
    if headings:
        print(f"\n{level.upper()}:")
        for heading in headings:
            print(f"  - {heading}")

# Example 8: Extract all images
result = crawler.handle_tool_call('extract_images', {
    'url': 'https://example.com/gallery',
    'include_alt_text': True
})

print(f"Found {result['total_images']} images")
for img in result['images'][:5]:
    print(f"  {img['alt']}: {img['url']}")

# Example 9: Extract tables as JSON
result = crawler.handle_tool_call('extract_tables', {
    'url': 'https://example.com/data',
    'format': 'json'
})

for table in result['tables']:
    print(f"\nTable {table['table_index']}:")
    print(f"  Headers: {table['headers']}")
    print(f"  Rows: {table['row_count']}")
    for row in table['data'][:3]:  # First 3 rows
        print(f"  {row}")
```

### Search and Metadata Examples

```python
# Example 10: Search for text within a page
result = crawler.handle_tool_call('search_text_in_page', {
    'url': 'https://example.com/article',
    'search_term': 'machine learning',
    'case_sensitive': False,
    'context_chars': 150
})

print(f"Found {result['total_matches']} matches for '{result['search_term']}'")
for match in result['matches'][:3]:
    print(f"\nPosition {match['position']}:")
    print(f"  {match['context']}")

# Example 11: Extract comprehensive metadata
result = crawler.handle_tool_call('get_page_metadata', {
    'url': 'https://example.com'
})

metadata = result['metadata']
print(f"Title: {metadata.get('title')}")
print(f"Description: {metadata.get('description')}")
print(f"Keywords: {metadata.get('keywords')}")
print(f"OG Image: {metadata.get('og:image')}")
print(f"Author: {metadata.get('author')}")
```

### Site Analysis Examples

```python
# Example 12: Check robots.txt compliance
result = crawler.handle_tool_call('get_robots_txt', {
    'url': 'https://example.com'
})

rules = result['rules']
print("Crawl Rules:")
print(f"  User Agents: {rules['user_agents']}")
print(f"  Disallowed: {rules['disallowed']}")
print(f"  Crawl Delay: {rules['crawl_delay']}")
print(f"  Sitemaps: {rules['sitemaps']}")

# Example 13: Get sitemap URLs
result = crawler.handle_tool_call('get_sitemap', {
    'url': 'https://example.com'
})

print(f"Sitemap URL: {result['sitemap_url']}")
print(f"Total URLs: {result['total_urls']}")
print("\nFirst 10 URLs:")
for url in result['urls'][:10]:
    print(f"  - {url}")
```

### Redirect Analysis Examples

```python
# Example 14: Check URL accessibility and redirects
result = crawler.handle_tool_call('check_url_accessibility', {
    'url': 'http://example.com',
    'follow_redirects': True
})

print(f"Accessible: {result['accessible']}")
print(f"Status: {result['status_code']}")
print(f"Final URL: {result['final_url']}")

if result['was_redirected']:
    print(f"Redirects: {result['redirect_count']}")
    print(f"Pattern: {result['redirect_info']['redirect_pattern']}")

# Example 15: Trace redirect chain
result = crawler.handle_tool_call('trace_redirects', {
    'url': 'http://example.com'
})

print(f"Original: {result['original_url']}")
print(f"Final: {result['final_url']}")
print(f"Time: {result['total_time_ms']}ms")
print(f"Pattern: {result['redirect_info']['redirect_pattern']}")

print("\nRecommendations:")
for rec in result.get('recommendations', []):
    print(f"  💡 {rec}")

# Example 16: Get detailed redirect chain
result = crawler.handle_tool_call('get_redirect_chain', {
    'url': 'http://example.com/old-page',
    'include_headers': False
})

print(f"Total redirects: {result['total_redirects']}")
print(f"Time: {result['total_time_ms']}ms\n")

for step in result['redirect_chain']:
    print(f"Step {step['step']}: {step['url']}")
    print(f"  Status: {step['status_code']} - {step.get('status_text', '')}")
    if step.get('location'):
        print(f"  → {step['location']}")
    if step.get('is_permanent'):
        print(f"  ⚠️ Permanent redirect")
```

### Advanced Use Cases

```python
# Example 17: SEO Audit - Find pages needing updates
result = crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'max_depth': 2,
    'track_redirects': True
})

updates_needed = []
for page in result['pages']:
    if page.get('redirect_info', {}).get('permanent_redirect'):
        updates_needed.append({
            'old': page['url'],
            'new': page['final_url']
        })

print(f"Pages needing link updates: {len(updates_needed)}")
for update in updates_needed[:5]:
    print(f"  {update['old']} → {update['new']}")

# Example 18: Competitive Analysis
competitors = [
    'https://competitor1.com',
    'https://competitor2.com',
    'https://competitor3.com'
]

for url in competitors:
    result = crawler.handle_tool_call('crawl_single_page', {'url': url})
    metadata = result.get('metadata', {})
    
    print(f"\n{url}:")
    print(f"  Title: {metadata.get('title')}")
    print(f"  Description: {metadata.get('description')}")
    print(f"  Links: {result['link_count']}")

# Example 19: Document Harvesting
result = crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'max_depth': 3,
    'max_pages': 100
})

all_documents = []
for page in result['pages']:
    doc_result = crawler.handle_tool_call('extract_all_document_links', {
        'url': page['url']
    })
    all_documents.extend(doc_result.get('documents', []))

print(f"Total documents found: {len(all_documents)}")
for doc_type in ['pdf', 'xlsx', 'docx']:
    type_docs = [d for d in all_documents if d['type'] == doc_type]
    print(f"  {doc_type.upper()}: {len(type_docs)}")

# Example 20: Link Validation
result = crawler.handle_tool_call('extract_all_links', {
    'url': 'https://example.com'
})

broken_links = []
for link in result['links']:
    check = crawler.handle_tool_call('check_url_accessibility', {
        'url': link['url'],
        'follow_redirects': True
    })
    
    if not check['accessible']:
        broken_links.append({
            'url': link['url'],
            'text': link['text'],
            'status': check.get('status_code', 'N/A')
        })

print(f"Broken links found: {len(broken_links)}")
for broken in broken_links[:5]:
    print(f"  [{broken['status']}] {broken['text']}: {broken['url']}")
```

### Batch Processing Examples

```python
# Example 21: Batch URL processing with rate limiting
import time

urls_to_crawl = [
    'https://example1.com',
    'https://example2.com',
    'https://example3.com'
]

results = []
for url in urls_to_crawl:
    result = crawler.handle_tool_call('crawl_single_page', {
        'url': url,
        'extract_metadata': True
    })
    results.append(result)
    time.sleep(1)  # Respect rate limits

print(f"Processed {len(results)} URLs")

# Example 22: Sitemap-based crawling
sitemap = crawler.handle_tool_call('get_sitemap', {
    'url': 'https://example.com'
})

for url in sitemap['urls'][:50]:  # First 50 URLs
    page = crawler.handle_tool_call('crawl_single_page', {
        'url': url
    })
    # Process page...
    time.sleep(0.5)
```

## Redirect Patterns Detected

The tool automatically detects these redirect patterns:

1. **simple** - Single redirect from one URL to another
2. **http_to_https** - Security upgrade from HTTP to HTTPS
3. **add_www** - Redirect from non-www to www version
4. **remove_www** - Redirect from www to non-www version
5. **chain** - Multiple redirects (3+) in sequence
6. **loop_detected** - Circular redirects (infinite loop)
7. **multiple** - Two redirects in sequence

## Best Practices

### 1. Respect Rate Limits
```python
# Built-in rate limiting: 100 requests per 10 seconds
# Add additional delays for large crawls
import time

for url in url_list:
    result = crawler.handle_tool_call('crawl_single_page', {'url': url})
    time.sleep(1)  # Additional courtesy delay
```

### 2. Check robots.txt First
```python
# Always check robots.txt before crawling
robots = crawler.handle_tool_call('get_robots_txt', {
    'url': 'https://example.com'
})

if '/private/' in robots['rules']['disallowed']:
    print("Respecting robots.txt disallow rules")
```

### 3. Use Appropriate Crawl Depth
```python
# Depth 1: Quick survey
crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'max_depth': 1,
    'max_pages': 10
})

# Depth 3: Comprehensive (use sparingly)
crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'max_depth': 3,
    'max_pages': 100
})
```

### 4. Handle Redirects Appropriately
```python
# Track redirects for SEO audits
result = crawler.handle_tool_call('crawl_website', {
    'url': 'http://example.com',
    'track_redirects': True
})

# Use final URLs for link updates
for page in result['pages']:
    if page.get('redirect_info', {}).get('permanent_redirect'):
        print(f"Update: {page['url']} → {page['final_url']}")
```

### 5. Filter Content Efficiently
```python
# Only extract what you need
result = crawler.handle_tool_call('crawl_single_page', {
    'url': 'https://example.com',
    'extract_links': False,  # Skip if not needed
    'extract_metadata': False  # Skip if not needed
})

# Filter document types
docs = crawler.handle_tool_call('extract_all_document_links', {
    'url': 'https://example.com',
    'document_types': ['pdf']  # Only PDFs
})
```

## Error Handling

### Common Errors and Solutions

#### Rate Limit Exceeded (429)
```python
result = crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com'
})

if result.get('status') == 429:
    print("Rate limit exceeded - waiting 10 seconds")
    time.sleep(10)
    # Retry
```

#### Invalid URL Format
```python
# Always include protocol
url = 'https://example.com'  # ✓ Correct
url = 'example.com'           # ✗ Wrong

if not url.startswith(('http://', 'https://')):
    url = 'https://' + url
```

#### Failed to Fetch Page
```python
result = crawler.handle_tool_call('crawl_single_page', {
    'url': 'https://example.com'
})

if 'error' in result:
    print(f"Error: {result['error']}")
    print(f"Status: {result.get('status', 'N/A')}")
```

#### Too Many Redirects
```python
result = crawler.handle_tool_call('trace_redirects', {
    'url': 'http://example.com',
    'max_redirects': 5  # Lower limit to catch loops
})

if 'error' in result and 'loop' in result['error'].lower():
    print("Redirect loop detected!")
```

## Performance Optimization

### 1. Use HEAD Requests for Checking
```python
# Fast redirect checking without fetching content
result = crawler.handle_tool_call('trace_redirects', {
    'url': 'http://example.com'
})
# Uses HEAD request - much faster
```

### 2. Disable Unnecessary Features
```python
result = crawler.handle_tool_call('crawl_website', {
    'url': 'https://example.com',
    'extract_metadata': False,  # Skip if not needed
    'track_redirects': False,    # Skip if not needed
    'include_external_links': False  # Skip if not needed
})
```

### 3. Use Sitemap for Efficient Crawling
```python
# Get all URLs from sitemap
sitemap = crawler.handle_tool_call('get_sitemap', {
    'url': 'https://example.com'
})

# Crawl specific URLs instead of entire site
for url in sitemap['urls'][:25]:
    # Process...
```

## Limitations

- **JavaScript Rendering**: Does not execute JavaScript (static HTML only)
- **Authentication**: Does not support authenticated pages
- **Dynamic Content**: Cannot handle AJAX-loaded content
- **File Download**: Extracts document links but doesn't download files
- **Crawl Depth**: Maximum depth limited to 3 levels
- **Page Limit**: Maximum 100 pages per crawl session
- **Rate Limiting**: 100 requests per 10-second window
- **Timeout**: 10-second timeout per request
- **Memory**: Large crawls consume significant memory
- **Redirect Loops**: Detected but may cause delays before timeout

## Use Cases

### SEO Optimization
- Audit redirect chains
- Find broken links
- Analyze page structure
- Extract metadata for optimization

### Content Migration
- Map old URLs to new URLs
- Verify redirect implementation
- Extract content for migration
- Find all document links

### Competitive Analysis
- Analyze competitor site structure
- Extract metadata and keywords
- Monitor content changes
- Compare redirect strategies

### Data Extraction
- Extract structured data from tables
- Harvest document links
- Collect image URLs
- Build site maps

### Link Validation
- Check for broken links
- Verify external links
- Monitor link changes
- Audit internal linking

## Security Considerations

- **Respect robots.txt**: Always check and follow robots.txt rules
- **Rate Limiting**: Built-in protection against overwhelming servers
- **User Agent**: Identifies as 'MCPWebCrawler/1.0'
- **Timeout Protection**: Prevents hanging on unresponsive servers
- **No Authentication**: Does not bypass login requirements
- **Public Data Only**: Only accesses publicly available content

## Support and Resources

- BeautifulSoup Documentation: https://www.crummy.com/software/BeautifulSoup/
- Requests Library: https://docs.python-requests.org/
- robots.txt Specification: https://www.robotstxt.org/
- Sitemap Protocol: https://www.sitemaps.org/

## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.