"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
SEC EDGAR Integration for Investor Relations Documents
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from .http_client import EnhancedHTTPClient


class SECEdgarClient:
    """
    Client for SEC EDGAR database
    Provides fallback for when direct IR scraping fails
    """
    
    # SEC filing types
    FILING_TYPES = {
        '10-K': 'annual_report',
        '10-Q': 'quarterly_report',
        '8-K': 'current_report',
        'DEF 14A': 'proxy_statement',
        '20-F': 'annual_report_foreign',
        'S-1': 'registration_statement',
        '424B4': 'prospectus'
    }
    
    def __init__(self, user_email: str = "ajsinha@gmail.com"):
        """
        Initialize SEC EDGAR client
        
        Args:
            user_email: Email for SEC API (required by SEC)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.base_url = "https://data.sec.gov"
        self.user_email = user_email
        self.http_client = EnhancedHTTPClient(min_delay=0.5, max_delay=1.0)
    
    def _get_sec_headers(self) -> Dict:
        """Get SEC-specific headers"""
        return {
            'User-Agent': f'SAJHA-MCP-Server/1.0 ({self.user_email})',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'data.sec.gov'
        }
    
    def get_company_submissions(self, cik: str) -> Dict:
        """
        Get company submission data from SEC
        
        Args:
            cik: Company CIK number (without leading zeros or with them)
            
        Returns:
            Company submission data
        """
        try:
            # Normalize CIK (remove leading zeros, then pad to 10 digits)
            cik_clean = str(int(cik))
            cik_padded = cik_clean.zfill(10)
            
            url = f"{self.base_url}/submissions/CIK{cik_padded}.json"
            
            data = self.http_client.fetch_json(url, custom_headers=self._get_sec_headers())
            return data
            
        except Exception as e:
            self.logger.error(f"Error fetching SEC submissions for CIK {cik}: {e}")
            raise ValueError(f"Failed to fetch SEC data: {str(e)}")
    
    def get_recent_filings(
        self,
        cik: str,
        filing_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get recent filings for a company
        
        Args:
            cik: Company CIK number
            filing_types: Optional list of filing types to filter (e.g., ['10-K', '10-Q'])
            limit: Maximum number of filings to return
            
        Returns:
            List of filing dictionaries
        """
        try:
            submissions = self.get_company_submissions(cik)
            
            filings = []
            recent_filings = submissions.get('filings', {}).get('recent', {})
            
            if not recent_filings:
                return []
            
            # Get arrays from recent filings
            accession_numbers = recent_filings.get('accessionNumber', [])
            filing_dates = recent_filings.get('filingDate', [])
            report_dates = recent_filings.get('reportDate', [])
            forms = recent_filings.get('form', [])
            file_numbers = recent_filings.get('fileNumber', [])
            primary_docs = recent_filings.get('primaryDocument', [])
            primary_doc_descriptions = recent_filings.get('primaryDocDescription', [])
            
            # Combine into filing objects
            for i in range(len(accession_numbers)):
                form = forms[i] if i < len(forms) else ''
                
                # Filter by filing type if specified
                if filing_types and form not in filing_types:
                    continue
                
                accession = accession_numbers[i] if i < len(accession_numbers) else ''
                filing_date = filing_dates[i] if i < len(filing_dates) else ''
                report_date = report_dates[i] if i < len(report_dates) else ''
                file_number = file_numbers[i] if i < len(file_numbers) else ''
                primary_doc = primary_docs[i] if i < len(primary_docs) else ''
                primary_doc_desc = primary_doc_descriptions[i] if i < len(primary_doc_descriptions) else ''
                
                # Build document URL
                accession_no_dashes = accession.replace('-', '')
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"
                
                filing = {
                    'accession_number': accession,
                    'filing_date': filing_date,
                    'report_date': report_date,
                    'form': form,
                    'file_number': file_number,
                    'primary_document': primary_doc,
                    'description': primary_doc_desc,
                    'document_url': doc_url,
                    'filing_url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=exclude&count=10",
                    'type': self.FILING_TYPES.get(form, 'other'),
                    'year': int(filing_date.split('-')[0]) if filing_date else None
                }
                
                filings.append(filing)
                
                if len(filings) >= limit:
                    break
            
            return filings
            
        except Exception as e:
            self.logger.error(f"Error getting recent filings for CIK {cik}: {e}")
            return []
    
    def get_annual_reports(self, cik: str, limit: int = 5) -> List[Dict]:
        """
        Get annual reports (10-K filings)
        
        Args:
            cik: Company CIK number
            limit: Maximum number of reports
            
        Returns:
            List of annual report dictionaries
        """
        return self.get_recent_filings(cik, filing_types=['10-K', '20-F'], limit=limit)
    
    def get_quarterly_reports(self, cik: str, limit: int = 10) -> List[Dict]:
        """
        Get quarterly reports (10-Q filings)
        
        Args:
            cik: Company CIK number
            limit: Maximum number of reports
            
        Returns:
            List of quarterly report dictionaries
        """
        return self.get_recent_filings(cik, filing_types=['10-Q'], limit=limit)
    
    def get_proxy_statements(self, cik: str, limit: int = 5) -> List[Dict]:
        """
        Get proxy statements (DEF 14A filings)
        
        Args:
            cik: Company CIK number
            limit: Maximum number of statements
            
        Returns:
            List of proxy statement dictionaries
        """
        return self.get_recent_filings(cik, filing_types=['DEF 14A'], limit=limit)
    
    def get_current_reports(self, cik: str, limit: int = 20) -> List[Dict]:
        """
        Get current reports (8-K filings)
        
        Args:
            cik: Company CIK number
            limit: Maximum number of reports
            
        Returns:
            List of current report dictionaries
        """
        return self.get_recent_filings(cik, filing_types=['8-K'], limit=limit)
    
    def search_filings(
        self,
        cik: str,
        keywords: List[str],
        filing_types: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search filings by keywords
        
        Args:
            cik: Company CIK number
            keywords: List of keywords to search for
            filing_types: Optional filing types to filter
            limit: Maximum number of results
            
        Returns:
            List of matching filing dictionaries
        """
        try:
            filings = self.get_recent_filings(cik, filing_types, limit=limit * 2)
            
            # Filter by keywords
            matching_filings = []
            for filing in filings:
                # Search in description and primary document name
                searchable_text = f"{filing.get('description', '')} {filing.get('primary_document', '')}".lower()
                
                # Check if any keyword matches
                for keyword in keywords:
                    if keyword.lower() in searchable_text:
                        matching_filings.append(filing)
                        break
                
                if len(matching_filings) >= limit:
                    break
            
            return matching_filings
            
        except Exception as e:
            self.logger.error(f"Error searching filings: {e}")
            return []
    
    def get_company_facts(self, cik: str) -> Dict:
        """
        Get company facts (financial data) from SEC
        
        Args:
            cik: Company CIK number
            
        Returns:
            Company facts data
        """
        try:
            cik_clean = str(int(cik))
            cik_padded = cik_clean.zfill(10)
            
            url = f"{self.base_url}/api/xbrl/companyfacts/CIK{cik_padded}.json"
            
            data = self.http_client.fetch_json(url, custom_headers=self._get_sec_headers())
            return data
            
        except Exception as e:
            self.logger.error(f"Error fetching company facts for CIK {cik}: {e}")
            return {}
    
    def get_latest_filing_of_type(self, cik: str, filing_type: str) -> Optional[Dict]:
        """
        Get the most recent filing of a specific type
        
        Args:
            cik: Company CIK number
            filing_type: Filing type (e.g., '10-K', '10-Q')
            
        Returns:
            Latest filing dictionary or None
        """
        filings = self.get_recent_filings(cik, filing_types=[filing_type], limit=1)
        return filings[0] if filings else None
    
    def format_for_ir_tool(self, filings: List[Dict], ticker: str) -> List[Dict]:
        """
        Format SEC filings to match IR tool document format
        
        Args:
            filings: List of SEC filing dictionaries
            ticker: Stock ticker symbol
            
        Returns:
            List of formatted document dictionaries
        """
        formatted_docs = []
        
        for filing in filings:
            doc = {
                'title': f"{filing['form']} - {filing['report_date'] or filing['filing_date']}",
                'url': filing['document_url'],
                'type': filing['type'],
                'year': filing['year'],
                'date': filing['filing_date'],
                'description': filing.get('description', ''),
                'ticker': ticker,
                'is_pdf': filing['primary_document'].endswith('.pdf') if filing.get('primary_document') else False,
                'source': 'SEC EDGAR',
                'form_type': filing['form'],
                'accession_number': filing['accession_number']
            }
            formatted_docs.append(doc)
        
        return formatted_docs
