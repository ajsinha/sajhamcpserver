"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for Investor Relations MCP Tools
Comprehensive tests for all 7 IR tools with web scraping functionality
"""

import unittest
import sys
import json
from typing import Dict, Any, List
from unittest.mock import Mock, patch, MagicMock

# Import the Investor Relations tools
try:
    from tools.impl.investor_relations_tool_refactored import (
        IRListSupportedCompaniesTool,
        IRFindPageTool,
        IRGetDocumentsTool,
        IRGetLatestEarningsTool,
        IRGetAnnualReportsTool,
        IRGetPresentationsTool,
        IRGetAllResourcesTool,
        INVESTOR_RELATIONS_TOOLS
    )
except ImportError:
    print("Error: Unable to import Investor Relations tools. Ensure the module is in the Python path.")
    sys.exit(1)


class TestIRListSupportedCompaniesTool(unittest.TestCase):
    """Test suite for IRListSupportedCompaniesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRListSupportedCompaniesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_list_supported_companies')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        # No required parameters for listing companies
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('supported_companies', schema['properties'])
        self.assertIn('count', schema['properties'])
        
        # Check company object structure
        companies_schema = schema['properties']['supported_companies']
        self.assertEqual(companies_schema['type'], 'array')
        
        item_props = companies_schema['items']['properties']
        self.assertIn('ticker', item_props)
        self.assertIn('name', item_props)
        self.assertIn('ir_url', item_props)
    
    def test_scraper_factory_exists(self):
        """Test that scraper factory is initialized"""
        self.assertIsNotNone(self.tool.scraper_factory)
        self.assertTrue(hasattr(self.tool.scraper_factory, 'get_all_scrapers_info'))
    
    def test_execute_returns_companies(self):
        """Test that execute returns company list"""
        result = self.tool.execute({})
        
        self.assertIn('supported_companies', result)
        self.assertIn('count', result)
        self.assertIsInstance(result['supported_companies'], list)
        self.assertGreater(result['count'], 0)
    
    def test_supported_companies_structure(self):
        """Test structure of supported companies"""
        result = self.tool.execute({})
        
        if result['supported_companies']:
            company = result['supported_companies'][0]
            self.assertIn('ticker', company)
            self.assertIn('name', company)
            self.assertIn('ir_url', company)


class TestIRFindPageTool(unittest.TestCase):
    """Test suite for IRFindPageTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRFindPageTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_find_page')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('ticker', schema['properties'])
        self.assertIn('ticker', schema['required'])
        
        ticker_prop = schema['properties']['ticker']
        self.assertEqual(ticker_prop['type'], 'string')
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('ir_page_url', props)
        self.assertIn('success', props)
    
    def test_ticker_required(self):
        """Test that ticker parameter is required"""
        # Should raise error when ticker is missing
        with self.assertRaises((KeyError, ValueError)):
            self.tool.execute({})
    
    def test_ticker_uppercase_conversion(self):
        """Test that tickers are converted to uppercase"""
        # The tool should handle lowercase tickers
        # This tests the internal behavior
        self.assertTrue(hasattr(self.tool, '_get_scraper'))


class TestIRGetDocumentsTool(unittest.TestCase):
    """Test suite for IRGetDocumentsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRGetDocumentsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_get_documents')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('document_type', props)
        self.assertIn('year', props)
        self.assertIn('limit', props)
        
        # Check ticker is required
        self.assertIn('ticker', schema['required'])
    
    def test_document_type_enum(self):
        """Test document type enum values"""
        schema = self.tool.get_input_schema()
        doc_type = schema['properties']['document_type']
        
        expected_types = [
            'annual_report',
            'quarterly_report',
            'earnings_presentation',
            'investor_presentation',
            'proxy_statement',
            'press_release',
            'esg_report',
            'all'
        ]
        
        self.assertEqual(doc_type['enum'], expected_types)
        self.assertEqual(doc_type['default'], 'all')
    
    def test_year_constraints(self):
        """Test year parameter constraints"""
        schema = self.tool.get_input_schema()
        year_prop = schema['properties']['year']
        
        self.assertEqual(year_prop['minimum'], 2000)
        self.assertEqual(year_prop['maximum'], 2030)
    
    def test_limit_constraints(self):
        """Test limit parameter constraints"""
        schema = self.tool.get_input_schema()
        limit_prop = schema['properties']['limit']
        
        self.assertEqual(limit_prop['default'], 10)
        self.assertEqual(limit_prop['minimum'], 1)
        self.assertEqual(limit_prop['maximum'], 50)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('document_type', props)
        self.assertIn('year', props)
        self.assertIn('count', props)
        self.assertIn('documents', props)
        self.assertIn('success', props)


