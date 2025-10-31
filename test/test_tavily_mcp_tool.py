"""
Copyright All rights reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Comprehensive Test Suite for Tavily Search MCP Tools
Tests all four tools with various scenarios including demo mode, API mode, and error cases
"""

import unittest
import json
from typing import Dict, Any
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
    from tavily_tool_refactored import (
        TavilyWebSearchTool,
        TavilyNewsSearchTool,
        TavilyResearchSearchTool,
        TavilyDomainSearchTool,
        TAVILY_TOOLS
    )
except ImportError:
    print("Warning: Could not import tools. Using mock implementations for testing structure.")


class TestTavilyToolsBase(unittest.TestCase):
    """Base test class with common setup and utilities"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        # Demo config (no API key)
        cls.demo_config = {}
        
        # API config (with mock key)
        cls.api_config = {
            'api_key': 'tvly-test-key-12345'
        }
    
    def _validate_common_response(self, response: Dict[str, Any], query: str):
        """Validate common response fields"""
        self.assertIn('query', response)
        self.assertEqual(response['query'], query)
        self.assertIn('results_count', response)
        self.assertIn('results', response)
        self.assertIsInstance(response['results'], list)
        self.assertEqual(len(response['results']), response['results_count'])
    
    def _validate_result_structure(self, result: Dict[str, Any]):
        """Validate individual result structure"""
        self.assertIn('title', result)
        self.assertIn('url', result)
        self.assertIn('content', result)
        self.assertIn('score', result)
        
        # Validate types
        self.assertIsInstance(result['title'], str)
        self.assertIsInstance(result['url'], str)
        self.assertIsInstance(result['content'], str)
        self.assertIsInstance(result['score'], (int, float))
        
        # Validate score range
        self.assertGreaterEqual(result['score'], 0.0)
        self.assertLessEqual(result['score'], 1.0)
    
    def _create_mock_api_response(self, query: str, num_results: int = 5) -> Dict:
        """Create a mock API response"""
        results = []
        for i in range(num_results):
            results.append({
                'title': f'Result {i+1} for {query}',
                'url': f'https://example.com/result{i+1}',
                'content': f'This is content for result {i+1} about {query}',
                'score': 0.9 - (i * 0.1),
                'published_date': '2024-10-31'
            })
        
        return {
            'results': results,
            'answer': f'This is an AI-generated answer about {query}'
        }


class TestTavilyWebSearchTool(TestTavilyToolsBase):
    """Test cases for tavily_web_search tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.demo_tool = TavilyWebSearchTool(self.demo_config)
        self.api_tool = TavilyWebSearchTool(self.api_config)
    
    def test_demo_mode_basic_search(self):
        """Test basic search in demo mode"""
        result = self.demo_tool.execute({
            'query': 'artificial intelligence'
        })
        
        self._validate_common_response(result, 'artificial intelligence')
        self.assertIn('note', result)  # Demo mode includes note
        self.assertIn('Demo mode', result['note'])
    
    def test_demo_mode_with_answer(self):
        """Test demo mode includes AI answer"""
        result = self.demo_tool.execute({
            'query': 'machine learning',
            'include_answer': True
        })
        
        self.assertIn('answer', result)
        self.assertIsInstance(result['answer'], str)
        self.assertGreater(len(result['answer']), 0)
    
    def test_demo_mode_with_images(self):
        """Test demo mode includes images"""
        result = self.demo_tool.execute({
            'query': 'quantum computing',
            'include_images': True
        })
        
        self.assertIn('images', result)
        self.assertIsInstance(result['images'], list)
        if len(result['images']) > 0:
            img = result['images'][0]
            self.assertIn('url', img)
            self.assertIn('description', img)
    
    def test_search_depth_basic(self):
        """Test basic search depth"""
        result = self.demo_tool.execute({
            'query': 'python programming',
            'search_depth': 'basic'
        })
        
        self.assertEqual(result['search_depth'], 'basic')
    
    def test_search_depth_advanced(self):
        """Test advanced search depth"""
        result = self.demo_tool.execute({
            'query': 'deep learning',
            'search_depth': 'advanced'
        })
        
        self.assertEqual(result['search_depth'], 'advanced')
    
    def test_max_results_parameter(self):
        """Test max_results parameter"""
        for max_results in [1, 3, 5, 10]:
            result = self.demo_tool.execute({
                'query': 'test query',
                'max_results': max_results
            })
            self.assertLessEqual(result['results_count'], max_results)
    
    def test_result_structure(self):
        """Test structure of returned results"""
        result = self.demo_tool.execute({
            'query': 'data science'
        })
        
        for item in result['results']:
            self._validate_result_structure(item)
    
    def test_missing_query_parameter(self):
        """Test error when query parameter is missing"""
        with self.assertRaises(ValueError) as context:
            self.demo_tool.execute({})
        
        self.assertIn('required', str(context.exception).lower())
    
    def test_empty_query_string(self):
        """Test error with empty query string"""
        with self.assertRaises(ValueError):
            self.demo_tool.execute({'query': ''})
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.demo_tool.get_input_schema()
        
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('query', schema['properties'])
        self.assertIn('required', schema)
        self.assertIn('query', schema['required'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.demo_tool.get_output_schema()
        
        self.assertIn('type', schema)
        self.assertEqual(schema['type'], 'object')
        self.assertIn('properties', schema)
        self.assertIn('results', schema['properties'])
    
    @patch('urllib.request.urlopen')
    def test_api_mode_success(self, mock_urlopen):
        """Test successful API call"""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            self._create_mock_api_response('test query')
        ).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = self.api_tool.execute({
            'query': 'test query'
        })
        
        self._validate_common_response(result, 'test query')
        self.assertNotIn('note', result)  # No demo note in API mode
    
    @patch('urllib.request.urlopen')
    def test_api_mode_401_error(self, mock_urlopen):
        """Test 401 authentication error"""
        import urllib.error
        
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'url', 401, 'Unauthorized', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.api_tool.execute({'query': 'test'})
        
        self.assertIn('Invalid API key', str(context.exception))
    
    @patch('urllib.request.urlopen')
    def test_api_mode_429_rate_limit(self, mock_urlopen):
        """Test 429 rate limit error"""
        import urllib.error
        
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'url', 429, 'Too Many Requests', {}, None
        )
        
        with self.assertRaises(ValueError) as context:
            self.api_tool.execute({'query': 'test'})
        
        self.assertIn('Rate limit', str(context.exception))


