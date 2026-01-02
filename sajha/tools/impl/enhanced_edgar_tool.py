"""
Copyright All Rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Enhanced SEC EDGAR MCP Tool Implementation
Comprehensive access to SEC EDGAR database through multiple specialized tools

This module provides granular access to various SEC EDGAR APIs including:
- Company search and information
- Filing submissions and documents
- Financial facts and XBRL data
- Insider transactions
- Institutional holdings
- Mutual fund holdings
"""

import json
import urllib.parse
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import time
import re

# Import base tool class
import sys
import os
sys.path.insert(0, '/mnt/user-data/uploads')
from sajha.tools.base_mcp_tool import BaseMCPTool


class EDGARBaseTool(BaseMCPTool):
    """
    Base class for SEC EDGAR tools with shared functionality
    
    Implements rate limiting, request handling, and common utilities
    for interacting with SEC EDGAR APIs.
    """
    
    def __init__(self, config: Dict = None):
        """Initialize EDGAR base tool"""
        super().__init__(config)
        
        # SEC EDGAR API endpoints
        self.base_url = "https://data.sec.gov"
        self.submissions_url = f"{self.base_url}/submissions"
        self.company_tickers_url = f"{self.base_url}/files/company_tickers.json"
        
        # Required headers for SEC API (User-Agent is MANDATORY per SEC requirements)
        self.headers = {
            'User-Agent': 'Enhanced EDGAR Tool ashutosh.sinha@research.com',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
        
        # Rate limiting: SEC allows 10 requests per second
        self.rate_limit_delay = 0.11  # 110ms between requests
        self.last_request_time = 0
        
        # Common form types
        self.form_types = {
            '10-K': 'Annual Report',
            '10-Q': 'Quarterly Report',
            '8-K': 'Current Report',
            '4': 'Statement of Changes in Beneficial Ownership',
            '3': 'Initial Statement of Beneficial Ownership',
            '5': 'Annual Statement of Beneficial Ownership',
            'S-1': 'Registration Statement',
            'S-3': 'Registration Statement',
            'S-4': 'Registration Statement (Business Combination)',
            'S-8': 'Registration Statement (Employee Benefit Plan)',
            'DEF 14A': 'Proxy Statement',
            '13F-HR': 'Institutional Investment Manager Holdings',
            '13F-NT': 'Notice of Confidential Treatment',
            '20-F': 'Annual Report (Foreign Private Issuer)',
            '6-K': 'Current Report (Foreign Private Issuer)',
            '40-F': 'Annual Report (Canadian Issuer)',
            '424B2': 'Prospectus',
            '424B3': 'Prospectus',
            '424B4': 'Prospectus',
            '424B5': 'Prospectus',
            'SC 13D': 'Beneficial Ownership Report',
            'SC 13G': 'Beneficial Ownership Report (Passive)',
            'SC 13G/A': 'Beneficial Ownership Report Amendment',
            '144': 'Notice of Proposed Sale of Securities',
            'N-Q': 'Quarterly Schedule of Portfolio Holdings (Mutual Fund)',
            'N-CSR': 'Certified Shareholder Report (Mutual Fund)',
            'N-PORT': 'Monthly Portfolio Investments Report',
            'NPORT-P': 'Monthly Portfolio Investments Report'
        }
        
        # Cache for company tickers (to avoid repeated API calls)
        self._tickers_cache = None
        self._tickers_cache_time = None
        self._cache_ttl = 3600  # 1 hour
    
    def _rate_limit(self):
        """Enforce rate limiting for SEC API (10 requests per second max)"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        
        self.last_request_time = time.time()
    
    def _make_request(self, url: str) -> Union[Dict, List]:
        """
        Make HTTP request to SEC API with rate limiting
        
        Args:
            url: Full URL to request
            
        Returns:
            JSON response as dictionary or list
            
        Raises:
            ValueError: On HTTP errors or invalid responses
        """
        self._rate_limit()
        
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode('utf-8')
                return json.loads(content)
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Resource not found: {url}")
            elif e.code == 403:
                raise ValueError("Access forbidden. Ensure User-Agent header is properly set.")
            elif e.code == 429:
                raise ValueError("Rate limit exceeded. SEC allows max 10 requests/second.")
            else:
                raise ValueError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise ValueError(f"Network error: {str(e)}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            raise ValueError(f"Request failed: {str(e)}")
    
    def _format_cik(self, cik: Union[str, int]) -> str:
        """
        Format CIK to 10-digit format with leading zeros
        
        Args:
            cik: CIK number as string or integer
            
        Returns:
            10-digit CIK string
        """
        return str(cik).strip().zfill(10)
    
    def _get_company_tickers(self, use_cache: bool = True) -> Dict:
        """
        Get company tickers database with caching
        
        Args:
            use_cache: Whether to use cached data
            
        Returns:
            Company tickers dictionary
        """
        current_time = time.time()
        
        # Check cache
        if (use_cache and self._tickers_cache and self._tickers_cache_time and
            (current_time - self._tickers_cache_time) < self._cache_ttl):
            return self._tickers_cache
        
        # Fetch fresh data
        self._tickers_cache = self._make_request(self.company_tickers_url)
        self._tickers_cache_time = current_time
        
        return self._tickers_cache


class EDGARCompanySearchTool(EDGARBaseTool):
    """
    Tool to search for companies in SEC EDGAR database by name or ticker symbol
    
    Provides fast lookup of company CIK numbers needed for other EDGAR API calls.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_company_search',
            'description': 'Search for public companies in SEC EDGAR database by company name or ticker symbol',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Company name or ticker symbol to search for (e.g., 'Apple Inc', 'AAPL')"
                },
                "search_type": {
                    "type": "string",
                    "description": "Type of search to perform",
                    "enum": ["name", "ticker", "auto"],
                    "default": "auto"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company search"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Original search query"
                },
                "results_count": {
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
                                "description": "Central Index Key (10-digit identifier)"
                            },
                            "ticker": {
                                "type": "string",
                                "description": "Stock ticker symbol"
                            },
                            "title": {
                                "type": "string",
                                "description": "Company name"
                            },
                            "exchange": {
                                "type": "string",
                                "description": "Stock exchange where traded"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company search"""
        query = arguments.get('query', '').strip()
        search_type = arguments.get('search_type', 'auto')
        limit = arguments.get('limit', 10)
        
        if not query:
            raise ValueError("Query parameter is required")
        
        # Fetch company tickers database
        tickers_data = self._get_company_tickers()
        
        # Convert to list format for searching
        companies_list = []
        for key, company in tickers_data.items():
            if isinstance(company, dict):
                companies_list.append(company)
        
        # Perform search
        results = []
        query_upper = query.upper()
        query_lower = query.lower()
        
        for company in companies_list:
            match = False
            priority = 2  # Default priority
            
            if search_type in ['auto', 'ticker']:
                ticker = company.get('ticker', '').upper()
                if query_upper == ticker:
                    match = True
                    priority = 0  # Exact ticker match (highest priority)
            
            if search_type in ['auto', 'name']:
                title = company.get('title', '').lower()
                if query_lower in title:
                    match = True
                    if title.startswith(query_lower):
                        priority = min(priority, 1)  # Name starts with query
            
            if match:
                results.append({
                    'priority': priority,
                    'data': {
                        'cik': self._format_cik(company.get('cik_str', '')),
                        'ticker': company.get('ticker', ''),
                        'title': company.get('title', ''),
                        'exchange': company.get('exchange', 'N/A')
                    }
                })
        
        # Sort by priority and limit results
        results.sort(key=lambda x: x['priority'])
        companies = [r['data'] for r in results[:limit]]
        
        return {
            'query': query,
            'results_count': len(companies),
            'companies': companies
        }


class EDGARCompanySubmissionsTool(EDGARBaseTool):
    """
    Tool to retrieve company filing submissions and metadata
    
    Returns comprehensive information about a company's SEC filings including
    recent filings, historical filings, and company information.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_company_submissions',
            'description': 'Retrieve comprehensive filing submissions and company information from SEC EDGAR',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company submissions"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit identifier or shorter format"
                },
                "include_old_filings": {
                    "type": "boolean",
                    "description": "Include historical filings (may require additional API calls)",
                    "default": False
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company submissions"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "name": {
                    "type": "string",
                    "description": "Company name"
                },
                "sic": {
                    "type": "string",
                    "description": "Standard Industrial Classification code"
                },
                "sicDescription": {
                    "type": "string",
                    "description": "SIC code description"
                },
                "category": {
                    "type": "string",
                    "description": "Filer category (e.g., 'Large Accelerated Filer')"
                },
                "fiscalYearEnd": {
                    "type": "string",
                    "description": "Fiscal year end (MMDD format)"
                },
                "stateOfIncorporation": {
                    "type": "string",
                    "description": "State of incorporation"
                },
                "addresses": {
                    "type": "object",
                    "description": "Business and mailing addresses"
                },
                "filings_count": {
                    "type": "integer",
                    "description": "Total number of filings available"
                },
                "recent_filings": {
                    "type": "array",
                    "description": "Recent filing submissions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {
                                "type": "string",
                                "description": "Filing accession number"
                            },
                            "filingDate": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "reportDate": {
                                "type": "string",
                                "description": "Report period end date"
                            },
                            "form": {
                                "type": "string",
                                "description": "Form type (e.g., '10-K', '10-Q')"
                            },
                            "primaryDocument": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "primaryDocDescription": {
                                "type": "string",
                                "description": "Primary document description"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company submissions retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        include_old = arguments.get('include_old_filings', False)
        
        if not cik:
            raise ValueError("CIK parameter is required")
        
        # Fetch submissions data
        url = f"{self.submissions_url}/CIK{cik}.json"
        data = self._make_request(url)
        
        # Extract recent filings
        recent = data.get('filings', {}).get('recent', {})
        filings = []
        
        if recent:
            # Convert parallel arrays to list of objects
            fields = ['accessionNumber', 'filingDate', 'reportDate', 'form', 
                     'primaryDocument', 'primaryDocDescription']
            
            length = len(recent.get('accessionNumber', []))
            for i in range(length):
                filing = {}
                for field in fields:
                    filing[field] = recent.get(field, [])[i] if i < len(recent.get(field, [])) else None
                filings.append(filing)
        
        # Build response
        result = {
            'cik': cik,
            'name': data.get('name', ''),
            'sic': data.get('sic', ''),
            'sicDescription': data.get('sicDescription', ''),
            'category': data.get('category', ''),
            'fiscalYearEnd': data.get('fiscalYearEnd', ''),
            'stateOfIncorporation': data.get('stateOfIncorporation', ''),
            'addresses': {
                'business': data.get('addresses', {}).get('business', {}),
                'mailing': data.get('addresses', {}).get('mailing', {})
            },
            'filings_count': len(filings),
            'recent_filings': filings
        }
        
        return result


class EDGARCompanyFactsTool(EDGARBaseTool):
    """
    Tool to retrieve company financial facts from XBRL filings
    
    Provides structured financial data including income statement, balance sheet,
    and cash flow statement items reported in XBRL format.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_company_facts',
            'description': 'Retrieve structured financial facts and XBRL data for a company',
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
                    "description": "Central Index Key (CIK) - 10 digit identifier or shorter format"
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company facts"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "entityName": {
                    "type": "string",
                    "description": "Company name"
                },
                "facts_count": {
                    "type": "integer",
                    "description": "Number of distinct facts/concepts available"
                },
                "taxonomies": {
                    "type": "array",
                    "description": "Available XBRL taxonomies (e.g., 'us-gaap', 'dei', 'srt')",
                    "items": {"type": "string"}
                },
                "facts": {
                    "type": "object",
                    "description": "Financial facts organized by taxonomy",
                    "additionalProperties": {
                        "type": "object",
                        "description": "Facts for specific taxonomy"
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company facts retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        
        if not cik:
            raise ValueError("CIK parameter is required")
        
        # Fetch company facts
        url = f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json"
        data = self._make_request(url)
        
        # Extract facts information
        facts = data.get('facts', {})
        taxonomies = list(facts.keys())
        
        # Count total facts
        facts_count = sum(len(taxonomy_facts) for taxonomy_facts in facts.values())
        
        return {
            'cik': cik,
            'entityName': data.get('entityName', ''),
            'facts_count': facts_count,
            'taxonomies': taxonomies,
            'facts': facts
        }


class EDGARCompanyConceptTool(EDGARBaseTool):
    """
    Tool to retrieve specific financial concept data for a company
    
    Retrieves all historical values for a specific XBRL concept/fact
    (e.g., Revenue, Assets, EPS) across all filings.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_company_concept',
            'description': 'Retrieve historical data for a specific financial concept/metric',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for company concept"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK)"
                },
                "taxonomy": {
                    "type": "string",
                    "description": "XBRL taxonomy (e.g., 'us-gaap', 'ifrs-full', 'dei')",
                    "default": "us-gaap"
                },
                "concept": {
                    "type": "string",
                    "description": "XBRL concept/tag (e.g., 'Revenue', 'Assets', 'EarningsPerShareBasic')"
                }
            },
            "required": ["cik", "concept"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for company concept"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "taxonomy": {
                    "type": "string",
                    "description": "XBRL taxonomy"
                },
                "tag": {
                    "type": "string",
                    "description": "XBRL concept tag"
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable label for the concept"
                },
                "description": {
                    "type": "string",
                    "description": "Concept description"
                },
                "entityName": {
                    "type": "string",
                    "description": "Company name"
                },
                "units_count": {
                    "type": "integer",
                    "description": "Number of different unit types (USD, shares, etc.)"
                },
                "units": {
                    "type": "object",
                    "description": "Historical values organized by unit type",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "end": {
                                    "type": "string",
                                    "description": "Period end date"
                                },
                                "val": {
                                    "type": "number",
                                    "description": "Value"
                                },
                                "accn": {
                                    "type": "string",
                                    "description": "Accession number"
                                },
                                "fy": {
                                    "type": "integer",
                                    "description": "Fiscal year"
                                },
                                "fp": {
                                    "type": "string",
                                    "description": "Fiscal period (Q1, Q2, Q3, FY)"
                                },
                                "form": {
                                    "type": "string",
                                    "description": "Form type"
                                },
                                "filed": {
                                    "type": "string",
                                    "description": "Filing date"
                                }
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute company concept retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        taxonomy = arguments.get('taxonomy', 'us-gaap')
        concept = arguments.get('concept', '')
        
        if not cik or not concept:
            raise ValueError("CIK and concept parameters are required")
        
        # Fetch company concept data
        url = f"{self.base_url}/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
        data = self._make_request(url)
        
        # Extract units information
        units = data.get('units', {})
        units_count = len(units)
        
        return {
            'cik': cik,
            'taxonomy': taxonomy,
            'tag': data.get('tag', ''),
            'label': data.get('label', ''),
            'description': data.get('description', ''),
            'entityName': data.get('entityName', ''),
            'units_count': units_count,
            'units': units
        }


class EDGARFilingsByFormTool(EDGARBaseTool):
    """
    Tool to search and filter company filings by form type
    
    Filters a company's submissions to return only specific form types
    (e.g., all 10-K annual reports or all 8-K current reports).
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_filings_by_form',
            'description': 'Search company filings filtered by form type (10-K, 10-Q, 8-K, etc.)',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for filings by form"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK)"
                },
                "form_type": {
                    "type": "string",
                    "description": "Form type to filter (e.g., '10-K', '10-Q', '8-K', 'DEF 14A')"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD format)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of filings to return (1-500)",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50
                }
            },
            "required": ["cik", "form_type"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for filings by form"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name"
                },
                "form_type": {
                    "type": "string",
                    "description": "Form type filtered"
                },
                "form_description": {
                    "type": "string",
                    "description": "Description of form type"
                },
                "filings_count": {
                    "type": "integer",
                    "description": "Number of filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of matching filings",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {
                                "type": "string",
                                "description": "Filing accession number"
                            },
                            "filingDate": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "reportDate": {
                                "type": "string",
                                "description": "Report period end date"
                            },
                            "form": {
                                "type": "string",
                                "description": "Form type"
                            },
                            "primaryDocument": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "primaryDocDescription": {
                                "type": "string",
                                "description": "Primary document description"
                            },
                            "document_url": {
                                "type": "string",
                                "description": "URL to access the filing document"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute filings by form search"""
        cik = self._format_cik(arguments.get('cik', ''))
        form_type = arguments.get('form_type', '').upper()
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit', 50)
        
        if not cik or not form_type:
            raise ValueError("CIK and form_type parameters are required")
        
        # Fetch submissions data
        url = f"{self.submissions_url}/CIK{cik}.json"
        data = self._make_request(url)
        
        company_name = data.get('name', '')
        
        # Extract recent filings
        recent = data.get('filings', {}).get('recent', {})
        
        # Filter by form type
        filtered_filings = []
        if recent:
            forms = recent.get('form', [])
            for i, form in enumerate(forms):
                if form.upper() == form_type:
                    filing_date = recent.get('filingDate', [])[i]
                    
                    # Apply date filters
                    if start_date and filing_date < start_date:
                        continue
                    if end_date and filing_date > end_date:
                        continue
                    
                    accession = recent.get('accessionNumber', [])[i]
                    accession_no_dashes = accession.replace('-', '')
                    
                    filing = {
                        'accessionNumber': accession,
                        'filingDate': filing_date,
                        'reportDate': recent.get('reportDate', [])[i] if i < len(recent.get('reportDate', [])) else None,
                        'form': form,
                        'primaryDocument': recent.get('primaryDocument', [])[i] if i < len(recent.get('primaryDocument', [])) else None,
                        'primaryDocDescription': recent.get('primaryDocDescription', [])[i] if i < len(recent.get('primaryDocDescription', [])) else None,
                        'document_url': f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession_no_dashes}"
                    }
                    filtered_filings.append(filing)
                    
                    if len(filtered_filings) >= limit:
                        break
        
        return {
            'cik': cik,
            'company_name': company_name,
            'form_type': form_type,
            'form_description': self.form_types.get(form_type, 'Unknown form type'),
            'filings_count': len(filtered_filings),
            'filings': filtered_filings
        }


