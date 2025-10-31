"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Base IR Web Scraper Abstract Class
"""

import re
import json
import logging
import urllib.request
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from html.parser import HTMLParser


class LinkExtractor(HTMLParser):
    """HTML parser to extract links from pages"""
    
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_link = None
    
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs_dict = dict(attrs)
            href = attrs_dict.get('href', '')
            if href:
                self.current_link = {
                    'href': href,
                    'text': '',
                    'attrs': attrs_dict
                }
    
    def handle_data(self, data):
        if self.current_link is not None:
            self.current_link['text'] += data.strip() + ' '
    
    def handle_endtag(self, tag):
        if tag == 'a' and self.current_link is not None:
            self.current_link['text'] = self.current_link['text'].strip()
            self.links.append(self.current_link)
            self.current_link = None


class BaseIRWebScraper(ABC):
    """
    Abstract base class for Investor Relations web scrapers
    Each company will have its own scraper implementation
    """
    
    def __init__(self, ticker: str):
        """
        Initialize the scraper
        
        Args:
            ticker: Stock ticker symbol
        """
        self.ticker = ticker.upper()
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.user_agent = "SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)"
        
        # Document type patterns (can be overridden by subclasses)
        self.document_patterns = {
            'annual_report': [
                r'annual\s+report',
                r'10-k',
                r'form\s+10-k',
                r'annual\s+filing'
            ],
            'quarterly_report': [
                r'quarterly\s+report',
                r'10-q',
                r'form\s+10-q',
                r'q[1-4]\s+\d{4}',
                r'[q|Q][1-4].*report'
            ],
            'earnings_presentation': [
                r'earnings',
                r'results',
                r'earnings\s+call',
                r'earnings\s+presentation',
                r'financial\s+results'
            ],
            'investor_presentation': [
                r'investor\s+presentation',
                r'corporate\s+presentation',
                r'investor\s+deck',
                r'company\s+presentation'
            ],
            'proxy_statement': [
                r'proxy',
                r'def\s+14a',
                r'proxy\s+statement'
            ],
            'press_release': [
                r'press\s+release',
                r'news\s+release',
                r'announcement'
            ],
            'esg_report': [
                r'esg',
                r'sustainability',
                r'corporate\s+responsibility',
                r'impact\s+report',
                r'environmental'
            ]
        }
    
    @abstractmethod
    def get_ir_page_url(self) -> str:
        """
        Get the main investor relations page URL
        
        Returns:
            IR page URL
        """
        pass
    
    @abstractmethod
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """
        Scrape documents from the IR page
        
        Args:
            document_type: Type of document to filter for
            year: Year to filter for
            
        Returns:
            List of document information dictionaries
        """
        pass
    
    def get_latest_earnings(self) -> Dict:
        """
        Get the latest earnings information
        
        Returns:
            Latest earnings information
        """
        # Default implementation - can be overridden
        docs = self.scrape_documents(document_type='earnings_presentation')
        if docs:
            return {
                'ticker': self.ticker,
                'latest_earnings': docs[0],
                'previous_earnings': docs[1:5] if len(docs) > 1 else []
            }
        return {
            'ticker': self.ticker,
            'latest_earnings': None,
            'message': 'No earnings documents found'
        }
    
    def get_annual_reports(self, year: Optional[int] = None, limit: int = 5) -> Dict:
        """
        Get annual reports
        
        Args:
            year: Optional year filter
            limit: Maximum number of reports
            
        Returns:
            Annual reports information
        """
        docs = self.scrape_documents(document_type='annual_report', year=year)
        return {
            'ticker': self.ticker,
            'count': len(docs[:limit]),
            'annual_reports': docs[:limit]
        }
    
    def get_presentations(self, limit: int = 10) -> Dict:
        """
        Get investor presentations
        
        Args:
            limit: Maximum number of presentations
            
        Returns:
            Presentations information
        """
        investor_pres = self.scrape_documents(document_type='investor_presentation')
        earnings_pres = self.scrape_documents(document_type='earnings_presentation')
        
        all_presentations = investor_pres + earnings_pres
        # Remove duplicates based on URL
        seen_urls = set()
        unique_presentations = []
        for pres in all_presentations:
            if pres['url'] not in seen_urls:
                seen_urls.add(pres['url'])
                unique_presentations.append(pres)
        
        return {
            'ticker': self.ticker,
            'count': len(unique_presentations[:limit]),
            'presentations': unique_presentations[:limit]
        }
    
    def get_all_resources(self) -> Dict:
        """
        Get all available IR resources
        
        Returns:
            All IR resources
        """
        return {
            'ticker': self.ticker,
            'ir_page': self.get_ir_page_url(),
            'annual_reports': self.get_annual_reports(limit=3),
            'latest_earnings': self.get_latest_earnings(),
            'presentations': self.get_presentations(limit=5)
        }
    
    # Helper methods
    
    def fetch_page(self, url: str, timeout: int = 15) -> str:
        """
        Fetch a web page
        
        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
            
        Returns:
            Page content as string
        """
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', self.user_agent)
            req.add_header('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode('utf-8', errors='ignore')
                return content
                
        except urllib.error.HTTPError as e:
            self.logger.error(f"HTTP Error fetching {url}: {e.code}")
            raise ValueError(f"Failed to fetch page: HTTP {e.code}")
        except urllib.error.URLError as e:
            self.logger.error(f"URL Error fetching {url}: {e.reason}")
            raise ValueError(f"Failed to fetch page: {e.reason}")
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            raise ValueError(f"Failed to fetch page: {str(e)}")
    
    def extract_links(self, html_content: str, base_url: str = None) -> List[Dict]:
        """
        Extract all links from HTML content
        
        Args:
            html_content: HTML content
            base_url: Base URL for relative links
            
        Returns:
            List of link dictionaries
        """
        parser = LinkExtractor()
        try:
            parser.feed(html_content)
        except:
            self.logger.warning("Error parsing HTML content")
            return []
        
        links = []
        for link in parser.links:
            href = link['href']
            
            # Convert relative URLs to absolute
            if base_url and not href.startswith(('http://', 'https://', '//')):
                if href.startswith('/'):
                    # Parse base URL to get scheme and netloc
                    parsed_base = urllib.parse.urlparse(base_url)
                    href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                else:
                    href = urllib.parse.urljoin(base_url, href)
            
            links.append({
                'url': href,
                'text': link['text'],
                'attrs': link.get('attrs', {})
            })
        
        return links
    
    def filter_links_by_pattern(self, links: List[Dict], patterns: List[str]) -> List[Dict]:
        """
        Filter links by regex patterns
        
        Args:
            links: List of link dictionaries
            patterns: List of regex patterns
            
        Returns:
            Filtered links
        """
        filtered = []
        for link in links:
            text = link['text'].lower()
            url = link['url'].lower()
            combined = f"{text} {url}"
            
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    filtered.append(link)
                    break
        
        return filtered
    
    def filter_by_document_type(self, links: List[Dict], document_type: str) -> List[Dict]:
        """
        Filter links by document type
        
        Args:
            links: List of link dictionaries
            document_type: Document type to filter for
            
        Returns:
            Filtered links
        """
        if document_type not in self.document_patterns:
            return links
        
        patterns = self.document_patterns[document_type]
        return self.filter_links_by_pattern(links, patterns)
    
    def filter_by_year(self, links: List[Dict], year: int) -> List[Dict]:
        """
        Filter links by year
        
        Args:
            links: List of link dictionaries
            year: Year to filter for
            
        Returns:
            Filtered links
        """
        year_pattern = str(year)
        filtered = []
        
        for link in links:
            text = link['text']
            url = link['url']
            combined = f"{text} {url}"
            
            if year_pattern in combined:
                filtered.append(link)
        
        return filtered
    
    def extract_year_from_text(self, text: str) -> Optional[int]:
        """
        Extract year from text
        
        Args:
            text: Text to search
            
        Returns:
            Year if found, None otherwise
        """
        # Look for 4-digit years
        match = re.search(r'\b(20[0-2][0-9])\b', text)
        if match:
            return int(match.group(1))
        return None
    
    def is_pdf_link(self, url: str) -> bool:
        """Check if URL points to a PDF"""
        return url.lower().endswith('.pdf')
    
    def is_document_link(self, url: str) -> bool:
        """Check if URL points to a document"""
        doc_extensions = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx']
        url_lower = url.lower()
        return any(url_lower.endswith(ext) for ext in doc_extensions)
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        # Remove fragments
        url = url.split('#')[0]
        # Remove trailing slashes
        url = url.rstrip('/')
        return url
    
    def create_document_dict(
        self,
        title: str,
        url: str,
        doc_type: Optional[str] = None,
        year: Optional[int] = None,
        date: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict:
        """
        Create a standardized document dictionary
        
        Args:
            title: Document title
            url: Document URL
            doc_type: Document type
            year: Document year
            date: Document date
            description: Document description
            
        Returns:
            Document dictionary
        """
        # Try to extract year if not provided
        if not year:
            year = self.extract_year_from_text(f"{title} {url}")
        
        return {
            'title': title,
            'url': self.normalize_url(url),
            'type': doc_type,
            'year': year,
            'date': date,
            'description': description,
            'ticker': self.ticker,
            'is_pdf': self.is_pdf_link(url)
        }
