# Migration Guide: Old IR Scraper → Enhanced IR Scraper

## Overview

This guide helps you migrate from the old company-specific scraper system to the new configuration-driven, scalable system.

## Key Changes

### Architecture Changes

| Component | Old | New |
|-----------|-----|-----|
| HTTP Client | `urllib.request` | `EnhancedHTTPClient` |
| Base Class | `BaseIRWebScraper` | `EnhancedBaseIRScraper` |
| Company Scrapers | Individual classes | `GenericIRScraper` |
| Factory | `IRWebScraperFactory` | `EnhancedIRScraperFactory` |
| Configuration | Hard-coded | `sp500_companies.json` |
| Fallback | None | SEC EDGAR integration |

## Step-by-Step Migration

### Step 1: Update Imports

**Old:**
```python
from ir.base_ir_webscraper import BaseIRWebScraper
from ir.ir_webscraper_factory import IRWebScraperFactory
from ir.company_ir_scrapers import TeslaIRScraper, MicrosoftIRScraper
```

**New:**
```python
from ir.enhanced_base_scraper import EnhancedBaseIRScraper
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase
from ir.generic_ir_scraper import GenericIRScraper
```

### Step 2: Update Factory Initialization

**Old:**
```python
# Factory auto-registers 7 hardcoded companies
factory = IRWebScraperFactory()
```

**New:**
```python
# Load from configuration file
company_db = CompanyDatabase('sp500_companies.json')
factory = EnhancedIRScraperFactory(
    company_db=company_db,
    use_sec_fallback=True  # Enable SEC EDGAR fallback
)
```

### Step 3: Update Scraper Usage

**Old:**
```python
# Get scraper (only works for 7 companies)
scraper = factory.get_scraper('TSLA')

# Scrape documents
docs = scraper.scrape_documents(
    document_type='annual_report',
    year=2024
)
```

**New:**
```python
# Get scraper (works for 500+ companies)
scraper = factory.get_scraper('TSLA')

# Same API! But now with SEC fallback
docs = scraper.scrape_documents(
    document_type='annual_report',
    year=2024
)

# Documents may come from IR page or SEC EDGAR
# Check source with: doc['source']
```

### Step 4: Update Tool Integration

**Old:**
```python
from tools.impl.investor_relations_tool import InvestorRelationsTool

tool = InvestorRelationsTool(config={
    'name': 'investor_relations',
    'enabled': True
})

result = tool.execute({
    'action': 'get_latest_earnings',
    'ticker': 'MSFT'
})
```

**New:**
```python
from enhanced_investor_relations_tool import EnhancedInvestorRelationsTool

tool = EnhancedInvestorRelationsTool(config={
    'company_config_file': 'sp500_companies.json',
    'use_sec_fallback': True
})

result = tool.execute({
    'action': 'get_latest_earnings',
    'ticker': 'MSFT'
})

# New actions available:
# - 'get_quarterly_reports'
# - 'search_documents'
# - 'get_company_info'
# - 'add_company'
```

## Behavioral Changes

### 1. Rate Limiting (NEW)

The new system automatically rate limits requests:

```python
# Old: No rate limiting → may trigger bot detection
for ticker in tickers:
    scraper = factory.get_scraper(ticker)
    docs = scraper.scrape_documents()  # Rapid fire requests

# New: Automatic rate limiting (2-5 seconds between requests)
for ticker in tickers:
    scraper = factory.get_scraper(ticker)
    docs = scraper.scrape_documents()  # Automatically delayed
```

### 2. Retry Logic (NEW)

The new system automatically retries failed requests:

```python
# Old: Single attempt, fails on 403
try:
    content = scraper.fetch_page(url)
except:
    # Failed permanently

# New: Automatic retry with exponential backoff
try:
    content = scraper.fetch_page(url)
    # Retries 3 times with increasing delays on 403/429/5xx errors
except:
    # Failed after all retries
```

### 3. SEC Fallback (NEW)

When direct scraping fails, the system tries SEC EDGAR:

```python
# Old: Returns empty list on failure
docs = scraper.scrape_documents()  # Returns []

# New: Tries SEC EDGAR if IR page scraping fails
docs = scraper.scrape_documents()  # Returns SEC filings as fallback
# Check where documents came from:
for doc in docs:
    print(doc.get('source'))  # 'IR Page' or 'SEC EDGAR'
```

### 4. Enhanced Document Metadata (NEW)

Documents now include more metadata:

```python
# Old document format:
{
    'title': 'Q4 2024 Earnings',
    'url': 'https://...',
    'type': 'earnings_presentation',
    'year': 2024,
    'is_pdf': True,
    'ticker': 'TSLA'
}

# New document format (additional fields):
{
    'title': 'Q4 2024 Earnings',
    'url': 'https://...',
    'type': 'earnings_presentation',
    'year': 2024,
    'quarter': 'Q4',  # NEW
    'date': '2024-10-20',  # NEW
    'context': '...',  # NEW: surrounding text
    'source': 'IR Page',  # NEW: 'IR Page' or 'SEC EDGAR'
    'form_type': '8-K',  # NEW: for SEC filings
    'is_pdf': True,
    'ticker': 'TSLA'
}
```

## Adding Custom Companies

### Old System

Required writing a new scraper class:

```python
# Had to create new file: my_company_scraper.py
class MyCompanyIRScraper(BaseIRWebScraper):
    def __init__(self):
        super().__init__('MYCO')
        self.ir_url = 'https://...'
    
    def get_ir_page_url(self):
        return self.ir_url
    
    def scrape_documents(self, document_type=None, year=None):
        # Custom scraping logic...
        pass

# Then register in factory
factory.register_scraper('MYCO', MyCompanyIRScraper)
```

