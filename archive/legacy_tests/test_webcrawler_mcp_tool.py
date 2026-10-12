"""
Copyright All rights reserved 2025-2030 Ashutosh Sinha, Email: ajsinha@gmail.com
Comprehensive Test Suite for Web Crawler MCP Tools
"""

import unittest
import sys
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import json

# Add parent directory to path for imports
sys.path.insert(0, '/mnt/user-data/uploads')

from webcrawler_tool_refactored import (
    CrawlURLTool,
    ExtractLinksTool,
    ExtractContentTool,
    ExtractMetadataTool,
    CrawlSitemapTool,
    CheckRobotsTxtTool,
    GetPageInfoTool,
    LinkExtractor,
    WebCrawlerBaseTool
)


class TestLinkExtractor(unittest.TestCase):
    """Test cases for LinkExtractor HTML parser"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.parser = LinkExtractor()
    
    def test_extract_links(self):
        """Test link extraction from HTML"""
        html = '''
        <html>
            <body>
                <a href="https://example.com">Link 1</a>
                <a href="/about">Link 2</a>
                <a href="#section">Anchor</a>
            </body>
        </html>
        '''
        self.parser.feed(html)
        self.assertEqual(len(self.parser.links), 3)
        self.assertIn("https://example.com", self.parser.links)
        self.assertIn("/about", self.parser.links)
    
    def test_extract_images(self):
        """Test image extraction from HTML"""
        html = '''
        <html>
            <body>
                <img src="image1.jpg" alt="Image 1" />
                <img src="https://example.com/image2.png" alt="Image 2" title="Title 2" />
            </body>
        </html>
        '''
        self.parser.feed(html)
        self.assertEqual(len(self.parser.images), 2)
        self.assertEqual(self.parser.images[0]['src'], "image1.jpg")
        self.assertEqual(self.parser.images[0]['alt'], "Image 1")
        self.assertEqual(self.parser.images[1]['title'], "Title 2")
    
    def test_extract_title(self):
        """Test title extraction"""
        html = '<html><head><title>Test Page Title</title></head></html>'
        self.parser.feed(html)
        self.assertEqual(self.parser.title, "Test Page Title")
    
    def test_extract_meta_description(self):
        """Test meta description extraction"""
        html = '''
        <html>
            <head>
                <meta name="description" content="This is a test description" />
                <meta name="keywords" content="test, keywords" />
            </head>
        </html>
        '''
        self.parser.feed(html)
        self.assertEqual(self.parser.meta_description, "This is a test description")
        self.assertEqual(self.parser.meta_keywords, "test, keywords")
    
    def test_extract_headings(self):
        """Test heading extraction"""
        html = '''
        <html>
            <body>
                <h1>Heading 1</h1>
                <h2>Heading 2A</h2>
                <h2>Heading 2B</h2>
                <h3>Heading 3</h3>
            </body>
        </html>
        '''
        self.parser.feed(html)
        self.assertEqual(len(self.parser.headings['h1']), 1)
        self.assertEqual(len(self.parser.headings['h2']), 2)
        self.assertEqual(len(self.parser.headings['h3']), 1)
        self.assertEqual(self.parser.headings['h1'][0], "Heading 1")


class TestWebCrawlerBaseTool(unittest.TestCase):
    """Test cases for WebCrawlerBaseTool shared functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a concrete implementation for testing
        class TestTool(WebCrawlerBaseTool):
            def execute(self, arguments):
                return {}
            def get_input_schema(self):
                return {}
            def get_output_schema(self):
                return {}
        
        self.tool = TestTool()
    
    def test_is_valid_url(self):
        """Test URL validation"""
        self.assertTrue(self.tool._is_valid_url("https://example.com"))
        self.assertTrue(self.tool._is_valid_url("http://example.com/path"))
        self.assertFalse(self.tool._is_valid_url("invalid"))
        self.assertFalse(self.tool._is_valid_url("example.com"))
        self.assertFalse(self.tool._is_valid_url(""))
    
    def test_normalize_url(self):
        """Test URL normalization"""
        base = "https://example.com/page"
        
        # Absolute URL
        result = self.tool._normalize_url("https://other.com/path", base)
        self.assertEqual(result, "https://other.com/path")
        
        # Relative URL
        result = self.tool._normalize_url("/about", base)
        self.assertEqual(result, "https://example.com/about")
        
        # Fragment removal
        result = self.tool._normalize_url("https://example.com/page#section", base)
        self.assertEqual(result, "https://example.com/page")
    
    def test_is_same_domain(self):
        """Test domain comparison"""
        self.assertTrue(
            self.tool._is_same_domain(
                "https://example.com/page1",
                "https://example.com/page2"
            )
        )
        self.assertFalse(
            self.tool._is_same_domain(
                "https://example.com",
                "https://other.com"
            )
        )
        self.assertTrue(
            self.tool._is_same_domain(
                "http://example.com",
                "https://example.com"
            )
        )


