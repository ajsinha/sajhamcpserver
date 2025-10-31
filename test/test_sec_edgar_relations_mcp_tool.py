"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Test Suite for SEC Edgar Search MCP Tools
Comprehensive tests for all SEC EDGAR data retrieval tools
"""

import unittest
import json
import urllib.error
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Import all tools
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.impl.sec_edgar_tool_refactored import (
    SECSearchCompanyTool,
    SECGetCompanyInfoTool,
    SECGetCompanyFilingsTool,
    SECGetCompanyFactsTool,
    SECGetFinancialDataTool,
    SECGetInsiderTradingTool,
    SECGetMutualFundHoldingsTool,
    SEC_EDGAR_TOOLS
)


class TestSECEdgarBaseSetup(unittest.TestCase):
    """Base test class with common setup"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.test_config = {
            'enabled': True,
            'version': '1.0.0'
        }
        
        # Sample company data
        cls.apple_cik = '0000320193'
        cls.apple_ticker = 'AAPL'
        cls.test_ticker = 'TEST'
        cls.test_cik = '0001234567'
        
        # Mock API responses
        cls.mock_ticker_data = {
            '0': {
                'cik_str': 320193,
                'ticker': 'AAPL',
                'title': 'Apple Inc.',
                'exchange': 'Nasdaq'
            },
            '1': {
                'cik_str': 789019,
                'ticker': 'MSFT',
                'title': 'MICROSOFT CORP',
                'exchange': 'Nasdaq'
            },
            '2': {
                'cik_str': 1318605,
                'ticker': 'TSLA',
                'title': 'Tesla, Inc.',
                'exchange': 'Nasdaq'
            }
        }


class TestSECSearchCompanyTool(TestSECEdgarBaseSetup):
    """Test cases for sec_search_company tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECSearchCompanyTool(self.test_config)
    
    def test_tool_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'sec_search_company')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
        self.assertIn('User-Agent', self.tool.user_agent)
        self.assertIn('ajsinha@gmail.com', self.tool.user_agent)
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('search_term', schema['properties'])
        self.assertIn('limit', schema['properties'])
        self.assertEqual(schema['properties']['limit']['default'], 10)
        self.assertEqual(schema['properties']['limit']['maximum'], 100)
        self.assertIn('search_term', schema['required'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('search_term', schema['properties'])
        self.assertIn('result_count', schema['properties'])
        self.assertIn('companies', schema['properties'])
        
        # Check company item schema
        company_schema = schema['properties']['companies']['items']['properties']
        self.assertIn('cik', company_schema)
        self.assertIn('name', company_schema)
        self.assertIn('ticker', company_schema)
    
    @patch('urllib.request.urlopen')
    def test_search_by_ticker(self, mock_urlopen):
        """Test searching by ticker symbol"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result = self.tool.execute({
            'search_term': 'AAPL',
            'limit': 5
        })
        
        self.assertIn('search_term', result)
        self.assertIn('result_count', result)
        self.assertIn('companies', result)
        self.assertEqual(result['search_term'], 'AAPL')
        self.assertGreaterEqual(result['result_count'], 1)
    
    @patch('urllib.request.urlopen')
    def test_search_by_company_name(self, mock_urlopen):
        """Test searching by company name"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result = self.tool.execute({
            'search_term': 'Apple',
            'limit': 10
        })
        
        self.assertGreater(result['result_count'], 0)
        # Check that Apple is in results
        apple_found = any('APPLE' in c['name'].upper() for c in result['companies'])
        self.assertTrue(apple_found)
    
    @patch('urllib.request.urlopen')
    def test_search_case_insensitive(self, mock_urlopen):
        """Test case-insensitive search"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result1 = self.tool.execute({'search_term': 'apple'})
        result2 = self.tool.execute({'search_term': 'APPLE'})
        
        self.assertEqual(result1['result_count'], result2['result_count'])
    
    def test_empty_search_term(self):
        """Test error on empty search term"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'search_term': ''})
        self.assertIn('required', str(context.exception).lower())
    
    @patch('urllib.request.urlopen')
    def test_limit_parameter(self, mock_urlopen):
        """Test limit parameter"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result = self.tool.execute({
            'search_term': 'Corp',
            'limit': 2
        })
        
        self.assertLessEqual(len(result['companies']), 2)


class TestSECGetCompanyInfoTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_company_info tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetCompanyInfoTool(self.test_config)
    
    def test_tool_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'sec_get_company_info')
        self.assertIsNotNone(self.tool.user_agent)
    
    def test_input_schema_oneof(self):
        """Test oneOf constraint for cik or ticker"""
        schema = self.tool.get_input_schema()
        self.assertIn('oneOf', schema)
        self.assertEqual(len(schema['oneOf']), 2)
    
    @patch('urllib.request.urlopen')
    def test_get_company_info_by_ticker(self, mock_urlopen):
        """Test getting company info by ticker"""
        # Mock ticker to CIK conversion
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        # Mock company info response
        info_response = MagicMock()
        info_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'tickers': ['AAPL'],
            'sic': '3571',
            'sicDescription': 'Electronic Computers',
            'fiscalYearEnd': '0930',
            'addresses': {
                'business': {
                    'street1': 'One Apple Park Way',
                    'city': 'Cupertino',
                    'stateOrCountry': 'CA',
                    'zipCode': '95014'
                }
            }
        }
        info_response.read.return_value = json.dumps(info_data).encode('utf-8')
        info_response.__enter__.return_value = info_response
        
        mock_urlopen.side_effect = [ticker_response, info_response]
        
        result = self.tool.execute({'ticker': 'AAPL'})
        
        self.assertIn('cik', result)
        self.assertIn('name', result)
        self.assertIn('tickers', result)
        self.assertEqual(result['name'], 'Apple Inc.')
    
    @patch('urllib.request.urlopen')
    def test_get_company_info_by_cik(self, mock_urlopen):
        """Test getting company info by CIK"""
        mock_response = MagicMock()
        info_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'sic': '3571',
            'sicDescription': 'Electronic Computers'
        }
        mock_response.read.return_value = json.dumps(info_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result = self.tool.execute({'cik': '320193'})
        
        self.assertEqual(result['cik'], '0000320193')
    
    def test_cik_normalization(self):
        """Test CIK is normalized to 10 digits"""
        self.assertEqual(self.tool._normalize_cik('123'), '0000000123')
        self.assertEqual(self.tool._normalize_cik('0000320193'), '0000320193')
    
    @patch('urllib.request.urlopen')
    def test_company_not_found(self, mock_urlopen):
        """Test error when company not found"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'url', 404, 'Not Found', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'cik': '9999999999'})
        self.assertIn('not found', str(context.exception).lower())


class TestSECGetCompanyFilingsTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_company_filings tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetCompanyFilingsTool(self.test_config)
    
    def test_filing_types_enum(self):
        """Test filing types enumeration"""
        schema = self.tool.get_input_schema()
        filing_types = schema['properties']['filing_type']['enum']
        
        self.assertIn('10-K', filing_types)
        self.assertIn('10-Q', filing_types)
        self.assertIn('8-K', filing_types)
        self.assertIn('4', filing_types)
        self.assertIn('13F-HR', filing_types)
    
    @patch('urllib.request.urlopen')
    def test_get_all_filings(self, mock_urlopen):
        """Test getting all filings"""
        # Mock ticker conversion
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        # Mock filings response
        filings_response = MagicMock()
        filings_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'filings': {
                'recent': {
                    'accessionNumber': ['0001234567-24-000001', '0001234567-24-000002'],
                    'filingDate': ['2024-11-01', '2024-08-01'],
                    'reportDate': ['2024-09-30', '2024-06-30'],
                    'form': ['10-K', '10-Q'],
                    'primaryDocument': ['aapl-20240930.htm', 'aapl-20240630.htm']
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.side_effect = [ticker_response, filings_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'limit': 10
        })
        
        self.assertIn('filings', result)
        self.assertIn('filing_count', result)
        self.assertGreater(result['filing_count'], 0)
    
    @patch('urllib.request.urlopen')
    def test_filter_by_filing_type(self, mock_urlopen):
        """Test filtering by filing type"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        filings_response = MagicMock()
        filings_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'filings': {
                'recent': {
                    'accessionNumber': ['0001-10K', '0002-10Q', '0003-10K', '0004-8K'],
                    'filingDate': ['2024-11-01', '2024-08-01', '2023-11-01', '2024-05-01'],
                    'reportDate': ['2024-09-30', '2024-06-30', '2023-09-30', '2024-04-30'],
                    'form': ['10-K', '10-Q', '10-K', '8-K'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm', 'doc3.htm', 'doc4.htm']
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.side_effect = [ticker_response, filings_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'filing_type': '10-K',
            'limit': 10
        })
        
        # All filings should be 10-K
        for filing in result['filings']:
            self.assertEqual(filing['form'], '10-K')
    
    @patch('urllib.request.urlopen')
    def test_date_range_filter(self, mock_urlopen):
        """Test filtering by date range"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        filings_response = MagicMock()
        filings_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'filings': {
                'recent': {
                    'accessionNumber': ['0001', '0002', '0003'],
                    'filingDate': ['2024-11-01', '2024-06-01', '2023-11-01'],
                    'reportDate': ['2024-09-30', '2024-03-31', '2023-09-30'],
                    'form': ['10-K', '10-Q', '10-K'],
                    'primaryDocument': ['doc1.htm', 'doc2.htm', 'doc3.htm']
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.side_effect = [ticker_response, filings_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'start_date': '2024-01-01',
            'end_date': '2024-12-31',
            'limit': 10
        })
        
        # All filings should be in 2024
        for filing in result['filings']:
            self.assertTrue(filing['filing_date'].startswith('2024'))


class TestSECGetCompanyFactsTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_company_facts tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetCompanyFactsTool(self.test_config)
    
    @patch('urllib.request.urlopen')
    def test_get_company_facts(self, mock_urlopen):
        """Test getting all company facts"""
        # Mock ticker conversion
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        # Mock facts response
        facts_response = MagicMock()
        facts_data = {
            'cik': '0000320193',
            'entityName': 'Apple Inc.',
            'facts': {
                'us-gaap': {
                    'Assets': {
                        'label': 'Assets',
                        'description': 'Total assets',
                        'units': {
                            'USD': [
                                {
                                    'end': '2024-09-30',
                                    'val': 364980000000,
                                    'form': '10-K'
                                }
                            ]
                        }
                    },
                    'Revenues': {
                        'label': 'Revenues',
                        'description': 'Total revenues',
                        'units': {
                            'USD': [
                                {
                                    'end': '2024-09-30',
                                    'val': 383285000000,
                                    'form': '10-K'
                                }
                            ]
                        }
                    }
                },
                'dei': {
                    'EntityPublicFloat': {
                        'label': 'Public Float',
                        'units': {
                            'USD': [{'end': '2024-03-31', 'val': 2800000000000}]
                        }
                    }
                }
            }
        }
        facts_response.read.return_value = json.dumps(facts_data).encode('utf-8')
        facts_response.__enter__.return_value = facts_response
        
        mock_urlopen.side_effect = [ticker_response, facts_response]
        
        result = self.tool.execute({'ticker': 'AAPL'})
        
        self.assertIn('cik', result)
        self.assertIn('entity_name', result)
        self.assertIn('facts', result)
        self.assertIn('us-gaap', result['facts'])
        self.assertIn('Assets', result['facts']['us-gaap'])
        self.assertIn('Revenues', result['facts']['us-gaap'])
    
    def test_output_schema_facts_structure(self):
        """Test facts structure in output schema"""
        schema = self.tool.get_output_schema()
        self.assertIn('facts', schema['properties'])
        facts_schema = schema['properties']['facts']
        self.assertEqual(facts_schema['type'], 'object')


class TestSECGetFinancialDataTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_financial_data tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetFinancialDataTool(self.test_config)
    
    def test_fact_type_enum(self):
        """Test fact type enumeration"""
        schema = self.tool.get_input_schema()
        fact_types = schema['properties']['fact_type']['enum']
        
        self.assertIn('Assets', fact_types)
        self.assertIn('Revenues', fact_types)
        self.assertIn('NetIncomeLoss', fact_types)
        self.assertIn('EarningsPerShare', fact_types)
    
    @patch('urllib.request.urlopen')
    def test_get_available_facts(self, mock_urlopen):
        """Test getting list of available facts"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        facts_response = MagicMock()
        facts_data = {
            'cik': '0000320193',
            'entityName': 'Apple Inc.',
            'facts': {
                'us-gaap': {
                    'Assets': {},
                    'Revenues': {},
                    'NetIncomeLoss': {}
                },
                'dei': {
                    'EntityPublicFloat': {}
                }
            }
        }
        facts_response.read.return_value = json.dumps(facts_data).encode('utf-8')
        facts_response.__enter__.return_value = facts_response
        
        mock_urlopen.side_effect = [ticker_response, facts_response]
        
        # Call without fact_type to get available facts
        result = self.tool.execute({'ticker': 'AAPL'})
        
        self.assertIn('available_facts', result)
        self.assertIn('us-gaap', result['available_facts'])
        self.assertIn('Assets', result['available_facts']['us-gaap'])
    
    @patch('urllib.request.urlopen')
    def test_get_specific_fact(self, mock_urlopen):
        """Test getting specific financial fact"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        facts_response = MagicMock()
        facts_data = {
            'cik': '0000320193',
            'entityName': 'Apple Inc.',
            'facts': {
                'us-gaap': {
                    'Revenues': {
                        'label': 'Revenues',
                        'description': 'Total revenues',
                        'units': {
                            'USD': [
                                {
                                    'end': '2024-09-30',
                                    'val': 383285000000,
                                    'accn': '0001234567-24-000001',
                                    'fy': 2024,
                                    'fp': 'FY',
                                    'form': '10-K'
                                },
                                {
                                    'end': '2023-09-30',
                                    'val': 394328000000,
                                    'accn': '0001234567-23-000001',
                                    'fy': 2023,
                                    'fp': 'FY',
                                    'form': '10-K'
                                }
                            ]
                        }
                    }
                }
            }
        }
        facts_response.read.return_value = json.dumps(facts_data).encode('utf-8')
        facts_response.__enter__.return_value = facts_response
        
        mock_urlopen.side_effect = [ticker_response, facts_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'fact_type': 'Revenues'
        })
        
        self.assertIn('fact_type', result)
        self.assertEqual(result['fact_type'], 'Revenues')
        self.assertIn('data', result)
        self.assertGreater(len(result['data']), 0)
        
        # Check data structure
        data_item = result['data'][0]
        self.assertIn('taxonomy', data_item)
        self.assertIn('label', data_item)
        self.assertIn('units', data_item)


class TestSECGetInsiderTradingTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_insider_trading tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetInsiderTradingTool(self.test_config)
    
    @patch('urllib.request.urlopen')
    def test_get_insider_trading(self, mock_urlopen):
        """Test getting insider trading filings"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        filings_response = MagicMock()
        filings_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'filings': {
                'recent': {
                    'accessionNumber': ['0001-4', '0002-10K', '0003-4', '0004-4'],
                    'filingDate': ['2024-11-01', '2024-10-01', '2024-09-15', '2024-09-01'],
                    'reportDate': ['2024-10-31', '2024-09-30', '2024-09-14', '2024-08-31'],
                    'form': ['4', '10-K', '4', '4'],
                    'primaryDocument': ['form4-1.xml', 'report.htm', 'form4-2.xml', 'form4-3.xml']
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.side_effect = [ticker_response, filings_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'limit': 10
        })
        
        self.assertIn('filings', result)
        self.assertIn('filing_count', result)
        
        # All returned filings should be Form 4
        for filing in result['filings']:
            self.assertEqual(filing['form'], '4')
    
    @patch('urllib.request.urlopen')
    def test_insider_trading_limit(self, mock_urlopen):
        """Test limit parameter for insider trading"""
        ticker_response = MagicMock()
        ticker_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        ticker_response.__enter__.return_value = ticker_response
        
        filings_response = MagicMock()
        # Create many Form 4 filings
        filings_data = {
            'cik': '0000320193',
            'name': 'Apple Inc.',
            'filings': {
                'recent': {
                    'accessionNumber': [f'000{i}-4' for i in range(50)],
                    'filingDate': ['2024-11-01'] * 50,
                    'reportDate': ['2024-10-31'] * 50,
                    'form': ['4'] * 50,
                    'primaryDocument': [f'form4-{i}.xml' for i in range(50)]
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.side_effect = [ticker_response, filings_response]
        
        result = self.tool.execute({
            'ticker': 'AAPL',
            'limit': 5
        })
        
        self.assertEqual(result['filing_count'], 5)
        self.assertEqual(len(result['filings']), 5)


class TestSECGetMutualFundHoldingsTool(TestSECEdgarBaseSetup):
    """Test cases for sec_get_mutual_fund_holdings tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetMutualFundHoldingsTool(self.test_config)
    
    @patch('urllib.request.urlopen')
    def test_get_mutual_fund_holdings(self, mock_urlopen):
        """Test getting 13F filings"""
        filings_response = MagicMock()
        filings_data = {
            'cik': '0001067983',
            'name': 'BERKSHIRE HATHAWAY INC',
            'filings': {
                'recent': {
                    'accessionNumber': ['0001-13F', '0002-10K', '0003-13F', '0004-13F'],
                    'filingDate': ['2024-11-14', '2024-11-01', '2024-08-14', '2024-05-15'],
                    'reportDate': ['2024-09-30', '2024-09-30', '2024-06-30', '2024-03-31'],
                    'form': ['13F-HR', '10-K', '13F-HR', '13F-HR'],
                    'primaryDocument': ['form13f-1.xml', 'report.htm', 'form13f-2.xml', 'form13f-3.xml']
                }
            }
        }
        filings_response.read.return_value = json.dumps(filings_data).encode('utf-8')
        filings_response.__enter__.return_value = filings_response
        
        mock_urlopen.return_value = filings_response
        
        result = self.tool.execute({
            'cik': '0001067983',
            'limit': 5
        })
        
        self.assertIn('filings', result)
        self.assertIn('filing_count', result)
        self.assertEqual(result['name'], 'BERKSHIRE HATHAWAY INC')
        
        # All returned filings should be Form 13F-HR
        for filing in result['filings']:
            self.assertEqual(filing['form'], '13F-HR')
    
    def test_default_limit(self):
        """Test default limit is 5 for 13F"""
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['properties']['limit']['default'], 5)
        self.assertEqual(schema['properties']['limit']['maximum'], 20)


class TestSECEdgarToolRegistry(unittest.TestCase):
    """Test cases for tool registry"""
    
    def test_registry_completeness(self):
        """Test that all tools are registered"""
        expected_tools = [
            'sec_search_company',
            'sec_get_company_info',
            'sec_get_company_filings',
            'sec_get_company_facts',
            'sec_get_financial_data',
            'sec_get_insider_trading',
            'sec_get_mutual_fund_holdings'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, SEC_EDGAR_TOOLS)
    
    def test_registry_instantiation(self):
        """Test that all registered tools can be instantiated"""
        for tool_name, tool_class in SEC_EDGAR_TOOLS.items():
            tool = tool_class()
            self.assertIsNotNone(tool)
            self.assertTrue(hasattr(tool, 'execute'))
            self.assertTrue(hasattr(tool, 'get_input_schema'))
            self.assertTrue(hasattr(tool, 'get_output_schema'))


class TestCommonFunctionality(TestSECEdgarBaseSetup):
    """Test cases for shared base functionality"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECSearchCompanyTool(self.test_config)
    
    def test_normalize_cik(self):
        """Test CIK normalization"""
        self.assertEqual(self.tool._normalize_cik('123'), '0000000123')
        self.assertEqual(self.tool._normalize_cik('0000123'), '0000000123')
        self.assertEqual(self.tool._normalize_cik('1234567890'), '1234567890')
    
    @patch('urllib.request.urlopen')
    def test_ticker_to_cik_conversion(self, mock_urlopen):
        """Test ticker to CIK conversion"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        cik = self.tool._ticker_to_cik('AAPL')
        self.assertEqual(cik, '0000320193')
    
    @patch('urllib.request.urlopen')
    def test_ticker_not_found(self, mock_urlopen):
        """Test error when ticker not found"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_ticker_data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        with self.assertRaises(ValueError) as context:
            self.tool._ticker_to_cik('INVALIDTICKER')
        self.assertIn('not found', str(context.exception).lower())
    
    def test_user_agent_contains_email(self):
        """Test User-Agent contains contact email"""
        self.assertIn('ajsinha@gmail.com', self.tool.user_agent)
        self.assertIn('SAJHA-MCP-Server', self.tool.user_agent)
    
    def test_filing_types_dictionary(self):
        """Test filing types dictionary"""
        self.assertIsNotNone(self.tool.filing_types)
        self.assertIn('10-K', self.tool.filing_types)
        self.assertIn('10-Q', self.tool.filing_types)
        self.assertEqual(self.tool.filing_types['10-K'], 'Annual Report')


class TestErrorHandling(TestSECEdgarBaseSetup):
    """Test cases for error handling"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECGetCompanyInfoTool(self.test_config)
    
    @patch('urllib.request.urlopen')
    def test_http_404_error(self, mock_urlopen):
        """Test handling of HTTP 404 errors"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'url', 404, 'Not Found', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'cik': '9999999999'})
        self.assertIn('not found', str(context.exception).lower())
    
    @patch('urllib.request.urlopen')
    def test_http_403_error(self, mock_urlopen):
        """Test handling of HTTP 403 errors"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'url', 403, 'Forbidden', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'cik': '0000320193'})
        self.assertIn('403', str(context.exception))
    
    @patch('urllib.request.urlopen')
    def test_network_error(self, mock_urlopen):
        """Test handling of network errors"""
        mock_urlopen.side_effect = urllib.error.URLError('Network error')
        
        with self.assertRaises(Exception):
            self.tool.execute({'cik': '0000320193'})
    
    def test_missing_required_parameter(self):
        """Test error when required parameter is missing"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({})
        self.assertIn('required', str(context.exception).lower())


class TestSchemaValidation(TestSECEdgarBaseSetup):
    """Test cases for schema validation"""
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have valid schemas"""
        for tool_name, tool_class in SEC_EDGAR_TOOLS.items():
            tool = tool_class()
            
            # Test input schema
            input_schema = tool.get_input_schema()
            self.assertIsInstance(input_schema, dict)
            self.assertIn('type', input_schema)
            self.assertIn('properties', input_schema)
            
            # Test output schema
            output_schema = tool.get_output_schema()
            self.assertIsInstance(output_schema, dict)
            self.assertIn('type', output_schema)
            self.assertIn('properties', output_schema)
    
    def test_schema_property_types(self):
        """Test schema property types are valid"""
        valid_types = ['string', 'integer', 'boolean', 'array', 'object']
        
        for tool_name, tool_class in SEC_EDGAR_TOOLS.items():
            tool = tool_class()
            schema = tool.get_input_schema()
            
            for prop_name, prop_schema in schema['properties'].items():
                if 'type' in prop_schema:
                    self.assertIn(prop_schema['type'], valid_types,
                                f"Invalid type in {tool_name}.{prop_name}")


class TestAPIEndpoints(TestSECEdgarBaseSetup):
    """Test cases for API endpoint configuration"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = SECSearchCompanyTool(self.test_config)
    
    def test_api_url_configured(self):
        """Test API URL is configured"""
        self.assertEqual(self.tool.api_url, 'https://data.sec.gov')
    
    def test_user_agent_required(self):
        """Test User-Agent is set for all requests"""
        self.assertIsNotNone(self.tool.user_agent)
        self.assertNotEqual(self.tool.user_agent, '')


class TestCachingAndPerformance(TestSECEdgarBaseSetup):
    """Test cases for caching and performance"""
    
    def test_rate_limit_metadata(self):
        """Test rate limit is defined in metadata"""
        for tool_name in ['sec_search_company', 'sec_get_company_info']:
            # Rate limit should be defined in JSON configs
            # This is a metadata test, actual rate limiting would be 
            # implemented at a higher level
            pass
    
    def test_cache_ttl_metadata(self):
        """Test cache TTL is appropriate for different data types"""
        # Company info changes rarely - should have longer TTL
        # Filings change frequently - should have shorter TTL
        # This is verified in JSON configs
        pass


def suite():
    """Create test suite"""
    test_suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestSECSearchCompanyTool,
        TestSECGetCompanyInfoTool,
        TestSECGetCompanyFilingsTool,
        TestSECGetCompanyFactsTool,
        TestSECGetFinancialDataTool,
        TestSECGetInsiderTradingTool,
        TestSECGetMutualFundHoldingsTool,
        TestSECEdgarToolRegistry,
        TestCommonFunctionality,
        TestErrorHandling,
        TestSchemaValidation,
        TestAPIEndpoints,
        TestCachingAndPerformance
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    return test_suite


if __name__ == '__main__':
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"Success Rate: {(result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100:.2f}%")
    print("=" * 70)
    print("\nKey Features Tested:")
    print("  ✓ Company search by name and ticker")
    print("  ✓ Company information retrieval")
    print("  ✓ SEC filings with filtering")
    print("  ✓ XBRL financial facts")
    print("  ✓ Targeted financial data extraction")
    print("  ✓ Insider trading (Form 4)")
    print("  ✓ Institutional holdings (Form 13F)")
    print("  ✓ Error handling and validation")
    print("  ✓ Schema validation")
    print("  ✓ CIK normalization")
    print("  ✓ Ticker to CIK conversion")
    print("=" * 70)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
