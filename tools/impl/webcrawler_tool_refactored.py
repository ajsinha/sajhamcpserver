"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Web Crawler MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from html.parser import HTMLParser
from collections import deque
from tools.base_mcp_tool import BaseMCPTool


class LinkExtractor(HTMLParser):
    """HTML parser to extract links and metadata"""
    
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []
        self.title = None
        self.meta_description = None
        self.meta_keywords = None
        self.headings = {'h1': [], 'h2': [], 'h3': []}
        self.current_tag = None
        self.current_data = []
    
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        
        if tag == 'a' and 'href' in attrs_dict:
            self.links.append(attrs_dict['href'])
        
        elif tag == 'img' and 'src' in attrs_dict:
            self.images.append({
                'src': attrs_dict['src'],
                'alt': attrs_dict.get('alt', ''),
                'title': attrs_dict.get('title', '')
            })
        
        elif tag == 'meta':
            name = attrs_dict.get('name', '').lower()
            content = attrs_dict.get('content', '')
            
            if name == 'description':
                self.meta_description = content
            elif name == 'keywords':
                self.meta_keywords = content
        
        elif tag in ['h1', 'h2', 'h3']:
            self.current_tag = tag
            self.current_data = []
        
        elif tag == 'title':
            self.current_tag = 'title'
            self.current_data = []
    
    def handle_data(self, data):
        if self.current_tag:
            self.current_data.append(data)
    
    def handle_endtag(self, tag):
        if tag == self.current_tag:
            text = ''.join(self.current_data).strip()
            if text:
                if tag == 'title':
                    self.title = text
                elif tag in self.headings:
                    self.headings[tag].append(text)
            self.current_tag = None
            self.current_data = []