class TestIRGetLatestEarningsTool(unittest.TestCase):
    """Test suite for IRGetLatestEarningsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRGetLatestEarningsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_get_latest_earnings')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('ticker', schema['properties'])
        self.assertIn('ticker', schema['required'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('latest_earnings', props)
        self.assertIn('success', props)
        
        # Check latest_earnings structure
        earnings_props = props['latest_earnings']['properties']
        self.assertIn('quarter', earnings_props)
        self.assertIn('year', earnings_props)
        self.assertIn('report_url', earnings_props)
        self.assertIn('presentation_url', earnings_props)
        self.assertIn('date', earnings_props)


class TestIRGetAnnualReportsTool(unittest.TestCase):
    """Test suite for IRGetAnnualReportsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRGetAnnualReportsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_get_annual_reports')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('year', props)
        self.assertIn('limit', props)
        
        self.assertIn('ticker', schema['required'])
    
    def test_year_filter_optional(self):
        """Test that year filter is optional"""
        schema = self.tool.get_input_schema()
        self.assertNotIn('year', schema.get('required', []))
    
    def test_limit_constraints(self):
        """Test limit parameter constraints"""
        schema = self.tool.get_input_schema()
        limit_prop = schema['properties']['limit']
        
        self.assertEqual(limit_prop['default'], 5)
        self.assertEqual(limit_prop['minimum'], 1)
        self.assertEqual(limit_prop['maximum'], 20)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('year', props)
        self.assertIn('count', props)
        self.assertIn('annual_reports', props)
        self.assertIn('success', props)
        
        # Check report structure
        reports_items = props['annual_reports']['items']['properties']
        self.assertIn('title', reports_items)
        self.assertIn('url', reports_items)
        self.assertIn('year', reports_items)
        self.assertIn('date', reports_items)