class TestCheckRobotsTxtTool(unittest.TestCase):
    """Test cases for CheckRobotsTxtTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = CheckRobotsTxtTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('user_agent', schema['properties'])
        self.assertIn('required', schema)
        self.assertIn('url', schema['required'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('can_fetch', schema['properties'])
        self.assertIn('crawl_delay', schema['properties'])
    
    def test_invalid_url(self):
        """Test handling of invalid URLs"""
        with self.assertRaises(ValueError):
            self.tool.execute({"url": "invalid-url"})
    
    @patch('urllib.robotparser.RobotFileParser')
    def test_can_fetch_allowed(self, mock_parser):
        """Test when robots.txt allows crawling"""
        mock_rp = Mock()
        mock_rp.can_fetch.return_value = True
        mock_rp.crawl_delay.return_value = 2.0
        mock_parser.return_value = mock_rp
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertTrue(result['can_fetch'])
        self.assertEqual(result['crawl_delay'], 2.0)
        self.assertIn('checked_at', result)
    
    @patch('urllib.robotparser.RobotFileParser')
    def test_can_fetch_disallowed(self, mock_parser):
        """Test when robots.txt disallows crawling"""
        mock_rp = Mock()
        mock_rp.can_fetch.return_value = False
        mock_rp.crawl_delay.return_value = None
        mock_parser.return_value = mock_rp
        
        result = self.tool.execute({"url": "https://example.com/admin"})
        
        self.assertFalse(result['can_fetch'])
    
    def test_robots_txt_not_found(self):
        """Test handling when robots.txt doesn't exist"""
        # This should not raise an error, should return can_fetch=True with note
        result = self.tool.execute({"url": "https://httpbin.org/robots.txt"})
        # Even if robots.txt doesn't exist, tool should handle gracefully
        self.assertIsInstance(result, dict)
        self.assertIn('can_fetch', result)


