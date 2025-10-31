"""
Copyright © 2025-2030 Ashutosh Sinha
Email: ajsinha@gmail.com
All Rights Reserved

Wikipedia MCP Tool - Comprehensive Test Suite
Tests for wiki_search, wiki_get_page, and wiki_get_summary tools
"""

import unittest
import json
import time
from typing import Dict, Any
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from wikipedia_tool import (
        WikiSearchTool,
        WikiGetPageTool,
        WikiGetSummaryTool,
        WikipediaBaseTool,
        WIKIPEDIA_TOOLS
    )
except ImportError:
    print("Warning: Could not import wikipedia_tool. Ensure the module is in the correct path.")


class TestWikipediaBaseTool(unittest.TestCase):
    """Test suite for WikipediaBaseTool base class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.base_tool = WikipediaBaseTool()
    
    def test_initialization(self):
        """Test base tool initialization"""
        self.assertEqual(self.base_tool.default_lang, 'en')
        self.assertIn('{lang}', self.base_tool.api_base)
        self.assertIn('wikipedia.org', self.base_tool.api_base)
    
    def test_api_base_format(self):
        """Test API base URL formatting"""
        url = self.base_tool.api_base.format(lang='en')
        self.assertEqual(url, 'https://en.wikipedia.org/w/api.php')
        
        url = self.base_tool.api_base.format(lang='es')
        self.assertEqual(url, 'https://es.wikipedia.org/w/api.php')
    
    @patch('urllib.request.urlopen')
    def test_make_request_success(self, mock_urlopen):
        """Test successful API request"""
        # Mock response
        mock_response = Mock()
        mock_response.read.return_value = b'{"query": {"search": []}}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        params = {'action': 'query', 'list': 'search'}
        result = self.base_tool._make_request(params, 'en')
        
        self.assertIsInstance(result, dict)
        self.assertIn('query', result)
    
    @patch('urllib.request.urlopen')
    def test_make_request_404_error(self, mock_urlopen):
        """Test 404 error handling"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url='', code=404, msg='Not Found', hdrs=None, fp=None
        )
        
        params = {'action': 'query'}
        with self.assertRaises(ValueError) as context:
            self.base_tool._make_request(params, 'en')
        
        self.assertIn('not found', str(context.exception).lower())
    
    @patch('urllib.request.urlopen')
    def test_make_request_timeout(self, mock_urlopen):
        """Test timeout handling"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError('timeout')
        
        params = {'action': 'query'}
        with self.assertRaises(ValueError) as context:
            self.base_tool._make_request(params, 'en')
        
        self.assertIn('failed', str(context.exception).lower())


class TestWikiSearchTool(unittest.TestCase):
    """Test suite for WikiSearchTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.search_tool = WikiSearchTool()
    
    def test_initialization(self):
        """Test search tool initialization"""
        self.assertEqual(self.search_tool.config['name'], 'wiki_search')
        self.assertTrue(self.search_tool.config['enabled'])
        self.assertEqual(self.search_tool.config['version'], '1.0.0')
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.search_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('limit', schema['properties'])
        self.assertIn('language', schema['properties'])
        self.assertIn('query', schema['required'])
        
        # Test query constraints
        query_schema = schema['properties']['query']
        self.assertEqual(query_schema['type'], 'string')
        self.assertEqual(query_schema['minLength'], 1)
        self.assertEqual(query_schema['maxLength'], 300)
        
        # Test limit constraints
        limit_schema = schema['properties']['limit']
        self.assertEqual(limit_schema['type'], 'integer')
        self.assertEqual(limit_schema['minimum'], 1)
        self.assertEqual(limit_schema['maximum'], 20)
        self.assertEqual(limit_schema['default'], 5)
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.search_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('results', schema['properties'])
        self.assertIn('result_count', schema['properties'])
        self.assertIn('query', schema['required'])
        self.assertIn('results', schema['required'])
        
        # Test results array structure
        results_schema = schema['properties']['results']
        self.assertEqual(results_schema['type'], 'array')
        self.assertIn('items', results_schema)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_basic_search(self, mock_request):
        """Test basic search execution"""
        # Mock API response
        mock_request.return_value = {
            'query': {
                'search': [
                    {
                        'pageid': 1234,
                        'title': 'Test Article',
                        'snippet': 'Test snippet',
                        'timestamp': '2025-10-31T10:00:00Z',
                        'wordcount': 1000
                    }
                ]
            }
        }
        
        result = self.search_tool.execute({
            'query': 'test query'
        })
        
        self.assertEqual(result['query'], 'test query')
        self.assertEqual(result['result_count'], 1)
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['title'], 'Test Article')
        self.assertEqual(result['results'][0]['page_id'], 1234)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_limit(self, mock_request):
        """Test search with custom limit"""
        mock_request.return_value = {
            'query': {
                'search': [
                    {'pageid': i, 'title': f'Article {i}', 'snippet': 'test'}
                    for i in range(10)
                ]
            }
        }
        
        result = self.search_tool.execute({
            'query': 'test',
            'limit': 10
        })
        
        self.assertEqual(result['result_count'], 10)
        self.assertEqual(len(result['results']), 10)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_language(self, mock_request):
        """Test search with different language"""
        mock_request.return_value = {
            'query': {
                'search': [
                    {
                        'pageid': 5678,
                        'title': 'Artículo de prueba',
                        'snippet': 'Texto de prueba'
                    }
                ]
            }
        }
        
        result = self.search_tool.execute({
            'query': 'prueba',
            'language': 'es'
        })
        
        self.assertEqual(result['language'], 'es')
        mock_request.assert_called_once()
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_suggestion(self, mock_request):
        """Test search with spelling suggestion"""
        mock_request.return_value = {
            'query': {
                'search': [],
                'searchinfo': {
                    'suggestion': 'corrected query'
                }
            }
        }
        
        result = self.search_tool.execute({
            'query': 'misspeled query'
        })
        
        self.assertEqual(result['suggestion'], 'corrected query')
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_snippet_cleaning(self, mock_request):
        """Test that search match HTML tags are removed from snippets"""
        mock_request.return_value = {
            'query': {
                'search': [
                    {
                        'pageid': 1234,
                        'title': 'Test',
                        'snippet': 'This is <span class="searchmatch">highlighted</span> text'
                    }
                ]
            }
        }
        
        result = self.search_tool.execute({'query': 'test'})
        
        snippet = result['results'][0]['snippet']
        self.assertNotIn('<span', snippet)
        self.assertNotIn('</span>', snippet)
        self.assertIn('highlighted', snippet)


