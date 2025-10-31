"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Company Configuration Database for Investor Relations
"""

import json
import logging
from typing import Dict, List, Optional
from pathlib import Path


class CompanyConfig:
    """Company configuration data"""
    
    def __init__(self, data: Dict):
        self.ticker = data.get('ticker', '').upper()
        self.name = data.get('name', '')
        self.cik = data.get('cik')  # SEC CIK number
        self.ir_url = data.get('ir_url', '')
        self.ir_platform = data.get('ir_platform', 'generic')  # e.g., 'q4', 'workiva', 'generic'
        self.document_urls = data.get('document_urls', {})
        self.custom_config = data.get('custom_config', {})
        
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'ticker': self.ticker,
            'name': self.name,
            'cik': self.cik,
            'ir_url': self.ir_url,
            'ir_platform': self.ir_platform,
            'document_urls': self.document_urls,
            'custom_config': self.custom_config
        }


class CompanyDatabase:
    """
    Database of S&P 500 company configurations
    Supports configuration-driven IR scraping
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize company database
        
        Args:
            config_file: Optional path to configuration file
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.companies: Dict[str, CompanyConfig] = {}
        self.ticker_to_cik: Dict[str, str] = {}
        self.cik_to_ticker: Dict[str, str] = {}
        
        if config_file and Path(config_file).exists():
            self.load_from_file(config_file)
        else:
            self._initialize_default_companies()
    
    def _initialize_default_companies(self):
        """Initialize with default S&P 500 companies"""
        # Core companies with known configurations
        default_companies = [
            {
                'ticker': 'AAPL',
                'name': 'Apple Inc.',
                'cik': '0000320193',
                'ir_url': 'https://investor.apple.com',
                'ir_platform': 'generic',
                'document_urls': {
                    'earnings': 'https://investor.apple.com/investor-relations/default.aspx',
                    'sec_filings': 'https://investor.apple.com/sec-filings/default.aspx',
                }
            },
            {
                'ticker': 'MSFT',
                'name': 'Microsoft Corporation',
                'cik': '0000789019',
                'ir_url': 'https://www.microsoft.com/en-us/investor',
                'ir_platform': 'generic',
                'document_urls': {
                    'earnings': 'https://www.microsoft.com/en-us/investor/earnings/overview',
                    'sec_filings': 'https://www.microsoft.com/en-us/investor/sec-filings',
                    'annual_report': 'https://www.microsoft.com/en-us/investor/annual-report'
                }
            },
            {
                'ticker': 'GOOGL',
                'name': 'Alphabet Inc.',
                'cik': '0001652044',
                'ir_url': 'https://abc.xyz/investor',
                'ir_platform': 'generic',
                'document_urls': {
                    'sec_filings': 'https://abc.xyz/investor/#financial-information'
                }
            },
            {
                'ticker': 'AMZN',
                'name': 'Amazon.com Inc.',
                'cik': '0001018724',
                'ir_url': 'https://ir.aboutamazon.com',
                'ir_platform': 'generic',
                'document_urls': {
                    'annual_reports': 'https://ir.aboutamazon.com/annual-reports-proxies-and-shareholder-letters/default.aspx',
                    'quarterly_results': 'https://ir.aboutamazon.com/quarterly-results/default.aspx'
                }
            },
            {
                'ticker': 'NVDA',
                'name': 'NVIDIA Corporation',
                'cik': '0001045810',
                'ir_url': 'https://investor.nvidia.com',
                'ir_platform': 'generic',
                'document_urls': {
                    'financial_info': 'https://investor.nvidia.com/financial-info/financial-reports/default.aspx'
                }
            },
            {
                'ticker': 'TSLA',
                'name': 'Tesla Inc.',
                'cik': '0001318605',
                'ir_url': 'https://ir.tesla.com',
                'ir_platform': 'generic',
                'document_urls': {
                    'quarterly_results': 'https://ir.tesla.com/financial-information/quarterly-results',
                    'annual_reports': 'https://ir.tesla.com/financial-information/annual-reports',
                    'sec_filings': 'https://ir.tesla.com/sec-filings'
                }
            },
            {
                'ticker': 'JPM',
                'name': 'JPMorgan Chase & Co.',
                'cik': '0000019617',
                'ir_url': 'https://www.jpmorganchase.com/ir',
                'ir_platform': 'generic',
                'document_urls': {
                    'quarterly_earnings': 'https://www.jpmorganchase.com/ir/financial-information/quarterly-earnings',
                    'sec_filings': 'https://www.jpmorganchase.com/ir/sec-filings'
                }
            },
            {
                'ticker': 'GS',
                'name': 'Goldman Sachs Group Inc.',
                'cik': '0000886982',
                'ir_url': 'https://www.goldmansachs.com/investor-relations',
                'ir_platform': 'generic',
                'document_urls': {
                    'financials': 'https://www.goldmansachs.com/investor-relations/financial-information'
                }
            },
            {
                'ticker': 'BAC',
                'name': 'Bank of America Corporation',
                'cik': '0000070858',
                'ir_url': 'https://investor.bankofamerica.com',
                'ir_platform': 'q4',
                'document_urls': {}
            },
            {
                'ticker': 'WMT',
                'name': 'Walmart Inc.',
                'cik': '0000104169',
                'ir_url': 'https://stock.walmart.com',
                'ir_platform': 'generic',
                'document_urls': {}
            },
            # Add more as needed...
        ]
        
        for company_data in default_companies:
            self.add_company(CompanyConfig(company_data))
    
    def add_company(self, company: CompanyConfig):
        """Add a company to the database"""
        self.companies[company.ticker] = company
        if company.cik:
            self.ticker_to_cik[company.ticker] = company.cik
            self.cik_to_ticker[company.cik] = company.ticker
    
    def get_company(self, ticker: str) -> Optional[CompanyConfig]:
        """Get company configuration by ticker"""
        return self.companies.get(ticker.upper())
    
    def get_company_by_cik(self, cik: str) -> Optional[CompanyConfig]:
        """Get company configuration by CIK"""
        ticker = self.cik_to_ticker.get(cik)
        if ticker:
            return self.companies.get(ticker)
        return None
    
    def has_company(self, ticker: str) -> bool:
        """Check if ticker is in database"""
        return ticker.upper() in self.companies
    
    def get_all_tickers(self) -> List[str]:
        """Get all supported tickers"""
        return sorted(list(self.companies.keys()))
    
    def get_cik(self, ticker: str) -> Optional[str]:
        """Get CIK number for ticker"""
        return self.ticker_to_cik.get(ticker.upper())
    
    def load_from_file(self, file_path: str):
        """
        Load company configurations from JSON file
        
        Args:
            file_path: Path to JSON configuration file
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                
            companies_data = data.get('companies', [])
            for company_data in companies_data:
                company = CompanyConfig(company_data)
                self.add_company(company)
                
            self.logger.info(f"Loaded {len(companies_data)} companies from {file_path}")
            
        except Exception as e:
            self.logger.error(f"Error loading company database: {e}")
            raise
    
    def save_to_file(self, file_path: str):
        """
        Save company configurations to JSON file
        
        Args:
            file_path: Path to save JSON configuration
        """
        try:
            data = {
                'companies': [company.to_dict() for company in self.companies.values()],
                'total_companies': len(self.companies)
            }
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
                
            self.logger.info(f"Saved {len(self.companies)} companies to {file_path}")
            
        except Exception as e:
            self.logger.error(f"Error saving company database: {e}")
            raise
    
    def auto_discover_company(self, ticker: str) -> Optional[CompanyConfig]:
        """
        Auto-discover company IR page and configuration
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            CompanyConfig if discovered, None otherwise
        """
        # Try common IR URL patterns
        common_patterns = [
            f'https://ir.{ticker.lower()}.com',
            f'https://investor.{ticker.lower()}.com',
            f'https://investors.{ticker.lower()}.com',
            f'https://www.{ticker.lower()}.com/investor',
            f'https://www.{ticker.lower()}.com/investors',
            f'https://www.{ticker.lower()}.com/investor-relations',
        ]
        
        # This would need an HTTP client to test URLs
        # For now, return None - can be implemented later
        self.logger.info(f"Auto-discovery for {ticker} not yet implemented")
        return None
    
    def get_stats(self) -> Dict:
        """Get database statistics"""
        return {
            'total_companies': len(self.companies),
            'with_cik': len(self.ticker_to_cik),
            'platforms': self._count_platforms(),
            'tickers': self.get_all_tickers()
        }
    
    def _count_platforms(self) -> Dict[str, int]:
        """Count companies by IR platform"""
        platforms = {}
        for company in self.companies.values():
            platform = company.ir_platform
            platforms[platform] = platforms.get(platform, 0) + 1
        return platforms
