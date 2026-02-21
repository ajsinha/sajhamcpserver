"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Enhanced Investor Relations Package

This package provides enhanced investor relations web scraping capabilities with:
- Bot detection avoidance
- Rate limiting and retry logic
- SEC EDGAR fallback
- Support for 500+ S&P 500 companies
- Configuration-driven approach
"""

from .http_client import EnhancedHTTPClient, RateLimiter
from .company_database import CompanyDatabase, CompanyConfig
from .sec_edgar import SECEdgarClient
from .enhanced_base_scraper import EnhancedBaseIRScraper
from .generic_ir_scraper import GenericIRScraper
from .enhanced_factory import EnhancedIRScraperFactory

__all__ = [
    'EnhancedHTTPClient',
    'RateLimiter',
    'CompanyDatabase',
    'CompanyConfig',
    'SECEdgarClient',
    'EnhancedBaseIRScraper',
    'GenericIRScraper',
    'EnhancedIRScraperFactory',
]

__version__ = '2.9.8'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'
