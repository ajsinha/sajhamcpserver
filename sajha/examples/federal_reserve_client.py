#!/usr/bin/env python3
"""
SAJHA MCP Server - Federal Reserve Tools Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Federal Reserve (FRED) tools:
- fed_search_series: Search economic data series
- fed_get_series: Get data for a specific series
- fed_get_latest: Get latest value
- fed_get_common_indicators: Get common economic indicators

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.federal_reserve_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class FederalReserveClient(SajhaClient):
    """Client for Federal Reserve (FRED) tools."""
    
    def search_series(self, query: str, limit: int = 10) -> dict:
        """
        Search for economic data series.
        
        Args:
            query: Search term (e.g., 'GDP', 'unemployment')
            limit: Maximum results
        """
        return self.execute_tool('fed_search_series', {
            'query': query,
            'limit': limit
        })
    
    def get_series(self, 
                   series_id: str,
                   start_date: str = None,
                   end_date: str = None,
                   limit: int = 100) -> dict:
        """
        Get data for a specific series.
        
        Args:
            series_id: FRED series ID (e.g., 'GDP', 'UNRATE')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Maximum data points
        """
        args = {'series_id': series_id, 'limit': limit}
        if start_date:
            args['start_date'] = start_date
        if end_date:
            args['end_date'] = end_date
        return self.execute_tool('fed_get_series', args)
    
    def get_latest(self, series_id: str) -> dict:
        """
        Get latest value for a series.
        
        Args:
            series_id: FRED series ID
        """
        return self.execute_tool('fed_get_latest', {'series_id': series_id})
    
    def get_common_indicators(self) -> dict:
        """Get common economic indicators (GDP, unemployment, inflation, etc.)."""
        return self.execute_tool('fed_get_common_indicators', {})


@run_example
def example_search_series():
    """Example: Search for economic series"""
    client = FederalReserveClient()
    
    print("\n🔍 Searching for 'inflation' series...")
    results = client.search_series("inflation", limit=5)
    pretty_print(results, "FRED Series Search Results")


@run_example
def example_get_gdp_data():
    """Example: Get GDP data"""
    client = FederalReserveClient()
    
    print("\n📊 Getting GDP data (last 2 years)...")
    gdp = client.get_series('GDP', limit=8)  # Quarterly data
    pretty_print(gdp, "US GDP Data")


@run_example
def example_get_unemployment():
    """Example: Get unemployment rate"""
    client = FederalReserveClient()
    
    print("\n👷 Getting unemployment rate...")
    unrate = client.get_latest('UNRATE')
    pretty_print(unrate, "US Unemployment Rate")


@run_example
def example_get_common_indicators():
    """Example: Get common economic indicators"""
    client = FederalReserveClient()
    
    print("\n📈 Getting common economic indicators...")
    indicators = client.get_common_indicators()
    pretty_print(indicators, "Common Economic Indicators")


@run_example
def example_economic_dashboard():
    """Example: Economic dashboard with multiple indicators"""
    client = FederalReserveClient()
    
    indicators = {
        'UNRATE': 'Unemployment Rate',
        'CPIAUCSL': 'Consumer Price Index',
        'FEDFUNDS': 'Federal Funds Rate',
        'GDP': 'Gross Domestic Product',
        'DGS10': '10-Year Treasury Rate'
    }
    
    print("\n🎯 Economic Dashboard")
    print("-" * 50)
    
    for series_id, name in indicators.items():
        try:
            latest = client.get_latest(series_id)
            value = latest.get('value', 'N/A')
            date = latest.get('date', 'N/A')
            print(f"{name:<30} {value:>10} ({date})")
        except Exception as e:
            print(f"{name:<30} Error: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Federal Reserve Tools Examples v2.3.0")
    print("=" * 60)
    
    example_search_series()
    example_get_gdp_data()
    example_get_unemployment()
    example_get_common_indicators()
    example_economic_dashboard()
