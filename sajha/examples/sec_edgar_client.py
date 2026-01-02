#!/usr/bin/env python3
"""
SAJHA MCP Server - SEC EDGAR Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for SEC EDGAR tools:
- edgar_company_search: Search for companies
- edgar_company_facts: Get company financial facts
- edgar_company_submissions: Get company filings
- edgar_filing_details: Get filing details
- edgar_insider_transactions: Get insider trading data
- edgar_financial_ratios: Get financial ratios
- And many more...

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.sec_edgar_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class SECEdgarClient(SajhaClient):
    """Client for SEC EDGAR tools."""
    
    def search_company(self, query: str, limit: int = 10) -> dict:
        """
        Search for companies by name or ticker.
        
        Args:
            query: Company name or ticker symbol
            limit: Maximum results
        """
        return self.execute_tool('edgar_company_search', {
            'query': query,
            'limit': limit
        })
    
    def get_company_facts(self, cik: str) -> dict:
        """
        Get company financial facts (XBRL data).
        
        Args:
            cik: Central Index Key (10-digit, zero-padded)
        """
        return self.execute_tool('edgar_company_facts', {'cik': cik})
    
    def get_company_submissions(self, cik: str, form_type: str = None) -> dict:
        """
        Get company SEC filings.
        
        Args:
            cik: Central Index Key
            form_type: Optional filter (10-K, 10-Q, 8-K, etc.)
        """
        args = {'cik': cik}
        if form_type:
            args['form_type'] = form_type
        return self.execute_tool('edgar_company_submissions', args)
    
    def get_filing_details(self, accession_number: str) -> dict:
        """
        Get details of a specific filing.
        
        Args:
            accession_number: SEC accession number
        """
        return self.execute_tool('edgar_filing_details', {
            'accession_number': accession_number
        })
    
    def get_insider_transactions(self, cik: str, limit: int = 20) -> dict:
        """
        Get insider trading transactions.
        
        Args:
            cik: Company CIK
            limit: Maximum transactions
        """
        return self.execute_tool('edgar_insider_transactions', {
            'cik': cik,
            'limit': limit
        })
    
    def get_financial_ratios(self, cik: str) -> dict:
        """
        Get calculated financial ratios.
        
        Args:
            cik: Company CIK
        """
        return self.execute_tool('edgar_financial_ratios', {'cik': cik})
    
    def get_institutional_holdings(self, cik: str) -> dict:
        """
        Get institutional ownership data (13F filings).
        
        Args:
            cik: Company CIK
        """
        return self.execute_tool('edgar_institutional_holdings', {'cik': cik})
    
    def search_by_sic(self, sic_code: str, limit: int = 20) -> dict:
        """
        Search companies by SIC code (industry).
        
        Args:
            sic_code: Standard Industrial Classification code
            limit: Maximum results
        """
        return self.execute_tool('edgar_companies_by_sic', {
            'sic_code': sic_code,
            'limit': limit
        })
    
    def get_10k_filings(self, cik: str, limit: int = 5) -> dict:
        """Get 10-K annual report filings."""
        return self.execute_tool('edgar_filings_by_form', {
            'cik': cik,
            'form_type': '10-K',
            'limit': limit
        })
    
    def get_10q_filings(self, cik: str, limit: int = 5) -> dict:
        """Get 10-Q quarterly report filings."""
        return self.execute_tool('edgar_filings_by_form', {
            'cik': cik,
            'form_type': '10-Q',
            'limit': limit
        })


@run_example
def example_search_company():
    """Example: Search for companies"""
    client = SECEdgarClient()
    
    print("\n🔍 Searching for 'Apple'...")
    results = client.search_company("Apple", limit=5)
    pretty_print(results, "Company Search Results")


@run_example
def example_get_company_filings():
    """Example: Get company filings"""
    client = SECEdgarClient()
    
    # Apple's CIK
    cik = "0000320193"
    print(f"\n📄 Getting filings for Apple (CIK: {cik})...")
    filings = client.get_company_submissions(cik)
    pretty_print(filings, "Apple SEC Filings")


@run_example
def example_get_10k_filings():
    """Example: Get 10-K annual reports"""
    client = SECEdgarClient()
    
    # Microsoft's CIK
    cik = "0000789019"
    print(f"\n📊 Getting 10-K filings for Microsoft...")
    filings = client.get_10k_filings(cik, limit=3)
    pretty_print(filings, "Microsoft 10-K Filings")


@run_example
def example_insider_transactions():
    """Example: Get insider trading data"""
    client = SECEdgarClient()
    
    # Tesla's CIK
    cik = "0001318605"
    print(f"\n👔 Getting insider transactions for Tesla...")
    transactions = client.get_insider_transactions(cik, limit=10)
    pretty_print(transactions, "Tesla Insider Transactions")


@run_example
def example_financial_ratios():
    """Example: Get financial ratios"""
    client = SECEdgarClient()
    
    # Amazon's CIK
    cik = "0001018724"
    print(f"\n📈 Getting financial ratios for Amazon...")
    ratios = client.get_financial_ratios(cik)
    pretty_print(ratios, "Amazon Financial Ratios")


@run_example
def example_industry_analysis():
    """Example: Industry analysis using SIC codes"""
    client = SECEdgarClient()
    
    # SIC 7372: Prepackaged Software
    sic_code = "7372"
    print(f"\n🏭 Finding companies in SIC {sic_code} (Software)...")
    companies = client.search_by_sic(sic_code, limit=10)
    pretty_print(companies, "Software Industry Companies")


@run_example
def example_company_deep_dive():
    """Example: Complete company analysis"""
    client = SECEdgarClient()
    
    company_name = "NVIDIA"
    print(f"\n🔬 Deep Dive Analysis: {company_name}")
    print("=" * 50)
    
    # Step 1: Search for company
    print("\n1️⃣ Searching for company...")
    search_results = client.search_company(company_name, limit=1)
    
    if search_results.get('companies'):
        company = search_results['companies'][0]
        cik = company.get('cik', '')
        print(f"   Found: {company.get('name')} (CIK: {cik})")
        
        if cik:
            # Step 2: Get recent filings
            print("\n2️⃣ Recent filings...")
            filings = client.get_company_submissions(cik)
            if filings.get('filings'):
                for f in filings['filings'][:5]:
                    print(f"   - {f.get('form', 'N/A')}: {f.get('filedAt', 'N/A')}")
            
            # Step 3: Financial ratios
            print("\n3️⃣ Financial ratios...")
            try:
                ratios = client.get_financial_ratios(cik)
                pretty_print(ratios, "")
            except Exception as e:
                print(f"   Error: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - SEC EDGAR Tools Examples v2.2.0")
    print("=" * 60)
    
    example_search_company()
    example_get_company_filings()
    example_get_10k_filings()
    example_insider_transactions()
    example_financial_ratios()
    example_industry_analysis()
    example_company_deep_dive()
