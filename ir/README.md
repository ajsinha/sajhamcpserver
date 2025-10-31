# Enhanced Investor Relations Web Scraper

## 🎯 Key Improvements

### 1. Bot Detection Avoidance

**Previous Issues:**
- Simple urllib with basic user-agent
- No rate limiting
- No retry logic
- Getting 403 errors frequently

**New Solutions:**
- **Realistic Browser Headers**: Rotates through multiple realistic Chrome/Firefox/Safari user agents
- **Rate Limiting**: Configurable delays between requests (2-5 seconds default) with domain-specific tracking
- **Retry Logic**: Exponential backoff for 403, 429, and 5xx errors
- **Session Management**: Maintains cookies and referer headers like a real browser
- **Randomized Delays**: Adds randomness to delays to avoid patterns

### 2. S&P 500 Scalability

**Previous Issues:**
- Separate scraper class for each company
- Only 7 companies supported
- Not scalable to 500+ companies

**New Solutions:**
- **Generic Scraper**: Single scraper that works for all companies
- **Configuration-Driven**: JSON file with company configurations
- **SEC EDGAR Fallback**: Automatically falls back to SEC filings when direct scraping fails
- **Pattern Detection**: Automatically detects common IR platform types (Q4, Workiva, etc.)
- **Easy to Extend**: Add new companies by editing JSON file, no code changes needed

## 📦 New Architecture

```
http_client.py              # Enhanced HTTP client with bot avoidance
company_database.py         # Company configuration database
sec_edgar.py               # SEC EDGAR integration for fallback
enhanced_base_scraper.py   # Improved base scraper with pattern detection
generic_ir_scraper.py      # Generic scraper for all companies
enhanced_factory.py        # Factory with generic scraper support
enhanced_investor_relations_tool.py  # Updated MCP tool
sp500_companies.json       # S&P 500 company configurations
```

## 🚀 Quick Start

### 1. Install Dependencies

```python
# No external dependencies required - uses only Python stdlib
# Recommended: Python 3.8+
```

### 2. Load Company Database

```python
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase

# Initialize with S&P 500 companies
company_db = CompanyDatabase('sp500_companies.json')
factory = EnhancedIRScraperFactory(company_db=company_db)

# Get scraper for any supported company
scraper = factory.get_scraper('AAPL')
```

### 3. Scrape Documents

```python
# Get annual reports
annual_reports = scraper.scrape_documents(
    document_type='annual_report',
    year=2024
)

# Get latest earnings
earnings = scraper.get_latest_earnings()

# Get all resources
all_resources = scraper.get_all_resources()
```

## 🔧 Configuration

### Adding New Companies

Add to `sp500_companies.json`:

```json
{
  "ticker": "NEWCO",
  "name": "New Company Inc.",
  "cik": "0001234567",
  "ir_url": "https://investor.newcompany.com",
  "ir_platform": "generic",
  "document_urls": {
    "earnings": "https://investor.newcompany.com/earnings",
    "sec_filings": "https://investor.newcompany.com/sec-filings"
  }
}
```

Or add programmatically:

```python
factory.add_company(
    ticker='NEWCO',
    name='New Company Inc.',
    ir_url='https://investor.newcompany.com',
    cik='0001234567'
)

# Save to file
factory.save_company_database('sp500_companies.json')
```

### Adjusting Bot Detection Settings

```python
from ir.http_client import EnhancedHTTPClient

# Custom rate limiting
http_client = EnhancedHTTPClient(
    min_delay=1.0,      # Minimum 1 second between requests
    max_delay=3.0,      # Maximum 3 seconds between requests
    max_retries=5,      # Retry up to 5 times
    timeout=45          # 45 second timeout
)
```

## 📊 Features Comparison

| Feature | Old System | New System |
|---------|-----------|------------|
| Companies Supported | 7 | 500+ (configurable) |
| Bot Detection | ❌ Basic | ✅ Advanced |
| Rate Limiting | ❌ None | ✅ Configurable |
| Retry Logic | ❌ None | ✅ Exponential backoff |
| SEC Fallback | ❌ None | ✅ Automatic |
| Session Management | ❌ None | ✅ Cookie + headers |
| User Agent | 🟡 Static | ✅ Rotating realistic |
| Error Handling | 🟡 Basic | ✅ Comprehensive |
| Extensibility | ❌ Requires coding | ✅ JSON config |

## 🎓 Usage Examples

### Example 1: Get Tesla's Latest 10-K

