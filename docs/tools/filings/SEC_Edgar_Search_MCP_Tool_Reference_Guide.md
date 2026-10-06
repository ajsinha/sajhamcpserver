# SEC Edgar Search MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**All Rights Reserved**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Tool Inventory](#tool-inventory)
5. [Detailed Tool Specifications](#detailed-tool-specifications)
6. [Schema Definitions](#schema-definitions)
7. [Working Mechanism](#working-mechanism)
8. [Authentication & Security](#authentication--security)
9. [Limitations & Constraints](#limitations--constraints)
10. [Sample Code & Usage](#sample-code--usage)
11. [Error Handling](#error-handling)
12. [Performance Considerations](#performance-considerations)
13. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The **SEC Edgar Search MCP Tool** is a comprehensive suite of tools designed to access and retrieve financial data from the U.S. Securities and Exchange Commission (SEC) EDGAR database through official public APIs. The toolkit provides capabilities for company search, financial data extraction, filings retrieval, insider trading monitoring, and institutional holdings analysis.

### Key Features

- **Company Search**: Find companies by name or ticker symbol
- **Company Information**: Retrieve detailed company profiles and metadata
- **SEC Filings**: Access 10-K, 10-Q, 8-K, and other regulatory filings
- **Financial Data**: Extract XBRL-formatted financial metrics
- **Insider Trading**: Monitor Form 4 insider transactions
- **Institutional Holdings**: Track Form 13F institutional positions
- **XBRL Facts**: Access comprehensive structured financial data

### Use Cases

- Financial analysis and research
- Regulatory compliance monitoring
- Investment research and due diligence
- Market intelligence gathering
- Insider trading analysis
- Institutional investor tracking
- Financial modeling and valuation

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Client Layer                      │
│         (AI Systems/Financial Applications)              │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ MCP Protocol
                       │
┌──────────────────────▼──────────────────────────────────┐
│              SEC Edgar Tool Registry                     │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - sec_search_company                             │  │
│  │  - sec_get_company_info                           │  │
│  │  - sec_get_company_filings                        │  │
│  │  - sec_get_company_facts                          │  │
│  │  - sec_get_financial_data                         │  │
│  │  - sec_get_insider_trading                        │  │
│  │  - sec_get_mutual_fund_holdings                   │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│           SECEdgarBaseTool (Base Class)                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - CIK normalization                              │  │
│  │  - Ticker to CIK conversion                       │  │
│  │  - User-Agent management                          │  │
│  │  - HTTP request handling                          │  │
│  │  - Filing type definitions                        │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                 HTTP/HTTPS Layer                         │
│             urllib.request module                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ HTTPS API Calls
                       │ User-Agent: SAJHA-MCP-Server/1.0
                       │
┌──────────────────────▼──────────────────────────────────┐
│              SEC EDGAR Public APIs                       │
│  ┌───────────────────────────────────────────────────┐  │
│  │  - https://data.sec.gov/api/xbrl/                 │  │
│  │  - https://data.sec.gov/submissions/              │  │
│  │  - https://www.sec.gov/files/                     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Component Architecture

```
BaseMCPTool (Abstract)
       │
       │ inherits
       │
SECEdgarBaseTool (Abstract)
       │
       ├── Shared Functionality:
       │   ├── _normalize_cik()
       │   ├── _ticker_to_cik()
       │   ├── _get_cik_from_args()
       │   ├── user_agent (with contact email)
       │   └── filing_types dictionary
       │
       ├── Concrete Tool Classes:
       ├─────► SECSearchCompanyTool
       ├─────► SECGetCompanyInfoTool
       ├─────► SECGetCompanyFilingsTool
       ├─────► SECGetCompanyFactsTool
       ├─────► SECGetFinancialDataTool
       ├─────► SECGetInsiderTradingTool
       └─────► SECGetMutualFundHoldingsTool
```

---

## System Requirements

### Python Version
- Python 3.7 or higher

### Required Dependencies

```bash
# Standard library only - no external dependencies required!
urllib.request   # HTTP requests (built-in)
urllib.parse     # URL encoding (built-in)
json            # JSON parsing (built-in)
typing          # Type hints (built-in)
datetime        # Date handling (built-in)
```

### Installation

No additional installation required - uses Python standard library only!

### Network Requirements

- Internet connectivity required
- Access to SEC EDGAR API endpoints:
  - `https://data.sec.gov`
  - `https://www.sec.gov`
- HTTPS (port 443) access required
- Recommended: Stable connection for large data transfers

---

## Tool Inventory

| Tool Name | Version | Purpose | Data Source |
|-----------|---------|---------|-------------|
| sec_search_company | 1.0.0 | Search companies by name or ticker | SEC Company Tickers |
| sec_get_company_info | 1.0.0 | Get company profile and metadata | SEC Submissions |
| sec_get_company_filings | 1.0.0 | Retrieve SEC filings (10-K, 10-Q, etc.) | SEC Submissions |
| sec_get_company_facts | 1.0.0 | Get all XBRL financial facts | SEC XBRL API |
| sec_get_financial_data | 1.0.0 | Get specific financial metrics | SEC XBRL API |
| sec_get_insider_trading | 1.0.0 | Get Form 4 insider transactions | SEC Submissions |
| sec_get_mutual_fund_holdings | 1.0.0 | Get Form 13F institutional holdings | SEC Submissions |

---

## Detailed Tool Specifications

### 1. sec_search_company

**Description**: Search for companies by name or ticker symbol in SEC EDGAR database

**Category**: Financial Data / Company Discovery

**Input Parameters**:
```json
{
  "search_term": {
    "type": "string",
    "required": true,
    "description": "Company name or ticker (e.g., 'Apple', 'AAPL')"
  },
  "limit": {
    "type": "integer",
    "default": 10,
    "minimum": 1,
    "maximum": 100,
    "description": "Maximum results to return"
  }
}
```

**Output Schema**:
```json
{
  "search_term": "string - Original search query",
  "result_count": "integer - Number of matches found",
  "companies": [
    {
      "cik": "string - 10-digit Central Index Key",
      "name": "string - Company legal name",
      "ticker": "string - Stock ticker symbol",
      "exchange": "string - Stock exchange (Nasdaq, NYSE, etc.)"
    }
  ]
}
```

**Rate Limit**: 10 requests/second  
**Cache TTL**: 3600 seconds (1 hour)

**API Endpoint**: `https://www.sec.gov/files/company_tickers.json`

---

### 2. sec_get_company_info

**Description**: Retrieve detailed company information including business address, SIC code, and fiscal year end

**Category**: Financial Data / Company Profile

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "10-digit Central Index Key"
  },
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol"
  }
}
```
**Note**: Either `cik` OR `ticker` must be provided (oneOf constraint)

**Output Schema**:
```json
{
  "cik": "string - 10-digit CIK",
  "name": "string - Company legal name",
  "tickers": ["string array - All ticker symbols"],
  "sic": "string - Standard Industrial Classification code",
  "sic_description": "string - Industry description",
  "category": "string - SEC filer category",
  "fiscal_year_end": "string - MMDD format",
  "state_of_incorporation": "string - State or country",
  "business_address": {
    "street1": "string",
    "street2": "string",
    "city": "string",
    "stateOrCountry": "string",
    "zipCode": "string"
  },
  "mailing_address": "object - Mailing address",
  "ein": "string - Employer Identification Number",
  "phone": "string - Phone number",
  "exchanges": ["string array - Stock exchanges"],
  "website": "string - Company website URL",
  "investor_website": "string - Investor relations URL"
}
```

**Rate Limit**: 10 requests/second  
**Cache TTL**: 3600 seconds (1 hour)

**API Endpoint**: `https://data.sec.gov/submissions/CIK{cik}.json`

---

### 3. sec_get_company_filings

**Description**: Retrieve SEC filings for a company with optional filtering by type and date range

**Category**: Financial Data / Regulatory Filings

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "10-digit CIK"
  },
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol"
  },
  "filing_type": {
    "type": "string",
    "enum": [
      "10-K", "10-Q", "8-K", "10-K/A", "10-Q/A",
      "S-1", "S-3", "S-4", "13F-HR", "4",
      "DEF 14A", "20-F", "6-K", "SC 13D", "SC 13G"
    ],
    "description": "Filing form type (optional)"
  },
  "start_date": {
    "type": "string",
    "description": "Start date (YYYY-MM-DD)"
  },
  "end_date": {
    "type": "string",
    "description": "End date (YYYY-MM-DD)"
  },
  "limit": {
    "type": "integer",
    "default": 10,
    "minimum": 1,
    "maximum": 100
  }
}
```

**Output Schema**:
```json
{
  "cik": "string",
  "name": "string - Company name",
  "filing_count": "integer",
  "filings": [
    {
      "accession_number": "string - Unique filing ID",
      "filing_date": "string - YYYY-MM-DD",
      "report_date": "string - YYYY-MM-DD",
      "form": "string - Form type (10-K, 10-Q, etc.)",
      "primary_document": "string - Document filename",
      "description": "string - Filing description"
    }
  ]
}
```

**Filing Types**:
- **10-K**: Annual Report
- **10-Q**: Quarterly Report
- **8-K**: Current Report (material events)
- **4**: Insider Trading Statement
- **13F-HR**: Institutional Holdings
- **DEF 14A**: Proxy Statement
- **S-1**: IPO Registration
- **20-F**: Foreign Company Annual Report

**Rate Limit**: 10 requests/second  
**Cache TTL**: 1800 seconds (30 minutes)

**API Endpoint**: `https://data.sec.gov/submissions/CIK{cik}.json`

---

### 4. sec_get_company_facts

**Description**: Retrieve all XBRL financial facts reported by a company in structured format

**Category**: Financial Data / XBRL Data

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "10-digit CIK"
  },
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol"
  }
}
```

**Output Schema**:
```json
{
  "cik": "string",
  "entity_name": "string - Company name",
  "facts": {
    "us-gaap": {
      "Assets": "object - Asset data across periods",
      "Revenues": "object - Revenue data",
      "NetIncomeLoss": "object - Net income data",
      "...": "object - Hundreds of other GAAP metrics"
    },
    "dei": {
      "EntityPublicFloat": "object",
      "EntityCommonStockSharesOutstanding": "object",
      "...": "object"
    },
    "...": "object - Other taxonomies"
  }
}
```

**Taxonomies**:
- **us-gaap**: Generally Accepted Accounting Principles metrics
- **dei**: Document and Entity Information
- **invest**: Investment company facts
- **srt**: SEC Reporting Taxonomy

**Rate Limit**: 10 requests/second  
**Cache TTL**: 3600 seconds (1 hour)

**API Endpoint**: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`

