"""
Copyright All rights reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Comprehensive Test Suite for United Nations MCP Tools
Tests all nine tools with various scenarios including success and error cases
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
    from united_nations_tool_refactored import (
        UNGetSDGsTool,
        UNGetSDGIndicatorsTool,
        UNGetSDGDataTool,
        UNGetSDGTargetsTool,
        UNGetSDGProgressTool,
        UNGetTradeDataTool,
        UNGetCountryTradeTool,
        UNGetTradeBalanceTool,
        UNCompareCountryTradeTool,
        UNITED_NATIONS_TOOLS
    )
except ImportError:
    print("Warning: Could not import tools. Using mock implementations for testing structure.")


class TestUNToolsBase(unittest.TestCase):
    """Base test class with common setup and utilities"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.config = {}
        
        # Mock SDG API responses
        cls.mock_sdgs = [
            {
                'code': '1',
                'title': 'No Poverty',
                'description': 'End poverty in all its forms everywhere',
                'colorInfo': {'hex': '#E5243B'},
                'uri': 'https://unstats.un.org/sdgs/metadata/?Text=&Goal=1'
            },
            {
                'code': '13',
                'title': 'Climate Action',
                'description': 'Take urgent action to combat climate change',
                'colorInfo': {'hex': '#3F7E44'},
                'uri': 'https://unstats.un.org/sdgs/metadata/?Text=&Goal=13'
            }
        ]
        
        # Mock indicators
        cls.mock_indicators = [
            {
                'code': '1.1.1',
                'description': 'Proportion of population below poverty line',
                'tier': 'Tier I',
                'uri': 'https://unstats.un.org/sdgs/metadata/?Text=&Goal=1&Target=1.1'
            },
            {
                'code': '1.2.1',
                'description': 'Poverty headcount ratio',
                'tier': 'Tier I',
                'uri': 'https://unstats.un.org/sdgs/metadata/?Text=&Goal=1&Target=1.2'
            }
        ]
        
        # Mock time series data
        cls.mock_timeseries = [
            {
                'timePeriodStart': 2015,
                'value': 21.9,
                'units': '%',
                'geoAreaName': 'India',
                'seriesDescription': 'Poverty headcount ratio at $1.90 a day'
            },
            {
                'timePeriodStart': 2020,
                'value': 16.4,
                'units': '%',
                'geoAreaName': 'India',
                'seriesDescription': 'Poverty headcount ratio at $1.90 a day'
            }
        ]
    
    def _validate_success_response(self, response: Dict[str, Any]):
        """Validate response doesn't have errors"""
        self.assertNotIn('error', response, 
                        f"Response has error: {response.get('error')}")
    
    def _validate_error_response(self, response: Dict[str, Any]):
        """Validate error response structure"""
        self.assertIn('error', response)
        self.assertIsInstance(response['error'], str)


