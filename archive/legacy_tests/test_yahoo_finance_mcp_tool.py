"""
Copyright © 2025-2030 Ashutosh Sinha
Email: ajsinha@gmail.com
All Rights Reserved

Yahoo Finance MCP Tool - Comprehensive Test Suite
Tests for yahoo_get_quote, yahoo_get_history, and yahoo_search_symbols tools
"""

import unittest
import json
import time
from typing import Dict, Any
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from yahoo_finance_tool import (
        YahooGetQuoteTool,
        YahooGetHistoryTool,
        YahooSearchSymbolsTool,
        YahooFinanceBaseTool,
        YAHOO_FINANCE_TOOLS
    )
except ImportError:
    print("Warning: Could not import yahoo_finance_tool. Ensure the module is in the correct path.")


class TestYahooFinanceBaseTool(unittest.TestCase):
    """Test suite for YahooFinanceBaseTool base class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.base_tool = YahooFinanceBaseTool()
    
    def test_initialization(self):
        """Test base tool initialization"""
        self.assertEqual(self.base_tool.base_url, 'https://query2.finance.yahoo.com')
        self.assertIn('User-Agent', self.base_tool.headers)
        self.assertIn('Mozilla', self.base_tool.headers['User-Agent'])
    
    def test_base_url_format(self):
        """Test base URL format"""
        self.assertTrue(self.base_tool.base_url.startswith('https://'))
        self.assertIn('finance.yahoo.com', self.base_tool.base_url)
    
    @patch('urllib.request.urlopen')
    def test_make_request_success(self, mock_urlopen):
        """Test successful API request"""
        # Mock response
        mock_response = Mock()
        mock_response.read.return_value = b'{"quoteSummary": {"result": []}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        url = f"{self.base_tool.base_url}/test"
        result = self.base_tool._make_request(url)
        
        self.assertIsInstance(result, dict)
        self.assertIn('quoteSummary', result)
    
    @patch('urllib.request.urlopen')
    def test_make_request_404_error(self, mock_urlopen):
        """Test 404 error handling"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url='', code=404, msg='Not Found', hdrs=None, fp=None
        )
        
        url = f"{self.base_tool.base_url}/test"
        with self.assertRaises(ValueError) as context:
            self.base_tool._make_request(url)
        
        self.assertIn('not found', str(context.exception).lower())
    
    @patch('urllib.request.urlopen')
    def test_make_request_timeout(self, mock_urlopen):
        """Test timeout handling"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError('timeout')
        
        url = f"{self.base_tool.base_url}/test"
        with self.assertRaises(ValueError) as context:
            self.base_tool._make_request(url)
        
        self.assertIn('failed', str(context.exception).lower())
    
    def test_headers_configuration(self):
        """Test that headers are properly configured"""
        self.assertIsInstance(self.base_tool.headers, dict)
        self.assertGreater(len(self.base_tool.headers['User-Agent']), 0)


class TestYahooGetQuoteTool(unittest.TestCase):
    """Test suite for YahooGetQuoteTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.quote_tool = YahooGetQuoteTool()
    
    def test_initialization(self):
        """Test quote tool initialization"""
        self.assertEqual(self.quote_tool.config['name'], 'yahoo_get_quote')
        self.assertTrue(self.quote_tool.config['enabled'])
        self.assertEqual(self.quote_tool.config['version'], '1.0.0')
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.quote_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('symbol', schema['properties'])
        self.assertIn('symbol', schema['required'])
        
        # Test symbol constraints
        symbol_schema = schema['properties']['symbol']
        self.assertEqual(symbol_schema['type'], 'string')
        self.assertIn('pattern', symbol_schema)
        self.assertEqual(symbol_schema['pattern'], '^[A-Z^.]{1,10}$')
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.quote_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('symbol', schema['properties'])
        self.assertIn('price', schema['properties'])
        self.assertIn('name', schema['properties'])
        self.assertIn('market_cap', schema['properties'])
        self.assertIn('pe_ratio', schema['properties'])
        self.assertIn('dividend_yield', schema['properties'])
        
        # Test required fields
        self.assertIn('symbol', schema['required'])
        self.assertIn('price', schema['required'])
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_basic_quote(self, mock_request):
        """Test basic quote execution"""
        # Mock API response
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'longName': 'Apple Inc.',
                        'regularMarketPrice': {'raw': 178.50},
                        'currency': 'USD',
                        'regularMarketChange': {'raw': 2.50},
                        'regularMarketChangePercent': {'raw': 1.42},
                        'regularMarketVolume': {'raw': 52000000},
                        'regularMarketDayHigh': {'raw': 179.20},
                        'regularMarketDayLow': {'raw': 177.80},
                        'regularMarketOpen': {'raw': 178.00},
                        'regularMarketPreviousClose': {'raw': 176.00},
                        'marketCap': {'raw': 2780000000000}
                    },
                    'summaryDetail': {
                        'averageVolume': {'raw': 55000000},
                        'trailingPE': {'raw': 28.5},
                        'dividendYield': {'raw': 0.0055},
                        'fiftyTwoWeekHigh': {'raw': 199.62},
                        'fiftyTwoWeekLow': {'raw': 164.08}
                    },
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        result = self.quote_tool.execute({
            'symbol': 'AAPL'
        })
        
        self.assertEqual(result['symbol'], 'AAPL')
        self.assertEqual(result['name'], 'Apple Inc.')
        self.assertEqual(result['price'], 178.50)
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['change'], 2.50)
        self.assertAlmostEqual(result['change_percent'], 1.42, places=2)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_with_null_values(self, mock_request):
        """Test handling of null values"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'longName': 'Test Company',
                        'regularMarketPrice': {'raw': 50.00},
                        'currency': 'USD'
                    },
                    'summaryDetail': {},
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        result = self.quote_tool.execute({'symbol': 'TEST'})
        
        self.assertEqual(result['symbol'], 'TEST')
        self.assertEqual(result['price'], 50.00)
        self.assertIsNone(result['pe_ratio'])
        self.assertIsNone(result['dividend_yield'])
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_symbol_not_found(self, mock_request):
        """Test handling of invalid symbol"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': []
            }
        }
        
        with self.assertRaises(ValueError) as context:
            self.quote_tool.execute({'symbol': 'INVALID'})
        
        self.assertIn('no data', str(context.exception).lower())
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_index_symbol(self, mock_request):
        """Test quote for market index"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'shortName': 'S&P 500',
                        'regularMarketPrice': {'raw': 4500.00},
                        'currency': 'USD',
                        'regularMarketChange': {'raw': 25.50},
                        'regularMarketChangePercent': {'raw': 0.57}
                    },
                    'summaryDetail': {},
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        result = self.quote_tool.execute({'symbol': '^GSPC'})
        
        self.assertEqual(result['symbol'], '^GSPC')
        self.assertEqual(result['name'], 'S&P 500')
        self.assertEqual(result['price'], 4500.00)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_symbol_uppercase_conversion(self, mock_request):
        """Test that symbols are converted to uppercase"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'longName': 'Apple Inc.',
                        'regularMarketPrice': {'raw': 178.50},
                        'currency': 'USD'
                    },
                    'summaryDetail': {},
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        result = self.quote_tool.execute({'symbol': 'aapl'})
        
        self.assertEqual(result['symbol'], 'AAPL')