class WebCrawlerBaseTool(BaseMCPTool):
    """
    Base class for Web Crawler tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Web Crawler base tool"""
        super().__init__(config)
        
        self.max_depth = 3  # Maximum crawl depth
        self.default_timeout = 10
        self.default_delay = 1.0  # Delay between requests in seconds
        self.user_agent = 'Mozilla/5.0 (compatible; WebCrawlerTool/1.0)'
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format"""
        try:
            result = urllib.parse.urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _fetch_url(self, url: str, timeout: int = None) -> tuple:
        """Fetch URL content"""
        if timeout is None:
            timeout = self.default_timeout
        
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode('utf-8', errors='ignore')
            content_type = response.headers.get('Content-Type', '')
            status_code = response.status
            return content, content_type, status_code
    
    def _normalize_url(self, url: str, base_url: str) -> Optional[str]:
        """Normalize and resolve relative URLs"""
        try:
            # Remove fragments
            url = url.split('#')[0]
            
            # Handle relative URLs
            if not url.startswith(('http://', 'https://')):
                url = urllib.parse.urljoin(base_url, url)
            
            # Validate
            if self._is_valid_url(url):
                return url
            return None
        except:
            return None
    
    def _is_same_domain(self, url1: str, url2: str) -> bool:
        """Check if two URLs are from the same domain"""
        try:
            domain1 = urllib.parse.urlparse(url1).netloc
            domain2 = urllib.parse.urlparse(url2).netloc
            return domain1 == domain2
        except:
            return False


class CrawlURLTool(WebCrawlerBaseTool):
    """Tool to crawl a website starting from a URL"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'crawl_url',
            'description': 'Recursively crawl a website starting from a URL, following links up to specified depth',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Starting URL to crawl (e.g., 'https://example.com')"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum crawl depth (0-3). 0 = only start page, 1 = start + direct links, etc.",
                    "default": 1,
                    "minimum": 0,
                    "maximum": 3
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of pages to crawl",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                },
                "follow_external": {
                    "type": "boolean",
                    "description": "Follow links to external domains",
                    "default": false
                },
                "respect_robots": {
                    "type": "boolean",
                    "description": "Respect robots.txt rules",
                    "default": true
                },
                "extract_images": {
                    "type": "boolean",
                    "description": "Extract image URLs from pages",
                    "default": true
                },
                "extract_text": {
                    "type": "boolean",
                    "description": "Extract text content previews",
                    "default": true
                },
                "delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds (to be polite)",
                    "default": 1.0,
                    "minimum": 0.5,
                    "maximum": 5.0
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds",
                    "default": 10,
                    "minimum": 5,
                    "maximum": 30
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "start_url": {
                    "type": "string",
                    "description": "Starting URL"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum depth crawled"
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages limit"
                },
                "pages_crawled": {
                    "type": "integer",
                    "description": "Actual number of pages crawled"
                },
                "pages": {
                    "type": "array",
                    "description": "Information about each crawled page",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "depth": {"type": "integer"},
                            "status_code": {"type": "integer"},
                            "title": {"type": "string"},
                            "meta_description": {"type": "string"},
                            "link_count": {"type": "integer"},
                            "image_count": {"type": "integer"},
                            "text_preview": {"type": "string"},
                            "crawled_at": {"type": "string"}
                        }
                    }
                },
                "crawl_duration": {
                    "type": "number",
                    "description": "Total crawl time in seconds"
                },
                "completed_at": {
                    "type": "string",
                    "description": "Timestamp when crawl completed"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute crawl URL operation"""
        url = arguments.get('url')
        max_depth = min(arguments.get('max_depth', 1), self.max_depth)
        max_pages = min(arguments.get('max_pages', 10), 100)
        follow_external = arguments.get('follow_external', False)
        respect_robots = arguments.get('respect_robots', True)
        extract_images = arguments.get('extract_images', True)
        extract_text = arguments.get('extract_text', True)
        delay = arguments.get('delay', self.default_delay)
        timeout = arguments.get('timeout', self.default_timeout)
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        # Check robots.txt if required
        if respect_robots:
            robots_check = self._check_robots_txt(url)
            if not robots_check['can_fetch']:
                return {
                    'error': 'Crawling not allowed by robots.txt',
                    'robots_check': robots_check,
                    'url': url
                }
        
        visited: Set[str] = set()
        to_visit = deque([(url, 0)])  # (url, depth)
        pages = []
        
        start_time = time.time()
        
        while to_visit and len(visited) < max_pages:
            if len(visited) >= max_pages:
                break
            
            current_url, depth = to_visit.popleft()
            
            # Skip if already visited
            if current_url in visited:
                continue
            
            # Skip if depth exceeded
            if depth > max_depth:
                continue
            
            # Skip external links if not following
            if not follow_external and not self._is_same_domain(url, current_url):
                continue
            
            try:
                # Respect delay between requests
                if visited:  # Don't delay on first request
                    time.sleep(delay)
                
                # Fetch page
                content, content_type, status_code = self._fetch_url(current_url, timeout)
                
                # Parse page
                parser = LinkExtractor()
                parser.feed(content)
                
                # Store page info
                page_info = {
                    'url': current_url,
                    'depth': depth,
                    'status_code': status_code,
                    'content_type': content_type,
                    'title': parser.title,
                    'meta_description': parser.meta_description,
                    'link_count': len(parser.links),
                    'crawled_at': datetime.now().isoformat()
                }
                
                if extract_images:
                    page_info['image_count'] = len(parser.images)
                    page_info['images'] = [self._normalize_url(img['src'], current_url) for img in parser.images[:10]]
                
                if extract_text:
                    text = re.sub(r'<[^>]+>', '', content)
                    text = re.sub(r'\s+', ' ', text).strip()
                    page_info['text_preview'] = text[:500]
                
                pages.append(page_info)
                visited.add(current_url)
                
                # Add links to queue if within depth limit
                if depth < max_depth:
                    for link in parser.links:
                        normalized = self._normalize_url(link, current_url)
                        if normalized and normalized not in visited:
                            # Check domain restriction
                            if follow_external or self._is_same_domain(url, normalized):
                                to_visit.append((normalized, depth + 1))
                
            except Exception as e:
                self.logger.warning(f"Error crawling {current_url}: {e}")
                pages.append({
                    'url': current_url,
                    'depth': depth,
                    'error': str(e),
                    'crawled_at': datetime.now().isoformat()
                })
                visited.add(current_url)
        
        end_time = time.time()
        
        return {
            'start_url': url,
            'max_depth': max_depth,
            'max_pages': max_pages,
            'pages_crawled': len(visited),
            'pages': pages,
            'follow_external': follow_external,
            'respect_robots': respect_robots,
            'crawl_duration': round(end_time - start_time, 2),
            'completed_at': datetime.now().isoformat()
        }
    
    def _check_robots_txt(self, url: str) -> Dict:
        """Check robots.txt for a URL"""
        try:
            parsed = urllib.parse.urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            
            can_fetch = rp.can_fetch(self.user_agent, url)
            
            return {
                'robots_url': robots_url,
                'can_fetch': can_fetch,
                'user_agent': self.user_agent,
                'checked_at': datetime.now().isoformat()
            }
        except Exception as e:
            # If robots.txt doesn't exist or can't be read, allow crawling
            return {
                'can_fetch': True,
                'note': 'robots.txt not found or unreadable, proceeding with crawl',
                'error': str(e)
            }


class ExtractLinksTool(WebCrawlerBaseTool):
    """Tool to extract all links from a web page"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'extract_links',
            'description': 'Extract all hyperlinks from a web page',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the page to extract links from"
                },
                "normalize": {
                    "type": "boolean",
                    "description": "Convert relative URLs to absolute URLs",
                    "default": true
                },
                "internal_only": {
                    "type": "boolean",
                    "description": "Return only internal (same-domain) links",
                    "default": false
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Source URL"
                },
                "links": {
                    "type": "array",
                    "description": "Extracted hyperlinks",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "is_internal": {"type": "boolean"},
                            "is_absolute": {"type": "boolean"}
                        }
                    }
                },
                "link_count": {
                    "type": "integer",
                    "description": "Total number of links found"
                },
                "internal_count": {
                    "type": "integer",
                    "description": "Number of internal links"
                },
                "external_count": {
                    "type": "integer",
                    "description": "Number of external links"
                },
                "extracted_at": {
                    "type": "string",
                    "description": "Timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute extract links operation"""
        url = arguments.get('url')
        normalize = arguments.get('normalize', True)
        internal_only = arguments.get('internal_only', False)
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        links = []
        internal_count = 0
        external_count = 0
        
        for link in parser.links:
            if normalize:
                normalized = self._normalize_url(link, url)
                if not normalized:
                    continue
                link_url = normalized
                is_absolute = True
            else:
                link_url = link
                is_absolute = link.startswith(('http://', 'https://'))
            
            is_internal = self._is_same_domain(url, link_url) if is_absolute else True
            
            if internal_only and not is_internal:
                continue
            
            links.append({
                'url': link_url,
                'is_internal': is_internal,
                'is_absolute': is_absolute
            })
            
            if is_internal:
                internal_count += 1
            else:
                external_count += 1
        
        return {
            'url': url,
            'links': links,
            'link_count': len(links),
            'internal_count': internal_count,
            'external_count': external_count,
            'extracted_at': datetime.now().isoformat()
        }


class ExtractContentTool(WebCrawlerBaseTool):
    """Tool to extract structured content from a web page"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'extract_content',
            'description': 'Extract structured content including text, images, and headings from a web page',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the page to extract content from"
                },
                "extract_images": {
                    "type": "boolean",
                    "description": "Extract image URLs and metadata",
                    "default": true
                },
                "extract_text": {
                    "type": "boolean",
                    "description": "Extract text content",
                    "default": true
                },
                "text_max_length": {
                    "type": "integer",
                    "description": "Maximum text length to extract",
                    "default": 5000,
                    "minimum": 100,
                    "maximum": 50000
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Source URL"
                },
                "title": {
                    "type": "string",
                    "description": "Page title"
                },
                "text_content": {
                    "type": "string",
                    "description": "Extracted text content"
                },
                "images": {
                    "type": "array",
                    "description": "Image URLs with metadata",
                    "items": {
                        "type": "object",
                        "properties": {
                            "src": {"type": "string"},
                            "alt": {"type": "string"},
                            "title": {"type": "string"}
                        }
                    }
                },
                "headings": {
                    "type": "object",
                    "description": "Page headings organized by level",
                    "properties": {
                        "h1": {"type": "array", "items": {"type": "string"}},
                        "h2": {"type": "array", "items": {"type": "string"}},
                        "h3": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "content_length": {
                    "type": "integer",
                    "description": "Total content length in characters"
                },
                "extracted_at": {
                    "type": "string",
                    "description": "Timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute extract content operation"""
        url = arguments.get('url')
        extract_images = arguments.get('extract_images', True)
        extract_text = arguments.get('extract_text', True)
        text_max_length = arguments.get('text_max_length', 5000)
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        result = {
            'url': url,
            'status_code': status_code,
            'title': parser.title,
            'headings': parser.headings,
            'extracted_at': datetime.now().isoformat()
        }
        
        if extract_text:
            # Strip HTML tags
            text = re.sub(r'<[^>]+>', '', content)
            # Normalize whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            # Limit length
            if len(text) > text_max_length:
                text = text[:text_max_length] + '...'
            result['text_content'] = text
            result['content_length'] = len(text)
        
        if extract_images:
            # Normalize image URLs
            images = []
            for img in parser.images:
                normalized_src = self._normalize_url(img['src'], url)
                if normalized_src:
                    images.append({
                        'src': normalized_src,
                        'alt': img.get('alt', ''),
                        'title': img.get('title', '')
                    })
            result['images'] = images
            result['image_count'] = len(images)
        
        return result


class ExtractMetadataTool(WebCrawlerBaseTool):
    """Tool to extract page metadata"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'extract_metadata',
            'description': 'Extract metadata including title, description, keywords, and headings from a web page',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the page to extract metadata from"
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Page URL"
                },
                "status_code": {
                    "type": "integer",
                    "description": "HTTP status code"
                },
                "content_type": {
                    "type": "string",
                    "description": "Content-Type header"
                },
                "title": {
                    "type": "string",
                    "description": "Page title"
                },
                "meta_description": {
                    "type": "string",
                    "description": "Meta description tag content"
                },
                "meta_keywords": {
                    "type": "string",
                    "description": "Meta keywords tag content"
                },
                "headings": {
                    "type": "object",
                    "description": "Page headings by level",
                    "properties": {
                        "h1": {"type": "array"},
                        "h2": {"type": "array"},
                        "h3": {"type": "array"}
                    }
                },
                "content_length": {
                    "type": "integer",
                    "description": "Content length in bytes"
                },
                "extracted_at": {
                    "type": "string",
                    "description": "Extraction timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute extract metadata operation"""
        url = arguments.get('url')
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        return {
            'url': url,
            'status_code': status_code,
            'content_type': content_type,
            'title': parser.title,
            'meta_description': parser.meta_description,
            'meta_keywords': parser.meta_keywords,
            'headings': parser.headings,
            'content_length': len(content),
            'extracted_at': datetime.now().isoformat()
        }


class CrawlSitemapTool(WebCrawlerBaseTool):
    """Tool to crawl and extract URLs from sitemap.xml"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'crawl_sitemap',
            'description': 'Crawl and extract URLs from sitemap.xml file',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Base URL or direct sitemap URL (e.g., 'https://example.com' or 'https://example.com/sitemap.xml')"
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "sitemap_url": {
                    "type": "string",
                    "description": "Sitemap URL that was successfully crawled"
                },
                "status_code": {
                    "type": "integer",
                    "description": "HTTP status code"
                },
                "url_count": {
                    "type": "integer",
                    "description": "Number of URLs found in sitemap"
                },
                "urls": {
                    "type": "array",
                    "description": "URLs extracted from sitemap",
                    "items": {
                        "type": "string"
                    }
                },
                "retrieved_at": {
                    "type": "string",
                    "description": "Retrieval timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute crawl sitemap operation"""
        url = arguments.get('url')
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        try:
            # Try common sitemap locations
            parsed = urllib.parse.urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            sitemap_urls = [
                url if url.endswith('sitemap.xml') else None,
                f"{base_url}/sitemap.xml",
                f"{base_url}/sitemap_index.xml",
                f"{base_url}/sitemap1.xml"
            ]
            
            sitemap_urls = [u for u in sitemap_urls if u]
            
            for sitemap_url in sitemap_urls:
                try:
                    content, content_type, status_code = self._fetch_url(sitemap_url)
                    
                    # Extract URLs from sitemap
                    urls = re.findall(r'<loc>(.*?)</loc>', content)
                    
                    if urls:
                        return {
                            'sitemap_url': sitemap_url,
                            'status_code': status_code,
                            'url_count': len(urls),
                            'urls': urls,
                            'retrieved_at': datetime.now().isoformat()
                        }
                except:
                    continue
            
            return {
                'error': 'No sitemap found',
                'attempted_urls': sitemap_urls,
                'base_url': base_url
            }
            
        except Exception as e:
            self.logger.error(f"Error crawling sitemap: {e}")
            return {
                'error': str(e),
                'url': url
            }


class CheckRobotsTxtTool(WebCrawlerBaseTool):
    """Tool to check robots.txt rules"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'check_robots_txt',
            'description': 'Check robots.txt file and determine if crawling is allowed',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to check (can be base domain or specific path)"
                },
                "user_agent": {
                    "type": "string",
                    "description": "User agent to check rules for (optional, defaults to tool's user agent)",
                    "default": "Mozilla/5.0 (compatible; WebCrawlerTool/1.0)"
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Checked URL"
                },
                "robots_url": {
                    "type": "string",
                    "description": "robots.txt URL"
                },
                "can_fetch": {
                    "type": "boolean",
                    "description": "Whether crawling is allowed"
                },
                "user_agent": {
                    "type": "string",
                    "description": "User agent checked"
                },
                "crawl_delay": {
                    "type": ["number", "null"],
                    "description": "Suggested crawl delay in seconds (if specified)"
                },
                "checked_at": {
                    "type": "string",
                    "description": "Check timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute check robots.txt operation"""
        url = arguments.get('url')
        user_agent = arguments.get('user_agent', self.user_agent)
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        try:
            parsed = urllib.parse.urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            
            can_fetch = rp.can_fetch(user_agent, url)
            crawl_delay = rp.crawl_delay(user_agent)
            
            return {
                'url': url,
                'robots_url': robots_url,
                'can_fetch': can_fetch,
                'user_agent': user_agent,
                'crawl_delay': crawl_delay,
                'checked_at': datetime.now().isoformat()
            }
        except Exception as e:
            # If robots.txt doesn't exist or can't be read, allow crawling
            return {
                'url': url,
                'can_fetch': True,
                'note': 'robots.txt not found or unreadable',
                'error': str(e),
                'checked_at': datetime.now().isoformat()
            }


class GetPageInfoTool(WebCrawlerBaseTool):
    """Tool to get comprehensive page information"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'get_page_info',
            'description': 'Get comprehensive information about a web page including metadata, structure, and statistics',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the page to analyze"
                }
            },
            "required": ["url"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Page URL"
                },
                "status_code": {
                    "type": "integer",
                    "description": "HTTP status code"
                },
                "content_type": {
                    "type": "string",
                    "description": "Content type"
                },
                "title": {
                    "type": "string",
                    "description": "Page title"
                },
                "meta_description": {
                    "type": "string",
                    "description": "Meta description"
                },
                "meta_keywords": {
                    "type": "string",
                    "description": "Meta keywords"
                },
                "headings": {
                    "type": "object",
                    "description": "Heading statistics and samples",
                    "properties": {
                        "h1_count": {"type": "integer"},
                        "h2_count": {"type": "integer"},
                        "h3_count": {"type": "integer"},
                        "h1": {"type": "array", "items": {"type": "string"}},
                        "h2": {"type": "array", "items": {"type": "string"}},
                        "h3": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "link_count": {
                    "type": "integer",
                    "description": "Total number of links"
                },
                "image_count": {
                    "type": "integer",
                    "description": "Total number of images"
                },
                "content_length": {
                    "type": "integer",
                    "description": "Content length in characters"
                },
                "retrieved_at": {
                    "type": "string",
                    "description": "Retrieval timestamp"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get page info operation"""
        url = arguments.get('url')
        
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        # Count different elements
        link_count = len(parser.links)
        image_count = len(parser.images)
        
        return {
            'url': url,
            'status_code': status_code,
            'content_type': content_type,
            'title': parser.title,
            'meta_description': parser.meta_description,
            'meta_keywords': parser.meta_keywords,
            'headings': {
                'h1_count': len(parser.headings['h1']),
                'h2_count': len(parser.headings['h2']),
                'h3_count': len(parser.headings['h3']),
                'h1': parser.headings['h1'][:5],  # First 5
                'h2': parser.headings['h2'][:5],
                'h3': parser.headings['h3'][:5]
            },
            'link_count': link_count,
            'image_count': image_count,
            'content_length': len(content),
            'retrieved_at': datetime.now().isoformat()
        }


# Tool registry for easy access
WEB_CRAWLER_TOOLS = {
    'crawl_url': CrawlURLTool,
    'extract_links': ExtractLinksTool,
    'extract_content': ExtractContentTool,
    'extract_metadata': ExtractMetadataTool,
    'crawl_sitemap': CrawlSitemapTool,
    'check_robots_txt': CheckRobotsTxtTool,
    'get_page_info': GetPageInfoTool
}