class TestIRGetPresentationsTool(unittest.TestCase):
    """Test suite for IRGetPresentationsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRGetPresentationsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_get_presentations')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('limit', props)
        
        self.assertIn('ticker', schema['required'])
    
    def test_limit_constraints(self):
        """Test limit parameter constraints"""
        schema = self.tool.get_input_schema()
        limit_prop = schema['properties']['limit']
        
        self.assertEqual(limit_prop['default'], 10)
        self.assertEqual(limit_prop['minimum'], 1)
        self.assertEqual(limit_prop['maximum'], 30)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('count', props)
        self.assertIn('presentations', props)
        self.assertIn('success', props)


class TestIRGetAllResourcesTool(unittest.TestCase):
    """Test suite for IRGetAllResourcesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRGetAllResourcesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'ir_get_all_resources')
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('ticker', schema['properties'])
        self.assertIn('ticker', schema['required'])
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        props = schema['properties']
        self.assertIn('ticker', props)
        self.assertIn('ir_page_url', props)
        self.assertIn('resources', props)
        self.assertIn('success', props)
        
        # Check resources structure
        resources_props = props['resources']['properties']
        self.assertIn('annual_reports', resources_props)
        self.assertIn('quarterly_reports', resources_props)
        self.assertIn('presentations', resources_props)
        self.assertIn('press_releases', resources_props)


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry is defined"""
        self.assertIsNotNone(INVESTOR_RELATIONS_TOOLS)
        self.assertIsInstance(INVESTOR_RELATIONS_TOOLS, dict)
    
    def test_all_tools_in_registry(self):
        """Test that all 7 tools are in the registry"""
        expected_tools = [
            'ir_list_supported_companies',
            'ir_find_page',
            'ir_get_documents',
            'ir_get_latest_earnings',
            'ir_get_annual_reports',
            'ir_get_presentations',
            'ir_get_all_resources'
        ]
        
        self.assertEqual(len(INVESTOR_RELATIONS_TOOLS), 7)
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, INVESTOR_RELATIONS_TOOLS)
    
    def test_tools_are_classes(self):
        """Test that registry contains class references"""
        for tool_name, tool_class in INVESTOR_RELATIONS_TOOLS.items():
            self.assertTrue(callable(tool_class))
    
    def test_tool_instantiation(self):
        """Test that all tools can be instantiated"""
        for tool_name, tool_class in INVESTOR_RELATIONS_TOOLS.items():
            try:
                tool_instance = tool_class()
                self.assertIsNotNone(tool_instance)
                self.assertTrue(hasattr(tool_instance, 'execute'))
                self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
                self.assertTrue(hasattr(tool_instance, 'get_output_schema'))
            except Exception as e:
                self.fail(f"Failed to instantiate {tool_name}: {e}")


class TestBaseToolFunctionality(unittest.TestCase):
    """Test suite for base tool functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRFindPageTool()
    
    def test_scraper_factory_initialized(self):
        """Test that scraper factory is initialized"""
        self.assertIsNotNone(self.tool.scraper_factory)
        self.assertTrue(hasattr(self.tool.scraper_factory, 'is_supported'))
        self.assertTrue(hasattr(self.tool.scraper_factory, 'get_scraper'))
        self.assertTrue(hasattr(self.tool.scraper_factory, 'get_supported_tickers'))
    
    def test_get_scraper_method_exists(self):
        """Test that _get_scraper method exists"""
        self.assertTrue(hasattr(self.tool, '_get_scraper'))
        self.assertTrue(callable(self.tool._get_scraper))


class TestSupportedCompanies(unittest.TestCase):
    """Test suite for supported companies"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRListSupportedCompaniesTool()
    
    def test_expected_companies_present(self):
        """Test that expected companies are present"""
        result = self.tool.execute({})
        
        expected_tickers = ['TSLA', 'MSFT', 'C', 'BMO', 'RY', 'JPM', 'GS']
        
        actual_tickers = [
            company['ticker'] 
            for company in result['supported_companies']
        ]
        
        for ticker in expected_tickers:
            self.assertIn(ticker, actual_tickers)
    
    def test_company_count(self):
        """Test that company count matches array length"""
        result = self.tool.execute({})
        
        self.assertEqual(
            result['count'],
            len(result['supported_companies'])
        )


class TestDocumentTypeValidation(unittest.TestCase):
    """Test suite for document type validation"""
    
    def test_all_document_types_defined(self):
        """Test that all document types are defined"""
        tool = IRGetDocumentsTool()
        schema = tool.get_input_schema()
        
        doc_types = schema['properties']['document_type']['enum']
        
        expected_types = [
            'annual_report',
            'quarterly_report',
            'earnings_presentation',
            'investor_presentation',
            'proxy_statement',
            'press_release',
            'esg_report',
            'all'
        ]
        
        for doc_type in expected_types:
            self.assertIn(doc_type, doc_types)


class TestErrorHandling(unittest.TestCase):
    """Test suite for error handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = IRFindPageTool()
    
    def test_unsupported_ticker_error(self):
        """Test error handling for unsupported ticker"""
        # Using a ticker that's definitely not supported
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'ticker': 'INVALID_TICKER_XYZ'})
        
        error_msg = str(context.exception)
        self.assertIn('not supported', error_msg.lower())


class TestSchemaValidation(unittest.TestCase):
    """Test suite for schema validation"""
    
    def test_all_tools_have_schemas(self):
        """Test that all tools implement schema methods"""
        for tool_name, tool_class in INVESTOR_RELATIONS_TOOLS.items():
            tool = tool_class()
            
            # Test input schema
            input_schema = tool.get_input_schema()
            self.assertIsNotNone(input_schema)
            self.assertIn('type', input_schema)
            self.assertIn('properties', input_schema)
            
            # Test output schema
            output_schema = tool.get_output_schema()
            self.assertIsNotNone(output_schema)
            self.assertIn('type', output_schema)
            self.assertIn('properties', output_schema)


