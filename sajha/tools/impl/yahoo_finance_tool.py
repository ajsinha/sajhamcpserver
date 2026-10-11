"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Yahoo Finance MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL


class YahooFinanceBaseTool(BaseMCPTool):
    """
    Base class for Yahoo Finance tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Yahoo Finance base tool"""
        super().__init__(config)
        
        # Yahoo Finance API endpoints
        self.base_url = "https://query2.finance.yahoo.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    
    def _make_request(self, url: str) -> Dict:
        """
        Make HTTP request to Yahoo Finance API
        
        Args:
            url: Full URL to request
            
        Returns:
            Parsed JSON response
        """
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = safe_json_response(response, ENCODINGS_ALL)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Symbol or resource not found")
            else:
                raise ValueError(f"Failed to fetch data: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to fetch data: {str(e)}")


class YahooGetQuoteTool(YahooFinanceBaseTool):
    """
    Tool to retrieve real-time stock quotes from Yahoo Finance
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'yahoo_get_quote',
            'description': 'Retrieve real-time stock quote data including current price, volume, market cap, and key statistics',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for stock quotes"""
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, BRK-A, ^GSPC for the S&P 500, BTC-USD, EURUSD=X, 7203.T)",
                    "pattern": "^[A-Za-z0-9^.=-]{1,20}$"
                }
            },
            "required": ["symbol"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for stock quotes"""
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "name": {"type": "string"},
                "price": {"type": ["number", "null"]},
                "currency": {"type": "string"},
                "change": {"type": ["number", "null"]},
                "change_percent": {"type": ["number", "null"]},
                "volume": {"type": ["integer", "null"]},
                "avg_volume": {"type": ["integer", "null"]},
                "market_cap": {"type": ["number", "null"]},
                "pe_ratio": {"type": ["number", "null"]},
                "dividend_yield": {"type": ["number", "null"]},
                "fifty_two_week_high": {"type": ["number", "null"]},
                "fifty_two_week_low": {"type": ["number", "null"]},
                "day_high": {"type": ["number", "null"]},
                "day_low": {"type": ["number", "null"]},
                "open": {"type": ["number", "null"]},
                "previous_close": {"type": ["number", "null"]},
                "last_updated": {"type": "string"}
            },
            "required": ["symbol", "price"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get quote operation through yfinance, which handles the cookie and crumb
        that Yahoo's quoteSummary endpoint now requires (a plain request gets HTTP 401)."""
        symbol = arguments['symbol'].upper()
        try:
            import yfinance as yf
        except ImportError:
            raise ValueError("yahoo_get_quote needs the yfinance package (pip install yfinance)")
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            self.logger.error(f"Failed to get quote for {symbol}: {e}", exc_info=True)
            raise ValueError(f"Failed to get quote for {symbol}: {str(e)}")
        price = info.get('regularMarketPrice')
        if price is None:
            price = info.get('currentPrice')
        if price is None:
            raise ValueError(f"No quote found for symbol: {symbol}")
        market_time = info.get('regularMarketTime')
        return {
            'symbol': symbol,
            'name': info.get('longName') or info.get('shortName'),
            'price': price,
            'currency': info.get('currency'),
            'change': info.get('regularMarketChange'),
            'change_percent': info.get('regularMarketChangePercent'),
            'volume': info.get('regularMarketVolume'),
            'avg_volume': info.get('averageVolume'),
            'market_cap': info.get('marketCap'),
            'pe_ratio': info.get('trailingPE'),
            'dividend_yield': info.get('dividendYield'),
            'fifty_two_week_high': info.get('fiftyTwoWeekHigh'),
            'fifty_two_week_low': info.get('fiftyTwoWeekLow'),
            'day_high': info.get('regularMarketDayHigh'),
            'day_low': info.get('regularMarketDayLow'),
            'open': info.get('regularMarketOpen'),
            'previous_close': info.get('regularMarketPreviousClose'),
            'exchange': info.get('exchange'),
            'market_time': datetime.fromtimestamp(market_time, tz=timezone.utc).isoformat()
            if isinstance(market_time, (int, float)) else None,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }


class YahooGetHistoryTool(YahooFinanceBaseTool):
    """
    Tool to retrieve historical price and volume data from Yahoo Finance
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'yahoo_get_history',
            'description': 'Retrieve historical price and volume data for a stock over a specified time period',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Period to seconds mapping
        self.period_map = {
            '1d': 86400,
            '5d': 432000,
            '1mo': 2592000,
            '3mo': 7776000,
            '6mo': 15552000,
            '1y': 31536000,
            '2y': 63072000,
            '5y': 157680000,
            '10y': 315360000,
            'ytd': 'ytd',
            'max': 'max'
        }
        
        # Interval mapping
        self.interval_map = {
            '1m': '1m', '2m': '2m', '5m': '5m', '15m': '15m',
            '30m': '30m', '60m': '60m', '90m': '90m', '1h': '1h',
            '1d': '1d', '5d': '5d', '1wk': '1wk', '1mo': '1mo', '3mo': '3mo'
        }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for historical data"""
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol",
                    "pattern": "^[A-Za-z0-9^.=-]{1,20}$"
                },
                "period": {
                    "type": "string",
                    "description": "Time period for historical data",
                    "enum": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
                    "default": "1mo"
                },
                "interval": {
                    "type": "string",
                    "description": "Data interval/granularity",
                    "enum": ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"],
                    "default": "1d"
                },
                "include_events": {
                    "type": "boolean",
                    "description": "Include dividend and split events",
                    "default": True
                }
            },
            "required": ["symbol"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for historical data"""
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "period": {"type": "string"},
                "interval": {"type": "string"},
                "data_points": {"type": "integer"},
                "history": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "open": {"type": ["number", "null"]},
                            "high": {"type": ["number", "null"]},
                            "low": {"type": ["number", "null"]},
                            "close": {"type": ["number", "null"]},
                            "volume": {"type": ["integer", "null"]},
                            "adjusted_close": {"type": ["number", "null"]}
                        }
                    }
                },
                "dividends": {"type": "array"},
                "splits": {"type": "array"},
                "currency": {"type": "string"},
                "last_updated": {"type": "string"}
            },
            "required": ["symbol", "history"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get history operation"""
        symbol = arguments['symbol'].upper()
        period = arguments.get('period', '1mo')
        interval = arguments.get('interval', '1d')
        include_events = arguments.get('include_events', True)
        
        # Calculate time range
        now = int(datetime.now().timestamp())
        if period == 'ytd':
            # Year to date
            year_start = datetime(datetime.now().year, 1, 1)
            period1 = int(year_start.timestamp())
            period2 = now
        elif period == 'max':
            # Maximum available data
            period1 = 0
            period2 = now
        else:
            period1 = now - self.period_map[period]
            period2 = now
        
        # Build API URL
        url = f"{self.base_url}/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}"
        params = {
            'period1': period1,
            'period2': period2,
            'interval': interval,
            'events': 'div,split' if include_events else '',
            'includeAdjustedClose': 'true'
        }
        url += '?' + urllib.parse.urlencode(params)
        
        try:
            data = self._make_request(url)
            chart = data.get('chart', {})
            result = chart.get('result', [])
            
            if not result:
                raise ValueError(f"No historical data found for symbol: {symbol}")
            
            stock_data = result[0]
            timestamps = stock_data.get('timestamp', [])
            quotes = stock_data.get('indicators', {}).get('quote', [{}])[0]
            # adjusted closes come in their own block (includeAdjustedClose); null when Yahoo omits it
            adjclose = ((stock_data.get('indicators', {}).get('adjclose') or [{}])[0] or {}).get('adjclose') or []
            
            # Build history array
            history = []
            for i, ts in enumerate(timestamps):
                date = datetime.fromtimestamp(ts).isoformat()
                history.append({
                    'date': date,
                    'open': quotes.get('open', [])[i] if i < len(quotes.get('open', [])) else None,
                    'high': quotes.get('high', [])[i] if i < len(quotes.get('high', [])) else None,
                    'low': quotes.get('low', [])[i] if i < len(quotes.get('low', [])) else None,
                    'close': quotes.get('close', [])[i] if i < len(quotes.get('close', [])) else None,
                    'volume': int(quotes.get('volume', [])[i]) if i < len(quotes.get('volume', [])) and quotes.get('volume', [])[i] else None,
                    'adjusted_close': adjclose[i] if i < len(adjclose) else None
                })
            
            # Extract events
            dividends = []
            splits = []
            
            if include_events:
                events = stock_data.get('events', {})
                
                # Process dividends
                if 'dividends' in events:
                    for ts, div in events['dividends'].items():
                        dividends.append({
                            'date': datetime.fromtimestamp(int(ts)).isoformat(),
                            'amount': div.get('amount')
                        })
                
                # Process splits
                if 'splits' in events:
                    for ts, split in events['splits'].items():
                        splits.append({
                            'date': datetime.fromtimestamp(int(ts)).isoformat(),
                            'ratio': f"{split.get('numerator')}:{split.get('denominator')}"
                        })
            
            return {
                'symbol': symbol,
                'period': period,
                'interval': interval,
                'data_points': len(history),
                'history': history,
                'dividends': dividends,
                'splits': splits,
                'currency': stock_data.get('meta', {}).get('currency', 'USD'),
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get history for {symbol}: {e}", exc_info=True)
            raise ValueError(f"Failed to get history for {symbol}: {str(e)}")


#: the exchange filter of yahoo_search_symbols -> the codes Yahoo reports in search results
EXCHANGE_CODES = {
    'NYSE': {'NYQ'},
    'NASDAQ': {'NMS', 'NGM', 'NCM', 'NAS'},
    'AMEX': {'ASE'},
    'LSE': {'LSE', 'IOB'},
    'TSX': {'TOR'},
}


class YahooSearchSymbolsTool(YahooFinanceBaseTool):
    """
    Tool to search for stock symbols by company name or keyword
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'yahoo_search_symbols',
            'description': 'Search for stock symbols and companies by name, ticker, or keyword',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for symbol search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - company name, ticker symbol, or keyword",
                    "minLength": 1,
                    "maxLength": 100
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                },
                "exchange": {
                    "type": "string",
                    "description": "Filter by exchange (optional)",
                    "enum": ["NYSE", "NASDAQ", "AMEX", "LSE", "TSX", "all"],
                    "default": "all"
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for symbol search"""
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "result_count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string"},
                            "name": {"type": "string"},
                            "exchange": {"type": "string"},
                            "type": {"type": "string"},
                            "sector": {"type": ["string", "null"]},
                            "industry": {"type": ["string", "null"]},
                            "market_cap": {"type": ["number", "null"]},
                            "description": {"type": ["string", "null"]}
                        }
                    }
                },
                "last_updated": {"type": "string"}
            },
            "required": ["query", "results"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the search symbols operation"""
        query = arguments['query']
        limit = arguments.get('limit', 10)
        exchange_filter = arguments.get('exchange', 'all')
        codes = EXCHANGE_CODES.get(exchange_filter)       # None for 'all'

        # Build search URL; with an exchange filter, ask for more so that the filter still fills limit
        url = f"{self.base_url}/v1/finance/search"
        params = {
            'q': query,
            'quotesCount': limit if not codes else min(max(limit * 4, 25), 100),
            'newsCount': 0,
            'enableFuzzyQuery': 'false'
        }
        url += '?' + urllib.parse.urlencode(params)
        
        try:
            data = self._make_request(url)
            quotes = data.get('quotes', [])
            
            results = []
            for quote in quotes:
                if len(results) >= limit:
                    break
                # Yahoo reports its own exchange codes (NMS, NYQ, ...), not NYSE or NASDAQ
                if codes and quote.get('exchange') not in codes:
                    continue
                
                results.append({
                    'symbol': quote.get('symbol'),
                    'name': quote.get('longname') or quote.get('shortname'),
                    'exchange': quote.get('exchange'),
                    'type': quote.get('quoteType', 'EQUITY'),
                    'sector': quote.get('sector'),
                    'industry': quote.get('industry'),
                    'market_cap': quote.get('marketCap'),
                    'exchange_name': quote.get('exchDisp'),
                    'description': None  # Not available in search results
                })
            
            return {
                'query': query,
                'result_count': len(results),
                'results': results,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to search symbols for '{query}': {e}", exc_info=True)
            raise ValueError(f"Failed to search symbols: {str(e)}")


# Tool registry for easy access
YAHOO_FINANCE_TOOLS = {
    'yahoo_get_quote': YahooGetQuoteTool,
    'yahoo_get_history': YahooGetHistoryTool,
    'yahoo_search_symbols': YahooSearchSymbolsTool
}
