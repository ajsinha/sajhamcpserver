#!/usr/bin/env python3
"""
SAJHA MCP Server - Central Banks Tools Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Central Bank tools:
- Bank of Canada (BoC): boc_* tools
- Bank of Japan (BoJ): boj_* tools
- People's Bank of China (PBoC): pboc_* tools
- Banque de France (BdF): bdf_* tools

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.central_banks_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class CentralBanksClient(SajhaClient):
    """Client for Central Bank data tools."""
    
    # ============= Bank of Canada =============
    def boc_get_exchange_rate(self, currency: str = 'USD') -> dict:
        """Get CAD exchange rate."""
        return self.execute_tool('boc_get_exchange_rate', {'currency': currency})
    
    def boc_get_interest_rate(self, rate_type: str = 'policy') -> dict:
        """Get BoC interest rate."""
        return self.execute_tool('boc_get_interest_rate', {'rate_type': rate_type})
    
    def boc_get_bond_yield(self, maturity: str = '10Y') -> dict:
        """Get Canadian bond yield."""
        return self.execute_tool('boc_get_bond_yield', {'maturity': maturity})
    
    def boc_get_common_indicators(self) -> dict:
        """Get common Canadian economic indicators."""
        return self.execute_tool('boc_get_common_indicators', {})
    
    def boc_search_series(self, query: str, limit: int = 10) -> dict:
        """Search BoC data series."""
        return self.execute_tool('boc_search_series', {'query': query, 'limit': limit})
    
    # ============= Bank of Japan =============
    def boj_get_exchange_rate(self, currency: str = 'USD') -> dict:
        """Get JPY exchange rate."""
        return self.execute_tool('boj_get_exchange_rate', {'currency': currency})
    
    def boj_get_policy_rate(self) -> dict:
        """Get BoJ policy rate."""
        return self.execute_tool('boj_get_policy_rate', {})
    
    def boj_get_jgb_yield(self, maturity: str = '10Y') -> dict:
        """Get Japanese Government Bond yield."""
        return self.execute_tool('boj_get_jgb_yield', {'maturity': maturity})
    
    def boj_get_money_stock(self) -> dict:
        """Get Japan money stock (M2)."""
        return self.execute_tool('boj_get_money_stock', {})
    
    def boj_get_price_index(self) -> dict:
        """Get Japan price indices."""
        return self.execute_tool('boj_get_price_index', {})
    
    # ============= People's Bank of China =============
    def pboc_get_exchange_rate(self, currency: str = 'USD') -> dict:
        """Get CNY exchange rate."""
        return self.execute_tool('pboc_get_exchange_rate', {'currency': currency})
    
    def pboc_get_lpr(self) -> dict:
        """Get Loan Prime Rate (LPR)."""
        return self.execute_tool('pboc_get_lpr', {})
    
    def pboc_get_forex_reserves(self) -> dict:
        """Get China forex reserves."""
        return self.execute_tool('pboc_get_forex_reserves', {})
    
    # ============= Banque de France =============
    def bdf_get_exchange_rate(self, currency: str = 'USD') -> dict:
        """Get EUR/currency rate from BdF."""
        return self.execute_tool('bdf_get_exchange_rate', {'currency': currency})
    
    def bdf_get_ecb_policy_rate(self) -> dict:
        """Get ECB policy rate from BdF."""
        return self.execute_tool('bdf_get_ecb_policy_rate', {})
    
    def bdf_get_oat_yield(self, maturity: str = '10y') -> dict:
        """Get the French 10-year government bond (OAT) yield."""
        return self.execute_tool('bdf_get_oat_yield', {'bond_term': maturity.lower()})
    
    def bdf_get_french_indicator(self, indicator: str) -> dict:
        """Get French economic indicator."""
        return self.execute_tool('bdf_get_french_indicator', {'indicator': indicator})
    
    def bdf_get_eurozone_indicator(self, indicator: str) -> dict:
        """Get Eurozone economic indicator."""
        return self.execute_tool('bdf_get_eurozone_indicator', {'indicator': indicator})


@run_example
def example_boc_overview():
    """Example: Bank of Canada overview"""
    client = CentralBanksClient()
    
    print("\n🇨🇦 Bank of Canada Data")
    print("-" * 40)
    
    # Exchange rate
    print("\n💱 CAD/USD Exchange Rate:")
    rate = client.boc_get_exchange_rate('USD')
    print(f"   {rate}")
    
    # Interest rate
    print("\n🏦 Policy Rate:")
    policy = client.boc_get_interest_rate('policy')
    print(f"   {policy}")


@run_example
def example_boj_overview():
    """Example: Bank of Japan overview"""
    client = CentralBanksClient()
    
    print("\n🇯🇵 Bank of Japan Data")
    print("-" * 40)
    
    # Exchange rate
    print("\n💱 USD/JPY Exchange Rate:")
    rate = client.boj_get_exchange_rate('USD')
    print(f"   {rate}")
    
    # JGB yield
    print("\n📊 10Y JGB Yield:")
    jgb = client.boj_get_jgb_yield('10Y')
    print(f"   {jgb}")


@run_example
def example_pboc_overview():
    """Example: People's Bank of China overview"""
    client = CentralBanksClient()
    
    print("\n🇨🇳 People's Bank of China Data")
    print("-" * 40)
    
    # Exchange rate
    print("\n💱 USD/CNY Exchange Rate:")
    rate = client.pboc_get_exchange_rate('USD')
    print(f"   {rate}")
    
    # LPR
    print("\n🏦 Loan Prime Rate:")
    lpr = client.pboc_get_lpr()
    print(f"   {lpr}")


