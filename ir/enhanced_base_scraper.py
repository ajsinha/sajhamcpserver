"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Enhanced Base IR Web Scraper with Pattern Detection
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from html.parser import HTMLParser
from ir.http_client import EnhancedHTTPClient


class LinkExtractor(HTMLParser):
    """Enhanced HTML parser to extract links with more context"""
    
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_link = None
        self.current_context = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs_dict = dict(attrs)
            href = attrs_dict.get('href', '')
            if href:
                self.current_link = {
                    'href': href,
                    'text': '',
                    'attrs': attrs_dict,
                    'context': ' '.join(self.current_context[-3:])  # Last 3 elements of context
                }
        
        # Track context
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'span']:
            self.current_context.append('')
    
    def handle_data(self, data):
        data_stripped = data.strip()
        if data_stripped:
            if self.current_link is not None:
                self.current_link['text'] += data_stripped + ' '
            if self.current_context:
                self.current_context[-1] += data_stripped + ' '
    
    def handle_endtag(self, tag):
        if tag == 'a' and self.current_link is not None:
            self.current_link['text'] = self.current_link['text'].strip()
            self.links.append(self.current_link)
            self.current_link = None


class EnhancedBaseIRScraper(ABC):
    """
    Enhanced base class for IR web scrapers with:
    - Better bot detection avoidance
    - Pattern detection for common IR platforms
    - SEC EDGAR fallback
    - Improved error handling
    """
    
    def __init__(self, ticker: str, company_config: Optional[Dict] = None):
        """
        Initialize the scraper
        
        Args:
            ticker: Stock ticker symbol
            company_config: Optional company configuration
        """
        self.ticker = ticker.upper()
        self.logger = logging.getLogger(f"{self.__class__.__name__}.{self.ticker}")
        self.company_config = company_config or {}
        
        # Initialize HTTP client with bot avoidance
        self.http_client = EnhancedHTTPClient(
            min_delay=2.0,
            max_delay=5.0,
            max_retries=3,
            timeout=30
        )
        
        # Document type patterns (enhanced)
        self.document_patterns = {
            'annual_report': [
                r'annual\s+report',
                r'10-k',
                r'form\s+10-k',
                r'annual\s+filing',
                r'form\s+20-f',
                r'20-f',
                r'year\s+end\s+report'
            ],
            'quarterly_report': [
                r'quarterly\s+report',
                r'10-q',
                r'form\s+10-q',
                r'q[1-4]\s+\d{4}',
                r'[q|Q][1-4].*report',
                r'quarter(ly)?\s+result',
                r'q[1-4]\s+fy\s*\d{2,4}'
            ],
            'earnings_presentation': [
                r'earnings',
                r'results',
                r'earnings\s+call',
                r'earnings\s+presentation',
                r'financial\s+results',
                r'earnings\s+release',
                r'quarterly\s+earnings'
            ],
            'investor_presentation': [
                r'investor\s+presentation',
                r'corporate\s+presentation',
                r'investor\s+deck',
                r'company\s+presentation',
                r'investor\s+overview',
                r'analyst\s+day',
                r'investor\s+day'
            ],
            'proxy_statement': [
                r'proxy',
                r'def\s+14a',
                r'proxy\s+statement',
                r'def14a',
                r'notice\s+of\s+annual\s+meeting'
            ],
            'press_release': [
                r'press\s+release',
                r'news\s+release',
                r'announcement',
                r'media\s+release'
            ],
            'esg_report': [
                r'esg',
                r'sustainability',
                r'corporate\s+responsibility',
                r'impact\s+report',
                r'environmental',
                r'csr\s+report',
                r'social\s+responsibility'
            ]
        }
        
        # Common IR platform patterns
        self.platform_patterns = {
            'q4': [
                r'q4inc\.com',
                r'q4web\.com',
                r'q4ir\.com'
            ],
            'workiva': [
                r'workiva\.com',
                r'app\.workiva\.com'
            ],
            'irwebpage': [
                r'irwebpage\.com'
            ],
            'nasdaq': [
                r'nasdaq\.com/market-activity'
            ]
        }
    
    @abstractmethod
    def get_ir_page_url(self) -> str:
        """Get the main investor relations page URL"""
        pass
    
    @abstractmethod
    def scrape_documents(
        self,
        document_type: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """Scrape documents from the IR page"""
        pass
    
    def fetch_page(self, url: str) -> str:
        """
        Fetch a web page with bot detection avoidance
        
        Args:
            url: URL to fetch
            
        Returns:
            Page content as string
        """
        try:
            return self.http_client.fetch(url)
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            raise
    
    def extract_links(self, html_content: str, base_url: str = None) -> List[Dict]:
        """
        Extract all links from HTML content with context
        
        Args:
            html_content: HTML content
            base_url: Base URL for relative links
            
        Returns:
            List of link dictionaries with enhanced context
        """
        parser = LinkExtractor()
        try:
            parser.feed(html_content)
        except Exception as e:
            self.logger.warning(f"Error parsing HTML content: {e}")
            return []
        
        links = []
        for link in parser.links:
            href = link['href']
            
            # Skip empty links, javascript, mailto, tel
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            
            # Convert relative URLs to absolute
            if base_url:
                if not href.startswith(('http://', 'https://', '//')):
                    if href.startswith('/'):
                        # Parse base URL to get scheme and netloc
                        import urllib.parse
                        parsed_base = urllib.parse.urlparse(base_url)
                        href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                    else:
                        import urllib.parse
                        href = urllib.parse.urljoin(base_url, href)
            
            # Handle protocol-relative URLs
            if href.startswith('//'):
                href = 'https:' + href
            
            links.append({
                'url': href,
                'text': link['text'],
                'attrs': link.get('attrs', {}),
                'context': link.get('context', '')
            })
        
        return links
    
    def detect_platform(self, url: str) -> str:
        """
        Detect IR platform from URL
        
        Args:
            url: IR page URL
            
        Returns:
            Platform name or 'generic'
        """
        url_lower = url.lower()
        
        for platform, patterns in self.platform_patterns.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    return platform
        
        return 'generic'
    
    def filter_links_by_pattern(
        self,
        links: List[Dict],
        patterns: List[str],
        include_context: bool = True
    ) -> List[Dict]:
        """
        Filter links by regex patterns with context
        
        Args:
            links: List of link dictionaries
            patterns: List of regex patterns
            include_context: Whether to search in context as well
            
        Returns:
            Filtered links
        """
        filtered = []
        for link in links:
            text = link['text'].lower()
            url = link['url'].lower()
            context = link.get('context', '').lower() if include_context else ''
            combined = f"{text} {url} {context}"
            
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    filtered.append(link)
                    break
        
        return filtered
    
    def filter_by_document_type(self, links: List[Dict], document_type: str) -> List[Dict]:
        """Filter links by document type"""
        if document_type not in self.document_patterns:
            return links
        
        patterns = self.document_patterns[document_type]
        return self.filter_links_by_pattern(links, patterns)
    
    def filter_by_year(self, links: List[Dict], year: int) -> List[Dict]:
        """Filter links by year"""
        year_pattern = str(year)
        filtered = []
        
        for link in links:
            text = link['text']
            url = link['url']
            context = link.get('context', '')
            combined = f"{text} {url} {context}"
            
            if year_pattern in combined:
                filtered.append(link)
        
        return filtered
    
    def extract_year_from_text(self, text: str) -> Optional[int]:
        """Extract year from text (looks for 4-digit years)"""
        match = re.search(r'\b(20[0-2][0-9])\b', text)
        if match:
            return int(match.group(1))
        return None
    
    def extract_quarter_from_text(self, text: str) -> Optional[str]:
        """Extract quarter information from text"""
        # Look for Q1, Q2, Q3, Q4
        match = re.search(r'\bq([1-4])\b', text, re.IGNORECASE)
        if match:
            return f"Q{match.group(1)}"
        return None
    
    def is_document_link(self, url: str) -> bool:
        """Check if URL points to a document"""
        doc_extensions = ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.htm', '.html']
        url_lower = url.lower()
        return any(url_lower.endswith(ext) for ext in doc_extensions)
    
    def is_pdf_link(self, url: str) -> bool:
        """Check if URL points to a PDF"""
        return url.lower().endswith('.pdf')
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL"""
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
        quarter: Optional[str] = None,
        date: Optional[str] = None,
        description: Optional[str] = None,
        context: Optional[str] = None
    ) -> Dict:
        """
        Create a standardized document dictionary
        
        Args:
            title: Document title
            url: Document URL
            doc_type: Document type
            year: Document year
            quarter: Quarter (Q1, Q2, Q3, Q4)
            date: Document date
            description: Document description
            context: Additional context
            
        Returns:
            Document dictionary
        """
        # Try to extract year if not provided
        if not year:
            year = self.extract_year_from_text(f"{title} {url} {description or ''} {context or ''}")
        
        # Try to extract quarter if not provided
        if not quarter:
            quarter = self.extract_quarter_from_text(f"{title} {url} {description or ''} {context or ''}")
        
        return {
            'title': title,
            'url': self.normalize_url(url),
            'type': doc_type,
            'year': year,
            'quarter': quarter,
            'date': date,
            'description': description,
            'ticker': self.ticker,
            'is_pdf': self.is_pdf_link(url),
            'context': context
        }
    
    def get_latest_earnings(self) -> Dict:
        """Get the latest earnings information"""
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
        """Get annual reports"""
        docs = self.scrape_documents(document_type='annual_report', year=year)
        return {
            'ticker': self.ticker,
            'count': len(docs[:limit]),
            'annual_reports': docs[:limit]
        }
    
    def get_presentations(self, limit: int = 10) -> Dict:
        """Get investor presentations"""
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
        """Get all available IR resources"""
        return {
            'ticker': self.ticker,
            'ir_page': self.get_ir_page_url(),
            'annual_reports': self.get_annual_reports(limit=3),
            'latest_earnings': self.get_latest_earnings(),
            'presentations': self.get_presentations(limit=5)
        }
