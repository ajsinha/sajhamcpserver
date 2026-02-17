#!/usr/bin/env python3
"""
SAJHA MCP Server - Wikipedia Tools Client v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Wikipedia tools:
- wiki_search: Search Wikipedia articles
- wiki_get_summary: Get article summary
- wiki_get_page: Get full article content

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.wikipedia_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class WikipediaClient(SajhaClient):
    """Client for Wikipedia tools."""
    
    def search(self, query: str, limit: int = 10) -> dict:
        """
        Search Wikipedia articles.
        
        Args:
            query: Search query
            limit: Maximum results (1-20)
        """
        return self.execute_tool('wiki_search', {
            'query': query,
            'limit': limit
        })
    
    def get_summary(self, title: str, sentences: int = 5) -> dict:
        """
        Get article summary.
        
        Args:
            title: Article title
            sentences: Number of sentences (1-10)
        """
        return self.execute_tool('wiki_get_summary', {
            'title': title,
            'sentences': sentences
        })
    
    def get_page(self, title: str, section: str = None) -> dict:
        """
        Get full article content.
        
        Args:
            title: Article title
            section: Optional specific section
        """
        args = {'title': title}
        if section:
            args['section'] = section
        return self.execute_tool('wiki_get_page', args)


@run_example
def example_search():
    """Example: Search Wikipedia"""
    client = WikipediaClient()
    
    print("\n🔍 Searching Wikipedia for 'Machine Learning'...")
    results = client.search("Machine Learning", limit=5)
    pretty_print(results, "Wikipedia Search Results")


@run_example
def example_get_summary():
    """Example: Get article summary"""
    client = WikipediaClient()
    
    print("\n📄 Getting summary for 'Python (programming language)'...")
    summary = client.get_summary("Python (programming language)", sentences=3)
    pretty_print(summary, "Article Summary")


@run_example
def example_get_page():
    """Example: Get full article"""
    client = WikipediaClient()
    
    print("\n📖 Getting full article for 'Artificial Intelligence'...")
    page = client.get_page("Artificial Intelligence")
    
    # Truncate content for display
    if 'content' in page and len(page['content']) > 1000:
        page['content'] = page['content'][:1000] + '...[truncated]'
    
    pretty_print(page, "Full Article")


@run_example
def example_research_workflow():
    """Example: Complete research workflow"""
    client = WikipediaClient()
    
    topic = "Quantum Computing"
    print(f"\n🔬 Research Workflow: {topic}")
    
    # Step 1: Search for related articles
    print("\n1️⃣ Searching for related articles...")
    search_results = client.search(topic, limit=3)
    
    if search_results.get('results'):
        articles = search_results['results']
        print(f"   Found {len(articles)} articles")
        
        # Step 2: Get summaries for each
        print("\n2️⃣ Getting summaries...")
        for article in articles[:2]:
            title = article.get('title', '')
            if title:
                print(f"\n   📄 {title}")
                summary = client.get_summary(title, sentences=2)
                if summary.get('summary'):
                    print(f"      {summary['summary'][:200]}...")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Wikipedia Tools Examples v2.3.0")
    print("=" * 60)
    
    example_search()
    example_get_summary()
    example_get_page()
    example_research_workflow()
