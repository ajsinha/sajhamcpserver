"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
SEC EDGAR MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools.base_mcp_tool import BaseMCPTool

class SECEdgarTool(BaseMCPTool):
    """
    SEC EDGAR API tool for retrieving US company filings and financial data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize SEC EDGAR tool"""
        default_config = {
            'name': 'sec_edgar',
            'description': 'Retrieve company filings and financial data from SEC EDGAR',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
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

    def get_input_schema(self) -> Dict:
        """Get input schema for SEC EDGAR tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_company_info",
                        "get_company_filings",
                        "get_company_facts",
                        "search_company",
                        "get_filing_details",
                        "get_financial_data",
                        "get_insider_trading",
                        "get_mutual_fund_holdings"
                    ]
                },
                "cik": {
                    "type": "string",
                    "description": "Central Index Key (CIK) - 10 digit company identifier"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., AAPL, MSFT)"
                },
                "company_name": {
                    "type": "string",
                    "description": "Company name or partial name for search"
                },
                "filing_type": {
                    "type": "string",
                    "description": "Type of filing to retrieve",
                    "enum": list(self.filing_types.keys())
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
                },
                "fact_type": {
                    "type": "string",
                    "description": "Type of financial fact/metric",
                    "enum": [
                        "Assets", "Liabilities", "StockholdersEquity",
                        "Revenues", "NetIncomeLoss", "EarningsPerShare",
                        "Cash", "OperatingIncome", "GrossProfit",
                        "CurrentAssets", "CurrentLiabilities", "LongTermDebt"
                    ]
                },
                "accession_number": {
                    "type": "string",
                    "description": "Accession number for specific filing"
                }
            },
            "required": ["action"]
        }

    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute SEC EDGAR tool

        Args:
            arguments: Tool arguments

        Returns:
            Company filings and financial data from SEC EDGAR
        """
        action = arguments.get('action')

        if action == 'search_company':
            company_name = arguments.get('company_name')
            ticker = arguments.get('ticker')

            if not company_name and not ticker:
                raise ValueError("Either 'company_name' or 'ticker' is required")

            return self._search_company(company_name or ticker)

        elif action == 'get_company_info':
            cik = self._get_cik(arguments)
            return self._get_company_info(cik)

        elif action == 'get_company_filings':
            cik = self._get_cik(arguments)
            filing_type = arguments.get('filing_type')
            start_date = arguments.get('start_date')
            end_date = arguments.get('end_date')
            limit = arguments.get('limit', 10)

            return self._get_company_filings(cik, filing_type, start_date, end_date, limit)

        elif action == 'get_company_facts':
            cik = self._get_cik(arguments)
            return self._get_company_facts(cik)

        elif action == 'get_financial_data':
            cik = self._get_cik(arguments)
            fact_type = arguments.get('fact_type')
            return self._get_financial_data(cik, fact_type)

        elif action == 'get_filing_details':
            accession_number = arguments.get('accession_number')
            if not accession_number:
                raise ValueError("'accession_number' is required")

            return self._get_filing_details(accession_number)

        elif action == 'get_insider_trading':
            cik = self._get_cik(arguments)
            limit = arguments.get('limit', 10)
            return self._get_insider_trading(cik, limit)

        elif action == 'get_mutual_fund_holdings':
            cik = self._get_cik(arguments)
            return self._get_mutual_fund_holdings(cik)

        else:
            raise ValueError(f"Unknown action: {action}")

    def _get_cik(self, arguments: Dict) -> str:
        """
        Extract and normalize CIK from arguments

        Args:
            arguments: Tool arguments

        Returns:
            Normalized 10-digit CIK
        """
        cik = arguments.get('cik')
        ticker = arguments.get('ticker')

        if not cik and not ticker:
            raise ValueError("Either 'cik' or 'ticker' is required")

        if ticker and not cik:
            # Try to get CIK from ticker via company tickers file
            cik = self._ticker_to_cik(ticker)

        # Normalize CIK to 10 digits
        if cik:
            cik = str(cik).zfill(10)

        return cik

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
                for company in data.values():
                    if company.get('ticker', '').upper() == ticker_upper:
                        return str(company['cik_str']).zfill(10)

                raise ValueError(f"Ticker not found: {ticker}")

        except Exception as e:
            self.logger.error(f"Failed to convert ticker to CIK: {e}")
            raise ValueError(f"Failed to convert ticker to CIK: {str(e)}")

    def _search_company(self, query: str) -> Dict:
        """
        Search for companies by name or ticker

        Args:
            query: Search query

        Returns:
            List of matching companies
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

                query_lower = query.lower()
                matches = []

                for company in data.values():
                    title = company.get('title', '').lower()
                    ticker = company.get('ticker', '').lower()

                    if query_lower in title or query_lower == ticker:
                        matches.append({
                            'cik': str(company['cik_str']).zfill(10),
                            'ticker': company['ticker'],
                            'title': company['title']
                        })

                return {
                    'query': query,
                    'match_count': len(matches),
                    'matches': matches[:50]  # Limit to 50 results
                }

        except Exception as e:
            self.logger.error(f"Company search failed: {e}")
            raise ValueError(f"Company search failed: {str(e)}")

    def _get_company_info(self, cik: str) -> Dict:
        """
        Get company information

        Args:
            cik: Central Index Key

        Returns:
            Company information
        """
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
                    'ticker': data.get('tickers', [None])[0] if data.get('tickers') else None,
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

    def _get_company_filings(
        self,
        cik: str,
        filing_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10
    ) -> Dict:
        """
        Get company filings

        Args:
            cik: Central Index Key
            filing_type: Type of filing
            start_date: Start date
            end_date: End date
            limit: Maximum number of results

        Returns:
            Company filings
        """
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

    def _get_company_facts(self, cik: str) -> Dict:
        """
        Get company facts (XBRL financial data)

        Args:
            cik: Central Index Key

        Returns:
            Company facts
        """
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

    def _get_financial_data(self, cik: str, fact_type: Optional[str] = None) -> Dict:
        """
        Get specific financial data for a company

        Args:
            cik: Central Index Key
            fact_type: Type of financial fact

        Returns:
            Financial data
        """
        try:
            facts_data = self._get_company_facts(cik)
            facts = facts_data.get('facts', {})

            if not fact_type:
                # Return summary of available facts
                summary = {}
                for taxonomy in facts:
                    summary[taxonomy] = list(facts[taxonomy].keys())

                return {
                    'cik': cik,
                    'entity_name': facts_data.get('entity_name'),
                    'available_facts': summary
                }

            # Search for specific fact type across taxonomies
            result = {
                'cik': cik,
                'entity_name': facts_data.get('entity_name'),
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

        except Exception as e:
            self.logger.error(f"Failed to get financial data: {e}")
            raise ValueError(f"Failed to get financial data: {str(e)}")

    def _get_filing_details(self, accession_number: str) -> Dict:
        """
        Get details for a specific filing

        Args:
            accession_number: Filing accession number

        Returns:
            Filing details
        """
        return {
            'accession_number': accession_number,
            'note': 'Full filing details require CIK. Use get_company_filings for complete data.'
        }

    def _get_insider_trading(self, cik: str, limit: int = 10) -> Dict:
        """
        Get insider trading forms (Form 4)

        Args:
            cik: Central Index Key
            limit: Maximum number of results

        Returns:
            Insider trading data
        """
        return self._get_company_filings(cik, filing_type='4', limit=limit)

    def _get_mutual_fund_holdings(self, cik: str) -> Dict:
        """
        Get mutual fund holdings (Form 13F)

        Args:
            cik: Central Index Key

        Returns:
            Mutual fund holdings
        """
        return self._get_company_filings(cik, filing_type='13F-HR', limit=5)