**⚠️ WARNING**: This endpoint returns ALL financial facts and can be very large (>5MB). Consider using `sec_get_financial_data` for specific metrics.

---

### 5. sec_get_financial_data

**Description**: Retrieve specific financial metrics from company XBRL filings

**Category**: Financial Data / Targeted Metrics

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "10-digit CIK"
  },
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol"
  },
  "fact_type": {
    "type": "string",
    "optional": true,
    "enum": [
      "Assets", "Liabilities", "StockholdersEquity",
      "Revenues", "NetIncomeLoss", "EarningsPerShare",
      "Cash", "OperatingIncome", "GrossProfit",
      "CurrentAssets", "CurrentLiabilities", "LongTermDebt"
    ],
    "description": "Specific metric to retrieve. If not provided, returns list of available facts."
  }
}
```

**Output Schema (with fact_type)**:
```json
{
  "cik": "string",
  "entity_name": "string",
  "fact_type": "string - Requested metric",
  "data": [
    {
      "taxonomy": "string - e.g., us-gaap",
      "label": "string - Human-readable label",
      "description": "string - Metric description",
      "units": {
        "USD": [
          {
            "end": "2024-12-31",
            "val": 1234567890,
            "accn": "0001234567-24-000001",
            "fy": 2024,
            "fp": "FY",
            "form": "10-K",
            "filed": "2025-02-15"
          }
        ]
      }
    }
  ]
}
```

**Output Schema (without fact_type)**:
```json
{
  "cik": "string",
  "entity_name": "string",
  "available_facts": {
    "us-gaap": ["Assets", "Liabilities", "Revenues", "..."],
    "dei": ["EntityPublicFloat", "..."]
  }
}
```

**Rate Limit**: 10 requests/second  
**Cache TTL**: 3600 seconds (1 hour)

**API Endpoint**: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`

