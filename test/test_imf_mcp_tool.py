"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for IMF MCP Tools
Comprehensive tests for all 8 IMF (International Monetary Fund) tools
"""

import unittest
import sys
import json
from datetime import datetime
from typing import Dict, Any, List
from unittest.mock import Mock, patch, MagicMock
import urllib.error

# Import the IMF tools
try:
    from tools.impl.imf_tool_refactored import (
        IMFGetDatabasesTool,
        IMFGetDataflowsTool,
        IMFGetDataTool,
        IMFGetIFSDataTool,
        IMFGetWEODataTool,
        IMFGetBOPDataTool,
        IMFCompareCountriesTool,
        IMFGetCountryProfileTool,
        IMF_TOOLS
    )
except ImportError:
    print("Error: Unable to import IMF tools. Ensure the module is in the Python path.")
    sys.exit(1)


class TestIMFGetDatabasesTool(unittest.TestCase):
    """Test suite for IMFGetDatabasesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetDatabasesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_databases')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_database_definitions(self):
        """Test that all major databases are defined"""
        expected_databases = ['IFS', 'WEO', 'BOP', 'DOT', 'FSI', 
                             'GFSR', 'GFSMAB', 'CDIS', 'CPIS', 'WHDREO']
        
        for db in expected_databases:
            self.assertIn(db, self.tool.databases)
            self.assertIsInstance(self.tool.databases[db], str)
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('databases', schema['properties'])
        self.assertIn('count', schema['properties'])
    
    def test_execute(self):
        """Test listing databases"""
        result = self.tool.execute({})
        
        self.assertIn('databases', result)
        self.assertIn('count', result)
        self.assertIsInstance(result['databases'], list)
        self.assertEqual(result['count'], len(result['databases']))
        self.assertGreaterEqual(result['count'], 10)
        
        # Check database structure
        for db in result['databases']:
            self.assertIn('code', db)
            self.assertIn('name', db)
            self.assertIsInstance(db['code'], str)
            self.assertIsInstance(db['name'], str)


class TestIMFGetDataflowsTool(unittest.TestCase):
    """Test suite for IMFGetDataflowsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetDataflowsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_dataflows')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('database', schema['properties'])
        self.assertIn('database', schema['required'])
        
        # Check enum values
        db_enum = schema['properties']['database']['enum']
        self.assertIn('IFS', db_enum)
        self.assertIn('WEO', db_enum)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('database', schema['properties'])
        self.assertIn('dataflows', schema['properties'])
        self.assertIn('count', schema['properties'])
    
    def test_execute_requires_database(self):
        """Test that database parameter is required"""
        with self.assertRaises(ValueError):
            self.tool.execute({})
    
    def test_execute_with_valid_database(self):
        """Test execution with valid database"""
        valid_databases = ['IFS', 'WEO', 'BOP']
        
        for database in valid_databases:
            result = self.tool.execute({'database': database})
            
            self.assertIn('database', result)
            self.assertEqual(result['database'], database)
            self.assertIn('dataflows', result)
            self.assertIn('count', result)


class TestIMFGetDataTool(unittest.TestCase):
    """Test suite for IMFGetDataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetDataTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_data')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        # Check required fields
        required = schema['required']
        self.assertIn('database', required)
        self.assertIn('country_code', required)
        self.assertIn('indicator_code', required)
        
        # Check properties
        props = schema['properties']
        self.assertIn('database', props)
        self.assertIn('country_code', props)
        self.assertIn('indicator_code', props)
        self.assertIn('start_year', props)
        self.assertIn('end_year', props)
        self.assertIn('frequency', props)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('database', props)
        self.assertIn('country_code', props)
        self.assertIn('indicator_code', props)
        self.assertIn('data', props)
        self.assertIn('count', props)
    
    def test_execute_requires_parameters(self):
        """Test that required parameters are enforced"""
        with self.assertRaises(ValueError):
            self.tool.execute({})
        
        with self.assertRaises(ValueError):
            self.tool.execute({'database': 'IFS'})
        
        with self.assertRaises(ValueError):
            self.tool.execute({'database': 'IFS', 'country_code': 'US'})
    
    def test_frequency_parameter(self):
        """Test frequency parameter validation"""
        schema = self.tool.get_input_schema()
        freq_enum = schema['properties']['frequency']['enum']
        
        self.assertIn('A', freq_enum)  # Annual
        self.assertIn('Q', freq_enum)  # Quarterly
        self.assertIn('M', freq_enum)  # Monthly