class TestTavilyNewsSearchTool(TestTavilyToolsBase):
    """Test cases for tavily_news_search tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.demo_tool = TavilyNewsSearchTool(self.demo_config)
        self.api_tool = TavilyNewsSearchTool(self.api_config)
    
    def test_news_search_basic(self):
        """Test basic news search"""
        result = self.demo_tool.execute({
            'query': 'technology news'
        })
        
        self._validate_common_response(result, 'technology news')
        self.assertEqual(result['topic'], 'news')
    
    def test_news_with_published_dates(self):
        """Test that news results include published dates"""
        result = self.demo_tool.execute({
            'query': 'breaking news'
        })
        
        for item in result['results']:
            self.assertIn('published_date', item)
    
    def test_news_max_results(self):
        """Test max_results parameter for news"""
        result = self.demo_tool.execute({
            'query': 'market news',
            'max_results': 10
        })
        
        self.assertLessEqual(result['results_count'], 10)
    
    def test_news_with_answer(self):
        """Test news search with AI summary"""
        result = self.demo_tool.execute({
            'query': 'climate news',
            'include_answer': True
        })
        
        self.assertIn('answer', result)
        self.assertIsInstance(result['answer'], str)
    
    def test_news_without_answer(self):
        """Test news search without AI summary"""
        result = self.demo_tool.execute({
            'query': 'sports news',
            'include_answer': False
        })
        
        # Answer might still be included by demo mode
        # Just ensure results are present
        self.assertGreater(result['results_count'], 0)
    
    def test_news_input_schema(self):
        """Test news tool input schema"""
        schema = self.demo_tool.get_input_schema()
        
        self.assertIn('query', schema['properties'])
        self.assertIn('max_results', schema['properties'])
        self.assertIn('include_answer', schema['properties'])
    
    def test_news_result_structure(self):
        """Test structure of news results"""
        result = self.demo_tool.execute({
            'query': 'financial news'
        })
        
        for item in result['results']:
            self._validate_result_structure(item)
            self.assertIn('published_date', item)


class TestTavilyResearchSearchTool(TestTavilyToolsBase):
    """Test cases for tavily_research_search tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.demo_tool = TavilyResearchSearchTool(self.demo_config)
        self.api_tool = TavilyResearchSearchTool(self.api_config)
    
    def test_research_always_advanced_depth(self):
        """Test that research always uses advanced depth"""
        result = self.demo_tool.execute({
            'query': 'quantum physics'
        })
        
        self.assertEqual(result['search_depth'], 'advanced')
    
    def test_research_topic_general(self):
        """Test research with general topic"""
        result = self.demo_tool.execute({
            'query': 'research topic',
            'topic': 'general'
        })
        
        self.assertEqual(result['topic'], 'general')
    
    def test_research_topic_science(self):
        """Test research with science topic"""
        result = self.demo_tool.execute({
            'query': 'scientific research',
            'topic': 'science'
        })
        
        self.assertEqual(result['topic'], 'science')
    
    def test_research_topic_finance(self):
        """Test research with finance topic"""
        result = self.demo_tool.execute({
            'query': 'market analysis',
            'topic': 'finance'
        })
        
        self.assertEqual(result['topic'], 'finance')
    
    def test_research_higher_default_results(self):
        """Test that research has higher default result count"""
        result = self.demo_tool.execute({
            'query': 'academic research'
        })
        
        # Research defaults to 10 results
        self.assertGreaterEqual(result['results_count'], 5)
    
    def test_research_max_results_range(self):
        """Test research max_results range (5-20)"""
        for max_results in [5, 10, 15, 20]:
            result = self.demo_tool.execute({
                'query': 'test research',
                'max_results': max_results
            })
            self.assertLessEqual(result['results_count'], max_results)
    
    def test_research_always_includes_answer(self):
        """Test that research always includes AI answer"""
        result = self.demo_tool.execute({
            'query': 'comprehensive research'
        })
        
        self.assertIn('answer', result)
        self.assertIsInstance(result['answer'], str)
        self.assertGreater(len(result['answer']), 0)
    
    def test_research_with_raw_content(self):
        """Test research with raw content option"""
        result = self.demo_tool.execute({
            'query': 'detailed research',
            'include_raw_content': True
        })
        
        # In demo mode, raw_content might not be included
        # Just verify the parameter is accepted
        self._validate_common_response(result, 'detailed research')
    
    def test_research_without_raw_content(self):
        """Test research without raw content"""
        result = self.demo_tool.execute({
            'query': 'research topic',
            'include_raw_content': False
        })
        
        self._validate_common_response(result, 'research topic')
    
    def test_research_input_schema(self):
        """Test research tool input schema"""
        schema = self.demo_tool.get_input_schema()
        
        self.assertIn('query', schema['properties'])
        self.assertIn('topic', schema['properties'])
        self.assertIn('max_results', schema['properties'])
        self.assertIn('include_raw_content', schema['properties'])
        
        # Check topic enum
        self.assertIn('enum', schema['properties']['topic'])
        self.assertIn('general', schema['properties']['topic']['enum'])
        self.assertIn('science', schema['properties']['topic']['enum'])
        self.assertIn('finance', schema['properties']['topic']['enum'])


