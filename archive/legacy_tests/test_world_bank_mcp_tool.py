"""
Copyright All rights reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Comprehensive Test Suite for World Bank MCP Tools
Tests all ten tools with various scenarios including success and error cases
"""

import unittest
import json
from typing import Dict, Any, List
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


# Mock BaseMCPTool for testing
class BaseMCPTool:
    """Mock base class for testing"""
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.name = self.config.get('name', 'test_tool')
        
    class Logger:
        def info(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass
        def debug(self, msg): pass
    
    logger = Logger()


# Import the tools (in real scenario, adjust import path)
try:
    from world_bank_tool import (
        WBGetCountriesTool,
        WBGetIndicatorsTool,
        WBGetCountryDataTool,
        WBGetIndicatorDataTool,
        WBSearchIndicatorsTool,
        WBCompareCountriesTool,
        WBGetIncomeLevelsTool,
        WBGetLendingTypesTool,
        WBGetRegionsTool,
        WBGetTopicIndicatorsTool,
        WORLD_BANK_TOOLS
    )
except ImportError:
    print("Warning: Could not import tools. Using mock implementations for testing structure.")


class TestWorldBankToolsBase(unittest.TestCase):
    """Base test class with common setup and utilities"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.config = {}
        
        # Mock World Bank API responses
        cls.mock_countries = [
            {
                'page': 1,
                'pages': 1,
                'per_page': 300,
                'total': 3
            },
            [
                {
                    'id': 'US',
                    'iso2Code': 'US',
                    'name': 'United States',
                    'capitalCity': 'Washington D.C.',
                    'longitude': '-77.0369',
                    'latitude': '38.8951',
                    'region': {
                        'id': 'NAC',
                        'value': 'North America'
                    },
                    'incomeLevel': {
                        'id': 'HIC',
                        'value': 'High income'
                    },
                    'lendingType': {
                        'id': 'LNX',
                        'value': 'Not classified'
                    }
                },
                {
                    'id': 'IN',
                    'iso2Code': 'IN',
                    'name': 'India',
                    'capitalCity': 'New Delhi',
                    'longitude': '77.225',
                    'latitude': '28.6353',
                    'region': {
                        'id': 'SAS',
                        'value': 'South Asia'
                    },
                    'incomeLevel': {
                        'id': 'LMC',
                        'value': 'Lower middle income'
                    },
                    'lendingType': {
                        'id': 'IBD',
                        'value': 'IBRD'
                    }
                },
                {
                    'id': 'CN',
                    'iso2Code': 'CN',
                    'name': 'China',
                    'capitalCity': 'Beijing',
                    'longitude': '116.286',
                    'latitude': '40.0495',
                    'region': {
                        'id': 'EAS',
                        'value': 'East Asia & Pacific'
                    },
                    'incomeLevel': {
                        'id': 'UMC',
                        'value': 'Upper middle income'
                    },
                    'lendingType': {
                        'id': 'IBD',
                        'value': 'IBRD'
                    }
                }
            ]
        ]
        
        # Mock indicators
        cls.mock_indicators = [
            {
                'page': 1,
                'pages': 2,
                'per_page': 2,
                'total': 3
            },
            [
                {
                    'id': 'NY.GDP.MKTP.CD',
                    'name': 'GDP (current US$)',
                    'source': {
                        'id': '2',
                        'value': 'World Development Indicators'
                    },
                    'sourceNote': 'GDP at purchaser\'s prices...',
                    'sourceOrganization': 'World Bank national accounts data',
                    'topics': [
                        {'id': '3', 'value': 'Economy & Growth'}
                    ]
                },
                {
                    'id': 'SP.POP.TOTL',
                    'name': 'Population, total',
                    'source': {
                        'id': '2',
                        'value': 'World Development Indicators'
                    },
                    'sourceNote': 'Total population is based on...',
                    'sourceOrganization': 'World Bank staff estimates',
                    'topics': [
                        {'id': '19', 'value': 'Climate Change'}
                    ]
                }
            ]
        ]
        
        # Mock country data (time series)
        cls.mock_country_data = [
            {
                'page': 1,
                'pages': 1,
                'per_page': 100,
                'total': 3
            },
            [
                {
                    'indicator': {
                        'id': 'NY.GDP.MKTP.CD',
                        'value': 'GDP (current US$)'
                    },
                    'country': {
                        'id': 'US',
                        'value': 'United States'
                    },
                    'value': '27360935000000',
                    'date': '2023',
                    'decimal': 0
                },
                {
                    'indicator': {
                        'id': 'NY.GDP.MKTP.CD',
                        'value': 'GDP (current US$)'
                    },
                    'country': {
                        'id': 'US',
                        'value': 'United States'
                    },
                    'value': '25464475000000',
                    'date': '2022',
                    'decimal': 0
                },
                {
                    'indicator': {
                        'id': 'NY.GDP.MKTP.CD',
                        'value': 'GDP (current US$)'
                    },
                    'country': {
                        'id': 'US',
                        'value': 'United States'
                    },
                    'value': '23315081000000',
                    'date': '2021',
                    'decimal': 0
                }
            ]
        ]
    
    def _validate_success_response(self, response: Dict[str, Any]):
        """Validate response structure"""
        self.assertIsInstance(response, dict)
        self.assertIn('last_updated', response)
    
    def _mock_api_response(self, mock_urlopen, data):
        """Helper to mock API response"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response


class TestWBGetCountriesTool(TestWorldBankToolsBase):
    """Test cases for wb_get_countries tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetCountriesTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_all_countries(self, mock_urlopen):
        """Test getting all countries"""
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        result = self.tool.execute({})
        
        self._validate_success_response(result)
        self.assertIn('total_countries', result)
        self.assertIn('countries', result)
        self.assertGreater(result['total_countries'], 0)
    
    @patch('urllib.request.urlopen')
    def test_filter_by_income_level(self, mock_urlopen):
        """Test filtering by income level"""
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        result = self.tool.execute({
            'income_level': 'HIC'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['filters_applied']['income_level'], 'HIC')
    
    @patch('urllib.request.urlopen')
    def test_filter_by_region(self, mock_urlopen):
        """Test filtering by region"""
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        result = self.tool.execute({
            'region': 'SAS'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['filters_applied']['region'], 'SAS')
    
    @patch('urllib.request.urlopen')
    def test_filter_by_lending_type(self, mock_urlopen):
        """Test filtering by lending type"""
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        result = self.tool.execute({
            'lending_type': 'IBD'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['filters_applied']['lending_type'], 'IBD')
    
    @patch('urllib.request.urlopen')
    def test_country_structure(self, mock_urlopen):
        """Test country object structure"""
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        result = self.tool.execute({})
        
        for country in result['countries']:
            self.assertIn('id', country)
            self.assertIn('name', country)
            self.assertIn('capital', country)
            self.assertIn('region', country)
            self.assertIn('income_level', country)
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('properties', schema)
        self.assertIn('income_level', schema['properties'])
        self.assertIn('region', schema['properties'])
        self.assertIn('lending_type', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        self.assertIn('properties', schema)
        self.assertIn('total_countries', schema['properties'])
        self.assertIn('countries', schema['properties'])


class TestWBGetIndicatorsTool(TestWorldBankToolsBase):
    """Test cases for wb_get_indicators tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetIndicatorsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_indicators(self, mock_urlopen):
        """Test getting indicators"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'per_page': 2
        })
        
        self._validate_success_response(result)
        self.assertIn('indicators', result)
        self.assertIn('total_indicators', result)
        self.assertGreater(result['total_indicators'], 0)
    
    @patch('urllib.request.urlopen')
    def test_filter_by_topic(self, mock_urlopen):
        """Test filtering by topic"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'topic_id': 8,
            'per_page': 10
        })
        
        self._validate_success_response(result)
    
    @patch('urllib.request.urlopen')
    def test_pagination(self, mock_urlopen):
        """Test pagination"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'page': 2,
            'per_page': 50
        })
        
        self._validate_success_response(result)
        self.assertIn('page', result)
        self.assertIn('total_pages', result)
    
    @patch('urllib.request.urlopen')
    def test_indicator_structure(self, mock_urlopen):
        """Test indicator object structure"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({})
        
        for indicator in result['indicators']:
            self.assertIn('id', indicator)
            self.assertIn('name', indicator)
            self.assertIn('source', indicator)