class TestCrawlSitemapTool(unittest.TestCase):
    """Test cases for CrawlSitemapTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = CrawlSitemapTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('required', schema)
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('sitemap_url', schema['properties'])
        self.assertIn('url_count', schema['properties'])
        self.assertIn('urls', schema['properties'])
    
    def test_invalid_url(self):
        """Test handling of invalid URLs"""
        with self.assertRaises(ValueError):
            self.tool.execute({"url": "not-a-url"})
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_parse_sitemap_xml(self, mock_fetch):
        """Test sitemap XML parsing"""
        sitemap_xml = '''<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
            <url><loc>https://example.com/page3</loc></url>
        </urlset>'''
        
        mock_fetch.return_value = (sitemap_xml, 'application/xml', 200)
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertEqual(result['url_count'], 3)
        self.assertIn('https://example.com/page1', result['urls'])
        self.assertIn('https://example.com/page2', result['urls'])
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_sitemap_not_found(self, mock_fetch):
        """Test handling when sitemap not found"""
        mock_fetch.side_effect = Exception("404 Not Found")
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertIn('error', result)


class TestCrawlURLTool(unittest.TestCase):
    """Test cases for CrawlURLTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = CrawlURLTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('max_depth', schema['properties'])
        self.assertIn('max_pages', schema['properties'])
        self.assertIn('delay', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('start_url', schema['properties'])
        self.assertIn('pages_crawled', schema['properties'])
        self.assertIn('pages', schema['properties'])
    
    def test_invalid_url(self):
        """Test handling of invalid URLs"""
        with self.assertRaises(ValueError):
            self.tool.execute({"url": "invalid"})
    
    def test_default_parameters(self):
        """Test default parameter values"""
        schema = self.tool.get_input_schema()
        props = schema['properties']
        
        self.assertEqual(props['max_depth']['default'], 1)
        self.assertEqual(props['max_pages']['default'], 10)
        self.assertEqual(props['delay']['default'], 1.0)
        self.assertFalse(props['follow_external']['default'])
        self.assertTrue(props['respect_robots']['default'])
    
    def test_parameter_constraints(self):
        """Test parameter constraints"""
        schema = self.tool.get_input_schema()
        props = schema['properties']
        
        # Depth constraints
        self.assertEqual(props['max_depth']['minimum'], 0)
        self.assertEqual(props['max_depth']['maximum'], 3)
        
        # Pages constraints
        self.assertEqual(props['max_pages']['minimum'], 1)
        self.assertEqual(props['max_pages']['maximum'], 100)
        
        # Delay constraints
        self.assertEqual(props['delay']['minimum'], 0.5)
        self.assertEqual(props['delay']['maximum'], 5.0)


class TestExtractLinksTool(unittest.TestCase):
    """Test cases for ExtractLinksTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ExtractLinksTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('links', schema['properties'])
        self.assertIn('link_count', schema['properties'])
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_extract_links(self, mock_fetch):
        """Test link extraction from HTML"""
        html = '''
        <html>
            <body>
                <a href="https://example.com/page1">Link 1</a>
                <a href="/page2">Link 2</a>
                <a href="https://other.com">External</a>
            </body>
        </html>
        '''
        mock_fetch.return_value = (html, 'text/html', 200)
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertGreater(result['link_count'], 0)
        self.assertIsInstance(result['links'], list)


class TestExtractContentTool(unittest.TestCase):
    """Test cases for ExtractContentTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ExtractContentTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('text_content', schema['properties'])
        self.assertIn('word_count', schema['properties'])
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_extract_text_content(self, mock_fetch):
        """Test text content extraction"""
        html = '''
        <html>
            <head><title>Test Page</title></head>
            <body>
                <p>This is a test paragraph.</p>
                <p>Another paragraph with content.</p>
            </body>
        </html>
        '''
        mock_fetch.return_value = (html, 'text/html', 200)
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertIn('text_content', result)
        self.assertIn('word_count', result)
        self.assertGreater(result['word_count'], 0)


class TestExtractMetadataTool(unittest.TestCase):
    """Test cases for ExtractMetadataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = ExtractMetadataTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('title', schema['properties'])
        self.assertIn('meta_description', schema['properties'])
        self.assertIn('meta_keywords', schema['properties'])
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_extract_metadata(self, mock_fetch):
        """Test metadata extraction"""
        html = '''
        <html>
            <head>
                <title>Test Page Title</title>
                <meta name="description" content="Test description" />
                <meta name="keywords" content="test, keywords" />
                <meta property="og:title" content="OG Title" />
            </head>
        </html>
        '''
        mock_fetch.return_value = (html, 'text/html', 200)
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertEqual(result['title'], "Test Page Title")
        self.assertEqual(result['meta_description'], "Test description")
        self.assertEqual(result['meta_keywords'], "test, keywords")


class TestGetPageInfoTool(unittest.TestCase):
    """Test cases for GetPageInfoTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = GetPageInfoTool()
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('url', schema['properties'])
        self.assertIn('status_code', schema['properties'])
        self.assertIn('title', schema['properties'])
        self.assertIn('headings', schema['properties'])
        self.assertIn('link_count', schema['properties'])
        self.assertIn('image_count', schema['properties'])
    
    @patch('webcrawler_tool_refactored.WebCrawlerBaseTool._fetch_url')
    def test_get_comprehensive_info(self, mock_fetch):
        """Test comprehensive page information extraction"""
        html = '''
        <html>
            <head>
                <title>Test Page</title>
                <meta name="description" content="Test description" />
            </head>
            <body>
                <h1>Main Heading</h1>
                <h2>Subheading 1</h2>
                <h2>Subheading 2</h2>
                <a href="/link1">Link</a>
                <img src="image.jpg" />
            </body>
        </html>
        '''
        mock_fetch.return_value = (html, 'text/html', 200)
        
        result = self.tool.execute({"url": "https://example.com"})
        
        self.assertEqual(result['status_code'], 200)
        self.assertEqual(result['title'], "Test Page")
        self.assertIn('headings', result)
        self.assertGreater(result['link_count'], 0)
        self.assertGreater(result['image_count'], 0)


class TestToolIntegration(unittest.TestCase):
    """Integration tests for tool workflows"""
    
    def test_robots_then_crawl_workflow(self):
        """Test checking robots.txt before crawling"""
        robots_tool = CheckRobotsTxtTool()
        crawl_tool = CrawlURLTool()
        
        # Both tools should be properly initialized
        self.assertIsNotNone(robots_tool)
        self.assertIsNotNone(crawl_tool)
        
        # Schemas should be compatible
        robots_schema = robots_tool.get_input_schema()
        crawl_schema = crawl_tool.get_input_schema()
        
        self.assertIn('url', robots_schema['properties'])
        self.assertIn('url', crawl_schema['properties'])
    
    def test_sitemap_before_crawl_workflow(self):
        """Test using sitemap to guide crawling"""
        sitemap_tool = CrawlSitemapTool()
        crawl_tool = CrawlURLTool()
        
        # Both tools should work with URLs
        sitemap_schema = sitemap_tool.get_input_schema()
        crawl_schema = crawl_tool.get_input_schema()
        
        self.assertIn('url', sitemap_schema['properties'])
        self.assertIn('url', crawl_schema['properties'])
    
    def test_tool_metrics_tracking(self):
        """Test that tools track execution metrics"""
        tool = CheckRobotsTxtTool()
        
        # Initial metrics
        metrics = tool.get_metrics()
        self.assertEqual(metrics['execution_count'], 0)
        self.assertIsNone(metrics['last_execution'])
        
        # Note: We can't execute without valid network/URL
        # This just tests the metrics structure
        self.assertIn('name', metrics)
        self.assertIn('version', metrics)
        self.assertIn('enabled', metrics)


class TestErrorHandling(unittest.TestCase):
    """Test error handling across all tools"""
    
    def test_invalid_url_handling(self):
        """Test that all tools handle invalid URLs properly"""
        tools = [
            CrawlURLTool(),
            ExtractLinksTool(),
            ExtractContentTool(),
            ExtractMetadataTool(),
            CrawlSitemapTool(),
            CheckRobotsTxtTool(),
            GetPageInfoTool()
        ]
        
        for tool in tools:
            with self.subTest(tool=tool.name):
                with self.assertRaises(ValueError):
                    tool.execute({"url": "invalid-url"})
    
    def test_missing_required_parameters(self):
        """Test handling of missing required parameters"""
        tool = CrawlURLTool()
        
        with self.assertRaises(ValueError):
            tool.validate_arguments({})  # Missing 'url'
    
    def test_tool_enable_disable(self):
        """Test tool enable/disable functionality"""
        tool = CheckRobotsTxtTool()
        
        # Should be enabled by default
        self.assertTrue(tool.enabled)
        
        # Disable tool
        tool.disable()
        self.assertFalse(tool.enabled)
        
        # Re-enable tool
        tool.enable()
        self.assertTrue(tool.enabled)


class TestPerformance(unittest.TestCase):
    """Performance and timing tests"""
    
    def test_schema_access_performance(self):
        """Test that schema access is fast"""
        tool = CrawlURLTool()
        
        start = time.time()
        for _ in range(1000):
            schema = tool.get_input_schema()
        duration = time.time() - start
        
        # Should be very fast (< 0.1 seconds for 1000 accesses)
        self.assertLess(duration, 0.1)
    
    def test_tool_initialization_performance(self):
        """Test that tool initialization is fast"""
        start = time.time()
        for _ in range(100):
            tool = CrawlURLTool()
        duration = time.time() - start
        
        # Should be very fast (< 0.5 seconds for 100 initializations)
        self.assertLess(duration, 0.5)


class TestConfigurationLoading(unittest.TestCase):
    """Test configuration loading from JSON files"""
    
    def test_tool_config_structure(self):
        """Test that tools can be configured properly"""
        config = {
            'name': 'test_crawler',
            'description': 'Test crawler tool',
            'version': '2.0.0',
            'enabled': True
        }
        
        tool = CrawlURLTool(config)
        
        self.assertEqual(tool.name, 'test_crawler')
        self.assertEqual(tool.description, 'Test crawler tool')
        self.assertEqual(tool.version, '2.0.0')
        self.assertTrue(tool.enabled)


def run_test_suite():
    """Run the complete test suite with detailed output"""
    
    print("="*70)
    print("Web Crawler MCP Tool - Comprehensive Test Suite")
    print("Copyright All rights reserved 2025-2030 Ashutosh Sinha")
    print("Email: ajsinha@gmail.com")
    print("="*70)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestLinkExtractor,
        TestWebCrawlerBaseTool,
        TestCheckRobotsTxtTool,
        TestCrawlSitemapTool,
        TestCrawlURLTool,
        TestExtractLinksTool,
        TestExtractContentTool,
        TestExtractMetadataTool,
        TestGetPageInfoTool,
        TestToolIntegration,
        TestErrorHandling,
        TestPerformance,
        TestConfigurationLoading
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("="*70)
    print("Test Suite Summary")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print()
    
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED!")
    else:
        print("✗ SOME TESTS FAILED")
        
    print("="*70)
    
    return result


if __name__ == '__main__':
    # Run the complete test suite
    result = run_test_suite()
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
