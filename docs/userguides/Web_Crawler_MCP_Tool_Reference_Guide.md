# Web Crawler MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030 Ashutosh Sinha, Email: ajsinha@gmail.com**

**Version:** 1.0.0  
**Last Updated:** October 31, 2025

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Tool Categories](#tool-categories)
4. [Technical Implementation](#technical-implementation)
5. [Tool Details](#tool-details)
6. [Authentication & API Keys](#authentication--api-keys)
7. [Rate Limiting & Politeness](#rate-limiting--politeness)
8. [Limitations](#limitations)
9. [Usage Examples](#usage-examples)
10. [Best Practices](#best-practices)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The Web Crawler MCP (Model Context Protocol) Tool is a comprehensive suite of Python-based tools designed for ethical and efficient web scraping, crawling, and content extraction. It provides a modular architecture with seven specialized tools that can be used independently or in combination for various web data gathering tasks.

### Key Features

- ✅ **Ethical Crawling**: Built-in robots.txt compliance
- ✅ **Modular Design**: Seven independent tools for specific tasks
- ✅ **Rate Limiting**: Configurable delays to respect server resources
- ✅ **No Dependencies**: Uses Python standard library (urllib, HTMLParser)
- ✅ **No Authentication**: No API keys or credentials required
- ✅ **Comprehensive Metadata**: Extracts titles, descriptions, keywords, headings
- ✅ **Flexible Crawling**: Recursive crawling with depth control
- ✅ **Sitemap Support**: Direct sitemap.xml parsing

### Working Mechanism

**Method:** Web Scraping & Crawling  
**Protocol:** HTTP/HTTPS  
**Authentication:** None required  
**Data Source:** Direct website HTML parsing  
**Dependencies:** Python standard library only

The tools work by:
1. Making HTTP requests to target URLs
2. Parsing HTML content using Python's built-in HTMLParser
3. Extracting structured data (links, metadata, text)
4. Following links recursively (when configured)
5. Respecting crawl delays and robots.txt rules

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Tool Framework                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              BaseMCPTool (Abstract)                        │  │
│  │  - Configuration Management                                │  │
│  │  - Input/Output Schema Validation                          │  │
│  │  - Execution Tracking & Metrics                            │  │
│  │  - Enable/Disable Control                                  │  │
│  └────────────────────┬──────────────────────────────────────┘  │
│                       │                                          │
│                       │ inherits                                 │
│                       ▼                                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │        WebCrawlerBaseTool (Shared Functionality)          │  │
│  │  - URL Validation & Normalization                          │  │
│  │  - HTTP Request Handling (urllib)                          │  │
│  │  - Domain Comparison                                       │  │
│  │  - User-Agent Management                                   │  │
│  │  - Timeout & Delay Configuration                           │  │
│  └────────────────────┬──────────────────────────────────────┘  │
│                       │                                          │
│          ┌────────────┴────────────┐                            │
│          │ inherits                │                            │
│          ▼                         ▼                            │
│  ┌───────────────┐         ┌──────────────────┐                │
│  │  LinkExtractor│         │  HTML Parser     │                │
│  │  (HTMLParser) │         │  Utilities       │                │
│  │  - Links      │         │  - Text Extract  │                │
│  │  - Images     │         │  - Metadata      │                │
│  │  - Metadata   │         │  - Sitemap Parse │                │
│  │  - Headings   │         │  - Robots.txt    │                │
│  └───────────────┘         └──────────────────┘                │
│          │                         │                            │
│          └────────────┬────────────┘                            │
│                       │                                          │
│          ┌────────────┴────────────────────────┐                │
│          │    Individual Tool Implementations  │                │
│          └─────────────────────────────────────┘                │
└──────────────────────┬──────────────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    │                  │                  │
    ▼                  ▼                  ▼
┌─────────┐    ┌─────────────┐    ┌─────────────┐
│  crawl_ │    │   extract_  │    │   crawl_    │
│   url   │    │    links    │    │  sitemap    │
└─────────┘    └─────────────┘    └─────────────┘
    │                  │                  │
    ▼                  ▼                  ▼
┌─────────┐    ┌─────────────┐    ┌─────────────┐
│ extract_│    │  extract_   │    │   check_    │
│ content │    │  metadata   │    │ robots_txt  │
└─────────┘    └─────────────┘    └─────────────┘
    │
    ▼
┌─────────┐
│  get_   │
│  page_  │
│  info   │
└─────────┘
```

### Class Hierarchy

```python
BaseMCPTool (Abstract Base Class)
    │
    ├── Properties: name, description, version, enabled
    ├── Methods: execute(), validate_arguments(), get_metrics()
    └── Configuration: load_from_config()
        │
        └── WebCrawlerBaseTool (Shared Web Crawling Logic)
            │
            ├── Properties: max_depth, default_timeout, user_agent
            ├── Methods: _is_valid_url(), _fetch_url(), _normalize_url()
            └── URL Handling: domain comparison, link resolution
                │
                ├── CrawlURLTool (Recursive Website Crawler)
                ├── ExtractLinksTool (Link Extraction)
                ├── ExtractContentTool (Content Extraction)
                ├── ExtractMetadataTool (Metadata Extraction)
                ├── CrawlSitemapTool (Sitemap Parser)
                ├── CheckRobotsTxtTool (Robots.txt Checker)
                └── GetPageInfoTool (Comprehensive Page Analysis)
```

### Component Flow Diagram

```
User Request
    │
    ▼
┌────────────────┐
│  MCP Protocol  │  ◄── JSON-RPC Format
└────────┬───────┘
         │
         ▼
┌────────────────┐
│  Tool Router   │  ◄── Selects appropriate tool
└────────┬───────┘
         │
         ▼
┌────────────────────────┐
│  Argument Validation   │  ◄── Validates against input schema
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Tool Execution        │
│  ┌──────────────────┐  │
│  │ 1. Check Config  │  │
│  │ 2. Validate URL  │  │
│  │ 3. Check Robots  │  │  (if respect_robots = true)
│  │ 4. HTTP Request  │  │
│  │ 5. Parse HTML    │  │
│  │ 6. Extract Data  │  │
│  │ 7. Apply Delay   │  │  (politeness)
│  └──────────────────┘  │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Result Formatting     │  ◄── Matches output schema
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Return JSON Response  │
└────────────────────────┘
```

---

## Tool Categories

### 1. Core Crawling Tools

| Tool | Purpose | Max Depth | Max Pages |
|------|---------|-----------|-----------|
| **crawl_url** | Recursive website crawling | 3 levels | 100 pages |
| **crawl_sitemap** | Sitemap parsing | N/A | Unlimited |

### 2. Content Extraction Tools

| Tool | Purpose | Output |
|------|---------|--------|
| **extract_links** | Link extraction | All URLs on page |
| **extract_content** | Text content extraction | Clean text + structure |
| **extract_metadata** | SEO metadata extraction | Title, description, keywords |

### 3. Analysis & Compliance Tools

| Tool | Purpose | Use Case |
|------|---------|----------|
| **check_robots_txt** | Robots.txt compliance | Pre-crawl permission check |
| **get_page_info** | Comprehensive page analysis | SEO auditing, monitoring |

---

## Technical Implementation

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **HTTP Client** | `urllib.request` | Making web requests |
| **HTML Parser** | `HTMLParser` | Parsing HTML content |
| **URL Handling** | `urllib.parse` | URL manipulation |
| **Robots.txt** | `urllib.robotparser` | Robots.txt compliance |
| **Data Structures** | `deque`, `set` | Efficient crawling |
| **Date/Time** | `datetime` | Timestamps |
| **JSON** | `json` | Configuration & output |

### No External Dependencies Required

The tool is built entirely on Python's standard library, making it:
- ✅ Easy to deploy (no pip install required)
- ✅ Lightweight (minimal footprint)
- ✅ Secure (no third-party code)
- ✅ Portable (works anywhere Python runs)

### Data Flow

```
Input (JSON Arguments)
    │
    ▼
┌─────────────────────┐
│ Argument Validation │
│ - Check required    │
│ - Validate types    │
│ - Apply defaults    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  URL Validation     │
│ - Parse URL         │
│ - Check scheme      │
│ - Validate domain   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Robots.txt Check    │  (if enabled)
│ - Fetch robots.txt  │
│ - Parse rules       │
│ - Check permission  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  HTTP Request       │
│ - Set headers       │
│ - Set user-agent    │
│ - Apply timeout     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  HTML Parsing       │
│ - Feed to parser    │
│ - Extract elements  │
│ - Build structure   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Data Processing    │
│ - Normalize URLs    │
│ - Filter content    │
│ - Format output     │
└──────────┬──────────┘
           │
           ▼
Output (JSON Response)
```

---

## Tool Details

### 1. check_robots_txt

**Purpose:** Check robots.txt file to determine if web crawling is allowed and get crawl delay recommendations.

**Working Method:** API-like call to robots.txt endpoint, parsed using RobotFileParser.

#### Input Schema

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "URL to check (can be base domain or specific path)",
      "required": true
    },
    "user_agent": {
      "type": "string",
      "description": "User agent string to check rules for",
      "default": "Mozilla/5.0 (compatible; WebCrawlerTool/1.0)",
      "required": false
    }
  }
}
```

#### Output Schema

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "The URL that was checked"
    },
    "robots_url": {
      "type": "string",
      "description": "The robots.txt URL that was consulted"
    },
    "can_fetch": {
      "type": "boolean",
      "description": "Whether crawling is allowed"
    },
    "user_agent": {
      "type": "string",
      "description": "User agent that was checked"
    },
    "crawl_delay": {
      "type": ["number", "null"],
      "description": "Suggested crawl delay in seconds (null if not specified)"
    },
    "checked_at": {
      "type": "string",
      "description": "ISO timestamp when check was performed"
    },
    "note": {
      "type": "string",
      "description": "Additional notes (e.g., if robots.txt not found)"
    },
    "error": {
      "type": "string",
      "description": "Error message if robots.txt couldn't be read"
    }
  }
}
```

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import CheckRobotsTxtTool

tool = CheckRobotsTxtTool()
result = tool.execute({
    "url": "https://example.com/admin",
    "user_agent": "MyBot/1.0"
})

print(f"Can crawl: {result['can_fetch']}")
print(f"Crawl delay: {result['crawl_delay']} seconds")
```

#### Metadata

- **Rate Limit:** 60 requests/minute
- **Cache TTL:** 86400 seconds (24 hours)
- **Category:** Web Scraping
- **Tags:** robots.txt, crawling rules, politeness, web ethics, SEO

---

### 2. crawl_sitemap

**Purpose:** Crawl and extract all URLs from a website's sitemap.xml file for complete site structure overview.

**Working Method:** Direct HTTP request to sitemap.xml, XML parsing to extract URLs.

#### Input Schema

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "Base website URL or direct sitemap URL",
      "examples": ["https://example.com", "https://example.com/sitemap.xml"],
      "required": true
    }
  }
}
```

#### Output Schema

```json
{
  "type": "object",
  "properties": {
    "sitemap_url": {
      "type": "string",
      "description": "The sitemap URL that was successfully crawled"
    },
    "status_code": {
      "type": "integer",
      "description": "HTTP status code"
    },
    "url_count": {
      "type": "integer",
      "description": "Total number of URLs found in the sitemap"
    },
    "urls": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Complete list of URLs extracted from the sitemap"
    },
    "retrieved_at": {
      "type": "string",
      "description": "ISO timestamp when sitemap was retrieved"
    },
    "error": {
      "type": "string",
      "description": "Error message if sitemap couldn't be found or parsed"
    },
    "attempted_urls": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of sitemap URLs that were attempted"
    }
  }
}
```

#### Automatic Sitemap Discovery

The tool automatically tries these common sitemap locations:
1. `/sitemap.xml`
2. `/sitemap_index.xml`
3. `/sitemap1.xml`
4. `/post-sitemap.xml`
5. `/page-sitemap.xml`

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import CrawlSitemapTool

tool = CrawlSitemapTool()
result = tool.execute({
    "url": "https://example.com"
})

print(f"Found {result['url_count']} URLs")
for url in result['urls'][:5]:
    print(f"  - {url}")
```