class EDGARInsiderTransactionsTool(EDGARBaseTool):
    """
    Tool to retrieve insider trading transactions (Form 4 filings)
    
    Returns recent insider buy/sell transactions reported on Form 4.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_insider_transactions',
            'description': 'Retrieve insider trading transactions (Form 4) for a company',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for insider transactions"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of transactions to return (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for insider transactions"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name"
                },
                "transactions_count": {
                    "type": "integer",
                    "description": "Number of Form 4 filings returned"
                },
                "transactions": {
                    "type": "array",
                    "description": "List of insider transaction filings",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {
                                "type": "string",
                                "description": "Filing accession number"
                            },
                            "filingDate": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "reportDate": {
                                "type": "string",
                                "description": "Transaction report date"
                            },
                            "primaryDocument": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "document_url": {
                                "type": "string",
                                "description": "URL to access the filing"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute insider transactions retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        limit = arguments.get('limit', 20)
        
        if not cik:
            raise ValueError("CIK parameter is required")
        
        # Use the filings by form functionality
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': '4',
            'limit': limit
        })
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'transactions_count': result.get('filings_count', 0),
            'transactions': result.get('filings', [])
        }


class EDGARInstitutionalHoldingsTool(EDGARBaseTool):
    """
    Tool to retrieve institutional investment holdings (Form 13F)
    
    Returns 13F-HR filings showing institutional investment positions.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_institutional_holdings',
            'description': 'Retrieve institutional investment holdings (Form 13F) for an institutional manager',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for institutional holdings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) of institutional manager"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of 13F filings to return (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for institutional holdings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "manager_name": {
                    "type": "string",
                    "description": "Investment manager name"
                },
                "filings_count": {
                    "type": "integer",
                    "description": "Number of 13F filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of 13F-HR filings",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {
                                "type": "string",
                                "description": "Filing accession number"
                            },
                            "filingDate": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "reportDate": {
                                "type": "string",
                                "description": "Report period end date"
                            },
                            "primaryDocument": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "document_url": {
                                "type": "string",
                                "description": "URL to access the filing"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute institutional holdings retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        limit = arguments.get('limit', 10)
        
        if not cik:
            raise ValueError("CIK parameter is required")
        
        # Use the filings by form functionality
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': '13F-HR',
            'limit': limit
        })
        
        return {
            'cik': cik,
            'manager_name': result.get('company_name', ''),
            'filings_count': result.get('filings_count', 0),
            'filings': result.get('filings', [])
        }