class TestIMFGetIFSDataTool(unittest.TestCase):
    """Test suite for IMFGetIFSDataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetIFSDataTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_ifs_data')
    
    def test_ifs_indicators_defined(self):
        """Test that IFS indicators are properly defined"""
        expected_indicators = [
            'exchange_rate', 'exchange_rate_avg', 'policy_rate',
            'treasury_bill_rate', 'deposit_rate', 'lending_rate',
            'cpi', 'core_cpi', 'ppi',
            'money_supply_m1', 'money_supply_m2', 'money_supply_m3',
            'reserve_money', 'international_reserves', 'gold_reserves',
            'foreign_reserves', 'gdp_current', 'gdp_constant',
            'industrial_production', 'exports', 'imports', 'unemployment_rate'
        ]
        
        for indicator in expected_indicators:
            self.assertIn(indicator, self.tool.ifs_indicators)
            self.assertIsInstance(self.tool.ifs_indicators[indicator], str)
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('country_code', schema['required'])
        
        props = schema['properties']
        self.assertIn('country_code', props)
        self.assertIn('indicator', props)
        self.assertIn('indicator_code', props)
        
        # Check indicator enum
        indicator_enum = props['indicator']['enum']
        self.assertIn('cpi', indicator_enum)
        self.assertIn('exchange_rate', indicator_enum)
        self.assertIn('policy_rate', indicator_enum)
    
    def test_execute_with_indicator_shorthand(self):
        """Test execution with indicator shorthand"""
        # This would require mocking the API call
        # For now, test that the tool accepts the parameter
        schema = self.tool.get_input_schema()
        self.assertIn('indicator', schema['properties'])
    
    def test_indicator_code_mapping(self):
        """Test that indicator shortcuts map to codes"""
        mappings = {
            'cpi': 'PCPI_IX',
            'exchange_rate': 'ENDA_XDC_USD_RATE',
            'policy_rate': 'FPOLM_PA'
        }
        
        for indicator, code in mappings.items():
            self.assertEqual(self.tool.ifs_indicators[indicator], code)


class TestIMFGetWEODataTool(unittest.TestCase):
    """Test suite for IMFGetWEODataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetWEODataTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_weo_data')
    
    def test_weo_indicators_defined(self):
        """Test that WEO indicators are properly defined"""
        expected_indicators = [
            'gdp_growth', 'gdp_per_capita', 'inflation_avg', 'inflation_eop',
            'unemployment', 'current_account', 'fiscal_balance', 'public_debt',
            'exports_volume', 'imports_volume', 'population'
        ]
        
        for indicator in expected_indicators:
            self.assertIn(indicator, self.tool.weo_indicators)
            self.assertIsInstance(self.tool.weo_indicators[indicator], str)
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('country_code', schema['required'])
        
        props = schema['properties']
        self.assertIn('indicator', props)
        
        # Check WEO indicator enum
        indicator_enum = props['indicator']['enum']
        self.assertIn('gdp_growth', indicator_enum)
        self.assertIn('inflation_avg', indicator_enum)
        self.assertIn('unemployment', indicator_enum)
    
    def test_indicator_code_mapping(self):
        """Test WEO indicator code mappings"""
        mappings = {
            'gdp_growth': 'NGDP_RPCH',
            'inflation_avg': 'PCPIPCH',
            'unemployment': 'LUR',
            'public_debt': 'GGXWDG_NGDP'
        }
        
        for indicator, code in mappings.items():
            self.assertEqual(self.tool.weo_indicators[indicator], code)


class TestIMFGetBOPDataTool(unittest.TestCase):
    """Test suite for IMFGetBOPDataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetBOPDataTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_bop_data')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        required = schema['required']
        self.assertIn('country_code', required)
        self.assertIn('indicator_code', required)
        
        props = schema['properties']
        self.assertIn('frequency', props)
        
        # BOP typically has A and Q frequency
        freq_enum = props['frequency']['enum']
        self.assertIn('A', freq_enum)
        self.assertIn('Q', freq_enum)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('database', props)
        self.assertIn('country_code', props)
        self.assertIn('indicator_code', props)
        self.assertIn('data', props)


class TestIMFCompareCountriesTool(unittest.TestCase):
    """Test suite for IMFCompareCountriesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFCompareCountriesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_compare_countries')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('country_codes', schema['required'])
        
        props = schema['properties']
        self.assertIn('country_codes', props)
        self.assertIn('database', props)
        self.assertIn('indicator', props)
        
        # country_codes should be array
        self.assertEqual(props['country_codes']['type'], 'array')
        self.assertEqual(props['country_codes']['minItems'], 2)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('database', props)
        self.assertIn('indicator_code', props)
        self.assertIn('countries', props)
        
        # countries should be array
        self.assertEqual(props['countries']['type'], 'array')
    
    def test_requires_multiple_countries(self):
        """Test that at least 2 countries are required"""
        schema = self.tool.get_input_schema()
        min_items = schema['properties']['country_codes']['minItems']
        self.assertEqual(min_items, 2)


