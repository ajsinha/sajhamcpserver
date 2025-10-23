# Yahoo Finance MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The Yahoo Finance MCP Tool provides real-time and historical financial market data including stock prices, company information, financial statements, and market indices.

## Configuration
- No API key required
- Uses yfinance Python library
- Real-time market data during trading hours
- Historical data available for most securities

## Available Methods

### Stock Information

#### 1. get_stock_price
Get current stock price.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Current price, currency, change
- Day high/low, volume
- Market capitalization
- Previous close, open price

#### 2. get_stock_info
Get comprehensive stock information.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Company details (name, sector, industry, country)
- Valuation metrics (P/E, P/B, PEG ratio)
- Financial metrics (margins, ROE, ROA)
- 52-week high/low
- Moving averages (50-day, 200-day)
- Dividend information

### Historical Data

#### 3. get_historical_data
Get historical price data.
**Parameters:**
- `symbol`: Stock ticker symbol (required)
- `period` (default: '1mo'): '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'
- `interval` (default: '1d'): '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo'
- `start_date` (optional): Start date for custom range
- `end_date` (optional): End date for custom range

**Returns:**
- OHLC (Open, High, Low, Close) data
- Volume
- Date/timestamp for each data point

### Financial Statements

#### 4. get_financials
Get financial statements.
**Parameters:**
- `symbol`: Stock ticker symbol (required)
- `quarterly` (default: False): Annual or quarterly data

**Returns:**
- Income statement items
- Revenue, expenses, earnings
- Operating metrics

#### 5. get_balance_sheet
Get balance sheet data.
**Parameters:**
- `symbol`: Stock ticker symbol (required)
- `quarterly` (default: False): Annual or quarterly data

**Returns:**
- Assets, liabilities, equity
- Working capital items
- Long-term assets and debt

#### 6. get_cash_flow
Get cash flow statement data.
**Parameters:**
- `symbol`: Stock ticker symbol (required)
- `quarterly` (default: False): Annual or quarterly data

**Returns:**
- Operating cash flow
- Investing cash flow
- Financing cash flow
- Free cash flow

### Corporate Actions

#### 7. get_dividends
Get dividend history.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Dividend payment dates
- Dividend amounts
- Historical dividend data

#### 8. get_splits
Get stock split history.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Split dates
- Split ratios
- Historical split data

#### 9. get_actions
Get corporate actions (dividends, splits, etc.).
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Combined dividend and split history
- Action dates and types

### Analyst Information

#### 10. get_recommendations
Get analyst recommendations.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Recent analyst recommendations
- Firm names
- Grade changes (upgrades/downgrades)
- Action taken

#### 11. get_earnings
Get earnings data.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Earnings dates
- EPS estimates vs actual
- Earnings history

### Ownership Information

#### 12. get_institutional_holders
Get institutional holders information.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Major institutional holders
- Number of shares held
- Value of holdings
- Percentage ownership

### Options Data

#### 13. get_options
Get options chain data.
**Parameters:**
- `symbol`: Stock ticker symbol (required)
- `expiration_date` (optional): Specific expiration date

**Returns:**
- Available expiration dates
- Call options data
- Put options data
- Strike prices, volumes, open interest
- Implied volatility

### News

#### 14. get_news
Get recent news for a stock.
**Parameters:**
- `symbol`: Stock ticker symbol (required)

**Returns:**
- Recent news articles (limited to 10)
- Article titles and links
- Publishers
- Publication dates

### Market Data

#### 15. get_market_summary
Get market summary for major indices.
**Parameters:**
- `indices` (default: ['^GSPC', '^DJI', '^IXIC', '^RUT']): List of index symbols

**Returns:**
- S&P 500, Dow Jones, Nasdaq, Russell 2000
- Current prices
- Changes and percentage changes
- Volume

#### 16. search_symbols
Search for stock symbols.
**Parameters:**
- `query`: Search query (required)

**Returns:**
- Matching symbols (limited functionality)

#### 17. get_trending_tickers
Get trending tickers.
**Returns:**
- Currently trending symbols (limited functionality)

#### 18. get_sector_performance
Get sector performance data.
**Returns:**
- Performance of major sector ETFs
- Technology (XLK)
- Healthcare (XLV)
- Financials (XLF)
- Consumer Discretionary (XLY)
- Communication (XLC)
- Industrials (XLI)
- Consumer Staples (XLP)
- Energy (XLE)
- Utilities (XLU)
- Real Estate (XLRE)
- Materials (XLB)

## Data Format Examples

### Stock Price Response
```json
{
  "symbol": "AAPL",
  "price": 150.25,
  "currency": "USD",
  "change": 2.50,
  "change_percent": 1.69,
  "previous_close": 147.75,
  "open": 148.00,
  "day_high": 151.00,
  "day_low": 147.50,
  "volume": 75000000,
  "market_cap": 2500000000000,
  "timestamp": "2024-01-15T16:00:00"
}
```

### Historical Data Response
```json
{
  "symbol": "AAPL",
  "period": "1mo",
  "interval": "1d",
  "data_points": 22,
  "data": [
    {
      "date": "2024-01-15",
      "open": 148.00,
      "high": 151.00,
      "low": 147.50,
      "close": 150.25,
      "volume": 75000000
    }
  ]
}
```

## Example Usage
```python
# Get current stock price
result = yf_tool.handle_tool_call('get_stock_price', {
    'symbol': 'AAPL'
})

# Get historical data
result = yf_tool.handle_tool_call('get_historical_data', {
    'symbol': 'MSFT',
    'period': '3mo',
    'interval': '1d'
})

# Get financial statements
result = yf_tool.handle_tool_call('get_financials', {
    'symbol': 'GOOGL',
    'quarterly': True
})

# Get options chain
result = yf_tool.handle_tool_call('get_options', {
    'symbol': 'TSLA'
})
```

## Limitations

- Some features like symbol search and trending tickers have limited functionality
- Real-time data may have slight delays
- Some international markets may have limited coverage
- Options data availability varies by security



## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.