class TestWBGetCountryDataTool(TestWorldBankToolsBase):
    """Test cases for wb_get_country_data tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetCountryDataTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_country_data_with_shorthand(self, mock_urlopen):
        """Test getting country data with indicator shorthand"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'country_code': 'US',
            'indicator': 'gdp',
            'start_year': 2020,
            'end_year': 2023
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['country']['id'], 'US')
        self.assertIn('data', result)
        self.assertIn('data_points', result)
    
    @patch('urllib.request.urlopen')
    def test_get_country_data_with_code(self, mock_urlopen):
        """Test getting country data with direct indicator code"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'country_code': 'US',
            'indicator_code': 'NY.GDP.MKTP.CD',
            'start_year': 2020,
            'end_year': 2023
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['indicator']['id'], 'NY.GDP.MKTP.CD')
    
    def test_required_parameters(self):
        """Test that country_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_code', schema['required'])
    
    def test_indicator_or_code_required(self):
        """Test that either indicator or indicator_code must be provided"""
        with self.assertRaises(ValueError):
            self.tool.execute({
                'country_code': 'US'
            })
    
    def test_unknown_indicator(self):
        """Test handling of unknown indicator shorthand"""
        with self.assertRaises(ValueError):
            self.tool.execute({
                'country_code': 'US',
                'indicator': 'unknown_indicator'
            })
    
    @patch('urllib.request.urlopen')
    def test_data_point_structure(self, mock_urlopen):
        """Test data point structure"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'country_code': 'US',
            'indicator': 'gdp'
        })
        
        for point in result['data']:
            self.assertIn('year', point)
            self.assertIn('value', point)
            self.assertIsInstance(point['year'], int)


class TestWBGetIndicatorDataTool(TestWorldBankToolsBase):
    """Test cases for wb_get_indicator_data tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetIndicatorDataTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_indicator_data(self, mock_urlopen):
        """Test getting cross-country indicator data"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'indicator': 'gdp',
            'year': 2023
        })
        
        self._validate_success_response(result)
        self.assertIn('indicator', result)
        self.assertIn('data', result)
        self.assertIn('country_count', result)
    
    @patch('urllib.request.urlopen')
    def test_filter_by_income_level(self, mock_urlopen):
        """Test filtering by income level"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'indicator': 'gdp_per_capita',
            'income_level': 'HIC',
            'year': 2023
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['filters_applied']['income_level'], 'HIC')
    
    @patch('urllib.request.urlopen')
    def test_filter_by_region(self, mock_urlopen):
        """Test filtering by region"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'indicator': 'population',
            'region': 'SAS',
            'year': 2023
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['filters_applied']['region'], 'SAS')
    
    @patch('urllib.request.urlopen')
    def test_year_range(self, mock_urlopen):
        """Test year range filter"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'indicator': 'gdp',
            'start_year': 2010,
            'end_year': 2023
        })
        
        self._validate_success_response(result)
        self.assertIn('year_filter', result)


