# SAJHA MCP Server - Python API Clients

**Copyright All Rights Reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**

---

Comprehensive Python clients for accessing Wikipedia and Yahoo Finance tools via the SAJHA MCP Server API.

## Table of Contents
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Files Included](#files-included)
- [Prerequisites](#prerequisites)
- [Authentication](#authentication)
- [Wikipedia Client](#wikipedia-client)
- [Yahoo Finance Client](#yahoo-finance-client)
- [Complete Examples](#complete-examples)
- [Common Use Cases](#common-use-cases)
- [Error Handling](#error-handling)
- [Running Examples](#running-examples)
- [Configuration](#configuration)
- [Tips and Best Practices](#tips-and-best-practices)
- [Support](#support)

---

## Quick Start

Get started in 30 seconds with either client!

### Wikipedia Client - 30 Second Start

```python
from wikipedia_client import WikipediaClient

# Login
client = WikipediaClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Search
results = client.search("machine learning")

# Get summary
summary = client.get_summary(query="Python (programming language)")
print(summary['summary'])

# Get full article
page = client.get_page(query="Artificial Intelligence")
print(page['content'][:500])
```

### Yahoo Finance Client - 30 Second Start

```python
from yahoo_finance_client import YahooFinanceClient

# Login
client = YahooFinanceClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Get quote
quote = client.get_quote("AAPL")
print(f"Price: ${quote['price']:.2f}")

# Get history
history = client.get_history("TSLA", period="1mo")
print(f"Data points: {len(history['history'])}")

# Search symbols
results = client.search_symbols("Apple")
print(results['results'][0]['symbol'])
```

### Run Demo Script

```bash
python demo.py
```

---

## Installation

```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install requests
```

---

## Files Included

1. **wikipedia_client.py** - Wikipedia tools client
2. **yahoo_finance_client.py** - Yahoo Finance tools client
3. **demo.py** - Comprehensive demo script with 5 real-world examples
4. **README.md** - This documentation file
5. **requirements.txt** - Python dependencies

---

## Prerequisites

- Python 3.7 or higher
- `requests` library

---

## Authentication

Both clients require authentication with the SAJHA MCP Server. You can authenticate in two ways:

### Method 1: During Initialization
```python
from wikipedia_client import WikipediaClient

client = WikipediaClient(
    base_url="http://localhost:5000",
    user_id="your_user_id",
    password="your_password"
)
```

### Method 2: After Initialization
```python
from wikipedia_client import WikipediaClient

client = WikipediaClient(base_url="http://localhost:5000")
client.login("your_user_id", "your_password")
```

---

## Wikipedia Client

### Overview

The Wikipedia client provides access to three powerful tools:
- **search()** - Search Wikipedia articles by keyword
- **get_page()** - Retrieve complete article content
- **get_summary()** - Get concise article summaries

### Quick Start Example
```python
from wikipedia_client import WikipediaClient

# Initialize and authenticate
client = WikipediaClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Search for articles
results = client.search("artificial intelligence", limit=10)
client.print_search_results(results)

# Get article summary
summary = client.get_summary(query="Machine Learning", sentences=5)
client.print_summary(summary)

# Get complete article
page = client.get_page(query="Python (programming language)")
print(f"Title: {page['title']}")
print(f"Word Count: {page['word_count']}")
print(f"Content: {page['content'][:500]}...")
```

### Available Methods

#### 1. `search(query, limit=5, language='en')`
Search Wikipedia articles by keyword or phrase.

**Parameters:**
- `query` (str): Search query
- `limit` (int): Maximum number of results (1-20, default: 5)
- `language` (str): Language edition (e.g., 'en', 'es', 'fr')

**Returns:**
- Dict containing query, language, result_count, results list, suggestion, and timestamp

**Example:**
```python
results = client.search("quantum computing", limit=10)
results = client.search("inteligencia artificial", language="es")
```

#### 2. `get_page(query=None, page_id=None, language='en', ...)`
Retrieve complete Wikipedia article content.

**Parameters:**
- `query` (str): Article title
- `page_id` (int): Wikipedia page ID (alternative to query)
- `language` (str): Language edition
- `redirect` (bool): Follow redirects (default: True)
- `include_images` (bool): Include images (default: True)
- `include_links` (bool): Include links (default: True)
- `include_references` (bool): Include references (default: False)

**Returns:**
- Dict containing title, page_id, url, language, content, summary, sections, images, links, references, categories, last_modified, word_count

**Example:**
```python
page = client.get_page(query="Artificial Intelligence")
page = client.get_page(page_id=5043734)
page = client.get_page(query="Python", include_references=True)
```

#### 3. `get_summary(query=None, page_id=None, sentences=3, ...)`
Retrieve concise article summary.

**Parameters:**
- `query` (str): Article title
- `page_id` (int): Wikipedia page ID
- `language` (str): Language edition
- `sentences` (int): Number of sentences (1-10, default: 3)
- `redirect` (bool): Follow redirects
- `include_image` (bool): Include thumbnail

**Returns:**
- Dict containing title, page_id, url, language, summary, extract, thumbnail, coordinates, description

**Example:**
```python
summary = client.get_summary(query="Machine Learning", sentences=5)
summary = client.get_summary(query="Mount Everest", include_image=True)
```

---

## Yahoo Finance Client

### Overview

The Yahoo Finance client provides access to:
- **get_quote()** - Real-time stock quotes
- **get_history()** - Historical price data
- **search_symbols()** - Search for stock symbols
- **get_multiple_quotes()** - Batch quote retrieval

### Quick Start Example
```python
from yahoo_finance_client import YahooFinanceClient

# Initialize and authenticate
client = YahooFinanceClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Get stock quote
quote = client.get_quote("AAPL")
client.print_quote(quote)

# Get historical data
history = client.get_history("TSLA", period="1y", interval="1d")
client.print_history_summary(history)

# Search for symbols
results = client.search_symbols("electric vehicle", limit=10)
client.print_search_results(results)
```

### Available Methods

#### 1. `get_quote(symbol)`
Retrieve real-time stock quote data.

**Parameters:**
- `symbol` (str): Stock ticker symbol (e.g., AAPL, GOOGL, ^GSPC)

**Returns:**
- Dict containing symbol, name, price, currency, change, change_percent, volume, avg_volume, market_cap, pe_ratio, dividend_yield, 52-week high/low, day high/low, open, previous_close

**Example:**
```python
quote = client.get_quote("AAPL")
quote = client.get_quote("^GSPC")  # S&P 500 index
print(f"Price: ${quote['price']:.2f}")
print(f"Change: {quote['change_percent']:.2f}%")
```

#### 2. `get_history(symbol, period='1mo', interval='1d', include_events=True)`
Retrieve historical price and volume data.

**Parameters:**
- `symbol` (str): Stock ticker symbol
- `period` (str): Time period
  - Options: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
- `interval` (str): Data interval
  - Options: '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo'
- `include_events` (bool): Include dividends and splits

**Returns:**
- Dict containing symbol, period, interval, data_points, history array, dividends, splits, currency

**Example:**
```python
# Get 1 year of daily data
history = client.get_history("AAPL", period="1y", interval="1d")

# Get 1 month of hourly data
history = client.get_history("TSLA", period="1mo", interval="1h")

# Get today's 5-minute data
history = client.get_history("GOOGL", period="1d", interval="5m")
```

#### 3. `search_symbols(query, limit=10, exchange='all')`
Search for stock symbols by name, ticker, or keyword.

**Parameters:**
- `query` (str): Search query
- `limit` (int): Maximum results (1-50, default: 10)
- `exchange` (str): Filter by exchange
  - Options: 'NYSE', 'NASDAQ', 'AMEX', 'LSE', 'TSX', 'all'

**Returns:**
- Dict containing query, result_count, results list with symbol, name, exchange, type, sector, industry, market_cap

**Example:**
```python
results = client.search_symbols("Apple")
results = client.search_symbols("electric vehicle", limit=20)
results = client.search_symbols("semiconductor", exchange="NASDAQ")
```

#### 4. `get_multiple_quotes(symbols)`
Get quotes for multiple symbols at once.

**Parameters:**
- `symbols` (list): List of ticker symbols

**Returns:**
- Dict mapping symbols to their quote data

**Example:**
```python
symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "META"]
quotes = client.get_multiple_quotes(symbols)

for symbol, quote in quotes.items():
    if quote:
        print(f"{symbol}: ${quote['price']:.2f} ({quote['change_percent']:+.2f}%)")
```

---

## Complete Examples

### Wikipedia Example
```python
from wikipedia_client import WikipediaClient

# Initialize
client = WikipediaClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Search and explore
search_results = client.search("machine learning", limit=5)
for article in search_results['results']:
    print(f"- {article['title']}")
    
    # Get summary for each result
    summary = client.get_summary(query=article['title'], sentences=2)
    print(f"  {summary['summary']}")
    print()
```

### Yahoo Finance Example
```python
from yahoo_finance_client import YahooFinanceClient

# Initialize
client = YahooFinanceClient(
    base_url="http://localhost:5000",
    user_id="admin",
    password="admin123"
)

# Monitor portfolio
portfolio = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
quotes = client.get_multiple_quotes(portfolio)

total_value = 0
for symbol, quote in quotes.items():
    if quote and quote.get('price'):
        shares = 10  # Assume 10 shares each
        value = quote['price'] * shares
        total_value += value
        
        print(f"{symbol}: {shares} shares @ ${quote['price']:.2f} = ${value:,.2f}")

print(f"\nTotal Portfolio Value: ${total_value:,.2f}")
```

### Combined Example: Research Company
```python
from wikipedia_client import WikipediaClient
from yahoo_finance_client import YahooFinanceClient

# Initialize both clients
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

company = "Tesla"

# Get company information from Wikipedia
print(f"Researching: {company}")
print("="*80)

wiki_summary = wiki.get_summary(query=f"{company} Inc", sentences=3)
print(f"\nWikipedia Summary:")
print(wiki_summary['summary'])

# Get stock information from Yahoo Finance
ticker_results = yahoo.search_symbols(company, limit=1)
if ticker_results['results']:
    symbol = ticker_results['results'][0]['symbol']
    
    # Current quote
    quote = yahoo.get_quote(symbol)
    print(f"\nStock Quote ({symbol}):")
    print(f"Price: ${quote['price']:,.2f}")
    print(f"Change: {quote['change_percent']:+.2f}%")
    print(f"Market Cap: ${quote['market_cap']/1e9:,.2f}B")
    
    # Historical performance
    history = yahoo.get_history(symbol, period="1y", interval="1d")
    print(f"\n1-Year Performance:")
    print(f"Data Points: {history['data_points']}")
    
    first_close = history['history'][0]['close']
    last_close = history['history'][-1]['close']
    year_return = ((last_close - first_close) / first_close) * 100
    print(f"1-Year Return: {year_return:+.2f}%")
```

---

## Common Use Cases

### Research a Company
```python
from wikipedia_client import WikipediaClient
from yahoo_finance_client import YahooFinanceClient

wiki = WikipediaClient("http://localhost:5000", "admin", "admin123")
yahoo = YahooFinanceClient("http://localhost:5000", "admin", "admin123")

# Wikipedia info
summary = wiki.get_summary(query="Tesla Inc")
print(summary['summary'])

# Stock info
quote = yahoo.get_quote("TSLA")
print(f"Price: ${quote['price']:.2f} ({quote['change_percent']:+.2f}%)")
```

### Monitor Portfolio
```python
from yahoo_finance_client import YahooFinanceClient

client = YahooFinanceClient("http://localhost:5000", "admin", "admin123")

portfolio = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
quotes = client.get_multiple_quotes(portfolio)

for symbol, quote in quotes.items():
    if quote:
        print(f"{symbol}: ${quote['price']:.2f} ({quote['change_percent']:+.2f}%)")
```

### Compare Technologies
```python
from wikipedia_client import WikipediaClient

client = WikipediaClient("http://localhost:5000", "admin", "admin123")

topics = ["Machine Learning", "Blockchain", "Quantum Computing"]

for topic in topics:
    summary = client.get_summary(query=topic, sentences=2)
    print(f"\n{topic}:")
    print(summary['summary'])
```

---

## Error Handling

Both clients raise exceptions for various error conditions. Always use try-except blocks:

```python
try:
    quote = client.get_quote("AAPL")
    print(f"Price: ${quote['price']:.2f}")
except Exception as e:
    print(f"Error: {e}")
```

### Common Errors
- Authentication failed
- Invalid token / session expired
- Tool not found
- Access denied
- Invalid arguments
- Network errors

---

## Running Examples

Each client file includes a `main()` function with comprehensive examples:

```bash
# Run Wikipedia client examples
python wikipedia_client.py

# Run Yahoo Finance client examples
python yahoo_finance_client.py

# Run comprehensive demo script
python demo.py
```

---

## Configuration

### Change Server URL
```python
client = WikipediaClient(base_url="http://your-server:5000")
```

### Re-authenticate
```python
client.login("new_user_id", "new_password")
```

---

## Tips and Best Practices

1. **Cache authentication token**: Store the token for reuse
2. **Handle rate limits**: Be mindful of API rate limits
3. **Error handling**: Always wrap API calls in try-except blocks
4. **Timeouts**: Requests have 30-second timeout by default
5. **Data validation**: Check for None values in responses
6. **Use helper methods**: Both clients include `print_*()` methods for formatted output
7. **Batch operations**: Use `get_multiple_quotes()` for portfolio monitoring
8. **Language support**: Wikipedia client supports multiple language editions

---

## Support

For issues or questions about:
- **SAJHA MCP Server**: Contact system administrator
- **API endpoints**: Check `/api/tools/list` endpoint
- **Tool schemas**: Check `/api/tools/<tool_name>/schema` endpoint

### Additional Resources
- View available tools: `GET http://localhost:5000/api/tools/list`
- Get tool schema: `GET http://localhost:5000/api/tools/<tool_name>/schema`
- Server health: `GET http://localhost:5000/health`

---

## License

**Copyright All Rights Reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**

All rights reserved. This software and associated documentation files are provided for use with the SAJHA MCP Server.