class EDGARMutualFundHoldingsTool(EDGARBaseTool):
    """
    Tool to retrieve mutual fund portfolio holdings (Form N-PORT)
    
    Returns N-PORT filings showing mutual fund portfolio positions.
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_mutual_fund_holdings',
            'description': 'Retrieve mutual fund portfolio holdings (Form N-PORT)',
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
                    "description": "Central Index Key (CIK) of mutual fund"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of N-PORT filings to return (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for mutual fund holdings"""
        return {
            "type": "object",
            "properties": {
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "fund_name": {
                    "type": "string",
                    "description": "Mutual fund name"
                },
                "filings_count": {
                    "type": "integer",
                    "description": "Number of N-PORT filings returned"
                },
                "filings": {
                    "type": "array",
                    "description": "List of N-PORT filings",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {
                                "type": "string",
                                "description": "Filing accession number"
                            },
                            "filingDate": {
                                "type": "string",
                                "description": "Date filed with SEC"
                            },
                            "reportDate": {
                                "type": "string",
                                "description": "Report period end date"
                            },
                            "primaryDocument": {
                                "type": "string",
                                "description": "Primary document filename"
                            },
                            "document_url": {
                                "type": "string",
                                "description": "URL to access the filing"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute mutual fund holdings retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        limit = arguments.get('limit', 10)
        
        if not cik:
            raise ValueError("CIK parameter is required")
        
        # Use the filings by form functionality  
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': 'NPORT-P',
            'limit': limit
        })
        
        return {
            'cik': cik,
            'fund_name': result.get('company_name', ''),
            'filings_count': result.get('filings_count', 0),
            'filings': result.get('filings', [])
        }


class EDGARFrameDataTool(EDGARBaseTool):
    """
    Tool to retrieve aggregated XBRL frame data across all companies
    
    Returns aggregated data for a specific XBRL concept across all filers
    for a given time period (useful for market-wide analysis).
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_frame_data',
            'description': 'Retrieve aggregated XBRL frame data across all companies for market analysis',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for frame data"""
        return {
            "type": "object",
            "properties": {
                "taxonomy": {
                    "type": "string",
                    "description": "XBRL taxonomy (e.g., 'us-gaap')",
                    "default": "us-gaap"
                },
                "concept": {
                    "type": "string",
                    "description": "XBRL concept (e.g., 'Revenue', 'Assets')"
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measure (e.g., 'USD', 'shares')",
                    "default": "USD"
                },
                "year": {
                    "type": "integer",
                    "description": "Calendar year (e.g., 2023)",
                    "minimum": 2009,
                    "maximum": 2030
                },
                "quarter": {
                    "type": "string",
                    "description": "Fiscal quarter (Q1, Q2, Q3, Q4) or 'CY' for full year",
                    "enum": ["Q1", "Q2", "Q3", "Q4", "CY"],
                    "default": "CY"
                }
            },
            "required": ["concept", "year"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for frame data"""
        return {
            "type": "object",
            "properties": {
                "taxonomy": {
                    "type": "string",
                    "description": "XBRL taxonomy"
                },
                "tag": {
                    "type": "string",
                    "description": "XBRL concept tag"
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable label"
                },
                "description": {
                    "type": "string",
                    "description": "Concept description"
                },
                "frame": {
                    "type": "string",
                    "description": "Frame identifier (e.g., 'CY2023Q4')"
                },
                "units_count": {
                    "type": "integer",
                    "description": "Number of company data points"
                },
                "data": {
                    "type": "array",
                    "description": "Company-level data points",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cik": {
                                "type": "string",
                                "description": "Company CIK"
                            },
                            "entityName": {
                                "type": "string",
                                "description": "Company name"
                            },
                            "loc": {
                                "type": "string",
                                "description": "Location"
                            },
                            "val": {
                                "type": "number",
                                "description": "Value"
                            },
                            "accn": {
                                "type": "string",
                                "description": "Accession number"
                            },
                            "filed": {
                                "type": "string",
                                "description": "Filing date"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute frame data retrieval"""
        taxonomy = arguments.get('taxonomy', 'us-gaap')
        concept = arguments.get('concept', '')
        unit = arguments.get('unit', 'USD')
        year = arguments.get('year')
        quarter = arguments.get('quarter', 'CY')
        
        if not concept or not year:
            raise ValueError("Concept and year parameters are required")
        
        # Construct frame identifier
        if quarter == 'CY':
            frame = f"CY{year}"
        else:
            frame = f"CY{year}{quarter}"
        
        # Fetch frame data
        url = f"{self.base_url}/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{frame}.json"
        data = self._make_request(url)
        
        # Extract data points
        data_points = data.get('data', [])
        
        return {
            'taxonomy': taxonomy,
            'tag': data.get('tag', ''),
            'label': data.get('label', ''),
            'description': data.get('description', ''),
            'frame': frame,
            'units_count': len(data_points),
            'data': data_points
        }


class EDGARCompanyTickersByExchangeTool(EDGARBaseTool):
    """
    Tool to retrieve all companies listed on a specific exchange
    
    Returns companies filtered by stock exchange (NYSE, NASDAQ, etc.)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_company_tickers_by_exchange',
            'description': 'Get all public companies listed on a specific stock exchange',
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
                "exchange": {
                    "type": "string",
                    "description": "Stock exchange code",
                    "enum": ["Nasdaq", "NYSE", "AMEX", "BATS", "OTC"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of companies to return",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 100
                }
            },
            "required": ["exchange"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "exchange": {"type": "string"},
                "companies_count": {"type": "integer"},
                "companies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cik": {"type": "string"},
                            "ticker": {"type": "string"},
                            "title": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute exchange filter"""
        exchange = arguments.get('exchange', '')
        limit = arguments.get('limit', 100)
        
        tickers_data = self._get_company_tickers()
        
        companies = []
        for key, company in tickers_data.items():
            if isinstance(company, dict) and company.get('exchange', '') == exchange:
                companies.append({
                    'cik': self._format_cik(company.get('cik_str', '')),
                    'ticker': company.get('ticker', ''),
                    'title': company.get('title', '')
                })
                if len(companies) >= limit:
                    break
        
        return {
            'exchange': exchange,
            'companies_count': len(companies),
            'companies': companies
        }


class EDGARCompaniesBySICTool(EDGARBaseTool):
    """
    Tool to search companies by Standard Industrial Classification (SIC) code
    
    Enables industry-based company discovery and sector analysis
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_companies_by_sic',
            'description': 'Search companies by Standard Industrial Classification (SIC) code for industry analysis',
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
                "sic_code": {
                    "type": "string",
                    "description": "4-digit SIC code (e.g., '7372' for software, '6022' for banks)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum companies to return",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50
                }
            },
            "required": ["sic_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "sic_code": {"type": "string"},
                "companies_count": {"type": "integer"},
                "companies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cik": {"type": "string"},
                            "name": {"type": "string"},
                            "sic": {"type": "string"},
                            "sicDescription": {"type": "string"},
                            "fiscalYearEnd": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute SIC search"""
        sic_code = arguments.get('sic_code', '').strip()
        limit = arguments.get('limit', 50)
        
        if not sic_code:
            raise ValueError("SIC code is required")
        
        # Get tickers to find CIKs
        tickers_data = self._get_company_tickers()
        
        companies = []
        for key, company in tickers_data.items():
            if isinstance(company, dict):
                cik = self._format_cik(company.get('cik_str', ''))
                
                # Fetch company details to get SIC
                try:
                    url = f"{self.submissions_url}/CIK{cik}.json"
                    data = self._make_request(url)
                    
                    if data.get('sic', '') == sic_code:
                        companies.append({
                            'cik': cik,
                            'name': data.get('name', ''),
                            'sic': data.get('sic', ''),
                            'sicDescription': data.get('sicDescription', ''),
                            'fiscalYearEnd': data.get('fiscalYearEnd', '')
                        })
                        
                        if len(companies) >= limit:
                            break
                except:
                    continue
        
        return {
            'sic_code': sic_code,
            'companies_count': len(companies),
            'companies': companies
        }


class EDGARFilingDetailsTool(EDGARBaseTool):
    """
    Tool to get detailed information about a specific filing by accession number
    
    Returns comprehensive filing metadata and document URLs
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_filing_details',
            'description': 'Get detailed information about a specific SEC filing by accession number',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "accession_number": {
                    "type": "string",
                    "description": "Filing accession number (e.g., '0000320193-23-000077')"
                }
            },
            "required": ["cik", "accession_number"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "accessionNumber": {"type": "string"},
                "form": {"type": "string"},
                "filingDate": {"type": "string"},
                "reportDate": {"type": "string"},
                "acceptanceDateTime": {"type": "string"},
                "primaryDocument": {"type": "string"},
                "primaryDocDescription": {"type": "string"},
                "document_url": {"type": "string"},
                "filing_url": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute filing details retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        accession = arguments.get('accession_number', '').replace('-', '')
        
        if not cik or not accession:
            raise ValueError("CIK and accession_number are required")
        
        # Get submissions to find the filing
        url = f"{self.submissions_url}/CIK{cik}.json"
        data = self._make_request(url)
        
        recent = data.get('filings', {}).get('recent', {})
        accessions = recent.get('accessionNumber', [])
        
        # Find matching filing
        for i, acc in enumerate(accessions):
            if acc.replace('-', '') == accession:
                accession_formatted = acc
                form = recent.get('form', [])[i]
                primary_doc = recent.get('primaryDocument', [])[i]
                
                return {
                    'cik': cik,
                    'accessionNumber': acc,
                    'form': form,
                    'filingDate': recent.get('filingDate', [])[i],
                    'reportDate': recent.get('reportDate', [])[i] if i < len(recent.get('reportDate', [])) else None,
                    'acceptanceDateTime': recent.get('acceptanceDateTime', [])[i] if i < len(recent.get('acceptanceDateTime', [])) else None,
                    'primaryDocument': primary_doc,
                    'primaryDocDescription': recent.get('primaryDocDescription', [])[i] if i < len(recent.get('primaryDocDescription', [])) else None,
                    'document_url': f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession}",
                    'filing_url': f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary_doc}"
                }
        
        raise ValueError(f"Filing not found: {accession}")


class EDGAROwnershipReportsTool(EDGARBaseTool):
    """
    Tool to retrieve beneficial ownership reports (SC 13D/G)
    
    Returns activist investor and significant shareholder disclosures
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_ownership_reports',
            'description': 'Retrieve beneficial ownership reports (SC 13D/G) for activist investors and 5%+ shareholders',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key of company"
                },
                "form_type": {
                    "type": "string",
                    "description": "Ownership form type",
                    "enum": ["SC 13D", "SC 13G", "SC 13G/A", "SC 13D/A"],
                    "default": "SC 13D"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum reports to return",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "form_type": {"type": "string"},
                "reports_count": {"type": "integer"},
                "reports": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "form": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute ownership reports retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        form_type = arguments.get('form_type', 'SC 13D')
        limit = arguments.get('limit', 20)
        
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': form_type,
            'limit': limit
        })
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'form_type': form_type,
            'reports_count': result.get('filings_count', 0),
            'reports': result.get('filings', [])
        }


class EDGARProxyStatementsTool(EDGARBaseTool):
    """
    Tool to retrieve proxy statements (DEF 14A)
    
    Returns shareholder voting information, executive compensation, and governance details
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_proxy_statements',
            'description': 'Retrieve proxy statements (DEF 14A) with executive compensation and shareholder voting information',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum proxy statements to return",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "statements_count": {"type": "integer"},
                "statements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "reportDate": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute proxy statements retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        limit = arguments.get('limit', 10)
        
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': 'DEF 14A',
            'limit': limit
        })
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'statements_count': result.get('filings_count', 0),
            'statements': result.get('filings', [])
        }


class EDGARRegistrationStatementsTool(EDGARBaseTool):
    """
    Tool to retrieve registration statements (S-1, S-3, S-4, S-8)
    
    Returns IPO and securities registration filings
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_registration_statements',
            'description': 'Retrieve securities registration statements including IPO filings (S-1, S-3, S-4, S-8)',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "form_type": {
                    "type": "string",
                    "description": "Registration form type",
                    "enum": ["S-1", "S-3", "S-4", "S-8"],
                    "default": "S-1"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum filings to return",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "form_type": {"type": "string"},
                "filings_count": {"type": "integer"},
                "filings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "form": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute registration statements retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        form_type = arguments.get('form_type', 'S-1')
        limit = arguments.get('limit', 10)
        
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': form_type,
            'limit': limit
        })
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'form_type': form_type,
            'filings_count': result.get('filings_count', 0),
            'filings': result.get('filings', [])
        }


