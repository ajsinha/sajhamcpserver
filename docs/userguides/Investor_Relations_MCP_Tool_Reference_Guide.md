# Investor Relations MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technical Details](#technical-details)
4. [Authentication & Access](#authentication--access)
5. [Supported Companies](#supported-companies)
6. [Tool Descriptions](#tool-descriptions)
7. [Document Types](#document-types)
8. [Usage Examples](#usage-examples)
9. [Schema Reference](#schema-reference)
10. [Limitations](#limitations)
11. [Error Handling](#error-handling)
12. [Performance Considerations](#performance-considerations)

---

## Overview

The Investor Relations MCP Tool Suite provides programmatic access to corporate investor relations websites. Extract annual reports, quarterly earnings, investor presentations, and other financial documents from company IR pages.

### Key Features

- **7 Specialized Tools**: From company discovery to comprehensive document retrieval
- **7 Supported Companies**: Major financial institutions and tech companies
- **8 Document Types**: Annual reports, quarterly reports, presentations, and more
- **Web Scraping**: Direct extraction from company IR pages
- **No Authentication**: No API keys or registration required
- **Historical Data**: Access to multi-year document archives
- **Year Filtering**: Retrieve documents by specific year

### Data Categories

- Annual Reports (10-K)
- Quarterly Reports (10-Q)
- Earnings Presentations
- Investor Presentations
- Proxy Statements
- Press Releases
- ESG Reports
- All IR Documents

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
│              MCP Tool Layer (7 Tools)                    │
├──────────────────────────────────────────────────────────┤
│  • ir_list_supported_companies                           │
│  • ir_find_page                                          │
│  • ir_get_documents                                      │
│  • ir_get_latest_earnings                                │
│  • ir_get_annual_reports                                 │
│  • ir_get_presentations                                  │
│  • ir_get_all_resources                                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ Web Scraping
                     │
┌────────────────────▼────────────────────────────────────┐
│    InvestorRelationsBaseTool (Shared Functionality)      │
├──────────────────────────────────────────────────────────┤
│  • IRWebScraperFactory                                   │
│  • Company-Specific Scrapers                             │
│  • Ticker Validation                                     │
│  • Document Parsing                                      │
│  • Error Handling                                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS Requests
                     │ HTML Parsing
                     │
┌────────────────────▼────────────────────────────────────┐
│         Company Investor Relations Websites              │
│         (Tesla, Microsoft, JPMorgan, etc.)               │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```
BaseMCPTool (Abstract Base)
    │
    └── InvestorRelationsBaseTool
            │
            ├── IRListSupportedCompaniesTool
            ├── IRFindPageTool
            ├── IRGetDocumentsTool
            ├── IRGetLatestEarningsTool
            ├── IRGetAnnualReportsTool
            ├── IRGetPresentationsTool
            └── IRGetAllResourcesTool
```

### Component Descriptions

#### InvestorRelationsBaseTool
Base class providing shared functionality:
- IRWebScraperFactory integration
- Ticker validation against supported companies
- Scraper instantiation per company
- Common error handling
- Logging infrastructure

#### IRWebScraperFactory
Factory pattern for company-specific scrapers:
- Maintains list of supported companies
- Creates appropriate scraper for each ticker
- Company-specific scraping logic
- IR page URL mapping
- Document structure parsing

#### Individual Tool Classes
Each tool specializes in specific document retrieval:
- Custom input/output schemas
- Specialized filtering (year, type, limit)
- Domain-specific response formatting
- Tailored error messages

---

## Technical Details

### Data Retrieval Method

**Type**: Web Scraping  
**Protocol**: HTTPS  
**Method**: HTML Parsing  
**Format**: Structured JSON output

**Methods Used**:
- ✅ **Web Scraping**
- ✅ **HTML Parsing**
- ✅ **HTTP GET Requests**
- ✗ NOT API calls
- ✗ NOT Database queries
- ✗ NOT File system access

### Web Scraping Process

The tools scrape investor relations websites directly:

```python
# High-level scraping workflow:
1. Validate ticker against supported companies
2. Get company-specific scraper from factory
3. Navigate to company IR page
4. Parse HTML structure
5. Extract document links and metadata
6. Filter by type, year, limit
7. Return structured JSON
```

### HTTP Request Details

**Request Method**: HTTP GET  
**Target Pages**: Company IR websites  
**Parsing**: HTML structure analysis  

**Example URLs**:
```
Tesla:       https://ir.tesla.com
Microsoft:   https://www.microsoft.com/en-us/Investor
JPMorgan:    https://www.jpmorganchase.com/ir/
Goldman:     https://www.goldmansachs.com/investor-relations/
```

**Headers**:
```python
{
    'User-Agent': 'Mozilla/5.0 (compatible; IR Tool)',
    'Accept': 'text/html,application/xhtml+xml'
}
```

### HTML Parsing

The scrapers parse HTML to extract:
- Document titles
- PDF/document URLs
- Publication dates
- Document types
- Year information

**Example Parsing**:
```python
# Pseudo-code for document extraction
html = fetch_ir_page(url)
soup = BeautifulSoup(html, 'html.parser')

# Find document sections
annual_reports = soup.find_all('a', class_='annual-report')
for report in annual_reports:
    title = report.get_text()
    url = report.get('href')
    date = extract_date(report)
```

### No Authentication Required

- No API keys needed
- No user registration
- Public IR pages only
- Respects robots.txt
- Rate limiting applied

---

## Authentication & Access

### No Authentication Required

The Investor Relations tools access **public investor relations pages**:

- ✅ **No API Key Required**
- ✅ **No Registration Required**
- ✅ **No Cost**
- ✅ **No Login Required**
- ✅ **Public Information Only**

### Configuration

```python
from tools.impl.investor_relations_tool_refactored import IRGetLatestEarningsTool

# No configuration needed
tool = IRGetLatestEarningsTool()

# Optional configuration for logging
config = {
    'name': 'ir_get_latest_earnings',
    'enabled': True
}
tool = IRGetLatestEarningsTool(config)
```

### Rate Limiting

While no explicit authentication is needed:
- Be respectful of company servers
- Implement delays between requests
- Cache results when possible
- Avoid excessive automated queries

**Recommended Practices**:
```python
import time

# Add delay between requests
for ticker in ['TSLA', 'MSFT', 'JPM']:
    result = tool.execute({'ticker': ticker})
    time.sleep(2)  # 2 second delay
```

---

## Supported Companies

### Currently Supported (7 Companies)

| Ticker | Company Name | Industry | Country |
|--------|--------------|----------|---------|
| **TSLA** | Tesla, Inc. | Automotive/Tech | USA |
| **MSFT** | Microsoft Corporation | Technology | USA |
| **C** | Citigroup Inc. | Banking | USA |
| **JPM** | JPMorgan Chase & Co. | Banking | USA |
| **GS** | Goldman Sachs Group | Banking | USA |
| **BMO** | Bank of Montreal | Banking | Canada |
| **RY** | Royal Bank of Canada | Banking | Canada |

### Coverage Details

**Tech Companies** (2):
- Tesla, Microsoft

**US Banks** (3):
- Citigroup, JPMorgan Chase, Goldman Sachs

**Canadian Banks** (2):
- Bank of Montreal, Royal Bank of Canada

### Checking Support

```python
from tools.impl.investor_relations_tool_refactored import IRListSupportedCompaniesTool

tool = IRListSupportedCompaniesTool()
result = tool.execute({})

print(f"Supported Companies: {result['count']}")
for company in result['supported_companies']:
    print(f"  {company['ticker']}: {company['name']}")
    print(f"    IR URL: {company['ir_url']}")
```

---

## Tool Descriptions

### 1. ir_list_supported_companies

**Purpose**: List all companies with available IR data access

**Input**: None required

**Output**:
```json
{
  "supported_companies": [
    {
      "ticker": "TSLA",
      "name": "Tesla, Inc.",
      "ir_url": "https://ir.tesla.com"
    },
    {
      "ticker": "MSFT",
      "name": "Microsoft Corporation",
      "ir_url": "https://www.microsoft.com/en-us/Investor"
    }
  ],
  "count": 7
}
```

**Use Cases**:
- Discover available companies
- Check if ticker is supported
- Get IR page URLs

---

### 2. ir_find_page

**Purpose**: Find the investor relations page URL for a company

**Input**:
```json
{
  "ticker": "TSLA"
}
```

**Output**:
```json
{
  "ticker": "TSLA",
  "ir_page_url": "https://ir.tesla.com",
  "success": true
}
```

**Use Cases**:
- Direct access to IR page
- Verify IR page availability
- Get canonical IR URL

---

### 3. ir_get_documents

**Purpose**: Get investor relations documents filtered by type and year

**8 Document Types**:
- annual_report
- quarterly_report
- earnings_presentation
- investor_presentation
- proxy_statement
- press_release
- esg_report
- all (default)

**Input**:
```json
{
  "ticker": "MSFT",
  "document_type": "annual_report",
  "year": 2023,
  "limit": 10
}
```

**Output**:
```json
{
  "ticker": "MSFT",
  "document_type": "annual_report",
  "year": 2023,
  "count": 1,
  "documents": [
    {
      "title": "Microsoft Annual Report 2023",
      "url": "https://microsoft.com/.../2023-annual-report.pdf",
      "date": "2023-08-01",
      "type": "annual_report"
    }
  ],
  "success": true
}
```

**Use Cases**:
- Search specific document types
- Historical document analysis
- Year-specific research

---

### 4. ir_get_latest_earnings

**Purpose**: Get the most recent earnings report and presentation

**Input**:
```json
{
  "ticker": "JPM"
}
```

**Output**:
```json
{
  "ticker": "JPM",
  "latest_earnings": {
    "quarter": "Q3",
    "year": 2024,
    "report_url": "https://jpmorganchase.com/.../Q3-2024-earnings.pdf",
    "presentation_url": "https://jpmorganchase.com/.../Q3-2024-presentation.pdf",
    "date": "2024-10-15"
  },
  "success": true
}
```

**Use Cases**:
- Track latest quarterly results
- Access recent earnings presentation
- Monitor current performance

---

### 5. ir_get_annual_reports

**Purpose**: Get annual reports (10-K filings)

**Input**:
```json
{
  "ticker": "GS",
  "year": 2023,
  "limit": 5
}
```

**Output**:
```json
{
  "ticker": "GS",
  "year": 2023,
  "count": 1,
  "annual_reports": [
    {
      "title": "Goldman Sachs 2023 Annual Report",
      "url": "https://goldmansachs.com/.../2023-10K.pdf",
      "year": 2023,
      "date": "2024-02-26"
    }
  ],
  "success": true
}
```

**Use Cases**:
- Annual financial analysis
- Historical performance review
- 10-K filing access

---

### 6. ir_get_presentations

**Purpose**: Get investor presentations and earnings decks

**Input**:
```json
{
  "ticker": "BMO",
  "limit": 10
}
```

**Output**:
```json
{
  "ticker": "BMO",
  "count": 10,
  "presentations": [
    {
      "title": "BMO Q3 2024 Earnings Presentation",
      "url": "https://bmo.com/.../Q3-2024-presentation.pdf",
      "date": "2024-09-05",
      "type": "earnings_presentation"
    },
    {
      "title": "BMO Investor Day 2024",
      "url": "https://bmo.com/.../investor-day-2024.pdf",
      "date": "2024-03-15",
      "type": "investor_presentation"
    }
  ],
  "success": true
}
```

**Use Cases**:
- Review investor strategy decks
- Access earnings call presentations
- Analyze corporate communication

---

### 7. ir_get_all_resources

**Purpose**: Get comprehensive collection of all IR resources

**Input**:
```json
{
  "ticker": "C"
}
```

**Output**:
```json
{
  "ticker": "C",
  "ir_page_url": "https://www.citigroup.com/citi/investor/",
  "resources": {
    "annual_reports": [
      {
        "title": "Citigroup 2023 Annual Report",
        "url": "https://citigroup.com/.../2023-annual-report.pdf",
        "year": 2023,
        "date": "2024-03-01"
      }
    ],
    "quarterly_reports": [
      {
        "title": "Citigroup Q3 2024 Earnings",
        "url": "https://citigroup.com/.../Q3-2024.pdf",
        "date": "2024-10-15"
      }
    ],
    "presentations": [
      {
        "title": "Q3 2024 Earnings Presentation",
        "url": "https://citigroup.com/.../Q3-2024-deck.pdf",
        "date": "2024-10-15"
      }
    ],
    "press_releases": [
      {
        "title": "Citigroup Reports Q3 2024 Results",
        "url": "https://citigroup.com/.../press-release-Q3-2024.pdf",
        "date": "2024-10-15"
      }
    ]
  },
  "success": true
}
```

**Use Cases**:
- Comprehensive company research
- Build complete IR library
- Full disclosure analysis

---

## Document Types

### Detailed Document Type Reference

| Type | Description | Typical Frequency |
|------|-------------|-------------------|
| **annual_report** | 10-K filing, comprehensive annual review | Annual |
| **quarterly_report** | 10-Q filing, quarterly financial results | Quarterly |
| **earnings_presentation** | Slides for earnings calls | Quarterly |
| **investor_presentation** | Strategy and business overview decks | Ad-hoc |
| **proxy_statement** | Annual meeting proxy materials | Annual |
| **press_release** | News announcements, earnings releases | As needed |
| **esg_report** | Environmental, Social, Governance report | Annual |
| **all** | Retrieve all document types | - |

### Document Content

**Annual Reports** typically include:
- Financial statements
- Management discussion & analysis
- Business overview
- Risk factors
- Corporate governance

**Earnings Presentations** typically include:
- Quarterly financial highlights
- Key metrics and KPIs
- Segment performance
- Outlook and guidance
- Q&A slides

**Investor Presentations** typically include:
- Company strategy
- Business model
- Competitive positioning
- Growth initiatives
- Long-term targets

---

## Usage Examples

### Example 1: Check Supported Companies

```python
from tools.impl.investor_relations_tool_refactored import IRListSupportedCompaniesTool

tool = IRListSupportedCompaniesTool()
result = tool.execute({})

print(f"Available Companies ({result['count']}):\n")
for company in result['supported_companies']:
    print(f"{company['ticker']:6} {company['name']}")
    print(f"       {company['ir_url']}\n")
```

### Example 2: Get Latest Earnings

```python
from tools.impl.investor_relations_tool_refactored import IRGetLatestEarningsTool

tool = IRGetLatestEarningsTool()

# Get Tesla's latest earnings
result = tool.execute({'ticker': 'TSLA'})

if result['success']:
    earnings = result['latest_earnings']
    print(f"Tesla {earnings['quarter']} {earnings['year']} Earnings:")
    print(f"  Report:       {earnings['report_url']}")
    print(f"  Presentation: {earnings['presentation_url']}")
    print(f"  Date:         {earnings['date']}")
```

### Example 3: Get Annual Reports with Year Filter

```python
from tools.impl.investor_relations_tool_refactored import IRGetAnnualReportsTool

tool = IRGetAnnualReportsTool()

# Get Microsoft's 2023 annual report
result = tool.execute({
    'ticker': 'MSFT',
    'year': 2023
})

if result['success'] and result['count'] > 0:
    report = result['annual_reports'][0]
    print(f"Microsoft {report['year']} Annual Report:")
    print(f"  Title: {report['title']}")
    print(f"  URL:   {report['url']}")
    print(f"  Date:  {report['date']}")
```

### Example 4: Search Specific Document Type

```python
from tools.impl.investor_relations_tool_refactored import IRGetDocumentsTool

tool = IRGetDocumentsTool()

# Get JPMorgan's earnings presentations from 2024
result = tool.execute({
    'ticker': 'JPM',
    'document_type': 'earnings_presentation',
    'year': 2024,
    'limit': 5
})

print(f"JPMorgan 2024 Earnings Presentations ({result['count']}):\n")
for doc in result['documents']:
    print(f"  {doc['date']}: {doc['title']}")
    print(f"  {doc['url']}\n")
```

### Example 5: Get All Presentations

```python
from tools.impl.investor_relations_tool_refactored import IRGetPresentationsTool

tool = IRGetPresentationsTool()

# Get Goldman Sachs presentations
result = tool.execute({
    'ticker': 'GS',
    'limit': 10
})

print(f"Goldman Sachs Presentations ({result['count']}):\n")
for pres in result['presentations']:
    print(f"  [{pres['date']}] {pres['title']}")
    print(f"    Type: {pres['type']}")
    print(f"    URL:  {pres['url']}\n")
```

### Example 6: Comprehensive Resource Collection

```python
from tools.impl.investor_relations_tool_refactored import IRGetAllResourcesTool

tool = IRGetAllResourcesTool()

# Get all Citigroup IR resources
result = tool.execute({'ticker': 'C'})

if result['success']:
    resources = result['resources']
    
    print(f"Citigroup IR Resources:")
    print(f"  IR Page: {result['ir_page_url']}\n")
    
    print(f"Annual Reports: {len(resources['annual_reports'])}")
    for report in resources['annual_reports'][:3]:  # First 3
        print(f"  • {report['title']}")
    
    print(f"\nQuarterly Reports: {len(resources['quarterly_reports'])}")
    for report in resources['quarterly_reports'][:3]:
        print(f"  • {report['title']}")
    
    print(f"\nPresentations: {len(resources['presentations'])}")
    for pres in resources['presentations'][:3]:
        print(f"  • {pres['title']}")
```

### Example 7: Multi-Company Comparison

```python
from tools.impl.investor_relations_tool_refactored import IRGetLatestEarningsTool

tool = IRGetLatestEarningsTool()

# Compare latest earnings across banks
banks = ['JPM', 'GS', 'C']

print("Latest Bank Earnings Comparison:\n")
for ticker in banks:
    try:
        result = tool.execute({'ticker': ticker})
        if result['success']:
            earnings = result['latest_earnings']
            print(f"{ticker}: {earnings['quarter']} {earnings['year']}")
            print(f"  Date: {earnings['date']}")
            print(f"  Report: {earnings['report_url'][:60]}...\n")
    except Exception as e:
        print(f"{ticker}: Error - {e}\n")
```

### Example 8: Build Document Library

```python
from tools.impl.investor_relations_tool_refactored import IRGetDocumentsTool
import time

tool = IRGetDocumentsTool()

# Build comprehensive document library
document_types = [
    'annual_report',
    'quarterly_report',
    'earnings_presentation'
]

library = {}

for doc_type in document_types:
    result = tool.execute({
        'ticker': 'TSLA',
        'document_type': doc_type,
        'limit': 20
    })
    
    library[doc_type] = result['documents']
    print(f"Retrieved {result['count']} {doc_type}s")
    time.sleep(1)  # Rate limiting

print(f"\nTotal documents: {sum(len(docs) for docs in library.values())}")
```

### Example 9: Year-Over-Year Analysis

```python
from tools.impl.investor_relations_tool_refactored import IRGetAnnualReportsTool

tool = IRGetAnnualReportsTool()

# Get 5 years of annual reports
result = tool.execute({
    'ticker': 'MSFT',
    'limit': 5
})

print("Microsoft Annual Reports (Last 5 Years):\n")
for report in sorted(result['annual_reports'], key=lambda x: x['year'], reverse=True):
    print(f"{report['year']}: {report['title']}")
    print(f"  Published: {report['date']}")
    print(f"  URL: {report['url']}\n")
```

### Example 10: Error Handling

```python
from tools.impl.investor_relations_tool_refactored import IRGetDocumentsTool

tool = IRGetDocumentsTool()

def safe_get_documents(ticker: str, doc_type: str = 'all'):
    """Safely retrieve documents with error handling"""
    try:
        result = tool.execute({
            'ticker': ticker,
            'document_type': doc_type,
            'limit': 10
        })
        
        if result['success']:
            print(f"✓ Retrieved {result['count']} {doc_type}s for {ticker}")
            return result['documents']
        else:
            print(f"✗ Failed to retrieve documents for {ticker}")
            return []
            
    except ValueError as e:
        if 'not supported' in str(e):
            print(f"✗ {ticker} is not supported")
            print(f"  Supported tickers: TSLA, MSFT, C, JPM, GS, BMO, RY")
        else:
            print(f"✗ Error for {ticker}: {e}")
        return []

# Usage
documents = safe_get_documents('TSLA', 'annual_report')
documents = safe_get_documents('AAPL', 'annual_report')  # Not supported
```

---

## Schema Reference

### Common Input Parameters

```json
{
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol (TSLA, MSFT, C, JPM, GS, BMO, RY)",
    "required": true
  },
  "document_type": {
    "type": "string",
    "enum": [
      "annual_report",
      "quarterly_report",
      "earnings_presentation",
      "investor_presentation",
      "proxy_statement",
      "press_release",
      "esg_report",
      "all"
    ],
    "default": "all"
  },
  "year": {
    "type": "integer",
    "minimum": 2000,
    "maximum": 2030,
    "description": "Filter by specific year"
  },
  "limit": {
    "type": "integer",
    "minimum": 1,
    "maximum": 50,
    "description": "Maximum documents to return"
  }
}
```

### Document Object Schema

```json
{
  "title": {
    "type": "string",
    "description": "Document title"
  },
  "url": {
    "type": "string",
    "description": "Direct URL to document (PDF)"
  },
  "date": {
    "type": "string",
    "format": "YYYY-MM-DD",
    "description": "Publication date"
  },
  "type": {
    "type": "string",
    "description": "Document type"
  },
  "year": {
    "type": "integer",
    "description": "Year (for annual reports)"
  }
}
```

### Latest Earnings Schema

```json
{
  "ticker": "string",
  "latest_earnings": {
    "quarter": "string (Q1, Q2, Q3, Q4)",
    "year": "integer",
    "report_url": "string",
    "presentation_url": "string",
    "date": "string (YYYY-MM-DD)"
  },
  "success": "boolean"
}
```

### All Resources Schema

```json
{
  "ticker": "string",
  "ir_page_url": "string",
  "resources": {
    "annual_reports": "array of document objects",
    "quarterly_reports": "array of document objects",
    "presentations": "array of document objects",
    "press_releases": "array of document objects"
  },
  "success": "boolean"
}
```

---

## Limitations

### Company Coverage

1. **Limited Support**:
   - Only 7 companies currently supported
   - Tech: TSLA, MSFT
   - US Banks: C, JPM, GS
   - Canadian Banks: BMO, RY

2. **No Support For**:
   - Other tech companies (AAPL, GOOGL, AMZN)
   - Other banks (BAC, WFC, etc.)
   - International companies (outside US/Canada)
   - Private companies

### Technical Limitations

1. **Web Scraping Dependency**:
   - Relies on stable IR page structure
   - Changes to company websites may break scraping
   - No guarantees of data availability
   - Subject to website availability

2. **Performance**:
   - Slower than API access
   - Network dependent
   - May timeout on large requests
   - Rate limiting recommended

3. **Data Completeness**:
   - May not capture all documents
   - Depends on IR page structure
   - Historical coverage varies
   - Some documents may be missed

### Scraping Limitations

1. **Website Changes**:
   - Company site redesigns break scrapers
   - URL structure changes
   - HTML element changes
   - Requires scraper updates

2. **Access Issues**:
   - Sites may block scraping
   - Rate limiting may apply
   - CAPTCHA may be encountered
   - Network errors possible

3. **Document Availability**:
   - Not all documents may be listed
   - Older documents may be archived differently
   - Some documents may require login
   - PDF links may change

### Legal & Ethical Considerations

1. **Terms of Service**:
   - Respect company ToS
   - Adhere to robots.txt
   - Use for legitimate research only
   - No commercial scraping

2. **Rate Limiting**:
   - Implement delays between requests
   - Cache results appropriately
   - Avoid excessive automated queries
   - Be a good web citizen

---

## Error Handling

### Common Errors

#### 1. Unsupported Ticker
```python
ValueError: Ticker AAPL is not supported. 
Supported tickers: TSLA, MSFT, C, BMO, RY, JPM, GS
```

**Cause**: Ticker not in supported list  
**Solution**: Use `ir_list_supported_companies` to check availability

#### 2. Scraper Creation Failed
```python
ValueError: Failed to create scraper for ticker: TSLA
```

**Cause**: Internal scraper initialization error  
**Solution**: Check logs, retry request

#### 3. Document Retrieval Failed
```python
ValueError: Failed to get documents: Network error
```

**Causes**:
- Network connectivity issues
- Website temporarily unavailable
- Rate limiting encountered

**Solutions**:
- Check internet connection
- Retry after delay
- Implement exponential backoff

#### 4. No Documents Found
```json
{
  "count": 0,
  "documents": [],
  "success": true
}
```

**Causes**:
- No documents match filters
- Year filter too restrictive
- Document type not available

**Solutions**:
- Broaden search criteria
- Remove year filter
- Try different document type

### Error Handling Best Practices

```python
from typing import Optional, List, Dict
import time

def safe_ir_query(
    tool,
    ticker: str,
    max_retries: int = 3
) -> Optional[Dict]:
    """
    Query IR data with error handling and retries
    
    Args:
        tool: IR tool instance
        ticker: Stock ticker
        max_retries: Maximum retry attempts
    
    Returns:
        Result or None if failed
    """
    for attempt in range(max_retries):
        try:
            result = tool.execute({'ticker': ticker})
            
            if result.get('success'):
                return result
            else:
                print(f"⚠️  Query unsuccessful for {ticker}")
                return None
                
        except ValueError as e:
            error_msg = str(e)
            
            # Don't retry for unsupported tickers
            if 'not supported' in error_msg:
                print(f"❌ {ticker} is not supported")
                print("   Check supported companies with ir_list_supported_companies")
                return None
            
            # Retry for other errors
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"⚠️  Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ All {max_retries} attempts failed: {error_msg}")
                return None
        
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None
    
    return None

# Usage
result = safe_ir_query(tool, 'TSLA')
if result:
    print(f"✓ Successfully retrieved data")
```

### Validation Helper

```python
from tools.impl.investor_relations_tool_refactored import IRListSupportedCompaniesTool

def is_ticker_supported(ticker: str) -> bool:
    """Check if ticker is supported"""
    tool = IRListSupportedCompaniesTool()
    result = tool.execute({})
    
    supported_tickers = [
        company['ticker'] 
        for company in result['supported_companies']
    ]
    
    return ticker.upper() in supported_tickers

# Usage
if is_ticker_supported('TSLA'):
    print("✓ Tesla is supported")
else:
    print("✗ Not supported")
```

---

## Performance Considerations

### Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta
import hashlib
import json

class IRCache:
    """Cache for IR data queries"""
    
    def __init__(self, ttl_hours: int = 24):
        self.cache = {}
        self.ttl = timedelta(hours=ttl_hours)
    
    def _make_key(self, ticker: str, **kwargs) -> str:
        """Create cache key"""
        params = {'ticker': ticker, **kwargs}
        param_str = json.dumps(params, sort_keys=True)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def get(self, ticker: str, **kwargs) -> Optional[Dict]:
        """Get cached result"""
        key = self._make_key(ticker, **kwargs)
        
        if key in self.cache:
            result, timestamp = self.cache[key]
            
            if datetime.now() - timestamp < self.ttl:
                return result
            else:
                del self.cache[key]
        
        return None
    
    def set(self, result: Dict, ticker: str, **kwargs):
        """Cache result"""
        key = self._make_key(ticker, **kwargs)
        self.cache[key] = (result, datetime.now())

# Usage
cache = IRCache(ttl_hours=24)

def cached_query(tool, ticker: str, **kwargs):
    """Query with caching"""
    cached = cache.get(ticker, **kwargs)
    if cached:
        print("✓ Using cached result")
        return cached
    
    result = tool.execute({'ticker': ticker, **kwargs})
    cache.set(result, ticker, **kwargs)
    print("✓ Result cached")
    
    return result
```

### Rate Limiting

```python
import time
from datetime import datetime, timedelta

class RateLimiter:
    """Rate limiter for IR queries"""
    
    def __init__(self, requests_per_minute: int = 10):
        self.requests_per_minute = requests_per_minute
        self.requests = []
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        now = datetime.now()
        
        # Remove old requests
        self.requests = [
            r for r in self.requests 
            if now - r < timedelta(minutes=1)
        ]
        
        # Check limit
        if len(self.requests) >= self.requests_per_minute:
            oldest = min(self.requests)
            wait_until = oldest + timedelta(minutes=1)
            wait_seconds = (wait_until - now).total_seconds()
            
            if wait_seconds > 0:
                print(f"⏳ Rate limit reached, waiting {wait_seconds:.0f}s")
                time.sleep(wait_seconds)
        
        # Record request
        self.requests.append(now)

# Usage
limiter = RateLimiter(requests_per_minute=10)

for ticker in ['TSLA', 'MSFT', 'JPM']:
    limiter.wait_if_needed()
    result = tool.execute({'ticker': ticker})
```

### Recommended Cache TTL

| Data Type | Update Frequency | Recommended TTL |
|-----------|------------------|-----------------|
| Supported companies list | Rarely changes | 7 days |
| IR page URLs | Rarely changes | 7 days |
| Annual reports | Annual | 30 days |
| Quarterly reports | Quarterly | 7 days |
| Latest earnings | Quarterly | 1 day |
| Presentations | Ad-hoc | 7 days |

---

## Appendix A: Supported Companies Reference

### Detailed Company Information

**Tesla, Inc. (TSLA)**
- Industry: Automotive, Clean Energy
- IR Page: https://ir.tesla.com
- Coverage: Annual reports, quarterly earnings, presentations
- Update Frequency: Quarterly

**Microsoft Corporation (MSFT)**
- Industry: Technology, Cloud Computing
- IR Page: https://www.microsoft.com/en-us/Investor
- Coverage: Annual reports, quarterly results, investor presentations
- Update Frequency: Quarterly

**Citigroup Inc. (C)**
- Industry: Banking, Financial Services
- IR Page: https://www.citigroup.com/citi/investor/
- Coverage: Complete IR library
- Update Frequency: Quarterly

**JPMorgan Chase & Co. (JPM)**
- Industry: Banking, Investment Services
- IR Page: https://www.jpmorganchase.com/ir/
- Coverage: Comprehensive financial reports
- Update Frequency: Quarterly

**Goldman Sachs Group (GS)**
- Industry: Investment Banking
- IR Page: https://www.goldmansachs.com/investor-relations/
- Coverage: Full disclosure documents
- Update Frequency: Quarterly

**Bank of Montreal (BMO)**
- Industry: Banking (Canada)
- IR Page: https://www.bmo.com/main/investor-relations/
- Coverage: Complete IR materials
- Update Frequency: Quarterly

**Royal Bank of Canada (RY)**
- Industry: Banking (Canada)
- IR Page: https://www.rbc.com/investor-relations/
- Coverage: Full financial reports
- Update Frequency: Quarterly

---

## Appendix B: Quick Reference

### Tool Selection Guide

| Need | Use Tool |
|------|----------|
| List available companies | ir_list_supported_companies |
| Get IR page URL | ir_find_page |
| Search specific documents | ir_get_documents |
| Latest quarterly results | ir_get_latest_earnings |
| Annual reports only | ir_get_annual_reports |
| Presentation decks | ir_get_presentations |
| Complete IR library | ir_get_all_resources |

### Common Workflows

**Workflow 1: Check Support & Get Latest**
1. `ir_list_supported_companies` - Check availability
2. `ir_get_latest_earnings` - Get recent results

**Workflow 2: Historical Analysis**
1. `ir_find_page` - Verify IR page
2. `ir_get_annual_reports` - Get multiple years
3. Analyze year-over-year trends

**Workflow 3: Comprehensive Research**
1. `ir_get_all_resources` - Get complete library
2. Filter and analyze by type

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025 | Initial release with 7 tools, 7 companies |

---

## Support & Contact

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Copyright**: © 2025-2030 All Rights Reserved

For issues, questions, or feature requests, please contact the author directly.

---

*End of Investor Relations MCP Tool Reference Guide*
