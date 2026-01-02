"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tavily Search MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool


class TavilyBaseTool(BaseMCPTool):
    """
    Base class for Tavily search tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Tavily base tool"""
        super().__init__(config)
        
        # Tavily API endpoint
        self.api_url = "https://api.tavily.com/search"
        
        # API key (required for production use)
        self.api_key = config.get('api_key', '') if config else ''
        
        # Demo mode if no API key
        self.demo_mode = not self.api_key
    
    def _search(
        self, 
        query: str, 
        search_depth: str,
        topic: str,
        max_results: int,
        include_answer: bool,
        include_raw_content: bool,
        include_images: bool,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None
    ) -> Dict:
        """
        Perform Tavily search
        
        Args:
            query: Search query
            search_depth: Depth of search ('basic' or 'advanced')
            topic: Search category
            max_results: Maximum results to return
            include_answer: Include AI-generated answer
            include_raw_content: Include raw HTML content
            include_images: Include relevant images
            include_domains: Domains to specifically include
            exclude_domains: Domains to exclude
            
        Returns:
            Search results
        """
        # If in demo mode, return mock data
        if self.demo_mode:
            return self._get_demo_results(query, search_depth, topic, max_results, 
                                        include_answer, include_images)
        
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
    
    def _get_demo_results(
        self, 
        query: str, 
        search_depth: str,
        topic: str,
        max_results: int,
        include_answer: bool,
        include_images: bool
    ) -> Dict:
        """
        Get demo/mock search results when API key is not configured
        
        Args:
            query: Search query
            search_depth: Search depth
            topic: Search topic
            max_results: Maximum results
            include_answer: Include AI answer
            include_images: Include images
            
        Returns:
            Mock search results
        """
        max_results = min(max_results, 5)
        
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


class TavilyWebSearchTool(TavilyBaseTool):
    """
    General web search tool using Tavily API
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'tavily_web_search',
            'description': 'Perform general web search using Tavily AI-powered search engine',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for web search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find web information"
                },
                "search_depth": {
                    "type": "string",
                    "description": "Depth of search - 'basic' for quick results, 'advanced' for comprehensive search",
                    "enum": ["basic", "advanced"],
                    "default": "basic"
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
                "include_images": {
                    "type": "boolean",
                    "description": "Include relevant images in results",
                    "default": False
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for web search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query that was executed"
                },
                "search_depth": {
                    "type": "string",
                    "description": "Depth of search performed"
                },
                "topic": {
                    "type": "string",
                    "description": "Search topic category"
                },
                "results_count": {
                    "type": "integer",
                    "description": "Number of results returned"
                },
                "results": {
                    "type": "array",
                    "description": "Search results",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Title of the result"
                            },
                            "url": {
                                "type": "string",
                                "description": "URL of the result"
                            },
                            "content": {
                                "type": "string",
                                "description": "Excerpt or summary of the content"
                            },
                            "score": {
                                "type": "number",
                                "description": "Relevance score (0-1)"
                            },
                            "published_date": {
                                "type": "string",
                                "description": "Publication date if available"
                            }
                        }
                    }
                },
                "answer": {
                    "type": "string",
                    "description": "AI-generated answer summary (if requested)"
                },
                "images": {
                    "type": "array",
                    "description": "Related images (if requested)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string"
                            },
                            "description": {
                                "type": "string"
                            }
                        }
                    }
                }
            },
            "required": ["query", "results_count", "results"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute web search"""
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        search_depth = arguments.get('search_depth', 'basic')
        max_results = arguments.get('max_results', 5)
        include_answer = arguments.get('include_answer', True)
        include_images = arguments.get('include_images', False)
        
        return self._search(
            query=query,
            search_depth=search_depth,
            topic='general',
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=False,
            include_images=include_images
        )


class TavilyNewsSearchTool(TavilyBaseTool):
    """
    News-specific search tool using Tavily API
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'tavily_news_search',
            'description': 'Search for recent news articles using Tavily with news-optimized results',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for news search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of news articles to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Include AI-generated news summary",
                    "default": True
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for news search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The news search query"
                },
                "results_count": {
                    "type": "integer",
                    "description": "Number of news articles returned"
                },
                "results": {
                    "type": "array",
                    "description": "News articles",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "News article title"
                            },
                            "url": {
                                "type": "string",
                                "description": "Article URL"
                            },
                            "content": {
                                "type": "string",
                                "description": "Article excerpt"
                            },
                            "score": {
                                "type": "number",
                                "description": "Relevance score"
                            },
                            "published_date": {
                                "type": "string",
                                "description": "Publication date"
                            }
                        }
                    }
                },
                "answer": {
                    "type": "string",
                    "description": "AI-generated news summary"
                }
            },
            "required": ["query", "results_count", "results"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute news search"""
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        max_results = arguments.get('max_results', 5)
        include_answer = arguments.get('include_answer', True)
        
        return self._search(
            query=query,
            search_depth='basic',
            topic='news',
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=False,
            include_images=False
        )


