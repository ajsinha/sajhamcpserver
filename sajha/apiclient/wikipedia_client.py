"""
SAJHA MCP Server - Wikipedia Client
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

This client provides programmatic access to Wikipedia tools via the SAJHA MCP Server API.
Includes authentication and all Wikipedia tool operations:
- wiki_search: Search Wikipedia articles by keyword
- wiki_get_page: Get complete article content
- wiki_get_summary: Get article summary
"""

import json
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime


class WikipediaClient:
    """Client for Wikipedia tools via SAJHA MCP Server API"""
    
    def __init__(self, base_url: str = "http://localhost:5000", user_id: str = None, password: str = None):
        """
        Initialize Wikipedia client
        
        Args:
            base_url: Base URL of the SAJHA MCP Server (default: http://localhost:5000)
            user_id: User ID for authentication (optional, can login later)
            password: Password for authentication (optional, can login later)
        """
        self.base_url = base_url.rstrip('/')
        self.token = None
        self.user_info = None
        
        # Auto-login if credentials provided
        if user_id and password:
            self.login(user_id, password)
    
    def login(self, user_id: str, password: str) -> Dict[str, Any]:
        """
        Authenticate with the SAJHA MCP Server
        
        Args:
            user_id: User ID
            password: User password
            
        Returns:
            Dict containing token and user information
            
        Raises:
            Exception: If authentication fails
        """
        url = f"{self.base_url}/api/auth/login"
        payload = {
            "user_id": user_id,
            "password": password
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            self.token = data.get('token')
            self.user_info = data.get('user')
            
            print(f"✓ Successfully authenticated as {self.user_info.get('user_name')}")
            return data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise Exception("Authentication failed: Invalid credentials")
            else:
                raise Exception(f"Authentication failed: HTTP {e.response.status_code}")
        except Exception as e:
            raise Exception(f"Authentication failed: {str(e)}")
    
    def _make_request(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make authenticated API request to execute a tool
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            Exception: If request fails or user is not authenticated
        """
        if not self.token:
            raise Exception("Not authenticated. Please call login() first.")
        
        url = f"{self.base_url}/api/tools/execute"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "tool": tool_name,
            "arguments": arguments
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('success'):
                return data.get('result')
            else:
                raise Exception(f"Tool execution failed: {data.get('error')}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise Exception("Authentication failed: Invalid or expired token")
            elif e.response.status_code == 403:
                raise Exception(f"Access denied: You don't have permission to use {tool_name}")
            elif e.response.status_code == 404:
                raise Exception(f"Tool not found: {tool_name}")
            else:
                raise Exception(f"Request failed: HTTP {e.response.status_code}")
        except Exception as e:
            raise Exception(f"Request failed: {str(e)}")
    
    # ==================== Wikipedia Search ====================
    
    def search(self, query: str, limit: int = 5, language: str = 'en') -> Dict[str, Any]:
        """
        Search Wikipedia articles by keyword or phrase
        
        Args:
            query: Search query - topic, keyword, or phrase
            limit: Maximum number of search results (1-20, default: 5)
            language: Wikipedia language edition (e.g., 'en', 'es', 'fr', default: 'en')
            
        Returns:
            Dict containing:
                - query: Original search query
                - language: Language edition used
                - result_count: Number of results returned
                - results: List of matching articles with title, page_id, snippet, url, etc.
                - suggestion: Alternative search suggestion (if any)
                - last_updated: Timestamp
                
        Example:
            >>> client.search("artificial intelligence", limit=10)
            >>> client.search("machine learning")
            >>> client.search("inteligencia artificial", language="es")
        """
        arguments = {
            "query": query,
            "limit": limit,
            "language": language
        }
        return self._make_request("wiki_search", arguments)
    
    # ==================== Get Wikipedia Page ====================
    
    def get_page(self, 
                 query: Optional[str] = None,
                 page_id: Optional[int] = None,
                 language: str = 'en',
                 redirect: bool = True,
                 include_images: bool = True,
                 include_links: bool = True,
                 include_references: bool = False) -> Dict[str, Any]:
        """
        Retrieve the complete content of a Wikipedia article
        
        Args:
            query: Article title or exact page name (e.g., 'Machine Learning')
            page_id: Wikipedia page ID (alternative to query)
            language: Wikipedia language edition (default: 'en')
            redirect: Follow redirects to target article (default: True)
            include_images: Include image URLs from the article (default: True)
            include_links: Include internal and external links (default: True)
            include_references: Include article references and citations (default: False)
            
        Note: Either query or page_id must be provided
        
        Returns:
            Dict containing:
                - title: Article title
                - page_id: Wikipedia page ID
                - url: Full URL to the article
                - language: Language edition
                - content: Full article content in plain text
                - summary: Brief summary/lead section
                - sections: Article sections with headings
                - images: Image URLs (if include_images=True)
                - links: Internal and external links (if include_links=True)
                - references: Citations (if include_references=True)
                - categories: Wikipedia categories
                - last_modified: Last modification timestamp
                - word_count: Total word count
                
        Example:
            >>> client.get_page(query="Machine Learning")
            >>> client.get_page(page_id=5043734)
            >>> client.get_page(query="Python (programming language)", include_references=True)
        """
        arguments = {
            "language": language,
            "redirect": redirect,
            "include_images": include_images,
            "include_links": include_links,
            "include_references": include_references
        }
        
        if query:
            arguments["query"] = query
        elif page_id:
            arguments["page_id"] = page_id
        else:
            raise ValueError("Either 'query' or 'page_id' must be provided")
        
        return self._make_request("wiki_get_page", arguments)
    
    # ==================== Get Wikipedia Summary ====================
    
    def get_summary(self,
                    query: Optional[str] = None,
                    page_id: Optional[int] = None,
                    language: str = 'en',
                    sentences: int = 3,
                    redirect: bool = True,
                    include_image: bool = True) -> Dict[str, Any]:
        """
        Retrieve a concise summary of a Wikipedia article
        
        Args:
            query: Article title or page name (e.g., 'Photosynthesis')
            page_id: Wikipedia page ID (alternative to query)
            language: Wikipedia language edition (default: 'en')
            sentences: Number of sentences to return in summary (1-10, default: 3)
            redirect: Follow redirects to target article (default: True)
            include_image: Include main article image/thumbnail (default: True)
            
        Note: Either query or page_id must be provided
        
        Returns:
            Dict containing:
                - title: Article title
                - page_id: Wikipedia page ID
                - url: Full URL to the article
                - language: Language edition
                - summary: Concise summary from the lead section
                - extract: Plain text extract
                - thumbnail: Main article image (if include_image=True)
                - coordinates: Geographic coordinates (if applicable)
                - description: Short one-line description
                - last_modified: Last modification timestamp
                
        Example:
            >>> client.get_summary(query="Python (programming language)", sentences=5)
            >>> client.get_summary(query="Mount Everest", include_image=True)
            >>> client.get_summary(query="Quantum Computing", sentences=1)
        """
        arguments = {
            "language": language,
            "sentences": sentences,
            "redirect": redirect,
            "include_image": include_image
        }
        
        if query:
            arguments["query"] = query
        elif page_id:
            arguments["page_id"] = page_id
        else:
            raise ValueError("Either 'query' or 'page_id' must be provided")
        
        return self._make_request("wiki_get_summary", arguments)
    
    # ==================== Utility Methods ====================
    
    def print_search_results(self, results: Dict[str, Any], max_snippet_length: int = 150):
        """
        Pretty print search results
        
        Args:
            results: Search results from search() method
            max_snippet_length: Maximum length of snippet to display (default: 150)
        """
        print(f"\n{'='*80}")
        print(f"Search Results for: '{results['query']}' (Language: {results['language']})")
        print(f"Found {results['result_count']} results")
        print(f"{'='*80}\n")
        
        for i, article in enumerate(results['results'], 1):
            print(f"{i}. {article['title']}")
            print(f"   Page ID: {article['page_id']}")
            snippet = article['snippet']
            if len(snippet) > max_snippet_length:
                snippet = snippet[:max_snippet_length] + "..."
            print(f"   {snippet}")
            print(f"   URL: {article['url']}")
            print(f"   Words: {article.get('word_count', 'N/A')}")
            print()
        
        if results.get('suggestion'):
            print(f"💡 Did you mean: {results['suggestion']}")
    
    def print_summary(self, summary: Dict[str, Any]):
        """
        Pretty print article summary
        
        Args:
            summary: Summary result from get_summary() method
        """
        print(f"\n{'='*80}")
        print(f"Wikipedia Summary: {summary['title']}")
        print(f"{'='*80}")
        print(f"Page ID: {summary['page_id']}")
        print(f"URL: {summary['url']}")
        print(f"Language: {summary['language']}")
        if summary.get('description'):
            print(f"Description: {summary['description']}")
        print(f"\n{summary['summary']}")
        
        if summary.get('thumbnail'):
            print(f"\n📷 Image: {summary['thumbnail']['url']}")
        
        if summary.get('coordinates'):
            coords = summary['coordinates']
            print(f"\n📍 Location: {coords['latitude']}, {coords['longitude']}")
        
        print(f"\n{'='*80}\n")


# ==================== Example Usage ====================

def main():
    """Example usage of Wikipedia client"""
    
    # Initialize client (replace with your credentials)
    client = WikipediaClient(
        base_url="http://localhost:5000",
        user_id="admin",
        password="admin123"
    )
    
    print("\n" + "="*80)
    print("WIKIPEDIA CLIENT - EXAMPLE USAGE")
    print("="*80)
    
    # Example 1: Search for articles
    print("\n1. SEARCHING FOR ARTICLES ABOUT 'ARTIFICIAL INTELLIGENCE'")
    print("-" * 80)
    try:
        search_results = client.search("artificial intelligence", limit=5)
        client.print_search_results(search_results)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 2: Get article summary
    print("\n2. GETTING SUMMARY OF 'MACHINE LEARNING'")
    print("-" * 80)
    try:
        summary = client.get_summary(query="Machine Learning", sentences=5)
        client.print_summary(summary)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 3: Get complete article
    print("\n3. GETTING COMPLETE ARTICLE: 'PYTHON (PROGRAMMING LANGUAGE)'")
    print("-" * 80)
    try:
        page = client.get_page(query="Python (programming language)", include_references=True)
        print(f"Title: {page['title']}")
        print(f"Page ID: {page['page_id']}")
        print(f"URL: {page['url']}")
        print(f"Word Count: {page['word_count']}")
        print(f"Number of Sections: {len(page['sections'])}")
        print(f"Number of Images: {len(page['images'])}")
        print(f"Number of Categories: {len(page['categories'])}")
        print(f"\nFirst 500 characters of content:")
        print(page['content'][:500] + "...")
        print(f"\nCategories: {', '.join(page['categories'][:5])}")
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 4: Search in different language
    print("\n4. SEARCHING IN SPANISH WIKIPEDIA")
    print("-" * 80)
    try:
        search_results = client.search("inteligencia artificial", limit=3, language="es")
        client.print_search_results(search_results)
    except Exception as e:
        print(f"Error: {e}")
    
    # Example 5: Get page by ID
    print("\n5. GETTING PAGE BY ID")
    print("-" * 80)
    try:
        page = client.get_page(page_id=5043734)  # Machine Learning page
        print(f"Retrieved page: {page['title']}")
        print(f"URL: {page['url']}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
