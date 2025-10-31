"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for Federal Reserve MCP Tools
Comprehensive tests for all 4 FRED tools with various scenarios
"""

import unittest
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock

# Import the Federal Reserve tools
try:
    from tools.impl.fed_reserve_tool_refactored import (
        FedGetSeriesTool,
        FedGetLatestTool,
        FedSearchSeriesTool,
        FedGetCommonIndicatorsTool,
        FED_RESERVE_TOOLS
    )
except ImportError:
    print("Error: Unable to import Federal Reserve tools. Ensure the module is in the Python path.")
    sys.exit(1)


class TestFedGetSeriesTool(unittest.TestCase):
    """Test suite for FedGetSeriesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FedGetSeriesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fed_get_series')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_initialization_with_api_key(self):
        """Test tool initialization with API key"""
        config = {'api_key': 'test_key_12345'}
        tool = FedGetSeriesTool(config)
        self.assertEqual(tool.api_key, 'test_key_12345')
    
    def test_demo_mode_default(self):
        """Test that demo mode is default without API key"""
        tool = FedGetSeriesTool()
        self.assertEqual(tool.api_key, 'demo')
    
    def test_common_series_mapping(self):
        """Test common series mapping"""
        expected_series = {
            'gdp': 'GDP',
            'unemployment': 'UNRATE',
            'inflation': 'CPIAUCSL',
            'fed_rate': 'DFF',
            'treasury_10y': 'DGS10',
            'treasury_2y': 'DGS2',
            'sp500': 'SP500',
            'housing': 'HOUST',
            'retail': 'RSXFS',
            'industrial': 'INDPRO',
            'm2': 'M2SL',
            'pce': 'PCEPI'
        }
        self.assertEqual(self.tool.common_series, expected_series)
        self.assertEqual(len(self.tool.common_series), 12)
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('series_id', schema['properties'])
        self.assertIn('indicator', schema['properties'])
        self.assertIn('start_date', schema['properties'])
        self.assertIn('end_date', schema['properties'])
        self.assertIn('limit', schema['properties'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('type', schema)
        self.assertIn('properties', schema)
        self.assertIn('series_id', schema['properties'])
        self.assertIn('observations', schema['properties'])
    
    def test_execute_with_indicator_demo_mode(self):
        """Test execution with indicator shorthand in demo mode"""
        result = self.tool.execute({
            'indicator': 'gdp',
            'limit': 5
        })
        
        self.assertIn('series_id', result)
        self.assertIn('title', result)
        self.assertIn('observations', result)
        self.assertIsInstance(result['observations'], list)
        self.assertLessEqual(len(result['observations']), 5)
        
        # Check for demo mode note
        if 'note' in result:
            self.assertIn('Demo mode', result['note'])
    
    def test_execute_with_series_id_demo_mode(self):
        """Test execution with explicit series ID in demo mode"""
        result = self.tool.execute({
            'series_id': 'UNRATE',
            'limit': 10
        })
        
        self.assertEqual(result['series_id'], 'UNRATE')
        self.assertIn('observations', result)
        self.assertLessEqual(len(result['observations']), 10)
    
    def test_execute_with_date_range(self):
        """Test execution with date range"""
        result = self.tool.execute({
            'indicator': 'unemployment',
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        })
        
        self.assertIn('observations', result)
        # Demo mode will still return data
        self.assertGreater(len(result['observations']), 0)
    
    def test_limit_parameter_validation(self):
        """Test limit parameter constraints"""
        schema = self.tool.get_input_schema()
        limit_schema = schema['properties']['limit']
        
        self.assertEqual(limit_schema['minimum'], 1)
        self.assertEqual(limit_schema['maximum'], 1000)
        self.assertEqual(limit_schema['default'], 100)
    
    def test_observation_format(self):
        """Test observation data format"""
        result = self.tool.execute({
            'indicator': 'gdp',
            'limit': 2
        })
        
        if result['observations']:
            obs = result['observations'][0]
            self.assertIn('date', obs)
            self.assertIn('value', obs)
            
            # Value should be number or None
            self.assertTrue(
                isinstance(obs['value'], (int, float)) or 
                obs['value'] is None
            )


class TestFedGetLatestTool(unittest.TestCase):
    """Test suite for FedGetLatestTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FedGetLatestTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fed_get_latest')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('series_id', schema['properties'])
        self.assertIn('indicator', schema['properties'])
        
        # Should require one of series_id or indicator
        self.assertIn('oneOf', schema)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('date', schema['properties'])
        self.assertIn('value', schema['properties'])
        
        # Latest tool returns single value, not array
        self.assertNotIn('observations', schema['properties'])
    
    def test_execute_with_indicator(self):
        """Test execution with indicator shorthand"""
        result = self.tool.execute({
            'indicator': 'unemployment'
        })
        
        self.assertIn('series_id', result)
        self.assertIn('title', result)
        self.assertIn('date', result)
        self.assertIn('value', result)
        
        # Should return single value, not array
        self.assertNotIsInstance(result.get('value'), list)
    
    def test_execute_with_series_id(self):
        """Test execution with explicit series ID"""
        result = self.tool.execute({
            'series_id': 'DGS10'
        })
        
        self.assertEqual(result['series_id'], 'DGS10')
        self.assertIn('value', result)
    
    def test_all_common_indicators(self):
        """Test getting latest value for all common indicators"""
        indicators = [
            'gdp', 'unemployment', 'inflation', 'fed_rate',
            'treasury_10y', 'treasury_2y', 'sp500', 'housing',
            'retail', 'industrial', 'm2', 'pce'
        ]
        
        for indicator in indicators:
            result = self.tool.execute({'indicator': indicator})
            self.assertIn('value', result)
            self.assertIn('date', result)
    
    def test_value_types(self):
        """Test that values are numbers or None"""
        result = self.tool.execute({'indicator': 'gdp'})
        
        value = result['value']
        self.assertTrue(
            isinstance(value, (int, float)) or value is None
        )


class TestFedSearchSeriesTool(unittest.TestCase):
    """Test suite for FedSearchSeriesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FedSearchSeriesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fed_search_series')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('query', schema['properties'])
        self.assertIn('limit', schema['properties'])
        
        # Query should be required
        self.assertIn('query', schema['required'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('query', schema['properties'])
        self.assertIn('count', schema['properties'])
        self.assertIn('results', schema['properties'])
    
    def test_execute_search_demo_mode(self):
        """Test search execution in demo mode"""
        result = self.tool.execute({
            'query': 'unemployment'
        })
        
        self.assertIn('query', result)
        self.assertEqual(result['query'], 'unemployment')
        self.assertIn('count', result)
        self.assertIn('results', result)
        self.assertIsInstance(result['results'], list)
    
    def test_search_with_limit(self):
        """Test search with custom limit"""
        result = self.tool.execute({
            'query': 'GDP',
            'limit': 5
        })
        
        self.assertLessEqual(len(result['results']), 5)
    
    def test_limit_parameter_constraints(self):
        """Test limit parameter constraints"""
        schema = self.tool.get_input_schema()
        limit_schema = schema['properties']['limit']
        
        self.assertEqual(limit_schema['minimum'], 1)
        self.assertEqual(limit_schema['maximum'], 100)
        self.assertEqual(limit_schema['default'], 20)
    
    def test_result_structure(self):
        """Test search result structure"""
        result = self.tool.execute({
            'query': 'inflation',
            'limit': 2
        })
        
        if result['results']:
            series = result['results'][0]
            self.assertIn('id', series)
            self.assertIn('title', series)
            self.assertIn('units', series)
            self.assertIn('frequency', series)
    
    def test_empty_query_error(self):
        """Test error handling for empty query"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({})
        
        self.assertIn('query', str(context.exception).lower())


class TestFedGetCommonIndicatorsTool(unittest.TestCase):
    """Test suite for FedGetCommonIndicatorsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FedGetCommonIndicatorsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fed_get_common_indicators')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('indicators', schema['properties'])
        
        # Indicators should be array
        self.assertEqual(schema['properties']['indicators']['type'], 'array')
    
    def test_execute_default_indicators(self):
        """Test execution with default indicators (all)"""
        result = self.tool.execute({})
        
        self.assertIn('indicators', result)
        self.assertIn('last_updated', result)
        
        # Should return all 12 indicators
        self.assertEqual(len(result['indicators']), 12)
    
    def test_execute_specific_indicators(self):
        """Test execution with specific indicator list"""
        requested = ['gdp', 'unemployment', 'inflation']
        
        result = self.tool.execute({
            'indicators': requested
        })
        
        self.assertIn('indicators', result)
        indicators = result['indicators']
        
        # Should have exactly the requested indicators
        self.assertEqual(len(indicators), 3)
        for indicator in requested:
            self.assertIn(indicator, indicators)
    
    def test_execute_single_indicator(self):
        """Test execution with single indicator"""
        result = self.tool.execute({
            'indicators': ['fed_rate']
        })
        
        self.assertEqual(len(result['indicators']), 1)
        self.assertIn('fed_rate', result['indicators'])
    
    def test_indicator_data_structure(self):
        """Test structure of indicator data"""
        result = self.tool.execute({
            'indicators': ['gdp']
        })
        
        gdp_data = result['indicators']['gdp']
        
        if 'error' not in gdp_data:
            self.assertIn('series_id', gdp_data)
            self.assertIn('title', gdp_data)
            self.assertIn('value', gdp_data)
            self.assertIn('date', gdp_data)
            self.assertIn('units', gdp_data)
    
    def test_last_updated_timestamp(self):
        """Test that last_updated is valid ISO format"""
        result = self.tool.execute({})
        
        self.assertIn('last_updated', result)
        
        # Verify ISO 8601 format
        timestamp = result['last_updated']
        datetime.fromisoformat(timestamp)  # Should not raise exception
    
    def test_error_handling_invalid_indicator(self):
        """Test error handling for invalid indicator"""
        result = self.tool.execute({
            'indicators': ['invalid_indicator', 'gdp']
        })
        
        self.assertIn('indicators', result)
        
        # Invalid indicator should have error
        if 'invalid_indicator' in result['indicators']:
            self.assertIn('error', result['indicators']['invalid_indicator'])
        
        # Valid indicator should work
        if 'gdp' in result['indicators']:
            gdp_data = result['indicators']['gdp']
            if 'error' not in gdp_data:
                self.assertIn('value', gdp_data)
    
    def test_batch_retrieval_efficiency(self):
        """Test that batch retrieval works for multiple indicators"""
        indicators = ['gdp', 'unemployment', 'inflation', 'fed_rate']
        
        result = self.tool.execute({
            'indicators': indicators
        })
        
        # All requested indicators should be in result
        for indicator in indicators:
            self.assertIn(indicator, result['indicators'])


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry is defined"""
        self.assertIsNotNone(FED_RESERVE_TOOLS)
        self.assertIsInstance(FED_RESERVE_TOOLS, dict)
    
    def test_all_tools_in_registry(self):
        """Test that all 4 tools are in the registry"""
        expected_tools = [
            'fed_get_series',
            'fed_get_latest',
            'fed_search_series',
            'fed_get_common_indicators'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, FED_RESERVE_TOOLS)
    
    def test_tools_are_classes(self):
        """Test that registry contains class references"""
        for tool_name, tool_class in FED_RESERVE_TOOLS.items():
            self.assertTrue(callable(tool_class))
    
    def test_tool_instantiation(self):
        """Test that all tools can be instantiated"""
        for tool_name, tool_class in FED_RESERVE_TOOLS.items():
            try:
                tool_instance = tool_class()
                self.assertIsNotNone(tool_instance)
                self.assertTrue(hasattr(tool_instance, 'execute'))
                self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
                self.assertTrue(hasattr(tool_instance, 'get_output_schema'))
            except Exception as e:
                self.fail(f"Failed to instantiate {tool_name}: {e}")


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for common usage scenarios"""
    
    def test_scenario_economic_dashboard(self):
        """Test: Create an economic dashboard"""
        tool = FedGetCommonIndicatorsTool()
        result = tool.execute({
            'indicators': [
                'gdp',
                'unemployment',
                'inflation',
                'fed_rate',
                'treasury_10y',
                'sp500'
            ]
        })
        
        self.assertIn('indicators', result)
        self.assertIn('last_updated', result)
        
        # Verify we got multiple indicators
        self.assertGreaterEqual(len(result['indicators']), 5)
    
    def test_scenario_yield_curve_analysis(self):
        """Test: Analyze yield curve"""
        tool = FedGetLatestTool()
        
        # Get 2-year and 10-year rates
        rate_2y = tool.execute({'indicator': 'treasury_2y'})
        rate_10y = tool.execute({'indicator': 'treasury_10y'})
        
        self.assertIn('value', rate_2y)
        self.assertIn('value', rate_10y)
        
        # Calculate spread (if values are not None)
        if rate_2y['value'] is not None and rate_10y['value'] is not None:
            spread = rate_10y['value'] - rate_2y['value']
            self.assertIsInstance(spread, (int, float))
    
    def test_scenario_search_and_retrieve(self):
        """Test: Search for series then retrieve data"""
        # Step 1: Search
        search_tool = FedSearchSeriesTool()
        search_result = search_tool.execute({
            'query': 'unemployment',
            'limit': 5
        })
        
        self.assertGreater(len(search_result['results']), 0)
        
        # Step 2: Get data for first result
        if search_result['results']:
            series_id = search_result['results'][0]['id']
            
            series_tool = FedGetSeriesTool()
            data_result = series_tool.execute({
                'series_id': series_id,
                'limit': 5
            })
            
            self.assertIn('observations', data_result)
    
    def test_scenario_historical_comparison(self):
        """Test: Compare current vs historical values"""
        tool = FedGetSeriesTool()
        
        # Get recent data
        result = tool.execute({
            'indicator': 'unemployment',
            'limit': 12  # Last 12 months
        })
        
        self.assertIn('observations', result)
        
        if len(result['observations']) >= 2:
            recent = result['observations'][-1]['value']
            older = result['observations'][0]['value']
            
            # Both should be numbers or None
            if recent is not None and older is not None:
                change = recent - older
                self.assertIsInstance(change, (int, float))


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    """Test error handling and edge cases"""
    
    def test_missing_required_parameter(self):
        """Test handling of missing required parameters"""
        tool = FedSearchSeriesTool()
        
        with self.assertRaises(ValueError):
            tool.execute({})  # Missing required 'query'
    
    def test_invalid_indicator_name(self):
        """Test handling of invalid indicator"""
        tool = FedGetLatestTool()
        
        # Should either raise error or handle gracefully
        try:
            result = tool.execute({'indicator': 'invalid_xyz'})
            # If it returns, check for error indication
            self.assertTrue('error' in result or 'value' in result)
        except (ValueError, KeyError):
            # Expected to fail
            pass
    
    def test_null_values_in_observations(self):
        """Test handling of null values in time series"""
        tool = FedGetSeriesTool()
        result = tool.execute({
            'indicator': 'gdp',
            'limit': 10
        })
        
        # Should handle null values gracefully
        for obs in result['observations']:
            self.assertTrue(
                isinstance(obs['value'], (int, float)) or 
                obs['value'] is None
            )
    
    def test_large_limit_value(self):
        """Test handling of large limit values"""
        tool = FedGetSeriesTool()
        
        # Should respect maximum limit
        result = tool.execute({
            'indicator': 'gdp',
            'limit': 1000  # Maximum allowed
        })
        
        # Demo mode will return fewer, but should not error
        self.assertIn('observations', result)
        self.assertLessEqual(len(result['observations']), 1000)
    
    def test_date_range_validation(self):
        """Test date range handling"""
        tool = FedGetSeriesTool()
        
        # Valid date range
        result = tool.execute({
            'indicator': 'unemployment',
            'start_date': '2024-01-01',
            'end_date': '2024-12-31'
        })
        
        self.assertIn('observations', result)
    
    def test_empty_indicators_list(self):
        """Test common indicators with empty list"""
        tool = FedGetCommonIndicatorsTool()
        
        result = tool.execute({
            'indicators': []
        })
        
        # Should fall back to all indicators
        self.assertIn('indicators', result)
        self.assertGreater(len(result['indicators']), 0)


class TestDemoMode(unittest.TestCase):
    """Test demo mode functionality"""
    
    def test_demo_mode_indicator(self):
        """Test that demo mode is indicated in responses"""
        tool = FedGetSeriesTool()
        
        result = tool.execute({
            'indicator': 'gdp',
            'limit': 5
        })
        
        # Demo mode should add a note
        if 'note' in result:
            self.assertIn('demo', result['note'].lower())
    
    def test_demo_mode_data_format(self):
        """Test that demo mode returns properly formatted data"""
        tool = FedGetSeriesTool()
        
        result = tool.execute({
            'indicator': 'unemployment'
        })
        
        # Should have all required fields
        self.assertIn('series_id', result)
        self.assertIn('title', result)
        self.assertIn('observations', result)
        
        # Observations should be properly formatted
        if result['observations']:
            obs = result['observations'][0]
            self.assertIn('date', obs)
            self.assertIn('value', obs)
    
    def test_demo_mode_search(self):
        """Test demo mode search functionality"""
        tool = FedSearchSeriesTool()
        
        result = tool.execute({
            'query': 'test search'
        })
        
        # Should return results structure
        self.assertIn('query', result)
        self.assertIn('results', result)
        
        if 'note' in result:
            self.assertIn('demo', result['note'].lower())


class TestDataValidation(unittest.TestCase):
    """Test data validation and constraints"""
    
    def test_series_id_format(self):
        """Test series ID format"""
        # FRED series IDs are typically uppercase alphanumeric
        valid_ids = ['GDP', 'UNRATE', 'DGS10', 'CPIAUCSL']
        
        for series_id in valid_ids:
            # Should be uppercase
            self.assertEqual(series_id, series_id.upper())
            # Should be alphanumeric
            self.assertTrue(series_id.replace('_', '').isalnum())
    
    def test_date_format(self):
        """Test date format in observations"""
        tool = FedGetSeriesTool()
        result = tool.execute({
            'indicator': 'gdp',
            'limit': 2
        })
        
        if result['observations']:
            date_str = result['observations'][0]['date']
            
            # Should be YYYY-MM-DD format
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                self.fail(f"Invalid date format: {date_str}")
    
    def test_value_types(self):
        """Test that values are numeric or None"""
        tool = FedGetSeriesTool()
        result = tool.execute({
            'indicator': 'inflation'
        })
        
        for obs in result['observations']:
            value = obs['value']
            self.assertTrue(
                isinstance(value, (int, float)) or value is None,
                f"Invalid value type: {type(value)}"
            )


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
        TestFedGetSeriesTool,
        TestFedGetLatestTool,
        TestFedSearchSeriesTool,
        TestFedGetCommonIndicatorsTool,
        TestToolRegistry,
        TestIntegrationScenarios,
        TestErrorHandlingAndEdgeCases,
        TestDemoMode,
        TestDataValidation
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
    print("Federal Reserve MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
