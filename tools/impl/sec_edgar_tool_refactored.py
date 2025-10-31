"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
SEC EDGAR MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class SECEdgarBaseTool(BaseMCPTool):
    """
    Base class for SEC EDGAR tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize SEC EDGAR base tool"""
        super().__init__(config)
        
        # SEC EDGAR API endpoints
        self.api_url = "https://data.sec.gov"
        # SEC requires User-Agent with contact email: https://www.sec.gov/os/accessing-edgar-data
        self.user_agent = "SAJHA-MCP-Server/1.0 (ajsinha@gmail.com)"
        
        # Common filing types
        self.filing_types = {
            '10-K': 'Annual Report',
            '10-Q': 'Quarterly Report',
            '8-K': 'Current Report',
            '10-K/A': 'Annual Report Amendment',
            '10-Q/A': 'Quarterly Report Amendment',
            'S-1': 'Registration Statement',
            'S-3': 'Registration Statement',
            'S-4': 'Registration Statement',
            '13F-HR': 'Institutional Investment Manager Holdings',
            '4': 'Statement of Changes in Beneficial Ownership',
            'DEF 14A': 'Proxy Statement',
            '20-F': 'Annual Report (Foreign Private Issuer)',
            '6-K': 'Current Report (Foreign Private Issuer)',
            'SC 13D': 'Beneficial Ownership Report',
            'SC 13G': 'Beneficial Ownership Report (Passive)'
        }
    
    def _normalize_cik(self, cik: str) -> str:
        """Normalize CIK to 10 digits"""
        return str(cik).zfill(10)
    
    def _ticker_to_cik(self, ticker: str) -> str:
        """
        Convert ticker to CIK using SEC company tickers file
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            CIK number
        """
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                ticker_upper = ticker.upper()
                for entry in data.values():
                    if entry.get('ticker', '').upper() == ticker_upper:
                        return str(entry.get('cik_str', '')).zfill(10)
                
                raise ValueError(f"Ticker not found: {ticker}")
                
        except Exception as e:
            raise ValueError(f"Failed to convert ticker to CIK: {str(e)}")
    
    def _get_cik_from_args(self, cik: Optional[str] = None, ticker: Optional[str] = None) -> str:
        """
        Get CIK from either direct CIK or ticker symbol
        
        Args:
            cik: Central Index Key
            ticker: Stock ticker symbol
            
        Returns:
            Normalized 10-digit CIK
        """
        if not cik and not ticker:
            raise ValueError("Either 'cik' or 'ticker' is required")
        
        if ticker and not cik:
            cik = self._ticker_to_cik(ticker)
        
        return self._normalize_cik(cik)


