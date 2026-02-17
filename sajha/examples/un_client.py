#!/usr/bin/env python3
"""
SAJHA MCP Server - United Nations Tools Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for UN tools:
- un_get_sdgs: Get Sustainable Development Goals
- un_get_sdg_targets: Get SDG targets
- un_get_sdg_indicators: Get SDG indicators
- un_get_sdg_data: Get SDG data
- un_get_sdg_progress: Get country progress on SDGs
- un_get_trade_data: Get UN Comtrade data
- un_get_country_trade: Get country trade summary
- un_get_trade_balance: Get trade balance
- un_compare_trade: Compare trade between countries

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.un_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class UNClient(SajhaClient):
    """Client for United Nations data tools."""
    
    def get_sdgs(self) -> dict:
        """Get list of Sustainable Development Goals."""
        return self.execute_tool('un_get_sdgs', {})
    
    def get_sdg_targets(self, goal: int) -> dict:
        """
        Get targets for a specific SDG.
        
        Args:
            goal: SDG number (1-17)
        """
        return self.execute_tool('un_get_sdg_targets', {'goal': goal})
    
    def get_sdg_indicators(self, goal: int, target: str = None) -> dict:
        """
        Get indicators for an SDG.
        
        Args:
            goal: SDG number
            target: Specific target (optional)
        """
        args = {'goal': goal}
        if target:
            args['target'] = target
        return self.execute_tool('un_get_sdg_indicators', args)
    
    def get_sdg_data(self,
                     indicator: str,
                     country: str,
                     year: int = None) -> dict:
        """
        Get SDG indicator data.
        
        Args:
            indicator: SDG indicator code
            country: Country code
            year: Specific year
        """
        args = {'indicator': indicator, 'country': country}
        if year:
            args['year'] = year
        return self.execute_tool('un_get_sdg_data', args)
    
    def get_sdg_progress(self, country: str, goal: int = None) -> dict:
        """
        Get country's SDG progress.
        
        Args:
            country: Country code
            goal: Specific SDG (optional, all if not specified)
        """
        args = {'country': country}
        if goal:
            args['goal'] = goal
        return self.execute_tool('un_get_sdg_progress', args)
    
    def get_trade_data(self,
                       reporter: str,
                       partner: str = None,
                       year: int = None,
                       commodity: str = None) -> dict:
        """
        Get UN Comtrade data.
        
        Args:
            reporter: Reporter country code
            partner: Partner country (optional)
            year: Trade year
            commodity: HS commodity code
        """
        args = {'reporter': reporter}
        if partner:
            args['partner'] = partner
        if year:
            args['year'] = year
        if commodity:
            args['commodity'] = commodity
        return self.execute_tool('un_get_trade_data', args)
    
    def get_country_trade(self, country: str, year: int = None) -> dict:
        """
        Get country trade summary.
        
        Args:
            country: Country code
            year: Trade year
        """
        args = {'country': country}
        if year:
            args['year'] = year
        return self.execute_tool('un_get_country_trade', args)
    
    def get_trade_balance(self, country: str, year: int = None) -> dict:
        """
        Get country trade balance.
        
        Args:
            country: Country code
            year: Trade year
        """
        args = {'country': country}
        if year:
            args['year'] = year
        return self.execute_tool('un_get_trade_balance', args)
    
    def compare_trade(self,
                      countries: list,
                      indicator: str = 'total_trade',
                      year: int = None) -> dict:
        """
        Compare trade across countries.
        
        Args:
            countries: List of country codes
            indicator: Trade indicator
            year: Trade year
        """
        args = {'countries': countries, 'indicator': indicator}
        if year:
            args['year'] = year
        return self.execute_tool('un_compare_trade', args)


@run_example
def example_list_sdgs():
    """Example: List SDGs"""
    client = UNClient()
    
    print("\n🎯 Listing Sustainable Development Goals...")
    sdgs = client.get_sdgs()
    pretty_print(sdgs, "UN SDGs")


@run_example
def example_sdg_targets():
    """Example: Get SDG targets"""
    client = UNClient()
    
    goal = 1  # No Poverty
    print(f"\n🎯 Getting targets for SDG {goal}...")
    targets = client.get_sdg_targets(goal)
    pretty_print(targets, f"SDG {goal} Targets")


@run_example
def example_sdg_progress():
    """Example: Get country SDG progress"""
    client = UNClient()
    
    print("\n📊 Getting US SDG progress...")
    progress = client.get_sdg_progress('US')
    pretty_print(progress, "US SDG Progress")


@run_example
def example_country_trade():
    """Example: Get country trade data"""
    client = UNClient()
    
    print("\n🚢 Getting US trade summary...")
    trade = client.get_country_trade('US')
    pretty_print(trade, "US Trade Summary")


@run_example
def example_trade_balance():
    """Example: Get trade balance"""
    client = UNClient()
    
    print("\n⚖️ Getting US trade balance...")
    balance = client.get_trade_balance('US')
    pretty_print(balance, "US Trade Balance")


@run_example
def example_compare_trade():
    """Example: Compare trade across countries"""
    client = UNClient()
    
    countries = ['US', 'CN', 'DE', 'JP']
    print(f"\n📊 Comparing trade: {', '.join(countries)}")
    
    comparison = client.compare_trade(countries)
    pretty_print(comparison, "Trade Comparison")


@run_example
def example_sdg_dashboard():
    """Example: SDG Dashboard"""
    client = UNClient()
    
    print("\n🌍 SDG Dashboard")
    print("=" * 50)
    
    # List first 5 SDGs
    print("\n📋 SDG Overview:")
    sdgs = client.get_sdgs()
    
    if sdgs.get('goals'):
        for goal in sdgs['goals'][:5]:
            print(f"   {goal.get('number')}. {goal.get('title')}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - UN Tools Examples v2.3.0")
    print("=" * 60)
    
    example_list_sdgs()
    example_sdg_targets()
    example_sdg_progress()
    example_country_trade()
    example_trade_balance()
    example_compare_trade()
    example_sdg_dashboard()