#### Metadata

- **Rate Limit:** 60 requests/minute
- **Cache TTL:** 3600 seconds (1 hour)
- **Category:** Web Scraping
- **Tags:** sitemap, xml, urls, site structure, crawling, discovery

---

### 3. crawl_url

**Purpose:** Recursively crawl a website starting from a URL, following links up to a specified depth (max 3 levels).

**Working Method:** Breadth-first web crawling with HTML parsing and link following.

#### Input Schema

```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "Starting URL to crawl",
      "required": true
    },
    "max_depth": {
      "type": "integer",
      "description": "Maximum crawl depth (0-3)",
      "default": 1,
      "minimum": 0,
      "maximum": 3
    },
    "max_pages": {
      "type": "integer",
      "description": "Maximum number of pages to crawl",
      "default": 10,
      "minimum": 1,
      "maximum": 100
    },
    "follow_external": {
      "type": "boolean",
      "description": "Follow links to external domains",
      "default": false
    },
    "respect_robots": {
      "type": "boolean",
      "description": "Respect robots.txt rules",
      "default": true
    },
    "extract_images": {
      "type": "boolean",
      "description": "Extract and include image URLs",
      "default": true
    },
    "extract_text": {
      "type": "boolean",
      "description": "Extract text content previews",
      "default": true
    },
    "delay": {
      "type": "number",
      "description": "Delay between requests in seconds",
      "default": 1.0,
      "minimum": 0.5,
      "maximum": 5.0
    },
    "timeout": {
      "type": "integer",
      "description": "Request timeout in seconds",
      "default": 10,
      "minimum": 5,
      "maximum": 30
    }
  }
}
```