class TestWikiGetPageTool(unittest.TestCase):
    """Test suite for WikiGetPageTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.page_tool = WikiGetPageTool()
    
    def test_initialization(self):
        """Test page tool initialization"""
        self.assertEqual(self.page_tool.config['name'], 'wiki_get_page')
        self.assertTrue(self.page_tool.config['enabled'])
        self.assertEqual(self.page_tool.config['version'], '1.0.0')
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.page_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('page_id', schema['properties'])
        self.assertIn('language', schema['properties'])
        self.assertIn('redirect', schema['properties'])
        self.assertIn('include_images', schema['properties'])
        self.assertIn('include_links', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.page_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('title', schema['properties'])
        self.assertIn('content', schema['properties'])
        self.assertIn('sections', schema['properties'])
        self.assertIn('images', schema['properties'])
        self.assertIn('links', schema['properties'])
        self.assertIn('categories', schema['properties'])
        
        # Test required fields
        self.assertIn('title', schema['required'])
        self.assertIn('page_id', schema['required'])
        self.assertIn('url', schema['required'])
        self.assertIn('content', schema['required'])
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_by_title(self, mock_request):
        """Test page retrieval by title"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '12345': {
                        'pageid': 12345,
                        'title': 'Test Page',
                        'extract': 'Test content\n\n== Section 1 ==\nSection content',
                        'fullurl': 'https://en.wikipedia.org/wiki/Test_Page',
                        'images': [],
                        'links': [],
                        'categories': [],
                        'revisions': [{
                            'timestamp': '2025-10-31T10:00:00Z',
                            'user': 'TestUser',
                            'revid': 123456
                        }]
                    }
                }
            }
        }
        
        result = self.page_tool.execute({
            'query': 'Test Page'
        })
        
        self.assertEqual(result['title'], 'Test Page')
        self.assertEqual(result['page_id'], 12345)
        self.assertIn('Test content', result['content'])
        self.assertIsInstance(result['sections'], list)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_by_page_id(self, mock_request):
        """Test page retrieval by page ID"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '99999': {
                        'pageid': 99999,
                        'title': 'Page by ID',
                        'extract': 'Content',
                        'fullurl': 'https://en.wikipedia.org/wiki/Page_by_ID'
                    }
                }
            }
        }
        
        result = self.page_tool.execute({
            'page_id': 99999
        })
        
        self.assertEqual(result['page_id'], 99999)
        self.assertEqual(result['title'], 'Page by ID')
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_images(self, mock_request):
        """Test page retrieval with images"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '12345': {
                        'pageid': 12345,
                        'title': 'Test',
                        'extract': 'Content',
                        'images': [
                            {'title': 'File:Test1.jpg'},
                            {'title': 'File:Test2.png'}
                        ]
                    }
                }
            }
        }
        
        result = self.page_tool.execute({
            'query': 'Test',
            'include_images': True
        })
        
        self.assertIsInstance(result['images'], list)
        self.assertGreater(len(result['images']), 0)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_links(self, mock_request):
        """Test page retrieval with links"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '12345': {
                        'pageid': 12345,
                        'title': 'Test',
                        'extract': 'Content',
                        'links': [
                            {'title': 'Internal Link 1'},
                            {'title': 'Internal Link 2'}
                        ]
                    }
                }
            }
        }
        
        result = self.page_tool.execute({
            'query': 'Test',
            'include_links': True
        })
        
        self.assertIn('links', result)
        self.assertIn('internal', result['links'])
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_page_not_found(self, mock_request):
        """Test handling of non-existent page"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '-1': {
                        'title': 'NonExistent',
                        'missing': ''
                    }
                }
            }
        }
        
        with self.assertRaises(ValueError) as context:
            self.page_tool.execute({'query': 'NonExistent'})
        
        self.assertIn('not found', str(context.exception).lower())
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_section_parsing(self, mock_request):
        """Test that sections are properly parsed"""
        content_with_sections = """Introduction text

== First Section ==
First section content

== Second Section ==
Second section content

=== Subsection ===
Subsection content"""
        
        mock_request.return_value = {
            'query': {
                'pages': {
                    '12345': {
                        'pageid': 12345,
                        'title': 'Test',
                        'extract': content_with_sections
                    }
                }
            }
        }
        
        result = self.page_tool.execute({'query': 'Test'})
        
        self.assertIsInstance(result['sections'], list)
        self.assertGreater(len(result['sections']), 0)