class TestYahooGetHistoryTool(unittest.TestCase):
    """Test suite for YahooGetHistoryTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.history_tool = YahooGetHistoryTool()
    
    def test_initialization(self):
        """Test history tool initialization"""
        self.assertEqual(self.history_tool.config['name'], 'yahoo_get_history')
        self.assertTrue(self.history_tool.config['enabled'])
        self.assertEqual(self.history_tool.config['version'], '1.0.0')
        
        # Test period map
        self.assertIn('1d', self.history_tool.period_map)
        self.assertIn('1y', self.history_tool.period_map)
        self.assertIn('max', self.history_tool.period_map)
        
        # Test interval map
        self.assertIn('1m', self.history_tool.interval_map)
        self.assertIn('1d', self.history_tool.interval_map)
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.history_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('symbol', schema['properties'])
        self.assertIn('period', schema['properties'])
        self.assertIn('interval', schema['properties'])
        self.assertIn('include_events', schema['properties'])
        
        # Test period enum
        period_schema = schema['properties']['period']
        self.assertIn('enum', period_schema)
        self.assertIn('1d', period_schema['enum'])
        self.assertIn('1y', period_schema['enum'])
        
        # Test interval enum
        interval_schema = schema['properties']['interval']
        self.assertIn('enum', interval_schema)
        self.assertIn('1m', interval_schema['enum'])
        self.assertIn('1d', interval_schema['enum'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.history_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('symbol', schema['properties'])
        self.assertIn('history', schema['properties'])
        self.assertIn('dividends', schema['properties'])
        self.assertIn('splits', schema['properties'])
        
        # Test history array structure
        history_schema = schema['properties']['history']
        self.assertEqual(history_schema['type'], 'array')
        self.assertIn('items', history_schema)
        
        # Test OHLCV fields
        history_item = history_schema['items']['properties']
        self.assertIn('open', history_item)
        self.assertIn('high', history_item)
        self.assertIn('low', history_item)
        self.assertIn('close', history_item)
        self.assertIn('volume', history_item)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_basic_history(self, mock_request):
        """Test basic history execution"""
        # Mock API response
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200, 1698825600, 1698912000],
                    'indicators': {
                        'quote': [{
                            'open': [150.0, 151.0, 152.0],
                            'high': [152.5, 153.0, 154.0],
                            'low': [149.5, 150.5, 151.5],
                            'close': [151.0, 152.0, 153.0],
                            'volume': [50000000, 52000000, 51000000]
                        }]
                    },
                    'meta': {
                        'currency': 'USD'
                    }
                }]
            }
        }
        
        result = self.history_tool.execute({
            'symbol': 'AAPL',
            'period': '1mo',
            'interval': '1d'
        })
        
        self.assertEqual(result['symbol'], 'AAPL')
        self.assertEqual(result['period'], '1mo')
        self.assertEqual(result['interval'], '1d')
        self.assertEqual(result['data_points'], 3)
        self.assertEqual(len(result['history']), 3)
        self.assertEqual(result['currency'], 'USD')
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_with_dividends(self, mock_request):
        """Test history with dividend events"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [50000000]
                        }]
                    },
                    'events': {
                        'dividends': {
                            '1698739200': {
                                'amount': 0.24
                            }
                        }
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        result = self.history_tool.execute({
            'symbol': 'AAPL',
            'period': '1mo',
            'include_events': True
        })
        
        self.assertEqual(len(result['dividends']), 1)
        self.assertEqual(result['dividends'][0]['amount'], 0.24)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_with_splits(self, mock_request):
        """Test history with stock split events"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [50000000]
                        }]
                    },
                    'events': {
                        'splits': {
                            '1598400000': {
                                'numerator': 4,
                                'denominator': 1
                            }
                        }
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        result = self.history_tool.execute({
            'symbol': 'AAPL',
            'period': '5y',
            'include_events': True
        })
        
        self.assertEqual(len(result['splits']), 1)
        self.assertEqual(result['splits'][0]['ratio'], '4:1')
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_different_periods(self, mock_request):
        """Test different period options"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [50000000]
                        }]
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        periods = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '5y']
        for period in periods:
            result = self.history_tool.execute({
                'symbol': 'AAPL',
                'period': period
            })
            self.assertEqual(result['period'], period)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_different_intervals(self, mock_request):
        """Test different interval options"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [50000000]
                        }]
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        intervals = ['1m', '5m', '15m', '1h', '1d', '1wk']
        for interval in intervals:
            result = self.history_tool.execute({
                'symbol': 'AAPL',
                'period': '1mo',
                'interval': interval
            })
            self.assertEqual(result['interval'], interval)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_no_data(self, mock_request):
        """Test handling of no historical data"""
        mock_request.return_value = {
            'chart': {
                'result': []
            }
        }
        
        with self.assertRaises(ValueError) as context:
            self.history_tool.execute({'symbol': 'INVALID'})
        
        self.assertIn('no historical data', str(context.exception).lower())
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_ohlcv_data_structure(self, mock_request):
        """Test OHLCV data structure"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [50000000]
                        }]
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        result = self.history_tool.execute({
            'symbol': 'AAPL',
            'period': '1d'
        })
        
        point = result['history'][0]
        self.assertIn('date', point)
        self.assertIn('open', point)
        self.assertIn('high', point)
        self.assertIn('low', point)
        self.assertIn('close', point)
        self.assertIn('volume', point)
        self.assertIn('adjusted_close', point)


