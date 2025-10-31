"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Google Search MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List
from ..base_mcp_tool import BaseMCPTool

class GoogleSearchTool(BaseMCPTool):
    """
    Google Search tool using Custom Search JSON API
    Note: Requires Google Custom Search API key and Search Engine ID
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Google Search tool"""
        default_config = {
            'name': 'google_search',
            'description': 'Search the web using Google',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Google Custom Search API endpoint
        self.api_url = "https://www.googleapis.com/customsearch/v1"
        
        # API credentials (should be configured in properties)
        self.api_key = config.get('api_key', '') if config else ''
        self.search_engine_id = config.get('search_engine_id', '') if config else ''
        
        # If no API key, use a mock/demo mode
        self.demo_mode = not self.api_key or not self.search_engine_id
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Google Search tool"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 10
                },
                "start": {
                    "type": "integer",
                    "description": "Starting index for results (for pagination)",
                    "default": 1,
                    "minimum": 1
                },
                "safe_search": {
                    "type": "string",
                    "description": "Safe search level",
                    "enum": ["off", "medium", "high"],
                    "default": "medium"
                },
                "search_type": {
                    "type": "string",
                    "description": "Type of search",
                    "enum": ["web", "image", "video"],
                    "default": "web"
                },
                "site": {
                    "type": "string",
                    "description": "Restrict search to specific site (e.g., wikipedia.org)"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Google Search
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Search results
        """
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        # If in demo mode, return mock data
        if self.demo_mode:
            return self._get_demo_results(query, arguments)
        
        # Build search query
        num_results = arguments.get('num_results', 10)
        start = arguments.get('start', 1)
        safe_search = arguments.get('safe_search', 'medium')
        search_type = arguments.get('search_type', 'web')
        site = arguments.get('site')
        
        # Modify query if site restriction is specified
        if site:
            query = f"site:{site} {query}"
        
        return self._search(query, num_results, start, safe_search, search_type)
    
    def _search(self, query: str, num_results: int, start: int, safe_search: str, search_type: str) -> Dict:
        """
        Perform Google search
        
        Args:
            query: Search query
            num_results: Number of results
            start: Starting index
            safe_search: Safe search level
            search_type: Type of search
            
        Returns:
            Search results
        """
        params = {
            'key': self.api_key,
            'cx': self.search_engine_id,
            'q': query,
            'num': num_results,
            'start': start,
            'safe': safe_search
        }
        
        # Add search type if not web
        if search_type == 'image':
            params['searchType'] = 'image'
        
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Extract search information
                search_info = data.get('searchInformation', {})
                
                # Format results
                items = data.get('items', [])
                results = []
                
                for item in items:
                    result = {
                        'title': item.get('title', ''),
                        'link': item.get('link', ''),
                        'snippet': item.get('snippet', ''),
                        'displayLink': item.get('displayLink', '')
                    }
                    
                    # Add image-specific data if image search
                    if search_type == 'image' and 'image' in item:
                        result['image'] = {
                            'thumbnailLink': item['image'].get('thumbnailLink', ''),
                            'contextLink': item['image'].get('contextLink', ''),
                            'height': item['image'].get('height', 0),
                            'width': item['image'].get('width', 0)
                        }
                    
                    results.append(result)
                
                return {
                    'query': query,
                    'totalResults': search_info.get('totalResults', '0'),
                    'searchTime': search_info.get('searchTime', 0),
                    'count': len(results),
                    'results': results
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise ValueError("Invalid search parameters")
            elif e.code == 403:
                raise ValueError("API key invalid or quota exceeded")
            else:
                self.logger.error(f"Google Search API error: {e}")
                raise ValueError(f"Search failed: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Google Search error: {e}")
            raise ValueError(f"Search failed: {str(e)}")
    
    def _get_demo_results(self, query: str, arguments: Dict) -> Dict:
        """
        Get demo/mock search results when API key is not configured
        
        Args:
            query: Search query
            arguments: Search arguments
            
        Returns:
            Mock search results
        """
        num_results = min(arguments.get('num_results', 10), 5)  # Limit demo results
        
        # Create some demo results based on the query
        demo_results = []
        
        # Add some generic demo results
        base_results = [
            {
                'title': f'Example Result 1 for "{query}"',
                'link': f'https://example.com/search?q={urllib.parse.quote(query)}',
                'snippet': f'This is a demo result for your search query "{query}". In production, this would show real search results from Google.',
                'displayLink': 'example.com'
            },
            {
                'title': f'Wikipedia: {query.title()}',
                'link': f'https://en.wikipedia.org/wiki/{urllib.parse.quote(query.replace(" ", "_"))}',
                'snippet': f'Information about {query} from Wikipedia. This is a demo result showing what a Wikipedia search result might look like.',
                'displayLink': 'en.wikipedia.org'
            },
            {
                'title': f'News about {query}',
                'link': f'https://news.example.com/{urllib.parse.quote(query)}',
                'snippet': f'Latest news and updates about {query}. Stay informed with the most recent developments.',
                'displayLink': 'news.example.com'
            },
            {
                'title': f'Learn more about {query}',
                'link': f'https://learn.example.com/topics/{urllib.parse.quote(query)}',
                'snippet': f'Educational resources and tutorials about {query}. Perfect for beginners and experts alike.',
                'displayLink': 'learn.example.com'
            },
            {
                'title': f'{query} - Complete Guide',
                'link': f'https://guide.example.com/{urllib.parse.quote(query)}',
                'snippet': f'A comprehensive guide to understanding {query}. Everything you need to know in one place.',
                'displayLink': 'guide.example.com'
            }
        ]
        
        demo_results = base_results[:num_results]
        
        return {
            'query': query,
            'totalResults': '1000000',  # Mock total
            'searchTime': 0.25,  # Mock search time
            'count': len(demo_results),
            'results': demo_results,
            'note': 'Demo mode - Configure API key and Search Engine ID for real results'
        }