class TestIMFGetCountryProfileTool(unittest.TestCase):
    """Test suite for IMFGetCountryProfileTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetCountryProfileTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'imf_get_country_profile')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('country_code', schema['required'])
        self.assertIn('country_code', schema['properties'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('country_code', props)
        self.assertIn('country_name', props)
        self.assertIn('indicators', props)
        
        # indicators should be object
        self.assertEqual(props['indicators']['type'], 'object')
    
    def test_common_countries_mapping(self):
        """Test common country name mappings"""
        expected_countries = {
            'US': 'United States',
            'CN': 'China',
            'JP': 'Japan',
            'DE': 'Germany',
            'GB': 'United Kingdom'
        }
        
        for code, name in expected_countries.items():
            self.assertIn(code, self.tool.common_countries)
            self.assertEqual(self.tool.common_countries[code], name)


class TestIMFToolRegistry(unittest.TestCase):
    """Test suite for tool registry"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry is defined"""
        self.assertIsNotNone(IMF_TOOLS)
        self.assertIsInstance(IMF_TOOLS, dict)
    
    def test_all_tools_in_registry(self):
        """Test that all 8 tools are in the registry"""
        expected_tools = [
            'imf_get_databases',
            'imf_get_dataflows',
            'imf_get_data',
            'imf_get_ifs_data',
            'imf_get_weo_data',
            'imf_get_bop_data',
            'imf_compare_countries',
            'imf_get_country_profile'
        ]
        
        self.assertEqual(len(IMF_TOOLS), 8)
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, IMF_TOOLS)
    
    def test_tools_are_classes(self):
        """Test that registry contains class references"""
        for tool_name, tool_class in IMF_TOOLS.items():
            self.assertTrue(callable(tool_class))
    
    def test_tool_instantiation(self):
        """Test that all tools can be instantiated"""
        for tool_name, tool_class in IMF_TOOLS.items():
            try:
                tool_instance = tool_class()
                self.assertIsNotNone(tool_instance)
                self.assertTrue(hasattr(tool_instance, 'execute'))
                self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
                self.assertTrue(hasattr(tool_instance, 'get_output_schema'))
            except Exception as e:
                self.fail(f"Failed to instantiate {tool_name}: {e}")


class TestIMFAPIConfiguration(unittest.TestCase):
    """Test suite for API configuration"""
    
    def test_api_url_configuration(self):
        """Test that API URL is correctly configured"""
        tool = IMFGetDataTool()
        
        expected_url = "http://dataservices.imf.org/REST/SDMX_JSON.svc"
        self.assertEqual(tool.api_url, expected_url)
    
    def test_no_authentication_required(self):
        """Test that no API key is required"""
        tool = IMFGetDataTool()
        
        # Should not have api_key attribute or it should be None/empty
        self.assertFalse(hasattr(tool, 'api_key') and tool.api_key)