class TestUNGetSDGsTool(TestUNToolsBase):
    """Test cases for un_get_sdgs tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetSDGsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_sdgs_basic(self, mock_urlopen):
        """Test getting SDGs without details"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_sdgs).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'include_details': False
        })
        
        self._validate_success_response(result)
        self.assertIn('sdgs', result)
        self.assertIn('count', result)
        self.assertGreater(result['count'], 0)
    
    @patch('urllib.request.urlopen')
    def test_get_sdgs_with_details(self, mock_urlopen):
        """Test getting SDGs with descriptions"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_sdgs).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'include_details': True
        })
        
        self._validate_success_response(result)
        self.assertIn('sdgs', result)
        
        for sdg in result['sdgs']:
            self.assertIn('code', sdg)
            self.assertIn('title', sdg)
            self.assertIn('description', sdg)
            self.assertIn('color', sdg)
    
    def test_get_sdgs_count(self):
        """Test that SDG count is correct"""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(self.mock_sdgs).encode('utf-8')
            mock_urlopen.return_value.__enter__.return_value = mock_response
            
            result = self.tool.execute({})
            
            # Should return all parsed SDGs
            self.assertEqual(result['count'], len(result['sdgs']))
    
    def test_get_sdgs_structure(self):
        """Test SDG object structure"""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(self.mock_sdgs).encode('utf-8')
            mock_urlopen.return_value.__enter__.return_value = mock_response
            
            result = self.tool.execute({})
            
            for sdg in result['sdgs']:
                self.assertIn('code', sdg)
                self.assertIn('title', sdg)
                self.assertIn('color', sdg)
                self.assertIn('uri', sdg)
    
    def test_get_sdgs_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('include_details', schema['properties'])
    
    def test_get_sdgs_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        self.assertIn('properties', schema)
        self.assertIn('sdgs', schema['properties'])
        self.assertIn('count', schema['properties'])
    
    @patch('urllib.request.urlopen')
    def test_get_sdgs_api_error(self, mock_urlopen):
        """Test handling of API errors"""
        mock_urlopen.side_effect = Exception("API Error")
        
        result = self.tool.execute({})
        
        # Should return error gracefully
        self._validate_error_response(result)


class TestUNGetSDGIndicatorsTool(TestUNToolsBase):
    """Test cases for un_get_sdg_indicators tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetSDGIndicatorsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_indicators_for_sdg(self, mock_urlopen):
        """Test getting indicators for a specific SDG"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_indicators).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'sdg_code': '1'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['sdg_code'], '1')
        self.assertIn('indicators', result)
        self.assertIn('count', result)
    
    def test_get_indicators_required_parameter(self):
        """Test that sdg_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('sdg_code', schema['required'])
    
    @patch('urllib.request.urlopen')
    def test_get_indicators_structure(self, mock_urlopen):
        """Test indicator object structure"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_indicators).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({'sdg_code': '1'})
        
        for indicator in result['indicators']:
            self.assertIn('code', indicator)
            self.assertIn('description', indicator)
            self.assertIn('tier', indicator)
    
    @patch('urllib.request.urlopen')
    def test_get_indicators_filtering(self, mock_urlopen):
        """Test that indicators are filtered by SDG code"""
        all_indicators = self.mock_indicators + [
            {
                'code': '13.1.1',
                'description': 'Climate indicator',
                'tier': 'Tier I',
                'uri': 'test'
            }
        ]
        
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(all_indicators).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({'sdg_code': '1'})
        
        # Should only return indicators starting with '1.'
        for indicator in result['indicators']:
            self.assertTrue(indicator['code'].startswith('1.'))


class TestUNGetSDGDataTool(TestUNToolsBase):
    """Test cases for un_get_sdg_data tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetSDGDataTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_sdg_data_basic(self, mock_urlopen):
        """Test getting SDG time series data"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_timeseries).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'indicator_code': '1.1.1',
            'country_code': 'IND',
            'start_year': 2015,
            'end_year': 2020
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['indicator_code'], '1.1.1')
        self.assertEqual(result['country_code'], 'IND')
        self.assertIn('data', result)
        self.assertIn('count', result)
    
    def test_get_sdg_data_required_parameter(self):
        """Test that indicator_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('indicator_code', schema['required'])
    
    @patch('urllib.request.urlopen')
    def test_get_sdg_data_structure(self, mock_urlopen):
        """Test data point structure"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_timeseries).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'indicator_code': '1.1.1',
            'country_code': 'IND'
        })
        
        for point in result['data']:
            self.assertIn('year', point)
            self.assertIn('value', point)
            self.assertIn('unit', point)
    
    @patch('urllib.request.urlopen')
    def test_get_sdg_data_without_country(self, mock_urlopen):
        """Test getting global data without country filter"""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_timeseries).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'indicator_code': '1.1.1'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['indicator_code'], '1.1.1')


class TestUNGetSDGTargetsTool(TestUNToolsBase):
    """Test cases for un_get_sdg_targets tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetSDGTargetsTool(self.config)
    
    @patch('urllib.request.urlopen')
    def test_get_targets_for_sdg(self, mock_urlopen):
        """Test getting targets for a specific SDG"""
        mock_targets = [
            {
                'code': '1.1',
                'title': 'Eradicate extreme poverty',
                'description': 'By 2030, eradicate extreme poverty...',
                'uri': 'test_uri'
            },
            {
                'code': '1.2',
                'title': 'Reduce poverty by half',
                'description': 'By 2030, reduce at least by half...',
                'uri': 'test_uri'
            }
        ]
        
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_targets).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({
            'sdg_code': '1'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['sdg_code'], '1')
        self.assertIn('targets', result)
        self.assertIn('count', result)
    
    def test_get_targets_required_parameter(self):
        """Test that sdg_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('sdg_code', schema['required'])
    
    @patch('urllib.request.urlopen')
    def test_get_targets_structure(self, mock_urlopen):
        """Test target object structure"""
        mock_targets = [
            {
                'code': '13.1',
                'title': 'Climate resilience',
                'description': 'Strengthen resilience...',
                'uri': 'test_uri'
            }
        ]
        
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_targets).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.tool.execute({'sdg_code': '13'})
        
        for target in result['targets']:
            self.assertIn('code', target)
            self.assertIn('title', target)
            self.assertIn('description', target)


class TestUNGetSDGProgressTool(TestUNToolsBase):
    """Test cases for un_get_sdg_progress tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetSDGProgressTool(self.config)
    
    def test_get_progress_with_specific_sdg(self):
        """Test getting progress for specific SDG"""
        result = self.tool.execute({
            'country_code': 'IND',
            'sdg_code': '1'
        })
        
        self.assertEqual(result['country_code'], 'IND')
        self.assertEqual(result['sdg_code'], '1')
        self.assertIn('sdg_title', result)
    
    def test_get_progress_overview(self):
        """Test getting overview without specific SDG"""
        result = self.tool.execute({
            'country_code': 'USA'
        })
        
        self.assertEqual(result['country_code'], 'USA')
        # Should suggest specifying sdg_code
        self.assertIn('note', result)
    
    def test_get_progress_required_parameter(self):
        """Test that country_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_code', schema['required'])
    
    def test_get_progress_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('properties', schema)
        self.assertIn('country_code', schema['properties'])
        self.assertIn('sdg_code', schema['properties'])


class TestUNGetTradeDataTool(TestUNToolsBase):
    """Test cases for un_get_trade_data tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetTradeDataTool(self.config)
    
    def test_get_trade_data_basic(self):
        """Test basic trade data request"""
        result = self.tool.execute({
            'reporter_code': 'USA',
            'partner_code': 'CHN',
            'trade_flow': 'export',
            'year': 2022
        })
        
        self.assertEqual(result['reporter'], 'USA')
        self.assertEqual(result['partner'], 'CHN')
        self.assertEqual(result['trade_flow'], 'export')
        self.assertEqual(result['year'], 2022)
        self.assertIn('note', result)
    
    def test_get_trade_data_required_parameter(self):
        """Test that reporter_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('reporter_code', schema['required'])
    
    def test_get_trade_data_default_values(self):
        """Test default parameter values"""
        result = self.tool.execute({
            'reporter_code': 'DEU'
        })
        
        self.assertEqual(result['reporter'], 'DEU')
        self.assertEqual(result['partner'], 'all')
        self.assertEqual(result['trade_flow'], 'export')
    
    def test_get_trade_data_commodity_groups(self):
        """Test different commodity groups"""
        commodities = ['agricultural', 'machinery', 'chemicals']
        
        for commodity in commodities:
            result = self.tool.execute({
                'reporter_code': 'USA',
                'commodity_code': commodity
            })
            
            self.assertIn('commodity', result)
    
    def test_get_trade_data_flows(self):
        """Test different trade flow types"""
        flows = ['export', 'import', 're_export', 're_import']
        
        for flow in flows:
            result = self.tool.execute({
                'reporter_code': 'JPN',
                'trade_flow': flow
            })
            
            self.assertEqual(result['trade_flow'], flow)


class TestUNGetCountryTradeTool(TestUNToolsBase):
    """Test cases for un_get_country_trade tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetCountryTradeTool(self.config)
    
    def test_get_country_trade_basic(self):
        """Test getting country trade summary"""
        result = self.tool.execute({
            'country_code': 'USA',
            'year': 2022
        })
        
        self.assertEqual(result['country_code'], 'USA')
        self.assertEqual(result['year'], 2022)
        self.assertIn('exports', result)
        self.assertIn('imports', result)
    
    def test_get_country_trade_required_parameter(self):
        """Test that country_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_code', schema['required'])
    
    def test_get_country_trade_structure(self):
        """Test response structure"""
        result = self.tool.execute({
            'country_code': 'DEU'
        })
        
        self.assertIn('exports', result)
        self.assertIn('imports', result)
        
        # Check exports structure
        exports = result['exports']
        self.assertIn('total_value', exports)
        self.assertIn('top_partners', exports)
        
        # Check imports structure
        imports = result['imports']
        self.assertIn('total_value', imports)
        self.assertIn('top_partners', imports)
    
    def test_get_country_trade_default_year(self):
        """Test default year (previous year)"""
        result = self.tool.execute({
            'country_code': 'JPN'
        })
        
        # Should default to previous year
        expected_year = datetime.now().year - 1
        self.assertEqual(result['year'], expected_year)


class TestUNGetTradeBalanceTool(TestUNToolsBase):
    """Test cases for un_get_trade_balance tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNGetTradeBalanceTool(self.config)
    
    def test_get_trade_balance_basic(self):
        """Test trade balance calculation"""
        result = self.tool.execute({
            'country_code': 'USA',
            'partner_code': 'CHN',
            'year': 2022
        })
        
        self.assertEqual(result['country_code'], 'USA')
        self.assertEqual(result['partner_code'], 'CHN')
        self.assertEqual(result['year'], 2022)
        self.assertIn('data', result)
    
    def test_get_trade_balance_required_parameter(self):
        """Test that country_code is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_code', schema['required'])
    
    def test_get_trade_balance_data_structure(self):
        """Test data object structure"""
        result = self.tool.execute({
            'country_code': 'IND',
            'partner_code': 'USA'
        })
        
        data = result['data']
        self.assertIn('exports', data)
        self.assertIn('imports', data)
        self.assertIn('balance', data)
    
    def test_get_trade_balance_default_partner(self):
        """Test default partner (all/world)"""
        result = self.tool.execute({
            'country_code': 'BRA'
        })
        
        self.assertEqual(result['partner_code'], 'all')


class TestUNCompareCountryTradeTool(TestUNToolsBase):
    """Test cases for un_compare_trade tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = UNCompareCountryTradeTool(self.config)
    
    def test_compare_trade_basic(self):
        """Test comparing trade across countries"""
        result = self.tool.execute({
            'country_codes': ['USA', 'CHN', 'DEU'],
            'trade_flow': 'export',
            'year': 2022
        })
        
        self.assertEqual(result['trade_flow'], 'export')
        self.assertEqual(result['year'], 2022)
        self.assertIn('countries', result)
        self.assertEqual(len(result['countries']), 3)
    
    def test_compare_trade_required_parameter(self):
        """Test that country_codes is required"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('required', schema)
        self.assertIn('country_codes', schema['required'])
    
    def test_compare_trade_min_countries(self):
        """Test minimum country requirement"""
        schema = self.tool.get_input_schema()
        
        country_codes = schema['properties']['country_codes']
        self.assertEqual(country_codes['minItems'], 2)
    
    def test_compare_trade_max_countries(self):
        """Test maximum country limit"""
        schema = self.tool.get_input_schema()
        
        country_codes = schema['properties']['country_codes']
        self.assertEqual(country_codes['maxItems'], 10)
    
    def test_compare_trade_default_flow(self):
        """Test default trade flow"""
        result = self.tool.execute({
            'country_codes': ['JPN', 'KOR']
        })
        
        self.assertEqual(result['trade_flow'], 'export')
    
    def test_compare_trade_country_structure(self):
        """Test country object structure"""
        result = self.tool.execute({
            'country_codes': ['BRA', 'IND'],
            'trade_flow': 'import'
        })
        
        for country in result['countries']:
            self.assertIn('country_code', country)
            self.assertIn('total_value', country)


class TestUNToolRegistry(TestUNToolsBase):
    """Test cases for tool registry and integration"""
    
    def test_registry_exists(self):
        """Test that tool registry exists"""
        self.assertIsNotNone(UNITED_NATIONS_TOOLS)
        self.assertIsInstance(UNITED_NATIONS_TOOLS, dict)
    
    def test_all_tools_registered(self):
        """Test that all 9 tools are registered"""
        expected_tools = [
            'un_get_sdgs',
            'un_get_sdg_indicators',
            'un_get_sdg_data',
            'un_get_sdg_targets',
            'un_get_sdg_progress',
            'un_get_trade_data',
            'un_get_country_trade',
            'un_get_trade_balance',
            'un_compare_trade'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, UNITED_NATIONS_TOOLS)
    
    def test_tool_instantiation_from_registry(self):
        """Test creating tools from registry"""
        for tool_name, tool_class in UNITED_NATIONS_TOOLS.items():
            tool = tool_class(self.config)
            self.assertIsNotNone(tool)
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have input and output schemas"""
        for tool_name, tool_class in UNITED_NATIONS_TOOLS.items():
            tool = tool_class(self.config)
            
            input_schema = tool.get_input_schema()
            output_schema = tool.get_output_schema()
            
            self.assertIsInstance(input_schema, dict)
            self.assertIsInstance(output_schema, dict)
    
    def test_all_tools_have_execute(self):
        """Test that all tools have execute method"""
        for tool_name, tool_class in UNITED_NATIONS_TOOLS.items():
            tool = tool_class(self.config)
            self.assertTrue(hasattr(tool, 'execute'))
            self.assertTrue(callable(tool.execute))


class TestSDGDefinitions(TestUNToolsBase):
    """Test SDG definitions and classifications"""
    
    def test_sdg_count(self):
        """Test that there are 17 SDGs"""
        from united_nations_tool_refactored import UnitedNationsBaseTool
        
        tool = UnitedNationsBaseTool({})
        self.assertEqual(len(tool.sdgs), 17)
    
    def test_sdg_codes(self):
        """Test SDG code range"""
        from united_nations_tool_refactored import UnitedNationsBaseTool
        
        tool = UnitedNationsBaseTool({})
        
        for code in tool.sdgs.keys():
            code_int = int(code)
            self.assertGreaterEqual(code_int, 1)
            self.assertLessEqual(code_int, 17)
    
    def test_sdg_titles(self):
        """Test that all SDGs have titles"""
        from united_nations_tool_refactored import UnitedNationsBaseTool
        
        tool = UnitedNationsBaseTool({})
        
        for title in tool.sdgs.values():
            self.assertIsInstance(title, str)
            self.assertGreater(len(title), 0)


class TestTradeClassifications(TestUNToolsBase):
    """Test trade flow and commodity classifications"""
    
    def test_trade_flows(self):
        """Test trade flow definitions"""
        from united_nations_tool_refactored import UnitedNationsBaseTool
        
        tool = UnitedNationsBaseTool({})
        
        expected_flows = ['export', 'import', 're_export', 're_import']
        for flow in expected_flows:
            self.assertIn(flow, tool.trade_flows)
    
    def test_commodity_groups(self):
        """Test commodity group definitions"""
        from united_nations_tool_refactored import UnitedNationsBaseTool
        
        tool = UnitedNationsBaseTool({})
        
        expected_groups = [
            'all', 'agricultural', 'mineral', 'chemicals',
            'plastics_rubber', 'textiles', 'footwear', 'metals',
            'machinery', 'vehicles', 'optical_instruments'
        ]
        
        for group in expected_groups:
            self.assertIn(group, tool.commodity_groups)


class TestInputValidation(TestUNToolsBase):
    """Test input parameter validation"""
    
    def test_sdg_code_enum(self):
        """Test SDG code enum validation"""
        tool = UNGetSDGIndicatorsTool({})
        schema = tool.get_input_schema()
        
        sdg_code_prop = schema['properties']['sdg_code']
        self.assertIn('enum', sdg_code_prop)
        
        # Should have 17 values (1-17)
        self.assertEqual(len(sdg_code_prop['enum']), 17)
    
    def test_year_range_validation(self):
        """Test year parameter ranges"""
        tool = UNGetTradeDataTool({})
        schema = tool.get_input_schema()
        
        year_prop = schema['properties']['year']
        self.assertIn('minimum', year_prop)
        self.assertIn('maximum', year_prop)
        self.assertEqual(year_prop['minimum'], 1962)
    
    def test_country_codes_array_validation(self):
        """Test country_codes array validation"""
        tool = UNCompareCountryTradeTool({})
        schema = tool.get_input_schema()
        
        codes_prop = schema['properties']['country_codes']
        self.assertEqual(codes_prop['type'], 'array')
        self.assertEqual(codes_prop['minItems'], 2)
        self.assertEqual(codes_prop['maxItems'], 10)


class TestIntegrationScenarios(TestUNToolsBase):
    """Integration test scenarios"""
    
    @patch('urllib.request.urlopen')
    def test_sdg_exploration_workflow(self, mock_urlopen):
        """Test workflow: list SDGs -> get indicators -> get data"""
        # Step 1: List SDGs
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_sdgs).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        sdg_tool = UNGetSDGsTool({})
        sdgs = sdg_tool.execute({})
        
        self.assertGreater(sdgs['count'], 0)
        
        # Step 2: Get indicators for first SDG
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_indicators).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        indicator_tool = UNGetSDGIndicatorsTool({})
        indicators = indicator_tool.execute({'sdg_code': '1'})
        
        self.assertGreater(indicators['count'], 0)
        
        # Step 3: Get data for first indicator
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(self.mock_timeseries).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        data_tool = UNGetSDGDataTool({})
        data = data_tool.execute({
            'indicator_code': '1.1.1',
            'country_code': 'IND'
        })
        
        self._validate_success_response(data)
    
    def test_trade_analysis_workflow(self):
        """Test workflow: country trade -> balance -> comparison"""
        # Step 1: Get country trade summary
        trade_tool = UNGetCountryTradeTool({})
        trade = trade_tool.execute({
            'country_code': 'USA',
            'year': 2022
        })
        
        self.assertEqual(trade['country_code'], 'USA')
        
        # Step 2: Get trade balance with partner
        balance_tool = UNGetTradeBalanceTool({})
        balance = balance_tool.execute({
            'country_code': 'USA',
            'partner_code': 'CHN',
            'year': 2022
        })
        
        self.assertIn('data', balance)
        
        # Step 3: Compare with other countries
        compare_tool = UNCompareCountryTradeTool({})
        comparison = compare_tool.execute({
            'country_codes': ['USA', 'CHN', 'DEU'],
            'trade_flow': 'export',
            'year': 2022
        })
        
        self.assertEqual(len(comparison['countries']), 3)


