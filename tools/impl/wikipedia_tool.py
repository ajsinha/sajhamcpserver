"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Wikipedia MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List
from ..base_mcp_tool import BaseMCPTool

class WikipediaTool(BaseMCPTool):
    """
    Wikipedia search and content retrieval tool
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Wikipedia tool"""
        default_config = {
            'name': 'wikipedia',
            'description': 'Search and retrieve information from Wikipedia',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Wikipedia API endpoint
        self.api_url = "https://en.wikipedia.org/w/api.php"
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Wikipedia tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["search", "get_page", "get_summary"]
                },
                "query": {
                    "type": "string",
                    "description": "Search query or page title"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (for search)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                }
            },
            "required": ["action", "query"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Wikipedia tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Wikipedia data or search results
        """
        action = arguments.get('action')
        query = arguments.get('query')
        
        if not action or not query:
            raise ValueError("Both 'action' and 'query' are required")
        
        if action == 'search':
            return self._search(query, arguments.get('limit', 5))
        elif action == 'get_page':
            return self._get_page(query)
        elif action == 'get_summary':
            return self._get_summary(query)
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _search(self, query: str, limit: int) -> Dict:
        """
        Search Wikipedia
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            Search results
        """
        params = {
            'action': 'opensearch',
            'search': query,
            'limit': limit,
            'format': 'json'
        }
        
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        
        try:
            # Create request with User-Agent header
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)')

            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))

                # Format results
                results = []
                if len(data) >= 4:
                    titles = data[1]
                    descriptions = data[2]
                    urls = data[3]

                    for i in range(len(titles)):
                        results.append({
                            'title': titles[i],
                            'description': descriptions[i] if i < len(descriptions) else '',
                            'url': urls[i] if i < len(urls) else ''
                        })

                return {
                    'query': query,
                    'count': len(results),
                    'results': results
                }

        except Exception as e:
            self.logger.error(f"Wikipedia search error: {e}")
            raise ValueError(f"Failed to search Wikipedia: {str(e)}")

    def _get_page(self, title: str) -> Dict:
        """
        Get full Wikipedia page content

        Args:
            title: Page title

        Returns:
            Page content
        """
        params = {
            'action': 'query',
            'prop': 'extracts',
            'titles': title,
            'format': 'json',
            'exintro': False,
            'explaintext': True
        }

        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"

        try:
            # Create request with User-Agent header
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)')

            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))

                pages = data.get('query', {}).get('pages', {})
                if pages:
                    page_id = list(pages.keys())[0]
                    page = pages[page_id]

                    if 'missing' in page:
                        raise ValueError(f"Page not found: {title}")

                    return {
                        'title': page.get('title', title),
                        'pageid': page.get('pageid'),
                        'content': page.get('extract', ''),
                        'url': f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page.get('title', title).replace(' ', '_'))}"
                    }
                else:
                    raise ValueError(f"Page not found: {title}")

        except Exception as e:
            self.logger.error(f"Wikipedia page retrieval error: {e}")
            raise ValueError(f"Failed to get Wikipedia page: {str(e)}")

    def _get_summary(self, title: str) -> Dict:
        """
        Get Wikipedia page summary

        Args:
            title: Page title

        Returns:
            Page summary
        """
        params = {
            'action': 'query',
            'prop': 'extracts',
            'titles': title,
            'format': 'json',
            'exintro': True,  # Only get introduction
            'explaintext': True,
            'exsentences': 5  # Get first 5 sentences
        }

        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"

        try:
            # Create request with User-Agent header
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)')

            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))

                pages = data.get('query', {}).get('pages', {})
                if pages:
                    page_id = list(pages.keys())[0]
                    page = pages[page_id]

                    if 'missing' in page:
                        raise ValueError(f"Page not found: {title}")

                    return {
                        'title': page.get('title', title),
                        'pageid': page.get('pageid'),
                        'summary': page.get('extract', ''),
                        'url': f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page.get('title', title).replace(' ', '_'))}"
                    }
                else:
                    raise ValueError(f"Page not found: {title}")

        except Exception as e:
            self.logger.error(f"Wikipedia summary retrieval error: {e}")
            raise ValueError(f"Failed to get Wikipedia summary: {str(e)}")