class EDGARForeignIssuersTool(EDGARBaseTool):
    """
    Tool to retrieve foreign private issuer filings (20-F, 6-K, 40-F)
    
    Returns annual reports and current reports for foreign companies
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_foreign_issuers',
            'description': 'Retrieve foreign private issuer filings (20-F annual reports, 6-K current reports, 40-F Canadian)',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "form_type": {
                    "type": "string",
                    "description": "Foreign issuer form type",
                    "enum": ["20-F", "6-K", "40-F"],
                    "default": "20-F"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum filings to return",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                }
            },
            "required": ["cik", "form_type"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "form_type": {"type": "string"},
                "form_description": {"type": "string"},
                "filings_count": {"type": "integer"},
                "filings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "reportDate": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute foreign issuer filings retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        form_type = arguments.get('form_type', '20-F')
        limit = arguments.get('limit', 20)
        
        form_tool = EDGARFilingsByFormTool(self.config)
        result = form_tool.execute({
            'cik': cik,
            'form_type': form_type,
            'limit': limit
        })
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'form_type': form_type,
            'form_description': result.get('form_description', ''),
            'filings_count': result.get('filings_count', 0),
            'filings': result.get('filings', [])
        }


class EDGARCurrentReportsTool(EDGARBaseTool):
    """
    Tool to retrieve 8-K current reports (material events)
    
    Returns material corporate event disclosures
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_current_reports',
            'description': 'Retrieve 8-K current reports disclosing material corporate events',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "start_date": {
                    "type": "string",
                    "description": "Filter from date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter to date (YYYY-MM-DD)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum 8-K reports to return",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "reports_count": {"type": "integer"},
                "reports": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "reportDate": {"type": "string"},
                            "primaryDocDescription": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute 8-K current reports retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit', 50)
        
        form_tool = EDGARFilingsByFormTool(self.config)
        params = {
            'cik': cik,
            'form_type': '8-K',
            'limit': limit
        }
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
            
        result = form_tool.execute(params)
        
        return {
            'cik': cik,
            'company_name': result.get('company_name', ''),
            'reports_count': result.get('filings_count', 0),
            'reports': result.get('filings', [])
        }


class EDGARFinancialRatiosTool(EDGARBaseTool):
    """
    Tool to calculate common financial ratios from XBRL data
    
    Computes profitability, liquidity, and solvency ratios
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_financial_ratios',
            'description': 'Calculate common financial ratios (P/E, ROE, ROA, debt ratios, etc.) from XBRL data',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Fiscal year for ratio calculation",
                    "minimum": 2009,
                    "maximum": 2030
                },
                "fiscal_period": {
                    "type": "string",
                    "description": "Fiscal period",
                    "enum": ["FY", "Q1", "Q2", "Q3", "Q4"],
                    "default": "FY"
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "entityName": {"type": "string"},
                "fiscal_year": {"type": "integer"},
                "fiscal_period": {"type": "string"},
                "profitability_ratios": {
                    "type": "object",
                    "properties": {
                        "gross_margin": {"type": "number"},
                        "operating_margin": {"type": "number"},
                        "net_margin": {"type": "number"},
                        "return_on_assets": {"type": "number"},
                        "return_on_equity": {"type": "number"}
                    }
                },
                "liquidity_ratios": {
                    "type": "object",
                    "properties": {
                        "current_ratio": {"type": "number"},
                        "quick_ratio": {"type": "number"},
                        "cash_ratio": {"type": "number"}
                    }
                },
                "solvency_ratios": {
                    "type": "object",
                    "properties": {
                        "debt_to_equity": {"type": "number"},
                        "debt_to_assets": {"type": "number"},
                        "equity_multiplier": {"type": "number"}
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute financial ratios calculation"""
        cik = self._format_cik(arguments.get('cik', ''))
        fiscal_year = arguments.get('fiscal_year')
        fiscal_period = arguments.get('fiscal_period', 'FY')
        
        # Get company facts
        url = f"{self.base_url}/api/xbrl/companyfacts/CIK{cik}.json"
        data = self._make_request(url)
        
        entity_name = data.get('entityName', '')
        facts = data.get('facts', {}).get('us-gaap', {})
        
        # Helper function to get concept value
        def get_value(concept, year=fiscal_year, period=fiscal_period):
            if concept not in facts:
                return None
            units = facts[concept].get('units', {})
            usd_values = units.get('USD', [])
            
            for item in usd_values:
                if item.get('fy') == year and item.get('fp') == period:
                    return item.get('val')
            return None
        
        # Calculate ratios
        revenue = get_value('Revenues') or get_value('RevenueFromContractWithCustomerExcludingAssessedTax')
        gross_profit = get_value('GrossProfit')
        operating_income = get_value('OperatingIncomeLoss')
        net_income = get_value('NetIncomeLoss')
        assets = get_value('Assets')
        current_assets = get_value('AssetsCurrent')
        cash = get_value('CashAndCashEquivalentsAtCarryingValue')
        inventory = get_value('InventoryNet')
        current_liabilities = get_value('LiabilitiesCurrent')
        total_liabilities = get_value('Liabilities')
        equity = get_value('StockholdersEquity')
        
        # Profitability ratios
        profitability = {}
        if revenue:
            if gross_profit:
                profitability['gross_margin'] = round((gross_profit / revenue) * 100, 2)
            if operating_income:
                profitability['operating_margin'] = round((operating_income / revenue) * 100, 2)
            if net_income:
                profitability['net_margin'] = round((net_income / revenue) * 100, 2)
        
        if assets and net_income:
            profitability['return_on_assets'] = round((net_income / assets) * 100, 2)
        
        if equity and net_income:
            profitability['return_on_equity'] = round((net_income / equity) * 100, 2)
        
        # Liquidity ratios
        liquidity = {}
        if current_assets and current_liabilities:
            liquidity['current_ratio'] = round(current_assets / current_liabilities, 2)
            
            if inventory:
                quick_assets = current_assets - inventory
                liquidity['quick_ratio'] = round(quick_assets / current_liabilities, 2)
        
        if cash and current_liabilities:
            liquidity['cash_ratio'] = round(cash / current_liabilities, 2)
        
        # Solvency ratios
        solvency = {}
        if total_liabilities and equity:
            solvency['debt_to_equity'] = round(total_liabilities / equity, 2)
        
        if total_liabilities and assets:
            solvency['debt_to_assets'] = round(total_liabilities / assets, 2)
        
        if assets and equity:
            solvency['equity_multiplier'] = round(assets / equity, 2)
        
        return {
            'cik': cik,
            'entityName': entity_name,
            'fiscal_year': fiscal_year,
            'fiscal_period': fiscal_period,
            'profitability_ratios': profitability,
            'liquidity_ratios': liquidity,
            'solvency_ratios': solvency
        }


class EDGARAmendmentsTool(EDGARBaseTool):
    """
    Tool to track filing amendments (10-K/A, 10-Q/A, etc.)
    
    Returns amended filings to identify corrections and restatements
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_amendments',
            'description': 'Track amended filings (10-K/A, 10-Q/A, 8-K/A) to identify corrections and restatements',
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
                "cik": {
                    "type": "string",
                    "description": "Central Index Key"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum amendments to return",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                }
            },
            "required": ["cik"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "company_name": {"type": "string"},
                "amendments_count": {"type": "integer"},
                "amendments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "accessionNumber": {"type": "string"},
                            "filingDate": {"type": "string"},
                            "form": {"type": "string"},
                            "reportDate": {"type": "string"},
                            "document_url": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute amendments retrieval"""
        cik = self._format_cik(arguments.get('cik', ''))
        limit = arguments.get('limit', 20)
        
        # Get submissions
        url = f"{self.submissions_url}/CIK{cik}.json"
        data = self._make_request(url)
        
        company_name = data.get('name', '')
        recent = data.get('filings', {}).get('recent', {})
        
        # Filter amendments (forms ending with /A)
        amendments = []
        forms = recent.get('form', [])
        for i, form in enumerate(forms):
            if '/A' in form:
                accession = recent.get('accessionNumber', [])[i]
                accession_no_dashes = accession.replace('-', '')
                
                amendments.append({
                    'accessionNumber': accession,
                    'filingDate': recent.get('filingDate', [])[i],
                    'form': form,
                    'reportDate': recent.get('reportDate', [])[i] if i < len(recent.get('reportDate', [])) else None,
                    'document_url': f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession_no_dashes}"
                })
                
                if len(amendments) >= limit:
                    break
        
        return {
            'cik': cik,
            'company_name': company_name,
            'amendments_count': len(amendments),
            'amendments': amendments
        }