class TestTavilyDomainSearchTool(TestTavilyToolsBase):
    """Test cases for tavily_domain_search tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.demo_tool = TavilyDomainSearchTool(self.demo_config)
        self.api_tool = TavilyDomainSearchTool(self.api_config)
    
    def test_domain_search_with_include(self):
        """Test domain search with include_domains"""
        result = self.demo_tool.execute({
            'query': 'python documentation',
            'include_domains': ['python.org', 'github.com']
        })
        
        self._validate_common_response(result, 'python documentation')
        self.assertIn('included_domains', result)
        self.assertEqual(result['included_domains'], ['python.org', 'github.com'])
    
    def test_domain_search_with_exclude(self):
        """Test domain search with exclude_domains"""
        result = self.demo_tool.execute({
            'query': 'programming tutorial',
            'exclude_domains': ['pinterest.com', 'facebook.com']
        })
        
        self._validate_common_response(result, 'programming tutorial')
        self.assertIn('excluded_domains', result)
        self.assertEqual(result['excluded_domains'], ['pinterest.com', 'facebook.com'])
    
    def test_domain_search_missing_filters(self):
        """Test error when neither include nor exclude domains specified"""
        with self.assertRaises(ValueError) as context:
            self.demo_tool.execute({
                'query': 'test query'
            })
        
        self.assertIn('include_domains', str(context.exception).lower() or 
                     'exclude_domains', str(context.exception).lower())
    
    def test_domain_search_single_domain(self):
        """Test search with single included domain"""
        result = self.demo_tool.execute({
            'query': 'react documentation',
            'include_domains': ['react.dev']
        })
        
        self.assertEqual(result['included_domains'], ['react.dev'])
    
    def test_domain_search_multiple_domains(self):
        """Test search with multiple domains"""
        domains = ['github.com', 'stackoverflow.com', 'python.org']
        result = self.demo_tool.execute({
            'query': 'coding examples',
            'include_domains': domains
        })
        
        self.assertEqual(result['included_domains'], domains)
    
    def test_domain_search_with_answer(self):
        """Test domain search includes AI answer"""
        result = self.demo_tool.execute({
            'query': 'documentation search',
            'include_domains': ['docs.example.com'],
            'include_answer': True
        })
        
        self.assertIn('answer', result)
    
    def test_domain_search_max_results(self):
        """Test max_results parameter"""
        result = self.demo_tool.execute({
            'query': 'test query',
            'include_domains': ['example.com'],
            'max_results': 10
        })
        
        self.assertLessEqual(result['results_count'], 10)
    
    def test_domain_search_input_schema(self):
        """Test domain search input schema"""
        schema = self.demo_tool.get_input_schema()
        
        self.assertIn('include_domains', schema['properties'])
        self.assertIn('exclude_domains', schema['properties'])
        self.assertIn('oneOf', schema)  # Must have one of the filters
    
    def test_domain_search_exclude_only(self):
        """Test domain search with only exclude_domains"""
        result = self.demo_tool.execute({
            'query': 'general search',
            'exclude_domains': ['spam.com', 'ads.com']
        })
        
        self.assertNotIn('included_domains', result)
        self.assertIn('excluded_domains', result)


class TestTavilyToolRegistry(TestTavilyToolsBase):
    """Test cases for tool registry and integration"""
    
    def test_registry_exists(self):
        """Test that tool registry exists"""
        self.assertIsNotNone(TAVILY_TOOLS)
        self.assertIsInstance(TAVILY_TOOLS, dict)
    
    def test_all_tools_registered(self):
        """Test that all tools are registered"""
        expected_tools = [
            'tavily_web_search',
            'tavily_news_search',
            'tavily_research_search',
            'tavily_domain_search'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, TAVILY_TOOLS)
    
    def test_tool_instantiation_from_registry(self):
        """Test creating tools from registry"""
        for tool_name, tool_class in TAVILY_TOOLS.items():
            tool = tool_class(self.demo_config)
            self.assertIsNotNone(tool)
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have input and output schemas"""
        for tool_name, tool_class in TAVILY_TOOLS.items():
            tool = tool_class(self.demo_config)
            
            input_schema = tool.get_input_schema()
            output_schema = tool.get_output_schema()
            
            self.assertIsInstance(input_schema, dict)
            self.assertIsInstance(output_schema, dict)
            self.assertIn('type', input_schema)
            self.assertIn('type', output_schema)
    
    def test_all_tools_have_execute(self):
        """Test that all tools have execute method"""
        for tool_name, tool_class in TAVILY_TOOLS.items():
            tool = tool_class(self.demo_config)
            self.assertTrue(hasattr(tool, 'execute'))
            self.assertTrue(callable(tool.execute))


