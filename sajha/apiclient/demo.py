"""
SAJHA MCP Server - Demo Script
Demonstrates both Wikipedia and Yahoo Finance clients

This script shows practical examples of using both clients together
for research and financial analysis.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from wikipedia_client import WikipediaClient
from yahoo_finance_client import YahooFinanceClient


def demo_1_company_research():
    """Demo 1: Research a company using both Wikipedia and Yahoo Finance"""
    print("\n" + "="*80)
    print("DEMO 1: COMPANY RESEARCH - APPLE INC.")
    print("="*80)
    
    # Initialize clients
    wiki = WikipediaClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    yahoo = YahooFinanceClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    company_name = "Apple Inc"
    
    # Get Wikipedia information
    print(f"\n📚 Fetching Wikipedia information for {company_name}...")
    try:
        summary = wiki.get_summary(query=company_name, sentences=5)
        print(f"\nWikipedia Summary:")
        print("-" * 80)
        print(summary['summary'])
        print(f"\nFull article: {summary['url']}")
    except Exception as e:
        print(f"Error getting Wikipedia info: {e}")
    
    # Get stock information
    print(f"\n📈 Fetching stock information for AAPL...")
    try:
        quote = yahoo.get_quote("AAPL")
        yahoo.print_quote(quote)
        
        # Get historical data
        print("\n📊 Fetching 1-year historical data...")
        history = yahoo.get_history("AAPL", period="1y", interval="1d")
        
        # Calculate statistics
        closes = [h['close'] for h in history['history'] if h['close']]
        if closes:
            first_price = closes[0]
            last_price = closes[-1]
            year_return = ((last_price - first_price) / first_price) * 100
            
            print(f"1-Year Performance:")
            print(f"  Starting Price: ${first_price:.2f}")
            print(f"  Current Price: ${last_price:.2f}")
            print(f"  Return: {year_return:+.2f}%")
            
    except Exception as e:
        print(f"Error getting stock info: {e}")


def demo_2_technology_comparison():
    """Demo 2: Compare information about different technologies"""
    print("\n" + "="*80)
    print("DEMO 2: TECHNOLOGY COMPARISON")
    print("="*80)
    
    wiki = WikipediaClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    technologies = ["Machine Learning", "Blockchain", "Quantum Computing"]
    
    print("\n🔬 Comparing different technologies:")
    print("="*80)
    
    for tech in technologies:
        try:
            summary = wiki.get_summary(query=tech, sentences=2)
            print(f"\n{tech}:")
            print("-" * 80)
            print(summary['summary'])
        except Exception as e:
            print(f"\nError getting info for {tech}: {e}")


def demo_3_stock_portfolio():
    """Demo 3: Monitor a stock portfolio"""
    print("\n" + "="*80)
    print("DEMO 3: STOCK PORTFOLIO MONITORING")
    print("="*80)
    
    yahoo = YahooFinanceClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    # Define portfolio
    portfolio = {
        "AAPL": 10,   # 10 shares of Apple
        "GOOGL": 5,   # 5 shares of Google
        "MSFT": 8,    # 8 shares of Microsoft
        "TSLA": 3,    # 3 shares of Tesla
        "AMZN": 4     # 4 shares of Amazon
    }
    
    print("\n💼 Portfolio Summary:")
    print("="*80)
    print(f"{'Symbol':<10} {'Shares':>8} {'Price':>12} {'Value':>15} {'Change':>10}")
    print("-" * 80)
    
    total_value = 0
    total_cost = 0  # Hypothetical
    
    for symbol, shares in portfolio.items():
        try:
            quote = yahoo.get_quote(symbol)
            
            if quote and quote.get('price'):
                price = quote['price']
                value = price * shares
                change_pct = quote.get('change_percent', 0)
                
                total_value += value
                
                print(f"{symbol:<10} {shares:>8} ${price:>10,.2f} ${value:>13,.2f} {change_pct:>+9.2f}%")
        except Exception as e:
            print(f"{symbol:<10} Error: {e}")
    
    print("-" * 80)
    print(f"{'TOTAL':<10} {'':<8} {'':<12} ${total_value:>13,.2f}")
    print("="*80)


def demo_4_sector_research():
    """Demo 4: Research a specific sector"""
    print("\n" + "="*80)
    print("DEMO 4: SECTOR RESEARCH - ELECTRIC VEHICLES")
    print("="*80)
    
    wiki = WikipediaClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    yahoo = YahooFinanceClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    sector = "Electric Vehicle"
    
    # Get Wikipedia overview
    print(f"\n📚 Wikipedia Overview:")
    try:
        summary = wiki.get_summary(query=sector, sentences=3)
        print("-" * 80)
        print(summary['summary'])
    except Exception as e:
        print(f"Error: {e}")
    
    # Find companies in this sector
    print(f"\n📈 Finding {sector} Companies:")
    try:
        search_results = yahoo.search_symbols("electric vehicle", limit=5)
        
        print("-" * 80)
        print(f"{'Company':<30} {'Symbol':<10} {'Market Cap':<15}")
        print("-" * 80)
        
        for result in search_results['results']:
            name = result['name'][:28] if result['name'] else "N/A"
            symbol = result['symbol']
            market_cap = "N/A"
            
            if result.get('market_cap'):
                market_cap_b = result['market_cap'] / 1_000_000_000
                market_cap = f"${market_cap_b:.2f}B"
            
            print(f"{name:<30} {symbol:<10} {market_cap:<15}")
            
    except Exception as e:
        print(f"Error: {e}")


def demo_5_market_indices():
    """Demo 5: Monitor major market indices"""
    print("\n" + "="*80)
    print("DEMO 5: MAJOR MARKET INDICES")
    print("="*80)
    
    yahoo = YahooFinanceClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    indices = {
        "^GSPC": "S&P 500",
        "^DJI": "Dow Jones Industrial Average",
        "^IXIC": "NASDAQ Composite",
        "^RUT": "Russell 2000"
    }
    
    print("\n📊 Market Overview:")
    print("="*80)
    print(f"{'Index':<35} {'Symbol':<10} {'Price':>12} {'Change':>10}")
    print("-" * 80)
    
    for symbol, name in indices.items():
        try:
            quote = yahoo.get_quote(symbol)
            
            if quote and quote.get('price'):
                price = quote['price']
                change_pct = quote.get('change_percent', 0)
                direction = "▲" if change_pct >= 0 else "▼"
                
                print(f"{name:<35} {symbol:<10} {price:>12,.2f} {direction} {change_pct:>+8.2f}%")
        except Exception as e:
            print(f"{name:<35} {symbol:<10} Error: {e}")
    
    print("="*80)


def main():
    """Run all demos"""
    print("\n" + "="*80)
    print("SAJHA MCP SERVER - CLIENT DEMO")
    print("Demonstrating Wikipedia and Yahoo Finance Clients")
    print("="*80)
    
    try:
        # Run each demo
        demo_1_company_research()
        input("\n\nPress Enter to continue to next demo...")
        
        demo_2_technology_comparison()
        input("\n\nPress Enter to continue to next demo...")
        
        demo_3_stock_portfolio()
        input("\n\nPress Enter to continue to next demo...")
        
        demo_4_sector_research()
        input("\n\nPress Enter to continue to next demo...")
        
        demo_5_market_indices()
        
        print("\n" + "="*80)
        print("DEMO COMPLETED")
        print("="*80)
        
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
    except Exception as e:
        print(f"\n\nDemo error: {e}")


if __name__ == "__main__":
    # Note: Update the credentials before running
    print("\n⚠️  IMPORTANT: Update the user_id and password in the demo functions before running!")
    print("   Default credentials used: user_id='admin', password='admin123'")
    print("   Server URL: http://localhost:5000")
    print("\n   Press Ctrl+C to exit at any time.")
    
    input("\nPress Enter to start the demo...")
    main()
