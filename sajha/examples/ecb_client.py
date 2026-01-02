#!/usr/bin/env python3
"""
SAJHA MCP Server - European Central Bank Tools Client v2.1.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for ECB tools:
- ecb_get_exchange_rate: Get EUR exchange rates
- ecb_get_interest_rate: Get ECB interest rates
- ecb_get_inflation: Get eurozone inflation data
- ecb_get_bond_yield: Get government bond yields
- ecb_search_series: Search ECB data series
- ecb_get_series: Get specific series data
- ecb_get_latest: Get latest values
- ecb_get_common_indicators: Get common eurozone indicators

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.ecb_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class ECBClient(SajhaClient):
    """Client for European Central Bank tools."""
    
    def get_exchange_rate(self, 
                          currency: str = 'USD',
                          start_date: str = None,
                          end_date: str = None) -> dict:
        """
        Get EUR exchange rate against another currency.
        
        Args:
            currency: Target currency (USD, GBP, JPY, etc.)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        """
        args = {'currency': currency}
        if start_date:
            args['start_date'] = start_date
        if end_date:
            args['end_date'] = end_date
        return self.execute_tool('ecb_get_exchange_rate', args)
    
    def get_interest_rate(self, rate_type: str = 'MRO') -> dict:
        """
        Get ECB interest rates.
        
        Args:
            rate_type: Rate type (MRO, MLF, DFR)
                - MRO: Main Refinancing Operations
                - MLF: Marginal Lending Facility
                - DFR: Deposit Facility Rate
        """
        return self.execute_tool('ecb_get_interest_rate', {'rate_type': rate_type})
    
    def get_inflation(self, 
                      country: str = 'EA',
                      measure: str = 'HICP') -> dict:
        """
        Get inflation data.
        
        Args:
            country: Country code (EA for eurozone, DE, FR, etc.)
            measure: Inflation measure (HICP, Core, etc.)
        """
        return self.execute_tool('ecb_get_inflation', {
            'country': country,
            'measure': measure
        })
    
    def get_bond_yield(self, country: str = 'DE', maturity: str = '10Y') -> dict:
        """
        Get government bond yields.
        
        Args:
            country: Country code (DE, FR, IT, ES, etc.)
            maturity: Bond maturity (2Y, 5Y, 10Y, 30Y)
        """
        return self.execute_tool('ecb_get_bond_yield', {
            'country': country,
            'maturity': maturity
        })
    
    def search_series(self, query: str, limit: int = 10) -> dict:
        """Search ECB data series."""
        return self.execute_tool('ecb_search_series', {
            'query': query,
            'limit': limit
        })
    
    def get_common_indicators(self) -> dict:
        """Get common eurozone economic indicators."""
        return self.execute_tool('ecb_get_common_indicators', {})


@run_example
def example_exchange_rates():
    """Example: Get EUR exchange rates"""
    client = ECBClient()
    
    currencies = ['USD', 'GBP', 'JPY', 'CHF']
    print("\n💱 EUR Exchange Rates")
    print("-" * 40)
    
    for currency in currencies:
        rate = client.get_exchange_rate(currency)
        pretty_print(rate, f"EUR/{currency}")


@run_example
def example_interest_rates():
    """Example: Get ECB interest rates"""
    client = ECBClient()
    
    print("\n🏦 ECB Interest Rates")
    
    rates = ['MRO', 'MLF', 'DFR']
    for rate_type in rates:
        rate = client.get_interest_rate(rate_type)
        pretty_print(rate, f"{rate_type} Rate")


@run_example
def example_inflation():
    """Example: Get eurozone inflation"""
    client = ECBClient()
    
    print("\n📊 Eurozone Inflation Data")
    inflation = client.get_inflation('EA', 'HICP')
    pretty_print(inflation, "Eurozone HICP Inflation")


@run_example
def example_bond_yields():
    """Example: Get European government bond yields"""
    client = ECBClient()
    
    countries = ['DE', 'FR', 'IT', 'ES']
    print("\n📈 10-Year Government Bond Yields")
    print("-" * 40)
    
    for country in countries:
        try:
            yield_data = client.get_bond_yield(country, '10Y')
            pretty_print(yield_data, f"{country} 10Y Yield")
        except Exception as e:
            print(f"{country}: Error - {e}")


@run_example
def example_eurozone_dashboard():
    """Example: Complete eurozone economic dashboard"""
    client = ECBClient()
    
    print("\n🇪🇺 Eurozone Economic Dashboard")
    print("=" * 50)
    
    # Exchange rates
    print("\n💱 Major Exchange Rates (EUR base):")
    for curr in ['USD', 'GBP', 'JPY']:
        try:
            rate = client.get_exchange_rate(curr)
            print(f"   EUR/{curr}: {rate.get('rate', 'N/A')}")
        except:
            pass
    
    # Interest rates
    print("\n🏦 ECB Policy Rates:")
    for rate_type in ['MRO', 'DFR']:
        try:
            rate = client.get_interest_rate(rate_type)
            print(f"   {rate_type}: {rate.get('rate', 'N/A')}%")
        except:
            pass
    
    # Common indicators
    print("\n📊 Common Indicators:")
    try:
        indicators = client.get_common_indicators()
        pretty_print(indicators, "")
    except Exception as e:
        print(f"   Error: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - ECB Tools Examples v2.1.0")
    print("=" * 60)
    
    example_exchange_rates()
    example_interest_rates()
    example_inflation()
    example_bond_yields()
    example_eurozone_dashboard()