class TavilyResearchSearchTool(TavilyBaseTool):
    """
    Advanced research search tool using Tavily API with comprehensive results
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'tavily_research_search',
            'description': 'Perform comprehensive research search with advanced depth and analysis',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for research search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research query for comprehensive search"
                },
                "topic": {
                    "type": "string",
                    "description": "Research topic category",
                    "enum": ["general", "science", "finance"],
                    "default": "general"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (higher for research)",
                    "default": 10,
                    "minimum": 5,
                    "maximum": 20
                },
                "include_raw_content": {
                    "type": "boolean",
                    "description": "Include full HTML content for deeper analysis",
                    "default": False
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for research search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The research query"
                },
                "search_depth": {
                    "type": "string",
                    "description": "Search depth (always 'advanced' for research)"
                },
                "topic": {
                    "type": "string",
                    "description": "Research topic category"
                },
                "results_count": {
                    "type": "integer",
                    "description": "Number of research results"
                },
                "results": {
                    "type": "array",
                    "description": "Comprehensive research results",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string"
                            },
                            "url": {
                                "type": "string"
                            },
                            "content": {
                                "type": "string"
                            },
                            "score": {
                                "type": "number"
                            },
                            "published_date": {
                                "type": "string"
                            },
                            "raw_content": {
                                "type": "string",
                                "description": "Full HTML content (if requested)"
                            }
                        }
                    }
                },
                "answer": {
                    "type": "string",
                    "description": "AI-generated comprehensive research summary"
                }
            },
            "required": ["query", "results_count", "results", "answer"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute research search"""
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        topic = arguments.get('topic', 'general')
        max_results = arguments.get('max_results', 10)
        include_raw_content = arguments.get('include_raw_content', False)
        
        return self._search(
            query=query,
            search_depth='advanced',
            topic=topic,
            max_results=max_results,
            include_answer=True,
            include_raw_content=include_raw_content,
            include_images=False
        )


class TavilyDomainSearchTool(TavilyBaseTool):
    """
    Domain-specific search tool using Tavily API with domain filters
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'tavily_domain_search',
            'description': 'Search within specific domains or exclude domains using Tavily',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for domain search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to specifically search within (e.g., ['github.com', 'stackoverflow.com'])"
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to exclude from search"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "Include AI-generated answer",
                    "default": True
                }
            },
            "required": ["query"],
            "oneOf": [
                {"required": ["include_domains"]},
                {"required": ["exclude_domains"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for domain search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "included_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Domains that were included in search"
                },
                "excluded_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Domains that were excluded from search"
                },
                "results_count": {
                    "type": "integer",
                    "description": "Number of results"
                },
                "results": {
                    "type": "array",
                    "description": "Search results from specified domains",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string"
                            },
                            "url": {
                                "type": "string"
                            },
                            "content": {
                                "type": "string"
                            },
                            "score": {
                                "type": "number"
                            }
                        }
                    }
                },
                "answer": {
                    "type": "string",
                    "description": "AI-generated answer"
                }
            },
            "required": ["query", "results_count", "results"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute domain-filtered search"""
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        include_domains = arguments.get('include_domains', [])
        exclude_domains = arguments.get('exclude_domains', [])
        max_results = arguments.get('max_results', 5)
        include_answer = arguments.get('include_answer', True)
        
        if not include_domains and not exclude_domains:
            raise ValueError("Either 'include_domains' or 'exclude_domains' must be specified")
        
        result = self._search(
            query=query,
            search_depth='basic',
            topic='general',
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=False,
            include_images=False,
            include_domains=include_domains if include_domains else None,
            exclude_domains=exclude_domains if exclude_domains else None
        )
        
        # Add domain filter info to result
        if include_domains:
            result['included_domains'] = include_domains
        if exclude_domains:
            result['excluded_domains'] = exclude_domains
        
        return result


# Tool registry for easy access
TAVILY_TOOLS = {
    'tavily_web_search': TavilyWebSearchTool,
    'tavily_news_search': TavilyNewsSearchTool,
    'tavily_research_search': TavilyResearchSearchTool,
    'tavily_domain_search': TavilyDomainSearchTool
}
