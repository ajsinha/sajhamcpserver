"""
SAJHA MCP Server - Yahoo Finance Client
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

This client provides programmatic access to Yahoo Finance tools via the SAJHA MCP Server API.
Includes authentication and all Yahoo Finance tool operations:
- yahoo_get_quote: Get real-time stock quotes
- yahoo_get_history: Get historical price and volume data
- yahoo_search_symbols: Search for stock symbols and companies
"""

import json
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime


class YahooFinanceClient:
    """Client for Yahoo Finance tools via SAJHA MCP Server API"""
    
    def __init__(self, base_url: str = "http://localhost:5000", user_id: str = None, password: str = None):
        """
        Initialize Yahoo Finance client
        
        Args:
            base_url: Base URL of the SAJHA MCP Server (default: http://localhost:5000)
            user_id: User ID for authentication (optional, can login later)
            password: Password for authentication (optional, can login later)
        """
        self.base_url = base_url.rstrip('/')
        self.token = None
        self.user_info = None
        
        # Auto-login if credentials provided
        if user_id and password:
            self.login(user_id, password)
    
    def login(self, user_id: str, password: str) -> Dict[str, Any]:
        """
        Authenticate with the SAJHA MCP Server
        
        Args:
            user_id: User ID
            password: User password
            
        Returns:
            Dict containing token and user information
            
        Raises:
            Exception: If authentication fails
        """
        url = f"{self.base_url}/api/auth/login"
        payload = {
            "user_id": user_id,
            "password": password
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self.token = data.get('token')
            self.user_info = data.get('user')
            
            print(f"✓ Successfully authenticated as {self.user_info.get('user_name')}")
            return data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise Exception("Authentication failed: Invalid credentials")
            else:
                raise Exception(f"Authentication failed: HTTP {e.response.status_code}")
        except Exception as e:
            raise Exception(f"Authentication failed: {str(e)}")
    
    def _make_request(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make authenticated API request to execute a tool
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            Exception: If request fails or user is not authenticated
        """
        if not self.token:
            raise Exception("Not authenticated. Please call login() first.")
        
        url = f"{self.base_url}/api/tools/execute"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "tool": tool_name,
            "arguments": arguments
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('success'):
                return data.get('result')
            else:
                raise Exception(f"Tool execution failed: {data.get('error')}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise Exception("Authentication failed: Invalid or expired token")
            elif e.response.status_code == 403:
                raise Exception(f"Access denied: You don't have permission to use {tool_name}")
            elif e.response.status_code == 404:
                raise Exception(f"Tool not found: {tool_name}")
            else:
                raise Exception(f"Request failed: HTTP {e.response.status_code}")
        except Exception as e:
            raise Exception(f"Request failed: {str(e)}")
    
    # ==================== Get Stock Quote ====================
    
    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieve real-time stock quote data
        
        Args:
            symbol: Stock ticker symbol (e.g., AAPL, GOOGL, MSFT, TSLA, ^GSPC for S&P 500)
            
        Returns:
            Dict containing:
                - symbol: Stock ticker symbol
                - name: Company or security name
                - price: Current/latest price
                - currency: Currency of the price
                - change: Price change from previous close
                - change_percent: Percentage change from previous close
                - volume: Trading volume
                - avg_volume: Average trading volume
                - market_cap: Market capitalization
                - pe_ratio: Price-to-earnings ratio
                - dividend_yield: Dividend yield percentage
                - fifty_two_week_high: 52-week high price
                - fifty_two_week_low: 52-week low price
                - day_high: Today's high price
                - day_low: Today's low price
                - open: Opening price
                - previous_close: Previous closing price
                - last_updated: Timestamp of last update
                
        Example:
            >>> client.get_quote("AAPL")
            >>> client.get_quote("GOOGL")
            >>> client.get_quote("^GSPC")  # S&P 500 index
        """
        arguments = {
            "symbol": symbol.upper()
        }
        return self._make_request("yahoo_get_quote", arguments)
    
    # ==================== Get Historical Data ====================
    
    def get_history(self,
                    symbol: str,
                    period: str = "1mo",
                    interval: str = "1d",
                    include_events: bool = True) -> Dict[str, Any]:
        """
        Retrieve historical price and volume data for a stock
        
        Args:
            symbol: Stock ticker symbol (e.g., AAPL, GOOGL, MSFT)
            period: Time period for historical data
                    Options: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
                    Default: '1mo'
            interval: Data interval/granularity
                      Options: '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo'
                      Default: '1d'
            include_events: Include dividend and split events (default: True)
            
        Returns:
            Dict containing:
                - symbol: Stock ticker symbol
                - period: Time period requested
                - interval: Data interval used
                - data_points: Number of historical data points returned
                - history: List of historical data with date, open, high, low, close, volume, adjusted_close
                - dividends: Dividend events during the period (if include_events=True)
                - splits: Stock split events during the period (if include_events=True)
                - currency: Currency of prices
                - last_updated: Timestamp
                
        Example:
            >>> client.get_history("AAPL", period="1y", interval="1d")
            >>> client.get_history("TSLA", period="1mo", interval="1h")
            >>> client.get_history("GOOGL", period="1d", interval="5m")
        """
        arguments = {
            "symbol": symbol.upper(),
            "period": period,
            "interval": interval,
            "include_events": include_events
        }
        return self._make_request("yahoo_get_history", arguments)
    
    # ==================== Search Stock Symbols ====================
    
    def search_symbols(self,
                      query: str,
                      limit: int = 10,
                      exchange: str = "all") -> Dict[str, Any]:
        """
        Search for stock symbols and companies by name, ticker, or keyword
        
        Args:
            query: Search query - company name, ticker symbol, or keyword
            limit: Maximum number of results to return (1-50, default: 10)
            exchange: Filter by exchange
                      Options: 'NYSE', 'NASDAQ', 'AMEX', 'LSE', 'TSX', 'all'
                      Default: 'all'
            
        Returns:
            Dict containing:
                - query: Original search query
                - result_count: Number of results returned
                - results: List of matching securities with:
                    - symbol: Stock ticker symbol
                    - name: Company or security name
                    - exchange: Stock exchange
                    - type: Security type (EQUITY, ETF, INDEX, etc.)
                    - sector: Industry sector
                    - industry: Specific industry
                    - market_cap: Market capitalization
                - last_updated: Timestamp
                
        Example:
            >>> client.search_symbols("Apple")
            >>> client.search_symbols("electric vehicle", limit=20)
            >>> client.search_symbols("semiconductor", exchange="NASDAQ", limit=15)
        """
        arguments = {
            "query": query,
            "limit": limit,
            "exchange": exchange
        }
        return self._make_request("yahoo_search_symbols", arguments)
    
    # ==================== Utility Methods ====================
    
    def print_quote(self, quote: Dict[str, Any]):
        """
        Pretty print stock quote data
        
        Args:
            quote: Quote result from get_quote() method
        """
        print(f"\n{'='*80}")
        print(f"{quote['name']} ({quote['symbol']})")
        print(f"{'='*80}")
        
        # Price information
        price = quote.get('price')
        change = quote.get('change')
        change_percent = quote.get('change_percent')
        
        if price:
            price_str = f"${price:,.2f} {quote['currency']}"
            if change and change_percent:
                direction = "▲" if change >= 0 else "▼"
                color = "+" if change >= 0 else ""
                print(f"Price: {price_str} {direction} {color}{change:.2f} ({color}{change_percent:.2f}%)")
            else:
                print(f"Price: {price_str}")
        
        # Trading information
        if quote.get('volume'):
            print(f"Volume: {quote['volume']:,}")
        if quote.get('avg_volume'):
            print(f"Avg Volume: {quote['avg_volume']:,}")
        
        # Day range
        day_low = quote.get('day_low')
        day_high = quote.get('day_high')
        if day_low and day_high:
            print(f"Day Range: ${day_low:,.2f} - ${day_high:,.2f}")
        
        # 52-week range
        week_low = quote.get('fifty_two_week_low')
        week_high = quote.get('fifty_two_week_high')
        if week_low and week_high:
            print(f"52-Week Range: ${week_low:,.2f} - ${week_high:,.2f}")
        
        # Market metrics
        if quote.get('market_cap'):
            market_cap_b = quote['market_cap'] / 1_000_000_000
            print(f"Market Cap: ${market_cap_b:,.2f}B")
        
        if quote.get('pe_ratio'):
            print(f"P/E Ratio: {quote['pe_ratio']:.2f}")
        
        if quote.get('dividend_yield'):
            print(f"Dividend Yield: {quote['dividend_yield']*100:.2f}%")
        
        if quote.get('open'):
            print(f"Open: ${quote['open']:.2f}")
        
        if quote.get('previous_close'):
            print(f"Previous Close: ${quote['previous_close']:.2f}")
        
        print(f"\nLast Updated: {quote['last_updated']}")
        print(f"{'='*80}\n")
    
    def print_history_summary(self, history: Dict[str, Any], show_data_points: int = 5):
        """
        Pretty print historical data summary
        
        Args:
            history: History result from get_history() method
            show_data_points: Number of recent data points to display (default: 5)
        """
        print(f"\n{'='*80}")
        print(f"Historical Data: {history['symbol']}")
        print(f"{'='*80}")
        print(f"Period: {history['period']}")
        print(f"Interval: {history['interval']}")
        print(f"Total Data Points: {history['data_points']}")
        print(f"Currency: {history['currency']}")
        
        # Show recent data points
        if history['history']:
            print(f"\n{'Most Recent Data Points:':-^80}")
            print(f"{'Date':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>15}")
            print("-" * 80)
            
            for dp in history['history'][-show_data_points:]:
                date_str = dp['date'][:10] if len(dp['date']) > 10 else dp['date']
                open_val = f"${dp['open']:.2f}" if dp['open'] else "N/A"
                high_val = f"${dp['high']:.2f}" if dp['high'] else "N/A"
                low_val = f"${dp['low']:.2f}" if dp['low'] else "N/A"
                close_val = f"${dp['close']:.2f}" if dp['close'] else "N/A"
                volume_val = f"{dp['volume']:,}" if dp['volume'] else "N/A"
                
                print(f"{date_str:<20} {open_val:>10} {high_val:>10} {low_val:>10} {close_val:>10} {volume_val:>15}")
        
        # Show events
        if history.get('dividends'):
            print(f"\n{'Dividends:':-^80}")
            for div in history['dividends']:
                print(f"  {div['date'][:10]}: ${div['amount']:.4f}")
        
        if history.get('splits'):
            print(f"\n{'Splits:':-^80}")
            for split in history['splits']:
                print(f"  {split['date'][:10]}: {split['ratio']}")
        
        print(f"\n{'='*80}\n")
    
    def print_search_results(self, results: Dict[str, Any]):
        """
        Pretty print symbol search results
        
        Args:
            results: Search results from search_symbols() method
        """
        print(f"\n{'='*80}")
        print(f"Search Results for: '{results['query']}'")
        print(f"Found {results['result_count']} results")
        print(f"{'='*80}\n")
        
        for i, stock in enumerate(results['results'], 1):
            print(f"{i}. {stock['name']} ({stock['symbol']})")
            print(f"   Exchange: {stock['exchange']}")
            print(f"   Type: {stock['type']}")
            
            if stock.get('sector'):
                print(f"   Sector: {stock['sector']}")
            
            if stock.get('industry'):
                print(f"   Industry: {stock['industry']}")
            
            if stock.get('market_cap'):
                market_cap_b = stock['market_cap'] / 1_000_000_000
                print(f"   Market Cap: ${market_cap_b:,.2f}B")
            
            print()
        
        print(f"{'='*80}\n")
    
    def get_multiple_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get quotes for multiple symbols
        
        Args:
            symbols: List of stock ticker symbols
            
        Returns:
            Dict mapping symbols to their quote data
            
        Example:
            >>> client.get_multiple_quotes(["AAPL", "GOOGL", "MSFT", "TSLA"])
        """
        results = {}
        for symbol in symbols:
            try:
                results[symbol] = self.get_quote(symbol)
            except Exception as e:
                print(f"Error getting quote for {symbol}: {e}")
                results[symbol] = None
        return results


# ==================== Example Usage ====================

def main():
    """Example usage of Yahoo Finance client"""
    
    # Initialize client (replace with your credentials)
    client = YahooFinanceClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    print("\n" + "="*80)
    print("YAHOO FINANCE CLIENT - EXAMPLE USAGE")
    print("="*80)
    
    # Example 1: Get stock quote
    print("\n1. GETTING STOCK QUOTE FOR APPLE (AAPL)")
    print("-" * 80)
    try:
        quote = client.get_quote("AAPL")
        client.print_quote(quote)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 2: Get historical data
    print("\n2. GETTING 1-YEAR HISTORICAL DATA FOR TESLA (TSLA)")
    print("-" * 80)
    try:
        history = client.get_history("TSLA", period="1y", interval="1d")
        client.print_history_summary(history, show_data_points=10)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 3: Search for symbols
    print("\n3. SEARCHING FOR 'ELECTRIC VEHICLE' COMPANIES")
    print("-" * 80)
    try:
        search_results = client.search_symbols("electric vehicle", limit=10)
        client.print_search_results(search_results)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 4: Get intraday data
    print("\n4. GETTING TODAY'S INTRADAY DATA (5-MINUTE INTERVALS)")
    print("-" * 80)
    try:
        intraday = client.get_history("GOOGL", period="1d", interval="5m")
        print(f"Symbol: {intraday['symbol']}")
        print(f"Data Points: {intraday['data_points']}")
        print(f"Period: {intraday['period']}")
        print(f"Interval: {intraday['interval']}")
        
        if intraday['history']:
            latest = intraday['history'][-1]
            print(f"\nLatest Data Point:")
            print(f"  Time: {latest['date']}")
            print(f"  Close: ${latest['close']:.2f}")
            print(f"  Volume: {latest['volume']:,}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 5: Get multiple quotes
    print("\n5. GETTING QUOTES FOR MULTIPLE TECH STOCKS")
    print("-" * 80)
    try:
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "META"]
        quotes = client.get_multiple_quotes(symbols)
        
        print(f"{'Symbol':<10} {'Price':>12} {'Change':>12} {'Market Cap':>15}")
        print("-" * 80)
        
        for symbol, quote in quotes.items():
            if quote:
                price = f"${quote['price']:,.2f}" if quote.get('price') else "N/A"
                change = f"{quote['change_percent']:+.2f}%" if quote.get('change_percent') else "N/A"
                market_cap = f"${quote['market_cap']/1e9:,.2f}B" if quote.get('market_cap') else "N/A"
                print(f"{symbol:<10} {price:>12} {change:>12} {market_cap:>15}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 6: Search by exchange
    print("\n6. SEARCHING NASDAQ-LISTED SEMICONDUCTOR COMPANIES")
    print("-" * 80)
    try:
        search_results = client.search_symbols("semiconductor", limit=10, exchange="NASDAQ")
        client.print_search_results(search_results)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 7: Get index quote
    print("\n7. GETTING S&P 500 INDEX QUOTE")
    print("-" * 80)
    try:
        sp500 = client.get_quote("^GSPC")
        client.print_quote(sp500)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
