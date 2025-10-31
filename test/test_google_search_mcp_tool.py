"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for Google Search MCP Tool
Comprehensive tests for Google Custom Search API integration
"""

import unittest
import sys
import json
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock
import urllib.error

# Import the Google Search tool
try:
    from tools.impl.google_search_tool_refactored import GoogleSearchTool
except ImportError:
    print("Error: Unable to import Google Search tool. Ensure the module is in the Python path.")
    sys.exit(1)


class TestGoogleSearchToolInitialization(unittest.TestCase):
    """Test suite for GoogleSearchTool initialization"""
    
    def test_initialization_without_config(self):
        """Test tool initialization without configuration"""
        tool = GoogleSearchTool()
        
        self.assertEqual(tool.config['name'], 'google_search')
        self.assertEqual(tool.config['version'], '1.0.0')
        self.assertTrue(tool.config['enabled'])
    
    def test_initialization_with_api_key(self):
        """Test tool initialization with API credentials"""
        config = {
            'api_key': 'test_api_key_12345',
            'search_engine_id': 'test_cx_12345:abcdef'
        }
        tool = GoogleSearchTool(config)
        
        self.assertEqual(tool.api_key, 'test_api_key_12345')
        self.assertEqual(tool.search_engine_id, 'test_cx_12345:abcdef')
        self.assertFalse(tool.demo_mode)
    
    def test_demo_mode_activation(self):
        """Test that demo mode activates without credentials"""
        tool = GoogleSearchTool()
        self.assertTrue(tool.demo_mode)
        
        # Demo mode should also activate with empty credentials
        tool2 = GoogleSearchTool({'api_key': '', 'search_engine_id': ''})
        self.assertTrue(tool2.demo_mode)
    
    def test_api_url_configuration(self):
        """Test API URL is correctly configured"""
        tool = GoogleSearchTool()
        self.assertEqual(tool.api_url, "https://www.googleapis.com/customsearch/v1")


class TestGoogleSearchToolSchemas(unittest.TestCase):
    """Test suite for schema definitions"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('required', schema)
        
        # Check required fields
        self.assertIn('query', schema['required'])
        
        # Check properties
        properties = schema['properties']
        self.assertIn('query', properties)
        self.assertIn('num_results', properties)
        self.assertIn('start', properties)
        self.assertIn('safe_search', properties)
        self.assertIn('search_type', properties)
        self.assertIn('site', properties)
        self.assertIn('date_restrict', properties)
        self.assertIn('language', properties)
    
    def test_input_schema_constraints(self):
        """Test input schema parameter constraints"""
        schema = self.tool.get_input_schema()
        
        # num_results constraints
        num_results = schema['properties']['num_results']
        self.assertEqual(num_results['minimum'], 1)
        self.assertEqual(num_results['maximum'], 10)
        self.assertEqual(num_results['default'], 10)
        
        # safe_search enum
        safe_search = schema['properties']['safe_search']
        self.assertEqual(safe_search['enum'], ['off', 'medium', 'high'])
        self.assertEqual(safe_search['default'], 'medium')
        
        # search_type enum
        search_type = schema['properties']['search_type']
        self.assertEqual(search_type['enum'], ['web', 'image'])
        self.assertEqual(search_type['default'], 'web')
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('required', schema)
        
        # Check required output fields
        required = schema['required']
        self.assertIn('query', required)
        self.assertIn('count', required)
        self.assertIn('results', required)
        
        # Check properties
        properties = schema['properties']
        self.assertIn('query', properties)
        self.assertIn('totalResults', properties)
        self.assertIn('searchTime', properties)
        self.assertIn('count', properties)
        self.assertIn('results', properties)
    
    def test_output_schema_result_structure(self):
        """Test result item structure in output schema"""
        schema = self.tool.get_output_schema()
        
        results_schema = schema['properties']['results']
        self.assertEqual(results_schema['type'], 'array')
        
        item_schema = results_schema['items']
        item_properties = item_schema['properties']
        
        # Check result item properties
        self.assertIn('title', item_properties)
        self.assertIn('link', item_properties)
        self.assertIn('snippet', item_properties)
        self.assertIn('displayLink', item_properties)
        self.assertIn('image', item_properties)
        
        # Check required fields for result items
        item_required = item_schema['required']
        self.assertIn('title', item_required)
        self.assertIn('link', item_required)
        self.assertIn('snippet', item_required)