---

### 6. sec_get_insider_trading

**Description**: Retrieve insider trading reports (Form 4) for company insiders and executives

**Category**: Financial Data / Insider Transactions

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "10-digit CIK"
  },
  "ticker": {
    "type": "string",
    "description": "Stock ticker symbol"
  },
  "limit": {
    "type": "integer",
    "default": 10,
    "minimum": 1,
    "maximum": 100
  }
}
```

**Output Schema**:
```json
{
  "cik": "string",
  "name": "string - Company name",
  "filing_count": "integer - Number of Form 4 filings",
  "filings": [
    {
      "accession_number": "string",
      "filing_date": "string - YYYY-MM-DD",
      "report_date": "string - Transaction date",
      "form": "string - Will be '4'",
      "primary_document": "string",
      "description": "string"
    }
  ]
}
```

**Form 4 Information**:
- **Purpose**: Report changes in beneficial ownership by insiders
- **Filing Deadline**: Within 2 business days of transaction
- **Who Must File**: Officers, Directors, Beneficial owners >10%
- **Transaction Types**: Purchases, sales, option exercises, gifts, awards

**Rate Limit**: 10 requests/second  
**Cache TTL**: 1800 seconds (30 minutes)

**API Endpoint**: `https://data.sec.gov/submissions/CIK{cik}.json`

---

### 7. sec_get_mutual_fund_holdings

**Description**: Retrieve institutional investment manager holdings reports (Form 13F-HR)

**Category**: Financial Data / Institutional Holdings

**Input Parameters**:
```json
{
  "cik": {
    "type": "string",
    "description": "CIK of institutional manager"
  },
  "ticker": {
    "type": "string",
    "description": "Not typically used for institutions"
  },
  "limit": {
    "type": "integer",
    "default": 5,
    "minimum": 1,
    "maximum": 20
  }
}
```

**Output Schema**:
```json
{
  "cik": "string",
  "name": "string - Institution name",
  "filing_count": "integer - Number of 13F filings",
  "filings": [
    {
      "accession_number": "string",
      "filing_date": "string - YYYY-MM-DD",
      "report_date": "string - Quarter end date",
      "form": "string - Will be '13F-HR'",
      "primary_document": "string",
      "description": "string"
    }
  ]
}
```

**Form 13F Information**:
- **Purpose**: Quarterly equity holdings report
- **Who Must File**: Institutional managers with >$100M AUM
- **Filing Deadline**: Within 45 days after quarter end
- **Disclosure**: Security name, CUSIP, shares, market value

**Notable Institutional Managers (CIKs)**:
- Berkshire Hathaway: 0001067983
- Vanguard Group: 0001102694
- BlackRock: 0001364742
- State Street: 0001350694
- Fidelity: 0000315066

**Rate Limit**: 10 requests/second  
**Cache TTL**: 3600 seconds (1 hour)

**API Endpoint**: `https://data.sec.gov/submissions/CIK{cik}.json`

---

## Schema Definitions

### Common Data Types

#### CIK (Central Index Key)
```json
{
  "type": "string",
  "pattern": "^\\d{10}$",
  "description": "10-digit unique company identifier assigned by SEC"
}
```

#### Filing
```json
{
  "accession_number": "string - Format: 0000000000-00-000000",
  "filing_date": "string - ISO date (YYYY-MM-DD)",
  "report_date": "string - ISO date (YYYY-MM-DD)",
  "form": "string - SEC form type",
  "primary_document": "string - Filename",
  "description": "string - Human-readable description"
}
```

#### Address
```json
{
  "street1": "string",
  "street2": "string",
  "city": "string",
  "stateOrCountry": "string",
  "zipCode": "string"
}
```

#### XBRLUnit
```json
{
  "end": "string - Period end date",
  "val": "number - Value",
  "accn": "string - Accession number",
  "fy": "integer - Fiscal year",
  "fp": "string - Fiscal period (Q1, Q2, Q3, FY)",
  "form": "string - Form type",
  "filed": "string - Filing date"
}
```

---

## Working Mechanism

### Data Access Method

**HTTP API Calls (RESTful)**

The SEC Edgar Search MCP Tool operates by making **HTTPS API calls** to SEC's official public data endpoints. It does NOT perform:

- ❌ Web scraping
- ❌ HTML parsing
- ❌ Database queries
- ❌ Screen scraping
- ❌ Unofficial data sources

**✅ Official SEC EDGAR Public APIs**

