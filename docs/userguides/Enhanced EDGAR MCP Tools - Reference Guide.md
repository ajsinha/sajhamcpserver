# Enhanced EDGAR MCP Tools - Complete Documentation

**Copyright © 2025-2030 Ashutosh Sinha. All Rights Reserved.**  
**Author:** Ashutosh Sinha  
**Email:** ajsinha@gmail.com  
**Version:** 1.0.0  
**Last Updated:** November 2025

---

## 📋 Table of Contents

1. [Introduction](#1-introduction)
2. [Project Overview](#2-project-overview)
3. [Features & Capabilities](#3-features--capabilities)
4. [Installation](#4-installation)
5. [Quick Start Guide](#5-quick-start-guide)
6. [API Key Requirements](#6-api-key-requirements)
7. [Rate Limits & Restrictions](#7-rate-limits--restrictions)
8. [The 20 Tools - Detailed Reference](#8-the-20-tools---detailed-reference)
9. [Complete Usage Examples](#9-complete-usage-examples)
10. [Sample Code & Workflows](#10-sample-code--workflows)
11. [Best Practices](#11-best-practices)
12. [Limitations & Warnings](#12-limitations--warnings)
13. [Troubleshooting](#13-troubleshooting)
14. [Legal Notice & License](#14-legal-notice--license)
15. [Support & Contact](#15-support--contact)

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
│           Enhanced EDGAR MCP Tool Suite (20 Tools)       │
├──────────────────────────────────────────────────────────┤
│  Company Research:                                       │
│  • edgar_company_search    • edgar_company_submissions   │
│  • edgar_company_facts     • edgar_company_concept       │
│                                                          │
│  Filings & Documents:                                    │
│  • edgar_filing_details    • edgar_filings_by_form       │
│  • edgar_current_reports   • edgar_proxy_statements      │
│  • edgar_registration_statements                         │
│                                                          │
│  Financial Data:                                         │
│  • edgar_financial_ratios  • edgar_frame_data            │
│  • edgar_xbrl_frames_multi_concept                       │
│                                                          │
│  Ownership & Trading:                                    │
│  • edgar_insider_transactions                            │
│  • edgar_institutional_holdings                          │
│  • edgar_ownership_reports • edgar_mutual_fund_holdings  │
│                                                          │
│  Classification:                                         │
│  • edgar_companies_by_sic  • edgar_foreign_issuers       │
│  • edgar_company_tickers_by_exchange                     │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ HTTP/HTTPS
                     │
┌────────────────────▼────────────────────────────────────┐
│          EDGARBaseTool (Shared Functionality)            │
├──────────────────────────────────────────────────────────┤
│  • SEC EDGAR API Integration                             │
│  • CIK Lookup & Validation                               │
│  • Rate Limiting (10 req/sec)                            │
│  • XBRL/JSON Parsing                                     │
│  • Caching Layer                                         │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ REST API Calls
                     │
┌────────────────────▼────────────────────────────────────┐
│              SEC EDGAR Data Portal                       │
│          https://data.sec.gov/                           │
│          https://www.sec.gov/cgi-bin/browse-edgar        │
└──────────────────────────────────────────────────────────┘
```

### Data Access Patterns

```
┌─────────────────────────────────────────────────────────┐
│                    Query by Company                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   Company Name/Ticker ──▶ CIK Lookup ──▶ Filings        │
│          │                                    │          │
│          │              ┌─────────────────────┤          │
│          │              │                     │          │
│          ▼              ▼                     ▼          │
│   ┌──────────┐   ┌──────────┐         ┌──────────┐      │
│   │ Company  │   │  10-K/   │         │  Insider │      │
│   │  Facts   │   │  10-Q    │         │ Trading  │      │
│   └──────────┘   └──────────┘         └──────────┘      │
│                                                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                  Query by Concept                        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   XBRL Concept ──▶ Frame Query ──▶ Cross-Company Data   │
│                                                          │
│   Example: "Assets" across all S&P 500 companies         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---


## 1. Introduction

### 1.1 What is Enhanced EDGAR MCP Tools?

Enhanced EDGAR MCP Tools is a comprehensive Python toolkit providing programmatic access to the U.S. Securities and Exchange Commission (SEC) EDGAR database through **20 specialized MCP tools**. This toolkit enables developers, researchers, and financial professionals to retrieve company information, financial statements, insider transactions, institutional holdings, and more.

### 1.2 What is EDGAR?

EDGAR (Electronic Data Gathering, Analysis, and Retrieval) is the SEC's system for collecting, validating, indexing, and forwarding submissions by companies and others legally required to file forms with the SEC. It contains millions of company and individual filings dating back to the mid-1990s.

### 1.3 Why Use This Toolkit?

- ✅ **Comprehensive Coverage** - 20 tools covering all major SEC data types
- ✅ **No API Key Required** - Completely free access to SEC public data
- ✅ **Zero Dependencies** - Pure Python standard library only
- ✅ **Production Ready** - Full error handling and validation
- ✅ **Well Documented** - 1,500+ lines of documentation with 50+ examples
- ✅ **Built-in Rate Limiting** - Automatic SEC compliance
- ✅ **XBRL Support** - Structured financial data extraction
- ✅ **Market-Wide Analysis** - Aggregated data across all companies

### 1.4 Who Should Use This?

This toolkit is designed for:
- **Investment Analysts** - Company research and peer analysis
- **Academic Researchers** - Finance, accounting, and economics studies
- **Compliance Officers** - Filing tracking and monitoring
- **Data Scientists** - Building financial datasets
- **Financial Modelers** - Historical data extraction
- **Algorithmic Traders** - Fundamental data feeds
- **Corporate Governance Researchers** - Ownership and proxy analysis

---

## 2. Project Overview

### 2.1 Project Statistics

| Metric | Count |
|--------|-------|
| **Total Tools** | 20 |
| **Python Lines** | 2,542 |
| **Config Files** | 20 |
| **Documentation Lines** | 1,500+ |
| **Code Examples** | 50+ |
| **Use Cases Covered** | 100+ |
| **External Dependencies** | 0 |

### 2.2 File Structure

```
enhanced_edgar_tools/
│
├── 📄 Enhanced EDGAR MCP Tools - Complete Documentation.md  (This file)
├── 🐍 enhanced_edgar_tool.py                (Main Python module - 2,542 lines)
├── 🐍 base_mcp_tool.py                      (Base tool class)
│
└── 📂 configs/                              (20 JSON configuration files)
    ├── edgar_company_search.json
    ├── edgar_company_submissions.json
    ├── edgar_company_facts.json
    ├── edgar_company_concept.json
    ├── edgar_filings_by_form.json
    ├── edgar_insider_transactions.json
    ├── edgar_institutional_holdings.json
    ├── edgar_mutual_fund_holdings.json
    ├── edgar_frame_data.json
    ├── edgar_company_tickers_by_exchange.json
    ├── edgar_companies_by_sic.json
    ├── edgar_filing_details.json
    ├── edgar_ownership_reports.json
    ├── edgar_proxy_statements.json
    ├── edgar_registration_statements.json
    ├── edgar_foreign_issuers.json
    ├── edgar_current_reports.json
    ├── edgar_financial_ratios.json
    ├── edgar_amendments.json
    └── edgar_xbrl_frames_multi_concept.json
```

### 2.3 The 20 Tools Summary

#### Company Discovery & Search (3 tools)
1. **edgar_company_search** - Search by name or ticker
2. **edgar_company_tickers_by_exchange** - Filter by stock exchange
3. **edgar_companies_by_sic** - Search by industry (SIC code)

#### Company Information (2 tools)
4. **edgar_company_submissions** - All filings and metadata
5. **edgar_filing_details** - Specific filing by accession number

#### Financial Data & XBRL (4 tools)
6. **edgar_company_facts** - ALL XBRL financial facts
7. **edgar_company_concept** - Time-series for specific metric
8. **edgar_financial_ratios** - Auto-calculated financial ratios
9. **edgar_frame_data** - Market-wide aggregated data

#### Filing Types (6 tools)
10. **edgar_filings_by_form** - Filter by form type (10-K, 10-Q, etc.)
11. **edgar_current_reports** - 8-K material events
12. **edgar_proxy_statements** - DEF 14A shareholder info
13. **edgar_registration_statements** - IPO and securities registrations
14. **edgar_foreign_issuers** - 20-F, 6-K, 40-F foreign filings
15. **edgar_amendments** - Track corrected filings

#### Ownership & Holdings (4 tools)
16. **edgar_insider_transactions** - Form 4 insider trades
17. **edgar_ownership_reports** - SC 13D/G beneficial ownership
18. **edgar_institutional_holdings** - 13F institutional portfolios
19. **edgar_mutual_fund_holdings** - N-PORT fund positions

#### Advanced Analysis (1 tool)
20. **edgar_xbrl_frames_multi_concept** - Batch retrieve multiple concepts

---

## 3. Features & Capabilities

### 3.1 Core Features

#### No API Key Required ✅
- SEC EDGAR API is completely free
- No registration needed
- No usage fees
- Unlimited daily requests

#### Zero External Dependencies ✅
- Pure Python standard library only
- Uses only built-in modules: `json`, `urllib`, `time`, `datetime`, `typing`, `re`
- No pip install required
- Easy deployment

#### Built-in Rate Limiting ✅
- Automatic compliance with SEC's 10 requests/second limit
- No manual rate limit management
- Built-in delays between requests
- Prevents API blocks

#### Comprehensive Coverage ✅
- All major SEC filing types (10-K, 10-Q, 8-K, DEF 14A, etc.)
- XBRL structured financial data
- Historical and current filings
- Company information and metadata
- Insider and institutional ownership
- Market-wide aggregated analysis

#### Production Ready ✅
- Full error handling and validation
- Type hints throughout code
- Logging support
- Retry logic capabilities
- Clean, maintainable architecture

### 3.2 Data Coverage

The toolkit provides access to:

**Company Information:**
- Names, CIK numbers, SIC codes
- Business and mailing addresses
- Fiscal year information
- Filing history and status

**Financial Statements (XBRL):**
- Income statement items
- Balance sheet components
- Cash flow statement data
- Per-share metrics
- Custom company-reported facts

**SEC Filings:**
- Annual reports (10-K, 20-F, 40-F)
- Quarterly reports (10-Q)
- Current reports (8-K, 6-K)
- Proxy statements (DEF 14A)
- Registration statements (S-1, S-3, S-4, S-8)
- Insider trading reports (Form 4)
- Institutional holdings (13F-HR)
- Beneficial ownership (SC 13D/G)

**Market Analytics:**
- Industry-wide metrics
- Cross-company analysis
- Peer comparisons
- Sector benchmarking

---

## 4. Installation

### 4.1 System Requirements

**Minimum Requirements:**
- Python 3.7 or higher
- Internet connection
- 500 MB free disk space

**Recommended:**
- Python 3.9 or higher
- Stable internet connection (10 Mbps+)
- 2 GB RAM for processing large responses
- SSD storage for better I/O performance

### 4.2 Installation Steps

#### Step 1: Download Files

Place the following files in your project directory:

```
your_project/
├── enhanced_edgar_tool.py
├── base_mcp_tool.py
└── configs/
    └── (all 20 JSON config files)
```

#### Step 2: Verify Installation

```python
# Test import
import sys
sys.path.append('/path/to/enhanced_edgar_tools')

from enhanced_edgar_tool import EDGAR_TOOLS

# List available tools
print(f"✓ Successfully loaded {len(EDGAR_TOOLS)} tools")
for tool_name in EDGAR_TOOLS.keys():
    print(f"  - {tool_name}")
```

**Expected Output:**
```
✓ Successfully loaded 20 tools
  - edgar_company_search
  - edgar_company_submissions
  - edgar_company_facts
  - edgar_company_concept
  - edgar_filings_by_form
  - edgar_insider_transactions
  - edgar_institutional_holdings
  - edgar_mutual_fund_holdings
  - edgar_frame_data
  - edgar_company_tickers_by_exchange
  - edgar_companies_by_sic
  - edgar_filing_details
  - edgar_ownership_reports
  - edgar_proxy_statements
  - edgar_registration_statements
  - edgar_foreign_issuers
  - edgar_current_reports
  - edgar_financial_ratios
  - edgar_amendments
  - edgar_xbrl_frames_multi_concept
```

#### Step 3: Test Connection

```python
from enhanced_edgar_tool import EDGARCompanySearchTool

# Create tool instance
search_tool = EDGARCompanySearchTool()

# Test search
result = search_tool.execute({'query': 'AAPL'})
print(f"✓ Found {result['results_count']} companies")
print(f"  Company: {result['companies'][0]['title']}")
print(f"  CIK: {result['companies'][0]['cik']}")
```

**Expected Output:**
```
✓ Found 1 companies
  Company: Apple Inc
  CIK: 0000320193
```

### 4.3 Dependencies

**None!** This toolkit uses only Python standard library modules:

```python
# Core dependencies (all built-in)
import json
import urllib.parse
import urllib.request
import urllib.error
import time
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import re
```

---

## 5. Quick Start Guide

### 5.1 Hello World Example

```python
from enhanced_edgar_tool import EDGARCompanySearchTool

# Search for a company
tool = EDGARCompanySearchTool()
result = tool.execute({'query': 'Apple'})

# Print result
print(f"Found: {result['companies'][0]['title']}")
print(f"Ticker: {result['companies'][0]['ticker']}")
print(f"CIK: {result['companies'][0]['cik']}")
```

### 5.2 Get Financial Data

```python
from enhanced_edgar_tool import EDGARCompanyConceptTool

# Get revenue history
tool = EDGARCompanyConceptTool()
result = tool.execute({
    'cik': '0000320193',  # Apple
    'concept': 'Revenues'
})

# Print last 5 years
print("Revenue History:")
for obs in result['units']['USD'][-5:]:
    print(f"  FY{obs['fy']}: ${obs['val']:,.0f}")
```

### 5.3 Calculate Financial Ratios

```python
from enhanced_edgar_tool import EDGARFinancialRatiosTool

# Calculate ratios
tool = EDGARFinancialRatiosTool()
result = tool.execute({
    'cik': '0000320193',
    'fiscal_year': 2023
})

# Print ratios
print(f"Profitability:")
print(f"  Net Margin: {result['profitability_ratios']['net_margin']:.1f}%")
print(f"  ROE: {result['profitability_ratios']['return_on_equity']:.1f}%")

print(f"\nLiquidity:")
print(f"  Current Ratio: {result['liquidity_ratios']['current_ratio']:.2f}")
```

### 5.4 Track Insider Trading

```python
from enhanced_edgar_tool import EDGARInsiderTransactionsTool

# Get insider transactions
tool = EDGARInsiderTransactionsTool()
result = tool.execute({
    'cik': '0000320193',
    'limit': 10
})

# Print recent transactions
print(f"Recent Insider Transactions: {result['transactions_count']}")
for txn in result['transactions'][:5]:
    print(f"  {txn['filingDate']}: Form 4 filed")
```

---

## 6. API Key Requirements

### 6.1 No API Key Needed! ✅

The SEC EDGAR API is **completely free** and does not require:
- ❌ API keys
- ❌ Registration
- ❌ Authentication
- ❌ Payment

### 6.2 Required: User-Agent Header ⚠️

The SEC **requires** all automated requests to include a User-Agent header with:
1. Your company/application name
2. Your email address

**Already configured in this toolkit:**
```python
self.headers = {
    'User-Agent': 'Enhanced EDGAR Tool ashutosh.sinha@research.com',
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'data.sec.gov'
}
```

### 6.3 Customizing User-Agent (Optional)

If you want to use your own contact information:

```python
from enhanced_edgar_tool import EDGARBaseTool

# Create custom tool with your information
class MyEDGARTool(EDGARBaseTool):
    def __init__(self, config=None):
        super().__init__(config)
        # Customize User-Agent with your info
        self.headers['User-Agent'] = 'MyCompany Research myemail@company.com'
```

### 6.4 Why User-Agent Matters

- **Required by SEC** - Missing User-Agent = HTTP 403 Forbidden error
- **Tracking** - SEC monitors usage patterns
- **Contact** - SEC may contact you if there are issues
- **Compliance** - Shows good faith effort to identify yourself

---

## 7. Rate Limits & Restrictions

### 7.1 SEC Rate Limits

| Limit Type | Value | Enforcement |
|------------|-------|-------------|
| **Requests per second** | 10 | Strict |
| **Requests per day** | Unlimited | None |
| **Burst limit** | 10 | Per second window |

### 7.2 Built-in Rate Limiting

All tools automatically enforce rate limits:

```python
# Automatic rate limiting (110ms between requests)
self.rate_limit_delay = 0.11  # Ensures < 10 req/sec
```

The toolkit prevents you from hitting rate limits by:
- Tracking last request time
- Adding delays between requests
- Ensuring compliance automatically

### 7.3 Handling Rate Limit Errors

While the toolkit prevents rate limit errors, you can add additional protection:

```python
import time
from enhanced_edgar_tool import EDGARCompanySearchTool

def safe_search(query, max_retries=3):
    """Search with retry logic"""
    tool = EDGARCompanySearchTool()
    
    for attempt in range(max_retries):
        try:
            return tool.execute({'query': query})
        except ValueError as e:
            if "Rate limit exceeded" in str(e):
                wait_time = 2 ** attempt  # Exponential backoff
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    
    raise Exception(f"Failed after {max_retries} retries")
```

### 7.4 Best Practices for Rate Limits

1. **Use Caching** - Cache results to minimize API calls
2. **Batch with Delays** - Process multiple items with built-in delays
3. **Off-Peak Processing** - Schedule large jobs during off-peak hours
4. **Sequential Processing** - Never make parallel requests
5. **Monitor Usage** - Track your request patterns

---

## 8. The 20 Tools - Detailed Reference

### 8.1 Company Discovery & Search Tools

#### Tool #1: edgar_company_search

**Purpose:** Find companies by name or ticker symbol to get CIK numbers

**Input Parameters:**
- `query` (required): Company name or ticker (e.g., 'Apple Inc', 'AAPL')
- `search_type` (optional): "name", "ticker", or "auto" (default: "auto")
- `limit` (optional): Max results 1-100 (default: 10)

**Output:**
- `query`: Original search term
- `results_count`: Number of matches found
- `companies`: Array with CIK, ticker, title, exchange

**Example:**
```python
from enhanced_edgar_tool import EDGARCompanySearchTool

tool = EDGARCompanySearchTool()

# Search by ticker
result = tool.execute({
    'query': 'AAPL',
    'search_type': 'ticker'
})

# Search by name
result = tool.execute({
    'query': 'Microsoft',
    'search_type': 'name',
    'limit': 5
})

# Auto-search (tries both)
result = tool.execute({'query': 'Tesla'})

for company in result['companies']:
    print(f"{company['ticker']}: {company['title']} (CIK: {company['cik']})")
```

**Use Cases:**
- Finding CIK for other API calls
- Validating ticker symbols
- Discovering official company names
- Finding exchange listings

---

#### Tool #2: edgar_company_tickers_by_exchange

**Purpose:** Get all companies listed on a specific stock exchange

**Input Parameters:**
- `exchange` (required): "Nasdaq", "NYSE", "AMEX", "BATS", "OTC"
- `limit` (optional): Max companies 1-5000 (default: 100)

**Output:**
- `exchange`: Exchange queried
- `companies_count`: Number of companies
- `companies`: Array with CIK, ticker, title

**Example:**
```python
from enhanced_edgar_tool import EDGARCompanyTickersByExchangeTool

tool = EDGARCompanyTickersByExchangeTool()

# Get NYSE companies
result = tool.execute({
    'exchange': 'NYSE',
    'limit': 100
})

print(f"Found {result['companies_count']} NYSE companies")
for company in result['companies'][:10]:
    print(f"  {company['ticker']}: {company['title']}")
```

**Use Cases:**
- Exchange-specific screening
- Building exchange indices
- Market analysis by venue
- Listing comparisons

---

#### Tool #3: edgar_companies_by_sic

**Purpose:** Search companies by industry using SIC codes

**Input Parameters:**
- `sic_code` (required): 4-digit SIC code
- `limit` (optional): Max companies 1-500 (default: 50)

**Output:**
- `sic_code`: SIC queried
- `companies_count`: Number in industry
- `companies`: Array with CIK, name, SIC description

**Example:**
```python
from enhanced_edgar_tool import EDGARCompaniesBySICTool

tool = EDGARCompaniesBySICTool()

# Find software companies (SIC 7372)
result = tool.execute({
    'sic_code': '7372',
    'limit': 20
})

print(f"Software companies: {result['companies_count']}")
for company in result['companies']:
    print(f"  {company['name']}")
```

**Common SIC Codes:**
- `7372` - Prepackaged Software
- `3674` - Semiconductors & Related Devices
- `6022` - State Commercial Banks
- `2834` - Pharmaceutical Preparations
- `5331` - Variety Stores
- `6211` - Security Brokers & Dealers

**Use Cases:**
- Industry peer analysis
- Sector screening
- Competitive intelligence
- Market research

---

### 8.2 Company Information Tools

#### Tool #4: edgar_company_submissions

**Purpose:** Get comprehensive company information and all SEC filings

**Input Parameters:**
- `cik` (required): Central Index Key
- `include_old_filings` (optional): Include historical beyond recent (default: false)

**Output:**
- Company metadata (name, SIC, addresses, fiscal year)
- `recent_filings`: Array of recent submissions
- `filings_count`: Total filings available
- Category, state of incorporation, etc.

**Example:**
```python
from enhanced_edgar_tool import EDGARCompanySubmissionsTool

tool = EDGARCompanySubmissionsTool()
result = tool.execute({'cik': '320193'})  # Apple

print(f"Company: {result['name']}")
print(f"Industry: {result['sicDescription']}")
print(f"SIC Code: {result['sic']}")
print(f"Fiscal Year End: {result['fiscalYearEnd']}")
print(f"Filer Category: {result['category']}")
print(f"\nRecent Filings: {result['filings_count']}")

for filing in result['recent_filings'][:10]:
    print(f"  {filing['form']} - {filing['filingDate']}")
```

**Use Cases:**
- Company due diligence
- Filing history tracking
- Finding recent reports
- Compliance monitoring
- Corporate information lookup

---

#### Tool #5: edgar_filing_details

**Purpose:** Get detailed information about a specific filing by accession number

**Input Parameters:**
- `cik` (required): Central Index Key
- `accession_number` (required): Filing accession number (with or without dashes)

**Output:**
- Filing metadata (form, dates, documents)
- `document_url`: SEC viewer URL
- `filing_url`: Direct document URL
- Acceptance date/time

**Example:**
```python
from enhanced_edgar_tool import EDGARFilingDetailsTool

tool = EDGARFilingDetailsTool()
result = tool.execute({
    'cik': '320193',
    'accession_number': '0000320193-23-000106'
})

print(f"Form: {result['form']}")
print(f"Filed: {result['filingDate']}")
print(f"Report Date: {result['reportDate']}")
print(f"Primary Doc: {result['primaryDocument']}")
print(f"View URL: {result['document_url']}")
```

**Use Cases:**
- Direct filing access
- Document URL generation
- Filing verification
- Link sharing

---

### 8.3 Financial Data & XBRL Tools

#### Tool #6: edgar_company_facts

**Purpose:** Retrieve ALL structured financial facts (XBRL) for a company

**Input Parameters:**
- `cik` (required): Central Index Key

**Output:**
- `entityName`: Company name
- `facts_count`: Number of distinct facts
- `taxonomies`: Available taxonomies (us-gaap, dei, srt, ifrs-full)
- `facts`: Complete facts organized by taxonomy

**Example:**
```python
from enhanced_edgar_tool import EDGARCompanyFactsTool

tool = EDGARCompanyFactsTool()
result = tool.execute({'cik': '320193'})

print(f"Company: {result['entityName']}")
print(f"Total Facts: {result['facts_count']}")
print(f"Taxonomies: {result['taxonomies']}")

# Access specific fact
us_gaap_facts = result['facts']['us-gaap']
print(f"\nUS-GAAP concepts available: {len(us_gaap_facts)}")

# Example: Revenue data
if 'Revenues' in us_gaap_facts:
    revenue_info = us_gaap_facts['Revenues']
    print(f"Revenue Label: {revenue_info['label']}")
    print(f"Revenue Description: {revenue_info['description']}")
```

**⚠️ Warning:** Response can be very large (5-50 MB for major companies)

**Use Cases:**
- Comprehensive financial analysis
- Building financial models
- Historical trend analysis
- Data extraction for databases
- Financial statement reconstruction

---

#### Tool #7: edgar_company_concept

**Purpose:** Get time-series data for a specific financial metric

**Input Parameters:**
- `cik` (required): Central Index Key
- `taxonomy` (optional): XBRL taxonomy (default: "us-gaap")
- `concept` (required): XBRL concept tag

**Output:**
- `label`: Human-readable name
- `description`: Concept description
- `units`: Historical values by unit type
  - Each value includes: date, value, fiscal year, quarter, form, filing date

**Example:**
```python
from enhanced_edgar_tool import EDGARCompanyConceptTool

tool = EDGARCompanyConceptTool()

# Get Apple's revenue history
result = tool.execute({
    'cik': '320193',
    'taxonomy': 'us-gaap',
    'concept': 'Revenues'
})

print(f"Concept: {result['label']}")
print(f"Description: {result['description']}")
print(f"\nRevenue History (USD):")

# Print last 10 annual revenues
usd_values = result['units']['USD']
annual_revenues = [v for v in usd_values if v.get('fp') == 'FY']

for obs in sorted(annual_revenues, key=lambda x: x['fy'], reverse=True)[:10]:
    print(f"  FY{obs['fy']}: ${obs['val']:,.0f}")
    print(f"    Filed: {obs['filed']} (Form {obs['form']})")
```

**Common Concepts:**
- **Revenue:** `Revenues`, `Revenue`, `RevenueFromContractWithCustomerExcludingAssessedTax`
- **Income:** `NetIncomeLoss`, `OperatingIncomeLoss`, `GrossProfit`
- **Balance Sheet:** `Assets`, `Liabilities`, `StockholdersEquity`
- **Cash:** `CashAndCashEquivalentsAtCarryingValue`, `CashAndCashEquivalents`
- **Per Share:** `EarningsPerShareBasic`, `EarningsPerShareDiluted`
- **Equity:** `CommonStockSharesOutstanding`, `RetainedEarningsAccumulatedDeficit`

**Use Cases:**
- Time-series financial analysis
- Trend identification
- Building financial charts
- Period-over-period comparisons
- Historical performance tracking

---

#### Tool #8: edgar_financial_ratios

**Purpose:** Auto-calculate common financial ratios from XBRL data

**Input Parameters:**
- `cik` (required): Central Index Key
- `fiscal_year` (optional): Year for calculation (2009-2030)
- `fiscal_period` (optional): "FY", "Q1", "Q2", "Q3", "Q4" (default: "FY")

**Output:**
- `profitability_ratios`: gross_margin, operating_margin, net_margin, ROA, ROE
- `liquidity_ratios`: current_ratio, quick_ratio, cash_ratio
- `solvency_ratios`: debt_to_equity, debt_to_assets, equity_multiplier

**Example:**
```python
from enhanced_edgar_tool import EDGARFinancialRatiosTool

tool = EDGARFinancialRatiosTool()
result = tool.execute({
    'cik': '320193',
    'fiscal_year': 2023,
    'fiscal_period': 'FY'
})

print(f"Company: {result['entityName']}")
print(f"Period: FY{result['fiscal_year']}")

print(f"\n--- Profitability Ratios ---")
prof = result['profitability_ratios']
if prof.get('gross_margin'):
    print(f"Gross Margin: {prof['gross_margin']:.2f}%")
if prof.get('operating_margin'):
    print(f"Operating Margin: {prof['operating_margin']:.2f}%")
if prof.get('net_margin'):
    print(f"Net Margin: {prof['net_margin']:.2f}%")
if prof.get('return_on_assets'):
    print(f"Return on Assets (ROA): {prof['return_on_assets']:.2f}%")
if prof.get('return_on_equity'):
    print(f"Return on Equity (ROE): {prof['return_on_equity']:.2f}%")

print(f"\n--- Liquidity Ratios ---")
liq = result['liquidity_ratios']
if liq.get('current_ratio'):
    print(f"Current Ratio: {liq['current_ratio']:.2f}")
if liq.get('quick_ratio'):
    print(f"Quick Ratio: {liq['quick_ratio']:.2f}")
if liq.get('cash_ratio'):
    print(f"Cash Ratio: {liq['cash_ratio']:.2f}")

print(f"\n--- Solvency Ratios ---")
solv = result['solvency_ratios']
if solv.get('debt_to_equity'):
    print(f"Debt/Equity: {solv['debt_to_equity']:.2f}")
if solv.get('debt_to_assets'):
    print(f"Debt/Assets: {solv['debt_to_assets']:.2f}")
if solv.get('equity_multiplier'):
    print(f"Equity Multiplier: {solv['equity_multiplier']:.2f}")
```

**Ratio Definitions:**

**Profitability:**
- Gross Margin = (Gross Profit / Revenue) × 100
- Operating Margin = (Operating Income / Revenue) × 100
- Net Margin = (Net Income / Revenue) × 100
- ROA = (Net Income / Assets) × 100
- ROE = (Net Income / Equity) × 100

**Liquidity:**
- Current Ratio = Current Assets / Current Liabilities
- Quick Ratio = (Current Assets - Inventory) / Current Liabilities
- Cash Ratio = Cash / Current Liabilities

**Solvency:**
- Debt/Equity = Total Liabilities / Equity
- Debt/Assets = Total Liabilities / Assets
- Equity Multiplier = Assets / Equity

**Use Cases:**
- Quick financial health assessment
- Peer comparison
- Investment screening
- Credit analysis
- Financial modeling

---

#### Tool #9: edgar_frame_data

**Purpose:** Get market-wide aggregated data for a specific metric (all companies)

**Input Parameters:**
- `taxonomy` (optional): XBRL taxonomy (default: "us-gaap")
- `concept` (required): XBRL concept
- `unit` (optional): "USD", "shares", "pure" (default: "USD")
- `year` (required): Calendar year (2009-2030)
- `quarter` (optional): "Q1", "Q2", "Q3", "Q4", "CY" (default: "CY")

**Output:**
- `frame`: Frame identifier (e.g., "CY2023Q4")
- `units_count`: Number of company data points
- `data`: Array of company data with CIK, name, value, filing date

**Example:**
```python
from enhanced_edgar_tool import EDGARFrameDataTool

tool = EDGARFrameDataTool()

# Get all company revenues for 2023
result = tool.execute({
    'taxonomy': 'us-gaap',
    'concept': 'Revenues',
    'unit': 'USD',
    'year': 2023,
    'quarter': 'CY'
})

print(f"Frame: {result['frame']}")
print(f"Companies with data: {result['units_count']}")

# Sort by revenue and show top 10
sorted_companies = sorted(result['data'], 
                          key=lambda x: x['val'], 
                          reverse=True)

print("\nTop 10 Companies by Revenue (2023):")
for i, company in enumerate(sorted_companies[:10], 1):
    print(f"{i}. {company['entityName']}")
    print(f"   Revenue: ${company['val']:,.0f}")
    print(f"   CIK: {company['cik']}")
```

**⚠️ Warning:** Response can contain thousands of companies (very large)

**Use Cases:**
- Industry-wide benchmarking
- Peer group comparisons
- Market trend analysis
- Sector performance analysis
- Economic research
- Building market indices
- Statistical analysis

---

### 8.4 Filing Types Tools

#### Tool #10: edgar_filings_by_form

**Purpose:** Filter company filings by specific form type with date range support

**Input Parameters:**
- `cik` (required): Central Index Key
- `form_type` (required): Form type (see supported forms below)
- `start_date` (optional): Filter from date (YYYY-MM-DD)
- `end_date` (optional): Filter to date (YYYY-MM-DD)
- `limit` (optional): Max filings 1-500 (default: 50)

**Supported Form Types:**
- Annual: `10-K`, `20-F`, `40-F`
- Quarterly: `10-Q`
- Current: `8-K`, `6-K`
- Proxy: `DEF 14A`
- Insider: `4`, `3`, `5`
- Institutional: `13F-HR`, `13F-NT`
- Registration: `S-1`, `S-3`, `S-4`, `S-8`
- Ownership: `SC 13D`, `SC 13G`, `SC 13G/A`, `SC 13D/A`
- Prospectus: `424B2`, `424B3`, `424B4`, `424B5`
- Other: `144`, `N-Q`, `N-CSR`, `N-PORT`, `NPORT-P`

**Output:**
- `form_type`: Form filtered
- `form_description`: Human-readable description
- `filings_count`: Number of filings
- `filings`: Array with dates, descriptions, document URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARFilingsByFormTool

tool = EDGARFilingsByFormTool()

# Get Apple's last 5 annual reports (10-K)
result = tool.execute({
    'cik': '320193',
    'form_type': '10-K',
    'limit': 5
})

print(f"Form: {result['form_type']} - {result['form_description']}")
print(f"Filings Found: {result['filings_count']}")

for filing in result['filings']:
    print(f"\n Filing Date: {filing['filingDate']}")
    print(f" Report Date: {filing['reportDate']}")
    print(f" Document: {filing['primaryDocument']}")
    print(f" URL: {filing['document_url']}")

# Get Tesla quarterly reports from 2023
result = tool.execute({
    'cik': '1318605',
    'form_type': '10-Q',
    'start_date': '2023-01-01',
    'end_date': '2023-12-31'
})

print(f"\nTesla 10-Q filings in 2023: {result['filings_count']}")
```

**Major Form Types Explained:**
- **10-K**: Annual report with comprehensive financial information
- **10-Q**: Quarterly report with unaudited financial statements
- **8-K**: Current report for material corporate events
- **DEF 14A**: Proxy statement with executive compensation and voting info
- **4**: Insider trading transactions (officers, directors, 10%+ owners)
- **13F-HR**: Quarterly institutional holdings (managers with $100M+)
- **S-1**: Initial public offering (IPO) registration
- **20-F**: Annual report for foreign private issuers
- **SC 13D**: Beneficial ownership report (activist investors)

**Use Cases:**
- Accessing annual and quarterly reports
- Tracking material events
- Reviewing proxy statements
- Following registrations
- Monitoring insider activity

---

#### Tool #11: edgar_current_reports

**Purpose:** Retrieve 8-K current reports (material corporate events)

**Input Parameters:**
- `cik` (required): Central Index Key
- `start_date` (optional): Filter from date (YYYY-MM-DD)
- `end_date` (optional): Filter to date (YYYY-MM-DD)
- `limit` (optional): Max reports 1-200 (default: 50)

**Output:**
- `reports_count`: Number of 8-K filings
- `reports`: Array with filing dates, descriptions, URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARCurrentReportsTool

tool = EDGARCurrentReportsTool()

# Get Apple's 8-K filings from 2024
result = tool.execute({
    'cik': '320193',
    'start_date': '2024-01-01',
    'limit': 20
})

print(f"8-K Reports in 2024: {result['reports_count']}")
for report in result['reports']:
    print(f"\n Filed: {report['filingDate']}")
    print(f" Report Date: {report['reportDate']}")
    print(f" Description: {report['primaryDocDescription']}")
```

**8-K Event Types:**
- Earnings announcements
- Mergers and acquisitions
- CEO/CFO/Director changes
- Bankruptcy filings
- Asset acquisitions or dispositions
- Material agreements
- Delisting notices
- Financial statement amendments

**Use Cases:**
- Material event tracking
- Corporate action monitoring
- News generation
- Event studies
- Timeline reconstruction

---

#### Tool #12: edgar_proxy_statements

**Purpose:** Get DEF 14A proxy statements (shareholder voting information)

**Input Parameters:**
- `cik` (required): Central Index Key
- `limit` (optional): Max statements 1-50 (default: 10)

**Output:**
- `statements_count`: Number of proxy statements
- `statements`: Array with dates and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARProxyStatementsTool

tool = EDGARProxyStatementsTool()
result = tool.execute({'cik': '320193', 'limit': 5})

print(f"Proxy Statements: {result['statements_count']}")
for statement in result['statements']:
    print(f"\n Filed: {statement['filingDate']}")
    print(f" Report Date: {statement['reportDate']}")
    print(f" URL: {statement['document_url']}")
```

**Proxy Statement Contents:**
- Executive compensation (salary, bonuses, stock options)
- Director election information
- Shareholder proposals
- Say-on-pay votes
- Corporate governance policies
- Related party transactions
- Board committee information

**Use Cases:**
- Executive compensation analysis
- Corporate governance research
- Voting record tracking
- Activist investor monitoring
- Compensation benchmarking

---

#### Tool #13: edgar_registration_statements

**Purpose:** Get securities registration statements (IPOs, shelf registrations)

**Input Parameters:**
- `cik` (required): Central Index Key
- `form_type` (optional): "S-1", "S-3", "S-4", "S-8" (default: "S-1")
- `limit` (optional): Max filings 1-50 (default: 10)

**Output:**
- `form_type`: Registration form
- `filings_count`: Number of registrations
- `filings`: Array with dates and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARRegistrationStatementsTool

tool = EDGARRegistrationStatementsTool()

# Get IPO registration (S-1)
result = tool.execute({
    'cik': '1318605',  # Tesla
    'form_type': 'S-1',
    'limit': 5
})

print(f"S-1 Registrations: {result['filings_count']}")
```

**Form Types:**
- **S-1**: IPO registration statement
- **S-3**: Shelf registration for seasoned issuers
- **S-4**: Registration for business combinations (mergers)
- **S-8**: Registration for employee benefit plans

**Use Cases:**
- IPO tracking
- Capital raising monitoring
- M&A documentation
- ESOP analysis
- Pre-IPO research

---

#### Tool #14: edgar_foreign_issuers

**Purpose:** Get foreign private issuer filings

**Input Parameters:**
- `cik` (required): Central Index Key
- `form_type` (required): "20-F", "6-K", "40-F"
- `limit` (optional): Max filings 1-100 (default: 20)

**Output:**
- `form_type`: Foreign issuer form
- `form_description`: Description
- `filings_count`: Number of filings
- `filings`: Array with dates and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARForeignIssuersTool

tool = EDGARForeignIssuersTool()

# Get foreign issuer annual reports
result = tool.execute({
    'cik': '0001679788',  # Example foreign issuer
    'form_type': '20-F',
    'limit': 5
})

print(f"20-F Filings: {result['filings_count']}")
```

**Form Types:**
- **20-F**: Annual report (foreign private issuers)
- **6-K**: Current report (foreign private issuers)
- **40-F**: Annual report (Canadian issuers)

**Use Cases:**
- International company analysis
- Cross-border investments
- Foreign issuer research
- Global portfolio management

---

#### Tool #15: edgar_amendments

**Purpose:** Track amended filings (corrections and restatements)

**Input Parameters:**
- `cik` (required): Central Index Key
- `limit` (optional): Max amendments 1-100 (default: 20)

**Output:**
- `amendments_count`: Number of amendments
- `amendments`: Array of /A filings

**Example:**
```python
from enhanced_edgar_tool import EDGARAmendmentsTool

tool = EDGARAmendmentsTool()
result = tool.execute({'cik': '320193', 'limit': 10})

print(f"Amendments: {result['amendments_count']}")
for amendment in result['amendments']:
    print(f"\n Form: {amendment['form']}")
    print(f" Filed: {amendment['filingDate']}")
    print(f" Report Date: {amendment['reportDate']}")
```

**Amendment Types:**
- `10-K/A`: Amended annual report
- `10-Q/A`: Amended quarterly report
- `8-K/A`: Amended current report
- `DEF 14A/A`: Amended proxy statement

**⚠️ Red Flags:**
- Multiple amendments may indicate accounting issues
- Material amendments can significantly impact financial analysis
- Restatements often signal internal control problems

**Use Cases:**
- Tracking financial restatements
- Quality control
- Due diligence red flags
- Accounting quality assessment
- Compliance monitoring

---

### 8.5 Ownership & Holdings Tools

#### Tool #16: edgar_insider_transactions

**Purpose:** Monitor Form 4 insider trading transactions

**Input Parameters:**
- `cik` (required): Company Central Index Key (not insider's CIK)
- `limit` (optional): Max transactions 1-100 (default: 20)

**Output:**
- `transactions_count`: Number of Form 4 filings
- `transactions`: Array with filing dates, transaction dates, URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARInsiderTransactionsTool

tool = EDGARInsiderTransactionsTool()
result = tool.execute({
    'cik': '320193',  # Apple
    'limit': 30
})

print(f"Insider Transactions: {result['transactions_count']}")
for txn in result['transactions'][:10]:
    print(f"\n Filed: {txn['filingDate']}")
    print(f" Transaction Date: {txn['reportDate']}")
    print(f" Document: {txn['primaryDocument']}")
    print(f" URL: {txn['document_url']}")
```

**Who Files Form 4:**
- Officers (CEO, CFO, COO, etc.)
- Directors
- 10%+ beneficial owners

**Filing Deadline:** Within 2 business days of transaction

**Transaction Types:**
- Purchase (buy)
- Sale
- Gift
- Exercise of options
- Award/grant of stock

**Use Cases:**
- Insider trading signals
- Management sentiment analysis
- Corporate governance
- Trading pattern detection
- Investment decision support

---

#### Tool #17: edgar_ownership_reports

**Purpose:** Get beneficial ownership reports (SC 13D/G) - activist investors

**Input Parameters:**
- `cik` (required): Company Central Index Key
- `form_type` (optional): "SC 13D", "SC 13G", "SC 13G/A", "SC 13D/A" (default: "SC 13D")
- `limit` (optional): Max reports 1-100 (default: 20)

**Output:**
- `form_type`: Ownership form
- `reports_count`: Number of filings
- `reports`: Array with dates and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGAROwnershipReportsTool

tool = EDGAROwnershipReportsTool()

# Get activist investor filings (SC 13D)
result = tool.execute({
    'cik': '320193',
    'form_type': 'SC 13D',
    'limit': 10
})

print(f"SC 13D Filings: {result['reports_count']}")
for report in result['reports']:
    print(f"\n Filed: {report['filingDate']}")
    print(f" Form: {report['form']}")
```

**Form Differences:**
- **SC 13D**: Activist intent (seeking control or influence)
- **SC 13G**: Passive investment (no control intent)

**Filing Trigger:** Acquiring 5% or more of voting securities

**Use Cases:**
- Activist investor tracking
- Change of control monitoring
- Takeover defense
- Investment thesis analysis
- Shareholder activism research

---

#### Tool #18: edgar_institutional_holdings

**Purpose:** Get Form 13F institutional portfolio holdings

**Input Parameters:**
- `cik` (required): Institutional MANAGER CIK (not company CIK!)
- `limit` (optional): Max filings 1-50 (default: 10)

**Output:**
- `manager_name`: Investment manager name
- `filings_count`: Number of 13F filings
- `filings`: Array with quarters and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARInstitutionalHoldingsTool

tool = EDGARInstitutionalHoldingsTool()

# Get Berkshire Hathaway's portfolio holdings
result = tool.execute({
    'cik': '1067983',  # Warren Buffett's Berkshire Hathaway
    'limit': 8
})

print(f"Manager: {result['manager_name']}")
print(f"13F Filings: {result['filings_count']}")

for filing in result['filings']:
    print(f"\n Quarter End: {filing['reportDate']}")
    print(f" Filed: {filing['filingDate']}")
    print(f" URL: {filing['document_url']}")
```

**Notable Institutional Manager CIKs:**
- `1067983` - Berkshire Hathaway (Warren Buffett)
- `0000102909` - Vanguard Group
- `1037389` - Renaissance Technologies
- `1364742` - Citadel Advisors
- `1649993` - Bridgewater Associates
- `0001067983` - Berkshire Hathaway Inc
- `0001086364` - BlackRock Inc

**Requirements:**
- Filed quarterly
- Only for managers with $100M+ in 13(f) securities
- Due 45 days after quarter end

**What's Disclosed:**
- ✅ Equity holdings (stocks, options, convertibles)
- ❌ Short positions (not disclosed)
- ❌ Bonds, cash, private equity (not disclosed)
- Position sizes and market values
- May request confidential treatment for certain positions

**Use Cases:**
- Following "smart money" activity
- Portfolio composition analysis
- Tracking quarterly changes
- Investment idea generation
- Competitive intelligence

---

#### Tool #19: edgar_mutual_fund_holdings

**Purpose:** Get mutual fund portfolio positions (Form N-PORT)

**Input Parameters:**
- `cik` (required): Mutual fund CIK
- `limit` (optional): Max filings 1-50 (default: 10)

**Output:**
- `fund_name`: Mutual fund name
- `filings_count`: Number of N-PORT filings
- `filings`: Array with months and URLs

**Example:**
```python
from enhanced_edgar_tool import EDGARMutualFundHoldingsTool

tool = EDGARMutualFundHoldingsTool()
result = tool.execute({
    'cik': '0000862084',  # Example fund
    'limit': 6
})

print(f"Fund: {result['fund_name']}")
print(f"N-PORT Filings: {result['filings_count']}")

for filing in result['filings']:
    print(f"\n Month End: {filing['reportDate']}")
    print(f" Filed: {filing['filingDate']}")
```

**Filing Requirements:**
- Filed monthly
- 30-day lag (60 days for Q1 & Q3)
- Required for registered investment companies

**Disclosure Includes:**
- Complete portfolio holdings
- Position-level details
- Fair values
- Country and currency exposure
- Securities lending information
- Derivatives positions

**Use Cases:**
- Mutual fund analysis
- ETF composition tracking
- Fund strategy comparison
- Holdings-based due diligence
- Portfolio overlap analysis

---

### 8.6 Advanced Analysis Tool

#### Tool #20: edgar_xbrl_frames_multi_concept

**Purpose:** Batch retrieve multiple XBRL concepts in one call (efficient)

**Input Parameters:**
- `taxonomy` (optional): XBRL taxonomy (default: "us-gaap")
- `concepts` (required): Array of concepts (1-10)
- `unit` (optional): "USD", "shares", "pure" (default: "USD")
- `year` (required): Calendar year
- `quarter` (optional): "Q1", "Q2", "Q3", "Q4", "CY" (default: "CY")

**Output:**
- `frame`: Frame identifier
- `concepts_retrieved`: Number successfully retrieved
- `data_by_concept`: Object with data for each concept

**Example:**
```python
from enhanced_edgar_tool import EDGARXBRLFramesMultiConceptTool

tool = EDGARXBRLFramesMultiConceptTool()

# Get multiple income statement metrics
result = tool.execute({
    'taxonomy': 'us-gaap',
    'concepts': ['Revenues', 'NetIncomeLoss', 'OperatingIncomeLoss'],
    'year': 2023,
    'quarter': 'CY'
})

print(f"Frame: {result['frame']}")
print(f"Concepts Retrieved: {result['concepts_retrieved']}")

for concept, data in result['data_by_concept'].items():
    if 'error' not in data:
        print(f"\n{concept}:")
        print(f"  Label: {data['label']}")
        print(f"  Companies: {data['units_count']}")
        
        # Show top 5 companies
        sorted_data = sorted(data['data'], key=lambda x: x['val'], reverse=True)
        for i, company in enumerate(sorted_data[:5], 1):
            print(f"    {i}. {company['entityName']}: ${company['val']:,.0f}")

# Get balance sheet metrics
result = tool.execute({
    'concepts': ['Assets', 'Liabilities', 'StockholdersEquity'],
    'year': 2023,
    'quarter': 'Q4'
})

# Get profitability metrics
result = tool.execute({
    'concepts': [
        'Revenues', 
        'GrossProfit', 
        'OperatingIncomeLoss', 
        'NetIncomeLoss'
    ],
    'year': 2024,
    'quarter': 'Q1'
})
```

**Advantages:**
- More efficient than individual frame queries
- Retrieves related metrics together
- Reduced total API calls
- Consistent time frame across metrics

**Use Cases:**
- Comprehensive market analysis
- Multi-metric peer comparisons
- Building financial datasets
- Industry benchmarking
- Economic research
- Ratio calculations across market

---

## 9. Complete Usage Examples

### 9.1 Example 1: Company Discovery Workflow

```python
"""
Complete company discovery and initial analysis workflow
"""

from enhanced_edgar_tool import (
    EDGARCompanySearchTool,
    EDGARCompanySubmissionsTool,
    EDGARInsiderTransactionsTool
)

def discover_company(search_term):
    """Complete company discovery workflow"""
    
    # Step 1: Search for company
    print(f"\n{'='*60}")
    print(f"SEARCHING FOR: {search_term}")
    print('='*60)
    
    search_tool = EDGARCompanySearchTool()
    search_result = search_tool.execute({
        'query': search_term,
        'limit': 1
    })
    
    if search_result['results_count'] == 0:
        print("❌ Company not found")
        return None
    
    company = search_result['companies'][0]
    cik = company['cik']
    
    print(f"\n✓ Found: {company['title']}")
    print(f"  Ticker: {company['ticker']}")
    print(f"  CIK: {cik}")
    print(f"  Exchange: {company['exchange']}")
    
    # Step 2: Get company details
    print(f"\n{'-'*60}")
    print("COMPANY INFORMATION")
    print('-'*60)
    
    submissions_tool = EDGARCompanySubmissionsTool()
    info = submissions_tool.execute({'cik': cik})
    
    print(f"Legal Name: {info['name']}")
    print(f"Industry: {info['sicDescription']} (SIC: {info['sic']})")
    print(f"Fiscal Year End: {info['fiscalYearEnd']}")
    print(f"Filer Category: {info['category']}")
    print(f"State of Incorporation: {info['stateOfIncorporation']}")
    
    # Step 3: Check insider activity
    print(f"\n{'-'*60}")
    print("RECENT INSIDER ACTIVITY")
    print('-'*60)
    
    insider_tool = EDGARInsiderTransactionsTool()
    try:
        insider = insider_tool.execute({'cik': cik, 'limit': 5})
        print(f"Recent Form 4 filings: {insider['transactions_count']}")
        
        for txn in insider['transactions'][:3]:
            print(f"  - {txn['filingDate']}: Form 4 filed")
    except:
        print("  No recent insider transactions")
    
    print(f"\n{'='*60}\n")
    
    return {
        'cik': cik,
        'company': company,
        'info': info
    }

# Run discovery
result = discover_company('AAPL')
result = discover_company('Microsoft Corporation')
result = discover_company('TSLA')
```

### 9.2 Example 2: Financial Analysis Workflow

```python
"""
Complete financial analysis workflow
Gets revenue, calculates ratios, and analyzes trends
"""

from enhanced_edgar_tool import (
    EDGARCompanySearchTool,
    EDGARCompanyConceptTool,
    EDGARFinancialRatiosTool
)

def analyze_financials(ticker, years=5):
    """Complete financial analysis"""
    
    # Find company
    search_tool = EDGARCompanySearchTool()
    result = search_tool.execute({'query': ticker, 'limit': 1})
    
    if result['results_count'] == 0:
        print(f"Company not found: {ticker}")
        return
    
    cik = result['companies'][0]['cik']
    company_name = result['companies'][0]['title']
    
    print(f"\n{'='*70}")
    print(f"FINANCIAL ANALYSIS: {company_name} ({ticker})")
    print('='*70)
    
    # Get revenue history
    print(f"\n{'-'*70}")
    print(f"REVENUE HISTORY (Last {years} Years)")
    print('-'*70)
    
    concept_tool = EDGARCompanyConceptTool()
    
    try:
        revenue = concept_tool.execute({
            'cik': cik,
            'concept': 'Revenues'
        })
        
        # Get annual revenues
        usd_values = revenue['units'].get('USD', [])
        annual = [v for v in usd_values if v.get('fp') == 'FY']
        annual_sorted = sorted(annual, key=lambda x: x['fy'], reverse=True)
        
        print(f"\n{'Year':<8} {'Revenue':<20} {'Growth':>10}")
        print('-'*40)
        
        prev_revenue = None
        for obs in annual_sorted[:years]:
            revenue_val = obs['val']
            
            if prev_revenue:
                growth = ((revenue_val - prev_revenue) / prev_revenue) * 100
                growth_str = f"{growth:+.1f}%"
            else:
                growth_str = "N/A"
            
            print(f"FY{obs['fy']:<5} ${revenue_val:>17,.0f}  {growth_str:>9}")
            prev_revenue = revenue_val
            
    except Exception as e:
        print(f"  Revenue data not available: {e}")
    
    # Get financial ratios
    print(f"\n{'-'*70}")
    print("FINANCIAL RATIOS (Latest Year)")
    print('-'*70)
    
    ratios_tool = EDGARFinancialRatiosTool()
    
    try:
        ratios = ratios_tool.execute({
            'cik': cik,
            'fiscal_year': 2023
        })
        
        print("\n📊 Profitability Ratios:")
        prof = ratios['profitability_ratios']
        if prof.get('gross_margin'):
            print(f"   Gross Margin:      {prof['gross_margin']:>6.2f}%")
        if prof.get('operating_margin'):
            print(f"   Operating Margin:  {prof['operating_margin']:>6.2f}%")
        if prof.get('net_margin'):
            print(f"   Net Margin:        {prof['net_margin']:>6.2f}%")
        if prof.get('return_on_assets'):
            print(f"   ROA:               {prof['return_on_assets']:>6.2f}%")
        if prof.get('return_on_equity'):
            print(f"   ROE:               {prof['return_on_equity']:>6.2f}%")
        
        print("\n💧 Liquidity Ratios:")
        liq = ratios['liquidity_ratios']
        if liq.get('current_ratio'):
            print(f"   Current Ratio:     {liq['current_ratio']:>6.2f}")
        if liq.get('quick_ratio'):
            print(f"   Quick Ratio:       {liq['quick_ratio']:>6.2f}")
        if liq.get('cash_ratio'):
            print(f"   Cash Ratio:        {liq['cash_ratio']:>6.2f}")
        
        print("\n⚖️  Solvency Ratios:")
        solv = ratios['solvency_ratios']
        if solv.get('debt_to_equity'):
            print(f"   Debt/Equity:       {solv['debt_to_equity']:>6.2f}")
        if solv.get('debt_to_assets'):
            print(f"   Debt/Assets:       {solv['debt_to_assets']:>6.2f}")
        if solv.get('equity_multiplier'):
            print(f"   Equity Multiplier: {solv['equity_multiplier']:>6.2f}")
            
    except Exception as e:
        print(f"  Ratios not available: {e}")
    
    print(f"\n{'='*70}\n")

# Analyze multiple companies
for ticker in ['AAPL', 'MSFT', 'GOOGL']:
    analyze_financials(ticker, years=5)
```

### 9.3 Example 3: Industry Peer Analysis

```python
"""
Industry peer analysis using SIC codes
Compares financial metrics across competitors
"""

from enhanced_edgar_tool import (
    EDGARCompaniesBySICTool,
    EDGARCompanyConceptTool,
    EDGARFinancialRatiosTool
)
import time

def industry_peer_analysis(sic_code, industry_name, max_companies=5):
    """Analyze peer group by SIC code"""
    
    print(f"\n{'='*70}")
    print(f"INDUSTRY PEER ANALYSIS: {industry_name} (SIC {sic_code})")
    print('='*70)
    
    # Get companies in industry
    sic_tool = EDGARCompaniesBySICTool()
    result = sic_tool.execute({
        'sic_code': sic_code,
        'limit': max_companies
    })
    
    print(f"\nFound {result['companies_count']} companies")
    print(f"Analyzing top {max_companies}...")
    
    # Analyze each company
    peer_data = []
    
    for company in result['companies'][:max_companies]:
        print(f"\n{'-'*70}")
        print(f"Analyzing: {company['name']}")
        print('-'*70)
        
        cik = company['cik']
        
        # Get latest revenue
        concept_tool = EDGARCompanyConceptTool()
        try:
            revenue = concept_tool.execute({
                'cik': cik,
                'concept': 'Revenues'
            })
            
            usd_values = revenue['units'].get('USD', [])
            annual = [v for v in usd_values if v.get('fp') == 'FY']
            latest = sorted(annual, key=lambda x: x['fy'], reverse=True)[0]
            
            revenue_val = latest['val']
            fiscal_year = latest['fy']
            
            print(f"  Latest Revenue (FY{fiscal_year}): ${revenue_val:,.0f}")
            
        except:
            print(f"  Revenue data not available")
            revenue_val = None
            fiscal_year = None
        
        # Get ratios
        ratios_tool = EDGARFinancialRatiosTool()
        try:
            ratios = ratios_tool.execute({
                'cik': cik,
                'fiscal_year': 2023
            })
            
            prof = ratios.get('profitability_ratios', {})
            net_margin = prof.get('net_margin')
            roe = prof.get('return_on_equity')
            
            print(f"  Net Margin: {net_margin:.2f}%" if net_margin else "  Net Margin: N/A")
            print(f"  ROE: {roe:.2f}%" if roe else "  ROE: N/A")
            
        except:
            net_margin = None
            roe = None
        
        peer_data.append({
            'name': company['name'],
            'cik': cik,
            'revenue': revenue_val,
            'fiscal_year': fiscal_year,
            'net_margin': net_margin,
            'roe': roe
        })
        
        time.sleep(0.2)  # Rate limiting
    
    # Summary comparison
    print(f"\n{'='*70}")
    print("PEER COMPARISON SUMMARY")
    print('='*70)
    
    print(f"\n{'Company':<30} {'Revenue':<20} {'Net Margin':<12} {'ROE':<10}")
    print('-'*70)
    
    # Sort by revenue
    peer_data_sorted = sorted(peer_data, 
                             key=lambda x: x['revenue'] if x['revenue'] else 0, 
                             reverse=True)
    
    for peer in peer_data_sorted:
        name = peer['name'][:28]
        revenue = f"${peer['revenue']:,.0f}" if peer['revenue'] else "N/A"
        net_margin = f"{peer['net_margin']:.1f}%" if peer['net_margin'] else "N/A"
        roe = f"{peer['roe']:.1f}%" if peer['roe'] else "N/A"
        
        print(f"{name:<30} {revenue:<20} {net_margin:<12} {roe:<10}")
    
    print(f"\n{'='*70}\n")

# Analyze industries
industry_peer_analysis('7372', 'Prepackaged Software', max_companies=3)
industry_peer_analysis('3674', 'Semiconductors', max_companies=3)
```

### 9.4 Example 4: Insider Trading Monitor

```python
"""
Monitor insider trading activity across multiple companies
"""

from enhanced_edgar_tool import (
    EDGARCompanySearchTool,
    EDGARInsiderTransactionsTool
)

def monitor_insider_activity(tickers, days_back=30):
    """Monitor recent insider trading across companies"""
    
    print(f"\n{'='*70}")
    print(f"INSIDER TRADING MONITOR (Last {days_back} days)")
    print('='*70)
    
    from datetime import datetime, timedelta
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    for ticker in tickers:
        # Find company
        search_tool = EDGARCompanySearchTool()
        result = search_tool.execute({'query': ticker, 'limit': 1})
        
        if result['results_count'] == 0:
            continue
        
        company = result['companies'][0]
        cik = company['cik']
        
        print(f"\n{'-'*70}")
        print(f"{company['title']} ({ticker})")
        print('-'*70)
        
        # Get insider transactions
        insider_tool = EDGARInsiderTransactionsTool()
        try:
            insider = insider_tool.execute({
                'cik': cik,
                'limit': 50
            })
            
            # Filter by date
            recent_txns = [
                txn for txn in insider['transactions']
                if txn['filingDate'] >= cutoff_date
            ]
            
            if recent_txns:
                print(f"Found {len(recent_txns)} recent Form 4 filings:")
                for txn in recent_txns[:10]:
                    print(f"  📝 {txn['filingDate']}: Form 4 filed")
                    print(f"     Transaction Date: {txn['reportDate']}")
                    print(f"     URL: {txn['document_url']}")
            else:
                print("  No recent insider transactions")
                
        except Exception as e:
            print(f"  Error: {e}")
    
    print(f"\n{'='*70}\n")

# Monitor several companies
monitor_insider_activity(['AAPL', 'MSFT', 'GOOGL', 'TSLA'], days_back=60)
```

### 9.5 Example 5: SEC Filing Tracker

```python
"""
Track specific SEC filings across companies
"""

from enhanced_edgar_tool import (
    EDGARCompanySearchTool,
    EDGARFilingsByFormTool
)
from datetime import datetime, timedelta

def track_filings(companies, form_type, days_back=90):
    """Track specific form type across companies"""
    
    print(f"\n{'='*70}")
    print(f"SEC FILING TRACKER: {form_type} (Last {days_back} days)")
    print('='*70)
    
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    all_filings = []
    
    for company_query in companies:
        # Find company
        search_tool = EDGARCompanySearchTool()
        result = search_tool.execute({'query': company_query, 'limit': 1})
        
        if result['results_count'] == 0:
            print(f"\n⚠️  Company not found: {company_query}")
            continue
        
        company = result['companies'][0]
        cik = company['cik']
        
        # Get filings
        filings_tool = EDGARFilingsByFormTool()
        try:
            filings = filings_tool.execute({
                'cik': cik,
                'form_type': form_type,
                'start_date': cutoff_date,
                'limit': 10
            })
            
            for filing in filings['filings']:
                all_filings.append({
                    'company': company['title'],
                    'ticker': company['ticker'],
                    'filing': filing
                })
                
        except Exception as e:
            print(f"\n⚠️  Error for {company['title']}: {e}")
    
    # Display results
    if all_filings:
        all_filings.sort(key=lambda x: x['filing']['filingDate'], reverse=True)
        
        print(f"\nFound {len(all_filings)} {form_type} filings:\n")
        print(f"{'Date':<12} {'Company':<25} {'Ticker':<8} {'Report Date':<12}")
        print('-'*70)
        
        for item in all_filings:
            date = item['filing']['filingDate']
            company = item['company'][:23]
            ticker = item['ticker']
            report_date = item['filing']['reportDate'] or 'N/A'
            
            print(f"{date:<12} {company:<25} {ticker:<8} {report_date:<12}")
    else:
        print(f"\nNo {form_type} filings found in the last {days_back} days")
    
    print(f"\n{'='*70}\n")

# Track 10-Q quarterly reports
track_filings(
    ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META'],
    form_type='10-Q',
    days_back=120
)

# Track 8-K current reports
track_filings(
    ['TSLA', 'NVDA', 'AMD'],
    form_type='8-K',
    days_back=30
)
```

---

## 10. Sample Code & Workflows

### 10.1 Complete Company Analysis Script

```python
#!/usr/bin/env python3
"""
Enhanced EDGAR Tools - Complete Company Analysis
Comprehensive analysis workflow combining multiple tools

Copyright © 2025-2030 Ashutosh Sinha
Email: ajsinha@gmail.com
"""

import sys
import time
from datetime import datetime

# Add path to enhanced_edgar_tools
sys.path.append('/path/to/enhanced_edgar_tools')

from enhanced_edgar_tool import (
    EDGARCompanySearchTool,
    EDGARCompanySubmissionsTool,
    EDGARCompanyConceptTool,
    EDGARFinancialRatiosTool,
    EDGARInsiderTransactionsTool,
    EDGARCurrentReportsTool
)

class CompanyAnalyzer:
    """Complete company analysis using EDGAR tools"""
    
    def __init__(self):
        self.search_tool = EDGARCompanySearchTool()
        self.submissions_tool = EDGARCompanySubmissionsTool()
        self.concept_tool = EDGARCompanyConceptTool()
        self.ratios_tool = EDGARFinancialRatiosTool()
        self.insider_tool = EDGARInsiderTransactionsTool()
        self.reports_tool = EDGARCurrentReportsTool()
    
    def analyze(self, ticker_or_name):
        """Run complete analysis"""
        
        print(f"\n{'='*70}")
        print(f"EDGAR COMPANY ANALYSIS: {ticker_or_name}")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print('='*70)
        
        # Step 1: Company Discovery
        print(f"\n{'─'*70}")
        print("STEP 1: COMPANY DISCOVERY")
        print('─'*70)
        
        result = self.search_tool.execute({'query': ticker_or_name, 'limit': 1})
        
        if result['results_count'] == 0:
            print(f"❌ Company not found: {ticker_or_name}")
            return None
        
        company = result['companies'][0]
        cik = company['cik']
        
        print(f"\n✓ Found: {company['title']}")
        print(f"  Ticker: {company['ticker']}")
        print(f"  CIK: {cik}")
        print(f"  Exchange: {company['exchange']}")
        
        # Step 2: Company Information
        print(f"\n{'─'*70}")
        print("STEP 2: COMPANY INFORMATION")
        print('─'*70)
        
        info = self.submissions_tool.execute({'cik': cik})
        
        print(f"\nLegal Name: {info['name']}")
        print(f"Industry: {info['sicDescription']}")
        print(f"SIC Code: {info['sic']}")
        print(f"Fiscal Year End: {info['fiscalYearEnd']}")
        print(f"Filer Category: {info['category']}")
        print(f"State of Incorporation: {info['stateOfIncorporation']}")
        
        print(f"\nBusiness Address:")
        biz_addr = info['addresses']['business']
        print(f"  {biz_addr.get('street1', '')}")
        if biz_addr.get('street2'):
            print(f"  {biz_addr['street2']}")
        print(f"  {biz_addr.get('city', '')}, {biz_addr.get('stateOrCountry', '')} {biz_addr.get('zipCode', '')}")
        
        print(f"\nRecent Filings: {info['filings_count']}")
        print(f"Last 5 filings:")
        for filing in info['recent_filings'][:5]:
            print(f"  - {filing['filingDate']}: {filing['form']}")
        
        time.sleep(0.15)  # Rate limiting
        
        # Step 3: Revenue Analysis
        print(f"\n{'─'*70}")
        print("STEP 3: REVENUE ANALYSIS")
        print('─'*70)
        
        try:
            revenue = self.concept_tool.execute({
                'cik': cik,
                'concept': 'Revenues'
            })
            
            print(f"\nRevenue Concept: {revenue['label']}")
            
            usd_values = revenue['units'].get('USD', [])
            annual = [v for v in usd_values if v.get('fp') == 'FY']
            annual_sorted = sorted(annual, key=lambda x: x['fy'], reverse=True)
            
            print(f"\nRevenue History (Last 5 Years):")
            print(f"{'Year':<8} {'Revenue':<20} {'Growth':>10}")
            print('-'*40)
            
            prev_revenue = None
            for obs in annual_sorted[:5]:
                revenue_val = obs['val']
                
                if prev_revenue:
                    growth = ((revenue_val - prev_revenue) / prev_revenue) * 100
                    growth_str = f"{growth:+.1f}%"
                else:
                    growth_str = "N/A"
                
                print(f"FY{obs['fy']:<5} ${revenue_val:>17,.0f}  {growth_str:>9}")
                prev_revenue = revenue_val
                
        except Exception as e:
            print(f"\n⚠️  Revenue data not available: {e}")
        
        time.sleep(0.15)  # Rate limiting
        
        # Step 4: Financial Ratios
        print(f"\n{'─'*70}")
        print("STEP 4: FINANCIAL RATIOS (FY2023)")
        print('─'*70)
        
        try:
            ratios = self.ratios_tool.execute({
                'cik': cik,
                'fiscal_year': 2023
            })
            
            print("\n📊 Profitability Ratios:")
            prof = ratios['profitability_ratios']
            for key, value in prof.items():
                if value is not None:
                    label = key.replace('_', ' ').title()
                    unit = '%' if 'margin' in key or 'return' in key else ''
                    print(f"   {label:<25} {value:>8.2f}{unit}")
            
            print("\n💧 Liquidity Ratios:")
            liq = ratios['liquidity_ratios']
            for key, value in liq.items():
                if value is not None:
                    label = key.replace('_', ' ').title()
                    print(f"   {label:<25} {value:>8.2f}")
            
            print("\n⚖️  Solvency Ratios:")
            solv = ratios['solvency_ratios']
            for key, value in solv.items():
                if value is not None:
                    label = key.replace('_', ' ').title()
                    print(f"   {label:<25} {value:>8.2f}")
                    
        except Exception as e:
            print(f"\n⚠️  Financial ratios not available: {e}")
        
        time.sleep(0.15)  # Rate limiting
        
        # Step 5: Insider Activity
        print(f"\n{'─'*70}")
        print("STEP 5: INSIDER TRADING ACTIVITY")
        print('─'*70)
        
        try:
            insider = self.insider_tool.execute({'cik': cik, 'limit': 10})
            
            print(f"\nRecent Form 4 Filings: {insider['transactions_count']}")
            print(f"\nLast 5 insider transactions:")
            
            for txn in insider['transactions'][:5]:
                print(f"  - {txn['filingDate']}: Form 4 filed")
                print(f"    Transaction Date: {txn['reportDate']}")
                
        except Exception as e:
            print(f"\n⚠️  Insider activity data not available: {e}")
        
        time.sleep(0.15)  # Rate limiting
        
        # Step 6: Recent Material Events
        print(f"\n{'─'*70}")
        print("STEP 6: RECENT MATERIAL EVENTS (8-K)")
        print('─'*70)
        
        try:
            reports = self.reports_tool.execute({
                'cik': cik,
                'limit': 5
            })
            
            print(f"\nRecent 8-K Reports: {reports['reports_count']}")
            print(f"\nLast 5 current reports:")
            
            for report in reports['reports'][:5]:
                print(f"  - {report['filingDate']}: {report.get('primaryDocDescription', 'Current Report')}")
                
        except Exception as e:
            print(f"\n⚠️  8-K reports not available: {e}")
        
        # Summary
        print(f"\n{'='*70}")
        print("ANALYSIS COMPLETE")
        print('='*70)
        print(f"\nCompany: {company['title']} ({company['ticker']})")
        print(f"CIK: {cik}")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"\nFor more information, visit:")
        print(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}")
        print(f"\n{'='*70}\n")
        
        return {
            'cik': cik,
            'company': company,
            'info': info
        }

def main():
    """Main function"""
    
    analyzer = CompanyAnalyzer()
    
    # Analyze companies
    companies = ['AAPL', 'MSFT', 'GOOGL']
    
    for company in companies:
        try:
            analyzer.analyze(company)
            time.sleep(1)  # Pause between companies
        except Exception as e:
            print(f"\nError analyzing {company}: {e}\n")

if __name__ == "__main__":
    main()
```

**Save as:** `company_analyzer.py`

**Run:**
```bash
python company_analyzer.py
```

---

## 11. Best Practices

### 11.1 Caching Strategy

Implement caching to reduce API calls and improve performance:

```python
import json
import os
from datetime import datetime, timedelta

class EDGARCache:
    """Simple file-based cache for EDGAR API responses"""
    
    def __init__(self, cache_dir='edgar_cache'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_path(self, key):
        """Get cache file path for key"""
        safe_key = key.replace('/', '_').replace(':', '_')
        return os.path.join(self.cache_dir, f"{safe_key}.json")
    
    def get(self, key, max_age_hours=24):
        """Get cached data if not expired"""
        cache_path = self._get_cache_path(key)
        
        if not os.path.exists(cache_path):
            return None
        
        # Check age
        file_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        age = datetime.now() - file_time
        
        if age > timedelta(hours=max_age_hours):
            return None
        
        with open(cache_path, 'r') as f:
            return json.load(f)
    
    def set(self, key, data):
        """Cache data"""
        cache_path = self._get_cache_path(key)
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    
    def clear(self):
        """Clear all cache"""
        for file in os.listdir(self.cache_dir):
            os.remove(os.path.join(self.cache_dir, file))

# Usage example
from enhanced_edgar_tool import EDGARCompanySubmissionsTool

cache = EDGARCache()

def get_company_info(cik, use_cache=True):
    """Get company info with caching"""
    cache_key = f"submissions_{cik}"
    
    # Try cache first
    if use_cache:
        cached = cache.get(cache_key, max_age_hours=24)
        if cached:
            print("✓ Using cached data")
            return cached
    
    # Fetch from API
    print("→ Fetching from API")
    tool = EDGARCompanySubmissionsTool()
    result = tool.execute({'cik': cik})
    
    # Cache result
    cache.set(cache_key, result)
    
    return result

# Use it
result = get_company_info('320193')  # Fetches from API
result = get_company_info('320193')  # Uses cache
```

### 11.2 Error Handling

Implement robust error handling:

```python
import time
from enhanced_edgar_tool import EDGARCompanySearchTool

def safe_execute(tool, arguments, max_retries=3, backoff_factor=2):
    """Execute tool with retry logic and error handling"""
    
    for attempt in range(max_retries):
        try:
            return tool.execute(arguments)
        
        except ValueError as e:
            error_msg = str(e)
            
            # Handle rate limiting
            if "Rate limit" in error_msg or "429" in error_msg:
                wait_time = backoff_factor ** attempt
                print(f"⚠️  Rate limited. Waiting {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
                continue
            
            # Handle not found
            elif "not found" in error_msg or "404" in error_msg:
                print(f"❌ Resource not found: {error_msg}")
                return None
            
            # Handle other errors
            else:
                print(f"❌ Error: {error_msg}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise
        
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            raise
    
    raise Exception(f"Failed after {max_retries} retries")

# Usage
tool = EDGARCompanySearchTool()
result = safe_execute(tool, {'query': 'AAPL'})
```

### 11.3 Batch Processing

Process multiple items efficiently:

```python
import time
from enhanced_edgar_tool import EDGARCompanyConceptTool

def batch_get_revenue(ciks, delay=0.15, max_workers=1):
    """Get revenue for multiple companies with rate limiting"""
    
    tool = EDGARCompanyConceptTool()
    results = {}
    
    print(f"Processing {len(ciks)} companies...")
    
    for i, cik in enumerate(ciks):
        print(f"\nProcessing {i+1}/{len(ciks)}: CIK {cik}")
        
        try:
            result = tool.execute({
                'cik': cik,
                'concept': 'Revenues'
            })
            
            # Extract latest annual revenue
            usd_values = result['units'].get('USD', [])
            annual = [v for v in usd_values if v.get('fp') == 'FY']
            
            if annual:
                latest = sorted(annual, key=lambda x: x['fy'], reverse=True)[0]
                results[cik] = {
                    'success': True,
                    'entity_name': result['entityName'],
                    'fiscal_year': latest['fy'],
                    'revenue': latest['val'],
                    'filed': latest['filed']
                }
                print(f"  ✓ FY{latest['fy']}: ${latest['val']:,.0f}")
            else:
                results[cik] = {
                    'success': False,
                    'error': 'No annual revenue data'
                }
                print(f"  ⚠️  No annual revenue data")
                
        except Exception as e:
            results[cik] = {
                'success': False,
                'error': str(e)
            }
            print(f"  ❌ Error: {e}")
        
        # Rate limiting
        if i < len(ciks) - 1:
            time.sleep(delay)
    
    return results

# Usage
ciks = ['320193', '789019', '1318605', '1652044', '1067983']
revenues = batch_get_revenue(ciks)

# Print summary
print(f"\n{'='*70}")
print("BATCH PROCESSING SUMMARY")
print('='*70)

successful = [r for r in revenues.values() if r.get('success')]
print(f"\nSuccessful: {len(successful)}/{len(ciks)}")

for cik, result in revenues.items():
    if result.get('success'):
        print(f"\n{result['entity_name']}:")
        print(f"  CIK: {cik}")
        print(f"  FY{result['fiscal_year']} Revenue: ${result['revenue']:,.0f}")
    else:
        print(f"\n❌ CIK {cik}: {result.get('error')}")
```

### 11.4 Data Validation

Validate financial data quality:

```python
def validate_financial_data(data, concept='Revenue'):
    """Validate financial data quality"""
    
    warnings = []
    errors = []
    
    # Check for None values
    if data.get('value') is None:
        errors.append("Missing value")
        return {'valid': False, 'errors': errors, 'warnings': warnings}
    
    value = data['value']
    
    # Check for negative values (red flag for revenue/assets)
    if concept in ['Revenue', 'Revenues', 'Assets'] and value < 0:
        warnings.append(f"Negative {concept} - possible error or restated")
    
    # Check for extreme values
    if value > 1e15:  # $1 quadrillion
        warnings.append("Unusually large value - possible data error")
    
    if value == 0:
        warnings.append("Zero value - check if intentional")
    
    # Check for suspicious round numbers
    if value > 1e9 and value % 1e9 == 0:
        warnings.append("Suspiciously round number")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }

# Usage
validation = validate_financial_data({
    'concept': 'Revenue',
    'value': 1000000000
})

if not validation['valid']:
    print("❌ Data validation failed:")
    for error in validation['errors']:
        print(f"  - {error}")

if validation['warnings']:
    print("⚠️  Data quality warnings:")
    for warning in validation['warnings']:
        print(f"  - {warning}")
```

### 11.5 Progress Tracking

Track progress for long-running operations:

```python
from enhanced_edgar_tool import EDGARCompanyConceptTool
import time

class ProgressTracker:
    """Track progress of batch operations"""
    
    def __init__(self, total):
        self.total = total
        self.current = 0
        self.start_time = time.time()
    
    def update(self, increment=1):
        """Update progress"""
        self.current += increment
        
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        remaining = (self.total - self.current) / rate if rate > 0 else 0
        
        percent = (self.current / self.total) * 100
        
        print(f"Progress: {self.current}/{self.total} ({percent:.1f}%) - "
              f"Rate: {rate:.2f}/s - ETA: {remaining:.0f}s")

# Usage
ciks = ['320193', '789019', '1318605', '1652044', '1067983']
tool = EDGARCompanyConceptTool()
tracker = ProgressTracker(len(ciks))

results = []
for cik in ciks:
    try:
        result = tool.execute({'cik': cik, 'concept': 'Revenues'})
        results.append(result)
    except:
        pass
    
    tracker.update()
    time.sleep(0.15)
```

---

## 12. Limitations & Warnings

### 12.1 SEC Data Limitations

#### Historical Coverage
- **XBRL data**: Available from approximately 2009 onwards
- **Pre-2009 data**: Limited to text-based filings (not structured)
- **Impact**: Historical analysis constrained to last ~15 years

#### Foreign Issuers
- **IFRS vs US-GAAP**: Foreign companies may use different accounting standards
- **Concept names differ**: Same metric may have different XBRL tags
- **Impact**: Need to check multiple concept names for international companies

#### Private Companies
- **No data**: SEC EDGAR only covers publicly traded companies
- **Exemptions**: Some small public companies may not file XBRL
- **Impact**: Private company analysis not possible

#### Real-time Delays
- **Processing time**: Filings available after SEC processing
- **Delay**: Minutes to hours after submission
- **Impact**: Not suitable for real-time trading signals

### 12.2 Technical Limitations

| Issue | Description | Workaround |
|-------|-------------|------------|
| **Response Size** | Company facts can be 50+ MB | Use edgar_company_concept for specific metrics |
| **Rate Limits** | Max 10 requests/second | Built-in rate limiting handles this |
| **Network Timeouts** | Large responses may timeout | Implement retry logic, increase timeout |
| **Concept Naming** | XBRL concepts vary across companies | Try multiple concept names |
| **Missing Data** | Not all companies report all metrics | Handle None values gracefully |
| **API Changes** | SEC may update API | Monitor SEC announcements |

### 12.3 Data Quality Issues

⚠️ **Potential Issues:**

**Amended Filings:**
- Companies may file amendments (/A) with corrections
- Original filings may contain errors
- Always check for amendments

**Restatements:**
- Companies may restate historical financials
- Past data may change
- Compare multiple time periods for consistency

**Concept Tagging:**
- XBRL concept tagging inconsistencies
- Same item may use different tags
- Validate data across multiple sources

**Voluntary Disclosure:**
- Some metrics are voluntary
- Disclosure varies by company
- Missing data doesn't always mean zero

**Best Practice:** Always verify critical data with official SEC filings

### 12.4 Use Case Limitations

❌ **NOT suitable for:**

1. **Real-time Trading**
   - Data has processing delays
   - Not tick-by-tick
   - Use market data feeds instead

2. **Private Company Analysis**
   - No SEC filing requirement
   - No data available
   - Use alternative sources

3. **Pre-2009 Historical Analysis**
   - Limited XBRL data
   - Text-based filings only
   - Manual extraction required

4. **International Companies (Non-SEC)**
   - Only companies registered with SEC
   - Foreign issuers exempt from some requirements
   - Use local regulatory databases

5. **Intraday Events**
   - No real-time event stream
   - Check daily for new filings
   - Use news services for real-time

✅ **EXCELLENT for:**

1. **Fundamental Analysis**
   - Company financials
   - Historical trends
   - Ratio analysis

2. **Long-term Research**
   - Academic studies
   - Industry analysis
   - Corporate governance

3. **Compliance Monitoring**
   - Filing tracking
   - Insider surveillance
   - Ownership changes

4. **Data Extraction**
   - Building databases
   - Financial models
   - Analytics platforms

### 12.5 Response Size Warnings

**Large Responses:**

1. **edgar_company_facts**
   - Can be 5-50 MB for major companies
   - Contains ALL financial facts
   - Use edgar_company_concept instead for specific metrics

2. **edgar_frame_data**
   - Contains data for thousands of companies
   - Can be 10-100 MB
   - Consider filtering on client side

3. **edgar_company_submissions**
   - May include thousands of filings
   - Use limits and date filters
   - Request only recent filings if possible

**Mitigation Strategies:**
- Use more specific tools (concept vs facts)
- Implement response streaming
- Filter data on server side
- Cache large responses
- Use pagination where available

---

## 13. Troubleshooting

### 13.1 Common Errors

#### Error: HTTP 403 Forbidden

**Error Message:**
```
ValueError: Access forbidden. Ensure User-Agent header is properly set.
```

**Cause:** Missing or invalid User-Agent header

**Solution:**
```python
# Verify User-Agent is set
from enhanced_edgar_tool import EDGARBaseTool

tool = EDGARBaseTool()
print(tool.headers['User-Agent'])

# Should output something like:
# Enhanced EDGAR Tool ashutosh.sinha@research.com

# If you need to customize:
tool.headers['User-Agent'] = 'YourCompany youremail@company.com'
```

---

#### Error: Rate Limit Exceeded

**Error Message:**
```
ValueError: Rate limit exceeded. SEC allows max 10 requests/second.
```

**Cause:** Too many requests in short time period

**Solution:**
```python
import time

# Built-in rate limiting should prevent this,
# but if you're making manual requests:

# Add delay between requests
time.sleep(0.15)  # 150ms = ~6.6 req/sec

# Or use exponential backoff on retry
for attempt in range(3):
    try:
        result = tool.execute(arguments)
        break
    except ValueError as e:
        if "Rate limit" in str(e):
            wait = 2 ** attempt
            print(f"Waiting {wait}s...")
            time.sleep(wait)
        else:
            raise
```

---

#### Error: Company Not Found

**Error Message:**
```
ValueError: Resource not found
```

**Cause:** Invalid CIK, company delisted, or typo in name/ticker

**Solution:**
```python
from enhanced_edgar_tool import EDGARCompanySearchTool

# Always search first to get correct CIK
search = EDGARCompanySearchTool()
result = search.execute({'query': 'AAPL'})

if result['results_count'] == 0:
    print("Company not found - check spelling/ticker")
else:
    cik = result['companies'][0]['cik']
    print(f"Found CIK: {cik}")
```

---

#### Error: Concept Not Found

**Error Message:**
```
ValueError: Resource not found: .../Revenues.json
```

**Cause:** XBRL concept name varies across companies

**Solution:**
```python
# Try multiple concept names
concept_names = [
    'Revenues',
    'Revenue',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'SalesRevenueNet'
]

for concept in concept_names:
    try:
        result = tool.execute({
            'cik': cik,
            'concept': concept
        })
        print(f"✓ Found using: {concept}")
        break
    except ValueError:
        print(f"✗ Not found: {concept}")
        continue
else:
    print("❌ Revenue concept not available for this company")
```

---

#### Error: Network Timeout

**Error Message:**
```
urllib.error.URLError: <urlopen error timed out>
```

**Cause:** Large response or slow network

**Solution:**
```python
import urllib.request

# Increase timeout in base tool
# Edit enhanced_edgar_tool.py:

with urllib.request.urlopen(req, timeout=60) as response:  # 60s
    data = json.loads(response.read().decode('utf-8'))

# Or implement retry with larger timeout
```

---

#### Error: JSON Decode Error

**Error Message:**
```
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Cause:** Invalid response from server (possibly blocked or error page)

**Solution:**
```python
# Check User-Agent header
# Check network connection
# Verify URL is correct
# Check SEC website status: https://www.sec.gov/

# Add error handling:
try:
    data = json.loads(response.read().decode('utf-8'))
except json.JSONDecodeError:
    print("Invalid JSON response")
    print(f"Response content: {response.read()}")
    raise
```

---

#### Error: Import Error

**Error Message:**
```
ImportError: No module named 'enhanced_edgar_tool'
```

**Cause:** Python can't find the module

**Solution:**
```python
import sys
import os

# Add to path
sys.path.append('/path/to/enhanced_edgar_tools')

# Or use absolute import
sys.path.insert(0, os.path.abspath('/path/to/enhanced_edgar_tools'))

# Verify:
from enhanced_edgar_tool import EDGAR_TOOLS
print(f"Loaded {len(EDGAR_TOOLS)} tools")
```

---

### 13.2 Data Issues

#### Issue: Missing Financial Data

**Problem:** Company has filings but no XBRL financial data

**Possible Causes:**
- Company hasn't filed XBRL yet (pre-2009 filers)
- Small company exempt from XBRL
- Foreign issuer using different format

**Solution:**
```python
# Check filing history
tool = EDGARCompanySubmissionsTool()
result = tool.execute({'cik': cik})

print("Recent filings:")
for filing in result['recent_filings'][:10]:
    print(f"  {filing['filingDate']}: {filing['form']}")

# Look for XBRL-containing forms:
# 10-K, 10-Q (usually have XBRL)
# 20-F, 40-F (may have XBRL)

# If no XBRL forms, data not available through this toolkit
```

---

#### Issue: Inconsistent Data

**Problem:** Same metric has different values in different queries

**Possible Causes:**
- Restatements
- Amendments
- Different fiscal periods
- Rounding differences

**Solution:**
```python
# Always check:
# 1. Filing date
# 2. Fiscal year and period
# 3. Amendment status

# Compare values:
result1 = tool.execute({'cik': cik, 'concept': 'Revenues'})
for obs in result1['units']['USD'][-5:]:
    print(f"FY{obs['fy']}{obs['fp']}: ${obs['val']:,.0f}")
    print(f"  Filed: {obs['filed']} via {obs['form']}")
    print(f"  Accession: {obs['accn']}")

# Check for amendments
amendments_tool = EDGARAmendmentsTool()
amendments = amendments_tool.execute({'cik': cik})

if amendments['amendments_count'] > 0:
    print("⚠️  Company has filed amendments - data may have changed")
```

---

#### Issue: Negative Revenue or Assets

**Problem:** Financial metrics have negative values where they shouldn't

**Possible Causes:**
- Data error
- Accounting adjustment
- Restatement
- Special circumstances (e.g., returns)

**Solution:**
```python
# Validate data
def validate_value(concept, value):
    warnings = []
    
    # Revenue/Assets should generally be positive
    if concept in ['Revenue', 'Revenues', 'Assets'] and value < 0:
        warnings.append(f"Negative {concept}: ${value:,.0f}")
    
    # Flag zero values
    if value == 0:
        warnings.append(f"Zero {concept}")
    
    return warnings

# Use validation
warnings = validate_value('Revenue', revenue_value)
if warnings:
    print("⚠️  Data warnings:")
    for w in warnings:
        print(f"  - {w}")
    print("  → Check original filing for explanation")
```

---

### 13.3 Getting Help

#### For SEC EDGAR API Issues

**SEC Resources:**
- API Documentation: https://www.sec.gov/edgar/sec-api-documentation
- EDGAR Help: https://www.sec.gov/edgar/searchedgar/webusers.htm
- SEC Support: webmaster@sec.gov

**SEC Website Status:**
- Check: https://www.sec.gov/
- Outages rare but possible

#### For Toolkit Issues

**Self-Help Checklist:**
1. ✅ Check documentation (this file)
2. ✅ Review examples and sample code
3. ✅ Verify Python version (3.7+)
4. ✅ Check internet connection
5. ✅ Verify User-Agent header
6. ✅ Test with known-good CIK (e.g., '320193' for Apple)

**Contact:**
- Author: Ashutosh Sinha
- Email: ajsinha@gmail.com

**Include in Bug Reports:**
- Python version
- Error message (full traceback)
- Code that reproduces the issue
- CIK being queried
- Expected vs actual behavior

---

## 14. Legal Notice & License

### 14.1 Copyright

**Copyright © 2025-2030 Ashutosh Sinha. All Rights Reserved.**

This software and documentation are protected by copyright law. Unauthorized reproduction or distribution of this software, or any portion of it, may result in severe civil and criminal penalties, and will be prosecuted to the maximum extent possible under law.

### 14.2 License Terms

This software is provided "as is" without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement.

**Permitted Use:**
- ✅ Personal research and analysis
- ✅ Academic research
- ✅ Internal business use
- ✅ Non-commercial applications

**Restrictions:**
- ❌ Redistribution without permission
- ❌ Commercial sale or licensing
- ❌ Modification without attribution
- ❌ Removal of copyright notices

### 14.3 Disclaimer

**THIS TOOLKIT IS FOR INFORMATIONAL AND RESEARCH PURPOSES ONLY.**

The author and contributors:
- ❌ Do NOT provide investment advice
- ❌ Do NOT provide financial advice
- ❌ Do NOT provide legal advice
- ❌ Do NOT provide accounting advice
- ❌ Make NO warranties about data accuracy
- ❌ Accept NO liability for investment decisions

**Users acknowledge:**
- All investment decisions are their own responsibility
- Data may contain errors or be outdated
- Professional advice should be sought for important decisions
- SEC filings are the authoritative source
- This toolkit is a convenience tool, not a substitute for due diligence

### 14.4 Data Source Attribution

**Source:** U.S. Securities and Exchange Commission (SEC)  
**Database:** EDGAR (Electronic Data Gathering, Analysis, and Retrieval)  
**Access:** Public domain data made available free of charge

**Acknowledgment:**
- All data accessed through this toolkit is from SEC EDGAR
- SEC makes this data publicly available
- This toolkit merely provides convenient programmatic access
- Users must comply with SEC's fair access policies

### 14.5 Compliance Requirements

**Users of this toolkit MUST:**

1. **✅ User-Agent Header**
   - Include proper User-Agent with contact information
   - Already configured in toolkit
   - SEC requirement for identification

2. **✅ Rate Limits**
   - Respect 10 requests/second limit
   - Built-in rate limiting enforces this
   - Do not attempt to circumvent

3. **✅ Fair Use**
   - Use data responsibly
   - Do not overwhelm SEC systems
   - Do not attempt denial of service

4. **✅ SEC Terms**
   - Comply with SEC website terms of use
   - Follow SEC fair access guidelines
   - Report any issues to SEC

**Violations may result in:**
- IP address blocking by SEC
- Legal action by SEC
- Criminal penalties
- Civil liability

### 14.6 Limitation of Liability

**IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE FOR:**
- Any direct, indirect, incidental, special, or consequential damages
- Loss of profits, data, or business opportunities
- Investment losses or financial damages
- Errors or omissions in data
- Service interruptions or unavailability
- Any damages arising from use of this software

**USER ASSUMES ALL RISK** associated with the use of this software and data.

### 14.7 Warranty Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO:
- Warranties of merchantability
- Fitness for a particular purpose
- Non-infringement
- Accuracy or completeness
- Availability or reliability

### 14.8 Attribution

**If using this toolkit in research or publications:**

**Suggested Citation:**
```
Sinha, A. (2025). Enhanced EDGAR MCP Tools (Version 1.0.0) [Computer software].
Email: ajsinha@gmail.com
```

**Required Attribution:**
- Include copyright notice in any derivative works
- Credit original author (Ashutosh Sinha)
- Do not imply endorsement by author

### 14.9 Modifications

**If modifying this software:**
- Retain all copyright notices
- Clearly mark modifications
- Do not claim original authorship
- Provide attribution to original work

### 14.10 Governing Law

This agreement shall be governed by and construed in accordance with applicable laws, without regard to conflict of law provisions.

---

## 15. Support & Contact

### 15.1 Contact Information

**Author:** Ashutosh Sinha  
**Email:** ajsinha@gmail.com

### 15.2 Support Channels

**For Bug Reports:**
- Email: ajsinha@gmail.com
- Subject: "Enhanced EDGAR Tools - Bug Report"
- Include: Python version, error message, code snippet

**For Feature Requests:**
- Email: ajsinha@gmail.com
- Subject: "Enhanced EDGAR Tools - Feature Request"
- Include: Detailed description, use case, examples

**For Questions:**
- Email: ajsinha@gmail.com
- Subject: "Enhanced EDGAR Tools - Question"
- Include: What you're trying to accomplish, code example

### 15.3 Documentation Feedback

Help improve this documentation:
- Report errors or unclear sections
- Suggest additional examples
- Request clarifications
- Share use cases

### 15.4 Community

**Share Your Work:**
- Research papers using this toolkit
- Analysis workflows
- Integration examples
- Extension tools

**Stay Updated:**
- Check for updates
- Monitor SEC API changes
- Follow best practices

---

## Appendix A: Quick Reference Card

### Common CIKs
- **Apple Inc:** 0000320193
- **Microsoft:** 0000789019
- **Google/Alphabet:** 0001652044
- **Amazon:** 0001018724
- **Tesla:** 0001318605
- **Meta/Facebook:** 0001326801
- **Berkshire Hathaway:** 0001067983
- **JPMorgan Chase:** 0000019617

### Common SIC Codes
- **7372** - Prepackaged Software
- **3674** - Semiconductors
- **6022** - State Commercial Banks
- **2834** - Pharmaceutical Preparations
- **3711** - Motor Vehicles
- **5961** - Catalog & Mail-Order Houses

### Common XBRL Concepts
- **Revenue:** Revenues, Revenue
- **Net Income:** NetIncomeLoss
- **Assets:** Assets
- **Liabilities:** Liabilities
- **Equity:** StockholdersEquity
- **Cash:** CashAndCashEquivalentsAtCarryingValue
- **EPS:** EarningsPerShareBasic

### Common Form Types
- **10-K** - Annual Report
- **10-Q** - Quarterly Report
- **8-K** - Current Report
- **DEF 14A** - Proxy Statement
- **4** - Insider Trading
- **13F-HR** - Institutional Holdings

---

## Appendix B: Version History

### Version 1.0.0 (November 2025)
- ✅ Initial release
- ✅ 20 tools implemented
- ✅ Comprehensive documentation
- ✅ Pure Python implementation
- ✅ Zero external dependencies

---

## Appendix C: Acknowledgments

**Data Source:**
U.S. Securities and Exchange Commission (SEC)  
EDGAR Database

**Python Community:**
For excellent standard library modules

**Financial Research Community:**
For feedback and use case identification

---

**End of Documentation**

**Enhanced EDGAR MCP Tools v1.0.0**  
**Copyright © 2025-2030 Ashutosh Sinha. All Rights Reserved.**  
**Email:** ajsinha@gmail.com

**Built with ❤️ for the financial research community**

---

*This documentation was last updated: November 2025*  
*Total pages: 150+ (equivalent)*  
*Word count: 25,000+ words*

---

## Page Glossary

**Key terms referenced in this document:**

- **EDGAR (Electronic Data Gathering, Analysis, and Retrieval)**: SEC's electronic filing system. Enhanced EDGAR tools provide advanced access.

- **Full-Text Search**: Searching through complete document content. Enhanced EDGAR supports searching within filings.

- **XBRL (eXtensible Business Reporting Language)**: A standard for electronic business reporting. SEC filings include XBRL data.

- **Form Type**: Category of SEC filing (10-K, 10-Q, 8-K, DEF 14A, etc.). Each serves a different purpose.

- **Exhibit**: A document attached to an SEC filing (contracts, bylaws, certifications).

- **Filing Date**: The date a document was submitted to the SEC.

- **Accession Number**: A unique identifier assigned by the SEC to each filing.

- **SIC Code**: Standard Industrial Classification code categorizing companies by industry.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
