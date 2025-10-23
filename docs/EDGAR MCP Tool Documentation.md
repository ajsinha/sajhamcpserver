# EDGAR MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The EDGAR MCP Tool provides comprehensive access to the SEC EDGAR database for retrieving company filings, financial data, and regulatory information.

## Configuration
- **Environment Variables:**
  - `SEC_USER_AGENT`: Required user agent string for SEC API (format: "CompanyName/1.0 (contact@example.com)")

## Available Methods

### 1. get_company_info
Retrieves comprehensive company information from EDGAR.

**Parameters:**
- `cik` (optional): Company CIK number
- `ticker` (optional): Stock ticker symbol
*Note: Either CIK or ticker is required*

**Returns:**
- Company name, tickers, exchanges
- SIC code and description
- Address information
- Filing statistics
- Former names
- Entity type

### 2. get_company_filings
Retrieves company filings with advanced filtering options.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `filing_type` (optional): Specific form type (e.g., '10-K', '10-Q', '8-K')
- `date_from` (optional): Start date filter
- `date_to` (optional): End date filter
- `limit` (default: 20): Maximum number of results

**Returns:**
- List of filings with accession numbers
- Filing dates and report dates
- Document URLs
- Filing type statistics

### 3. get_filing_documents
Gets detailed documents and exhibits from a specific filing.

**Parameters:**
- `cik`: Company CIK
- `accession_number`: Filing accession number
- `include_exhibits` (default: true): Include exhibit documents

**Returns:**
- Primary documents
- Exhibits
- Graphics files
- XBRL documents
- Document URLs and metadata

### 4. get_insider_transactions
Retrieves insider trading transactions (Forms 3, 4, 5).

**Parameters:**
- `cik` or `ticker`: Company identifier
- `insider_cik` (optional): Specific insider's CIK
- `transaction_type` (optional): Type of transaction
- `date_from` (optional): Start date
- `date_to` (optional): End date
- `limit` (default: 50): Maximum results

**Returns:**
- Form 4 transactions
- Form 3 initial holdings
- Form 5 annual statements
- Transaction details

### 5. get_institutional_holdings
Gets institutional holdings from 13F filings.

**Parameters:**
- `cik`: Institution CIK
- `institution_name` (optional): Institution name
- `quarter` (optional): Specific quarter (format: "2024Q1")
- `cusip` (optional): Filter by specific CUSIP

**Returns:**
- Recent 13F-HR filings
- Holdings information
- Filing counts

### 6. get_beneficial_ownership
Retrieves beneficial ownership from Schedule 13D/G filings.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `owner_name` (optional): Specific owner name
- `ownership_threshold` (default: 5.0): Ownership percentage threshold

**Returns:**
- Schedule 13D filings (active ownership)
- Schedule 13G filings (passive ownership)
- Ownership changes

### 7. get_proxy_statements
Gets proxy statements and executive compensation data.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `year` (default: current year): Fiscal year
- `include_compensation` (default: true): Include compensation details

**Returns:**
- DEF 14A filings
- Executive compensation structure
- Proxy voting items

### 8. get_company_financials
Retrieves structured financial data from XBRL filings.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `statement_type` (default: 'all'): 'balance', 'income', 'cash_flow', 'comprehensive_income', or 'all'
- `period` (default: 'all'): 'annual', 'quarterly', or 'all'
- `fiscal_year` (optional): Specific fiscal year
- `fiscal_quarter` (optional): Specific quarter

**Returns:**
- Financial metrics by statement type
- Historical values with dates
- Units and forms

### 9. get_fund_data
Gets mutual fund and ETF data.

**Parameters:**
- `cik` or `ticker`: Fund identifier
- `series_id` (optional): Specific series ID
- `include_holdings` (default: true): Include holdings data

**Returns:**
- N-Q and N-CSR filings
- Proxy voting records (N-PX)
- Prospectus updates

### 10. search_filings
Full-text search across EDGAR filings.

**Parameters:**
- `query`: Search query text
- `filing_type` (optional): Filter by form types
- `cik` (optional): Filter by companies
- `date_from` (optional): Start date
- `date_to` (optional): End date
- `sic_code` (optional): Filter by SIC code
- `limit` (default: 50): Maximum results

### 11. get_recent_filings
Gets most recent filings with real-time updates.

