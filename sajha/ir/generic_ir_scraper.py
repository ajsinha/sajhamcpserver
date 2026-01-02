"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Generic IR Web Scraper for S&P 500 Companies
"""

import logging
from typing import Dict, List, Optional
from .enhanced_base_scraper import EnhancedBaseIRScraper
from .company_database import CompanyConfig
from .sec_edgar import SECEdgarClient


class GenericIRScraper(EnhancedBaseIRScraper):
    """
    Generic scraper that works for most S&P 500 companies
    Uses configuration-driven approach with pattern detection
    Falls back to SEC EDGAR when direct scraping fails
    """
    
    def __init__(
        self,
        ticker: str,
        company_config: CompanyConfig,
        use_sec_fallback: bool = True
    ):
        """
        Initialize generic scraper
        
        Args:
            ticker: Stock ticker symbol
            company_config: Company configuration
            use_sec_fallback: Whether to use SEC EDGAR as fallback
        """
        super().__init__(ticker, company_config.to_dict())
        self.company_config = company_config
        self.use_sec_fallback = use_sec_fallback
        
        if use_sec_fallback and company_config.cik:
            self.sec_client = SECEdgarClient()
        else:
            self.sec_client = None
    
    def get_ir_page_url(self) -> str:
        """Get the main investor relations page URL"""
        return self.company_config.ir_url
    
    def scrape_documents(
        self,
        document_type: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """
        Scrape documents from IR page with SEC fallback
        
        Args:
            document_type: Type of document to filter for
            year: Year to filter for
            
        Returns:
            List of document information dictionaries
        """
        documents = []
        
        # Try direct scraping first
        try:
            documents = self._scrape_from_ir_page(document_type, year)
            
            if documents:
                self.logger.info(f"Found {len(documents)} documents from IR page")
                return documents
        except Exception as e:
            self.logger.warning(f"Error scraping IR page: {e}")
        
        # Fall back to SEC EDGAR if enabled
        if self.use_sec_fallback and self.sec_client and self.company_config.cik:
            self.logger.info(f"Falling back to SEC EDGAR for {self.ticker}")
            try:
                documents = self._scrape_from_sec(document_type, year)
                if documents:
                    self.logger.info(f"Found {len(documents)} documents from SEC EDGAR")
            except Exception as e:
                self.logger.error(f"Error fetching from SEC: {e}")
        
        return documents
    
    def _scrape_from_ir_page(
        self,
        document_type: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """
        Scrape documents directly from IR page
        
        Args:
            document_type: Type of document to filter for
            year: Year to filter for
            
        Returns:
            List of document dictionaries
        """
        documents = []
        
        # Get URLs to scrape from configuration or use defaults
        urls_to_scrape = self._get_urls_to_scrape(document_type)
        
        for url in urls_to_scrape:
            try:
                self.logger.debug(f"Scraping {url}")
                content = self.fetch_page(url)
                links = self.extract_links(content, url)
                
                # Filter for document links
                doc_links = [link for link in links if self.is_document_link(link['url'])]
                
                # If no direct document links, look for links that might lead to documents
                if not doc_links:
                    # Look for links with document-related keywords
                    doc_related_patterns = [
                        r'download', r'view', r'pdf', r'report', r'filing',
                        r'presentation', r'earnings', r'annual', r'quarterly'
                    ]
                    doc_links = self.filter_links_by_pattern(links, doc_related_patterns)
                
                for link in doc_links:
                    # Determine document type
                    det_type = self._determine_document_type(
                        link['text'],
                        link['url'],
                        link.get('context', '')
                    )
                    
                    # Apply filters
                    if document_type and det_type != document_type:
                        continue
                    
                    combined_text = f"{link['text']} {link['url']} {link.get('context', '')}"
                    doc_year = self.extract_year_from_text(combined_text)
                    if year and doc_year != year:
                        continue
                    
                    doc_quarter = self.extract_quarter_from_text(combined_text)
                    
                    doc = self.create_document_dict(
                        title=link['text'] or f'{self.ticker} Document',
                        url=link['url'],
                        doc_type=det_type,
                        year=doc_year,
                        quarter=doc_quarter,
                        context=link.get('context', '')
                    )
                    documents.append(doc)
                    
            except Exception as e:
                self.logger.warning(f"Error scraping {url}: {e}")
                continue
        
        # Sort by year and quarter (most recent first)
        documents.sort(
            key=lambda x: (
                x.get('year', 0) or 0,
                {'Q4': 4, 'Q3': 3, 'Q2': 2, 'Q1': 1}.get(x.get('quarter', ''), 0)
            ),
            reverse=True
        )
        
        # Remove duplicates by URL
        seen_urls = set()
        unique_documents = []
        for doc in documents:
            if doc['url'] not in seen_urls:
                seen_urls.add(doc['url'])
                unique_documents.append(doc)
        
        return unique_documents
    
    def _scrape_from_sec(
        self,
        document_type: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[Dict]:
        """
        Scrape documents from SEC EDGAR
        
        Args:
            document_type: Type of document to filter for
            year: Year to filter for
            
        Returns:
            List of document dictionaries
        """
        if not self.sec_client or not self.company_config.cik:
            return []
        
        # Map document types to SEC filing types
        type_to_filing = {
            'annual_report': ['10-K', '20-F'],
            'quarterly_report': ['10-Q'],
            'proxy_statement': ['DEF 14A'],
            'current_report': ['8-K']
        }
        
        filing_types = None
        if document_type and document_type in type_to_filing:
            filing_types = type_to_filing[document_type]
        
        # Get recent filings
        filings = self.sec_client.get_recent_filings(
            self.company_config.cik,
            filing_types=filing_types,
            limit=50
        )
        
        # Filter by year if specified
        if year:
            filings = [f for f in filings if f.get('year') == year]
        
        # Format for IR tool
        documents = self.sec_client.format_for_ir_tool(filings, self.ticker)
        
        return documents
    
    def _get_urls_to_scrape(self, document_type: Optional[str] = None) -> List[str]:
        """
        Get URLs to scrape based on document type
        
        Args:
            document_type: Optional document type
            
        Returns:
            List of URLs to scrape
        """
        urls = []
        
        # Get URLs from company configuration
        doc_urls = self.company_config.document_urls
        
        if document_type:
            # Map document type to config keys
            type_to_keys = {
                'annual_report': ['annual_reports', 'annual_report', 'sec_filings'],
                'quarterly_report': ['quarterly_results', 'quarterly_reports', 'earnings', 'sec_filings'],
                'earnings_presentation': ['earnings', 'quarterly_results', 'financial_info'],
                'investor_presentation': ['presentations', 'investor_presentations'],
                'proxy_statement': ['sec_filings', 'proxy'],
                'press_release': ['press_releases', 'news']
            }
            
            keys = type_to_keys.get(document_type, [])
            for key in keys:
                if key in doc_urls:
                    urls.append(doc_urls[key])
        
        # If no specific URLs found, use main IR page
        if not urls:
            urls.append(self.company_config.ir_url)
            
            # Also try common sub-pages
            base_url = self.company_config.ir_url.rstrip('/')
            common_paths = [
                '/financial-information',
                '/financials',
                '/sec-filings',
                '/quarterly-results',
                '/quarterly-earnings',
                '/earnings',
                '/annual-reports',
                '/presentations',
                '/investor-presentations'
            ]
            
            for path in common_paths:
                urls.append(f"{base_url}{path}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls
    
    def _determine_document_type(
        self,
        text: str,
        url: str,
        context: str = ''
    ) -> Optional[str]:
        """
        Determine document type from text, URL, and context
        
        Args:
            text: Link text
            url: Document URL
            context: Surrounding context
            
        Returns:
            Document type or None
        """
        combined = f"{text} {url} {context}".lower()
        
        # Check each document type's patterns
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    return doc_type
        
        return None
    
    def get_specific_document(
        self,
        document_type: str,
        year: int,
        quarter: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get a specific document by type, year, and optionally quarter
        
        Args:
            document_type: Document type
            year: Year
            quarter: Optional quarter (Q1, Q2, Q3, Q4)
            
        Returns:
            Document dictionary or None if not found
        """
        documents = self.scrape_documents(document_type=document_type, year=year)
        
        if not documents:
            return None
        
        # If quarter specified, filter by quarter
        if quarter:
            quarter_docs = [d for d in documents if d.get('quarter') == quarter]
            if quarter_docs:
                return quarter_docs[0]
        
        # Return first match
        return documents[0]


import re