class SECSearchCompanyTool(SECEdgarBaseTool):
    """
    Tool to search for companies in SEC EDGAR database
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_search_company',
            'description': 'Search for companies by name or ticker symbol in SEC EDGAR database',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for searching companies"""
        return {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Company name or ticker symbol to search for (e.g., 'Apple', 'AAPL')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "required": ["search_term"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company search results"""
        return {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Original search term"
                },
                "result_count": {
                    "type": "integer",
                    "description": "Number of companies found"
                },
                "companies": {
                    "type": "array",
                    "description": "List of matching companies",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cik": {
                                "type": "string",
                                "description": "10-digit Central Index Key"
                            },
                            "name": {
                                "type": "string",
                                "description": "Company name"
                            },
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol"
                            },
                            "exchange": {
                                "type": "string",
                                "description": "Stock exchange (e.g., 'Nasdaq', 'NYSE')"
                            }
                        },
                        "required": ["cik", "name"]
                    }
                }
            },
            "required": ["search_term", "result_count", "companies"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company search"""
        search_term = arguments.get('search_term', '').strip()
        limit = arguments.get('limit', 10)
        
        if not search_term:
            raise ValueError("search_term is required")
        
        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                search_lower = search_term.lower()
                matches = []
                
                for entry in data.values():
                    name = entry.get('title', '')
                    ticker = entry.get('ticker', '')
                    
                    if (search_lower in name.lower() or 
                        search_lower in ticker.lower()):
                        matches.append({
                            'cik': str(entry.get('cik_str', '')).zfill(10),
                            'name': name,
                            'ticker': ticker,
                            'exchange': entry.get('exchange', 'N/A')
                        })
                    
                    if len(matches) >= limit:
                        break
                
                return {
                    'search_term': search_term,
                    'result_count': len(matches),
                    'companies': matches
                }
                
        except Exception as e:
            self.logger.error(f"Failed to search companies: {e}")
            raise ValueError(f"Failed to search companies: {str(e)}")


class SECGetCompanyInfoTool(SECEdgarBaseTool):
    """
    Tool to retrieve detailed company information from SEC EDGAR
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_company_info',
            'description': 'Retrieve detailed company information including business address, SIC code, and fiscal year end',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company info"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company info"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "name": {
                    "type": "string",
                    "description": "Company legal name"
                },
                "tickers": {
                    "type": "array",
                    "description": "Stock ticker symbols",
                    "items": {"type": "string"}
                },
                "sic": {
                    "type": "string",
                    "description": "Standard Industrial Classification code"
                },
                "sic_description": {
                    "type": "string",
                    "description": "SIC code description"
                },
                "category": {
                    "type": "string",
                    "description": "SEC filer category"
                },
                "fiscal_year_end": {
                    "type": "string",
                    "description": "Fiscal year end date (MMDD format)"
                },
                "state_of_incorporation": {
                    "type": "string",
                    "description": "State or country of incorporation"
                },
                "business_address": {
                    "type": "object",
                    "description": "Business address",
                    "properties": {
                        "street1": {"type": "string"},
                        "street2": {"type": "string"},
                        "city": {"type": "string"},
                        "stateOrCountry": {"type": "string"},
                        "zipCode": {"type": "string"}
                    }
                },
                "mailing_address": {
                    "type": "object",
                    "description": "Mailing address"
                },
                "ein": {
                    "type": "string",
                    "description": "Employer Identification Number"
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number"
                },
                "exchanges": {
                    "type": "array",
                    "description": "Stock exchanges",
                    "items": {"type": "string"}
                },
                "website": {
                    "type": "string",
                    "description": "Company website URL"
                },
                "investor_website": {
                    "type": "string",
                    "description": "Investor relations website URL"
                }
            },
            "required": ["cik", "name"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company info retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        
        try:
            url = f"{self.api_url}/submissions/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                return {
                    'cik': cik,
                    'name': data.get('name'),
                    'tickers': data.get('tickers', []),
                    'sic': data.get('sic'),
                    'sic_description': data.get('sicDescription'),
                    'category': data.get('category'),
                    'fiscal_year_end': data.get('fiscalYearEnd'),
                    'state_of_incorporation': data.get('stateOfIncorporation'),
                    'business_address': data.get('addresses', {}).get('business'),
                    'mailing_address': data.get('addresses', {}).get('mailing'),
                    'ein': data.get('ein'),
                    'phone': data.get('phone'),
                    'exchanges': data.get('exchanges', []),
                    'website': data.get('website'),
                    'investor_website': data.get('investorWebsite')
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Company not found: CIK {cik}")
            else:
                raise ValueError(f"Failed to get company info: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Failed to get company info: {e}")
            raise ValueError(f"Failed to get company info: {str(e)}")


class SECGetCompanyFilingsTool(SECEdgarBaseTool):
    """
    Tool to retrieve company SEC filings
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_company_filings',
            'description': 'Retrieve SEC filings for a company with optional filtering by type and date range',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company filings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                },
                "filing_type": {
                    "type": "string",
                    "description": "Type of filing to retrieve",
                    "enum": [
                        "10-K", "10-Q", "8-K", "10-K/A", "10-Q/A",
                        "S-1", "S-3", "S-4", "13F-HR", "4",
                        "DEF 14A", "20-F", "6-K", "SC 13D", "SC 13G"
                    ]
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date for filings (YYYY-MM-DD format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for filings (YYYY-MM-DD format)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company filings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "name": {
                    "type": "string",
                    "description": "Company name"
                },
                "filing_count": {
                    "type": "integer",
                    "description": "Number of filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of SEC filings",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accession_number": {
                                "type": "string",
                                "description": "Unique filing identifier"
                            },
                            "filing_date": {
                                "type": "string",
                                "description": "Date filed with SEC (YYYY-MM-DD)"
                            },
                            "report_date": {
                                "type": "string",
                                "description": "Period end date for the filing (YYYY-MM-DD)"
                            },
                            "form": {
                                "type": "string",
                                "description": "Form type (e.g., 10-K, 10-Q, 8-K)"
                            },
                            "primary_document": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "description": {
                                "type": "string",
                                "description": "Filing type description"
                            }
                        },
                        "required": ["accession_number", "filing_date", "form"]
                    }
                }
            },
            "required": ["cik", "name", "filing_count", "filings"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company filings retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        filing_type = arguments.get('filing_type')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit', 10)
        
        try:
            url = f"{self.api_url}/submissions/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                filings = data.get('filings', {}).get('recent', {})
                
                # Extract filing arrays
                accession_numbers = filings.get('accessionNumber', [])
                filing_dates = filings.get('filingDate', [])
                report_dates = filings.get('reportDate', [])
                forms = filings.get('form', [])
                primary_docs = filings.get('primaryDocument', [])
                
                # Build filing list
                filing_list = []
                for i in range(len(accession_numbers)):
                    filing = {
                        'accession_number': accession_numbers[i],
                        'filing_date': filing_dates[i] if i < len(filing_dates) else None,
                        'report_date': report_dates[i] if i < len(report_dates) else None,
                        'form': forms[i] if i < len(forms) else None,
                        'primary_document': primary_docs[i] if i < len(primary_docs) else None,
                        'description': self.filing_types.get(forms[i], '') if i < len(forms) else ''
                    }
                    
                    # Apply filters
                    if filing_type and filing.get('form') != filing_type:
                        continue
                    
                    if start_date and filing.get('filing_date', '9999') < start_date:
                        continue
                    
                    if end_date and filing.get('filing_date', '0000') > end_date:
                        continue
                    
                    filing_list.append(filing)
                    
                    if len(filing_list) >= limit:
                        break
                
                return {
                    'cik': cik,
                    'name': data.get('name'),
                    'filing_count': len(filing_list),
                    'filings': filing_list
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get company filings: {e}")
            raise ValueError(f"Failed to get company filings: {str(e)}")


class SECGetCompanyFactsTool(SECEdgarBaseTool):
    """
    Tool to retrieve company XBRL facts (structured financial data)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_company_facts',
            'description': 'Retrieve all XBRL financial facts reported by a company in structured format',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company facts"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company facts"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "entity_name": {
                    "type": "string",
                    "description": "Company entity name"
                },
                "facts": {
                    "type": "object",
                    "description": "XBRL facts organized by taxonomy (us-gaap, dei, etc.)",
                    "additionalProperties": {
                        "type": "object",
                        "description": "Facts for a specific taxonomy"
                    }
                }
            },
            "required": ["cik", "entity_name", "facts"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company facts retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        
        try:
            url = f"{self.api_url}/api/xbrl/companyfacts/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                return {
                    'cik': cik,
                    'entity_name': data.get('entityName'),
                    'facts': data.get('facts', {})
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Company facts not found: CIK {cik}")
            else:
                raise ValueError(f"Failed to get company facts: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Failed to get company facts: {e}")
            raise ValueError(f"Failed to get company facts: {str(e)}")


class SECGetFinancialDataTool(SECEdgarBaseTool):
    """
    Tool to retrieve specific financial metrics from company XBRL data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_financial_data',
            'description': 'Retrieve specific financial metrics (Assets, Revenue, Net Income, etc.) from company XBRL filings',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for financial data"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                },
                "fact_type": {
                    "type": "string",
                    "description": "Type of financial fact/metric to retrieve",
                    "enum": [
                        "Assets", "Liabilities", "StockholdersEquity",
                        "Revenues", "NetIncomeLoss", "EarningsPerShare",
                        "Cash", "OperatingIncome", "GrossProfit",
                        "CurrentAssets", "CurrentLiabilities", "LongTermDebt"
                    ]
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for financial data"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "entity_name": {
                    "type": "string",
                    "description": "Company entity name"
                },
                "fact_type": {
                    "type": "string",
                    "description": "Financial fact type requested"
                },
                "available_facts": {
                    "type": "object",
                    "description": "Summary of all available facts (when fact_type not specified)"
                },
                "data": {
                    "type": "array",
                    "description": "Financial data for the requested fact type",
                    "items": {
                        "type": "object",
                        "properties": {
                            "taxonomy": {
                                "type": "string",
                                "description": "Taxonomy source (e.g., us-gaap)"
                            },
                            "label": {
                                "type": "string",
                                "description": "Human-readable label"
                            },
                            "description": {
                                "type": "string",
                                "description": "Fact description"
                            },
                            "units": {
                                "type": "object",
                                "description": "Data values organized by unit (USD, shares, etc.)"
                            }
                        }
                    }
                }
            },
            "required": ["cik", "entity_name"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute financial data retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        fact_type = arguments.get('fact_type')
        
        try:
            # Get company facts
            url = f"{self.api_url}/api/xbrl/companyfacts/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                facts = data.get('facts', {})
                entity_name = data.get('entityName')
                
                if not fact_type:
                    # Return summary of available facts
                    summary = {}
                    for taxonomy in facts:
                        summary[taxonomy] = list(facts[taxonomy].keys())
                    
                    return {
                        'cik': cik,
                        'entity_name': entity_name,
                        'available_facts': summary
                    }
                
                # Search for specific fact type across taxonomies
                result = {
                    'cik': cik,
                    'entity_name': entity_name,
                    'fact_type': fact_type,
                    'data': []
                }
                
                for taxonomy, taxonomy_facts in facts.items():
                    if fact_type in taxonomy_facts:
                        fact_data = taxonomy_facts[fact_type]
                        result['data'].append({
                            'taxonomy': taxonomy,
                            'label': fact_data.get('label'),
                            'description': fact_data.get('description'),
                            'units': fact_data.get('units', {})
                        })
                
                return result
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Company facts not found: CIK {cik}")
            else:
                raise ValueError(f"Failed to get financial data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Failed to get financial data: {e}")
            raise ValueError(f"Failed to get financial data: {str(e)}")


class SECGetInsiderTradingTool(SECEdgarBaseTool):
    """
    Tool to retrieve insider trading reports (Form 4)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_insider_trading',
            'description': 'Retrieve insider trading reports (Form 4) for company insiders and executives',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for insider trading"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of Form 4 filings to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for insider trading"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "name": {
                    "type": "string",
                    "description": "Company name"
                },
                "filing_count": {
                    "type": "integer",
                    "description": "Number of Form 4 filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of insider trading filings (Form 4)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accession_number": {
                                "type": "string",
                                "description": "Unique filing identifier"
                            },
                            "filing_date": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "report_date": {
                                "type": "string",
                                "description": "Transaction date"
                            },
                            "form": {
                                "type": "string",
                                "description": "Form type (will be '4')"
                            },
                            "primary_document": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "description": {
                                "type": "string",
                                "description": "Filing description"
                            }
                        }
                    }
                }
            },
            "required": ["cik", "name", "filing_count", "filings"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute insider trading retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        limit = arguments.get('limit', 10)
        
        try:
            url = f"{self.api_url}/submissions/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                filings = data.get('filings', {}).get('recent', {})
                
                # Extract filing arrays
                accession_numbers = filings.get('accessionNumber', [])
                filing_dates = filings.get('filingDate', [])
                report_dates = filings.get('reportDate', [])
                forms = filings.get('form', [])
                primary_docs = filings.get('primaryDocument', [])
                
                # Build Form 4 filing list
                filing_list = []
                for i in range(len(accession_numbers)):
                    if i < len(forms) and forms[i] == '4':
                        filing_list.append({
                            'accession_number': accession_numbers[i],
                            'filing_date': filing_dates[i] if i < len(filing_dates) else None,
                            'report_date': report_dates[i] if i < len(report_dates) else None,
                            'form': forms[i],
                            'primary_document': primary_docs[i] if i < len(primary_docs) else None,
                            'description': 'Statement of Changes in Beneficial Ownership'
                        })
                    
                    if len(filing_list) >= limit:
                        break
                
                return {
                    'cik': cik,
                    'name': data.get('name'),
                    'filing_count': len(filing_list),
                    'filings': filing_list
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get insider trading data: {e}")
            raise ValueError(f"Failed to get insider trading data: {str(e)}")


class SECGetMutualFundHoldingsTool(SECEdgarBaseTool):
    """
    Tool to retrieve institutional investment manager holdings (Form 13F)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sec_get_mutual_fund_holdings',
            'description': 'Retrieve institutional investment manager holdings reports (Form 13F-HR)',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for mutual fund holdings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of Form 13F filings to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20
                }
            },
            "oneOf": [
                {"required": ["cik"]},
                {"required": ["ticker"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for mutual fund holdings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "10-digit Central Index Key"
                },
                "name": {
                    "type": "string",
                    "description": "Institution name"
                },
                "filing_count": {
                    "type": "integer",
                    "description": "Number of Form 13F filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of Form 13F holdings reports",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accession_number": {
                                "type": "string",
                                "description": "Unique filing identifier"
                            },
                            "filing_date": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "report_date": {
                                "type": "string",
                                "description": "Period end date for holdings"
                            },
                            "form": {
                                "type": "string",
                                "description": "Form type (will be '13F-HR')"
                            },
                            "primary_document": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "description": {
                                "type": "string",
                                "description": "Filing description"
                            }
                        }
                    }
                }
            },
            "required": ["cik", "name", "filing_count", "filings"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute mutual fund holdings retrieval"""
        cik = self._get_cik_from_args(
            arguments.get('cik'),
            arguments.get('ticker')
        )
        limit = arguments.get('limit', 5)
        
        try:
            url = f"{self.api_url}/submissions/CIK{cik}.json"
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                filings = data.get('filings', {}).get('recent', {})
                
                # Extract filing arrays
                accession_numbers = filings.get('accessionNumber', [])
                filing_dates = filings.get('filingDate', [])
                report_dates = filings.get('reportDate', [])
                forms = filings.get('form', [])
                primary_docs = filings.get('primaryDocument', [])
                
                # Build Form 13F filing list
                filing_list = []
                for i in range(len(accession_numbers)):
                    if i < len(forms) and forms[i] == '13F-HR':
                        filing_list.append({
                            'accession_number': accession_numbers[i],
                            'filing_date': filing_dates[i] if i < len(filing_dates) else None,
                            'report_date': report_dates[i] if i < len(report_dates) else None,
                            'form': forms[i],
                            'primary_document': primary_docs[i] if i < len(primary_docs) else None,
                            'description': 'Institutional Investment Manager Holdings'
                        })
                    
                    if len(filing_list) >= limit:
                        break
                
                return {
                    'cik': cik,
                    'name': data.get('name'),
                    'filing_count': len(filing_list),
                    'filings': filing_list
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get mutual fund holdings: {e}")
            raise ValueError(f"Failed to get mutual fund holdings: {str(e)}")


# Tool registry for easy access
SEC_EDGAR_TOOLS = {
    'sec_search_company': SECSearchCompanyTool,
    'sec_get_company_info': SECGetCompanyInfoTool,
    'sec_get_company_filings': SECGetCompanyFilingsTool,
    'sec_get_company_facts': SECGetCompanyFactsTool,
    'sec_get_financial_data': SECGetFinancialDataTool,
    'sec_get_insider_trading': SECGetInsiderTradingTool,
    'sec_get_mutual_fund_holdings': SECGetMutualFundHoldingsTool
}