class EDGARXBRLFramesMultiConceptTool(EDGARBaseTool):
    """
    Tool to retrieve multiple concepts in a single frame query
    
    Efficient batch retrieval of related metrics across all companies
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'edgar_xbrl_frames_multi_concept',
            'description': 'Retrieve multiple XBRL concepts in a single frame for efficient batch analysis',
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
                "taxonomy": {
                    "type": "string",
                    "description": "XBRL taxonomy",
                    "default": "us-gaap"
                },
                "concepts": {
                    "type": "array",
                    "description": "List of XBRL concepts to retrieve",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measure",
                    "default": "USD"
                },
                "year": {
                    "type": "integer",
                    "description": "Calendar year",
                    "minimum": 2009,
                    "maximum": 2030
                },
                "quarter": {
                    "type": "string",
                    "description": "Fiscal period",
                    "enum": ["Q1", "Q2", "Q3", "Q4", "CY"],
                    "default": "CY"
                }
            },
            "required": ["concepts", "year"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "frame": {"type": "string"},
                "concepts_retrieved": {"type": "integer"},
                "data_by_concept": {
                    "type": "object",
                    "description": "Data organized by concept",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "label": {"type": "string"},
                            "units_count": {"type": "integer"},
                            "data": {"type": "array"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute multi-concept frame retrieval"""
        taxonomy = arguments.get('taxonomy', 'us-gaap')
        concepts = arguments.get('concepts', [])
        unit = arguments.get('unit', 'USD')
        year = arguments.get('year')
        quarter = arguments.get('quarter', 'CY')
        
        if not concepts:
            raise ValueError("At least one concept is required")
        
        # Construct frame identifier
        frame = f"CY{year}{quarter}" if quarter != 'CY' else f"CY{year}"
        
        # Fetch data for each concept
        data_by_concept = {}
        for concept in concepts:
            try:
                url = f"{self.base_url}/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{frame}.json"
                data = self._make_request(url)
                
                data_by_concept[concept] = {
                    'tag': data.get('tag', ''),
                    'label': data.get('label', ''),
                    'units_count': len(data.get('data', [])),
                    'data': data.get('data', [])
                }
            except Exception as e:
                self.logger.warning(f"Failed to get concept {concept}: {e}")
                data_by_concept[concept] = {
                    'error': str(e)
                }
        
        return {
            'frame': frame,
            'concepts_retrieved': len([c for c in data_by_concept.values() if 'error' not in c]),
            'data_by_concept': data_by_concept
        }