class TestDemoModeVsApiMode(TestTavilyToolsBase):
    """Test differences between demo and API modes"""
    
    def test_demo_mode_detection(self):
        """Test that demo mode is correctly detected"""
        demo_tool = TavilyWebSearchTool({})
        api_tool = TavilyWebSearchTool({'api_key': 'tvly-test'})
        
        self.assertTrue(demo_tool.demo_mode)
        self.assertFalse(api_tool.demo_mode)
    
    def test_demo_mode_includes_note(self):
        """Test that demo mode includes informational note"""
        tool = TavilyWebSearchTool({})
        result = tool.execute({'query': 'test'})
        
        self.assertIn('note', result)
        self.assertIn('Demo mode', result['note'])
    
    def test_api_mode_requires_key(self):
        """Test that API mode requires valid key"""
        tool = TavilyWebSearchTool({'api_key': ''})
        # Empty string should trigger demo mode
        self.assertTrue(tool.demo_mode)
    
    def test_demo_results_consistent(self):
        """Test that demo results are consistent"""
        tool = TavilyWebSearchTool({})
        
        result1 = tool.execute({'query': 'test'})
        result2 = tool.execute({'query': 'test'})
        
        # Should get same number of results
        self.assertEqual(result1['results_count'], result2['results_count'])