**Parameters:**
- `filing_type` (optional): Filter by form types
- `minutes_ago` (default: 60): Time window in minutes
- `limit` (default: 100): Maximum results

### 12. get_ipo_registrations
Retrieves IPO registration statements.

**Parameters:**
- `status` (default: 'all'): Registration status
- `date_from` (optional): Start date
- `date_to` (optional): End date
- `industry` (optional): Industry filter

**Returns:**
- S-1, S-11, F-1, F-3 filings
- Registration status

### 13. get_merger_filings
Gets merger and acquisition related filings.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `transaction_type` (default: 'all'): 'merger', 'acquisition', or 'tender_offer'
- `date_from` (optional): Start date

**Returns:**
- DEFM14A merger proxies
- S-4 registration statements
- 8-K items related to M&A
- Tender offer documents

### 14. get_comment_letters
Retrieves SEC comment letters and company responses.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `date_from` (optional): Start date
- `include_responses` (default: true): Include company responses

**Returns:**
- CORRESP filings
- UPLOAD filings
- Comment letter exchanges

### 15. get_xbrl_facts
Gets structured XBRL company facts.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `concept` (optional): Specific XBRL concept
- `taxonomy` (default: 'us-gaap'): Taxonomy to use

**Returns:**
- XBRL facts by taxonomy
- Concept definitions
- Historical values

### 16. get_peer_comparison
Compares company metrics with industry peers.

**Parameters:**
- `cik` or `ticker`: Primary company
- `peer_ciks` (optional): List of peer CIKs
- `use_sic_peers` (default: false): Auto-select SIC peers
- `metrics`: List of metrics to compare

### 17. get_cik_lookup
Looks up CIK by various identifiers.

**Parameters:**
- `ticker` (optional): Stock ticker
- `company_name` (optional): Company name
- `cusip` (optional): CUSIP identifier
- `lei` (optional): LEI identifier

**Returns:**
- Matching CIKs
- Company names
- Match confidence

### 18. get_company_tickers
Gets comprehensive list of company tickers.

**Parameters:**
- `exchange` (optional): Filter by exchange
- `sic_code` (optional): Filter by SIC code
- `state` (optional): Filter by state
- `country` (optional): Filter by country
- `status` (default: 'active'): Company status

### 19. get_historical_data
Retrieves historical filing data for trend analysis.

**Parameters:**
- `cik` or `ticker`: Company identifier
- `metric`: Specific metric to track
- `years` (default: 5): Number of years
- `frequency` (default: 'annual'): 'annual' or 'quarterly'

### 20. validate_filing
Validates EDGAR filing format and compliance.

**Parameters:**
- `filing_content`: Filing document content
- `filing_type`: Type of filing
- `check_xbrl` (default: true): Validate XBRL structure

## Filing Type Categories

The tool organizes filings into categories:

- **Annual**: 10-K, 10-K/A, 20-F, 20-F/A, 40-F, 40-F/A
- **Quarterly**: 10-Q, 10-Q/A
- **Current**: 8-K, 8-K/A, 6-K
- **Proxy**: DEF 14A, DEFM14A, DEF 14C, PRE 14A
- **Registration**: S-1, S-3, S-4, S-8, S-11, F-1, F-3, F-4
- **Insider**: 3, 4, 5, 144
- **Institutional**: 13F-HR, 13F-HR/A, 13D, 13G, 13D/A, 13G/A
- **Fund**: N-Q, N-CSR, N-CSR/A, N-PX, 485BPOS, 485APOS

## Rate Limiting
- SEC limits requests to 10 per second
- Tool automatically manages rate limiting
- Includes caching for frequently accessed data

## Error Handling
- Automatic CIK normalization (10-digit format)
- Ticker to CIK conversion
- Graceful handling of missing data
- Network error recovery

## Example Usage
```python
# Get company information
result = edgar_tool.handle_tool_call('get_company_info', {
    'ticker': 'AAPL'
})

# Get recent 10-K filings
result = edgar_tool.handle_tool_call('get_company_filings', {
    'ticker': 'MSFT',
    'filing_type': '10-K',
    'limit': 5
})

# Get financial data
result = edgar_tool.handle_tool_call('get_company_financials', {
    'ticker': 'GOOGL',
    'statement_type': 'income',
    'period': 'annual'
})
```


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.