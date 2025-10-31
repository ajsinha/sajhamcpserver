"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Company-Specific IR Web Scrapers
"""

from typing import Dict, List, Optional
from ir.base_ir_webscraper import BaseIRWebScraper


class TeslaIRScraper(BaseIRWebScraper):
    """Tesla (TSLA) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('TSLA')
        self.ir_url = 'https://ir.tesla.com'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from Tesla IR page"""
        try:
            documents = []
            
            # Tesla has specific sections for different document types
            urls_to_scrape = [
                f"{self.ir_url}/financial-information/quarterly-results",
                f"{self.ir_url}/financial-information/annual-reports",
                f"{self.ir_url}/press-release"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    # Filter for document links
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        # Determine document type
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        # Apply filters
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'Tesla Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            # Sort by year (most recent first)
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping Tesla documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        """Determine document type from text and URL"""
        combined = f"{text} {url}".lower()
        
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class MicrosoftIRScraper(BaseIRWebScraper):
    """Microsoft (MSFT) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('MSFT')
        self.ir_url = 'https://www.microsoft.com/en-us/investor'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from Microsoft IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/earnings/overview",
                f"{self.ir_url}/sec-filings",
                f"{self.ir_url}/annual-report"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url']) or 'report' in link['text'].lower()]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'Microsoft Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping Microsoft documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class CitigroupIRScraper(BaseIRWebScraper):
    """Citigroup (C) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('C')
        self.ir_url = 'https://www.citigroup.com/global/investors'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from Citigroup IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/quarterly-earnings",
                f"{self.ir_url}/sec-filings",
                f"{self.ir_url}/financial-reports"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'Citigroup Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping Citigroup documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class BMOIRScraper(BaseIRWebScraper):
    """Bank of Montreal (BMO) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('BMO')
        self.ir_url = 'https://investor.bmo.com/english'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from BMO IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/financial-information/quarterly-results",
                f"{self.ir_url}/financial-information/annual-reports",
                f"{self.ir_url}/news-and-events"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'BMO Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping BMO documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class RBCIRScraper(BaseIRWebScraper):
    """Royal Bank of Canada (RY) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('RY')
        self.ir_url = 'https://www.rbc.com/investor-relations'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from RBC IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/quarterly-results.html",
                f"{self.ir_url}/annual-reports.html",
                f"{self.ir_url}/financial-information.html"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'RBC Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping RBC documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class JPMorganIRScraper(BaseIRWebScraper):
    """JPMorgan Chase (JPM) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('JPM')
        self.ir_url = 'https://www.jpmorganchase.com/ir'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from JPMorgan IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/financial-information/quarterly-earnings",
                f"{self.ir_url}/sec-filings",
                f"{self.ir_url}/annual-report"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'JPMorgan Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping JPMorgan documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None


class GoldmanSachsIRScraper(BaseIRWebScraper):
    """Goldman Sachs (GS) Investor Relations Scraper"""
    
    def __init__(self):
        super().__init__('GS')
        self.ir_url = 'https://www.goldmansachs.com/investor-relations'
    
    def get_ir_page_url(self) -> str:
        return self.ir_url
    
    def scrape_documents(self, document_type: Optional[str] = None, year: Optional[int] = None) -> List[Dict]:
        """Scrape documents from Goldman Sachs IR page"""
        try:
            documents = []
            
            urls_to_scrape = [
                f"{self.ir_url}/financial-information/quarterly-earnings",
                f"{self.ir_url}/financial-disclosures",
                f"{self.ir_url}/investor-presentations"
            ]
            
            for url in urls_to_scrape:
                try:
                    content = self.fetch_page(url)
                    links = self.extract_links(content, url)
                    
                    doc_links = [link for link in links if self.is_document_link(link['url'])]
                    
                    for link in doc_links:
                        det_type = self._determine_document_type(link['text'], link['url'])
                        
                        if document_type and det_type != document_type:
                            continue
                        
                        doc_year = self.extract_year_from_text(f"{link['text']} {link['url']}")
                        if year and doc_year != year:
                            continue
                        
                        doc = self.create_document_dict(
                            title=link['text'] or 'Goldman Sachs Document',
                            url=link['url'],
                            doc_type=det_type,
                            year=doc_year
                        )
                        documents.append(doc)
                        
                except Exception as e:
                    self.logger.warning(f"Error scraping {url}: {e}")
                    continue
            
            documents.sort(key=lambda x: x.get('year', 0) or 0, reverse=True)
            return documents
            
        except Exception as e:
            self.logger.error(f"Error scraping Goldman Sachs documents: {e}")
            return []
    
    def _determine_document_type(self, text: str, url: str) -> Optional[str]:
        combined = f"{text} {url}".lower()
        for doc_type, patterns in self.document_patterns.items():
            for pattern in patterns:
                if pattern in combined:
                    return doc_type
        return None