class TestWBSearchIndicatorsTool(TestWorldBankToolsBase):
    """Test cases for wb_search_indicators tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBSearchIndicatorsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_search_indicators(self, mock_urlopen):
        """Test searching indicators"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'search_term': 'gdp'
        })
        
        self._validate_success_response(result)
        self.assertIn('search_term', result)
        self.assertIn('total_results', result)
        self.assertIn('results', result)
    
    @patch('urllib.request.urlopen')
    def test_search_with_topic_filter(self, mock_urlopen):
        """Test search with topic filter"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'search_term': 'population',
            'topic_id': 19
        })
        
        self._validate_success_response(result)
    
    def test_search_term_required(self):
        """Test that search_term is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('search_term', schema['required'])
    
    @patch('urllib.request.urlopen')
    def test_relevance_scoring(self, mock_urlopen):
        """Test relevance scoring in results"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'search_term': 'gdp'
        })
        
        for item in result['results']:
            self.assertIn('relevance_score', item)
            self.assertIsInstance(item['relevance_score'], float)
            self.assertGreaterEqual(item['relevance_score'], 0.0)
            self.assertLessEqual(item['relevance_score'], 1.0)


class TestWBCompareCountriesTool(TestWorldBankToolsBase):
    """Test cases for wb_compare_countries tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBCompareCountriesTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_compare_countries(self, mock_urlopen):
        """Test comparing multiple countries"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'country_codes': ['US', 'CHN', 'IND'],
            'indicator': 'gdp',
            'start_year': 2020,
            'end_year': 2023
        })
        
        self._validate_success_response(result)
        self.assertIn('countries', result)
        self.assertIn('summary', result)
        self.assertIn('indicator', result)
    
    def test_country_codes_required(self):
        """Test that country_codes is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_codes', schema['required'])
    
    def test_min_countries(self):
        """Test minimum country requirement"""
        schema = self.tool.get_input_schema()
        
        codes_prop = schema['properties']['country_codes']
        self.assertEqual(codes_prop['minItems'], 2)
    
    def test_max_countries(self):
        """Test maximum country limit"""
        schema = self.tool.get_input_schema()
        
        codes_prop = schema['properties']['country_codes']
        self.assertEqual(codes_prop['maxItems'], 10)
    
    @patch('urllib.request.urlopen')
    def test_comparison_statistics(self, mock_urlopen):
        """Test that comparison includes statistics"""
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        result = self.tool.execute({
            'country_codes': ['US', 'CHN'],
            'indicator': 'gdp_per_capita',
            'most_recent_year': True
        })
        
        for country_data in result['countries']:
            self.assertIn('latest_value', country_data)
            self.assertIn('average', country_data)
            self.assertIn('min', country_data)
            self.assertIn('max', country_data)


