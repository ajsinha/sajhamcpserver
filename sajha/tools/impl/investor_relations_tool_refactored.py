"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Investor Relations MCP Tool Implementation - Refactored with Individual Tools
"""

import json
from typing import Dict, Any, List, Optional
from sajha.tools.base_mcp_tool import BaseMCPTool
#from sajha.ir.ir_webscraper_factory import IRWebScraperFactory
from sajha.ir.enhanced_factory import EnhancedIRScraperFactory as IRWebScraperFactory

class InvestorRelationsBaseTool(BaseMCPTool):
    """
    Base class for Investor Relations tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Investor Relations base tool"""
        super().__init__(config)
        
        # Initialize the scraper factory
        self.scraper_factory = IRWebScraperFactory()
    
    def _get_scraper(self, ticker: str):
        """Get scraper for a ticker"""
        ticker = ticker.upper()
        
        if not self.scraper_factory.is_supported(ticker):
            raise ValueError(
                f"Ticker {ticker} is not supported. "
                f"Supported tickers: {', '.join(self.scraper_factory.get_supported_tickers())}"
            )
        
        scraper = self.scraper_factory.get_scraper(ticker)
        if not scraper:
            raise ValueError(f"Failed to create scraper for ticker: {ticker}")
        
        return scraper


class IRListSupportedCompaniesTool(InvestorRelationsBaseTool):
    """
    Tool to list all supported companies
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_list_supported_companies',
            'description': 'List all companies with supported investor relations data',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {}
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "supported_companies": {
                    "type": "array",
                    "description": "List of supported companies",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string"},
                            "name": {"type": "string"},
                            "ir_url": {"type": "string"}
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of supported companies"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute list supported companies"""
        return self.scraper_factory.get_all_scrapers_info()


class IRFindPageTool(InvestorRelationsBaseTool):
    """
    Tool to find investor relations page URL
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_find_page',
            'description': 'Find the investor relations page URL for a company',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., TSLA, MSFT, JPM)"
                }
            },
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "ir_page_url": {"type": "string"},
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute find IR page"""
        ticker = arguments['ticker']
        scraper = self._get_scraper(ticker)
        
        try:
            ir_url = scraper.get_ir_page_url()
            return {
                'ticker': scraper.ticker,
                'ir_page_url': ir_url,
                'success': True
            }
        except Exception as e:
            raise ValueError(f"Failed to find IR page: {str(e)}")


class IRGetDocumentsTool(InvestorRelationsBaseTool):
    """
    Tool to get investor relations documents
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_get_documents',
            'description': 'Get investor relations documents by type and year',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
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
                    ],
                    "default": "all"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for documents (optional)",
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
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "document_type": {"type": "string"},
                "year": {"type": ["integer", "null"]},
                "count": {"type": "integer"},
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "date": {"type": "string"},
                            "type": {"type": "string"}
                        }
                    }
                },
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get documents"""
        ticker = arguments['ticker']
        document_type = arguments.get('document_type', 'all')
        year = arguments.get('year')
        limit = arguments.get('limit', 10)
        
        scraper = self._get_scraper(ticker)
        
        try:
            documents = scraper.scrape_documents(document_type, year)
            
            return {
                'ticker': scraper.ticker,
                'document_type': document_type,
                'year': year,
                'count': len(documents[:limit]),
                'documents': documents[:limit],
                'success': True
            }
        except Exception as e:
            raise ValueError(f"Failed to get documents: {str(e)}")


class IRGetLatestEarningsTool(InvestorRelationsBaseTool):
    """
    Tool to get latest earnings information
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_get_latest_earnings',
            'description': 'Get the latest earnings report and presentation for a company',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                }
            },
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "latest_earnings": {
                    "type": "object",
                    "properties": {
                        "quarter": {"type": "string"},
                        "year": {"type": "integer"},
                        "report_url": {"type": "string"},
                        "presentation_url": {"type": "string"},
                        "date": {"type": "string"}
                    }
                },
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get latest earnings"""
        ticker = arguments['ticker']
        scraper = self._get_scraper(ticker)
        
        try:
            earnings_data = scraper.get_latest_earnings()
            earnings_data['success'] = True
            return earnings_data
        except Exception as e:
            raise ValueError(f"Failed to get latest earnings: {str(e)}")


class IRGetAnnualReportsTool(InvestorRelationsBaseTool):
    """
    Tool to get annual reports
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_get_annual_reports',
            'description': 'Get annual reports (10-K) for a company',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "year": {
                    "type": "integer",
                    "description": "Specific year (optional)",
                    "minimum": 2000,
                    "maximum": 2030
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of reports to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                }
            },
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "year": {"type": ["integer", "null"]},
                "count": {"type": "integer"},
                "annual_reports": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "year": {"type": "integer"},
                            "date": {"type": "string"}
                        }
                    }
                },
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get annual reports"""
        ticker = arguments['ticker']
        year = arguments.get('year')
        limit = arguments.get('limit', 5)
        
        scraper = self._get_scraper(ticker)
        
        try:
            reports_data = scraper.get_annual_reports(year, limit)
            reports_data['success'] = True
            return reports_data
        except Exception as e:
            raise ValueError(f"Failed to get annual reports: {str(e)}")


class IRGetPresentationsTool(InvestorRelationsBaseTool):
    """
    Tool to get investor presentations
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_get_presentations',
            'description': 'Get investor presentations and earnings decks',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of presentations to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30
                }
            },
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "count": {"type": "integer"},
                "presentations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "date": {"type": "string"},
                            "type": {"type": "string"}
                        }
                    }
                },
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get presentations"""
        ticker = arguments['ticker']
        limit = arguments.get('limit', 10)
        
        scraper = self._get_scraper(ticker)
        
        try:
            presentations_data = scraper.get_presentations(limit)
            presentations_data['success'] = True
            return presentations_data
        except Exception as e:
            raise ValueError(f"Failed to get presentations: {str(e)}")


class IRGetAllResourcesTool(InvestorRelationsBaseTool):
    """
    Tool to get all investor relations resources
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ir_get_all_resources',
            'description': 'Get comprehensive investor relations resources including reports, presentations, and documents',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol"
                }
            },
            "required": ["ticker"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "ir_page_url": {"type": "string"},
                "resources": {
                    "type": "object",
                    "properties": {
                        "annual_reports": {"type": "array"},
                        "quarterly_reports": {"type": "array"},
                        "presentations": {"type": "array"},
                        "press_releases": {"type": "array"}
                    }
                },
                "success": {"type": "boolean"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get all resources"""
        ticker = arguments['ticker']
        scraper = self._get_scraper(ticker)
        
        try:
            resources_data = scraper.get_all_resources()
            resources_data['success'] = True
            return resources_data
        except Exception as e:
            raise ValueError(f"Failed to get all resources: {str(e)}")


# Tool registry
INVESTOR_RELATIONS_TOOLS = {
    'ir_list_supported_companies': IRListSupportedCompaniesTool,
    'ir_find_page': IRFindPageTool,
    'ir_get_documents': IRGetDocumentsTool,
    'ir_get_latest_earnings': IRGetLatestEarningsTool,
    'ir_get_annual_reports': IRGetAnnualReportsTool,
    'ir_get_presentations': IRGetPresentationsTool,
    'ir_get_all_resources': IRGetAllResourcesTool
}