class TestInputValidation(TestTavilyToolsBase):
    """Test input parameter validation"""
    
    def test_query_required_all_tools(self):
        """Test that query parameter is required for all tools"""
        tools = [
            TavilyWebSearchTool({}),
            TavilyNewsSearchTool({}),
            TavilyResearchSearchTool({}),
        ]
        
        for tool in tools:
            with self.assertRaises(ValueError):
                tool.execute({})
    
    def test_invalid_search_depth(self):
        """Test handling of invalid search depth"""
        tool = TavilyWebSearchTool({})
        
        # Demo mode should handle this gracefully
        # In production, Tavily API would validate
        result = tool.execute({
            'query': 'test',
            'search_depth': 'invalid'
        })
        
        # Should still return results in demo mode
        self.assertGreater(result['results_count'], 0)
    
    def test_invalid_topic(self):
        """Test handling of invalid topic"""
        tool = TavilyResearchSearchTool({})
        
        # Demo mode should handle gracefully
        result = tool.execute({
            'query': 'test',
            'topic': 'invalid'
        })
        
        # Should still work in demo mode
        self.assertGreater(result['results_count'], 0)
    
    def test_max_results_bounds(self):
        """Test max_results parameter bounds"""
        tool = TavilyWebSearchTool({})
        
        # Very high number should be capped
        result = tool.execute({
            'query': 'test',
            'max_results': 1000
        })
        
        # Demo mode caps at 5
        self.assertLessEqual(result['results_count'], 5)


class TestResponseValidation(TestTavilyToolsBase):
    """Test response structure validation"""
    
    def test_response_has_required_fields(self):
        """Test that responses have all required fields"""
        tool = TavilyWebSearchTool({})
        result = tool.execute({'query': 'test'})
        
        required_fields = ['query', 'results_count', 'results']
        for field in required_fields:
            self.assertIn(field, result)
    
    def test_results_array_valid(self):
        """Test that results array is valid"""
        tool = TavilyWebSearchTool({})
        result = tool.execute({'query': 'test'})
        
        self.assertIsInstance(result['results'], list)
        for item in result['results']:
            self.assertIsInstance(item, dict)
    
    def test_score_validation(self):
        """Test that scores are in valid range"""
        tool = TavilyWebSearchTool({})
        result = tool.execute({'query': 'test'})
        
        for item in result['results']:
            score = item['score']
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)
    
    def test_url_format(self):
        """Test that URLs are properly formatted"""
        tool = TavilyWebSearchTool({})
        result = tool.execute({'query': 'test'})
        
        for item in result['results']:
            url = item['url']
            self.assertTrue(url.startswith('http://') or url.startswith('https://'))