### API Endpoints Used

1. **Company Tickers**:
   - URL: `https://www.sec.gov/files/company_tickers.json`
   - Purpose: Company search and ticker-to-CIK conversion
   - Update Frequency: Daily

2. **Submissions API**:
   - URL: `https://data.sec.gov/submissions/CIK{cik}.json`
   - Purpose: Company info, filings list
   - Data: Metadata + recent filings

3. **XBRL Company Facts**:
   - URL: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
   - Purpose: Structured financial data
   - Data: All reported XBRL facts

### Process Flow

```
┌─────────────────┐
│  Tool Invocation│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Input Validation│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Ticker to CIK   │
│ (if ticker)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Normalize CIK   │
│ (pad to 10 dig) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Build API URL   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Set User-Agent  │
│ Header          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ HTTP GET Request│
│ via urllib      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse JSON      │
│ Response        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Filter/Process  │
│ Data            │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return Result   │
└─────────────────┘
```

### SEC API Requirements

**User-Agent Header**: SEC requires all API clients to identify themselves with a User-Agent header containing contact information:

```python
User-Agent: SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)
```

This is **mandatory** per SEC policy: https://www.sec.gov/os/accessing-edgar-data

---

## Authentication & Security

### Authentication Requirements

**No API Keys Required**

The SEC Edgar Search MCP Tool uses **public APIs** that do not require:
- ❌ API keys
- ❌ OAuth tokens
- ❌ Registration
- ❌ Paid subscriptions
- ❌ Username/password

**✅ Free and Open Access**

### Required Headers

**User-Agent Only**

```http
User-Agent: SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)
Accept: application/json
```

The User-Agent header with contact email is **mandatory** to comply with SEC fair access policy.

### Security Considerations

1. **Data Source**:
   - Official SEC EDGAR database
   - Public regulatory filings
   - No proprietary or restricted data

2. **Rate Limiting**:
   - SEC recommends max 10 requests/second
   - Implemented via tool rate limits
   - Respectful API usage required

3. **Data Privacy**:
   - All data is public information
   - No personal data processing
   - No PII storage

4. **Network Security**:
   - HTTPS/TLS encryption required
   - Certificate validation enabled
   - Secure urllib implementation

5. **Fair Access Policy**:
   - Contact email in User-Agent required
   - Rate limiting to prevent abuse
   - Terms of service compliance

---

## Limitations & Constraints

### SEC API Limitations

1. **Rate Limiting**:
   - Maximum 10 requests per second recommended
   - Excessive requests may result in IP blocking
   - No batch API available

2. **Data Availability**:
   - Only companies filing with SEC
   - Historical data varies by company
   - Some private companies not included
   - Foreign companies may have limited data

3. **Filing Delays**:
   - Real-time data not available
   - Filings processed with small delay
   - After-hours filings appear next day

### Tool-Specific Constraints

1. **Company Facts Tool**:
   - Returns very large responses (>5MB possible)
   - May cause memory issues for some companies
   - Consider using sec_get_financial_data for specific metrics

2. **Search Functionality**:
   - Basic substring matching only
   - No fuzzy search
   - Case-insensitive but exact matching
   - Limited to 100 results max

3. **Ticker to CIK Conversion**:
   - Relies on daily updated ticker file
   - Delisted companies may not resolve
   - Multiple classes of stock (A, B) may cause issues

4. **Date Filtering**:
   - Date filters work on filing date, not report date
   - Format must be YYYY-MM-DD
   - No partial date support

### Data Format Limitations

1. **XBRL Data**:
   - Complex nested structure
   - May require significant parsing
   - Unit conversions needed (USD, shares, etc.)
   - Different taxonomies for different facts

2. **Filing Documents**:
   - Only metadata returned (not full document text)
   - Document parsing requires separate tools
   - HTML and XBRL formats vary

3. **Missing Data**:
   - Not all companies report all metrics
   - Smaller companies may have limited data
   - Some fields may be null/empty

### Performance Constraints

1. **Large Company Data**:
   - Companies with long histories have more data
   - XBRL facts can be 5-10MB
   - Parsing time increases with data size

2. **Network Dependency**:
   - Requires stable internet connection
   - API downtime affects availability
   - No offline mode available

3. **Response Times**:
   - Typical response: 200-800ms
   - XBRL facts: 1-3 seconds (large data)
   - Network latency varies by location

---

## Sample Code & Usage

### Python Integration Example