### New System

Just add to JSON configuration:

```json
{
  "ticker": "MYCO",
  "name": "My Company Inc.",
  "cik": "0001234567",
  "ir_url": "https://investor.mycompany.com",
  "ir_platform": "generic",
  "document_urls": {}
}
```

Or programmatically:

```python
factory.add_company(
    ticker='MYCO',
    name='My Company Inc.',
    ir_url='https://investor.mycompany.com',
    cik='0001234567'
)
```

## Handling Breaking Changes

### No Longer Available: Company-Specific Scrapers

**Old:**
```python
from ir.company_ir_scrapers import TeslaIRScraper

# Direct instantiation
scraper = TeslaIRScraper()
```

**Migration:**
```python
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase

# Use factory
company_db = CompanyDatabase('sp500_companies.json')
factory = EnhancedIRScraperFactory(company_db=company_db)
scraper = factory.get_scraper('TSLA')
```

### Changed: fetch_page() Method

**Old:**
```python
# In BaseIRWebScraper
content = self.fetch_page(url, timeout=15)
```

**New:**
```python
# Uses EnhancedHTTPClient internally
content = self.fetch_page(url)  # timeout configured in http_client
```

### Changed: Document Type Patterns

The new system has enhanced patterns:

```python
# Old patterns (basic)
'annual_report': [
    r'annual\s+report',
    r'10-k',
    r'form\s+10-k'
]

# New patterns (comprehensive)
'annual_report': [
    r'annual\s+report',
    r'10-k',
    r'form\s+10-k',
    r'annual\s+filing',
    r'form\s+20-f',  # NEW: for foreign companies
    r'20-f',  # NEW
    r'year\s+end\s+report'  # NEW
]
```

## Testing Your Migration

### 1. Basic Functionality Test

```python
# Test basic scraping
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase

company_db = CompanyDatabase('sp500_companies.json')
factory = EnhancedIRScraperFactory(company_db=company_db)

# Test a few companies
test_tickers = ['AAPL', 'MSFT', 'GOOGL']

for ticker in test_tickers:
    print(f"\nTesting {ticker}...")
    scraper = factory.get_scraper(ticker)
    
    # Test IR page
    ir_url = scraper.get_ir_page_url()
    print(f"  IR URL: {ir_url}")
    
    # Test document scraping
    docs = scraper.scrape_documents(limit=5)
    print(f"  Found {len(docs)} documents")
    
    # Check sources
    sources = set(doc.get('source', 'IR Page') for doc in docs)
    print(f"  Sources: {sources}")
```

### 2. Compare Results

```python
# Compare old vs new system results
from ir_webscraper_factory import IRWebScraperFactory as OldFactory
from enhanced_factory import EnhancedIRScraperFactory as NewFactory

old_factory = OldFactory()
new_factory = NewFactory()

ticker = 'TSLA'

# Old system
old_scraper = old_factory.get_scraper(ticker)
old_docs = old_scraper.scrape_documents()

# New system
new_scraper = new_factory.get_scraper(ticker)
new_docs = new_scraper.scrape_documents()

print(f"Old system: {len(old_docs)} documents")
print(f"New system: {len(new_docs)} documents")
```

## Rollback Strategy

If you need to rollback:

1. Keep old files as backup
2. Use git tags/branches for version control
3. Test thoroughly before full deployment

```bash
# Tag current version
git tag -a v1.0-old -m "Old IR scraper system"

# Create new branch for migration
git checkout -b enhanced-ir-scraper

# After testing, merge or rollback
git checkout main
git merge enhanced-ir-scraper  # or revert to old tag
```

## Performance Considerations

### Old System
- Fast (no rate limiting)
- High failure rate (403 errors)
- No retry logic
- Limited to 7 companies

### New System
- Slower (2-5 second delays between requests)
- Low failure rate (automatic retries)
- More reliable results
- Supports 500+ companies

**Recommendation:** For bulk operations, process companies overnight or in batches to account for rate limiting.

## Common Migration Issues

### Issue 1: "Company not found"

```python
# Solution: Add to configuration
factory.add_company(
    ticker='TICKER',
    name='Company Name',
    ir_url='https://...',
    cik='...'  # Optional but recommended for SEC fallback
)
```

### Issue 2: "Still getting 403 errors"

```python
# Solution: Increase delays
from ir.http_client import EnhancedHTTPClient

# Configure with longer delays
client = EnhancedHTTPClient(
    min_delay=5.0,
    max_delay=10.0,
    max_retries=5
)
```

### Issue 3: "No documents found"

```python
# Solution: Check if SEC fallback is working
scraper = factory.get_scraper('TICKER')

# Verify SEC fallback is available
if scraper.sec_client and scraper.company_config.cik:
    print("SEC fallback available")
    # Try SEC directly
    filings = scraper.sec_client.get_recent_filings(
        scraper.company_config.cik
    )
else:
    print("SEC fallback not available - add CIK to configuration")
```

## Support

If you encounter issues during migration:

1. Check logs for specific error messages
2. Verify company configurations in JSON file
3. Test with SEC EDGAR fallback
4. Adjust rate limiting if getting 403 errors
5. Review the troubleshooting section in README.md

## Next Steps

After successful migration:

1. Add more companies to `sp500_companies.json`
2. Monitor logs for any failures
3. Tune rate limiting based on your needs
4. Set up caching to avoid redundant requests
5. Consider implementing automated tests