```python
factory = EnhancedIRScraperFactory()
scraper = factory.get_scraper('TSLA')

# Try IR page first, fall back to SEC if needed
documents = scraper.scrape_documents(
    document_type='annual_report',
    year=2024
)

print(f"Found {len(documents)} documents")
for doc in documents:
    print(f"  {doc['title']}: {doc['url']}")
```

### Example 2: Search Earnings Calls with Keywords

```python
scraper = factory.get_scraper('MSFT')

# Get all earnings presentations
earnings = scraper.scrape_documents(
    document_type='earnings_presentation'
)

# Filter by keywords
keywords = ['guidance', 'cloud', 'AI']
matching = [
    doc for doc in earnings
    if any(kw.lower() in doc['title'].lower() for kw in keywords)
]
```

### Example 3: Bulk Download Annual Reports

```python
import requests

tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN']

for ticker in tickers:
    scraper = factory.get_scraper(ticker)
    reports = scraper.get_annual_reports(limit=3)
    
    for report in reports['annual_reports']:
        if report['is_pdf']:
            print(f"Downloading {ticker} {report['title']}")
            # Download logic here
```

### Example 4: Using SEC EDGAR Only

```python
from sec_edgar import SECEdgarClient

sec_client = SECEdgarClient(user_email='your@email.com')

# Get Apple's recent 10-K filings
filings = sec_client.get_annual_reports(cik='0000320193', limit=5)

for filing in filings:
    print(f"{filing['form']}: {filing['filing_date']}")
    print(f"  URL: {filing['document_url']}")
```

## 🛡️ Bot Detection Best Practices

1. **Respect Rate Limits**: Use default 2-5 second delays
2. **Don't Parallelize**: Scrape sequentially to avoid detection
3. **Handle 403s Gracefully**: The system will retry with longer delays
4. **Use SEC Fallback**: When scraping fails, SEC EDGAR is reliable
5. **Monitor Logs**: Check for patterns of failures

## 🔍 Troubleshooting

### Getting 403 Errors

```python
# Increase delays
from ir.http_client import EnhancedHTTPClient

client = EnhancedHTTPClient(
    min_delay=5.0,    # Slower requests
    max_delay=10.0,
    max_retries=5     # More retries
)
```

### Company Not Found

```python
# Check if supported
if factory.is_supported('TICKER'):
    scraper = factory.get_scraper('TICKER')
else:
    # Add the company
    factory.add_company(
        ticker='TICKER',
        name='Company Name',
        ir_url='https://...',
        cik='0001234567'  # From SEC.gov
    )
```

### No Documents Found

```python
# Use SEC fallback explicitly
scraper = factory.get_scraper('TICKER')

if scraper.sec_client:
    # Get from SEC directly
    filings = scraper.sec_client.get_recent_filings(
        scraper.company_config.cik,
        limit=20
    )
```

## 📈 Performance Tips

1. **Cache Results**: Store scraped documents to avoid re-scraping
2. **Batch Requests**: Group similar requests together
3. **Use Specific Document Types**: Don't scrape everything when you need one type
4. **Limit Results**: Use the `limit` parameter to get only what you need

## 🔐 Security & Ethics

- **Respect robots.txt**: The system checks robots.txt (when enabled)
- **User-Agent Required**: Always include your email in SEC requests
- **Rate Limiting**: Don't overwhelm servers
- **Terms of Service**: Review each company's IR page terms before scraping

## 📝 Migration from Old System

### Old Code
```python
from ir_webscraper_factory import IRWebScraperFactory

factory = IRWebScraperFactory()
scraper = factory.get_scraper('TSLA')
docs = scraper.scrape_documents()
```

### New Code
```python
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase

# Load configurations
company_db = CompanyDatabase('sp500_companies.json')
factory = EnhancedIRScraperFactory(company_db=company_db)

# Same interface!
scraper = factory.get_scraper('TSLA')
docs = scraper.scrape_documents()
```

## 🤝 Contributing

To add support for more companies:

1. Find the company's IR page URL
2. Find their SEC CIK number at https://www.sec.gov/cgi-bin/browse-edgar
3. Add entry to `sp500_companies.json`
4. Test with the generic scraper

## 📄 License

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

## 🆘 Support

For issues or questions:
- Check the troubleshooting section
- Review logs for specific error messages
- Verify company IR pages are accessible
- Try SEC EDGAR fallback

## 🎯 Future Enhancements

- [ ] Support for international exchanges
- [ ] PDF text extraction
- [ ] Automated data extraction from filings
- [ ] Company news and press releases
- [ ] Conference call transcripts
- [ ] Real-time earnings alerts
- [ ] Enhanced caching layer
- [ ] Proxy support for additional anonymity
