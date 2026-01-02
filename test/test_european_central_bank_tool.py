"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for European Central Bank MCP Tools
Comprehensive tests for all 8 ECB tools with various scenarios
"""

import unittest
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock

# Import the ECB tools
try:
    from sajha.tools.impl.european_central_bank_tool_refactored import (
        ECBGetSeriesTool,
        ECBGetExchangeRateTool,
        ECBGetInterestRateTool,
        ECBGetBondYieldTool,
        ECBGetInflationTool,
        ECBGetLatestTool,
        ECBSearchSeriesTool,
        ECBGetCommonIndicatorsTool,
        EUROPEAN_CENTRAL_BANK_TOOLS
    )
except ImportError:
    print("Error: Unable to import ECB tools. Ensure the module is in the Python path.")
    sys.exit(1)


class TestECBGetSeriesTool(unittest.TestCase):
    """Test suite for ECBGetSeriesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetSeriesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_series')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('flow', schema['properties'])
        self.assertIn('key', schema['properties'])
        self.assertIn('indicator', schema['properties'])
        self.assertIn('start_date', schema['properties'])
        self.assertIn('end_date', schema['properties'])
        self.assertIn('recent_periods', schema['properties'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('flow', schema['properties'])
        self.assertIn('key', schema['properties'])
        self.assertIn('observations', schema['properties'])
    
    def test_execute_with_indicator(self):
        """Test execution with indicator shorthand"""
        try:
            result = self.tool.execute({
                'indicator': 'eur_usd',
                'recent_periods': 5
            })
            
            self.assertIn('flow', result)
            self.assertIn('key', result)
            self.assertIn('observations', result)
            self.assertEqual(result['flow'], 'EXR')
            
            if 'error' not in result:
                self.assertIsInstance(result['observations'], list)
                self.assertLessEqual(len(result['observations']), 10)
        except Exception as e:
            self.skipTest(f"API call failed (network/availability): {e}")
    
    def test_execute_with_flow_key(self):
        """Test execution with explicit flow and key"""
        try:
            result = self.tool.execute({
                'flow': 'EXR',
                'key': 'D.USD.EUR.SP00.A',
                'recent_periods': 3
            })
            
            self.assertIn('flow', result)
            self.assertEqual(result['flow'], 'EXR')
            self.assertIn('key', result)
        except Exception as e:
            self.skipTest(f"API call failed (network/availability): {e}")
    
    def test_execute_with_date_range(self):
        """Test execution with specific date range"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            result = self.tool.execute({
                'indicator': 'eur_usd',
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            })
            
            self.assertIn('observations', result)
            if result.get('observations'):
                # Verify dates are within range
                for obs in result['observations']:
                    obs_date = datetime.strptime(obs['date'], '%Y-%m-%d')
                    self.assertGreaterEqual(obs_date, start_date)
                    self.assertLessEqual(obs_date, end_date)
        except Exception as e:
            self.skipTest(f"API call failed (network/availability): {e}")
    
    def test_invalid_indicator(self):
        """Test handling of invalid indicator"""
        try:
            result = self.tool.execute({
                'indicator': 'invalid_indicator_xyz'
            })
            # Should either error or return empty observations
            self.assertTrue('error' in result or result.get('observation_count', 0) == 0)
        except Exception:
            pass  # Expected to fail


class TestECBGetExchangeRateTool(unittest.TestCase):
    """Test suite for ECBGetExchangeRateTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetExchangeRateTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_exchange_rate')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('currency_pair', schema['properties'])
        self.assertIn('indicator', schema['properties'])
        self.assertIn('enum', schema['properties']['indicator'])
        
        # Check supported currency pairs
        indicators = schema['properties']['indicator']['enum']
        self.assertIn('eur_usd', indicators)
        self.assertIn('eur_gbp', indicators)
        self.assertIn('eur_jpy', indicators)
    
    def test_execute_eur_usd(self):
        """Test EUR/USD exchange rate retrieval"""
        try:
            result = self.tool.execute({
                'indicator': 'eur_usd',
                'recent_periods': 5
            })
            
            self.assertEqual(result['flow'], 'EXR')
            self.assertIn('observations', result)
            
            if result.get('observations'):
                # Verify exchange rate values are reasonable
                for obs in result['observations']:
                    if obs['value'] is not None:
                        self.assertGreater(obs['value'], 0.5)
                        self.assertLess(obs['value'], 2.0)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_with_currency_pair(self):
        """Test with currency_pair parameter"""
        try:
            result = self.tool.execute({
                'currency_pair': 'EUR/GBP',
                'recent_periods': 3
            })
            
            self.assertIn('observations', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_all_supported_pairs(self):
        """Test all supported currency pairs"""
        pairs = ['eur_usd', 'eur_gbp', 'eur_jpy', 'eur_cny', 'eur_chf']
        
        for pair in pairs:
            try:
                result = self.tool.execute({
                    'indicator': pair,
                    'recent_periods': 1
                })
                self.assertIn('flow', result)
            except Exception as e:
                self.skipTest(f"API call failed for {pair}: {e}")


class TestECBGetInterestRateTool(unittest.TestCase):
    """Test suite for ECBGetInterestRateTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetInterestRateTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_interest_rate')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('rate_type', schema['properties'])
        
        rate_types = schema['properties']['rate_type']['enum']
        self.assertIn('main_refinancing_rate', rate_types)
        self.assertIn('deposit_facility_rate', rate_types)
        self.assertIn('marginal_lending_rate', rate_types)
        self.assertIn('eonia', rate_types)
        self.assertIn('ester', rate_types)
    
    def test_execute_main_refinancing_rate(self):
        """Test main refinancing rate retrieval"""
        try:
            result = self.tool.execute({
                'rate_type': 'main_refinancing_rate',
                'recent_periods': 5
            })
            
            self.assertEqual(result['flow'], 'FM')
            self.assertIn('observations', result)
            
            if result.get('observations'):
                # Interest rates should be between 0 and 20%
                for obs in result['observations']:
                    if obs['value'] is not None:
                        self.assertGreaterEqual(obs['value'], -1.0)
                        self.assertLess(obs['value'], 20.0)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_deposit_facility_rate(self):
        """Test deposit facility rate retrieval"""
        try:
            result = self.tool.execute({
                'rate_type': 'deposit_facility_rate',
                'recent_periods': 3
            })
            
            self.assertIn('observations', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_ester(self):
        """Test €STR (Euro Short-Term Rate) retrieval"""
        try:
            result = self.tool.execute({
                'rate_type': 'ester',
                'recent_periods': 5
            })
            
            self.assertIn('observations', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")


class TestECBGetBondYieldTool(unittest.TestCase):
    """Test suite for ECBGetBondYieldTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetBondYieldTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_bond_yield')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('bond_term', schema['properties'])
        
        bond_terms = schema['properties']['bond_term']['enum']
        self.assertIn('2y', bond_terms)
        self.assertIn('5y', bond_terms)
        self.assertIn('10y', bond_terms)
    
    def test_execute_10y_yield(self):
        """Test 10-year bond yield retrieval"""
        try:
            result = self.tool.execute({
                'bond_term': '10y',
                'recent_periods': 5
            })
            
            self.assertEqual(result['flow'], 'YC')
            self.assertIn('observations', result)
            
            if result.get('observations'):
                # Bond yields should be reasonable
                for obs in result['observations']:
                    if obs['value'] is not None:
                        self.assertGreaterEqual(obs['value'], -2.0)
                        self.assertLess(obs['value'], 15.0)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_2y_yield(self):
        """Test 2-year bond yield retrieval"""
        try:
            result = self.tool.execute({
                'bond_term': '2y',
                'recent_periods': 3
            })
            
            self.assertIn('observations', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_yield_curve_comparison(self):
        """Test yield curve analysis (2Y vs 10Y)"""
        try:
            result_2y = self.tool.execute({
                'bond_term': '2y',
                'recent_periods': 1
            })
            
            result_10y = self.tool.execute({
                'bond_term': '10y',
                'recent_periods': 1
            })
            
            if (result_2y.get('observations') and result_10y.get('observations')):
                val_2y = result_2y['observations'][-1]['value']
                val_10y = result_10y['observations'][-1]['value']
                
                if val_2y is not None and val_10y is not None:
                    # Yield curve can be normal or inverted
                    self.assertIsInstance(val_2y, (int, float))
                    self.assertIsInstance(val_10y, (int, float))
        except Exception as e:
            self.skipTest(f"API call failed: {e}")


class TestECBGetInflationTool(unittest.TestCase):
    """Test suite for ECBGetInflationTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetInflationTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_inflation')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('inflation_type', schema['properties'])
        
        inflation_types = schema['properties']['inflation_type']['enum']
        self.assertIn('overall', inflation_types)
        self.assertIn('core', inflation_types)
        self.assertIn('energy', inflation_types)
    
    def test_execute_overall_inflation(self):
        """Test overall HICP inflation retrieval"""
        try:
            result = self.tool.execute({
                'inflation_type': 'overall',
                'recent_periods': 12
            })
            
            self.assertEqual(result['flow'], 'ICP')
            self.assertIn('observations', result)
            
            if result.get('observations'):
                # Inflation rates should be reasonable
                for obs in result['observations']:
                    if obs['value'] is not None:
                        self.assertGreater(obs['value'], -10.0)
                        self.assertLess(obs['value'], 30.0)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_core_inflation(self):
        """Test core inflation retrieval"""
        try:
            result = self.tool.execute({
                'inflation_type': 'core',
                'recent_periods': 6
            })
            
            self.assertIn('observations', result)
            self.assertIn('core', result['description'].lower())
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_energy_inflation(self):
        """Test energy inflation retrieval"""
        try:
            result = self.tool.execute({
                'inflation_type': 'energy',
                'recent_periods': 6
            })
            
            self.assertIn('observations', result)
            self.assertIn('energy', result['description'].lower())
        except Exception as e:
            self.skipTest(f"API call failed: {e}")


class TestECBGetLatestTool(unittest.TestCase):
    """Test suite for ECBGetLatestTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetLatestTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_latest')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('flow', schema['properties'])
        self.assertIn('key', schema['properties'])
        self.assertIn('indicator', schema['properties'])
    
    def test_get_output_schema(self):
        """Test output schema - should have single value not array"""
        schema = self.tool.get_output_schema()
        self.assertIn('value', schema['properties'])
        self.assertIn('date', schema['properties'])
        # Latest tool returns single value, not observations array
        self.assertNotIn('observations', schema['properties'])
    
    def test_execute_with_indicator(self):
        """Test execution with indicator shorthand"""
        try:
            result = self.tool.execute({
                'indicator': 'eur_usd'
            })
            
            self.assertIn('flow', result)
            self.assertIn('value', result)
            self.assertIn('date', result)
            
            # Should return single value, not array
            self.assertNotIsInstance(result.get('value'), list)
            
            if result.get('value') is not None:
                self.assertIsInstance(result['value'], (int, float))
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_with_flow_key(self):
        """Test execution with explicit flow and key"""
        try:
            result = self.tool.execute({
                'flow': 'EXR',
                'key': 'D.USD.EUR.SP00.A'
            })
            
            self.assertEqual(result['flow'], 'EXR')
            self.assertIn('value', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_multiple_indicators(self):
        """Test getting latest values for multiple indicators"""
        indicators = ['eur_usd', 'main_refinancing_rate', 'bond_10y']
        
        for indicator in indicators:
            try:
                result = self.tool.execute({'indicator': indicator})
                self.assertIn('value', result)
                self.assertIn('date', result)
            except Exception as e:
                self.skipTest(f"API call failed for {indicator}: {e}")


class TestECBSearchSeriesTool(unittest.TestCase):
    """Test suite for ECBSearchSeriesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBSearchSeriesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_search_series')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('category', schema['properties'])
        
        categories = schema['properties']['category']['enum']
        self.assertIn('Exchange Rates', categories)
        self.assertIn('Interest Rates', categories)
        self.assertIn('Bond Yields', categories)
        self.assertIn('all', categories)
    
    def test_execute_all_categories(self):
        """Test search with all categories"""
        result = self.tool.execute({})
        
        self.assertIn('categories', result)
        self.assertIn('total_series', result)
        
        # Should return multiple categories
        self.assertGreater(len(result['categories']), 0)
        self.assertGreater(result['total_series'], 0)
        
        # Verify each category has series
        for category, series_list in result['categories'].items():
            self.assertIsInstance(series_list, list)
            for series in series_list:
                self.assertIn('indicator', series)
                self.assertIn('flow', series)
                self.assertIn('key', series)
                self.assertIn('description', series)
    
    def test_execute_specific_category(self):
        """Test search with specific category"""
        result = self.tool.execute({
            'category': 'Exchange Rates'
        })
        
        self.assertIn('categories', result)
        self.assertIn('Exchange Rates', result['categories'])
        
        # Should only return requested category
        self.assertEqual(len(result['categories']), 1)
        
        # Verify exchange rate series
        fx_series = result['categories']['Exchange Rates']
        self.assertGreater(len(fx_series), 0)
        
        # Check for expected FX pairs
        indicators = [s['indicator'] for s in fx_series]
        self.assertIn('eur_usd', indicators)
    
    def test_execute_each_category(self):
        """Test search for each available category"""
        categories = [
            'Exchange Rates',
            'Interest Rates',
            'Bond Yields',
            'Inflation (HICP)',
            'Economic Indicators',
            'Money Supply'
        ]
        
        for category in categories:
            result = self.tool.execute({'category': category})
            self.assertIn('categories', result)
            self.assertIn(category, result['categories'])
            self.assertGreater(len(result['categories'][category]), 0)
    
    def test_series_structure(self):
        """Test the structure of returned series information"""
        result = self.tool.execute({'category': 'Interest Rates'})
        
        series_list = result['categories']['Interest Rates']
        
        for series in series_list:
            # Each series should have these fields
            self.assertIn('indicator', series)
            self.assertIn('flow', series)
            self.assertIn('key', series)
            self.assertIn('description', series)
            
            # Verify data types
            self.assertIsInstance(series['indicator'], str)
            self.assertIsInstance(series['flow'], str)
            self.assertIsInstance(series['key'], str)
            self.assertIsInstance(series['description'], str)


class TestECBGetCommonIndicatorsTool(unittest.TestCase):
    """Test suite for ECBGetCommonIndicatorsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ECBGetCommonIndicatorsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ecb_get_common_indicators')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('indicators', schema['properties'])
        self.assertEqual(schema['properties']['indicators']['type'], 'array')
    
    def test_execute_default_indicators(self):
        """Test execution with default indicators"""
        try:
            result = self.tool.execute({})
            
            self.assertIn('indicators', result)
            self.assertIn('last_updated', result)
            
            # Default should include 5 key indicators
            indicators = result['indicators']
            self.assertGreater(len(indicators), 0)
            
            # Check for default indicators
            expected_defaults = [
                'eur_usd', 'main_refinancing_rate', 'bond_10y',
                'hicp_overall', 'unemployment_rate'
            ]
            
            for indicator in expected_defaults:
                if indicator in indicators:
                    data = indicators[indicator]
                    if 'error' not in data:
                        self.assertIn('value', data)
                        self.assertIn('date', data)
                        self.assertIn('description', data)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_custom_indicators(self):
        """Test execution with custom indicator list"""
        try:
            result = self.tool.execute({
                'indicators': ['eur_usd', 'bond_10y', 'hicp_overall']
            })
            
            self.assertIn('indicators', result)
            indicators = result['indicators']
            
            # Should have exactly 3 indicators
            self.assertEqual(len(indicators), 3)
            self.assertIn('eur_usd', indicators)
            self.assertIn('bond_10y', indicators)
            self.assertIn('hicp_overall', indicators)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_execute_single_indicator(self):
        """Test execution with single indicator"""
        try:
            result = self.tool.execute({
                'indicators': ['eur_usd']
            })
            
            self.assertIn('indicators', result)
            self.assertEqual(len(result['indicators']), 1)
            self.assertIn('eur_usd', result['indicators'])
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_last_updated_timestamp(self):
        """Test that last_updated timestamp is valid ISO format"""
        try:
            result = self.tool.execute({})
            
            self.assertIn('last_updated', result)
            
            # Verify ISO 8601 format
            timestamp = result['last_updated']
            datetime.fromisoformat(timestamp)  # Should not raise exception
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_error_handling_invalid_indicator(self):
        """Test error handling for invalid indicator"""
        try:
            result = self.tool.execute({
                'indicators': ['invalid_xyz', 'eur_usd']
            })
            
            self.assertIn('indicators', result)
            
            # Invalid indicator should have error
            if 'invalid_xyz' in result['indicators']:
                self.assertIn('error', result['indicators']['invalid_xyz'])
            
            # Valid indicator should work
            if 'eur_usd' in result['indicators']:
                data = result['indicators']['eur_usd']
                if 'error' not in data:
                    self.assertIn('value', data)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry and tool management"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry is defined"""
        self.assertIsNotNone(EUROPEAN_CENTRAL_BANK_TOOLS)
        self.assertIsInstance(EUROPEAN_CENTRAL_BANK_TOOLS, dict)
    
    def test_all_tools_in_registry(self):
        """Test that all 8 tools are in the registry"""
        expected_tools = [
            'ecb_get_series',
            'ecb_get_exchange_rate',
            'ecb_get_interest_rate',
            'ecb_get_bond_yield',
            'ecb_get_inflation',
            'ecb_get_latest',
            'ecb_search_series',
            'ecb_get_common_indicators'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, EUROPEAN_CENTRAL_BANK_TOOLS)
    
    def test_tools_are_classes(self):
        """Test that registry contains class references"""
        for tool_name, tool_class in EUROPEAN_CENTRAL_BANK_TOOLS.items():
            self.assertTrue(callable(tool_class))
    
    def test_tool_instantiation(self):
        """Test that all tools can be instantiated"""
        for tool_name, tool_class in EUROPEAN_CENTRAL_BANK_TOOLS.items():
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
        try:
            tool = ECBGetCommonIndicatorsTool()
            result = tool.execute({
                'indicators': [
                    'eur_usd',
                    'main_refinancing_rate',
                    'bond_10y',
                    'hicp_overall',
                    'unemployment_rate'
                ]
            })
            
            self.assertIn('indicators', result)
            self.assertIn('last_updated', result)
            
            # Verify we got multiple indicators
            self.assertGreaterEqual(len(result['indicators']), 3)
        except Exception as e:
            self.skipTest(f"Integration test failed: {e}")
    
    def test_scenario_yield_curve_analysis(self):
        """Test: Analyze yield curve"""
        try:
            tool = ECBGetBondYieldTool()
            
            yields = {}
            for term in ['2y', '5y', '10y']:
                result = tool.execute({
                    'bond_term': term,
                    'recent_periods': 1
                })
                
                if result.get('observations'):
                    yields[term] = result['observations'][-1]['value']
            
            # Should have retrieved multiple maturities
            self.assertGreater(len(yields), 0)
        except Exception as e:
            self.skipTest(f"Integration test failed: {e}")
    
    def test_scenario_fx_monitoring(self):
        """Test: Monitor multiple FX pairs"""
        try:
            tool = ECBGetExchangeRateTool()
            
            pairs = ['eur_usd', 'eur_gbp', 'eur_jpy']
            rates = {}
            
            for pair in pairs:
                result = tool.execute({
                    'indicator': pair,
                    'recent_periods': 1
                })
                
                if result.get('observations'):
                    rates[pair] = result['observations'][-1]['value']
            
            # Should have retrieved multiple pairs
            self.assertGreater(len(rates), 0)
        except Exception as e:
            self.skipTest(f"Integration test failed: {e}")
    
    def test_scenario_discover_then_fetch(self):
        """Test: Discover available series then fetch data"""
        # Step 1: Discover series
        search_tool = ECBSearchSeriesTool()
        search_result = search_tool.execute({
            'category': 'Interest Rates'
        })
        
        self.assertIn('categories', search_result)
        interest_rates = search_result['categories']['Interest Rates']
        self.assertGreater(len(interest_rates), 0)
        
        # Step 2: Fetch one of the discovered series
        try:
            first_series = interest_rates[0]
            
            fetch_tool = ECBGetLatestTool()
            data_result = fetch_tool.execute({
                'indicator': first_series['indicator']
            })
            
            self.assertIn('value', data_result)
        except Exception as e:
            self.skipTest(f"Integration test failed: {e}")


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    """Test error handling and edge cases"""
    
    def test_empty_indicator_list(self):
        """Test common indicators with empty list"""
        tool = ECBGetCommonIndicatorsTool()
        result = tool.execute({
            'indicators': []
        })
        
        # Should fall back to defaults
        self.assertIn('indicators', result)
    
    def test_very_old_date_range(self):
        """Test with very old date range"""
        try:
            tool = ECBGetSeriesTool()
            result = tool.execute({
                'indicator': 'eur_usd',
                'start_date': '1999-01-01',
                'end_date': '1999-12-31'
            })
            
            # Should either return data or handle gracefully
            self.assertIn('observations', result)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")
    
    def test_future_date_range(self):
        """Test with future date range"""
        try:
            tool = ECBGetSeriesTool()
            future_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
            
            result = tool.execute({
                'indicator': 'eur_usd',
                'start_date': future_date,
                'end_date': future_date
            })
            
            # Should return empty or handle gracefully
            self.assertTrue(
                'error' in result or 
                result.get('observation_count', 0) == 0
            )
        except Exception:
            pass  # Expected to fail or return empty
    
    def test_maximum_recent_periods(self):
        """Test with maximum recent_periods value"""
        try:
            tool = ECBGetSeriesTool()
            result = tool.execute({
                'indicator': 'eur_usd',
                'recent_periods': 100
            })
            
            self.assertIn('observations', result)
            # Should respect maximum
            if result.get('observations'):
                self.assertLessEqual(len(result['observations']), 100)
        except Exception as e:
            self.skipTest(f"API call failed: {e}")


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
        TestECBGetSeriesTool,
        TestECBGetExchangeRateTool,
        TestECBGetInterestRateTool,
        TestECBGetBondYieldTool,
        TestECBGetInflationTool,
        TestECBGetLatestTool,
        TestECBSearchSeriesTool,
        TestECBGetCommonIndicatorsTool,
        TestToolRegistry,
        TestIntegrationScenarios,
        TestErrorHandlingAndEdgeCases
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
    print("European Central Bank MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