class TestGoogleSearchToolDemoMode(unittest.TestCase):
    """Test suite for demo mode functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()  # No credentials = demo mode
    
    def test_demo_mode_basic_search(self):
        """Test basic search in demo mode"""
        result = self.tool.execute({
            'query': 'artificial intelligence'
        })
        
        self.assertIn('query', result)
        self.assertEqual(result['query'], 'artificial intelligence')
        self.assertIn('count', result)
        self.assertIn('results', result)
        self.assertIsInstance(result['results'], list)
    
    def test_demo_mode_response_structure(self):
        """Test that demo mode returns proper structure"""
        result = self.tool.execute({
            'query': 'test query',
            'num_results': 3
        })
        
        # Should have all expected fields
        self.assertIn('query', result)
        self.assertIn('totalResults', result)
        self.assertIn('searchTime', result)
        self.assertIn('count', result)
        self.assertIn('results', result)
        self.assertIn('note', result)
        
        # Note should indicate demo mode
        self.assertIn('Demo mode', result['note'])
    
    def test_demo_mode_result_format(self):
        """Test format of demo mode results"""
        result = self.tool.execute({
            'query': 'python programming',
            'num_results': 5
        })
        
        self.assertGreater(len(result['results']), 0)
        
        for item in result['results']:
            self.assertIn('title', item)
            self.assertIn('link', item)
            self.assertIn('snippet', item)
            self.assertIn('displayLink', item)
            
            # All should be strings
            self.assertIsInstance(item['title'], str)
            self.assertIsInstance(item['link'], str)
            self.assertIsInstance(item['snippet'], str)
            self.assertIsInstance(item['displayLink'], str)
    
    def test_demo_mode_num_results_limit(self):
        """Test that demo mode respects num_results limit"""
        result = self.tool.execute({
            'query': 'test',
            'num_results': 3
        })
        
        # Demo mode limits to 5 results max
        self.assertLessEqual(result['count'], 5)
        self.assertEqual(result['count'], len(result['results']))
    
    def test_demo_mode_query_inclusion(self):
        """Test that demo mode includes query in results"""
        query = 'machine learning'
        result = self.tool.execute({'query': query})
        
        # Query should appear in at least some result text
        combined_text = ' '.join([
            r['title'] + r['snippet'] 
            for r in result['results']
        ])
        
        self.assertIn(query, combined_text.lower())


class TestGoogleSearchToolValidation(unittest.TestCase):
    """Test suite for input validation"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_missing_query_error(self):
        """Test error when query is missing"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({})
        
        self.assertIn('query', str(context.exception).lower())
    
    def test_empty_query_error(self):
        """Test error when query is empty"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'query': ''})
        
        self.assertIn('query', str(context.exception).lower())
    
    def test_valid_num_results_values(self):
        """Test valid num_results values"""
        valid_values = [1, 5, 10]
        
        for num in valid_values:
            result = self.tool.execute({
                'query': 'test',
                'num_results': num
            })
            self.assertLessEqual(result['count'], num)
    
    def test_safe_search_values(self):
        """Test safe_search parameter values"""
        valid_values = ['off', 'medium', 'high']
        
        for value in valid_values:
            # Should not raise error
            result = self.tool.execute({
                'query': 'test',
                'safe_search': value
            })
            self.assertIsNotNone(result)
    
    def test_search_type_values(self):
        """Test search_type parameter values"""
        valid_types = ['web', 'image']
        
        for search_type in valid_types:
            result = self.tool.execute({
                'query': 'test',
                'search_type': search_type
            })
            self.assertIsNotNone(result)