```python
"""
Sample usage of SEC Edgar Search MCP Tools
"""
import json
from tools.impl.sec_edgar_tool_refactored import SEC_EDGAR_TOOLS

# Example 1: Search for a company
search_tool = SEC_EDGAR_TOOLS['sec_search_company']()
result = search_tool.execute({
    'search_term': 'Apple',
    'limit': 5
})
print(f"Found {result['result_count']} companies")
for company in result['companies']:
    print(f"  {company['name']} ({company['ticker']}) - CIK: {company['cik']}")

# Example 2: Get company information
info_tool = SEC_EDGAR_TOOLS['sec_get_company_info']()
result = info_tool.execute({'ticker': 'AAPL'})
print(f"\nCompany: {result['name']}")
print(f"CIK: {result['cik']}")
print(f"Industry: {result['sic_description']}")
print(f"Fiscal Year End: {result['fiscal_year_end']}")
if result.get('business_address'):
    addr = result['business_address']
    print(f"Address: {addr.get('city')}, {addr.get('stateOrCountry')}")

# Example 3: Get latest 10-K filings
filings_tool = SEC_EDGAR_TOOLS['sec_get_company_filings']()
result = filings_tool.execute({
    'ticker': 'TSLA',
    'filing_type': '10-K',
    'limit': 5
})
print(f"\n{result['name']} - 10-K Annual Reports:")
for filing in result['filings']:
    print(f"  {filing['filing_date']}: {filing['form']} - {filing['description']}")

# Example 4: Get available financial metrics
financial_tool = SEC_EDGAR_TOOLS['sec_get_financial_data']()
result = financial_tool.execute({'ticker': 'MSFT'})
print(f"\nAvailable metrics for {result['entity_name']}:")
for taxonomy, facts in result.get('available_facts', {}).items():
    print(f"  {taxonomy}: {len(facts)} facts")
    print(f"    Sample: {', '.join(facts[:5])}")

# Example 5: Get specific financial metric (Revenue)
result = financial_tool.execute({
    'ticker': 'GOOGL',
    'fact_type': 'Revenues'
})
print(f"\nRevenue data for {result['entity_name']}:")
for data_item in result.get('data', []):
    print(f"  Taxonomy: {data_item['taxonomy']}")
    print(f"  Label: {data_item['label']}")
    
    # Get USD values
    usd_values = data_item.get('units', {}).get('USD', [])
    recent_values = sorted(usd_values, 
                          key=lambda x: x.get('end', ''), 
                          reverse=True)[:5]
    
    print(f"  Recent values:")
    for val in recent_values:
        print(f"    {val['end']}: ${val['val']:,} ({val['form']})")

# Example 6: Get insider trading activity
insider_tool = SEC_EDGAR_TOOLS['sec_get_insider_trading']()
result = insider_tool.execute({
    'ticker': 'AAPL',
    'limit': 10
})
print(f"\nInsider Trading for {result['name']}:")
print(f"Total Form 4 filings: {result['filing_count']}")
for filing in result['filings'][:5]:
    print(f"  {filing['filing_date']}: Form {filing['form']}")

# Example 7: Get institutional holdings (13F)
# Using Berkshire Hathaway as example
holdings_tool = SEC_EDGAR_TOOLS['sec_get_mutual_fund_holdings']()
result = holdings_tool.execute({
    'cik': '0001067983',  # Berkshire Hathaway
    'limit': 4
})
print(f"\nInstitutional Holdings for {result['name']}:")
print(f"Recent 13F filings: {result['filing_count']}")
for filing in result['filings']:
    print(f"  {filing['report_date']}: Quarter ended")
    print(f"    Filed: {filing['filing_date']}")

# Example 8: Search and then get detailed info
search_tool = SEC_EDGAR_TOOLS['sec_search_company']()
search_result = search_tool.execute({'search_term': 'Tesla'})

if search_result['result_count'] > 0:
    cik = search_result['companies'][0]['cik']
    
    # Get company facts
    facts_tool = SEC_EDGAR_TOOLS['sec_get_company_facts']()
    facts_result = facts_tool.execute({'cik': cik})
    
    print(f"\nXBRL Facts for {facts_result['entity_name']}:")
    for taxonomy in facts_result.get('facts', {}).keys():
        fact_count = len(facts_result['facts'][taxonomy])
        print(f"  {taxonomy}: {fact_count} facts")

# Example 9: Get quarterly reports with date range
filings_tool = SEC_EDGAR_TOOLS['sec_get_company_filings']()
result = filings_tool.execute({
    'ticker': 'AMZN',
    'filing_type': '10-Q',
    'start_date': '2024-01-01',
    'end_date': '2024-12-31',
    'limit': 4
})
print(f"\n{result['name']} - 2024 Quarterly Reports:")
for filing in result['filings']:
    print(f"  Q{filing['report_date'][5:7]}: Filed {filing['filing_date']}")

# Example 10: Error handling
try:
    result = info_tool.execute({'ticker': 'INVALID_TICKER'})
except ValueError as e:
    print(f"\nError: {e}")
```

### MCP Protocol Integration

```python
"""
Example MCP server integration for SEC Edgar tools
"""
from typing import Dict, Any
import json

class SECEdgarMCPServer:
    def __init__(self):
        self.tools = {}
        
        # Register all SEC Edgar tools
        for tool_name, tool_class in SEC_EDGAR_TOOLS.items():
            self.tools[tool_name] = tool_class()
    
    def list_tools(self) -> list:
        """List available tools"""
        return [
            {
                'name': tool_name,
                'description': tool.config.get('description', ''),
                'input_schema': tool.get_input_schema(),
                'output_schema': tool.get_output_schema()
            }
            for tool_name, tool in self.tools.items()
        ]
    
    def execute_tool(self, tool_name: str, 
                     arguments: Dict[str, Any]) -> Dict:
        """Execute a specific tool"""
        if tool_name not in self.tools:
            return {
                'success': False,
                'error': f'Unknown tool: {tool_name}',
                'error_type': 'ToolNotFound'
            }
        
        tool = self.tools[tool_name]
        
        try:
            result = tool.execute(arguments)
            return {
                'success': True,
                'tool': tool_name,
                'result': result
            }
        except ValueError as e:
            return {
                'success': False,
                'tool': tool_name,
                'error': str(e),
                'error_type': 'ValueError'
            }
        except Exception as e:
            return {
                'success': False,
                'tool': tool_name,
                'error': str(e),
                'error_type': type(e).__name__
            }

# Usage
server = SECEdgarMCPServer()

# List tools
tools = server.list_tools()
print(f"Available tools: {len(tools)}")

# Execute search
response = server.execute_tool('sec_search_company', {
    'search_term': 'Microsoft',
    'limit': 5
})
if response['success']:
    companies = response['result']['companies']
    print(f"Found {len(companies)} companies")
else:
    print(f"Error: {response['error']}")

# Execute with error handling
response = server.execute_tool('sec_get_financial_data', {
    'ticker': 'AAPL',
    'fact_type': 'Revenues'
})
if response['success']:
    entity = response['result']['entity_name']
    data_count = len(response['result'].get('data', []))
    print(f"Retrieved {data_count} data items for {entity}")
```