class TestErrorHandling(TestUNToolsBase):
    """Test error handling scenarios"""
    
    @patch('urllib.request.urlopen')
    def test_network_error(self, mock_urlopen):
        """Test handling of network errors"""
        mock_urlopen.side_effect = Exception("Network error")
        
        tool = UNGetSDGsTool({})
        result = tool.execute({})
        
        # Should return error gracefully
        self._validate_error_response(result)
    
    @patch('urllib.request.urlopen')
    def test_invalid_json_response(self, mock_urlopen):
        """Test handling of invalid JSON"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'invalid json'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        tool = UNGetSDGDataTool({})
        result = tool.execute({'indicator_code': '1.1.1'})
        
        # Should handle gracefully
        self._validate_error_response(result)
    
    @patch('urllib.request.urlopen')
    def test_empty_response(self, mock_urlopen):
        """Test handling of empty response"""
        mock_response = MagicMock()
        mock_response.read.return_value = b'[]'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        tool = UNGetSDGIndicatorsTool({})
        result = tool.execute({'sdg_code': '1'})
        
        # Should still succeed with empty data
        self.assertEqual(result['count'], 0)


def run_test_suite():
    """Run the complete test suite"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetSDGsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetSDGIndicatorsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetSDGDataTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetSDGTargetsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetSDGProgressTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetTradeDataTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetCountryTradeTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNGetTradeBalanceTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNCompareCountryTradeTool))
    suite.addTests(loader.loadTestsFromTestCase(TestUNToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestSDGDefinitions))
    suite.addTests(loader.loadTestsFromTestCase(TestTradeClassifications))
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
    ║  United Nations MCP Tools - Comprehensive Test Suite            ║
    ║  Copyright All rights reserved 2025-2030, Ashutosh Sinha        ║
    ║  Email: ajsinha@gmail.com                                        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    result = run_test_suite()
    
    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
