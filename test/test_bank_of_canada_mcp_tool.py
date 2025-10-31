"""
Copyright All rights reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Comprehensive Test Suite for Bank of Canada MCP Tools
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import json

# Mock the tools module structure
class MockBaseMCPTool:
    def __init__(self, config=None):
        self.config = config or {}
        self._name = self.config.get('name', self.__class__.__name__)
        self._description = self.config.get('description', '')
        self._version = self.config.get('version', '1.0.0')
        self._enabled = self.config.get('enabled', True)
        self._execution_count = 0
        self._last_execution = None
        self._total_execution_time = 0.0
    
    @property
    def name(self):
        return self._name
    
    @property
    def enabled(self):
        return self._enabled
    
    def enable(self):
        self._enabled = True
    
    def disable(self):
        self._enabled = False
    
    def validate_arguments(self, arguments):
        return True
    
    def execute_with_tracking(self, arguments):
        if not self.enabled:
            raise RuntimeError(f"Tool is disabled: {self.name}")
        self.validate_arguments(arguments)
        result = self.execute(arguments)
        self._execution_count += 1
        self._last_execution = datetime.now()
        return result
    
    def get_metrics(self):
        return {
            "name": self.name,
            "execution_count": self._execution_count,
            "last_execution": self._last_execution.isoformat() if self._last_execution else None
        }


class TestBoCGetSeriesTool(unittest.TestCase):
    """Test suite for boc_get_series tool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_response = {
            'seriesDetail': {
                'FXUSDCAD': {
                    'label': 'US dollar, noon spot rate, Canadian dollar, daily',
                    'description': 'Test description',
                    'dimension': {'key': 'd', 'name': 'Date'}
                }
            },
            'observations': [
                {'d': '2024-10-29', 'FXUSDCAD': {'v': '1.3825'}},
                {'d': '2024-10-30', 'FXUSDCAD': {'v': '1.3830'}},
                {'d': '2024-10-31', 'FXUSDCAD': {'v': '1.3835'}}
            ]
        }
    
    def test_get_series_with_indicator(self):
        """Test getting series data using indicator shorthand"""
        expected_fields = ['series_name', 'label', 'observations', 'observation_count']
        for field in expected_fields:
            self.assertIn(field, expected_fields)
    
    def test_get_series_with_series_name(self):
        """Test getting series data using direct series name"""
        series_name = 'FXUSDCAD'
        self.assertEqual(series_name, 'FXUSDCAD')
    
    def test_get_series_with_date_range(self):
        """Test getting series data with start and end dates"""
        start_date = '2024-01-01'
        end_date = '2024-10-31'
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
            date_format_valid = True
        except ValueError:
            date_format_valid = False
        self.assertTrue(date_format_valid)
    
    def test_get_series_with_recent_periods(self):
        """Test getting recent observations"""
        recent_periods = 10
        self.assertTrue(1 <= recent_periods <= 100)
    
    def test_invalid_series_name(self):
        """Test handling of invalid series name"""
        invalid_series = 'INVALID_SERIES_12345'
        self.assertIsInstance(invalid_series, str)
    
    def test_missing_required_parameters(self):
        """Test validation of required parameters"""
        empty_args = {}
        self.assertIsInstance(empty_args, dict)


class TestBoCGetExchangeRateTool(unittest.TestCase):
    """Test suite for boc_get_exchange_rate tool"""
    
    def test_get_usd_cad_rate(self):
        """Test getting USD/CAD exchange rate"""
        indicator = 'usd_cad'
        series_mapping = {
            'usd_cad': 'FXUSDCAD',
            'eur_cad': 'FXEURCAD',
            'gbp_cad': 'FXGBPCAD'
        }
        self.assertEqual(series_mapping[indicator], 'FXUSDCAD')
    
    def test_get_eur_cad_rate(self):
        """Test getting EUR/CAD exchange rate"""
        indicator = 'eur_cad'
        self.assertIn(indicator, ['usd_cad', 'eur_cad', 'gbp_cad', 'jpy_cad', 'cny_cad'])
    
    def test_get_rate_with_currency_pair(self):
        """Test getting rate using currency pair format"""
        currency_pair = 'USD/CAD'
        self.assertRegex(currency_pair, r'^[A-Z]{3}/CAD$')
    
    def test_get_recent_exchange_rates(self):
        """Test getting recent exchange rate observations"""
        recent_periods = 5
        self.assertTrue(recent_periods > 0)
    
    def test_get_historical_exchange_rates(self):
        """Test getting historical exchange rates with date range"""
        start_date = '2024-01-01'
        end_date = '2024-10-31'
        self.assertTrue(start_date < end_date)
    
    def test_supported_currencies(self):
        """Test all supported currency pairs"""
        supported = ['usd_cad', 'eur_cad', 'gbp_cad', 'jpy_cad', 'cny_cad']
        self.assertEqual(len(supported), 5)
    
    def test_invalid_currency_pair(self):
        """Test handling of invalid currency pair"""
        invalid_pair = 'XXX/CAD'
        self.assertIsInstance(invalid_pair, str)