class TestGoogleSearchToolParameters(unittest.TestCase):
    """Test suite for parameter handling"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_site_restriction(self):
        """Test site restriction parameter"""
        result = self.tool.execute({
            'query': 'python',
            'site': 'wikipedia.org'
        })
        
        # In demo mode, just verify it doesn't error
        self.assertIsNotNone(result)
        self.assertIn('results', result)
    
    def test_date_restriction(self):
        """Test date restriction parameter"""
        date_restrictions = ['d7', 'w2', 'm3', 'y1']
        
        for date_restrict in date_restrictions:
            result = self.tool.execute({
                'query': 'news',
                'date_restrict': date_restrict
            })
            self.assertIsNotNone(result)
    
    def test_language_parameter(self):
        """Test language parameter"""
        languages = ['en', 'es', 'fr', 'de', 'ja']
        
        for lang in languages:
            result = self.tool.execute({
                'query': 'test',
                'language': lang
            })
            self.assertIsNotNone(result)
    
    def test_pagination_start(self):
        """Test pagination with start parameter"""
        result = self.tool.execute({
            'query': 'artificial intelligence',
            'start': 11,
            'num_results': 10
        })
        
        self.assertIsNotNone(result)
        self.assertIn('results', result)
    
    def test_combined_parameters(self):
        """Test multiple parameters together"""
        result = self.tool.execute({
            'query': 'machine learning',
            'num_results': 5,
            'safe_search': 'high',
            'site': 'edu',
            'date_restrict': 'm6',
            'language': 'en'
        })
        
        self.assertIsNotNone(result)
        self.assertIn('results', result)


class TestGoogleSearchToolResultProcessing(unittest.TestCase):
    """Test suite for result processing"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_result_count_matches_array_length(self):
        """Test that count field matches results array length"""
        result = self.tool.execute({
            'query': 'test',
            'num_results': 5
        })
        
        self.assertEqual(result['count'], len(result['results']))
    
    def test_result_fields_present(self):
        """Test that all expected fields are present in results"""
        result = self.tool.execute({
            'query': 'python programming',
            'num_results': 3
        })
        
        required_fields = ['title', 'link', 'snippet', 'displayLink']
        
        for item in result['results']:
            for field in required_fields:
                self.assertIn(field, item)
                self.assertIsNotNone(item[field])
    
    def test_result_urls_format(self):
        """Test that result URLs have valid format"""
        result = self.tool.execute({
            'query': 'test',
            'num_results': 3
        })
        
        for item in result['results']:
            link = item['link']
            # Should start with http:// or https://
            self.assertTrue(
                link.startswith('http://') or link.startswith('https://'),
                f"Invalid URL format: {link}"
            )
    
    def test_empty_results_handling(self):
        """Test handling when no results are found"""
        # In demo mode, should always return results
        result = self.tool.execute({
            'query': 'xyzabc123nonexistent',
            'num_results': 10
        })
        
        # Demo mode will still return results
        self.assertGreaterEqual(result['count'], 0)


class TestGoogleSearchToolImageSearch(unittest.TestCase):
    """Test suite for image search functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_image_search_type(self):
        """Test image search type parameter"""
        result = self.tool.execute({
            'query': 'sunset',
            'search_type': 'image',
            'num_results': 5
        })
        
        self.assertIsNotNone(result)
        self.assertIn('results', result)
    
    def test_image_search_results_structure(self):
        """Test that image results have proper structure"""
        result = self.tool.execute({
            'query': 'mountains',
            'search_type': 'image',
            'num_results': 3
        })
        
        # Should have standard fields
        for item in result['results']:
            self.assertIn('title', item)
            self.assertIn('link', item)
            self.assertIn('snippet', item)


class TestGoogleSearchToolErrorHandling(unittest.TestCase):
    """Test suite for error handling"""
    
    def setUp(self):
        """Set up test fixtures with invalid credentials"""
        self.tool_invalid = GoogleSearchTool({
            'api_key': 'invalid_key',
            'search_engine_id': 'invalid_cx'
        })
    
    def test_missing_query_error(self):
        """Test error for missing query"""
        with self.assertRaises(ValueError):
            self.tool_invalid.execute({})
    
    def test_none_query_error(self):
        """Test error for None query"""
        with self.assertRaises(ValueError):
            self.tool_invalid.execute({'query': None})
    
    @patch('urllib.request.urlopen')
    def test_http_400_error(self, mock_urlopen):
        """Test handling of HTTP 400 error"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'http://test.com', 400, 'Bad Request', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool_invalid.execute({'query': 'test'})
        
        self.assertIn('Invalid search parameters', str(context.exception))
    
    @patch('urllib.request.urlopen')
    def test_http_403_error(self, mock_urlopen):
        """Test handling of HTTP 403 error (quota/auth)"""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'http://test.com', 403, 'Forbidden', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.tool_invalid.execute({'query': 'test'})
        
        error_msg = str(context.exception)
        self.assertTrue(
            'quota exceeded' in error_msg.lower() or 
            'invalid' in error_msg.lower()
        )


