#!/usr/bin/env python3
"""
SAJHA MCP Server - World Bank Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for World Bank tools:
- wb_get_countries: List countries
- wb_get_indicators: List indicators
- wb_get_indicator_data: Get indicator data
- wb_get_country_data: Get country-specific data
- wb_compare_countries: Compare multiple countries
- wb_search_indicators: Search indicators

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.world_bank_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class WorldBankClient(SajhaClient):
    """Client for World Bank tools."""
    
    def get_countries(self, region: str = None, income_level: str = None) -> dict:
        """
        Get list of countries.
        
        Args:
            region: Filter by region (e.g., 'EAS', 'ECS', 'LCN')
            income_level: Filter by income (e.g., 'HIC', 'MIC', 'LIC')
        """
        args = {}
        if region:
            args['region'] = region
        if income_level:
            args['income_level'] = income_level
        return self.execute_tool('wb_get_countries', args)
    
    def get_indicators(self, topic: str = None, limit: int = 50) -> dict:
        """
        Get list of available indicators.
        
        Args:
            topic: Filter by topic (e.g., 'Economy', 'Health')
            limit: Maximum results
        """
        args = {'limit': limit}
        if topic:
            args['topic'] = topic
        return self.execute_tool('wb_get_indicators', args)
    
    def get_indicator_data(self,
                           indicator: str,
                           country: str = 'all',
                           start_year: int = None,
                           end_year: int = None) -> dict:
        """
        Get data for a specific indicator.
        
        Args:
            indicator: Indicator code (e.g., 'NY.GDP.MKTP.CD')
            country: Country code or 'all' (e.g., 'US', 'CN', 'IN')
            start_year: Start year
            end_year: End year
        """
        args = {'indicator': indicator, 'country': country}
        if start_year:
            args['start_year'] = start_year
        if end_year:
            args['end_year'] = end_year
        return self.execute_tool('wb_get_indicator_data', args)
    
    def get_country_data(self, country: str, indicators: list = None) -> dict:
        """
        Get data for a specific country.
        
        Args:
            country: Country code (e.g., 'US', 'CN')
            indicators: List of indicator codes
        """
        args = {'country': country}
        if indicators:
            args['indicators'] = indicators
        return self.execute_tool('wb_get_country_data', args)
    
    def compare_countries(self,
                          countries: list,
                          indicator: str,
                          year: int = None) -> dict:
        """
        Compare multiple countries on an indicator.
        
        Args:
            countries: List of country codes
            indicator: Indicator code
            year: Specific year (optional)
        """
        args = {'countries': countries, 'indicator': indicator}
        if year:
            args['year'] = year
        return self.execute_tool('wb_compare_countries', args)
    
    def search_indicators(self, query: str, limit: int = 20) -> dict:
        """
        Search for indicators by keyword.
        
        Args:
            query: Search term
            limit: Maximum results
        """
        return self.execute_tool('wb_search_indicators', {
            'query': query,
            'limit': limit
        })
    
    def get_regions(self) -> dict:
        """Get list of World Bank regions."""
        return self.execute_tool('wb_get_regions', {})
    
    def get_income_levels(self) -> dict:
        """Get list of income level classifications."""
        return self.execute_tool('wb_get_income_levels', {})


@run_example
def example_get_countries():
    """Example: Get list of countries"""
    client = WorldBankClient()
    
    print("\n🌍 Getting high-income countries...")
    countries = client.get_countries(income_level='HIC')
    pretty_print(countries, "High Income Countries")


@run_example
def example_search_indicators():
    """Example: Search for indicators"""
    client = WorldBankClient()
    
    print("\n🔍 Searching for GDP indicators...")
    results = client.search_indicators("GDP", limit=10)
    pretty_print(results, "GDP Indicators")


@run_example
def example_get_gdp_data():
    """Example: Get GDP data"""
    client = WorldBankClient()
    
    print("\n💰 Getting US GDP data...")
    gdp = client.get_indicator_data(
        indicator='NY.GDP.MKTP.CD',  # GDP (current US$)
        country='US',
        start_year=2015,
        end_year=2023
    )
    pretty_print(gdp, "US GDP Data")


@run_example
def example_compare_countries():
    """Example: Compare countries"""
    client = WorldBankClient()
    
    countries = ['US', 'CN', 'IN', 'JP', 'DE']
    print(f"\n📊 Comparing GDP for: {', '.join(countries)}")
    comparison = client.compare_countries(
        countries=countries,
        indicator='NY.GDP.MKTP.CD',
        year=2022
    )
    pretty_print(comparison, "GDP Comparison (2022)")


@run_example
def example_country_profile():
    """Example: Country economic profile"""
    client = WorldBankClient()
    
    country = 'IN'  # India
    print(f"\n🇮🇳 Country Profile: {country}")
    
    indicators = [
        'NY.GDP.MKTP.CD',      # GDP
        'NY.GDP.PCAP.CD',      # GDP per capita
        'SP.POP.TOTL',         # Population
        'SL.UEM.TOTL.ZS',      # Unemployment
        'FP.CPI.TOTL.ZG'       # Inflation
    ]
    
    profile = client.get_country_data(country, indicators)
    pretty_print(profile, f"{country} Economic Profile")


@run_example
def example_global_comparison():
    """Example: Global economic comparison"""
    client = WorldBankClient()
    
    print("\n🌐 Global Economic Comparison")
    print("=" * 60)
    
    # G7 countries
    g7 = ['US', 'JP', 'DE', 'GB', 'FR', 'IT', 'CA']
    
    # GDP comparison
    print("\n💵 GDP (2022):")
    gdp_comparison = client.compare_countries(
        countries=g7,
        indicator='NY.GDP.MKTP.CD',
        year=2022
    )
    
    if gdp_comparison.get('data'):
        for item in gdp_comparison['data']:
            country = item.get('country', 'N/A')
            value = item.get('value', 0)
            print(f"   {country}: ${value/1e12:.2f} trillion")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - World Bank Tools Examples v2.2.0")
    print("=" * 60)
    
    example_get_countries()
    example_search_indicators()
    example_get_gdp_data()
    example_compare_countries()
    example_country_profile()
    example_global_comparison()
