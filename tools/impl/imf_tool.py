"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
IMF (International Monetary Fund) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool

class IMFTool(BaseMCPTool):
    """
    IMF API tool for retrieving international monetary and financial statistics
    """
    
    def __init__(self, config: Dict = None):
        """Initialize IMF tool"""
        default_config = {
            'name': 'imf',
            'description': 'Retrieve international monetary and financial statistics from IMF',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # IMF Data API endpoint
        self.api_url = "http://dataservices.imf.org/REST/SDMX_JSON.svc"
        
        # Major IMF Databases
        self.databases = {
            'IFS': 'International Financial Statistics',
            'DOT': 'Direction of Trade Statistics',
            'BOP': 'Balance of Payments',
            'GFSR': 'Global Financial Stability Report',
            'FSI': 'Financial Soundness Indicators',
            'WEO': 'World Economic Outlook',
            'GFSMAB': 'Government Finance Statistics',
            'CDIS': 'Coordinated Direct Investment Survey',
            'CPIS': 'Coordinated Portfolio Investment Survey',
            'WHDREO': 'World Economic Outlook Historical'
        }
        
        # Common IFS (International Financial Statistics) indicators
        self.ifs_indicators = {
            # Exchange Rates
            'exchange_rate': 'ENDA_XDC_USD_RATE',  # End of Period Exchange Rate
            'exchange_rate_avg': 'EREA_XDC_USD_RATE',  # Period Average Exchange Rate
            
            # Interest Rates
            'policy_rate': 'FPOLM_PA',  # Monetary Policy-Related Interest Rate
            'treasury_bill_rate': 'FITB_PA',  # Treasury Bill Rate
            'deposit_rate': 'FDBR_PA',  # Deposit Rate
            'lending_rate': 'FILR_PA',  # Lending Rate
            
            # Prices
            'cpi': 'PCPI_IX',  # Consumer Price Index
            'core_cpi': 'PCCOR_IX',  # Core Consumer Price Index
            'ppi': 'PPPI_IX',  # Producer Price Index
            
            # Monetary
            'money_supply_m1': 'FM1_XDC',  # Money (M1)
            'money_supply_m2': 'FM2_XDC',  # Money (M2)
            'money_supply_m3': 'FM3_XDC',  # Money (M3)
            'reserve_money': 'FMRM_XDC',  # Reserve Money
            
            # Reserves & Assets
            'international_reserves': 'RAXG_USD',  # Total Reserves (Gold excluded)
            'gold_reserves': 'RAFZ_USD',  # Gold (National Valuation)
            'foreign_reserves': 'RAER_USD',  # Foreign Exchange Reserves
            
            # Economic Activity
            'gdp_current': 'NGDP_XDC',  # Gross Domestic Product (Current)
            'gdp_constant': 'NGDP_R_XDC',  # Gross Domestic Product (Constant)
            'industrial_production': 'PINDUST_IX',  # Industrial Production Index
            
            # Trade
            'exports': 'BXG_FOB_USD',  # Goods, Exports f.o.b.
            'imports': 'BMG_BP6_USD',  # Goods, Imports
            
            # Labor
            'unemployment_rate': 'LUR_PT',  # Unemployment Rate
        }
        
        # WEO (World Economic Outlook) indicators
        self.weo_indicators = {
            'gdp_growth': 'NGDP_RPCH',  # GDP growth (annual %)
            'gdp_per_capita': 'NGDPDPC',  # GDP per capita (current prices)
            'inflation_avg': 'PCPIPCH',  # Inflation, average consumer prices
            'inflation_eop': 'PCPIEPCH',  # Inflation, end of period
            'unemployment': 'LUR',  # Unemployment rate
            'current_account': 'BCA_NGDPD',  # Current account balance (% of GDP)
            'fiscal_balance': 'GGXCNL_NGDP',  # General government net lending/borrowing
            'public_debt': 'GGXWDG_NGDP',  # General government gross debt
            'exports_volume': 'TXG_RPCH',  # Volume of exports of goods
            'imports_volume': 'TMG_RPCH',  # Volume of imports of goods
            'population': 'LP',  # Population
        }
        
        # Country codes mapping (ISO2)
        self.common_countries = {
            'US': 'United States',
            'CN': 'China',
            'JP': 'Japan',
            'DE': 'Germany',
            'GB': 'United Kingdom',
            'FR': 'France',
            'IN': 'India',
            'IT': 'Italy',
            'BR': 'Brazil',
            'CA': 'Canada'
        }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for IMF tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_databases",
                        "get_dataflows",
                        "get_data",
                        "get_ifs_data",
                        "get_weo_data",
                        "get_bop_data",
                        "compare_countries",
                        "get_country_profile"
                    ]
                },
                "database": {
                    "type": "string",
                    "description": "IMF database code",
                    "enum": list(self.databases.keys())
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO 2-letter country code (e.g., US, CN, JP)"
                },
                "country_codes": {
                    "type": "array",
                    "description": "List of country codes for comparison",
                    "items": {"type": "string"}
                },
                "indicator_code": {
                    "type": "string",
                    "description": "IMF indicator code"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator name (IFS or WEO)",
                    "enum": list(self.ifs_indicators.keys()) + list(self.weo_indicators.keys())
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year for data retrieval",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year for data retrieval",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "frequency": {
                    "type": "string",
                    "description": "Data frequency",
                    "enum": ["A", "Q", "M"],
                    "default": "A"
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute IMF tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            International monetary and financial statistics from IMF
        """
        action = arguments.get('action')
        
        if action == 'get_databases':
            return self._get_databases()
            
        elif action == 'get_dataflows':
            database = arguments.get('database', 'IFS')
            return self._get_dataflows(database)
            
        elif action == 'get_data':
            database = arguments.get('database')
            country_code = arguments.get('country_code')
            indicator_code = arguments.get('indicator_code')
            
            if not database:
                raise ValueError("'database' is required")
            if not country_code:
                raise ValueError("'country_code' is required")
            if not indicator_code:
                raise ValueError("'indicator_code' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            frequency = arguments.get('frequency', 'A')
            
            return self._get_data(database, country_code, indicator_code, start_year, end_year, frequency)
            
        elif action == 'get_ifs_data':
            country_code = arguments.get('country_code')
            indicator = arguments.get('indicator')
            indicator_code = arguments.get('indicator_code')
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            if indicator and not indicator_code:
                indicator_code = self.ifs_indicators.get(indicator)
            
            if not indicator_code:
                raise ValueError("Either 'indicator_code' or 'indicator' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            frequency = arguments.get('frequency', 'M')
            
            return self._get_data('IFS', country_code, indicator_code, start_year, end_year, frequency)
            
        elif action == 'get_weo_data':
            country_code = arguments.get('country_code')
            indicator = arguments.get('indicator')
            indicator_code = arguments.get('indicator_code')
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            if indicator and not indicator_code:
                indicator_code = self.weo_indicators.get(indicator)
            
            if not indicator_code:
                raise ValueError("Either 'indicator_code' or 'indicator' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            
            return self._get_weo_data(country_code, indicator_code, start_year, end_year)
            
        elif action == 'get_bop_data':
            country_code = arguments.get('country_code')
            indicator_code = arguments.get('indicator_code')
            
            if not country_code:
                raise ValueError("'country_code' is required")
            if not indicator_code:
                raise ValueError("'indicator_code' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            frequency = arguments.get('frequency', 'A')
            
            return self._get_data('BOP', country_code, indicator_code, start_year, end_year, frequency)
            
        elif action == 'compare_countries':
            country_codes = arguments.get('country_codes', [])
            indicator = arguments.get('indicator')
            indicator_code = arguments.get('indicator_code')
            database = arguments.get('database', 'IFS')
            
            if not country_codes or len(country_codes) < 2:
                raise ValueError("At least 2 country codes required in 'country_codes'")
            
            if indicator and not indicator_code:
                if database == 'WEO':
                    indicator_code = self.weo_indicators.get(indicator)
                else:
                    indicator_code = self.ifs_indicators.get(indicator)
            
            if not indicator_code:
                raise ValueError("Either 'indicator_code' or 'indicator' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            frequency = arguments.get('frequency', 'A')
            
            return self._compare_countries(country_codes, database, indicator_code, start_year, end_year, frequency)
            
        elif action == 'get_country_profile':
            country_code = arguments.get('country_code')
            if not country_code:
                raise ValueError("'country_code' is required")
            
            return self._get_country_profile(country_code)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_databases(self) -> Dict:
        """
        Get list of available IMF databases
        
        Returns:
            List of databases
        """
        databases_list = []
        for code, name in self.databases.items():
            databases_list.append({
                'code': code,
                'name': name
            })
        
        return {
            'databases': databases_list,
            'count': len(databases_list)
        }
    
    def _get_dataflows(self, database: str) -> Dict:
        """
        Get dataflows for a database
        
        Args:
            database: Database code
            
        Returns:
            List of dataflows
        """
        try:
            url = f"{self.api_url}/Dataflow/{database}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Parse IMF SDMX response structure
                structure = data.get('Structure', {})
                dataflows = structure.get('Dataflows', {}).get('Dataflow', [])
                
                formatted_dataflows = []
                if isinstance(dataflows, list):
                    for df in dataflows:
                        formatted_dataflows.append({
                            'id': df.get('@id'),
                            'name': df.get('Name', {}).get('#text')
                        })
                elif isinstance(dataflows, dict):
                    formatted_dataflows.append({
                        'id': dataflows.get('@id'),
                        'name': dataflows.get('Name', {}).get('#text')
                    })
                
                return {
                    'database': database,
                    'dataflows': formatted_dataflows,
                    'count': len(formatted_dataflows)
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get dataflows: {e}")
            return {
                'database': database,
                'error': str(e),
                'note': 'Failed to retrieve dataflows. Database may not be available.'
            }
    
    def _get_data(
        self,
        database: str,
        country_code: str,
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        frequency: str = 'A'
    ) -> Dict:
        """
        Get data from IMF database
        
        Args:
            database: Database code
            country_code: Country code
            indicator_code: Indicator code
            start_year: Start year
            end_year: End year
            frequency: Data frequency (A=Annual, Q=Quarterly, M=Monthly)
            
        Returns:
            IMF data
        """
        try:
            # Build dimension string: Frequency.Country.Indicator
            dimension = f"{frequency}.{country_code}.{indicator_code}"
            
            # Build URL with optional date range
            url = f"{self.api_url}/CompactData/{database}/{dimension}"
            
            if start_year or end_year:
                start = start_year or 1950
                end = end_year or datetime.now().year
                url += f"?startPeriod={start}&endPeriod={end}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Parse IMF SDMX CompactData response
                compact_data = data.get('CompactData', {})
                dataset = compact_data.get('DataSet', {})
                series = dataset.get('Series', {})
                
                if not series:
                    return {
                        'database': database,
                        'country_code': country_code,
                        'indicator_code': indicator_code,
                        'data': [],
                        'count': 0,
                        'note': 'No data available for the specified parameters'
                    }
                
                # Extract observations
                observations = series.get('Obs', [])
                if not isinstance(observations, list):
                    observations = [observations]
                
                formatted_data = []
                for obs in observations:
                    if isinstance(obs, dict):
                        formatted_data.append({
                            'period': obs.get('@TIME_PERIOD'),
                            'value': float(obs.get('@OBS_VALUE')) if obs.get('@OBS_VALUE') else None
                        })
                
                return {
                    'database': database,
                    'country_code': country_code,
                    'indicator_code': indicator_code,
                    'frequency': frequency,
                    'data': formatted_data,
                    'count': len(formatted_data)
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Data not found for {country_code}/{indicator_code} in {database}")
            else:
                raise ValueError(f"Failed to get data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Failed to get IMF data: {e}")
            raise ValueError(f"Failed to get IMF data: {str(e)}")
    
    def _get_weo_data(
        self,
        country_code: str,
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> Dict:
        """
        Get World Economic Outlook data
        
        Args:
            country_code: Country code
            indicator_code: Indicator code
            start_year: Start year
            end_year: End year
            
        Returns:
            WEO data
        """
        return self._get_data('WEO', country_code, indicator_code, start_year, end_year, 'A')
    
    def _compare_countries(
        self,
        country_codes: List[str],
        database: str,
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        frequency: str = 'A'
    ) -> Dict:
        """
        Compare indicator data across multiple countries
        
        Args:
            country_codes: List of country codes
            database: Database code
            indicator_code: Indicator code
            start_year: Start year
            end_year: End year
            frequency: Data frequency
            
        Returns:
            Comparison data
        """
        comparison = {
            'database': database,
            'indicator_code': indicator_code,
            'frequency': frequency,
            'countries': []
        }
        
        for country_code in country_codes:
            try:
                data = self._get_data(database, country_code, indicator_code, start_year, end_year, frequency)
                comparison['countries'].append(data)
            except Exception as e:
                self.logger.warning(f"Failed to get data for {country_code}: {e}")
                comparison['countries'].append({
                    'country_code': country_code,
                    'error': str(e)
                })
        
        return comparison
    
    def _get_country_profile(self, country_code: str) -> Dict:
        """
        Get comprehensive country profile with key indicators
        
        Args:
            country_code: Country code
            
        Returns:
            Country profile
        """
        profile = {
            'country_code': country_code,
            'country_name': self.common_countries.get(country_code, country_code),
            'indicators': {}
        }
        
        # Key indicators to fetch
        key_indicators = {
            'GDP Growth': ('WEO', 'NGDP_RPCH', 'A'),
            'Inflation': ('WEO', 'PCPIPCH', 'A'),
            'Unemployment': ('WEO', 'LUR', 'A'),
            'Current Account': ('WEO', 'BCA_NGDPD', 'A'),
            'Public Debt': ('WEO', 'GGXWDG_NGDP', 'A')
        }
        
        current_year = datetime.now().year
        start_year = current_year - 5
        
        for name, (db, code, freq) in key_indicators.items():
            try:
                data = self._get_data(db, country_code, code, start_year, current_year, freq)
                if data['data']:
                    latest = data['data'][-1]
                    profile['indicators'][name] = {
                        'code': code,
                        'latest_value': latest['value'],
                        'latest_period': latest['period'],
                        'recent_data': data['data'][-3:] if len(data['data']) >= 3 else data['data']
                    }
            except Exception as e:
                self.logger.warning(f"Failed to get {name} for {country_code}: {e}")
                profile['indicators'][name] = {
                    'code': code,
                    'error': str(e)
                }
        
        return profile
