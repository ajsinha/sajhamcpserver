"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Enhanced IR Web Scraper Factory with Generic Scraper
"""

import logging
from typing import Optional
from ir.enhanced_base_scraper import EnhancedBaseIRScraper
from ir.generic_ir_scraper import GenericIRScraper
from ir.company_database import CompanyDatabase, CompanyConfig


class EnhancedIRScraperFactory:
    """
    Enhanced factory for creating IR web scraper instances
    - Uses generic scraper for all S&P 500 companies
    - Configuration-driven approach
    - Automatic fallback to SEC EDGAR
    """
    
    def __init__(
        self,
        company_db: Optional[CompanyDatabase] = None,
        use_sec_fallback: bool = True
    ):
        """
        Initialize the factory
        
        Args:
            company_db: Optional company database instance
            use_sec_fallback: Whether to use SEC EDGAR as fallback
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.company_db = company_db or CompanyDatabase()
        self.use_sec_fallback = use_sec_fallback
    
    def get_scraper(self, ticker: str) -> Optional[EnhancedBaseIRScraper]:
        """
        Get appropriate scraper for a ticker
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Scraper instance or None if company not found
        """
        ticker = ticker.upper()
        
        # Check if company exists in database
        company_config = self.company_db.get_company(ticker)
        
        if not company_config:
            self.logger.info(f"Company {ticker} not in database, attempting auto-discovery")
            company_config = self._auto_discover_company(ticker)
            
            if not company_config:
                self.logger.warning(f"Could not find or discover company {ticker}")
                return None
        
        # Create generic scraper
        try:
            scraper = GenericIRScraper(
                ticker=ticker,
                company_config=company_config,
                use_sec_fallback=self.use_sec_fallback
            )
            return scraper
        except Exception as e:
            self.logger.error(f"Error creating scraper for {ticker}: {e}")
            return None
    
    def is_supported(self, ticker: str) -> bool:
        """
        Check if a ticker is supported
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            True if supported
        """
        return self.company_db.has_company(ticker.upper())
    
    def get_supported_tickers(self) -> list:
        """
        Get list of all supported tickers
        
        Returns:
            List of supported ticker symbols
        """
        return self.company_db.get_all_tickers()
    
    def get_scraper_info(self, ticker: str) -> dict:
        """
        Get information about a specific scraper
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Scraper information dictionary
        """
        ticker = ticker.upper()
        company_config = self.company_db.get_company(ticker)
        
        if not company_config:
            return {
                'ticker': ticker,
                'supported': False,
                'scraper_class': None
            }
        
        return {
            'ticker': ticker,
            'supported': True,
            'company_name': company_config.name,
            'scraper_class': 'GenericIRScraper',
            'ir_page_url': company_config.ir_url,
            'ir_platform': company_config.ir_platform,
            'has_cik': company_config.cik is not None,
            'sec_fallback_available': company_config.cik is not None
        }
    
    def get_all_scrapers_info(self) -> dict:
        """
        Get information about all registered scrapers
        
        Returns:
            Dictionary of all scraper information
        """
        stats = self.company_db.get_stats()
        
        return {
            'total_supported': stats['total_companies'],
            'supported_tickers': stats['tickers'],
            'companies_with_cik': stats['with_cik'],
            'platforms': stats['platforms'],
            'scrapers': [
                self.get_scraper_info(ticker)
                for ticker in stats['tickers']
            ]
        }
    
    def _auto_discover_company(self, ticker: str) -> Optional[CompanyConfig]:
        """
        Attempt to auto-discover company configuration
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            CompanyConfig if discovered, None otherwise
        """
        # Try to discover from company database
        discovered = self.company_db.auto_discover_company(ticker)
        
        if discovered:
            # Add to database
            self.company_db.add_company(discovered)
            return discovered
        
        # Could add more auto-discovery methods here:
        # - Search for "{ticker} investor relations" and parse results
        # - Try common URL patterns
        # - Query financial APIs
        
        return None
    
    def add_company(
        self,
        ticker: str,
        name: str,
        ir_url: str,
        cik: Optional[str] = None,
        ir_platform: str = 'generic',
        document_urls: Optional[dict] = None
    ):
        """
        Add a new company to the database
        
        Args:
            ticker: Stock ticker symbol
            name: Company name
            ir_url: Investor relations page URL
            cik: Optional SEC CIK number
            ir_platform: IR platform type
            document_urls: Optional dictionary of document URLs
        """
        company_config = CompanyConfig({
            'ticker': ticker.upper(),
            'name': name,
            'ir_url': ir_url,
            'cik': cik,
            'ir_platform': ir_platform,
            'document_urls': document_urls or {}
        })
        
        self.company_db.add_company(company_config)
        self.logger.info(f"Added company {ticker} to database")
    
    def load_sp500_companies(self, file_path: str):
        """
        Load S&P 500 companies from a configuration file
        
        Args:
            file_path: Path to company configuration file
        """
        try:
            self.company_db.load_from_file(file_path)
            self.logger.info(f"Loaded S&P 500 companies from {file_path}")
        except Exception as e:
            self.logger.error(f"Error loading S&P 500 companies: {e}")
            raise
    
    def save_company_database(self, file_path: str):
        """
        Save current company database to file
        
        Args:
            file_path: Path to save configuration file
        """
        try:
            self.company_db.save_to_file(file_path)
            self.logger.info(f"Saved company database to {file_path}")
        except Exception as e:
            self.logger.error(f"Error saving company database: {e}")
            raise