@run_example
def example_global_central_bank_dashboard():
    """Example: Global central bank dashboard"""
    client = CentralBanksClient()
    
    print("\n🌍 Global Central Bank Dashboard")
    print("=" * 60)
    
    central_banks = {
        'Bank of Canada': ('boc_get_exchange_rate', 'CAD'),
        'Bank of Japan': ('boj_get_exchange_rate', 'JPY'),
        'PBoC': ('pboc_get_exchange_rate', 'CNY'),
    }
    
    print("\n💱 Exchange Rates vs USD:")
    for name, (method, currency) in central_banks.items():
        try:
            rate = getattr(client, method)('USD')
            print(f"   {name}: {rate.get('rate', 'N/A')}")
        except Exception as e:
            print(f"   {name}: Error - {e}")
    
    print("\n🏦 Policy Rates:")
    policy_methods = [
        ('Bank of Canada', 'boc_get_interest_rate', {'rate_type': 'policy'}),
        ('Bank of Japan', 'boj_get_policy_rate', {}),
        ('PBoC (LPR)', 'pboc_get_lpr', {}),
    ]
    
    for name, method, args in policy_methods:
        try:
            rate = getattr(client, method)(**args)
            print(f"   {name}: {rate.get('rate', 'N/A')}%")
        except Exception as e:
            print(f"   {name}: Error - {e}")


@run_example
def example_bond_yields_comparison():
    """Example: Global bond yields comparison"""
    client = CentralBanksClient()
    
    print("\n📊 10-Year Government Bond Yields")
    print("-" * 40)
    
    bonds = [
        ('Canada', 'boc_get_bond_yield'),
        ('Japan (JGB)', 'boj_get_jgb_yield'),
        ('France (OAT)', 'bdf_get_oat_yield'),
    ]
    
    for name, method in bonds:
        try:
            yield_data = getattr(client, method)('10Y')
            print(f"   {name}: {yield_data.get('yield', 'N/A')}%")
        except Exception as e:
            print(f"   {name}: Error")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Central Banks Tools Examples v2.3.0")
    print("=" * 60)
    
    example_boc_overview()
    example_boj_overview()
    example_pboc_overview()
    example_global_central_bank_dashboard()
    example_bond_yields_comparison()