class TestYahooSearchSymbolsTool(unittest.TestCase):
    """Test suite for YahooSearchSymbolsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.search_tool = YahooSearchSymbolsTool()
    
    def test_initialization(self):
        """Test search tool initialization"""
        self.assertEqual(self.search_tool.config['name'], 'yahoo_search_symbols')
        self.assertTrue(self.search_tool.config['enabled'])
        self.assertEqual(self.search_tool.config['version'], '1.0.0')
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.search_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('limit', schema['properties'])
        self.assertIn('exchange', schema['properties'])
        self.assertIn('query', schema['required'])
        
        # Test query constraints
        query_schema = schema['properties']['query']
        self.assertEqual(query_schema['type'], 'string')
        self.assertEqual(query_schema['minLength'], 1)
        self.assertEqual(query_schema['maxLength'], 100)
        
        # Test limit constraints
        limit_schema = schema['properties']['limit']
        self.assertEqual(limit_schema['type'], 'integer')
        self.assertEqual(limit_schema['minimum'], 1)
        self.assertEqual(limit_schema['maximum'], 50)
        self.assertEqual(limit_schema['default'], 10)
        
        # Test exchange enum
        exchange_schema = schema['properties']['exchange']
        self.assertIn('enum', exchange_schema)
        self.assertIn('NYSE', exchange_schema['enum'])
        self.assertIn('NASDAQ', exchange_schema['enum'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.search_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('result_count', schema['properties'])
        self.assertIn('results', schema['properties'])
        
        # Test results array structure
        results_schema = schema['properties']['results']
        self.assertEqual(results_schema['type'], 'array')
        
        # Test result item properties
        result_item = results_schema['items']['properties']
        self.assertIn('symbol', result_item)
        self.assertIn('name', result_item)
        self.assertIn('exchange', result_item)
        self.assertIn('type', result_item)
        self.assertIn('sector', result_item)
        self.assertIn('industry', result_item)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_basic_search(self, mock_request):
        """Test basic symbol search"""
        mock_request.return_value = {
            'quotes': [
                {
                    'symbol': 'AAPL',
                    'longname': 'Apple Inc.',
                    'shortname': 'Apple',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY',
                    'sector': 'Technology',
                    'industry': 'Consumer Electronics',
                    'marketCap': 2780000000000
                },
                {
                    'symbol': 'MSFT',
                    'longname': 'Microsoft Corporation',
                    'shortname': 'Microsoft',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY',
                    'sector': 'Technology',
                    'industry': 'Software'
                }
            ]
        }
        
        result = self.search_tool.execute({
            'query': 'technology'
        })
        
        self.assertEqual(result['query'], 'technology')
        self.assertEqual(result['result_count'], 2)
        self.assertEqual(len(result['results']), 2)
        self.assertEqual(result['results'][0]['symbol'], 'AAPL')
        self.assertEqual(result['results'][0]['name'], 'Apple Inc.')
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_with_limit(self, mock_request):
        """Test search with custom limit"""
        mock_request.return_value = {
            'quotes': [
                {'symbol': f'SYM{i}', 'shortname': f'Company {i}', 
                 'exchange': 'NASDAQ', 'quoteType': 'EQUITY'}
                for i in range(20)
            ]
        }
        
        result = self.search_tool.execute({
            'query': 'test',
            'limit': 15
        })
        
        self.assertLessEqual(result['result_count'], 15)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_with_exchange_filter(self, mock_request):
        """Test search with exchange filter"""
        mock_request.return_value = {
            'quotes': [
                {
                    'symbol': 'AAPL',
                    'shortname': 'Apple',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY'
                },
                {
                    'symbol': 'IBM',
                    'shortname': 'IBM',
                    'exchange': 'NYSE',
                    'quoteType': 'EQUITY'
                },
                {
                    'symbol': 'GOOGL',
                    'shortname': 'Alphabet',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY'
                }
            ]
        }
        
        result = self.search_tool.execute({
            'query': 'tech',
            'exchange': 'NASDAQ'
        })
        
        # Should filter out NYSE stocks
        for item in result['results']:
            self.assertEqual(item['exchange'], 'NASDAQ')
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_empty_results(self, mock_request):
        """Test handling of empty search results"""
        mock_request.return_value = {
            'quotes': []
        }
        
        result = self.search_tool.execute({
            'query': 'nonexistent123'
        })
        
        self.assertEqual(result['result_count'], 0)
        self.assertEqual(len(result['results']), 0)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_execute_different_security_types(self, mock_request):
        """Test search with different security types"""
        mock_request.return_value = {
            'quotes': [
                {
                    'symbol': 'AAPL',
                    'shortname': 'Apple',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY'
                },
                {
                    'symbol': 'SPY',
                    'shortname': 'SPDR S&P 500',
                    'exchange': 'NYSE',
                    'quoteType': 'ETF'
                },
                {
                    'symbol': '^GSPC',
                    'shortname': 'S&P 500',
                    'exchange': 'INDEX',
                    'quoteType': 'INDEX'
                }
            ]
        }
        
        result = self.search_tool.execute({
            'query': 'sp 500'
        })
        
        types = [r['type'] for r in result['results']]
        self.assertIn('EQUITY', types)
        self.assertIn('ETF', types)
        self.assertIn('INDEX', types)
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_name_fallback(self, mock_request):
        """Test that shortname is used when longname is absent"""
        mock_request.return_value = {
            'quotes': [
                {
                    'symbol': 'TEST',
                    'shortname': 'Test Co',
                    'exchange': 'NASDAQ',
                    'quoteType': 'EQUITY'
                }
            ]
        }
        
        result = self.search_tool.execute({'query': 'test'})
        
        self.assertEqual(result['results'][0]['name'], 'Test Co')


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry"""
    
    def test_registry_contains_all_tools(self):
        """Test that registry contains all tool classes"""
        self.assertIn('yahoo_get_quote', YAHOO_FINANCE_TOOLS)
        self.assertIn('yahoo_get_history', YAHOO_FINANCE_TOOLS)
        self.assertIn('yahoo_search_symbols', YAHOO_FINANCE_TOOLS)
    
    def test_registry_tool_instantiation(self):
        """Test that tools can be instantiated from registry"""
        for tool_name, tool_class in YAHOO_FINANCE_TOOLS.items():
            tool_instance = tool_class()
            self.assertIsNotNone(tool_instance)
            self.assertTrue(hasattr(tool_instance, 'execute'))
            self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
            self.assertTrue(hasattr(tool_instance, 'get_output_schema'))
    
    def test_registry_tool_count(self):
        """Test that registry has correct number of tools"""
        self.assertEqual(len(YAHOO_FINANCE_TOOLS), 3)


