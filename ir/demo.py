"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Demo Script for Enhanced IR Scraper System
"""

import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def demo_basic_usage():
    """Demonstrate basic usage of the enhanced system"""
    print("\n" + "="*60)
    print("DEMO 1: Basic Usage")
    print("="*60)
    
    from ir.enhanced_factory import EnhancedIRScraperFactory
    from ir.company_database import CompanyDatabase
    
    # Initialize
    print("\n1. Loading company database...")
    company_db = CompanyDatabase('../config/ir/sp500_companies.json')
    factory = EnhancedIRScraperFactory(company_db=company_db)
    
    print(f"   Loaded {len(factory.get_supported_tickers())} companies")
    
    # Get a scraper
    print("\n2. Getting scraper for Tesla (TSLA)...")
    scraper = factory.get_scraper('TSLA')
    print(f"   IR Page: {scraper.get_ir_page_url()}")
    
    # Scrape documents
    print("\n3. Scraping annual reports...")
    try:
        docs = scraper.scrape_documents(
            document_type='annual_report',
            year=2024
        )
        
        print(f"   Found {len(docs)} documents")
        for i, doc in enumerate(docs[:3], 1):
            print(f"   {i}. {doc['title']}")
            print(f"      URL: {doc['url']}")
            print(f"      Source: {doc.get('source', 'IR Page')}")
    except Exception as e:
        print(f"   Error: {e}")
        print(f"   Note: This is expected if running without network access")


def demo_sec_fallback():
    """Demonstrate SEC EDGAR fallback"""
    print("\n" + "="*60)
    print("DEMO 2: SEC EDGAR Fallback")
    print("="*60)
    
    from sec_edgar import SECEdgarClient
    
    print("\n1. Initializing SEC EDGAR client...")
    sec_client = SECEdgarClient(user_email='ajsinha@gmail.com')
    
    print("\n2. Fetching Apple's (AAPL) recent 10-K filings...")
    try:
        filings = sec_client.get_annual_reports(
            cik='0000320193',  # Apple's CIK
            limit=3
        )
        
        print(f"   Found {len(filings)} filings")
        for i, filing in enumerate(filings, 1):
            print(f"   {i}. {filing['form']} - {filing['filing_date']}")
            print(f"      URL: {filing['document_url']}")
    except Exception as e:
        print(f"   Error: {e}")
        print(f"   Note: This is expected if running without network access")


def demo_bot_detection():
    """Demonstrate bot detection avoidance features"""
    print("\n" + "="*60)
    print("DEMO 3: Bot Detection Avoidance")
    print("="*60)
    
    from ir.http_client import EnhancedHTTPClient, RateLimiter
    import time
    
    print("\n1. Rate Limiter Demo...")
    rate_limiter = RateLimiter(min_delay=1.0, max_delay=2.0)
    
    print("   Making 3 requests with rate limiting...")
    start = time.time()
    for i in range(3):
        rate_limiter.wait()
        print(f"   Request {i+1} at {time.time() - start:.2f}s")
    
    print("\n2. HTTP Client Features:")
    client = EnhancedHTTPClient(
        min_delay=2.0,
        max_delay=5.0,
        max_retries=3,
        timeout=30
    )
    
    print(f"   - Rotating user agents: {len(client.USER_AGENTS)} options")
    print(f"   - Rate limiting: {client.rate_limiter.min_delay}-{client.rate_limiter.max_delay}s")
    print(f"   - Retry logic: {client.max_retries} attempts")
    print(f"   - Session management: Cookie jar enabled")
    print(f"   - Realistic headers: Accept, Accept-Language, etc.")


def demo_company_database():
    """Demonstrate company database features"""
    print("\n" + "="*60)
    print("DEMO 4: Company Database")
    print("="*60)
    
    from ir.company_database import CompanyDatabase, CompanyConfig
    
    print("\n1. Loading database...")
    db = CompanyDatabase('../config/ir/sp500_companies.json')
    
    stats = db.get_stats()
    print(f"\n2. Database Statistics:")
    print(f"   Total companies: {stats['total_companies']}")
    print(f"   Companies with CIK: {stats['with_cik']}")
    print(f"   Platforms: {stats['platforms']}")
    
    print(f"\n3. Sample Companies:")
    for ticker in stats['tickers'][:5]:
        company = db.get_company(ticker)
        print(f"   - {ticker}: {company.name}")
        print(f"     IR URL: {company.ir_url}")
        if company.cik:
            print(f"     CIK: {company.cik}")
    
    print("\n4. Adding a new company...")
    new_company = CompanyConfig({
        'ticker': 'DEMO',
        'name': 'Demo Company Inc.',
        'cik': '0009999999',
        'ir_url': 'https://investor.democompany.com',
        'ir_platform': 'generic'
    })
    
    db.add_company(new_company)
    print(f"   Added {new_company.ticker}: {new_company.name}")
    print(f"   Total companies now: {len(db.get_all_tickers())}")


def demo_generic_scraper():
    """Demonstrate generic scraper capabilities"""
    print("\n" + "="*60)
    print("DEMO 5: Generic Scraper")
    print("="*60)
    
    from ir.generic_ir_scraper import GenericIRScraper
    from ir.company_database import CompanyConfig
    
    print("\n1. Creating a generic scraper for Microsoft...")
    
    company_config = CompanyConfig({
        'ticker': 'MSFT',
        'name': 'Microsoft Corporation',
        'cik': '0000789019',
        'ir_url': 'https://www.microsoft.com/en-us/investor',
        'ir_platform': 'generic',
        'document_urls': {
            'earnings': 'https://www.microsoft.com/en-us/investor/earnings/overview'
        }
    })
    
    scraper = GenericIRScraper(
        ticker='MSFT',
        company_config=company_config,
        use_sec_fallback=True
    )
    
    print(f"   IR Page: {scraper.get_ir_page_url()}")
    print(f"   Platform: {scraper.company_config.ir_platform}")
    print(f"   SEC Fallback: {'Enabled' if scraper.sec_client else 'Disabled'}")
    
    print("\n2. Document type patterns:")
    for doc_type, patterns in list(scraper.document_patterns.items())[:3]:
        print(f"   {doc_type}: {len(patterns)} patterns")
        print(f"      Examples: {patterns[:2]}")


def demo_tool_integration():
    """Demonstrate MCP tool integration"""
    print("\n" + "="*60)
    print("DEMO 6: MCP Tool Integration")
    print("="*60)
    
    from tools.impl.enhanced_investor_relations_tool import EnhancedInvestorRelationsTool
    
    print("\n1. Initializing tool...")
    tool = EnhancedInvestorRelationsTool(config={
        'company_config_file': 'sp500_companies.json',
        'use_sec_fallback': True
    })
    
    print("\n2. Available actions:")
    schema = tool.get_input_schema()
    actions = schema['properties']['action']['enum']
    for i, action in enumerate(actions, 1):
        print(f"   {i}. {action}")
    
    print("\n3. Example: List supported companies")
    try:
        result = tool.execute({'action': 'list_supported_companies'})
        if result.get('success'):
            print(f"   Total supported: {result['total_supported']}")
            print(f"   Sample tickers: {', '.join(result['supported_tickers'][:10])}...")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n4. Example: Get company info for Apple")
    try:
        result = tool.execute({
            'action': 'get_company_info',
            'ticker': 'AAPL'
        })
        if result.get('success'):
            print(f"   Company: {result.get('company_name')}")
            print(f"   IR URL: {result.get('ir_page_url')}")
            print(f"   Platform: {result.get('ir_platform')}")
            print(f"   SEC Fallback: {'Available' if result.get('has_cik') else 'Not available'}")
    except Exception as e:
        print(f"   Error: {e}")


def compare_old_vs_new():
    """Compare old vs new system features"""
    print("\n" + "="*60)
    print("COMPARISON: Old vs New System")
    print("="*60)
    
    comparison = [
        ("Companies Supported", "7", "500+"),
        ("Bot Detection", "Basic", "Advanced"),
        ("Rate Limiting", "None", "Configurable"),
        ("Retry Logic", "None", "Exponential backoff"),
        ("SEC Fallback", "None", "Automatic"),
        ("User Agent", "Static", "Rotating realistic"),
        ("Session Management", "None", "Cookie + headers"),
        ("Extensibility", "Requires coding", "JSON config"),
        ("Document Metadata", "Basic", "Enhanced"),
        ("Error Handling", "Basic", "Comprehensive"),
    ]
    
    print("\n{:<25} {:<15} {:<20}".format("Feature", "Old System", "New System"))
    print("-" * 60)
    for feature, old, new in comparison:
        print("{:<25} {:<15} {:<20}".format(feature, old, new))


def main():
    """Run all demos"""
    print("\n" + "="*70)
    print(" "*15 + "ENHANCED IR SCRAPER DEMO")
    print("="*70)
    
    demos = [
        ("Basic Usage", demo_basic_usage),
        ("SEC EDGAR Fallback", demo_sec_fallback),
        ("Bot Detection Avoidance", demo_bot_detection),
        ("Company Database", demo_company_database),
        ("Generic Scraper", demo_generic_scraper),
        ("MCP Tool Integration", demo_tool_integration),
        ("Old vs New Comparison", compare_old_vs_new),
    ]
    
    print("\nAvailable Demos:")
    for i, (name, _) in enumerate(demos, 1):
        print(f"  {i}. {name}")
    print(f"  {len(demos)+1}. Run All")
    print(f"  0. Exit")
    
    choice = input("\nSelect demo (0-{}): ".format(len(demos)+1))
    
    try:
        choice = int(choice)
        
        if choice == 0:
            print("\nExiting...")
            return
        elif choice == len(demos) + 1:
            # Run all
            for name, demo_func in demos:
                try:
                    demo_func()
                except Exception as e:
                    print(f"\nError in {name}: {e}")
                    import traceback
                    traceback.print_exc()
        elif 1 <= choice <= len(demos):
            name, demo_func = demos[choice - 1]
            try:
                demo_func()
            except Exception as e:
                print(f"\nError in {name}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("Invalid choice")
    
    except ValueError:
        print("Invalid input")
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    
    print("\n" + "="*70)
    print("Demo Complete!")
    print("="*70)
    print("\nNext Steps:")
    print("  1. Review README.md for detailed documentation")
    print("  2. Check MIGRATION.md for migration guide")
    print("  3. Customize sp500_companies.json for your needs")
    print("  4. Adjust rate limiting in http_client.py if needed")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