class TestIntegrationScenarios(TestTavilyToolsBase):
    """Integration test scenarios combining multiple features"""
    
    def test_web_to_research_workflow(self):
        """Test workflow: web search -> research deep dive"""
        # Quick web search
        web_tool = TavilyWebSearchTool({})
        web_result = web_tool.execute({
            'query': 'quantum computing',
            'search_depth': 'basic',
            'max_results': 3
        })
        
        self.assertLessEqual(web_result['results_count'], 3)
        
        # Deep research
        research_tool = TavilyResearchSearchTool({})
        research_result = research_tool.execute({
            'query': 'quantum computing',
            'topic': 'science',
            'max_results': 10
        })
        
        self.assertGreaterEqual(research_result['results_count'], 
                               web_result['results_count'])
    
    def test_news_with_domain_filter(self):
        """Test combining news search with domain filtering"""
        # First, get general news
        news_tool = TavilyNewsSearchTool({})
        news_result = news_tool.execute({
            'query': 'technology news',
            'max_results': 5
        })
        
        # Then, get news from specific domains
        domain_tool = TavilyDomainSearchTool({})
        filtered_result = domain_tool.execute({
            'query': 'technology news',
            'include_domains': ['techcrunch.com', 'theverge.com'],
            'max_results': 5
        })
        
        # Both should return results
        self.assertGreater(news_result['results_count'], 0)
        self.assertGreater(filtered_result['results_count'], 0)
    
    def test_progressive_search_depth(self):
        """Test progressive search from basic to advanced"""
        tool = TavilyWebSearchTool({})
        
        # Basic search
        basic_result = tool.execute({
            'query': 'machine learning',
            'search_depth': 'basic',
            'max_results': 5
        })
        
        # Advanced search
        advanced_result = tool.execute({
            'query': 'machine learning',
            'search_depth': 'advanced',
            'max_results': 10
        })
        
        # Both should succeed
        self.assertEqual(basic_result['search_depth'], 'basic')
        self.assertEqual(advanced_result['search_depth'], 'advanced')


class TestErrorScenarios(TestTavilyToolsBase):
    """Test various error scenarios"""
    
    def test_network_error_handling(self):
        """Test handling of network errors"""
        tool = TavilyWebSearchTool({'api_key': 'tvly-test'})
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = Exception("Network error")
            
            with self.assertRaises(ValueError) as context:
                tool.execute({'query': 'test'})
            
            self.assertIn('failed', str(context.exception).lower())
    
    def test_malformed_response_handling(self):
        """Test handling of malformed API responses"""
        tool = TavilyWebSearchTool({'api_key': 'tvly-test'})
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'invalid json'
            mock_urlopen.return_value.__enter__.return_value = mock_response
            
            with self.assertRaises(ValueError):
                tool.execute({'query': 'test'})
    
    def test_timeout_handling(self):
        """Test handling of request timeouts"""
        import socket
        tool = TavilyWebSearchTool({'api_key': 'tvly-test'})
        
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = socket.timeout("Request timeout")
            
            with self.assertRaises(ValueError):
                tool.execute({'query': 'test'})


class TestPerformanceConsiderations(TestTavilyToolsBase):
    """Test performance-related scenarios"""
    
    def test_large_result_count(self):
        """Test handling of large result counts"""
        tool = TavilyWebSearchTool({})
        
        # Demo mode should cap results
        result = tool.execute({
            'query': 'test',
            'max_results': 20
        })
        
        # Demo mode typically returns 5 or fewer
        self.assertLessEqual(result['results_count'], 5)
    
    def test_multiple_concurrent_searches(self):
        """Test multiple searches in sequence"""
        tool = TavilyWebSearchTool({})
        
        queries = ['query1', 'query2', 'query3']
        results = []
        
        for query in queries:
            result = tool.execute({'query': query})
            results.append(result)
        
        # All should succeed
        self.assertEqual(len(results), 3)
        for result in results:
            self.assertGreater(result['results_count'], 0)


def run_test_suite():
    """Run the complete test suite"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestTavilyWebSearchTool))
    suite.addTests(loader.loadTestsFromTestCase(TestTavilyNewsSearchTool))
    suite.addTests(loader.loadTestsFromTestCase(TestTavilyResearchSearchTool))
    suite.addTests(loader.loadTestsFromTestCase(TestTavilyDomainSearchTool))
    suite.addTests(loader.loadTestsFromTestCase(TestTavilyToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestDemoModeVsApiMode))
    suite.addTests(loader.loadTestsFromTestCase(TestInputValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestResponseValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceConsiderations))
    
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
    ║  Tavily Search MCP Tools - Comprehensive Test Suite             ║
    ║  Copyright All rights reserved 2025-2030, Ashutosh Sinha        ║
    ║  Email: ajsinha@gmail.com                                        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    result = run_test_suite()
    
    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