### Command-Line Interface Example

```python
"""
CLI wrapper for SEC Edgar tools
"""
import sys
import json
import argparse
from tools.impl.sec_edgar_tool_refactored import SEC_EDGAR_TOOLS

def main():
    parser = argparse.ArgumentParser(
        description='SEC Edgar Search MCP Tool CLI'
    )
    parser.add_argument('tool', choices=SEC_EDGAR_TOOLS.keys(),
                       help='Tool to execute')
    parser.add_argument('--args', type=str, required=True,
                       help='JSON arguments')
    
    args = parser.parse_args()
    
    # Parse arguments
    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError:
        print("Error: Invalid JSON arguments", file=sys.stderr)
        sys.exit(1)
    
    # Initialize and execute tool
    tool = SEC_EDGAR_TOOLS[args.tool]()
    
    try:
        result = tool.execute(tool_args)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

**CLI Usage:**

```bash
# Search for companies
python sec_cli.py sec_search_company \
    --args '{"search_term": "Apple", "limit": 5}'

# Get company info
python sec_cli.py sec_get_company_info \
    --args '{"ticker": "TSLA"}'

# Get filings
python sec_cli.py sec_get_company_filings \
    --args '{"ticker": "MSFT", "filing_type": "10-K", "limit": 5}'

# Get financial data
python sec_cli.py sec_get_financial_data \
    --args '{"ticker": "GOOGL", "fact_type": "Revenues"}'

# Get insider trading
python sec_cli.py sec_get_insider_trading \
    --args '{"ticker": "AAPL", "limit": 20}'

# Get institutional holdings
python sec_cli.py sec_get_mutual_fund_holdings \
    --args '{"cik": "0001067983", "limit": 4}'
```

---

## Error Handling

### Error Response Format

```python
{
    'error': True,
    'error_type': 'ValueError',
    'message': 'Company not found: CIK 1234567890',
    'tool': 'sec_get_company_info',
    'timestamp': '2025-10-31T12:00:00Z'
}
```

### Common Error Types

| Error Type | Description | Common Causes | Resolution |
|------------|-------------|---------------|------------|
| ValueError | Invalid input or not found | Wrong CIK/ticker, company doesn't exist | Verify CIK/ticker using search tool |
| HTTPError 404 | Resource not found | Company has no filings, invalid CIK | Check if company files with SEC |
| HTTPError 429 | Rate limit exceeded | Too many requests | Slow down request rate |
| HTTPError 403 | Access forbidden | Missing User-Agent, IP blocked | Check User-Agent header |
| URLError | Network error | Connection failed, DNS error | Check internet connection |
| JSONDecodeError | Invalid response | API returned non-JSON | Check SEC API status |

### Error Handling Best Practices

```python
import urllib.error
import json
from tools.impl.sec_edgar_tool_refactored import SEC_EDGAR_TOOLS

def safe_execute_sec_tool(tool_name, arguments):
    """Execute SEC tool with comprehensive error handling"""
    try:
        tool = SEC_EDGAR_TOOLS[tool_name]()
        result = tool.execute(arguments)
        return {
            'success': True,
            'data': result
        }
        
    except ValueError as e:
        error_msg = str(e)
        
        if 'not found' in error_msg.lower():
            return {
                'success': False,
                'error_type': 'not_found',
                'message': error_msg,
                'suggestion': 'Use sec_search_company to find valid CIK/ticker'
            }
        elif 'ticker not found' in error_msg.lower():
            return {
                'success': False,
                'error_type': 'invalid_ticker',
                'message': error_msg,
                'suggestion': 'Check ticker symbol spelling'
            }
        else:
            return {
                'success': False,
                'error_type': 'validation_error',
                'message': error_msg,
                'suggestion': 'Check input parameters'
            }
    
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                'success': False,
                'error_type': 'not_found',
                'message': f'Resource not found (HTTP 404)',
                'suggestion': 'Company may not file with SEC or CIK is invalid'
            }
        elif e.code == 429:
            return {
                'success': False,
                'error_type': 'rate_limit',
                'message': 'Rate limit exceeded',
                'suggestion': 'Wait before retrying (max 10 req/sec)'
            }
        elif e.code == 403:
            return {
                'success': False,
                'error_type': 'forbidden',
                'message': 'Access forbidden',
                'suggestion': 'Check User-Agent header or IP may be blocked'
            }
        else:
            return {
                'success': False,
                'error_type': 'http_error',
                'message': f'HTTP error {e.code}',
                'suggestion': 'Check SEC EDGAR API status'
            }
    
    except urllib.error.URLError as e:
        return {
            'success': False,
            'error_type': 'network_error',
            'message': f'Network error: {str(e)}',
            'suggestion': 'Check internet connection'
        }
    
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error_type': 'parse_error',
            'message': 'Invalid JSON response from API',
            'suggestion': 'SEC API may be experiencing issues'
        }
    
    except Exception as e:
        return {
            'success': False,
            'error_type': 'unknown',
            'message': f'Unexpected error: {str(e)}',
            'suggestion': 'Check logs for details'
        }

# Usage
result = safe_execute_sec_tool('sec_get_company_info', {
    'ticker': 'AAPL'
})

if result['success']:
    print(f"Company: {result['data']['name']}")
else:
    print(f"Error: {result['message']}")
    print(f"Suggestion: {result['suggestion']}")