class TestIntegration(unittest.TestCase):
    """Integration tests (require network connection and actual Yahoo Finance API)"""
    
    def setUp(self):
        """Set up for integration tests"""
        self.run_integration_tests = False  # Set to True to run actual API calls
        
        if not self.run_integration_tests:
            self.skipTest("Integration tests disabled. Set run_integration_tests=True to enable.")
    
    def test_real_quote(self):
        """Test real quote retrieval"""
        if not self.run_integration_tests:
            return
        
        quote_tool = YahooGetQuoteTool()
        result = quote_tool.execute({
            'symbol': 'AAPL'
        })
        
        self.assertEqual(result['symbol'], 'AAPL')
        self.assertIsNotNone(result['price'])
        self.assertGreater(result['price'], 0)
        self.assertIn('Apple', result['name'])
        
        # Rate limiting
        time.sleep(1)
    
    def test_real_history(self):
        """Test real historical data retrieval"""
        if not self.run_integration_tests:
            return
        
        history_tool = YahooGetHistoryTool()
        result = history_tool.execute({
            'symbol': 'MSFT',
            'period': '1mo',
            'interval': '1d'
        })
        
        self.assertEqual(result['symbol'], 'MSFT')
        self.assertGreater(len(result['history']), 0)
        self.assertGreater(result['data_points'], 0)
        
        # Verify OHLCV data
        point = result['history'][0]
        self.assertIn('open', point)
        self.assertIn('high', point)
        self.assertIn('low', point)
        self.assertIn('close', point)
        
        # Rate limiting
        time.sleep(1)
    
    def test_real_search(self):
        """Test real symbol search"""
        if not self.run_integration_tests:
            return
        
        search_tool = YahooSearchSymbolsTool()
        result = search_tool.execute({
            'query': 'Microsoft',
            'limit': 5
        })
        
        self.assertGreater(result['result_count'], 0)
        self.assertGreater(len(result['results']), 0)
        
        # Microsoft should be in results
        symbols = [r['symbol'] for r in result['results']]
        self.assertIn('MSFT', symbols)
        
        # Rate limiting
        time.sleep(1)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions"""
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_null_handling_in_quote(self, mock_request):
        """Test handling of various null values"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'regularMarketPrice': {'raw': 100.0},
                        'currency': 'USD'
                    },
                    'summaryDetail': {
                        'trailingPE': None,
                        'dividendYield': None
                    },
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        quote_tool = YahooGetQuoteTool()
        result = quote_tool.execute({'symbol': 'TEST'})
        
        self.assertIsNone(result['pe_ratio'])
        self.assertIsNone(result['dividend_yield'])
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_missing_volume_data(self, mock_request):
        """Test handling of missing volume data"""
        mock_request.return_value = {
            'chart': {
                'result': [{
                    'timestamp': [1698739200],
                    'indicators': {
                        'quote': [{
                            'open': [150.0],
                            'high': [152.5],
                            'low': [149.5],
                            'close': [151.0],
                            'volume': [None]
                        }]
                    },
                    'meta': {'currency': 'USD'}
                }]
            }
        }
        
        history_tool = YahooGetHistoryTool()
        result = history_tool.execute({
            'symbol': 'TEST',
            'period': '1d'
        })
        
        self.assertIsNone(result['history'][0]['volume'])
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_special_characters_in_symbol(self, mock_request):
        """Test handling of special characters in symbols"""
        mock_request.return_value = {
            'quoteSummary': {
                'result': [{
                    'price': {
                        'shortName': 'S&P 500',
                        'regularMarketPrice': {'raw': 4500.0},
                        'currency': 'USD'
                    },
                    'summaryDetail': {},
                    'defaultKeyStatistics': {}
                }]
            }
        }
        
        quote_tool = YahooGetQuoteTool()
        result = quote_tool.execute({'symbol': '^GSPC'})
        
        self.assertEqual(result['symbol'], '^GSPC')
    
    @patch.object(YahooFinanceBaseTool, '_make_request')
    def test_exchange_filter_no_matches(self, mock_request):
        """Test exchange filter with no matching results"""
        mock_request.return_value = {
            'quotes': [
                {
                    'symbol': 'TEST',
                    'shortname': 'Test',
                    'exchange': 'NYSE',
                    'quoteType': 'EQUITY'
                }
            ]
        }
        
        search_tool = YahooSearchSymbolsTool()
        result = search_tool.execute({
            'query': 'test',
            'exchange': 'NASDAQ'
        })
        
        self.assertEqual(result['result_count'], 0)