#### Output Schema

```json
{
  "type": "object",
  "properties": {
    "start_url": {
      "type": "string",
      "description": "Starting URL that was crawled"
    },
    "max_depth": {
      "type": "integer",
      "description": "Maximum depth setting used"
    },
    "max_pages": {
      "type": "integer",
      "description": "Maximum pages limit"
    },
    "pages_crawled": {
      "type": "integer",
      "description": "Actual number of pages successfully crawled"
    },
    "pages": {
      "type": "array",
      "description": "Detailed information about each crawled page",
      "items": {
        "type": "object",
        "properties": {
          "url": {"type": "string"},
          "depth": {"type": "integer"},
          "status_code": {"type": "integer"},
          "title": {"type": "string"},
          "meta_description": {"type": "string"},
          "link_count": {"type": "integer"},
          "image_count": {"type": "integer"},
          "images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Sample image URLs (up to 10)"
          },
          "text_preview": {
            "type": "string",
            "description": "Text content preview (first 500 chars)"
          },
          "crawled_at": {"type": "string"}
        }
      }
    },
    "follow_external": {"type": "boolean"},
    "respect_robots": {"type": "boolean"},
    "crawl_duration": {
      "type": "number",
      "description": "Total crawl time in seconds"
    },
    "completed_at": {"type": "string"}
  }
}
```

#### Crawl Depth Explanation

- **Depth 0:** Only the starting page
- **Depth 1:** Starting page + all pages linked directly from it
- **Depth 2:** Depth 1 + all pages linked from depth 1 pages
- **Depth 3:** Depth 2 + all pages linked from depth 2 pages (maximum)

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import CrawlURLTool

tool = CrawlURLTool()
result = tool.execute({
    "url": "https://example.com/blog",
    "max_depth": 2,
    "max_pages": 50,
    "delay": 2.0,
    "respect_robots": True
})

print(f"Crawled {result['pages_crawled']} pages in {result['crawl_duration']:.2f}s")
for page in result['pages']:
    print(f"[Depth {page['depth']}] {page['title']}: {page['url']}")
```

#### Metadata

- **Rate Limit:** 30 requests/minute
- **Cache TTL:** 1800 seconds (30 minutes)
- **Category:** Web Scraping
- **Tags:** crawler, scraper, website, recursive, links, sitemap

---

### 4. extract_links

**Purpose:** Extract all links from a single web page with detailed information.

**Working Method:** HTML parsing to extract anchor tags and href attributes.

#### Key Features

- Extracts internal and external links
- Categorizes link types (same domain, external, anchor)
- Returns absolute URLs
- Provides link text/titles
- Handles relative URLs

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import ExtractLinksTool

tool = ExtractLinksTool()
result = tool.execute({
    "url": "https://example.com"
})

print(f"Total links: {result['link_count']}")
print(f"Internal: {result['internal_link_count']}")
print(f"External: {result['external_link_count']}")
```