```

---

## Performance Considerations

### Optimization Strategies

1. **Caching**:
```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=100)
def cached_company_info(ticker):
    """Cache company info lookups"""
    tool = SEC_EDGAR_TOOLS['sec_get_company_info']()
    return tool.execute({'ticker': ticker})

# Usage
info = cached_company_info('AAPL')  # Fetches from API
info = cached_company_info('AAPL')  # Returns from cache
```

2. **Batch Processing**:
```python
def get_multiple_companies(tickers, delay=0.1):
    """Process multiple companies with rate limiting"""
    import time
    results = []
    
    tool = SEC_EDGAR_TOOLS['sec_get_company_info']()
    
    for ticker in tickers:
        try:
            result = tool.execute({'ticker': ticker})
            results.append({'ticker': ticker, 'data': result})
        except Exception as e:
            results.append({'ticker': ticker, 'error': str(e)})
        
        time.sleep(delay)  # Rate limiting
    
    return results
```

3. **Targeted Queries**:
```python
# Instead of getting all facts (large)
# facts_tool.execute({'ticker': 'AAPL'})  # 5MB+

# Get specific metric (small)
financial_tool.execute({
    'ticker': 'AAPL',
    'fact_type': 'Revenues'
})  # <100KB
```

### Performance Metrics

| Operation | Response Time | Data Size | Cache Benefit |
|-----------|---------------|-----------|---------------|
| Search Company | 200-400ms | <50KB | High (3600s) |
| Get Company Info | 300-600ms | 50-200KB | High (3600s) |
| Get Filings | 400-800ms | 100-500KB | Medium (1800s) |
| Get Company Facts | 1-3s | 1-10MB | High (3600s) |
| Get Financial Data | 500-1500ms | 50-500KB | High (3600s) |
| Get Insider Trading | 400-800ms | 100-300KB | Medium (1800s) |
| Get Mutual Fund Holdings | 400-800ms | 100-300KB | High (3600s) |

### Best Practices

1. **Rate Limiting**:
   - Maximum 10 requests/second
   - Use exponential backoff on errors
   - Implement request queuing

2. **Data Size Management**:
   - Use targeted queries when possible
   - Avoid company facts for large companies unless necessary
   - Filter filings by date range

3. **Caching Strategy**:
   - Cache company info (changes rarely)
   - Cache XBRL facts (updated quarterly)
   - Short cache for filings (updated frequently)

---

## Architecture Diagrams

### Tool Execution Flow

```
┌──────────────┐
│   Client     │
│  Request     │
└──────┬───────┘
       │
       │ {tool_name, cik/ticker, ...}
       │
       ▼
┌──────────────────────────────────┐
│   SEC Edgar Tool Registry        │
│                                  │
│  Lookup: SEC_EDGAR_TOOLS[name]   │
└──────┬───────────────────────────┘
       │
       │ Tool Instance
       │
       ▼
┌──────────────────────────────────┐
│    Tool Class Instance           │
│                                  │
│  ┌────────────────────────────┐  │
│  │  1. Validate Input         │  │
│  │  2. Convert Ticker to CIK  │  │
│  │  3. Normalize CIK          │  │
│  │  4. Build API URL          │  │
│  │  5. Set Headers            │  │
│  │  6. HTTP GET Request       │  │
│  │  7. Parse JSON Response    │  │
│  │  8. Filter/Transform Data  │  │
│  │  9. Return Result          │  │
│  └────────────────────────────┘  │
└──────┬───────────────────────────┘
       │
       │ Result Dictionary
       │
       ▼
┌──────────────┐
│   Client     │
│  Response    │
└──────────────┘
```

### Data Flow for Financial Query

```
User Query: "Get Apple's revenue"
      │
      ▼
┌─────────────────┐
│ Determine Tool  │
│ financial_data  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse Input     │
│ ticker: AAPL    │
│ fact: Revenues  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Ticker to CIK   │
│ AAPL → 0000320193│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Build URL       │
│ /companyfacts/  │
│ CIK0000320193   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ API Call        │
│ GET + User-Agent│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse JSON      │
│ Extract facts   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Filter for      │
│ "Revenues"      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return Data     │
│ with values &   │
│ timestamps      │
└─────────────────┘
```

### Class Hierarchy

```
           BaseMCPTool
                │
                │ (abstract inheritance)
                │
         SECEdgarBaseTool
         ┌──────┴───────┐
         │              │
    [Shared Methods]  [Configuration]
         │              │
         ├─ _normalize_cik()
         ├─ _ticker_to_cik()
         ├─ _get_cik_from_args()
         ├─ user_agent
         ├─ api_url
         ├─ filing_types
         │
         └─────┬────────────────────────────┐
               │                            │
    ┌──────────▼──────────┐    ┌───────────▼──────────┐
    │   Core Tools        │    │   Specialized Tools   │
    ├────────────────────┤    ├──────────────────────┤
    │ SearchCompanyTool  │    │ InsiderTradingTool   │
    │ GetCompanyInfoTool │    │ MutualFundHoldings   │
    │ GetFilingsTool     │    │                      │
    └────────────────────┘    └──────────────────────┘
    
    ┌──────────────────────┐
    │   Financial Tools    │
    ├─────────────────────┤
    │ GetCompanyFactsTool │
    │ GetFinancialData    │
    └─────────────────────┘