class TestWBGetIncomeLevelsTool(TestWorldBankToolsBase):
    """Test cases for wb_get_income_levels tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetIncomeLevelsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_income_levels(self, mock_urlopen):
        """Test getting income levels"""
        mock_data = [
            {'page': 1, 'pages': 1, 'per_page': 50, 'total': 4},
            [
                {'id': 'HIC', 'iso2code': 'XD', 'name': 'High income'},
                {'id': 'UMC', 'iso2code': 'XT', 'name': 'Upper middle income'},
                {'id': 'LMC', 'iso2code': 'XN', 'name': 'Lower middle income'},
                {'id': 'LIC', 'iso2code': 'XM', 'name': 'Low income'}
            ]
        ]
        
        self._mock_api_response(mock_urlopen, mock_data)
        
        result = self.tool.execute({})
        
        self._validate_success_response(result)
        self.assertIn('income_levels', result)
        self.assertIn('total_levels', result)
        self.assertIn('descriptions', result)
    
    @patch('urllib.request.urlopen')
    def test_income_level_structure(self, mock_urlopen):
        """Test income level object structure"""
        mock_data = [
            {'page': 1, 'pages': 1, 'per_page': 50, 'total': 1},
            [
                {'id': 'HIC', 'iso2code': 'XD', 'name': 'High income'}
            ]
        ]
        
        self._mock_api_response(mock_urlopen, mock_data)
        
        result = self.tool.execute({})
        
        for level in result['income_levels']:
            self.assertIn('id', level)
            self.assertIn('value', level)


class TestWBGetLendingTypesTool(TestWorldBankToolsBase):
    """Test cases for wb_get_lending_types tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetLendingTypesTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_lending_types(self, mock_urlopen):
        """Test getting lending types"""
        mock_data = [
            {'page': 1, 'pages': 1, 'per_page': 50, 'total': 4},
            [
                {'id': 'IBD', 'iso2code': 'XI', 'name': 'IBRD'},
                {'id': 'IDB', 'iso2code': 'XF', 'name': 'Blend'},
                {'id': 'IDX', 'iso2code': 'XH', 'name': 'IDA'},
                {'id': 'LNX', 'iso2code': 'XX', 'name': 'Not classified'}
            ]
        ]
        
        self._mock_api_response(mock_urlopen, mock_data)
        
        result = self.tool.execute({})
        
        self._validate_success_response(result)
        self.assertIn('lending_types', result)
        self.assertIn('total_types', result)
        self.assertIn('descriptions', result)


