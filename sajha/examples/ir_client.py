#!/usr/bin/env python3
"""
SAJHA MCP Server - Investor Relations Tools Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Investor Relations tools:
- ir_list_supported_companies: List supported companies
- ir_get_annual_reports: Get annual reports
- ir_get_presentations: Get investor presentations
- ir_get_documents: Get IR documents
- ir_get_latest_earnings: Get latest earnings info
- ir_get_all_resources: Get all IR resources
- ir_find_page: Find specific IR page

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.ir_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class InvestorRelationsClient(SajhaClient):
    """Client for Investor Relations tools."""
    
    def list_supported_companies(self) -> dict:
        """List companies with IR support."""
        return self.execute_tool('ir_list_supported_companies', {})
    
    def get_annual_reports(self, 
                           company: str, 
                           limit: int = 5) -> dict:
        """
        Get annual reports for a company.
        
        Args:
            company: Company ticker or name
            limit: Maximum reports
        """
        return self.execute_tool('ir_get_annual_reports', {
            'company': company,
            'limit': limit
        })
    
    def get_presentations(self, 
                          company: str, 
                          limit: int = 10) -> dict:
        """
        Get investor presentations.
        
        Args:
            company: Company ticker or name
            limit: Maximum presentations
        """
        return self.execute_tool('ir_get_presentations', {
            'company': company,
            'limit': limit
        })
    
    def get_documents(self, 
                      company: str,
                      doc_type: str = None,
                      limit: int = 20) -> dict:
        """
        Get IR documents.
        
        Args:
            company: Company ticker or name
            doc_type: Document type filter
            limit: Maximum documents
        """
        args = {'company': company, 'limit': limit}
        if doc_type:
            args['doc_type'] = doc_type
        return self.execute_tool('ir_get_documents', args)
    
    def get_latest_earnings(self, company: str) -> dict:
        """
        Get latest earnings information.
        
        Args:
            company: Company ticker or name
        """
        return self.execute_tool('ir_get_latest_earnings', {'company': company})
    
    def get_all_resources(self, company: str) -> dict:
        """
        Get all IR resources for a company.
        
        Args:
            company: Company ticker or name
        """
        return self.execute_tool('ir_get_all_resources', {'company': company})
    
    def find_page(self, company: str, page_type: str) -> dict:
        """
        Find specific IR page.
        
        Args:
            company: Company ticker or name
            page_type: Page type (annual_reports, presentations, etc.)
        """
        return self.execute_tool('ir_find_page', {
            'company': company,
            'page_type': page_type
        })


@run_example
def example_list_companies():
    """Example: List supported companies"""
    client = InvestorRelationsClient()
    
    print("\n🏢 Listing supported companies...")
    companies = client.list_supported_companies()
    pretty_print(companies, "Supported Companies")


@run_example
def example_annual_reports():
    """Example: Get annual reports"""
    client = InvestorRelationsClient()
    
    company = "AAPL"
    print(f"\n📊 Getting annual reports for {company}...")
    reports = client.get_annual_reports(company, limit=3)
    pretty_print(reports, f"{company} Annual Reports")


@run_example
def example_presentations():
    """Example: Get investor presentations"""
    client = InvestorRelationsClient()
    
    company = "MSFT"
    print(f"\n📑 Getting presentations for {company}...")
    presentations = client.get_presentations(company, limit=5)
    pretty_print(presentations, f"{company} Presentations")


@run_example
def example_latest_earnings():
    """Example: Get latest earnings"""
    client = InvestorRelationsClient()
    
    company = "GOOGL"
    print(f"\n💰 Getting latest earnings for {company}...")
    earnings = client.get_latest_earnings(company)
    pretty_print(earnings, f"{company} Latest Earnings")


@run_example
def example_all_resources():
    """Example: Get all IR resources"""
    client = InvestorRelationsClient()
    
    company = "AMZN"
    print(f"\n📚 Getting all IR resources for {company}...")
    resources = client.get_all_resources(company)
    pretty_print(resources, f"{company} IR Resources")


@run_example
def example_company_deep_dive():
    """Example: Company IR deep dive"""
    client = InvestorRelationsClient()
    
    company = "NVDA"
    print(f"\n🔬 IR Deep Dive: {company}")
    print("=" * 50)
    
    # Step 1: Get all resources
    print("\n1️⃣ Available resources:")
    try:
        resources = client.get_all_resources(company)
        if resources.get('categories'):
            for cat, items in resources['categories'].items():
                print(f"   • {cat}: {len(items) if isinstance(items, list) else 'N/A'} items")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Step 2: Latest earnings
    print("\n2️⃣ Latest earnings:")
    try:
        earnings = client.get_latest_earnings(company)
        print(f"   Date: {earnings.get('date', 'N/A')}")
        print(f"   EPS: {earnings.get('eps', 'N/A')}")
        print(f"   Revenue: {earnings.get('revenue', 'N/A')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Step 3: Recent presentations
    print("\n3️⃣ Recent presentations:")
    try:
        presentations = client.get_presentations(company, limit=3)
        if presentations.get('presentations'):
            for p in presentations['presentations'][:3]:
                print(f"   • {p.get('title', 'N/A')[:50]}")
    except Exception as e:
        print(f"   Error: {e}")


@run_example
def example_earnings_comparison():
    """Example: Compare earnings across companies"""
    client = InvestorRelationsClient()
    
    companies = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']
    print(f"\n📈 Earnings Comparison: {', '.join(companies)}")
    print("-" * 50)
    
    for company in companies:
        try:
            earnings = client.get_latest_earnings(company)
            eps = earnings.get('eps', 'N/A')
            date = earnings.get('date', 'N/A')
            print(f"   {company}: EPS ${eps} ({date})")
        except Exception as e:
            print(f"   {company}: Error - {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - IR Tools Examples v2.3.0")
    print("=" * 60)
    
    example_list_companies()
    example_annual_reports()
    example_presentations()
    example_latest_earnings()
    example_all_resources()
    example_company_deep_dive()
    example_earnings_comparison()