---

### 5. extract_content

**Purpose:** Extract clean text content from a web page, removing HTML tags and scripts.

**Working Method:** HTML parsing with script/style removal and text extraction.

#### Key Features

- Removes scripts, styles, and navigation
- Extracts main content text
- Preserves paragraph structure
- Returns word count
- Provides text preview

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import ExtractContentTool

tool = ExtractContentTool()
result = tool.execute({
    "url": "https://example.com/article"
})

print(f"Word count: {result['word_count']}")
print(f"Content:\n{result['text_content'][:500]}...")
```

---

### 6. extract_metadata

**Purpose:** Extract SEO and structural metadata from a web page.

**Working Method:** HTML parsing to extract meta tags, Open Graph, and Twitter Card data.

#### Extracted Metadata

- Page title
- Meta description
- Meta keywords
- Open Graph tags (og:title, og:description, og:image, og:type)
- Twitter Card tags
- Canonical URL
- Language
- Author
- Headings (H1, H2, H3)

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import ExtractMetadataTool

tool = ExtractMetadataTool()
result = tool.execute({
    "url": "https://example.com"
})

print(f"Title: {result['title']}")
print(f"Description: {result['meta_description']}")
print(f"OG Image: {result['og_image']}")
```

---

### 7. get_page_info

**Purpose:** Get comprehensive information about a web page including metadata, structure, and statistics.

**Working Method:** Combined HTML parsing for complete page analysis.

#### Comprehensive Analysis Includes

- HTTP status code and content type
- Page title and meta tags
- Heading statistics (H1, H2, H3 counts)
- Link count
- Image count
- Content length
- Full heading samples

#### Usage Example

```python
from tools.impl.webcrawler_tool_refactored import GetPageInfoTool

tool = GetPageInfoTool()
result = tool.execute({
    "url": "https://example.com"
})

print(f"Status: {result['status_code']}")
print(f"Title: {result['title']}")
print(f"H1 Count: {result['headings']['h1_count']}")
print(f"Links: {result['link_count']}")
print(f"Images: {result['image_count']}")
```

---

## Authentication & API Keys

### No Authentication Required

The Web Crawler MCP Tool **does not require** any:
- ❌ API Keys
- ❌ Authentication tokens
- ❌ User credentials
- ❌ OAuth flows
- ❌ Service accounts

### Why No Authentication?

The tool operates by:
1. Making standard HTTP requests (like a web browser)
2. Parsing publicly accessible HTML content
3. Following the same protocols as search engine crawlers

### User-Agent Configuration

While no authentication is needed, the tool uses a standard user-agent string:

```python
user_agent = 'Mozilla/5.0 (compatible; WebCrawlerTool/1.0)'
```

You can customize the user-agent when calling `check_robots_txt`:

```python
result = tool.execute({
    "url": "https://example.com",
    "user_agent": "MyCompanyBot/2.0 (+https://mycompany.com/bot)"
})
```

### Accessing Protected Content

**Important:** This tool cannot access:
- Password-protected pages
- Login-required content
- API endpoints requiring authentication
- Content behind paywalls
- Private intranets

For such content, you would need specialized tools or manual authentication setup.

---

## Rate Limiting & Politeness

### Built-in Politeness Features

The tool is designed to be a "good citizen" of the web:

#### 1. Configurable Delays

```python
# Default delay: 1 second between requests
result = tool.execute({
    "url": "https://example.com",
    "delay": 2.0  # 2 seconds between requests
})
```

**Recommended Delays:**
- Light crawling (< 10 pages): 1.0 seconds
- Medium crawling (10-50 pages): 2.0 seconds
- Heavy crawling (50-100 pages): 3.0-5.0 seconds

#### 2. Robots.txt Compliance

```python
result = tool.execute({
    "url": "https://example.com",
    "respect_robots": True  # Default: True
})
```

The tool automatically:
- Checks robots.txt before crawling
- Respects Disallow rules
- Honors Crawl-delay directives
- Follows User-agent specific rules

#### 3. Request Timeouts

```python
result = tool.execute({
    "url": "https://example.com",
    "timeout": 15  # 15 second timeout
})
```

Prevents hanging on slow servers.

#### 4. Page Limits

```python
result = tool.execute({
    "url": "https://example.com",
    "max_pages": 50  # Maximum 100 pages
})
```

Hard limit: 100 pages per crawl session.

### Rate Limit Guidelines

| Tool | Recommended Rate | Max Rate |
|------|------------------|----------|
| check_robots_txt | 60/minute | 60/minute |
| crawl_sitemap | 60/minute | 60/minute |
| crawl_url | 30/minute | 30/minute |
| extract_* tools | 60/minute | 60/minute |
| get_page_info | 60/minute | 60/minute |

### Best Practices for Politeness