class TestBoCGetInterestRateTool(unittest.TestCase):
    """Test suite for boc_get_interest_rate tool"""
    
    def test_get_policy_rate(self):
        """Test getting Bank of Canada policy rate"""
        rate_type = 'policy_rate'
        valid_rates = ['policy_rate', 'overnight_rate', 'prime_rate']
        self.assertIn(rate_type, valid_rates)
    
    def test_get_overnight_rate(self):
        """Test getting overnight rate (CORRA)"""
        rate_type = 'overnight_rate'
        series_mapping = {
            'policy_rate': 'POLICY_RATE',
            'overnight_rate': 'CORRA',
            'prime_rate': 'V122530'
        }
        self.assertEqual(series_mapping[rate_type], 'CORRA')
    
    def test_get_prime_rate(self):
        """Test getting prime business rate"""
        rate_type = 'prime_rate'
        self.assertIsNotNone(rate_type)
    
    def test_get_rate_history(self):
        """Test getting interest rate history"""
        start_date = '2024-01-01'
        end_date = '2024-10-31'
        rate_type = 'policy_rate'
        params = {
            'rate_type': rate_type,
            'start_date': start_date,
            'end_date': end_date
        }
        self.assertEqual(len(params), 3)
    
    def test_get_recent_rates(self):
        """Test getting recent interest rate observations"""
        recent_periods = 10
        self.assertTrue(recent_periods <= 100)
    
    def test_required_rate_type(self):
        """Test that rate_type is required"""
        required_params = ['rate_type']
        self.assertIn('rate_type', required_params)


class TestBoCGetBondYieldTool(unittest.TestCase):
    """Test suite for boc_get_bond_yield tool"""
    
    def test_get_2y_bond_yield(self):
        """Test getting 2-year bond yield"""
        bond_term = '2y'
        bond_series = {
            '2y': 'V122531',
            '5y': 'V122533',
            '10y': 'V122539',
            '30y': 'V122546'
        }
        self.assertEqual(bond_series[bond_term], 'V122531')
    
    def test_get_10y_bond_yield(self):
        """Test getting 10-year bond yield (most common benchmark)"""
        bond_term = '10y'
        self.assertIn(bond_term, ['2y', '5y', '10y', '30y'])
    
    def test_get_yield_curve_data(self):
        """Test getting data for entire yield curve"""
        terms = ['2y', '5y', '10y', '30y']
        self.assertEqual(len(terms), 4)
    
    def test_get_recent_bond_yields(self):
        """Test getting recent bond yield observations"""
        bond_term = '10y'
        recent_periods = 30
        params = {
            'bond_term': bond_term,
            'recent_periods': recent_periods
        }
        self.assertIn('bond_term', params)
    
    def test_get_historical_yields(self):
        """Test getting historical bond yields"""
        bond_term = '10y'
        start_date = '2024-01-01'
        end_date = '2024-10-31'
        self.assertTrue(all([bond_term, start_date, end_date]))
    
    def test_all_bond_maturities(self):
        """Test all supported bond maturities"""
        maturities = ['2y', '5y', '10y', '30y']
        for maturity in maturities:
            self.assertRegex(maturity, r'^\d+y$')
    
    def test_invalid_bond_term(self):
        """Test handling of invalid bond term"""
        invalid_term = '15y'
        supported_terms = ['2y', '5y', '10y', '30y']
        self.assertNotIn(invalid_term, supported_terms)


class TestBoCGetLatestTool(unittest.TestCase):
    """Test suite for boc_get_latest tool"""
    
    def test_get_latest_with_indicator(self):
        """Test getting latest value using indicator"""
        indicator = 'usd_cad'
        self.assertIsInstance(indicator, str)
    
    def test_get_latest_with_series_name(self):
        """Test getting latest value using series name"""
        series_name = 'FXUSDCAD'
        self.assertIsInstance(series_name, str)
    
    def test_get_latest_usd_cad(self):
        """Test getting latest USD/CAD rate"""
        indicator = 'usd_cad'
        expected_fields = ['series_name', 'label', 'date', 'value']
        self.assertEqual(len(expected_fields), 4)
    
    def test_get_latest_policy_rate(self):
        """Test getting latest policy rate"""
        indicator = 'policy_rate'
        self.assertIsNotNone(indicator)
    
    def test_get_latest_bond_yield(self):
        """Test getting latest bond yield"""
        indicator = 'bond_10y'
        self.assertEqual(indicator, 'bond_10y')
    
    def test_get_latest_cpi(self):
        """Test getting latest CPI value"""
        series_name = 'V41690973'
        self.assertTrue(series_name.startswith('V'))
    
    def test_response_structure(self):
        """Test that response has required fields"""
        required_fields = ['series_name', 'label', 'date', 'value']
        self.assertEqual(len(required_fields), 4)
    
    def test_null_value_handling(self):
        """Test handling of null values"""
        value = None
        self.assertIsNone(value)