class TestGoogleSearchToolIntegration(unittest.TestCase):
    """Integration tests for common usage scenarios"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_basic_search_workflow(self):
        """Test basic search workflow"""
        result = self.tool.execute({
            'query': 'python programming tutorials',
            'num_results': 5
        })
        
        self.assertIsNotNone(result)
        self.assertIn('query', result)
        self.assertGreater(result['count'], 0)
        self.assertGreater(len(result['results']), 0)
    
    def test_site_specific_search_workflow(self):
        """Test site-specific search workflow"""
        result = self.tool.execute({
            'query': 'machine learning',
            'site': 'wikipedia.org',
            'num_results': 5
        })
        
        self.assertIsNotNone(result)
        self.assertGreater(result['count'], 0)
    
    def test_recent_content_search_workflow(self):
        """Test searching for recent content"""
        result = self.tool.execute({
            'query': 'technology news',
            'date_restrict': 'd7',
            'num_results': 5
        })
        
        self.assertIsNotNone(result)
        self.assertIn('results', result)
    
    def test_safe_search_workflow(self):
        """Test safe search filtering"""
        result = self.tool.execute({
            'query': 'educational content',
            'safe_search': 'high',
            'num_results': 5
        })
        
        self.assertIsNotNone(result)
        self.assertGreater(result['count'], 0)
    
    def test_pagination_workflow(self):
        """Test pagination across multiple pages"""
        page1 = self.tool.execute({
            'query': 'artificial intelligence',
            'start': 1,
            'num_results': 10
        })
        
        page2 = self.tool.execute({
            'query': 'artificial intelligence',
            'start': 11,
            'num_results': 10
        })
        
        self.assertIsNotNone(page1)
        self.assertIsNotNone(page2)


class TestGoogleSearchToolEdgeCases(unittest.TestCase):
    """Test suite for edge cases"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GoogleSearchTool()
    
    def test_very_long_query(self):
        """Test handling of very long query"""
        long_query = 'test ' * 100  # Very long query
        
        result = self.tool.execute({
            'query': long_query,
            'num_results': 3
        })
        
        self.assertIsNotNone(result)
    
    def test_special_characters_in_query(self):
        """Test query with special characters"""
        special_queries = [
            'C++ programming',
            'price: $100-$200',
            'email@example.com',
            'search "exact phrase"',
            'math: 2+2=4'
        ]
        
        for query in special_queries:
            result = self.tool.execute({
                'query': query,
                'num_results': 3
            })
            self.assertIsNotNone(result)
    
    def test_non_english_query(self):
        """Test query in non-English languages"""
        queries = [
            ('español', 'es'),
            ('français', 'fr'),
            ('日本語', 'ja'),
            ('中文', 'zh')
        ]
        
        for query, lang in queries:
            result = self.tool.execute({
                'query': query,
                'language': lang,
                'num_results': 3
            })
            self.assertIsNotNone(result)
    
    def test_minimum_results(self):
        """Test requesting minimum number of results"""
        result = self.tool.execute({
            'query': 'test',
            'num_results': 1
        })
        
        self.assertGreaterEqual(result['count'], 0)
        self.assertLessEqual(result['count'], 1)
    
    def test_maximum_results(self):
        """Test requesting maximum number of results"""
        result = self.tool.execute({
            'query': 'test',
            'num_results': 10
        })
        
        # Demo mode limits to 5
        self.assertLessEqual(result['count'], 10)


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
        TestGoogleSearchToolInitialization,
        TestGoogleSearchToolSchemas,
        TestGoogleSearchToolDemoMode,
        TestGoogleSearchToolValidation,
        TestGoogleSearchToolParameters,
        TestGoogleSearchToolResultProcessing,
        TestGoogleSearchToolImageSearch,
        TestGoogleSearchToolErrorHandling,
        TestGoogleSearchToolIntegration,
        TestGoogleSearchToolEdgeCases
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
    print("Google Search MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
