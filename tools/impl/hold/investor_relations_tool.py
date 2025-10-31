"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Investor Relations MCP Tool Implementation
"""

import json
from typing import Dict, Any, List, Optional
from tools.base_mcp_tool import BaseMCPTool
from ir.ir_webscraper_factory import IRWebScraperFactory


class InvestorRelationsTool(BaseMCPTool):
    """
    Tool for finding investor relations documents and resources
    Uses factory pattern to get company-specific scrapers
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Investor Relations tool"""
        default_config = {
            'name': 'investor_relations',
            'description': 'Find investor relations documents and links for public companies',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Initialize the scraper factory
        self.scraper_factory = IRWebScraperFactory()
    
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
                        "get_presentations",
                        "get_all_resources",
                        "list_supported_companies"
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of documents to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Investor Relations tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Investor relations information and document links
        """
        action = arguments.get('action')
        
        # Handle action that doesn't require ticker
        if action == 'list_supported_companies':
            return self._list_supported_companies()
        
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
                
            elif action == 'get_presentations':
                limit = arguments.get('limit', 10)
                return self._get_presentations(scraper, limit)
                
            elif action == 'get_all_resources':
                return self._get_all_resources(scraper)
                
            else:
                raise ValueError(f"Unknown action: {action}")
                
        except Exception as e:
            self.logger.error(f"Error executing action {action} for {ticker}: {e}")
            return {
                'ticker': ticker,
                'action': action,
                'success': False,
                'error': str(e),
                'message': f"Failed to {action.replace('_', ' ')} for {ticker}"
            }
    
    def _list_supported_companies(self) -> Dict:
        """
        List all supported companies
        
        Returns:
            List of supported companies with their IR page URLs
        """
        return self.scraper_factory.get_all_scrapers_info()
    
    def _handle_unsupported_ticker(self, ticker: str) -> Dict:
        """
        Handle unsupported ticker
        
        Args:
            ticker: Unsupported ticker symbol
            
        Returns:
            Information about unsupported ticker with suggestions
        """
        supported_tickers = self.scraper_factory.get_supported_tickers()
        
        return {
            'ticker': ticker,
            'supported': False,
            'message': f"Ticker {ticker} is not currently supported",
            'supported_tickers': supported_tickers,
            'total_supported': len(supported_tickers),
            'suggestion': f"Please use one of the supported tickers: {', '.join(supported_tickers[:10])}{'...' if len(supported_tickers) > 10 else ''}",
            'note': "More companies will be added in future updates"
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
        """Get documents from IR page"""
        try:
            documents = scraper.scrape_documents(document_type, year)
            
            return {
                'ticker': scraper.ticker,
                'document_type': document_type or 'all',
                'year': year,
                'count': len(documents[:limit]),
                'documents': documents[:limit],
                'success': True
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