1. **Always respect robots.txt** (keep `respect_robots=true`)
2. **Use appropriate delays** (minimum 1 second between requests)
3. **Limit concurrent crawls** (don't run multiple tools simultaneously on same domain)
4. **Crawl during off-peak hours** (if doing large crawls)
5. **Set meaningful user-agent** (identifies your bot clearly)
6. **Honor crawl-delay directives** (if specified in robots.txt)
7. **Use sitemap when available** (more efficient than crawling)
8. **Cache results appropriately** (avoid repeat requests)

### Example: Polite Crawling Configuration

```python
# Highly polite configuration for production use
result = tool.execute({
    "url": "https://example.com",
    "max_depth": 2,
    "max_pages": 25,
    "follow_external": False,
    "respect_robots": True,
    "delay": 3.0,
    "timeout": 15
})
```

---

## Limitations

### Technical Limitations

#### 1. Depth Limitation
- **Maximum depth:** 3 levels
- **Reason:** Prevents infinite crawl loops and excessive resource use
- **Workaround:** Use sitemap for deeper site discovery

#### 2. Page Count Limitation
- **Maximum pages:** 100 per crawl session
- **Reason:** Prevents abuse and ensures reasonable execution time
- **Workaround:** Split large crawls into multiple sessions

#### 3. JavaScript Content
- **Limitation:** Cannot execute JavaScript
- **Impact:** Dynamic content loaded via JS won't be captured
- **Affected sites:** Single-page apps (SPAs), React/Vue/Angular sites
- **Workaround:** Use specialized tools like Selenium/Puppeteer

#### 4. Authentication
- **Limitation:** No login/authentication support
- **Impact:** Cannot access protected content
- **Workaround:** Use authenticated HTTP clients or browser automation

#### 5. AJAX Requests
- **Limitation:** Cannot capture AJAX-loaded content
- **Impact:** Content loaded after page load won't be visible
- **Workaround:** Use browser automation or reverse-engineer API calls

### Content Limitations

#### 1. Binary Content
- **PDF files:** Not parsed (requires separate PDF parser)
- **Images:** URLs extracted but not analyzed
- **Videos:** Links extracted but not processed
- **Audio:** Not processed

#### 2. Frames and Iframes
- **Limitation:** Content inside iframes not fully parsed
- **Workaround:** Crawl iframe sources separately

#### 3. Shadow DOM
- **Limitation:** Shadow DOM content not accessible
- **Impact:** Web components may not be fully parsed

### Network Limitations

#### 1. Timeout Constraints
- **Maximum timeout:** 30 seconds
- **Impact:** Very slow sites may fail
- **Workaround:** Increase timeout to maximum or try during off-peak

#### 2. No Proxy Support
- **Limitation:** Direct connections only (no proxy)
- **Impact:** Cannot bypass geo-restrictions
- **Workaround:** Use VPN or modify code to add proxy support

#### 3. SSL/TLS
- **Requirement:** Valid SSL certificates required
- **Impact:** Self-signed certificates will fail
- **Workaround:** Add SSL verification bypass (not recommended)

### Legal and Ethical Limitations

#### 1. Terms of Service
- **Limitation:** Tool doesn't check Terms of Service
- **Responsibility:** User must ensure compliance with ToS
- **Risk:** Legal action if ToS prohibits scraping

#### 2. Copyright
- **Limitation:** No automatic copyright checking
- **Responsibility:** User responsible for respecting copyright
- **Best practice:** Only use data within legal bounds

#### 3. Data Privacy
- **Limitation:** No PII detection or filtering
- **Responsibility:** User must handle personal data appropriately
- **Compliance:** Ensure GDPR/CCPA compliance when applicable

### Performance Limitations

#### 1. Single-threaded
- **Architecture:** Sequential requests only
- **Impact:** Slower than multi-threaded crawlers
- **Benefit:** More polite to servers

#### 2. Memory Usage
- **Large crawls:** Can consume significant memory
- **Recommendation:** Monitor memory for 100-page crawls
- **Workaround:** Process results in batches

#### 3. No Caching
- **Limitation:** No built-in response caching
- **Impact:** Repeated crawls re-fetch content
- **Workaround:** Implement external caching layer

### Sitemap Limitations

#### 1. Sitemap Size
- **Limitation:** Very large sitemaps may timeout
- **Recommendation:** Use sitemap index files
- **Max recommended:** 50,000 URLs per sitemap

#### 2. Compressed Sitemaps
- **Limitation:** Gzipped sitemaps not automatically decompressed
- **Workaround:** Decompress externally or use uncompressed version

### Robots.txt Limitations

#### 1. Wildcards
- **Support:** Basic wildcard support only
- **Limitation:** Complex patterns may not be fully supported

#### 2. Multiple User-Agents
- **Support:** Checks single user-agent at a time
- **Limitation:** Doesn't compare across multiple user-agents

---

## Usage Examples

### Example 1: Basic Website Crawl

```python
from tools.impl.webcrawler_tool_refactored import CrawlURLTool

# Initialize tool
crawler = CrawlURLTool()

# Execute crawl
result = crawler.execute({
    "url": "https://example.com",
    "max_depth": 1,
    "max_pages": 20
})

# Process results
print(f"Crawled {result['pages_crawled']} pages")
for page in result['pages']:
    print(f"  - {page['title']}: {page['url']}")
```

### Example 2: Check Robots.txt Before Crawling

```python
from tools.impl.webcrawler_tool_refactored import CheckRobotsTxtTool, CrawlURLTool

# Step 1: Check robots.txt
robots_checker = CheckRobotsTxtTool()
robots_result = robots_checker.execute({
    "url": "https://example.com"
})

if robots_result['can_fetch']:
    crawl_delay = robots_result.get('crawl_delay', 1.0)
    print(f"✓ Crawling allowed with delay: {crawl_delay}s")
    
    # Step 2: Crawl with appropriate delay
    crawler = CrawlURLTool()
    crawl_result = crawler.execute({
        "url": "https://example.com",
        "delay": max(crawl_delay, 1.0),
        "max_depth": 2,
        "max_pages": 50
    })
    
    print(f"Successfully crawled {crawl_result['pages_crawled']} pages")
else:
    print("✗ Crawling not allowed per robots.txt")
```

### Example 3: Extract All URLs from Sitemap

```python
from tools.impl.webcrawler_tool_refactored import CrawlSitemapTool

# Initialize and execute
sitemap_tool = CrawlSitemapTool()
result = sitemap_tool.execute({
    "url": "https://example.com"
})

# Display results
if 'error' not in result:
    print(f"Found {result['url_count']} URLs in sitemap")
    
    # Categorize URLs
    blog_posts = [url for url in result['urls'] if '/blog/' in url]
    pages = [url for url in result['urls'] if '/page/' in url]
    
    print(f"Blog posts: {len(blog_posts)}")
    print(f"Pages: {len(pages)}")
    
    # Export to file
    with open('sitemap_urls.txt', 'w') as f:
        for url in result['urls']:
            f.write(f"{url}\n")
else:
    print(f"Error: {result['error']}")
```

### Example 4: Deep Crawl with External Links

```python
from tools.impl.webcrawler_tool_refactored import CrawlURLTool
import time

crawler = CrawlURLTool()

# Configure for deep crawl
config = {
    "url": "https://example.com/blog",
    "max_depth": 3,
    "max_pages": 100,
    "follow_external": True,  # Follow external links
    "respect_robots": True,
    "extract_images": True,
    "extract_text": True,
    "delay": 2.0,  # Be polite with 2 second delay
    "timeout": 15
}

start_time = time.time()
result = crawler.execute(config)
duration = time.time() - start_time

# Analyze results
print(f"=== Crawl Summary ===")
print(f"Duration: {duration:.2f}s")
print(f"Pages crawled: {result['pages_crawled']}")
print(f"Average time per page: {duration/result['pages_crawled']:.2f}s")

# Find pages with most images
pages_by_images = sorted(result['pages'], key=lambda p: p['image_count'], reverse=True)
print(f"\nTop 5 pages by image count:")
for i, page in enumerate(pages_by_images[:5], 1):
    print(f"{i}. {page['title']} - {page['image_count']} images")
```

### Example 5: Extract Metadata for SEO Analysis

```python
from tools.impl.webcrawler_tool_refactored import ExtractMetadataTool

metadata_tool = ExtractMetadataTool()

urls_to_check = [
    "https://example.com",
    "https://example.com/about",
    "https://example.com/products"
]

seo_report = []

for url in urls_to_check:
    result = metadata_tool.execute({"url": url})
    
    # Check SEO issues
    issues = []
    if not result.get('title'):
        issues.append("Missing title")
    elif len(result['title']) > 60:
        issues.append("Title too long")
    
    if not result.get('meta_description'):
        issues.append("Missing meta description")
    elif len(result['meta_description']) > 160:
        issues.append("Description too long")
    
    if result.get('h1_count', 0) == 0:
        issues.append("Missing H1")
    elif result.get('h1_count', 0) > 1:
        issues.append("Multiple H1 tags")
    
    seo_report.append({
        'url': url,
        'title': result.get('title', 'N/A'),
        'description_length': len(result.get('meta_description', '')),
        'h1_count': result.get('h1_count', 0),
        'issues': issues
    })

# Print report
print("=== SEO Analysis Report ===")
for page in seo_report:
    print(f"\n{page['url']}")
    print(f"  Title: {page['title'][:50]}...")
    print(f"  Description length: {page['description_length']} chars")
    print(f"  H1 count: {page['h1_count']}")
    if page['issues']:
        print(f"  ⚠ Issues: {', '.join(page['issues'])}")
    else:
        print(f"  ✓ No issues found")
```

### Example 6: Monitor Page Changes

```python
from tools.impl.webcrawler_tool_refactored import GetPageInfoTool
import json
import time

page_monitor = GetPageInfoTool()
url = "https://example.com"

# Get baseline
baseline = page_monitor.execute({"url": url})

# Save baseline
with open('baseline.json', 'w') as f:
    json.dump(baseline, f)

# Wait and check again
time.sleep(3600)  # Wait 1 hour

# Get current state
current = page_monitor.execute({"url": url})

# Compare
changes = []
if baseline['title'] != current['title']:
    changes.append(f"Title changed from '{baseline['title']}' to '{current['title']}'")

if baseline['link_count'] != current['link_count']:
    changes.append(f"Link count changed from {baseline['link_count']} to {current['link_count']}")

if baseline['image_count'] != current['image_count']:
    changes.append(f"Image count changed from {baseline['image_count']} to {current['image_count']}")

if changes:
    print("⚠ Changes detected:")
    for change in changes:
        print(f"  - {change}")
else:
    print("✓ No changes detected")
```

### Example 7: Batch Process Multiple Sites

```python
from tools.impl.webcrawler_tool_refactored import CrawlSitemapTool, CheckRobotsTxtTool
import time

sites = [
    "https://example1.com",
    "https://example2.com",
    "https://example3.com"
]

robots_tool = CheckRobotsTxtTool()
sitemap_tool = CrawlSitemapTool()

results = []

for site in sites:
    print(f"\nProcessing {site}...")
    
    # Check robots.txt
    robots = robots_tool.execute({"url": site})
    
    if not robots['can_fetch']:
        print(f"  ✗ Skipping - crawling not allowed")
        continue
    
    # Get sitemap
    sitemap = sitemap_tool.execute({"url": site})
    
    if 'error' in sitemap:
        print(f"  ✗ No sitemap found")
        continue
    
    print(f"  ✓ Found {sitemap['url_count']} URLs")
    
    results.append({
        'site': site,
        'url_count': sitemap['url_count'],
        'crawl_delay': robots.get('crawl_delay'),
        'sitemap_url': sitemap['sitemap_url']
    })
    
    # Be polite
    time.sleep(2)

# Summary
print("\n=== Batch Processing Summary ===")
total_urls = sum(r['url_count'] for r in results)
print(f"Sites processed: {len(results)}/{len(sites)}")
print(f"Total URLs found: {total_urls}")
```

---

## Best Practices

### 1. Always Check Robots.txt First

```python
# ✓ GOOD
robots_result = robots_tool.execute({"url": url})
if robots_result['can_fetch']:
    crawl_result = crawler.execute({"url": url})

# ✗ BAD
crawl_result = crawler.execute({"url": url, "respect_robots": False})
```

### 2. Use Appropriate Delays

```python
# ✓ GOOD - Respectful delays
crawler.execute({
    "url": url,
    "delay": 2.0,  # 2 seconds between requests
    "max_pages": 25
})

# ✗ BAD - Too aggressive
crawler.execute({
    "url": url,
    "delay": 0.1,  # Only 0.1 seconds
    "max_pages": 100
})
```

### 3. Prefer Sitemaps Over Crawling

```python
# ✓ GOOD - Fast and efficient
sitemap_result = sitemap_tool.execute({"url": url})

# ✗ LESS EFFICIENT - Slower and more resource intensive
crawl_result = crawler.execute({
    "url": url,
    "max_depth": 3,
    "max_pages": 100
})
```

### 4. Handle Errors Gracefully

```python
# ✓ GOOD - Proper error handling
try:
    result = tool.execute({"url": url})
    if 'error' in result:
        logger.warning(f"Tool returned error: {result['error']}")
    else:
        process_results(result)
except Exception as e:
    logger.error(f"Execution failed: {e}")
    # Implement retry logic or fallback
```

### 5. Set Meaningful User-Agent

```python
# ✓ GOOD - Identifiable and contactable
robots_tool.execute({
    "url": url,
    "user_agent": "MyCompanyBot/1.0 (+https://mycompany.com/bot-info)"
})

# ✗ BAD - Generic or misleading
robots_tool.execute({
    "url": url,
    "user_agent": "Mozilla/5.0"  # Pretending to be a browser
})
```

### 6. Limit Crawl Scope

```python
# ✓ GOOD - Focused crawling
crawler.execute({
    "url": "https://example.com/blog",
    "max_depth": 2,
    "max_pages": 50,
    "follow_external": False  # Stay on same domain
})

# ✗ BAD - Unlimited scope
crawler.execute({
    "url": "https://example.com",
    "max_depth": 3,
    "max_pages": 100,
    "follow_external": True  # Will crawl entire internet
})
```

### 7. Cache Results

```python
import json
from pathlib import Path

# ✓ GOOD - Cache to avoid repeat requests
cache_file = Path(f"cache/{domain}_sitemap.json")
if cache_file.exists():
    with open(cache_file) as f:
        result = json.load(f)
else:
    result = sitemap_tool.execute({"url": url})
    cache_file.parent.mkdir(exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(result, f)
```

### 8. Monitor Performance

```python
# ✓ GOOD - Track metrics
import time

start = time.time()
result = tool.execute_with_tracking({"url": url})
duration = time.time() - start

metrics = tool.get_metrics()
print(f"Execution time: {duration:.2f}s")
print(f"Average execution time: {metrics['average_execution_time']:.2f}s")
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. "Invalid URL" Error

**Problem:**
```python
ValueError: Invalid URL: example.com
```

**Solution:**
```python
# Always include scheme (http:// or https://)
url = "https://example.com"  # ✓ Correct
# Not: url = "example.com"  # ✗ Wrong
```

#### 2. Timeout Errors

**Problem:**
```
urllib.error.URLError: <urlopen error timed out>
```

**Solution:**
```python
# Increase timeout
result = tool.execute({
    "url": url,
    "timeout": 30  # Increase from default 10s
})
```

#### 3. Robots.txt Returns "Not Allowed"

**Problem:**
```python
robots_result['can_fetch'] == False
```

**Solution:**
```python
# Option 1: Respect the robots.txt (recommended)
if not robots_result['can_fetch']:
    print("Crawling not allowed")
    exit()

# Option 2: Check specific user agent
robots_result = tool.execute({
    "url": url,
    "user_agent": "Googlebot"  # Try different user agent
})

# Option 3: Check robots.txt manually and contact site owner
```

#### 4. Empty Sitemap Results

**Problem:**
```python
sitemap_result['url_count'] == 0
```

**Solution:**
```python
# Try specific sitemap URL
result = tool.execute({
    "url": "https://example.com/sitemap_index.xml"
})

# Or check robots.txt for sitemap location
robots_url = "https://example.com/robots.txt"
# Check for Sitemap: directive
```

#### 5. Memory Issues with Large Crawls

**Problem:**
```
MemoryError: Out of memory during large crawl
```

**Solution:**
```python
# Reduce max_pages
result = tool.execute({
    "url": url,
    "max_pages": 25,  # Reduce from 100
    "extract_text": False  # Disable text extraction
})

# Or process in batches
for i in range(0, 100, 25):
    result = crawler.execute({
        "url": f"{base_url}/page/{i}",
        "max_pages": 25
    })
    process_batch(result)
```

#### 6. SSL Certificate Errors

**Problem:**
```
ssl.SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]
```

**Solution:**
```python
# This is a security issue with the target site
# Option 1: Contact site administrator
# Option 2: Only access http:// version (not recommended)
# Option 3: Custom SSL context (advanced, not shown)
```

#### 7. Encoding Issues

**Problem:**
```
UnicodeDecodeError: 'utf-8' codec can't decode byte
```

**Solution:**
```python
# The tool uses 'ignore' mode by default:
# content.decode('utf-8', errors='ignore')
# This should handle most encoding issues automatically
# If problems persist, check the source page encoding
```

#### 8. Rate Limiting by Server

**Problem:**
```
HTTP Error 429: Too Many Requests
```

**Solution:**
```python
# Increase delay significantly
result = tool.execute({
    "url": url,
    "delay": 5.0,  # 5 seconds between requests
    "max_pages": 10  # Reduce page count
})