class TestWBGetRegionsTool(TestWorldBankToolsBase):
    """Test cases for wb_get_regions tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetRegionsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_regions(self, mock_urlopen):
        """Test getting regions"""
        mock_data = [
            {'page': 1, 'pages': 1, 'per_page': 50, 'total': 8},
            [
                {'id': 'EAS', 'iso2code': 'Z4', 'name': 'East Asia & Pacific', 'code': 'EAS'},
                {'id': 'ECS', 'iso2code': 'Z7', 'name': 'Europe & Central Asia', 'code': 'ECS'},
                {'id': 'LCN', 'iso2code': 'ZJ', 'name': 'Latin America & Caribbean', 'code': 'LCN'},
                {'id': 'MEA', 'iso2code': 'ZQ', 'name': 'Middle East & North Africa', 'code': 'MEA'},
                {'id': 'NAC', 'iso2code': 'XU', 'name': 'North America', 'code': 'NAC'},
                {'id': 'SAS', 'iso2code': '8S', 'name': 'South Asia', 'code': 'SAS'},
                {'id': 'SSF', 'iso2code': 'ZG', 'name': 'Sub-Saharan Africa', 'code': 'SSF'},
                {'id': 'WLD', 'iso2code': '1W', 'name': 'World', 'code': 'WLD'}
            ]
        ]
        
        self._mock_api_response(mock_urlopen, mock_data)
        
        result = self.tool.execute({})
        
        self._validate_success_response(result)
        self.assertIn('regions', result)
        self.assertIn('total_regions', result)
        self.assertIn('descriptions', result)
        self.assertEqual(result['total_regions'], 8)


class TestWBGetTopicIndicatorsTool(TestWorldBankToolsBase):
    """Test cases for wb_get_topic_indicators tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = WBGetTopicIndicatorsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_topic_indicators(self, mock_urlopen):
        """Test getting indicators for a topic"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'topic_id': 8,  # Health
            'per_page': 50
        })
        
        self._validate_success_response(result)
        self.assertIn('topic', result)
        self.assertIn('indicators', result)
        self.assertIn('total_indicators', result)
        self.assertEqual(result['topic']['id'], 8)
    
    def test_topic_id_required(self):
        """Test that topic_id is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('topic_id', schema['required'])
    
    def test_topic_id_range(self):
        """Test topic_id range validation"""
        schema = self.tool.get_input_schema()
        
        topic_prop = schema['properties']['topic_id']
        self.assertEqual(topic_prop['minimum'], 1)
        self.assertEqual(topic_prop['maximum'], 21)
    
    @patch('urllib.request.urlopen')
    def test_topic_information(self, mock_urlopen):
        """Test that topic information is included"""
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        result = self.tool.execute({
            'topic_id': 4  # Education
        })
        
        topic = result['topic']
        self.assertIn('id', topic)
        self.assertIn('name', topic)
        self.assertIn('description', topic)


