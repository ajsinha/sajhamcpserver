"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Web Crawler MCP Tool Implementation
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


class WebCrawlerTool(BaseMCPTool):
    """
    Web Crawler tool for crawling websites and extracting content
    Maximum depth: 3 levels
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Web Crawler tool"""
        default_config = {
            'name': 'webcrawler',
            'description': 'Crawl websites and extract content with configurable depth',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        self.max_depth = 3  # Maximum crawl depth
        self.default_timeout = 10
        self.default_delay = 1.0  # Delay between requests in seconds
        self.user_agent = 'Mozilla/5.0 (compatible; WebCrawlerTool/1.0)'
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Web Crawler tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "crawl_url",
                        "extract_links",
                        "extract_content",
                        "extract_metadata",
                        "crawl_sitemap",
                        "check_robots_txt",
                        "get_page_info"
                    ]
                },
                "url": {
                    "type": "string",
                    "description": "URL to crawl or analyze"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum crawl depth (0-3)",
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
                    "description": "Follow external links",
                    "default": False
                },
                "respect_robots": {
                    "type": "boolean",
                    "description": "Respect robots.txt rules",
                    "default": True
                },
                "extract_images": {
                    "type": "boolean",
                    "description": "Extract image URLs",
                    "default": True
                },
                "extract_text": {
                    "type": "boolean",
                    "description": "Extract text content",
                    "default": True
                },
                "delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
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
            "required": ["action", "url"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Web Crawler tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Crawled data or extracted content
        """
        action = arguments.get('action')
        url = arguments.get('url')
        
        if not url:
            raise ValueError("'url' parameter is required")
        
        # Validate URL
        if not self._is_valid_url(url):
            raise ValueError(f"Invalid URL: {url}")
        
        if action == 'crawl_url':
            max_depth = min(arguments.get('max_depth', 1), self.max_depth)
            max_pages = min(arguments.get('max_pages', 10), 100)
            follow_external = arguments.get('follow_external', False)
            respect_robots = arguments.get('respect_robots', True)
            extract_images = arguments.get('extract_images', True)
            extract_text = arguments.get('extract_text', True)
            delay = arguments.get('delay', self.default_delay)
            timeout = arguments.get('timeout', self.default_timeout)
            
            return self._crawl_url(
                url, max_depth, max_pages, follow_external,
                respect_robots, extract_images, extract_text, delay, timeout
            )
            
        elif action == 'extract_links':
            return self._extract_links(url)
            
        elif action == 'extract_content':
            extract_images = arguments.get('extract_images', True)
            extract_text = arguments.get('extract_text', True)
            
            return self._extract_content(url, extract_images, extract_text)
            
        elif action == 'extract_metadata':
            return self._extract_metadata(url)
            
        elif action == 'crawl_sitemap':
            return self._crawl_sitemap(url)
            
        elif action == 'check_robots_txt':
            return self._check_robots_txt(url)
            
        elif action == 'get_page_info':
            return self._get_page_info(url)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _is_valid_url(self, url: str) -> bool:
        """Validate URL format"""
        try:
            result = urllib.parse.urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except:
            return False
    
    def _normalize_url(self, url: str, base_url: str) -> Optional[str]:
        """Normalize and resolve relative URLs"""
        try:
            # Handle relative URLs
            if not url.startswith(('http://', 'https://', '//')):
                url = urllib.parse.urljoin(base_url, url)
            
            # Parse URL
            parsed = urllib.parse.urlparse(url)
            
            # Remove fragment
            url = urllib.parse.urlunparse((
                parsed.scheme, parsed.netloc, parsed.path,
                parsed.params, parsed.query, ''
            ))
            
            return url if self._is_valid_url(url) else None
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
    
    def _fetch_url(self, url: str, timeout: int = None) -> tuple:
        """
        Fetch URL content
        
        Returns:
            Tuple of (content, content_type, status_code)
        """
        if timeout is None:
            timeout = self.default_timeout
        
        try:
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode('utf-8', errors='ignore')
                content_type = response.headers.get('Content-Type', '')
                status_code = response.status
                
                return content, content_type, status_code
                
        except urllib.error.HTTPError as e:
            self.logger.error(f"HTTP error fetching {url}: {e.code}")
            raise ValueError(f"HTTP {e.code} error fetching URL")
        except urllib.error.URLError as e:
            self.logger.error(f"URL error fetching {url}: {e}")
            raise ValueError(f"Failed to fetch URL: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            raise ValueError(f"Failed to fetch URL: {str(e)}")
    
    def _check_robots_txt(self, url: str) -> Dict:
        """
        Check robots.txt for the domain
        
        Returns:
            Robots.txt information
        """
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
                'url': url,
                'checked_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.warning(f"Could not check robots.txt: {e}")
            return {
                'robots_url': None,
                'can_fetch': True,  # Default to allowing if can't check
                'error': str(e),
                'url': url,
                'checked_at': datetime.now().isoformat()
            }
    
    def _extract_links(self, url: str) -> Dict:
        """
        Extract all links from a URL
        
        Returns:
            Dictionary with extracted links
        """
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        # Normalize links
        internal_links = []
        external_links = []
        
        for link in parser.links:
            normalized = self._normalize_url(link, url)
            if normalized:
                if self._is_same_domain(url, normalized):
                    internal_links.append(normalized)
                else:
                    external_links.append(normalized)
        
        # Remove duplicates
        internal_links = list(set(internal_links))
        external_links = list(set(external_links))
        
        return {
            'url': url,
            'status_code': status_code,
            'internal_links': internal_links,
            'external_links': external_links,
            'internal_count': len(internal_links),
            'external_count': len(external_links),
            'total_links': len(internal_links) + len(external_links),
            'extracted_at': datetime.now().isoformat()
        }
    
    def _extract_content(
        self,
        url: str,
        extract_images: bool = True,
        extract_text: bool = True
    ) -> Dict:
        """
        Extract content from a URL
        
        Returns:
            Dictionary with extracted content
        """
        content, content_type, status_code = self._fetch_url(url)
        
        parser = LinkExtractor()
        parser.feed(content)
        
        result = {
            'url': url,
            'status_code': status_code,
            'content_type': content_type,
            'title': parser.title,
            'headings': parser.headings,
            'extracted_at': datetime.now().isoformat()
        }
        
        if extract_images:
            # Normalize image URLs
            normalized_images = []
            for img in parser.images:
                img_copy = img.copy()
                img_copy['src'] = self._normalize_url(img['src'], url)
                normalized_images.append(img_copy)
            
            result['images'] = normalized_images
            result['image_count'] = len(normalized_images)
        
        if extract_text:
            # Extract plain text (simple implementation)
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', content)
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            result['text_content'] = text[:5000]  # Limit to first 5000 chars
            result['text_length'] = len(text)
        
        return result
    
    def _extract_metadata(self, url: str) -> Dict:
        """
        Extract metadata from a URL
        
        Returns:
            Dictionary with page metadata
        """
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
    
    def _get_page_info(self, url: str) -> Dict:
        """
        Get comprehensive page information
        
        Returns:
            Dictionary with page information
        """
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
    
    def _crawl_url(
        self,
        start_url: str,
        max_depth: int,
        max_pages: int,
        follow_external: bool,
        respect_robots: bool,
        extract_images: bool,
        extract_text: bool,
        delay: float,
        timeout: int
    ) -> Dict:
        """
        Crawl a URL and its links up to max_depth
        
        Returns:
            Dictionary with crawl results
        """
        # Check robots.txt if required
        if respect_robots:
            robots_check = self._check_robots_txt(start_url)
            if not robots_check['can_fetch']:
                return {
                    'error': 'Crawling not allowed by robots.txt',
                    'robots_check': robots_check,
                    'url': start_url
                }
        
        visited: Set[str] = set()
        to_visit = deque([(start_url, 0)])  # (url, depth)
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
            if not follow_external and not self._is_same_domain(start_url, current_url):
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
                            if follow_external or self._is_same_domain(start_url, normalized):
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
            'start_url': start_url,
            'max_depth': max_depth,
            'max_pages': max_pages,
            'pages_crawled': len(visited),
            'pages': pages,
            'follow_external': follow_external,
            'respect_robots': respect_robots,
            'crawl_duration': round(end_time - start_time, 2),
            'completed_at': datetime.now().isoformat()
        }
    
    def _crawl_sitemap(self, url: str) -> Dict:
        """
        Crawl sitemap.xml
        
        Returns:
            Dictionary with sitemap URLs
        """
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