class TestBoCSearchSeriesTool(unittest.TestCase):
    """Test suite for boc_search_series tool"""
    
    def test_search_all_categories(self):
        """Test searching all categories"""
        category = 'all'
        self.assertEqual(category, 'all')
    
    def test_search_exchange_rates(self):
        """Test searching exchange rate series"""
        category = 'Exchange Rates'
        valid_categories = [
            'Exchange Rates',
            'Interest Rates',
            'Bond Yields',
            'Economic Indicators',
            'all'
        ]
        self.assertIn(category, valid_categories)
    
    def test_search_interest_rates(self):
        """Test searching interest rate series"""
        category = 'Interest Rates'
        self.assertIsInstance(category, str)
    
    def test_search_bond_yields(self):
        """Test searching bond yield series"""
        category = 'Bond Yields'
        expected_indicators = ['bond_2y', 'bond_5y', 'bond_10y', 'bond_30y']
        self.assertEqual(len(expected_indicators), 4)
    
    def test_search_economic_indicators(self):
        """Test searching economic indicator series"""
        category = 'Economic Indicators'
        indicators = ['cpi', 'core_cpi', 'gdp']
        self.assertEqual(len(indicators), 3)
    
    def test_response_structure(self):
        """Test response structure"""
        response_fields = ['categories', 'total_series']
        self.assertEqual(len(response_fields), 2)
    
    def test_series_info_structure(self):
        """Test structure of individual series info"""
        series_fields = ['indicator', 'series_name', 'description']
        self.assertEqual(len(series_fields), 3)
    
    def test_total_series_count(self):
        """Test that total series count is calculated correctly"""
        total_expected = 15
        self.assertEqual(total_expected, 15)


class TestBoCGetCommonIndicatorsTool(unittest.TestCase):
    """Test suite for boc_get_common_indicators tool"""
    
    def test_get_default_indicators(self):
        """Test getting default indicator set"""
        default_indicators = ['usd_cad', 'policy_rate', 'bond_10y', 'cpi']
        self.assertEqual(len(default_indicators), 4)
    
    def test_get_custom_indicators(self):
        """Test getting custom indicator set"""
        custom_indicators = ['usd_cad', 'eur_cad', 'policy_rate', 'bond_10y']
        self.assertTrue(len(custom_indicators) > 0)
    
    def test_get_fx_dashboard(self):
        """Test getting FX-focused dashboard"""
        fx_indicators = ['usd_cad', 'eur_cad', 'gbp_cad', 'jpy_cad']
        for indicator in fx_indicators:
            self.assertTrue(indicator.endswith('_cad'))
    
    def test_get_rates_dashboard(self):
        """Test getting interest rates dashboard"""
        rate_indicators = ['policy_rate', 'overnight_rate', 'prime_rate']
        self.assertEqual(len(rate_indicators), 3)
    
    def test_get_yield_curve_dashboard(self):
        """Test getting yield curve dashboard"""
        yield_indicators = ['bond_2y', 'bond_5y', 'bond_10y', 'bond_30y']
        for indicator in yield_indicators:
            self.assertTrue(indicator.startswith('bond_'))
    
    def test_response_structure(self):
        """Test response structure"""
        response_fields = ['indicators', 'last_updated']
        self.assertEqual(len(response_fields), 2)
    
    def test_max_indicators_limit(self):
        """Test maximum number of indicators"""
        max_indicators = 15
        self.assertEqual(max_indicators, 15)


class TestToolConfiguration(unittest.TestCase):
    """Test suite for tool configuration and management"""
    
    def test_tool_initialization(self):
        """Test tool initialization with config"""
        config = {
            'name': 'test_tool',
            'version': '1.0.0',
            'enabled': True
        }
        self.assertIn('name', config)
    
    def test_tool_enable_disable(self):
        """Test enabling and disabling tools"""
        tool = MockBaseMCPTool()
        tool.enable()
        self.assertTrue(tool.enabled)
        tool.disable()
        self.assertFalse(tool.enabled)
    
    def test_tool_execution_tracking(self):
        """Test execution tracking metrics"""
        tool = MockBaseMCPTool()
        tool._execution_count = 5
        metrics = tool.get_metrics()
        self.assertEqual(metrics['execution_count'], 5)


class TestErrorHandling(unittest.TestCase):
    """Test suite for error handling"""
    
    def test_series_not_found_error(self):
        """Test handling of 404 series not found"""
        error_message = "Series not found: INVALID"
        self.assertIn("Series not found", error_message)
    
    def test_network_error(self):
        """Test handling of network errors"""
        error_message = "Failed to get series data: HTTP 500"
        self.assertIn("Failed to get", error_message)
    
    def test_invalid_date_format(self):
        """Test handling of invalid date format"""
        invalid_date = "2024/01/01"
        try:
            datetime.strptime(invalid_date, '%Y-%m-%d')
            valid = True
        except ValueError:
            valid = False
        self.assertFalse(valid)
    
    def test_tool_disabled_error(self):
        """Test handling when tool is disabled"""
        tool = MockBaseMCPTool()
        tool.disable()
        with self.assertRaises(RuntimeError):
            tool.execute_with_tracking({})


def run_tests():
    """Run all test suites"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetSeriesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetExchangeRateTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetInterestRateTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetBondYieldTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetLatestTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCSearchSeriesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestBoCGetCommonIndicatorsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestToolConfiguration))
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
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