class TestWikiGetSummaryTool(unittest.TestCase):
    """Test suite for WikiGetSummaryTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.summary_tool = WikiGetSummaryTool()
    
    def test_initialization(self):
        """Test summary tool initialization"""
        self.assertEqual(self.summary_tool.config['name'], 'wiki_get_summary')
        self.assertTrue(self.summary_tool.config['enabled'])
        self.assertEqual(self.summary_tool.config['version'], '1.0.0')
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.summary_tool.get_input_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('query', schema['properties'])
        self.assertIn('page_id', schema['properties'])
        self.assertIn('sentences', schema['properties'])
        self.assertIn('include_image', schema['properties'])
        
        # Test sentences constraints
        sentences_schema = schema['properties']['sentences']
        self.assertEqual(sentences_schema['type'], 'integer')
        self.assertEqual(sentences_schema['minimum'], 1)
        self.assertEqual(sentences_schema['maximum'], 10)
        self.assertEqual(sentences_schema['default'], 3)
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.summary_tool.get_output_schema()
        
        self.assertEqual(schema['type'], 'object')
        self.assertIn('summary', schema['properties'])
        self.assertIn('extract', schema['properties'])
        self.assertIn('thumbnail', schema['properties'])
        self.assertIn('coordinates', schema['properties'])
        
        # Test required fields
        self.assertIn('title', schema['required'])
        self.assertIn('page_id', schema['required'])
        self.assertIn('url', schema['required'])
        self.assertIn('summary', schema['required'])
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_basic_summary(self, mock_request):
        """Test basic summary retrieval"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '54321': {
                        'pageid': 54321,
                        'title': 'Summary Test',
                        'extract': 'This is a test summary. It has multiple sentences. Three to be exact.',
                        'fullurl': 'https://en.wikipedia.org/wiki/Summary_Test',
                        'description': 'Test description'
                    }
                }
            }
        }
        
        result = self.summary_tool.execute({
            'query': 'Summary Test',
            'sentences': 3
        })
        
        self.assertEqual(result['title'], 'Summary Test')
        self.assertEqual(result['page_id'], 54321)
        self.assertIn('test summary', result['summary'].lower())
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_thumbnail(self, mock_request):
        """Test summary with thumbnail image"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '54321': {
                        'pageid': 54321,
                        'title': 'Test',
                        'extract': 'Summary',
                        'thumbnail': {
                            'source': 'https://upload.wikimedia.org/test.jpg',
                            'width': 500,
                            'height': 375
                        },
                        'original': {
                            'source': 'https://upload.wikimedia.org/test_full.jpg',
                            'width': 1920,
                            'height': 1080
                        }
                    }
                }
            }
        }
        
        result = self.summary_tool.execute({
            'query': 'Test',
            'include_image': True
        })
        
        self.assertIsNotNone(result['thumbnail'])
        self.assertIn('url', result['thumbnail'])
        self.assertIn('width', result['thumbnail'])
        self.assertIn('height', result['thumbnail'])
        
        self.assertIsNotNone(result['original_image'])
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_with_coordinates(self, mock_request):
        """Test summary with geographic coordinates"""
        mock_request.return_value = {
            'query': {
                'pages': {
                    '54321': {
                        'pageid': 54321,
                        'title': 'Location',
                        'extract': 'A place',
                        'coordinates': [
                            {
                                'lat': 40.7128,
                                'lon': -74.0060
                            }
                        ]
                    }
                }
            }
        }
        
        result = self.summary_tool.execute({'query': 'Location'})
        
        self.assertIsNotNone(result['coordinates'])
        self.assertIn('latitude', result['coordinates'])
        self.assertIn('longitude', result['coordinates'])
        self.assertEqual(result['coordinates']['latitude'], 40.7128)
        self.assertEqual(result['coordinates']['longitude'], -74.0060)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_different_sentence_counts(self, mock_request):
        """Test summaries with different sentence counts"""
        for sentence_count in [1, 3, 5, 10]:
            mock_request.return_value = {
                'query': {
                    'pages': {
                        '12345': {
                            'pageid': 12345,
                            'title': 'Test',
                            'extract': 'Summary text'
                        }
                    }
                }
            }
            
            result = self.summary_tool.execute({
                'query': 'Test',
                'sentences': sentence_count
            })
            
            self.assertIsNotNone(result['summary'])
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_execute_missing_parameters(self, mock_request):
        """Test that missing required parameters raise error"""
        with self.assertRaises(ValueError):
            self.summary_tool.execute({})  # No query or page_id


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry"""
    
    def test_registry_contains_all_tools(self):
        """Test that registry contains all tool classes"""
        self.assertIn('wiki_search', WIKIPEDIA_TOOLS)
        self.assertIn('wiki_get_page', WIKIPEDIA_TOOLS)
        self.assertIn('wiki_get_summary', WIKIPEDIA_TOOLS)
    
    def test_registry_tool_instantiation(self):
        """Test that tools can be instantiated from registry"""
        for tool_name, tool_class in WIKIPEDIA_TOOLS.items():
            tool_instance = tool_class()
            self.assertIsNotNone(tool_instance)
            self.assertTrue(hasattr(tool_instance, 'execute'))
            self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
            self.assertTrue(hasattr(tool_instance, 'get_output_schema'))