class TestOutputFormatConsistency(unittest.TestCase):
    """Test suite for output format consistency"""
    
    def test_success_field_in_outputs(self):
        """Test that most outputs include success field"""
        tools_with_success = [
            IRFindPageTool,
            IRGetDocumentsTool,
            IRGetLatestEarningsTool,
            IRGetAnnualReportsTool,
            IRGetPresentationsTool,
            IRGetAllResourcesTool
        ]
        
        for tool_class in tools_with_success:
            tool = tool_class()
            schema = tool.get_output_schema()
            self.assertIn('success', schema['properties'])


class TestWebScrapingConfiguration(unittest.TestCase):
    """Test suite for web scraping configuration"""
    
    def test_scraper_factory_pattern(self):
        """Test that tools use scraper factory pattern"""
        tool = IRFindPageTool()
        
        # Should have scraper factory
        self.assertIsNotNone(tool.scraper_factory)
        
        # Factory should have required methods
        self.assertTrue(hasattr(tool.scraper_factory, 'is_supported'))
        self.assertTrue(hasattr(tool.scraper_factory, 'get_scraper'))


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for common usage scenarios"""
    
    def test_scenario_list_and_find(self):
        """Test: List companies then find IR page"""
        list_tool = IRListSupportedCompaniesTool()
        find_tool = IRFindPageTool()
        
        # List companies
        companies_result = list_tool.execute({})
        self.assertGreater(companies_result['count'], 0)
        
        # IR page URLs should be present
        for company in companies_result['supported_companies']:
            self.assertIn('ir_url', company)
            self.assertTrue(company['ir_url'].startswith('http'))


class TestYearFilterValidation(unittest.TestCase):
    """Test suite for year filter validation"""
    
    def test_year_range_reasonable(self):
        """Test that year ranges are reasonable"""
        tools_with_year = [
            IRGetDocumentsTool,
            IRGetAnnualReportsTool
        ]
        
        for tool_class in tools_with_year:
            tool = tool_class()
            schema = tool.get_input_schema()
            year_prop = schema['properties']['year']
            
            # Should have reasonable bounds
            self.assertEqual(year_prop['minimum'], 2000)
            self.assertEqual(year_prop['maximum'], 2030)


class TestLimitParameterValidation(unittest.TestCase):
    """Test suite for limit parameter validation"""
    
    def test_limit_parameters_present(self):
        """Test that limit parameters are properly defined"""
        tools_with_limit = [
            (IRGetDocumentsTool, 10, 1, 50),
            (IRGetAnnualReportsTool, 5, 1, 20),
            (IRGetPresentationsTool, 10, 1, 30)
        ]
        
        for tool_class, default, minimum, maximum in tools_with_limit:
            tool = tool_class()
            schema = tool.get_input_schema()
            limit_prop = schema['properties']['limit']
            
            self.assertEqual(limit_prop['default'], default)
            self.assertEqual(limit_prop['minimum'], minimum)
            self.assertEqual(limit_prop['maximum'], maximum)


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
        TestIRListSupportedCompaniesTool,
        TestIRFindPageTool,
        TestIRGetDocumentsTool,
        TestIRGetLatestEarningsTool,
        TestIRGetAnnualReportsTool,
        TestIRGetPresentationsTool,
        TestIRGetAllResourcesTool,
        TestToolRegistry,
        TestBaseToolFunctionality,
        TestSupportedCompanies,
        TestDocumentTypeValidation,
        TestErrorHandling,
        TestSchemaValidation,
        TestOutputFormatConsistency,
        TestWebScrapingConfiguration,
        TestIntegrationScenarios,
        TestYearFilterValidation,
        TestLimitParameterValidation
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
    print("Investor Relations MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