class TestWorldBankToolRegistry(TestWorldBankToolsBase):
    """Test cases for tool registry and integration"""
    
    def test_registry_exists(self):
        """Test that tool registry exists"""
        self.assertIsNotNone(WORLD_BANK_TOOLS)
        self.assertIsInstance(WORLD_BANK_TOOLS, dict)
    
    def test_all_tools_registered(self):
        """Test that all 10 tools are registered"""
        expected_tools = [
            'wb_get_countries',
            'wb_get_indicators',
            'wb_get_country_data',
            'wb_get_indicator_data',
            'wb_search_indicators',
            'wb_compare_countries',
            'wb_get_income_levels',
            'wb_get_lending_types',
            'wb_get_regions',
            'wb_get_topic_indicators'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, WORLD_BANK_TOOLS)
    
    def test_tool_instantiation_from_registry(self):
        """Test creating tools from registry"""
        for tool_name, tool_class in WORLD_BANK_TOOLS.items():
            tool = tool_class(self.config)
            self.assertIsNotNone(tool)
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have input and output schemas"""
        for tool_name, tool_class in WORLD_BANK_TOOLS.items():
            tool = tool_class(self.config)
            
            input_schema = tool.get_input_schema()
            output_schema = tool.get_output_schema()
            
            self.assertIsInstance(input_schema, dict)
            self.assertIsInstance(output_schema, dict)
    
    def test_all_tools_have_execute(self):
        """Test that all tools have execute method"""
        for tool_name, tool_class in WORLD_BANK_TOOLS.items():
            tool = tool_class(self.config)
            self.assertTrue(hasattr(tool, 'execute'))
            self.assertTrue(callable(tool.execute))


class TestIndicatorMappings(TestWorldBankToolsBase):
    """Test indicator shorthand mappings"""
    
    def test_indicator_map_exists(self):
        """Test that indicator map exists"""
        from world_bank_tool import WorldBankBaseTool
        
        tool = WorldBankBaseTool({})
        self.assertIsInstance(tool.indicator_map, dict)
        self.assertGreater(len(tool.indicator_map), 0)
    
    def test_common_indicators_mapped(self):
        """Test that common indicators are mapped"""
        from world_bank_tool import WorldBankBaseTool
        
        tool = WorldBankBaseTool({})
        
        common_indicators = [
            'gdp', 'gdp_per_capita', 'population', 'life_expectancy',
            'unemployment', 'inflation', 'co2_emissions'
        ]
        
        for indicator in common_indicators:
            self.assertIn(indicator, tool.indicator_map)
    
    def test_indicator_codes_format(self):
        """Test indicator code format"""
        from world_bank_tool import WorldBankBaseTool
        
        tool = WorldBankBaseTool({})
        
        for shorthand, code in tool.indicator_map.items():
            self.assertIsInstance(shorthand, str)
            self.assertIsInstance(code, str)
            self.assertGreater(len(code), 0)


class TestInputValidation(TestWorldBankToolsBase):
    """Test input parameter validation"""
    
    def test_country_code_pattern(self):
        """Test country code pattern validation"""
        tool = WBGetCountryDataTool({})
        schema = tool.get_input_schema()
        
        code_prop = schema['properties']['country_code']
        self.assertIn('pattern', code_prop)
        self.assertEqual(code_prop['pattern'], '^[A-Z]{2,3}$')
    
    def test_year_range_validation(self):
        """Test year parameter ranges"""
        tool = WBGetCountryDataTool({})
        schema = tool.get_input_schema()
        
        start_prop = schema['properties']['start_year']
        self.assertEqual(start_prop['minimum'], 1960)
        self.assertEqual(start_prop['maximum'], 2030)
        
        end_prop = schema['properties']['end_year']
        self.assertEqual(end_prop['minimum'], 1960)
        self.assertEqual(end_prop['maximum'], 2030)
    
    def test_per_page_limits(self):
        """Test per_page limits"""
        tool = WBGetIndicatorsTool({})
        schema = tool.get_input_schema()
        
        per_page_prop = schema['properties']['per_page']
        self.assertEqual(per_page_prop['minimum'], 1)
        self.assertEqual(per_page_prop['maximum'], 1000)


class TestIntegrationScenarios(TestWorldBankToolsBase):
    """Integration test scenarios"""
    
    @patch('urllib.request.urlopen')
    def test_country_analysis_workflow(self, mock_urlopen):
        """Test workflow: list countries -> get data -> compare"""
        # Step 1: Get countries
        self._mock_api_response(mock_urlopen, self.mock_countries)
        
        countries_tool = WBGetCountriesTool({})
        countries = countries_tool.execute({'region': 'SAS'})
        
        self.assertGreater(countries['total_countries'], 0)
        
        # Step 2: Get country data
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        data_tool = WBGetCountryDataTool({})
        data = data_tool.execute({
            'country_code': 'IND',
            'indicator': 'gdp',
            'start_year': 2020,
            'end_year': 2023
        })
        
        self._validate_success_response(data)
        
        # Step 3: Compare countries
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        compare_tool = WBCompareCountriesTool({})
        comparison = compare_tool.execute({
            'country_codes': ['IND', 'CHN'],
            'indicator': 'gdp',
            'start_year': 2020,
            'end_year': 2023
        })
        
        self._validate_success_response(comparison)
    
    @patch('urllib.request.urlopen')
    def test_indicator_discovery_workflow(self, mock_urlopen):
        """Test workflow: search -> get details -> fetch data"""
        # Step 1: Search indicators
        self._mock_api_response(mock_urlopen, self.mock_indicators)
        
        search_tool = WBSearchIndicatorsTool({})
        search = search_tool.execute({
            'search_term': 'gdp'
        })
        
        self._validate_success_response(search)
        
        # Step 2: Get indicator data across countries
        self._mock_api_response(mock_urlopen, self.mock_country_data)
        
        indicator_tool = WBGetIndicatorDataTool({})
        data = indicator_tool.execute({
            'indicator': 'gdp',
            'year': 2023
        })
        
        self._validate_success_response(data)


class TestErrorHandling(TestWorldBankToolsBase):
    """Test error handling scenarios"""
    
    @patch('urllib.request.urlopen')
    def test_http_404_error(self, mock_urlopen):
        """Test handling of HTTP 404 errors"""
        import urllib.error
        
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'http://test.com', 404, 'Not Found', {}, None
        )
        
        tool = WBGetCountryDataTool({})
        
        with self.assertRaises(ValueError) as context:
            tool.execute({
                'country_code': 'XYZ',
                'indicator': 'gdp'
            })
        
        self.assertIn('404', str(context.exception))
    
    @patch('urllib.request.urlopen')
    def test_network_timeout(self, mock_urlopen):
        """Test handling of network timeouts"""
        import socket
        
        mock_urlopen.side_effect = socket.timeout('Connection timed out')
        
        tool = WBGetCountriesTool({})
        
        with self.assertRaises(ValueError):
            tool.execute({})
    
    @patch('urllib.request.urlopen')
    def test_invalid_json_response(self, mock_urlopen):
        """Test handling of invalid JSON"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'invalid json'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        tool = WBGetIndicatorsTool({})
        
        with self.assertRaises(Exception):
            tool.execute({})
    
    @patch('urllib.request.urlopen')
    def test_empty_response(self, mock_urlopen):
        """Test handling of empty response"""
        empty_data = [
            {'page': 1, 'pages': 1, 'per_page': 100, 'total': 0},
            []
        ]
        
        self._mock_api_response(mock_urlopen, empty_data)
        
        tool = WBGetCountryDataTool({})
        result = tool.execute({
            'country_code': 'XYZ',
            'indicator': 'gdp'
        })
        
        # Should still succeed with empty data
        self.assertEqual(result['data_points'], 0)


def run_test_suite():
    """Run the complete test suite"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetCountriesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetIndicatorsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetCountryDataTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetIndicatorDataTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBSearchIndicatorsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBCompareCountriesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetIncomeLevelsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetLendingTypesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetRegionsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWBGetTopicIndicatorsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWorldBankToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestIndicatorMappings))
    suite.addTests(loader.loadTestsFromTestCase(TestInputValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result


if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║  World Bank MCP Tools - Comprehensive Test Suite                ║
    ║  Copyright All rights reserved 2025-2030, Ashutosh Sinha        ║
    ║  Email: ajsinha@gmail.com                                        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    result = run_test_suite()
    
    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
