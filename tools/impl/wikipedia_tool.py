"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Wikipedia MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class WikipediaBaseTool(BaseMCPTool):
    """
    Base class for Wikipedia tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Wikipedia base tool"""
        super().__init__(config)
        
        # Wikipedia API endpoint
        self.api_base = "https://{lang}.wikipedia.org/w/api.php"
        self.default_lang = 'en'
    
    def _make_request(self, params: Dict, language: str = 'en') -> Dict:
        """
        Make API request to Wikipedia
        
        Args:
            params: Query parameters
            language: Wikipedia language code
            
        Returns:
            Parsed JSON response
        """
        url = self.api_base.format(lang=language)
        params['format'] = 'json'
        url += '?' + urllib.parse.urlencode(params)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; MCP-Tools/1.0)'
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Wikipedia resource not found")
            else:
                raise ValueError(f"Wikipedia API request failed: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Wikipedia API request failed: {str(e)}")


class WikiSearchTool(WikipediaBaseTool):
    """
    Tool to search Wikipedia articles by keyword
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wiki_search',
            'description': 'Search Wikipedia articles by keyword or phrase',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Wikipedia search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - topic, keyword, or phrase",
                    "minLength": 1,
                    "maxLength": 300
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of search results",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5
                },
                "language": {
                    "type": "string",
                    "description": "Wikipedia language edition (e.g., 'en', 'es', 'fr')",
                    "pattern": "^[a-z]{2,3}$",
                    "default": "en"
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for search results"""
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "result_count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "page_id": {"type": "integer"},
                            "snippet": {"type": "string"},
                            "url": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "word_count": {"type": "integer"}
                        }
                    }
                },
                "suggestion": {"type": ["string", "null"]},
                "last_updated": {"type": "string"}
            },
            "required": ["query", "results"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the search operation"""
        query = arguments['query']
        limit = arguments.get('limit', 5)
        language = arguments.get('language', 'en')
        
        # Search for pages
        search_params = {
            'action': 'query',
            'list': 'search',
            'srsearch': query,
            'srlimit': limit,
            'srprop': 'snippet|titlesnippet|timestamp|wordcount'
        }
        
        try:
            data = self._make_request(search_params, language)
            
            search_results = data.get('query', {}).get('search', [])
            
            results = []
            for item in search_results:
                page_id = item.get('pageid')
                title = item.get('title')
                
                results.append({
                    'title': title,
                    'page_id': page_id,
                    'snippet': item.get('snippet', '').replace('<span class="searchmatch">', '').replace('</span>', ''),
                    'url': f"https://{language}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                    'timestamp': item.get('timestamp'),
                    'word_count': item.get('wordcount', 0)
                })
            
            # Check for search suggestion
            suggestion = data.get('query', {}).get('searchinfo', {}).get('suggestion')
            
            return {
                'query': query,
                'language': language,
                'result_count': len(results),
                'results': results,
                'suggestion': suggestion,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to search Wikipedia for '{query}': {e}")
            raise ValueError(f"Failed to search Wikipedia: {str(e)}")


class WikiGetPageTool(WikipediaBaseTool):
    """
    Tool to retrieve complete Wikipedia article content
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wiki_get_page',
            'description': 'Retrieve the complete content of a Wikipedia article',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for page retrieval"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Article title or exact page name",
                    "minLength": 1,
                    "maxLength": 300
                },
                "page_id": {
                    "type": "integer",
                    "description": "Wikipedia page ID (alternative to title)",
                    "minimum": 1
                },
                "language": {
                    "type": "string",
                    "description": "Wikipedia language edition",
                    "pattern": "^[a-z]{2,3}$",
                    "default": "en"
                },
                "redirect": {
                    "type": "boolean",
                    "description": "Follow redirects to the target article",
                    "default": True
                },
                "include_images": {
                    "type": "boolean",
                    "description": "Include image URLs",
                    "default": True
                },
                "include_links": {
                    "type": "boolean",
                    "description": "Include internal and external links",
                    "default": True
                },
                "include_references": {
                    "type": "boolean",
                    "description": "Include article references",
                    "default": False
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for page content"""
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "page_id": {"type": "integer"},
                "url": {"type": "string"},
                "language": {"type": "string"},
                "content": {"type": "string"},
                "html_content": {"type": "string"},
                "summary": {"type": "string"},
                "sections": {"type": "array"},
                "images": {"type": "array"},
                "links": {"type": "object"},
                "references": {"type": "array"},
                "categories": {"type": "array"},
                "last_modified": {"type": "string"},
                "last_modified_by": {"type": "string"},
                "revision_id": {"type": "integer"},
                "word_count": {"type": "integer"},
                "last_updated": {"type": "string"}
            },
            "required": ["title", "page_id", "url", "content"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get page operation"""
        query = arguments.get('query')
        page_id = arguments.get('page_id')
        language = arguments.get('language', 'en')
        redirect = arguments.get('redirect', True)
        include_images = arguments.get('include_images', True)
        include_links = arguments.get('include_links', True)
        include_references = arguments.get('include_references', False)
        
        # Build page identifier
        if page_id:
            page_identifier = {'pageids': page_id}
        elif query:
            page_identifier = {'titles': query}
        else:
            raise ValueError("Either 'query' or 'page_id' must be provided")
        
        # Get page content
        params = {
            'action': 'query',
            'prop': 'extracts|info|revisions|categories|pageimages',
            'explaintext': True,
            'exsectionformat': 'plain',
            'inprop': 'url',
            'rvprop': 'timestamp|user|ids',
            'rvlimit': 1,
            'redirects': 1 if redirect else 0,
            'pithumbsize': 500,
            **page_identifier
        }
        
        try:
            data = self._make_request(params, language)
            
            pages = data.get('query', {}).get('pages', {})
            
            if not pages or '-1' in pages:
                raise ValueError(f"Page not found: {query or page_id}")
            
            page_data = list(pages.values())[0]
            
            page_id = page_data.get('pageid')
            title = page_data.get('title')
            content = page_data.get('extract', '')
            
            # Get summary (first paragraph)
            summary = content.split('\n\n')[0] if content else ''
            
            # Parse sections
            sections = []
            current_section = {'title': 'Introduction', 'level': 1, 'content': ''}
            for line in content.split('\n'):
                if line.startswith('=='):
                    if current_section['content']:
                        sections.append(current_section)
                    level = line.count('=') // 2
                    title_text = line.strip('= ')
                    current_section = {'title': title_text, 'level': level, 'content': ''}
                else:
                    current_section['content'] += line + '\n'
            if current_section['content']:
                sections.append(current_section)
            
            # Get images
            images = []
            if include_images:
                thumbnail = page_data.get('thumbnail')
                if thumbnail:
                    images.append({
                        'url': thumbnail.get('source'),
                        'title': title,
                        'description': None
                    })
            
            # Get links
            links = {'internal': [], 'external': []}
            if include_links:
                # Would need additional API calls to get links
                pass
            
            # Get categories
            categories = []
            for cat in page_data.get('categories', []):
                categories.append(cat.get('title', '').replace('Category:', ''))
            
            # Get revision info
            revisions = page_data.get('revisions', [])
            last_revision = revisions[0] if revisions else {}
            
            return {
                'title': title,
                'page_id': page_id,
                'url': page_data.get('fullurl', f"https://{language}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"),
                'language': language,
                'content': content,
                'html_content': '',  # Would need separate API call
                'summary': summary,
                'sections': sections,
                'images': images,
                'links': links,
                'references': [],  # Would need HTML parsing
                'categories': categories,
                'last_modified': last_revision.get('timestamp'),
                'last_modified_by': last_revision.get('user'),
                'revision_id': last_revision.get('revid'),
                'word_count': len(content.split()),
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get Wikipedia page: {e}")
            raise ValueError(f"Failed to get Wikipedia page: {str(e)}")


class WikiGetSummaryTool(WikipediaBaseTool):
    """
    Tool to retrieve concise Wikipedia article summaries
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wiki_get_summary',
            'description': 'Retrieve a concise summary of a Wikipedia article',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for summary retrieval"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Article title or page name",
                    "minLength": 1,
                    "maxLength": 300
                },
                "page_id": {
                    "type": "integer",
                    "description": "Wikipedia page ID",
                    "minimum": 1
                },
                "language": {
                    "type": "string",
                    "description": "Wikipedia language edition",
                    "pattern": "^[a-z]{2,3}$",
                    "default": "en"
                },
                "sentences": {
                    "type": "integer",
                    "description": "Number of sentences in summary",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 3
                },
                "redirect": {
                    "type": "boolean",
                    "description": "Follow redirects",
                    "default": True
                },
                "include_image": {
                    "type": "boolean",
                    "description": "Include main article image",
                    "default": True
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for summary"""
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "page_id": {"type": "integer"},
                "url": {"type": "string"},
                "language": {"type": "string"},
                "summary": {"type": "string"},
                "extract": {"type": "string"},
                "extract_html": {"type": "string"},
                "thumbnail": {"type": ["object", "null"]},
                "original_image": {"type": ["object", "null"]},
                "coordinates": {"type": ["object", "null"]},
                "last_modified": {"type": "string"},
                "description": {"type": "string"},
                "content_type": {"type": "string"},
                "last_updated": {"type": "string"}
            },
            "required": ["title", "page_id", "url", "summary"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get summary operation"""
        query = arguments.get('query')
        page_id = arguments.get('page_id')
        language = arguments.get('language', 'en')
        sentences = arguments.get('sentences', 3)
        redirect = arguments.get('redirect', True)
        include_image = arguments.get('include_image', True)
        
        # Build page identifier
        if page_id:
            page_identifier = {'pageids': page_id}
        elif query:
            page_identifier = {'titles': query}
        else:
            raise ValueError("Either 'query' or 'page_id' must be provided")
        
        # Get summary
        params = {
            'action': 'query',
            'prop': 'extracts|info|pageimages|description|coordinates',
            'exintro': True,
            'explaintext': True,
            'exsentences': sentences,
            'inprop': 'url',
            'redirects': 1 if redirect else 0,
            'pithumbsize': 500,
            **page_identifier
        }
        
        try:
            data = self._make_request(params, language)
            
            pages = data.get('query', {}).get('pages', {})
            
            if not pages or '-1' in pages:
                raise ValueError(f"Page not found: {query or page_id}")
            
            page_data = list(pages.values())[0]
            
            page_id = page_data.get('pageid')
            title = page_data.get('title')
            extract = page_data.get('extract', '')
            
            # Get thumbnail
            thumbnail = None
            original_image = None
            if include_image:
                thumb_data = page_data.get('thumbnail')
                if thumb_data:
                    thumbnail = {
                        'url': thumb_data.get('source'),
                        'width': thumb_data.get('width'),
                        'height': thumb_data.get('height')
                    }
                
                original_data = page_data.get('original')
                if original_data:
                    original_image = {
                        'url': original_data.get('source'),
                        'width': original_data.get('width'),
                        'height': original_data.get('height')
                    }
            
            # Get coordinates
            coordinates = None
            coords_data = page_data.get('coordinates')
            if coords_data and len(coords_data) > 0:
                coord = coords_data[0]
                coordinates = {
                    'latitude': coord.get('lat'),
                    'longitude': coord.get('lon')
                }
            
            return {
                'title': title,
                'page_id': page_id,
                'url': page_data.get('fullurl', f"https://{language}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"),
                'language': language,
                'summary': extract,
                'extract': extract,
                'extract_html': '',  # Would need separate API call
                'thumbnail': thumbnail,
                'original_image': original_image,
                'coordinates': coordinates,
                'last_modified': page_data.get('touched'),
                'description': page_data.get('description', ''),
                'content_type': page_data.get('contentmodel', 'standard'),
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get Wikipedia summary: {e}")
            raise ValueError(f"Failed to get Wikipedia summary: {str(e)}")


# Tool registry for easy access
WIKIPEDIA_TOOLS = {
    'wiki_search': WikiSearchTool,
    'wiki_get_page': WikiGetPageTool,
    'wiki_get_summary': WikiGetSummaryTool
}