class TestDataValidation(unittest.TestCase):
    """Test data validation and type checking"""
    
    def test_symbol_pattern_validation(self):
        """Test symbol pattern requirements"""
        quote_tool = YahooGetQuoteTool()
        schema = quote_tool.get_input_schema()
        
        pattern = schema['properties']['symbol']['pattern']
        
        # Valid symbols
        import re
        self.assertIsNotNone(re.match(pattern, 'AAPL'))
        self.assertIsNotNone(re.match(pattern, '^GSPC'))
        self.assertIsNotNone(re.match(pattern, 'BRK.A'))
        
        # Invalid symbols (lowercase)
        self.assertIsNone(re.match(pattern, 'aapl'))
    
    def test_period_enum_values(self):
        """Test that all period values are valid"""
        history_tool = YahooGetHistoryTool()
        schema = history_tool.get_input_schema()
        
        periods = schema['properties']['period']['enum']
        expected = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max']
        
        for period in expected:
            self.assertIn(period, periods)
    
    def test_interval_enum_values(self):
        """Test that all interval values are valid"""
        history_tool = YahooGetHistoryTool()
        schema = history_tool.get_input_schema()
        
        intervals = schema['properties']['interval']['enum']
        expected = ['1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo']
        
        for interval in expected:
            self.assertIn(interval, intervals)


def run_test_suite():
    """Run the complete test suite with reporting"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestYahooFinanceBaseTool))
    suite.addTests(loader.loadTestsFromTestCase(TestYahooGetQuoteTool))
    suite.addTests(loader.loadTestsFromTestCase(TestYahooGetHistoryTool))
    suite.addTests(loader.loadTestsFromTestCase(TestYahooSearchSymbolsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestDataValidation))
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("="*70)
    
    return result


if __name__ == '__main__':
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║        Yahoo Finance MCP Tool - Comprehensive Test Suite     ║
    ║                                                               ║
    ║         Copyright © 2025-2030 Ashutosh Sinha                 ║
    ║         Email: ajsinha@gmail.com                             ║
    ║         All Rights Reserved                                   ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    result = run_test_suite()
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
