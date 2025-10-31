"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tavily Search MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List
from ..base_mcp_tool import BaseMCPTool

class TavilyTool(BaseMCPTool):
    """
    Tavily AI-powered search tool for retrieving web information
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Tavily tool"""
        default_config = {
            'name': 'tavily',
            'description': 'AI-powered web search using Tavily API',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Tavily API endpoint
        self.api_url = "https://api.tavily.com/search"
        
        # API key (required for production use)
        self.api_key = config.get('api_key', '') if config else ''
        
        # Demo mode if no API key
        self.demo_mode = not self.api_key
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Tavily tool"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "search_depth": {
                    "type": "string",
                    "description": "Depth of search - 'basic' for quick results, 'advanced' for comprehensive search",
                    "enum": ["basic", "advanced"],
                    "default": "basic"
                },
                "topic": {
                    "type": "string",
                    "description": "Category of search",
                    "enum": ["general", "news", "finance", "science"],
                    "default": "general"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Include AI-generated answer summary",
                    "default": True
                },
                "include_raw_content": {
                    "type": "boolean",
                    "description": "Include raw HTML content of pages",
                    "default": False
                },
                "include_images": {
                    "type": "boolean",
                    "description": "Include relevant images in results",
                    "default": False
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to specifically include in search"
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to exclude from search"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Tavily search
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Search results from Tavily
        """
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        # If in demo mode, return mock data
        if self.demo_mode:
            return self._get_demo_results(query, arguments)
        
        # Build search request
        search_depth = arguments.get('search_depth', 'basic')
        topic = arguments.get('topic', 'general')
        max_results = arguments.get('max_results', 5)
        include_answer = arguments.get('include_answer', True)
        include_raw_content = arguments.get('include_raw_content', False)
        include_images = arguments.get('include_images', False)
        include_domains = arguments.get('include_domains', [])
        exclude_domains = arguments.get('exclude_domains', [])
        
        return self._search(
            query, 
            search_depth, 
            topic, 
            max_results,
            include_answer,
            include_raw_content,
            include_images,
            include_domains,
            exclude_domains
        )
    
    def _search(
        self, 
        query: str, 
        search_depth: str,
        topic: str,
        max_results: int,
        include_answer: bool,
        include_raw_content: bool,
        include_images: bool,
        include_domains: List[str],
        exclude_domains: List[str]
    ) -> Dict:
        """
        Perform Tavily search
        
        Args:
            query: Search query
            search_depth: Depth of search
            topic: Search category
            max_results: Maximum results
            include_answer: Include AI answer
            include_raw_content: Include raw content
            include_images: Include images
            include_domains: Domains to include
            exclude_domains: Domains to exclude
            
        Returns:
            Search results
        """
        # Build request payload
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images
        }
        
        # Add domain filters if provided
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        
        try:
            # Make API request
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
            )
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                
                # Format results
                formatted_results = []
                for item in result.get('results', []):
                    formatted_item = {
                        'title': item.get('title', ''),
                        'url': item.get('url', ''),
                        'content': item.get('content', ''),
                        'score': item.get('score', 0),
                        'published_date': item.get('published_date', '')
                    }
                    
                    # Add optional fields if present
                    if include_raw_content and 'raw_content' in item:
                        formatted_item['raw_content'] = item['raw_content']
                    
                    formatted_results.append(formatted_item)
                
                response_data = {
                    'query': query,
                    'search_depth': search_depth,
                    'topic': topic,
                    'results_count': len(formatted_results),
                    'results': formatted_results
                }
                
                # Add answer if requested and available
                if include_answer and 'answer' in result:
                    response_data['answer'] = result['answer']
                
                # Add images if requested and available
                if include_images and 'images' in result:
                    response_data['images'] = result['images']
                
                return response_data
                
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise ValueError("Invalid search parameters")
            elif e.code == 401:
                raise ValueError("Invalid API key")
            elif e.code == 429:
                raise ValueError("Rate limit exceeded")
            else:
                self.logger.error(f"Tavily API error: {e}")
                raise ValueError(f"Search failed: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Tavily search error: {e}")
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
        max_results = min(arguments.get('max_results', 5), 5)
        search_depth = arguments.get('search_depth', 'basic')
        topic = arguments.get('topic', 'general')
        include_answer = arguments.get('include_answer', True)
        include_images = arguments.get('include_images', False)
        
        # Create demo results
        demo_results = [
            {
                'title': f'Comprehensive Guide to {query.title()}',
                'url': f'https://example.com/guide/{urllib.parse.quote(query.lower().replace(" ", "-"))}',
                'content': f'This is a comprehensive guide covering everything you need to know about {query}. This demo result shows what Tavily would return with real data. The content includes in-depth analysis, expert opinions, and practical examples.',
                'score': 0.95,
                'published_date': '2024-10-15'
            },
            {
                'title': f'Latest Research on {query.title()}',
                'url': f'https://research.example.com/papers/{urllib.parse.quote(query)}',
                'content': f'Recent academic research and studies related to {query}. This demo content demonstrates the type of results Tavily provides, including scholarly articles and research papers with high relevance scores.',
                'score': 0.92,
                'published_date': '2024-10-20'
            },
            {
                'title': f'{query.title()} - Industry Insights and Trends',
                'url': f'https://insights.example.com/{urllib.parse.quote(query)}',
                'content': f'Industry analysis and current trends for {query}. Expert commentary and data-driven insights help understand the market dynamics and future predictions.',
                'score': 0.88,
                'published_date': '2024-10-22'
            },
            {
                'title': f'Practical Applications of {query.title()}',
                'url': f'https://practical.example.com/topics/{urllib.parse.quote(query)}',
                'content': f'Real-world applications and use cases for {query}. This includes case studies, best practices, and implementation guides from leading organizations.',
                'score': 0.85,
                'published_date': '2024-10-18'
            },
            {
                'title': f'{query.title()} News and Updates',
                'url': f'https://news.example.com/category/{urllib.parse.quote(query)}',
                'content': f'Latest news, announcements, and updates about {query}. Stay informed with breaking news and recent developments in the field.',
                'score': 0.82,
                'published_date': '2024-10-25'
            }
        ]
        
        response_data = {
            'query': query,
            'search_depth': search_depth,
            'topic': topic,
            'results_count': max_results,
            'results': demo_results[:max_results],
            'note': 'Demo mode - Configure Tavily API key for real search results'
        }
        
        # Add demo answer if requested
        if include_answer:
            response_data['answer'] = f"Based on the search results for '{query}', here is a comprehensive summary: This is a demo AI-generated answer that would provide a concise overview of the topic, synthesizing information from multiple sources. In production, Tavily's AI would analyze all results and provide an intelligent summary."
        
        # Add demo images if requested
        if include_images:
            response_data['images'] = [
                {
                    'url': f'https://images.example.com/{urllib.parse.quote(query)}/1.jpg',
                    'description': f'Illustration related to {query}'
                },
                {
                    'url': f'https://images.example.com/{urllib.parse.quote(query)}/2.jpg',
                    'description': f'Diagram showing {query} concepts'
                }
            ]
        
        return response_data
