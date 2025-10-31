"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Yahoo Finance MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List
from datetime import datetime, timedelta
from ..base_mcp_tool import BaseMCPTool

class YahooFinanceTool(BaseMCPTool):
    """
    Yahoo Finance stock market data retrieval tool
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Yahoo Finance tool"""
        default_config = {
            'name': 'yahoo_finance',
            'description': 'Retrieve stock market data from Yahoo Finance',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Yahoo Finance API endpoints (using free endpoints)
        self.quote_url = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
        self.search_url = "https://query1.finance.yahoo.com/v1/finance/search"
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Yahoo Finance tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["get_quote", "get_history", "search_symbols"]
                },
                "symbol": {
                    "type": "string",
                    "description": "Stock symbol (e.g., AAPL, GOOGL)"
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search_symbols)"
                },
                "period": {
                    "type": "string",
                    "description": "Time period for historical data",
                    "enum": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
                    "default": "1mo"
                },
                "interval": {
                    "type": "string",
                    "description": "Data interval",
                    "enum": ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"],
                    "default": "1d"
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Yahoo Finance tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Stock market data
        """
        action = arguments.get('action')
        
        if action == 'get_quote':
            symbol = arguments.get('symbol')
            if not symbol:
                raise ValueError("'symbol' is required for get_quote action")
            return self._get_quote(symbol)
            
        elif action == 'get_history':
            symbol = arguments.get('symbol')
            if not symbol:
                raise ValueError("'symbol' is required for get_history action")
            period = arguments.get('period', '1mo')
            interval = arguments.get('interval', '1d')
            return self._get_history(symbol, period, interval)
            
        elif action == 'search_symbols':
            query = arguments.get('query')
            if not query:
                raise ValueError("'query' is required for search_symbols action")
            return self._search_symbols(query)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_quote(self, symbol: str) -> Dict:
        """
        Get current stock quote
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Stock quote data
        """
        url = self.quote_url.format(symbol)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if 'chart' in data and 'result' in data['chart'] and data['chart']['result']:
                    result = data['chart']['result'][0]
                    meta = result.get('meta', {})
                    
                    # Get current price and other data
                    quote_data = {
                        'symbol': meta.get('symbol', symbol),
                        'currency': meta.get('currency', 'USD'),
                        'exchange': meta.get('exchangeName', ''),
                        'regularMarketPrice': meta.get('regularMarketPrice', 0),
                        'previousClose': meta.get('previousClose', 0),
                        'regularMarketOpen': meta.get('regularMarketOpen', 0),
                        'regularMarketDayHigh': meta.get('regularMarketDayHigh', 0),
                        'regularMarketDayLow': meta.get('regularMarketDayLow', 0),
                        'regularMarketVolume': meta.get('regularMarketVolume', 0),
                        'marketCap': meta.get('marketCap', 0),
                        'fiftyTwoWeekHigh': meta.get('fiftyTwoWeekHigh', 0),
                        'fiftyTwoWeekLow': meta.get('fiftyTwoWeekLow', 0),
                        'timestamp': datetime.fromtimestamp(meta.get('regularMarketTime', 0)).isoformat()
                    }
                    
                    # Calculate change and change percentage
                    if quote_data['previousClose'] > 0:
                        change = quote_data['regularMarketPrice'] - quote_data['previousClose']
                        change_percent = (change / quote_data['previousClose']) * 100
                        quote_data['change'] = round(change, 2)
                        quote_data['changePercent'] = round(change_percent, 2)
                    else:
                        quote_data['change'] = 0
                        quote_data['changePercent'] = 0
                    
                    return quote_data
                else:
                    raise ValueError(f"No data found for symbol: {symbol}")
                    
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Symbol not found: {symbol}")
            else:
                self.logger.error(f"Yahoo Finance API error: {e}")
                raise ValueError(f"Failed to get quote: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Yahoo Finance quote error: {e}")
            raise ValueError(f"Failed to get quote: {str(e)}")
    
    def _get_history(self, symbol: str, period: str, interval: str) -> Dict:
        """
        Get historical stock data
        
        Args:
            symbol: Stock symbol
            period: Time period
            interval: Data interval
            
        Returns:
            Historical stock data
        """
        params = {
            'range': period,
            'interval': interval
        }
        
        url = f"{self.quote_url.format(symbol)}?{urllib.parse.urlencode(params)}"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if 'chart' in data and 'result' in data['chart'] and data['chart']['result']:
                    result = data['chart']['result'][0]
                    meta = result.get('meta', {})
                    indicators = result.get('indicators', {})
                    timestamps = result.get('timestamp', [])
                    
                    # Get quote data
                    quote = indicators.get('quote', [{}])[0]
                    
                    # Format historical data
                    history = []
                    for i, ts in enumerate(timestamps):
                        history.append({
                            'date': datetime.fromtimestamp(ts).isoformat(),
                            'open': quote.get('open', [])[i] if i < len(quote.get('open', [])) else None,
                            'high': quote.get('high', [])[i] if i < len(quote.get('high', [])) else None,
                            'low': quote.get('low', [])[i] if i < len(quote.get('low', [])) else None,
                            'close': quote.get('close', [])[i] if i < len(quote.get('close', [])) else None,
                            'volume': quote.get('volume', [])[i] if i < len(quote.get('volume', [])) else None
                        })
                    
                    return {
                        'symbol': meta.get('symbol', symbol),
                        'currency': meta.get('currency', 'USD'),
                        'exchange': meta.get('exchangeName', ''),
                        'period': period,
                        'interval': interval,
                        'dataPoints': len(history),
                        'history': history
                    }
                else:
                    raise ValueError(f"No data found for symbol: {symbol}")
                    
        except Exception as e:
            self.logger.error(f"Yahoo Finance history error: {e}")
            raise ValueError(f"Failed to get historical data: {str(e)}")
    
    def _search_symbols(self, query: str) -> Dict:
        """
        Search for stock symbols
        
        Args:
            query: Search query
            
        Returns:
            Search results
        """
        params = {
            'q': query,
            'quotesCount': 10,
            'newsCount': 0
        }
        
        url = f"{self.search_url}?{urllib.parse.urlencode(params)}"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                quotes = data.get('quotes', [])
                
                # Format results
                results = []
                for quote in quotes:
                    results.append({
                        'symbol': quote.get('symbol', ''),
                        'name': quote.get('longname', quote.get('shortname', '')),
                        'type': quote.get('typeDisp', quote.get('quoteType', '')),
                        'exchange': quote.get('exchDisp', quote.get('exchange', '')),
                        'score': quote.get('score', 0)
                    })
                
                return {
                    'query': query,
                    'count': len(results),
                    'results': results
                }
                
        except Exception as e:
            self.logger.error(f"Yahoo Finance search error: {e}")
            raise ValueError(f"Failed to search symbols: {str(e)}")