# Or implement exponential backoff
```

### Debug Mode

Enable detailed logging for troubleshooting:

```python
import logging

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Now tool will log detailed information
tool = CrawlURLTool()
result = tool.execute({"url": url})
```

### Getting Help

If you encounter issues not covered here:

1. Check tool metrics: `tool.get_metrics()`
2. Enable debug logging
3. Test with a simple URL (e.g., example.com)
4. Check if the site blocks crawlers
5. Review robots.txt manually
6. Contact: ajsinha@gmail.com

---

## Appendix A: Complete Tool Comparison

| Feature | crawl_url | extract_links | extract_content | extract_metadata | crawl_sitemap | check_robots_txt | get_page_info |
|---------|-----------|---------------|-----------------|------------------|---------------|------------------|---------------|
| **Recursive** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **Depth Control** | ✓ (0-3) | N/A | N/A | N/A | N/A | N/A | N/A |
| **Page Limit** | ✓ (1-100) | N/A | N/A | N/A | Unlimited | N/A | N/A |
| **Respects Robots** | ✓ | ✗ | ✗ | ✗ | ✗ | N/A | ✗ |
| **Extracts Links** | ✓ | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ |
| **Extracts Text** | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Extracts Metadata** | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✓ |
| **Extracts Images** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| **Configurable Delay** | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| **External Links** | ✓ | ✓ | N/A | N/A | ✓ | N/A | N/A |
| **Best For** | Site crawling | Link analysis | Content extraction | SEO analysis | URL discovery | Compliance check | Page auditing |

---

## Appendix B: HTTP Status Code Reference

| Code | Meaning | Tool Behavior |
|------|---------|---------------|
| 200 | OK | Processes content normally |
| 301 | Moved Permanently | Follows redirect automatically |
| 302 | Found (Temporary Redirect) | Follows redirect automatically |
| 400 | Bad Request | Returns error |
| 401 | Unauthorized | Returns error (no auth support) |
| 403 | Forbidden | Returns error |
| 404 | Not Found | Returns error |
| 429 | Too Many Requests | Returns error (rate limited) |
| 500 | Internal Server Error | Returns error |
| 503 | Service Unavailable | Returns error |

---

## Appendix C: Sample Output Structures

### check_robots_txt Output

```json
{
  "url": "https://example.com/admin",
  "robots_url": "https://example.com/robots.txt",
  "can_fetch": false,
  "user_agent": "Mozilla/5.0 (compatible; WebCrawlerTool/1.0)",
  "crawl_delay": 2.0,
  "checked_at": "2025-10-31T12:00:00.000000"
}
```

### crawl_sitemap Output

```json
{
  "sitemap_url": "https://example.com/sitemap.xml",
  "status_code": 200,
  "url_count": 150,
  "urls": [
    "https://example.com/",
    "https://example.com/about",
    "https://example.com/blog/post-1"
  ],
  "retrieved_at": "2025-10-31T12:00:00.000000"
}
```

### crawl_url Output

```json
{
  "start_url": "https://example.com",
  "max_depth": 2,
  "max_pages": 50,
  "pages_crawled": 45,
  "pages": [
    {
      "url": "https://example.com",
      "depth": 0,
      "status_code": 200,
      "title": "Example Domain",
      "meta_description": "Example description",
      "link_count": 25,
      "image_count": 10,
      "images": ["https://example.com/img1.jpg"],
      "text_preview": "This domain is for use in examples...",
      "crawled_at": "2025-10-31T12:00:00.000000"
    }
  ],
  "follow_external": false,
  "respect_robots": true,
  "crawl_duration": 95.5,
  "completed_at": "2025-10-31T12:01:35.000000"
}
```

---

## Appendix D: Robots.txt Example

```
User-agent: *
Disallow: /admin/
Disallow: /private/
Crawl-delay: 2

