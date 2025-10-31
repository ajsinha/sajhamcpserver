"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Enhanced Investor Relations MCP Tool Implementation
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from tools.base_mcp_tool import BaseMCPTool
from ir.enhanced_factory import EnhancedIRScraperFactory
from ir.company_database import CompanyDatabase


class EnhancedInvestorRelationsTool(BaseMCPTool):
    """
    Enhanced tool for finding investor relations documents and resources
    - Supports all S&P 500 companies via configuration
    - Better bot detection avoidance
    - SEC EDGAR fallback
    - Generic scraper for scalability
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Enhanced Investor Relations tool"""
        default_config = {
            'name': 'investor_relations',
            'description': 'Find investor relations documents and links for public companies',
            'version': '2.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Initialize company database
        config_file = config.get('config/ir/company_config_file') if config else None
        self.company_db = CompanyDatabase(config_file)
        
        # Initialize scraper factory
        use_sec_fallback = config.get('use_sec_fallback', True) if config else True
        self.scraper_factory = EnhancedIRScraperFactory(
            company_db=self.company_db,
            use_sec_fallback=use_sec_fallback
        )
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Investor Relations tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "find_ir_page",
                        "get_documents",
                        "get_latest_earnings",
                        "get_annual_reports",
                        "get_quarterly_reports",
                        "get_presentations",
                        "get_all_resources",
                        "list_supported_companies",
                        "get_company_info",
                        "search_documents",
                        "add_company"
                    ]
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., TSLA, MSFT, JPM)"
                },
                "document_type": {
                    "type": "string",
                    "description": "Type of document to search for",
                    "enum": [
                        "annual_report",
                        "quarterly_report",
                        "earnings_presentation",
                        "investor_presentation",
                        "proxy_statement",
                        "press_release",
                        "esg_report",
                        "all"
                    ]
                },
                "year": {
                    "type": "integer",
                    "description": "Year for documents (e.g., 2024, 2023)",
                    "minimum": 2000,
                    "maximum": 2030
                },
                "quarter": {
                    "type": "string",
                    "description": "Quarter for documents (Q1, Q2, Q3, Q4)",
                    "enum": ["Q1", "Q2", "Q3", "Q4"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of documents to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                },
                "keywords": {
                    "type": "array",
                    "description": "Keywords to search for in documents",
                    "items": {"type": "string"}
                },
                "company_info": {
                    "type": "object",
                    "description": "Company information for add_company action",
                    "properties": {
                        "name": {"type": "string"},
                        "ir_url": {"type": "string"},
                        "cik": {"type": "string"},
                        "ir_platform": {"type": "string"}
                    }
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Investor Relations tool action
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Investor relations information and document links
        """
        action = arguments.get('action')
        
        # Actions that don't require ticker
        if action == 'list_supported_companies':
            return self._list_supported_companies()
        
        if action == 'add_company':
            return self._add_company(arguments)
        
        # All other actions require ticker
        ticker = arguments.get('ticker', '').upper()
        if not ticker:
            raise ValueError("'ticker' is required for this action")
        
        # Check if ticker is supported
        if not self.scraper_factory.is_supported(ticker):
            return self._handle_unsupported_ticker(ticker)
        
        # Get the appropriate scraper
        scraper = self.scraper_factory.get_scraper(ticker)
        
        if not scraper:
            raise ValueError(f"Failed to create scraper for ticker: {ticker}")
        
        # Execute the requested action
        try:
            if action == 'find_ir_page':
                return self._find_ir_page(scraper)
            
            elif action == 'get_documents':
                document_type = arguments.get('document_type')
                year = arguments.get('year')
                limit = arguments.get('limit', 10)
                return self._get_documents(scraper, document_type, year, limit)
            
            elif action == 'get_latest_earnings':
                return self._get_latest_earnings(scraper)
            
            elif action == 'get_annual_reports':
                year = arguments.get('year')
                limit = arguments.get('limit', 5)
                return self._get_annual_reports(scraper, year, limit)
            
            elif action == 'get_quarterly_reports':
                year = arguments.get('year')
                limit = arguments.get('limit', 10)
                return self._get_quarterly_reports(scraper, year, limit)
            
            elif action == 'get_presentations':
                limit = arguments.get('limit', 10)
                return self._get_presentations(scraper, limit)
            
            elif action == 'get_all_resources':
                return self._get_all_resources(scraper)
            
            elif action == 'get_company_info':
                return self._get_company_info(ticker)
            
            elif action == 'search_documents':
                keywords = arguments.get('keywords', [])
                document_type = arguments.get('document_type')
                year = arguments.get('year')
                limit = arguments.get('limit', 20)
                return self._search_documents(scraper, keywords, document_type, year, limit)
            
            else:
                raise ValueError(f"Unknown action: {action}")
                
        except Exception as e:
            self.logger.error(f"Error executing action {action} for {ticker}: {e}")
            return {
                'ticker': ticker,
                'action': action,
                'success': False,
                'error': str(e),
                'message': f"Failed to {action.replace('_', ' ')} for {ticker}",
                'suggestion': "Try using SEC EDGAR fallback or check if the company's IR page is accessible"
            }
    
    def _list_supported_companies(self) -> Dict:
        """List all supported companies"""
        info = self.scraper_factory.get_all_scrapers_info()
        
        return {
            'success': True,
            'total_supported': info['total_supported'],
            'companies_with_sec_fallback': info['companies_with_cik'],
            'supported_tickers': info['supported_tickers'],
            'platforms': info['platforms'],
            'message': f"Currently supporting {info['total_supported']} companies",
            'note': "All companies support SEC EDGAR fallback when CIK is available"
        }
    
    def _handle_unsupported_ticker(self, ticker: str) -> Dict:
        """Handle unsupported ticker"""
        supported_tickers = self.scraper_factory.get_supported_tickers()
        
        return {
            'ticker': ticker,
            'supported': False,
            'success': False,
            'message': f"Ticker {ticker} is not currently supported",
            'total_supported': len(supported_tickers),
            'suggestion': f"Use 'list_supported_companies' action to see all supported tickers",
            'note': "You can add new companies using the 'add_company' action"
        }
    
    def _find_ir_page(self, scraper) -> Dict:
        """Find IR page URL"""
        try:
            ir_url = scraper.get_ir_page_url()
            return {
                'ticker': scraper.ticker,
                'ir_page_url': ir_url,
                'success': True,
                'message': f"Found IR page for {scraper.ticker}"
            }
        except Exception as e:
            raise ValueError(f"Failed to find IR page: {str(e)}")
    
    def _get_documents(
        self,
        scraper,
        document_type: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 10
    ) -> Dict:
        """Get documents from IR page or SEC"""
        try:
            documents = scraper.scrape_documents(document_type, year)
            
            return {
                'ticker': scraper.ticker,
                'document_type': document_type or 'all',
                'year': year,
                'count': len(documents[:limit]),
                'total_found': len(documents),
                'documents': documents[:limit],
                'success': True,
                'sources': list(set(doc.get('source', 'IR Page') for doc in documents))
            }
        except Exception as e:
            raise ValueError(f"Failed to get documents: {str(e)}")
    
    def _get_latest_earnings(self, scraper) -> Dict:
        """Get latest earnings information"""
        try:
            earnings_data = scraper.get_latest_earnings()
            earnings_data['success'] = True
            return earnings_data
        except Exception as e:
            raise ValueError(f"Failed to get latest earnings: {str(e)}")
    
    def _get_annual_reports(
        self,
        scraper,
        year: Optional[int] = None,
        limit: int = 5
    ) -> Dict:
        """Get annual reports"""
        try:
            reports_data = scraper.get_annual_reports(year, limit)
            reports_data['success'] = True
            return reports_data
        except Exception as e:
            raise ValueError(f"Failed to get annual reports: {str(e)}")
    
    def _get_quarterly_reports(
        self,
        scraper,
        year: Optional[int] = None,
        limit: int = 10
    ) -> Dict:
        """Get quarterly reports"""
        try:
            documents = scraper.scrape_documents(
                document_type='quarterly_report',
                year=year
            )
            return {
                'ticker': scraper.ticker,
                'count': len(documents[:limit]),
                'quarterly_reports': documents[:limit],
                'success': True
            }
        except Exception as e:
            raise ValueError(f"Failed to get quarterly reports: {str(e)}")
    
    def _get_presentations(self, scraper, limit: int = 10) -> Dict:
        """Get investor presentations"""
        try:
            presentations_data = scraper.get_presentations(limit)
            presentations_data['success'] = True
            return presentations_data
        except Exception as e:
            raise ValueError(f"Failed to get presentations: {str(e)}")
    
    def _get_all_resources(self, scraper) -> Dict:
        """Get all IR resources"""
        try:
            resources_data = scraper.get_all_resources()
            resources_data['success'] = True
            return resources_data
        except Exception as e:
            raise ValueError(f"Failed to get all resources: {str(e)}")
    
    def _get_company_info(self, ticker: str) -> Dict:
        """Get company information"""
        try:
            info = self.scraper_factory.get_scraper_info(ticker)
            info['success'] = True
            return info
        except Exception as e:
            raise ValueError(f"Failed to get company info: {str(e)}")
    
    def _search_documents(
        self,
        scraper,
        keywords: List[str],
        document_type: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 20
    ) -> Dict:
        """Search documents by keywords"""
        try:
            # Get all documents of specified type
            documents = scraper.scrape_documents(document_type, year)
            
            # Filter by keywords
            if keywords:
                matching_docs = []
                for doc in documents:
                    doc_text = f"{doc.get('title', '')} {doc.get('description', '')} {doc.get('context', '')}".lower()
                    if any(keyword.lower() in doc_text for keyword in keywords):
                        matching_docs.append(doc)
                documents = matching_docs
            
            return {
                'ticker': scraper.ticker,
                'keywords': keywords,
                'document_type': document_type,
                'year': year,
                'count': len(documents[:limit]),
                'total_matches': len(documents),
                'documents': documents[:limit],
                'success': True
            }
        except Exception as e:
            raise ValueError(f"Failed to search documents: {str(e)}")
    
    def _add_company(self, arguments: Dict) -> Dict:
        """Add a new company to the database"""
        try:
            ticker = arguments.get('ticker', '').upper()
            company_info = arguments.get('company_info', {})
            
            if not ticker or not company_info:
                raise ValueError("Both 'ticker' and 'company_info' are required")
            
            name = company_info.get('name')
            ir_url = company_info.get('ir_url')
            cik = company_info.get('cik')
            ir_platform = company_info.get('ir_platform', 'generic')
            
            if not name or not ir_url:
                raise ValueError("'name' and 'ir_url' are required in company_info")
            
            self.scraper_factory.add_company(
                ticker=ticker,
                name=name,
                ir_url=ir_url,
                cik=cik,
                ir_platform=ir_platform
            )
            
            return {
                'ticker': ticker,
                'success': True,
                'message': f"Successfully added {name} ({ticker}) to the database",
                'company_info': {
                    'ticker': ticker,
                    'name': name,
                    'ir_url': ir_url,
                    'cik': cik,
                    'ir_platform': ir_platform
                }
            }
        except Exception as e:
            raise ValueError(f"Failed to add company: {str(e)}")