# Tool registry for easy access
EDGAR_TOOLS = {
    'edgar_company_search': EDGARCompanySearchTool,
    'edgar_company_submissions': EDGARCompanySubmissionsTool,
    'edgar_company_facts': EDGARCompanyFactsTool,
    'edgar_company_concept': EDGARCompanyConceptTool,
    'edgar_filings_by_form': EDGARFilingsByFormTool,
    'edgar_insider_transactions': EDGARInsiderTransactionsTool,
    'edgar_institutional_holdings': EDGARInstitutionalHoldingsTool,
    'edgar_mutual_fund_holdings': EDGARMutualFundHoldingsTool,
    'edgar_frame_data': EDGARFrameDataTool,
    'edgar_company_tickers_by_exchange': EDGARCompanyTickersByExchangeTool,
    'edgar_companies_by_sic': EDGARCompaniesBySICTool,
    'edgar_filing_details': EDGARFilingDetailsTool,
    'edgar_ownership_reports': EDGAROwnershipReportsTool,
    'edgar_proxy_statements': EDGARProxyStatementsTool,
    'edgar_registration_statements': EDGARRegistrationStatementsTool,
    'edgar_foreign_issuers': EDGARForeignIssuersTool,
    'edgar_current_reports': EDGARCurrentReportsTool,
    'edgar_financial_ratios': EDGARFinancialRatiosTool,
    'edgar_amendments': EDGARAmendmentsTool,
    'edgar_xbrl_frames_multi_concept': EDGARXBRLFramesMultiConceptTool
}


if __name__ == "__main__":
    # Example usage
    print("Enhanced EDGAR MCP Tools")
    print("=" * 60)
    print(f"Available tools: {len(EDGAR_TOOLS)}")
    for tool_name in EDGAR_TOOLS.keys():
        print(f"  - {tool_name}")
