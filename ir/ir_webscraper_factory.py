"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
IR Web Scraper Factory
"""

from typing import Dict, Type, Optional
from ir.base_ir_webscraper import BaseIRWebScraper
from ir.company_ir_scrapers import (
    TeslaIRScraper,
    MicrosoftIRScraper,
    CitigroupIRScraper,
    BMOIRScraper,
    RBCIRScraper,
    JPMorganIRScraper,
    GoldmanSachsIRScraper
)


class IRWebScraperFactory:
    """
    Factory for creating appropriate IR web scraper instances
    """
    
    def __init__(self):
        """Initialize the factory with registered scrapers"""
        self._scrapers: Dict[str, Type[BaseIRWebScraper]] = {}
        self._register_default_scrapers()
    
    def _register_default_scrapers(self):
        """Register all default company scrapers"""
        self.register_scraper('TSLA', TeslaIRScraper)
        self.register_scraper('MSFT', MicrosoftIRScraper)
        self.register_scraper('C', CitigroupIRScraper)
        self.register_scraper('BMO', BMOIRScraper)
        self.register_scraper('RY', RBCIRScraper)
        self.register_scraper('JPM', JPMorganIRScraper)
        self.register_scraper('GS', GoldmanSachsIRScraper)
    
    def register_scraper(self, ticker: str, scraper_class: Type[BaseIRWebScraper]):
        """
        Register a scraper for a specific ticker
        
        Args:
            ticker: Stock ticker symbol
            scraper_class: Scraper class to register
        """
        self._scrapers[ticker.upper()] = scraper_class
    
    def get_scraper(self, ticker: str) -> Optional[BaseIRWebScraper]:
        """
        Get appropriate scraper for a ticker
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Scraper instance or None if not found
        """
        ticker = ticker.upper()
        scraper_class = self._scrapers.get(ticker)
        
        if scraper_class:
            return scraper_class()
        
        return None
    
    def is_supported(self, ticker: str) -> bool:
        """
        Check if a ticker is supported
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            True if supported, False otherwise
        """
        return ticker.upper() in self._scrapers
    
    def get_supported_tickers(self) -> list:
        """
        Get list of all supported tickers
        
        Returns:
            List of supported ticker symbols
        """
        return sorted(list(self._scrapers.keys()))
    
    def get_scraper_info(self, ticker: str) -> Dict:
        """
        Get information about a specific scraper
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Scraper information dictionary
        """
        ticker = ticker.upper()
        
        if not self.is_supported(ticker):
            return {
                'ticker': ticker,
                'supported': False,
                'scraper_class': None
            }
        
        scraper_class = self._scrapers[ticker]
        scraper = scraper_class()
        
        return {
            'ticker': ticker,
            'supported': True,
            'scraper_class': scraper_class.__name__,
            'ir_page_url': scraper.get_ir_page_url()
        }
    
    def get_all_scrapers_info(self) -> Dict:
        """
        Get information about all registered scrapers
        
        Returns:
            Dictionary of all scraper information
        """
        return {
            'total_supported': len(self._scrapers),
            'supported_tickers': self.get_supported_tickers(),
            'scrapers': [self.get_scraper_info(ticker) for ticker in self._scrapers.keys()]
        }