class TestIntegration(unittest.TestCase):
    """Integration tests (require network connection)"""
    
    def setUp(self):
        """Set up for integration tests"""
        self.run_integration_tests = False  # Set to True to run actual API calls
        
        if not self.run_integration_tests:
            self.skipTest("Integration tests disabled. Set run_integration_tests=True to enable.")
    
    def test_real_search(self):
        """Test real Wikipedia search"""
        if not self.run_integration_tests:
            return
        
        search_tool = WikiSearchTool()
        result = search_tool.execute({
            'query': 'Python programming',
            'limit': 3
        })
        
        self.assertGreater(result['result_count'], 0)
        self.assertGreater(len(result['results']), 0)
        self.assertIn('Python', result['results'][0]['title'])
        
        # Rate limiting
        time.sleep(1)
    
    def test_real_page_retrieval(self):
        """Test real page retrieval"""
        if not self.run_integration_tests:
            return
        
        page_tool = WikiGetPageTool()
        result = page_tool.execute({
            'query': 'Python (programming language)'
        })
        
        self.assertEqual(result['title'], 'Python (programming language)')
        self.assertGreater(len(result['content']), 0)
        self.assertGreater(result['word_count'], 0)
        
        # Rate limiting
        time.sleep(1)
    
    def test_real_summary(self):
        """Test real summary retrieval"""
        if not self.run_integration_tests:
            return
        
        summary_tool = WikiGetSummaryTool()
        result = summary_tool.execute({
            'query': 'Artificial intelligence',
            'sentences': 2
        })
        
        self.assertEqual(result['title'], 'Artificial intelligence')
        self.assertGreater(len(result['summary']), 0)
        
        # Rate limiting
        time.sleep(1)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions"""
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_empty_search_results(self, mock_request):
        """Test handling of empty search results"""
        mock_request.return_value = {
            'query': {
                'search': []
            }
        }
        
        search_tool = WikiSearchTool()
        result = search_tool.execute({'query': 'zxcvbnmasdfghjk'})
        
        self.assertEqual(result['result_count'], 0)
        self.assertEqual(len(result['results']), 0)
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_unicode_handling(self, mock_request):
        """Test Unicode character handling"""
        mock_request.return_value = {
            'query': {
                'search': [{
                    'pageid': 1,
                    'title': '日本語テスト',
                    'snippet': 'Unicode 测试 Тест'
                }]
            }
        }
        
        search_tool = WikiSearchTool()
        result = search_tool.execute({'query': '日本語'})
        
        self.assertEqual(result['results'][0]['title'], '日本語テスト')
    
    @patch.object(WikipediaBaseTool, '_make_request')
    def test_special_characters_in_url(self, mock_request):
        """Test URL encoding for special characters"""
        mock_request.return_value = {
            'query': {
                'search': [{
                    'pageid': 1,
                    'title': 'Test & Special / Characters',
                    'snippet': 'test'
                }]
            }
        }
        
        search_tool = WikiSearchTool()
        result = search_tool.execute({'query': 'test'})
        
        url = result['results'][0]['url']
        self.assertIn('%', url)  # URL should be encoded


def run_test_suite():
    """Run the complete test suite with reporting"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestWikipediaBaseTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWikiSearchTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWikiGetPageTool))
    suite.addTests(loader.loadTestsFromTestCase(TestWikiGetSummaryTool))
    suite.addTests(loader.loadTestsFromTestCase(TestToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    
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
    ║         Wikipedia MCP Tool - Comprehensive Test Suite        ║
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
