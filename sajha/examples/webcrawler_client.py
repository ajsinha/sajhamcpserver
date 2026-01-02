#!/usr/bin/env python3
"""
SAJHA MCP Server - Web Crawler Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Web Crawler tools:
- crawl_url: Crawl a URL
- crawl_sitemap: Parse sitemap
- extract_links: Extract links from page
- extract_content: Extract main content
- extract_metadata: Get page metadata
- get_page_info: Get page information
- check_robots_txt: Check robots.txt

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.webcrawler_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class WebCrawlerClient(SajhaClient):
    """Client for Web Crawler tools."""
    
    def crawl_url(self, 
                  url: str, 
                  depth: int = 1,
                  max_pages: int = 10) -> dict:
        """
        Crawl a URL.
        
        Args:
            url: URL to crawl
            depth: Crawl depth (1-3)
            max_pages: Maximum pages to crawl
        """
        return self.execute_tool('crawl_url', {
            'url': url,
            'depth': depth,
            'max_pages': max_pages
        })
    
    def crawl_sitemap(self, url: str) -> dict:
        """
        Parse and analyze a sitemap.
        
        Args:
            url: Sitemap URL
        """
        return self.execute_tool('crawl_sitemap', {'url': url})
    
    def extract_links(self, url: str, filter_pattern: str = None) -> dict:
        """
        Extract links from a page.
        
        Args:
            url: Page URL
            filter_pattern: Optional regex pattern to filter links
        """
        args = {'url': url}
        if filter_pattern:
            args['filter_pattern'] = filter_pattern
        return self.execute_tool('extract_links', args)
    
    def extract_content(self, url: str) -> dict:
        """
        Extract main content from a page.
        
        Args:
            url: Page URL
        """
        return self.execute_tool('extract_content', {'url': url})
    
    def extract_metadata(self, url: str) -> dict:
        """
        Get page metadata (title, description, etc.).
        
        Args:
            url: Page URL
        """
        return self.execute_tool('extract_metadata', {'url': url})
    
    def get_page_info(self, url: str) -> dict:
        """
        Get comprehensive page information.
        
        Args:
            url: Page URL
        """
        return self.execute_tool('get_page_info', {'url': url})
    
    def check_robots_txt(self, url: str, user_agent: str = '*') -> dict:
        """
        Check robots.txt rules for a URL.
        
        Args:
            url: URL to check
            user_agent: User agent to check rules for
        """
        return self.execute_tool('check_robots_txt', {
            'url': url,
            'user_agent': user_agent
        })


@run_example
def example_extract_metadata():
    """Example: Extract page metadata"""
    client = WebCrawlerClient()
    
    url = "https://example.com"
    print(f"\n📄 Extracting metadata from: {url}")
    metadata = client.extract_metadata(url)
    pretty_print(metadata, "Page Metadata")


@run_example
def example_extract_links():
    """Example: Extract links from page"""
    client = WebCrawlerClient()
    
    url = "https://example.com"
    print(f"\n🔗 Extracting links from: {url}")
    links = client.extract_links(url)
    pretty_print(links, "Extracted Links")


@run_example
def example_extract_content():
    """Example: Extract main content"""
    client = WebCrawlerClient()
    
    url = "https://example.com"
    print(f"\n📝 Extracting content from: {url}")
    content = client.extract_content(url)
    
    # Truncate for display
    if content.get('content') and len(content['content']) > 500:
        content['content'] = content['content'][:500] + '...[truncated]'
    
    pretty_print(content, "Extracted Content")


@run_example
def example_check_robots():
    """Example: Check robots.txt"""
    client = WebCrawlerClient()
    
    url = "https://google.com"
    print(f"\n🤖 Checking robots.txt for: {url}")
    robots = client.check_robots_txt(url)
    pretty_print(robots, "Robots.txt Rules")


@run_example
def example_page_info():
    """Example: Get comprehensive page info"""
    client = WebCrawlerClient()
    
    url = "https://example.com"
    print(f"\n📊 Getting page info for: {url}")
    info = client.get_page_info(url)
    pretty_print(info, "Page Information")


@run_example
def example_website_analysis():
    """Example: Complete website analysis"""
    client = WebCrawlerClient()
    
    url = "https://example.com"
    print(f"\n🔬 Website Analysis: {url}")
    print("=" * 50)
    
    # Step 1: Check robots.txt
    print("\n1️⃣ Robots.txt:")
    try:
        robots = client.check_robots_txt(url)
        print(f"   Allowed: {robots.get('allowed', 'N/A')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Step 2: Get metadata
    print("\n2️⃣ Metadata:")
    try:
        metadata = client.extract_metadata(url)
        print(f"   Title: {metadata.get('title', 'N/A')}")
        print(f"   Description: {metadata.get('description', 'N/A')[:100]}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Step 3: Extract links
    print("\n3️⃣ Links:")
    try:
        links = client.extract_links(url)
        link_count = len(links.get('links', []))
        print(f"   Found {link_count} links")
        for link in links.get('links', [])[:5]:
            print(f"   - {link}")
    except Exception as e:
        print(f"   Error: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Web Crawler Tools Examples v2.2.0")
    print("=" * 60)
    
    example_extract_metadata()
    example_extract_links()
    example_extract_content()
    example_check_robots()
    example_page_info()
    example_website_analysis()