```

---

## Appendix A: SEC Filing Types Reference

### Common Filing Types

| Form | Name | Purpose | Frequency | Importance |
|------|------|---------|-----------|------------|
| 10-K | Annual Report | Comprehensive annual financial statements | Annual | ⭐⭐⭐⭐⭐ |
| 10-Q | Quarterly Report | Quarterly financial statements | Quarterly | ⭐⭐⭐⭐ |
| 8-K | Current Report | Material events | As needed | ⭐⭐⭐⭐ |
| 4 | Insider Trading | Changes in beneficial ownership | Within 2 days | ⭐⭐⭐ |
| 13F-HR | Institutional Holdings | Quarterly holdings >$100M AUM | Quarterly | ⭐⭐⭐⭐ |
| DEF 14A | Proxy Statement | Annual meeting materials | Annual | ⭐⭐⭐ |
| S-1 | IPO Registration | Initial public offering | Once | ⭐⭐⭐⭐⭐ |
| SC 13D | Activist Filing | Beneficial ownership >5% | As needed | ⭐⭐⭐⭐ |
| SC 13G | Passive Filing | Beneficial ownership >5% (passive) | Annual | ⭐⭐⭐ |
| 20-F | Foreign Annual | Foreign company annual report | Annual | ⭐⭐⭐⭐ |

---

## Appendix B: XBRL Taxonomy Reference

### US-GAAP Common Facts

| Fact Name | Description | Unit | Category |
|-----------|-------------|------|----------|
| Assets | Total assets | USD | Balance Sheet |
| Liabilities | Total liabilities | USD | Balance Sheet |
| StockholdersEquity | Shareholders' equity | USD | Balance Sheet |
| Revenues | Revenue/Sales | USD | Income Statement |
| NetIncomeLoss | Net income | USD | Income Statement |
| EarningsPerShare | Earnings per share | USD/shares | Income Statement |
| Cash | Cash and equivalents | USD | Balance Sheet |
| CurrentAssets | Current assets | USD | Balance Sheet |
| CurrentLiabilities | Current liabilities | USD | Balance Sheet |
| LongTermDebt | Long-term debt | USD | Balance Sheet |
| OperatingIncome | Operating income | USD | Income Statement |
| GrossProfit | Gross profit | USD | Income Statement |
| CostOfRevenue | Cost of goods sold | USD | Income Statement |

---

## Appendix C: Notable CIK Numbers

### Major Companies

| Company | Ticker | CIK | Industry |
|---------|--------|-----|----------|
| Apple Inc. | AAPL | 0000320193 | Technology |
| Microsoft Corp. | MSFT | 0000789019 | Technology |
| Amazon.com Inc. | AMZN | 0001018724 | E-commerce |
| Alphabet Inc. (Google) | GOOGL | 0001652044 | Technology |
| Tesla Inc. | TSLA | 0001318605 | Automotive |
| Meta Platforms (Facebook) | META | 0001326801 | Technology |
| Berkshire Hathaway | BRK.B | 0001067983 | Conglomerate |
| JPMorgan Chase | JPM | 0000019617 | Banking |
| Johnson & Johnson | JNJ | 0000200406 | Healthcare |
| Walmart Inc. | WMT | 0000104169 | Retail |

### Major Institutional Investors

| Institution | CIK | AUM (Approx) |
|-------------|-----|--------------|
| Berkshire Hathaway | 0001067983 | $300B+ |
| Vanguard Group | 0001102694 | $7T+ |
| BlackRock | 0001364742 | $9T+ |
| State Street | 0001350694 | $3T+ |
| Fidelity | 0000315066 | $4T+ |

---

## Appendix D: Quick Reference

### Command Cheat Sheet

```bash
# Search company
{"search_term": "Apple", "limit": 10}

# Get company info
{"ticker": "AAPL"}
{"cik": "0000320193"}

# Get filings
{"ticker": "TSLA", "filing_type": "10-K", "limit": 5}
{"ticker": "MSFT", "start_date": "2024-01-01", "end_date": "2024-12-31"}

# Get all facts (WARNING: Large)
{"ticker": "GOOGL"}

# Get specific financial data
{"ticker": "AMZN", "fact_type": "Revenues"}
{"ticker": "AAPL", "fact_type": "NetIncomeLoss"}

# Get insider trading
{"ticker": "TSLA", "limit": 20}

# Get institutional holdings
{"cik": "0001067983", "limit": 4}
```

---

## Support & Contact

**Copyright © 2025-2030 Ashutosh Sinha**  
**Email:** ajsinha@gmail.com  
**All Rights Reserved**

For issues, questions, or contributions, please contact the author.

### Additional Resources

- **SEC EDGAR API Documentation**: https://www.sec.gov/edgar/sec-api-documentation
- **SEC Fair Access Policy**: https://www.sec.gov/os/accessing-edgar-data
- **XBRL Taxonomy**: https://xbrl.sec.gov/
- **SEC Forms List**: https://www.sec.gov/forms

---

**Document Version:** 1.0.0  
**Last Updated:** October 31, 2025  
**Status:** Production Ready

---

## Page Glossary

**Key terms referenced in this document:**

- **SEC (Securities and Exchange Commission)**: The U.S. federal agency responsible for enforcing securities laws and regulating the securities industry.

- **EDGAR (Electronic Data Gathering, Analysis, and Retrieval)**: The SEC's electronic system for companies to submit required filings. SAJHA tools provide comprehensive EDGAR access.

- **10-K**: An annual report filed by public companies containing comprehensive business and financial information.

- **10-Q**: A quarterly report filed by public companies with unaudited financial statements.

- **8-K**: A current report filed to announce major events that shareholders should know about.

- **CIK (Central Index Key)**: A unique identifier assigned by the SEC to companies and individuals filing documents.

- **Full-Text Search**: Searching through all text in documents. SAJHA's EDGAR tools support full-text search across SEC filings.

- **Insider Trading**: Buying or selling securities based on material non-public information. SEC Form 4 filings track insider transactions.

*For complete definitions, see the [Glossary](../architecture/Glossary.md).*
