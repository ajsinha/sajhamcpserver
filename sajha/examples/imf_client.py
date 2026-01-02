#!/usr/bin/env python3
"""
SAJHA MCP Server - IMF Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for IMF tools:
- imf_get_databases: List available databases
- imf_get_dataflows: List data flows
- imf_get_data: Get data from a dataset
- imf_get_weo_data: World Economic Outlook data
- imf_get_ifs_data: International Financial Statistics
- imf_get_bop_data: Balance of Payments data
- imf_get_country_profile: Country economic profile
- imf_compare_countries: Compare countries

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.imf_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class IMFClient(SajhaClient):
    """Client for IMF data tools."""
    
    def get_databases(self) -> dict:
        """List available IMF databases."""
        return self.execute_tool('imf_get_databases', {})
    
    def get_dataflows(self, database_id: str = None) -> dict:
        """
        List data flows (series) in a database.
        
        Args:
            database_id: Optional database ID filter
        """
        args = {}
        if database_id:
            args['database_id'] = database_id
        return self.execute_tool('imf_get_dataflows', args)
    
    def get_data(self,
                 database_id: str,
                 indicator: str,
                 country: str = None,
                 start_year: int = None,
                 end_year: int = None) -> dict:
        """
        Get data from an IMF dataset.
        
        Args:
            database_id: Database identifier
            indicator: Indicator code
            country: Country code (ISO 3166-1 alpha-2)
            start_year: Start year
            end_year: End year
        """
        args = {'database_id': database_id, 'indicator': indicator}
        if country:
            args['country'] = country
        if start_year:
            args['start_year'] = start_year
        if end_year:
            args['end_year'] = end_year
        return self.execute_tool('imf_get_data', args)
    
    def get_weo_data(self,
                     indicator: str,
                     country: str = None,
                     year: int = None) -> dict:
        """
        Get World Economic Outlook data.
        
        Args:
            indicator: WEO indicator code
            country: Country code
            year: Specific year
        """
        args = {'indicator': indicator}
        if country:
            args['country'] = country
        if year:
            args['year'] = year
        return self.execute_tool('imf_get_weo_data', args)
    
    def get_ifs_data(self,
                     indicator: str,
                     country: str,
                     frequency: str = 'A') -> dict:
        """
        Get International Financial Statistics data.
        
        Args:
            indicator: IFS indicator code
            country: Country code
            frequency: A (Annual), Q (Quarterly), M (Monthly)
        """
        return self.execute_tool('imf_get_ifs_data', {
            'indicator': indicator,
            'country': country,
            'frequency': frequency
        })
    
    def get_bop_data(self, country: str, year: int = None) -> dict:
        """
        Get Balance of Payments data.
        
        Args:
            country: Country code
            year: Specific year
        """
        args = {'country': country}
        if year:
            args['year'] = year
        return self.execute_tool('imf_get_bop_data', args)
    
    def get_country_profile(self, country: str) -> dict:
        """
        Get country economic profile.
        
        Args:
            country: Country code
        """
        return self.execute_tool('imf_get_country_profile', {'country': country})
    
    def compare_countries(self,
                          countries: list,
                          indicator: str,
                          year: int = None) -> dict:
        """
        Compare multiple countries on an indicator.
        
        Args:
            countries: List of country codes
            indicator: Indicator code
            year: Specific year
        """
        args = {'countries': countries, 'indicator': indicator}
        if year:
            args['year'] = year
        return self.execute_tool('imf_compare_countries', args)


@run_example
def example_list_databases():
    """Example: List IMF databases"""
    client = IMFClient()
    
    print("\n📚 Listing IMF databases...")
    databases = client.get_databases()
    pretty_print(databases, "IMF Databases")


@run_example
def example_weo_data():
    """Example: Get World Economic Outlook data"""
    client = IMFClient()
    
    print("\n🌍 Getting WEO data for US GDP growth...")
    weo = client.get_weo_data(
        indicator='NGDP_RPCH',  # Real GDP growth
        country='US'
    )
    pretty_print(weo, "US GDP Growth (WEO)")


@run_example
def example_country_profile():
    """Example: Get country economic profile"""
    client = IMFClient()
    
    print("\n🇺🇸 Getting US economic profile...")
    profile = client.get_country_profile('US')
    pretty_print(profile, "US Economic Profile")


@run_example
def example_compare_gdp_growth():
    """Example: Compare GDP growth across countries"""
    client = IMFClient()
    
    countries = ['US', 'CN', 'DE', 'JP', 'IN']
    print(f"\n📊 Comparing GDP growth: {', '.join(countries)}")
    
    comparison = client.compare_countries(
        countries=countries,
        indicator='NGDP_RPCH'  # Real GDP growth
    )
    pretty_print(comparison, "GDP Growth Comparison")


@run_example
def example_emerging_markets():
    """Example: Emerging markets analysis"""
    client = IMFClient()
    
    print("\n🌏 Emerging Markets Analysis")
    print("=" * 50)
    
    emerging = ['CN', 'IN', 'BR', 'RU', 'ZA']  # BRICS
    
    for country in emerging:
        print(f"\n   {country}:")
        try:
            profile = client.get_country_profile(country)
            print(f"   GDP Growth: {profile.get('gdp_growth', 'N/A')}")
            print(f"   Inflation: {profile.get('inflation', 'N/A')}")
        except Exception as e:
            print(f"   Error: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - IMF Tools Examples v2.2.0")
    print("=" * 60)
    
    example_list_databases()
    example_weo_data()
    example_country_profile()
    example_compare_gdp_growth()
    example_emerging_markets()
