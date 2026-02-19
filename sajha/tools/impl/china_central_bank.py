"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
People's Bank of China (PBoC) MCP Tool Implementation

Uses FRED (Federal Reserve Economic Data) API for Chinese economic indicators.
FRED provides reliable access to Chinese economic data from official sources.
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_DEFAULT


class PeoplesBankOfChinaBaseTool(BaseMCPTool):
    """
    Base class for People's Bank of China tools with shared functionality.
    
    Uses FRED API to access Chinese economic data including:
    - CGB (Chinese Government Bond) yields
    - Policy rates
    - Exchange rates
    - Monetary aggregates
    - Price indices
    - Economic indicators
    """
    
    def __init__(self, config: Dict = None):
        """Initialize People's Bank of China base tool"""
        super().__init__(config)
        
        # FRED API endpoint
        self.api_url = "https://api.stlouisfed.org/fred/series/observations"
        self.fred_api_key = None
        
        # FRED series codes for Chinese economic data
        self.fred_series = {
            # Interest Rates
            'lending_rate': 'INTDSRCNM193N',  # Lending Rate
            'deposit_rate': 'INTDSRCNM193N',  # Deposit Rate (same series)
            'prime_rate': 'CHNCPIALLMINMEI',  # Placeholder - China doesn't publish LPR on FRED
            
            # Government Bond Yields
            'cgb_10y': 'IRLTLT01CNM156N',  # 10-Year Government Bond Yield
            'cgb_3m': 'IR3TIB01CNM156N',  # 3-Month Interbank Rate
            
            # Exchange Rates
            'usd_cny': 'DEXCHUS',  # Chinese Yuan to US Dollar
            'eur_cny': 'EXCHUS',  # Effective Exchange Rate Index
            
            # Monetary Aggregates
            'm0': 'MYAGM0CNM189N',  # M0 (Currency in Circulation)
            'm1': 'MYAGM1CNM189S',  # M1 Money Stock
            'm2': 'MYAGM2CNM189N',  # M2 Money Stock
            
            # Price Indices
            'cpi': 'CHNCPIALLMINMEI',  # CPI All Items
            'ppi': 'CHNPIEAMP01GYM',  # Producer Price Index
            'core_cpi': 'CHNCPICORMINMEI',  # Core CPI
            
            # Economic Indicators
            'gdp': 'MKTGDPCNA646NWDB',  # GDP (World Bank)
            'gdp_growth': 'NYGDPMKTPKDZCHN',  # GDP Growth Rate
            'unemployment': 'LRUNTTTTCNM156S',  # Unemployment Rate
            'industrial_production': 'CHNPROINDMISMEI',  # Industrial Production
            'retail_sales': 'CHNSLRTTO02IXOBM',  # Retail Sales
            'exports': 'CHNXTEXVA01CXMLM',  # Exports
            'imports': 'CHNXTIMVA01CXMLM',  # Imports
            'trade_balance': 'CHNTBALNM',  # Trade Balance (approximate)
            'fdi': 'ROWFDNCA052NWDB',  # Foreign Direct Investment
            
            # Real Estate
            'house_price_index': 'QCNN628BIS',  # Residential Property Prices
        }
        
        # Human-readable labels
        self.series_labels = {
            'lending_rate': 'PBoC Lending Rate',
            'deposit_rate': 'PBoC Deposit Rate',
            'prime_rate': 'Loan Prime Rate (LPR)',
            'cgb_10y': '10-Year Chinese Government Bond Yield',
            'cgb_3m': '3-Month Interbank Rate',
            'usd_cny': 'USD/CNY Exchange Rate',
            'eur_cny': 'Effective Exchange Rate Index',
            'm0': 'M0 (Currency in Circulation)',
            'm1': 'M1 Money Stock',
            'm2': 'M2 Money Stock',
            'cpi': 'Consumer Price Index (All Items)',
            'ppi': 'Producer Price Index',
            'core_cpi': 'Core CPI (Less Food and Energy)',
            'gdp': 'Gross Domestic Product',
            'gdp_growth': 'GDP Growth Rate',
            'unemployment': 'Unemployment Rate',
            'industrial_production': 'Industrial Production Index',
            'retail_sales': 'Retail Sales',
            'exports': 'Exports',
            'imports': 'Imports',
            'trade_balance': 'Trade Balance',
            'fdi': 'Foreign Direct Investment',
            'house_price_index': 'Residential Property Price Index',
        }
    
    def _get_api_key(self) -> str:
        """Get FRED API key from configuration"""
        if self.fred_api_key:
            return self.fred_api_key
            
        from sajha.config import get_api_key_manager
        api_key_manager = get_api_key_manager()
        
        for key_name in ['fred_api_key', 'FRED_API_KEY', 'fred']:
            api_key = api_key_manager.get_api_key(key_name)
            if api_key:
                self.fred_api_key = api_key
                return api_key
        
        raise ValueError(
            "FRED API key not configured. Please add 'fred_api_key' to config/apikeys.json. "
            "Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    
    def _fetch_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from FRED API
        """
        fred_code = self.fred_series.get(series_id, series_id)
        label = self.series_labels.get(series_id, series_id)
        
        api_key = self._get_api_key()
        
        params = {
            'series_id': fred_code,
            'api_key': api_key,
            'file_type': 'json',
            'sort_order': 'desc' if recent_periods else 'asc'
        }
        
        if not start_date and not end_date and recent_periods:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start = datetime.now() - timedelta(days=recent_periods * 45)
            start_date = start.strftime('%Y-%m-%d')
        
        if start_date:
            params['observation_start'] = start_date
        if end_date:
            params['observation_end'] = end_date
        if recent_periods:
            params['limit'] = recent_periods
        
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        
        try:
            headers = {
                'User-Agent': 'SAJHA-MCP-Server/2.2.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = safe_json_response(response, ENCODINGS_DEFAULT)
                
                observations = []
                if 'observations' in data:
                    for obs in data['observations']:
                        value = obs.get('value')
                        if value and value != '.':
                            try:
                                observations.append({
                                    'date': obs.get('date'),
                                    'value': float(value)
                                })
                            except ValueError:
                                pass
                    
                    if recent_periods:
                        observations.reverse()
                    
                    return {
                        'series_code': fred_code,
                        'series_id': series_id,
                        'label': label,
                        'source': 'FRED (Federal Reserve Economic Data)',
                        'observation_count': len(observations),
                        'observations': observations
                    }
                else:
                    raise ValueError(f"No observations found for series: {fred_code}")
                
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise ValueError(f"Invalid series or parameters: {fred_code}")
            elif e.code == 404:
                raise ValueError(f"Series not found: {fred_code}")
            else:
                raise ValueError(f"FRED API error: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to get series data: {str(e)}")


class PBoCGetCGBYieldTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve Chinese Government Bond (CGB) yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_cgb_yield',
            'description': 'Retrieve Chinese Government Bond (CGB) yields',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "bond_term": {
                    "type": "string",
                    "description": "Bond term/maturity",
                    "enum": ["10y", "3m"],
                    "default": "10y"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute CGB yield retrieval"""
        bond_term = arguments.get('bond_term', '10y')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        term_mapping = {
            '10y': 'cgb_10y',
            '3m': 'cgb_3m'
        }
        
        series_id = term_mapping.get(bond_term)
        if not series_id:
            return {"error": f"Unsupported bond term: {bond_term}. Supported: 10y, 3m"}
        
        return self._fetch_series(series_id, start_date, end_date, recent_periods)


class PBoCGetPolicyRateTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve People's Bank of China policy rates
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_policy_rate',
            'description': 'Retrieve PBoC policy interest rates',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "rate_type": {
                    "type": "string",
                    "description": "Type of policy rate",
                    "enum": ["lending", "deposit"],
                    "default": "lending"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute policy rate retrieval"""
        rate_type = arguments.get('rate_type', 'lending')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        type_mapping = {
            'lending': 'lending_rate',
            'deposit': 'deposit_rate'
        }
        
        series_id = type_mapping.get(rate_type)
        if not series_id:
            return {"error": f"Unsupported rate type: {rate_type}"}
        
        return self._fetch_series(series_id, start_date, end_date, recent_periods)


class PBoCGetExchangeRateTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve CNY exchange rates
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_exchange_rate',
            'description': 'Retrieve Chinese Yuan exchange rates',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "currency_pair": {
                    "type": "string",
                    "description": "Currency pair",
                    "enum": ["usd_cny"],
                    "default": "usd_cny"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute exchange rate retrieval"""
        currency_pair = arguments.get('currency_pair', 'usd_cny')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        if currency_pair not in ['usd_cny']:
            return {"error": f"Unsupported currency pair: {currency_pair}. Supported: usd_cny"}
        
        return self._fetch_series(currency_pair, start_date, end_date, recent_periods)


class PBoCGetMoneySupplyTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve Chinese money supply data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_money_supply',
            'description': 'Retrieve Chinese money supply (M0, M1, M2)',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "aggregate": {
                    "type": "string",
                    "description": "Monetary aggregate",
                    "enum": ["m0", "m1", "m2"],
                    "default": "m2"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute money supply retrieval"""
        aggregate = arguments.get('aggregate', 'm2')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        if aggregate not in ['m0', 'm1', 'm2']:
            return {"error": f"Unsupported aggregate: {aggregate}"}
        
        return self._fetch_series(aggregate, start_date, end_date, recent_periods)


class PBoCGetInflationTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve Chinese inflation data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_inflation',
            'description': 'Retrieve Chinese inflation data (CPI, PPI)',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "measure": {
                    "type": "string",
                    "description": "Inflation measure",
                    "enum": ["cpi", "core_cpi", "ppi"],
                    "default": "cpi"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute inflation data retrieval"""
        measure = arguments.get('measure', 'cpi')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        if measure not in ['cpi', 'core_cpi', 'ppi']:
            return {"error": f"Unsupported measure: {measure}"}
        
        return self._fetch_series(measure, start_date, end_date, recent_periods)


class PBoCGetEconomicIndicatorTool(PeoplesBankOfChinaBaseTool):
    """
    Tool to retrieve various Chinese economic indicators
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_economic_indicator',
            'description': 'Retrieve Chinese economic indicators (GDP, unemployment, industrial production, trade)',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "indicator": {
                    "type": "string",
                    "description": "Economic indicator",
                    "enum": ["gdp", "gdp_growth", "unemployment", "industrial_production", 
                             "retail_sales", "exports", "imports", "fdi", "house_price_index"],
                    "default": "gdp_growth"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations",
                    "minimum": 1,
                    "maximum": 500
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observations": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute economic indicator retrieval"""
        indicator = arguments.get('indicator', 'gdp_growth')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        valid_indicators = list(self.fred_series.keys())
        if indicator not in valid_indicators:
            return {"error": f"Unsupported indicator: {indicator}"}
        
        return self._fetch_series(indicator, start_date, end_date, recent_periods)


class PBoCListSeriesTools(PeoplesBankOfChinaBaseTool):
    """
    Tool to list available Chinese economic series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_list_series',
            'description': 'List available Chinese economic data series',
            'version': '2.9.6',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category filter (optional)",
                    "enum": ["rates", "fx", "money", "prices", "economy", "all"],
                    "default": "all"
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series": {"type": "array"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute series listing"""
        category = arguments.get('category', 'all')
        
        category_mapping = {
            'rates': ['lending_rate', 'deposit_rate', 'cgb_10y', 'cgb_3m'],
            'fx': ['usd_cny'],
            'money': ['m0', 'm1', 'm2'],
            'prices': ['cpi', 'core_cpi', 'ppi', 'house_price_index'],
            'economy': ['gdp', 'gdp_growth', 'unemployment', 'industrial_production', 
                       'retail_sales', 'exports', 'imports', 'fdi'],
            'all': list(self.fred_series.keys())
        }
        
        series_ids = category_mapping.get(category, category_mapping['all'])
        
        series_list = []
        for series_id in series_ids:
            if series_id in self.fred_series:
                series_list.append({
                    'id': series_id,
                    'fred_code': self.fred_series[series_id],
                    'label': self.series_labels.get(series_id, series_id)
                })
        
        return {
            'category': category,
            'count': len(series_list),
            'source': 'FRED (Federal Reserve Economic Data)',
            'series': series_list
        }


# Tool registry
CHINA_CENTRAL_BANK_TOOLS = {
    'pboc_get_cgb_yield': PBoCGetCGBYieldTool,
    'pboc_get_policy_rate': PBoCGetPolicyRateTool,
    'pboc_get_exchange_rate': PBoCGetExchangeRateTool,
    'pboc_get_money_supply': PBoCGetMoneySupplyTool,
    'pboc_get_inflation': PBoCGetInflationTool,
    'pboc_get_economic_indicator': PBoCGetEconomicIndicatorTool,
    'pboc_list_series': PBoCListSeriesTools,
}
