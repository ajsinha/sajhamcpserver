#!/usr/bin/env python3
"""
SAJHA MCP Server - Yahoo Finance Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Yahoo Finance tools:
- yahoo_get_quote: Get stock quote
- yahoo_get_history: Get historical data
- yahoo_search_symbols: Search for symbols

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.yahoo_finance_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class YahooFinanceClient(SajhaClient):
    """Client for Yahoo Finance tools."""
    
    def get_quote(self, symbol: str) -> dict:
        """
        Get current stock quote.
        
        Args:
            symbol: Stock ticker symbol (e.g., AAPL, MSFT)
        """
        return self.execute_tool('yahoo_get_quote', {'symbol': symbol})
    
    def get_history(self, 
                    symbol: str, 
                    period: str = '1mo',
                    interval: str = '1d') -> dict:
        """
        Get historical price data.
        
        Args:
            symbol: Stock ticker symbol
            period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max)
            interval: Data interval (1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo)
        """
        return self.execute_tool('yahoo_get_history', {
            'symbol': symbol,
            'period': period,
            'interval': interval
        })
    
    def search_symbols(self, query: str, limit: int = 10) -> dict:
        """
        Search for stock symbols.
        
        Args:
            query: Search query (company name or symbol)
            limit: Maximum results
        """
        return self.execute_tool('yahoo_search_symbols', {
            'query': query,
            'limit': limit
        })


@run_example
def example_get_quote():
    """Example: Get stock quote"""
    client = YahooFinanceClient()
    
    symbols = ['AAPL', 'MSFT', 'GOOGL']
    print("\n💹 Getting stock quotes...")
    
    for symbol in symbols:
        quote = client.get_quote(symbol)
        pretty_print(quote, f"Quote: {symbol}")


@run_example
def example_get_history():
    """Example: Get historical data"""
    client = YahooFinanceClient()
    
    print("\n📈 Getting AAPL historical data (1 month)...")
    history = client.get_history('AAPL', period='1mo', interval='1d')
    pretty_print(history, "AAPL Historical Data")


@run_example
def example_search_symbols():
    """Example: Search for symbols"""
    client = YahooFinanceClient()
    
    print("\n🔍 Searching for 'Tesla'...")
    results = client.search_symbols('Tesla', limit=5)
    pretty_print(results, "Symbol Search Results")


@run_example
def example_portfolio_analysis():
    """Example: Portfolio analysis workflow"""
    client = YahooFinanceClient()
    
    portfolio = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META']
    print(f"\n📊 Portfolio Analysis: {', '.join(portfolio)}")
    
    total_value = 0
    print("\n" + "-" * 50)
    print(f"{'Symbol':<8} {'Price':>12} {'Change':>12} {'% Change':>10}")
    print("-" * 50)
    
    for symbol in portfolio:
        try:
            quote = client.get_quote(symbol)
            price = quote.get('regularMarketPrice', 0)
            change = quote.get('regularMarketChange', 0)
            pct_change = quote.get('regularMarketChangePercent', 0)
            
            print(f"{symbol:<8} ${price:>10.2f} {change:>+11.2f} {pct_change:>+9.2f}%")
            total_value += price
        except Exception as e:
            print(f"{symbol:<8} Error: {e}")
    
    print("-" * 50)
    print(f"Total Portfolio Value (1 share each): ${total_value:.2f}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Yahoo Finance Tools Examples v2.2.0")
    print("=" * 60)
    
    example_get_quote()
    example_get_history()
    example_search_symbols()
    example_portfolio_analysis()