User-agent: Googlebot
Disallow: /temp/
Crawl-delay: 1

Sitemap: https://example.com/sitemap.xml
```

**Interpretation:**
- All crawlers: Cannot access /admin/ or /private/, 2 second delay
- Googlebot: Cannot access /temp/, 1 second delay
- Sitemap location provided

---

## License

**Copyright All rights reserved 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | Oct 2025 | Initial release with 7 tools |

---

**End of Document**

---

## Page Glossary

**Key terms referenced in this document:**

- **Web Crawler**: Software that systematically browses websites to collect information. Also known as a spider or bot.

- **HTML (HyperText Markup Language)**: The standard markup language for web pages. Crawlers parse HTML to extract content.

- **DOM (Document Object Model)**: The programming interface for HTML. Crawlers navigate DOM to find elements.

- **CSS Selector**: A pattern for selecting HTML elements. Used to target specific content for extraction.

- **XPath**: A query language for selecting nodes in XML/HTML documents. Alternative to CSS selectors.

- **robots.txt**: A file telling crawlers which pages they should or shouldn't request. SAJHA respects robots.txt.

- **Rate Limiting**: Controlling request frequency to avoid overloading servers. Essential for polite crawling.

- **User Agent**: A string identifying the client making requests. Crawlers should identify themselves appropriately.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