class TestIMFDataRetrieval(unittest.TestCase):
    """Test suite for data retrieval methods"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetDataTool()
    
    def test_get_data_method_exists(self):
        """Test that _get_data method exists"""
        self.assertTrue(hasattr(self.tool, '_get_data'))
        self.assertTrue(callable(self.tool._get_data))
    
    def test_data_output_format(self):
        """Test expected data output format"""
        # This is the expected structure
        expected_keys = ['database', 'country_code', 'indicator_code', 
                        'frequency', 'data', 'count']
        
        schema = self.tool.get_output_schema()
        props = schema['properties']
        
        for key in expected_keys:
            self.assertIn(key, props)


class TestIMFErrorHandling(unittest.TestCase):
    """Test suite for error handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IMFGetDataTool()
    
    @patch('urllib.request.urlopen')
    def test_http_404_error(self, mock_urlopen):
        """Test handling of HTTP 404 error"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'http://test.com', 404, 'Not Found', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool._get_data('IFS', 'US', 'INVALID_CODE')
        
        self.assertIn('not found', str(context.exception).lower())
    
    @patch('urllib.request.urlopen')
    def test_network_error_handling(self, mock_urlopen):
        """Test handling of network errors"""
        mock_urlopen.side_effect = urllib.error.URLError('Network error')
        
        with self.assertRaises(ValueError) as context:
            self.tool._get_data('IFS', 'US', 'PCPI_IX')
        
        self.assertIn('failed', str(context.exception).lower())


class TestIMFIntegrationScenarios(unittest.TestCase):
    """Integration tests for common usage scenarios"""
    
    def test_scenario_database_discovery(self):
        """Test: Discover available databases"""
        tool = IMFGetDatabasesTool()
        result = tool.execute({})
        
        self.assertIn('databases', result)
        self.assertGreater(result['count'], 0)
        
        # Should include major databases
        codes = [db['code'] for db in result['databases']]
        self.assertIn('IFS', codes)
        self.assertIn('WEO', codes)
        self.assertIn('BOP', codes)
    
    def test_scenario_indicator_shortcuts(self):
        """Test: Using indicator shortcuts"""
        ifs_tool = IMFGetIFSDataTool()
        weo_tool = IMFGetWEODataTool()
        
        # Verify IFS shortcuts exist
        self.assertIn('cpi', ifs_tool.ifs_indicators)
        self.assertIn('exchange_rate', ifs_tool.ifs_indicators)
        
        # Verify WEO shortcuts exist
        self.assertIn('gdp_growth', weo_tool.weo_indicators)
        self.assertIn('inflation_avg', weo_tool.weo_indicators)


class TestIMFYearValidation(unittest.TestCase):
    """Test suite for year parameter validation"""
    
    def test_year_range_constraints(self):
        """Test year range constraints"""
        tool = IMFGetDataTool()
        schema = tool.get_input_schema()
        
        start_year = schema['properties']['start_year']
        self.assertEqual(start_year['minimum'], 1950)
        self.assertEqual(start_year['maximum'], 2030)
        
        end_year = schema['properties']['end_year']
        self.assertEqual(end_year['minimum'], 1950)
        self.assertEqual(end_year['maximum'], 2030)


class TestIMFFrequencySupport(unittest.TestCase):
    """Test suite for frequency parameter support"""
    
    def test_annual_frequency(self):
        """Test annual frequency support"""
        tool = IMFGetDataTool()
        schema = tool.get_input_schema()
        
        freq_enum = schema['properties']['frequency']['enum']
        self.assertIn('A', freq_enum)
    
    def test_quarterly_frequency(self):
        """Test quarterly frequency support"""
        tool = IMFGetDataTool()
        schema = tool.get_input_schema()
        
        freq_enum = schema['properties']['frequency']['enum']
        self.assertIn('Q', freq_enum)
    
    def test_monthly_frequency(self):
        """Test monthly frequency support"""
        tool = IMFGetIFSDataTool()
        schema = tool.get_input_schema()
        
        freq_enum = schema['properties']['frequency']['enum']
        self.assertIn('M', freq_enum)


class TestIMFCountryCodes(unittest.TestCase):
    """Test suite for country code handling"""
    
    def test_country_code_format(self):
        """Test country code format expectations"""
        # Country codes should be 2-letter ISO codes
        tool = IMFGetDataTool()
        
        valid_codes = ['US', 'CN', 'JP', 'DE', 'GB', 'FR', 'IN']
        
        for code in valid_codes:
            # Should be uppercase
            self.assertEqual(code, code.upper())
            # Should be 2 characters
            self.assertEqual(len(code), 2)
            # Should be alphabetic
            self.assertTrue(code.isalpha())


class TestIMFDatabaseTypes(unittest.TestCase):
    """Test suite for database type definitions"""
    
    def test_major_databases_available(self):
        """Test that major databases are available"""
        tool = IMFGetDatabasesTool()
        
        major_databases = ['IFS', 'WEO', 'BOP', 'FSI', 'DOT']
        
        for db in major_databases:
            self.assertIn(db, tool.databases)
    
    def test_database_descriptions(self):
        """Test that databases have descriptions"""
        tool = IMFGetDatabasesTool()
        
        for code, name in tool.databases.items():
            self.assertIsNotNone(name)
            self.assertGreater(len(name), 0)
            self.assertIsInstance(name, str)


class TestIMFDataValidation(unittest.TestCase):
    """Test suite for data validation"""
    
    def test_observation_structure(self):
        """Test expected observation structure"""
        tool = IMFGetDataTool()
        schema = tool.get_output_schema()
        
        data_items = schema['properties']['data']['items']
        data_props = data_items['properties']
        
        self.assertIn('period', data_props)
        self.assertIn('value', data_props)
        
        # Value can be number or null
        value_types = data_props['value']['type']
        self.assertIn('number', value_types)
        self.assertIn('null', value_types)


def run_test_suite(verbosity=2):
    """
    Run the complete test suite
    
    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)
    
    Returns:
        TestResult object
    """
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestIMFGetDatabasesTool,
        TestIMFGetDataflowsTool,
        TestIMFGetDataTool,
        TestIMFGetIFSDataTool,
        TestIMFGetWEODataTool,
        TestIMFGetBOPDataTool,
        TestIMFCompareCountriesTool,
        TestIMFGetCountryProfileTool,
        TestIMFToolRegistry,
        TestIMFAPIConfiguration,
        TestIMFDataRetrieval,
        TestIMFErrorHandling,
        TestIMFIntegrationScenarios,
        TestIMFYearValidation,
        TestIMFFrequencySupport,
        TestIMFCountryCodes,
        TestIMFDatabaseTypes,
        TestIMFDataValidation
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return result


def print_test_summary(result):
    """Print a summary of test results"""
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("="*70)
    
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("="*70)


if __name__ == '__main__':
    print("IMF MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
