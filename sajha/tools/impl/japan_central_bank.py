"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Bank of Japan (BoJ) MCP Tool Implementation

Uses FRED (Federal Reserve Economic Data) API for Japanese economic indicators.
FRED provides reliable access to Bank of Japan and Japanese economic data.
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_DEFAULT


class BankOfJapanBaseTool(BaseMCPTool):
    """
    Base class for Bank of Japan tools with shared functionality.
    
    Uses FRED API to access Japanese economic data including:
    - JGB (Japanese Government Bond) yields
    - Policy rates
    - Exchange rates
    - Monetary aggregates
    - Price indices
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Bank of Japan base tool"""
        super().__init__(config)
        
        # FRED API endpoint for Japanese data
        self.api_url = "https://api.stlouisfed.org/fred/series/observations"
        self.fred_api_key = None  # Will be loaded from config
        
        # FRED series codes for Japanese economic data
        self.fred_series = {
            # JGB Yields (Japanese Government Bonds)
            'jgb_10y': 'IRLTLT01JPM156N',  # 10-Year JGB Yield
            'jgb_3m': 'IR3TIB01JPM156N',  # 3-Month Treasury Bill Rate
            
            # Policy Rates
            'policy_rate': 'IRSTCI01JPM156N',  # Immediate Rates: Call Money
            'discount_rate': 'INTDSRJPM193N',  # Discount Rate
            
            # Exchange Rates
            'usd_jpy': 'DEXJPUS',  # Japanese Yen to US Dollar
            'eur_jpy': 'EXJPEU',  # Japanese Yen to Euro (inverted)
            
            # Monetary Aggregates
            'm1': 'MYAGM1JPM189S',  # M1 Money Stock
            'm2': 'MYAGM2JPM189N',  # M2 Money Stock
            'm3': 'MABMM301JPM189S',  # M3 Money Stock
            
            # Price Indices
            'cpi': 'JPNCPIALLMINMEI',  # CPI All Items
            'core_cpi': 'JPNCPICORMINMEI',  # CPI Less Food and Energy
            'ppi': 'PIEAMP01JPM661N',  # Producer Price Index
            
            # Economic Indicators
            'gdp': 'JPNRGDPEXP',  # Real GDP
            'unemployment': 'LRUNTTTTJPM156S',  # Unemployment Rate
            'industrial_production': 'JPNPROINDMISMEI',  # Industrial Production
            'trade_balance': 'JPNXTEXVA01NCMLM',  # Trade Balance
        }
        
        # Human-readable labels
        self.series_labels = {
            'jgb_10y': '10-Year Japanese Government Bond Yield',
            'jgb_3m': '3-Month Treasury Bill Rate',
            'policy_rate': 'Bank of Japan Call Money Rate',
            'discount_rate': 'Bank of Japan Discount Rate',
            'usd_jpy': 'USD/JPY Exchange Rate',
            'eur_jpy': 'EUR/JPY Exchange Rate',
            'm1': 'M1 Money Stock',
            'm2': 'M2 Money Stock',
            'm3': 'M3 Money Stock',
            'cpi': 'Consumer Price Index (All Items)',
            'core_cpi': 'Core CPI (Less Food and Energy)',
            'ppi': 'Producer Price Index',
            'gdp': 'Real GDP',
            'unemployment': 'Unemployment Rate',
            'industrial_production': 'Industrial Production Index',
            'trade_balance': 'Trade Balance',
        }
    
    def _get_api_key(self) -> str:
        """Get FRED API key from configuration"""
        if self.fred_api_key:
            return self.fred_api_key
            
        # Try to get from config
        from sajha.config import get_api_key_manager
        api_key_manager = get_api_key_manager()
        
        # Try multiple possible key names
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
        
        Args:
            series_id: FRED series ID or our shorthand name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        # Get the FRED series code
        fred_code = self.fred_series.get(series_id, series_id)
        label = self.series_labels.get(series_id, series_id)
        
        # Build API request
        api_key = self._get_api_key()
        
        params = {
            'series_id': fred_code,
            'api_key': api_key,
            'file_type': 'json',
            'sort_order': 'desc' if recent_periods else 'asc'
        }
        
        # Set date range
        if not start_date and not end_date and recent_periods:
            # Get recent data - go back enough time to get the periods
            end_date = datetime.now().strftime('%Y-%m-%d')
            # Estimate start date (assume monthly data, add buffer)
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
                        # FRED uses '.' for missing values
                        if value and value != '.':
                            try:
                                observations.append({
                                    'date': obs.get('date'),
                                    'value': float(value)
                                })
                            except ValueError:
                                pass
                    
                    # Sort chronologically if we fetched in desc order
                    if recent_periods:
                        observations.reverse()
                    
                    return {
                        'series_code': fred_code,
                        'series_id': series_id,
                        'label': label,
                        'source': 'FRED (Federal Reserve Economic Data)',
                        'frequency': data.get('frequency', 'Unknown'),
                        'units': data.get('units', 'Unknown'),
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
    
    def _list_available_series(self) -> List[Dict]:
        """Return list of available series"""
        series_list = []
        for series_id, fred_code in self.fred_series.items():
            series_list.append({
                'id': series_id,
                'fred_code': fred_code,
                'label': self.series_labels.get(series_id, series_id)
            })
        return series_list


class BoJGetJGBYieldTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Japanese Government Bond (JGB) yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_jgb_yield',
            'description': 'Retrieve Japanese Government Bond (JGB) yields',
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
                    "description": "Start date (YYYY-MM-DD)",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
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
                "source": {"type": "string"},
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "value": {"type": "number"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute JGB yield retrieval"""
        bond_term = arguments.get('bond_term', '10y')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        # Map bond term to series
        term_mapping = {
            '10y': 'jgb_10y',
            '3m': 'jgb_3m'
        }
        
        series_id = term_mapping.get(bond_term)
        if not series_id:
            return {"error": f"Unsupported bond term: {bond_term}. Supported: 10y, 3m"}
        
        return self._fetch_series(series_id, start_date, end_date, recent_periods)


class BoJGetPolicyRateTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Bank of Japan policy rates
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_policy_rate',
            'description': 'Retrieve Bank of Japan policy interest rates',
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
                    "enum": ["call_money", "discount"],
                    "default": "call_money"
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
        rate_type = arguments.get('rate_type', 'call_money')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        type_mapping = {
            'call_money': 'policy_rate',
            'discount': 'discount_rate'
        }
        
        series_id = type_mapping.get(rate_type)
        if not series_id:
            return {"error": f"Unsupported rate type: {rate_type}"}
        
        return self._fetch_series(series_id, start_date, end_date, recent_periods)


class BoJGetExchangeRateTool(BankOfJapanBaseTool):
    """
    Tool to retrieve JPY exchange rates
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_exchange_rate',
            'description': 'Retrieve Japanese Yen exchange rates',
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
                    "enum": ["usd_jpy", "eur_jpy"],
                    "default": "usd_jpy"
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
        currency_pair = arguments.get('currency_pair', 'usd_jpy')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        if currency_pair not in ['usd_jpy', 'eur_jpy']:
            return {"error": f"Unsupported currency pair: {currency_pair}"}
        
        return self._fetch_series(currency_pair, start_date, end_date, recent_periods)


class BoJGetMoneySupplyTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Japanese money supply data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_money_supply',
            'description': 'Retrieve Japanese money supply (M1, M2, M3)',
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
                    "enum": ["m1", "m2", "m3"],
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
        
        if aggregate not in ['m1', 'm2', 'm3']:
            return {"error": f"Unsupported aggregate: {aggregate}"}
        
        return self._fetch_series(aggregate, start_date, end_date, recent_periods)


class BoJGetInflationTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Japanese inflation data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_inflation',
            'description': 'Retrieve Japanese inflation data (CPI, PPI)',
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


class BoJGetEconomicIndicatorTool(BankOfJapanBaseTool):
    """
    Tool to retrieve various Japanese economic indicators
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_economic_indicator',
            'description': 'Retrieve Japanese economic indicators (GDP, unemployment, industrial production)',
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
                    "enum": ["gdp", "unemployment", "industrial_production", "trade_balance"],
                    "default": "gdp"
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
        indicator = arguments.get('indicator', 'gdp')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods')
        
        valid_indicators = ['gdp', 'unemployment', 'industrial_production', 'trade_balance']
        if indicator not in valid_indicators:
            return {"error": f"Unsupported indicator: {indicator}. Valid: {valid_indicators}"}
        
        return self._fetch_series(indicator, start_date, end_date, recent_periods)


class BoJListSeriesTools(BankOfJapanBaseTool):
    """
    Tool to list available Japanese economic series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_list_series',
            'description': 'List available Japanese economic data series',
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
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "fred_code": {"type": "string"},
                            "label": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute series listing"""
        category = arguments.get('category', 'all')
        
        category_mapping = {
            'rates': ['jgb_10y', 'jgb_3m', 'policy_rate', 'discount_rate'],
            'fx': ['usd_jpy', 'eur_jpy'],
            'money': ['m1', 'm2', 'm3'],
            'prices': ['cpi', 'core_cpi', 'ppi'],
            'economy': ['gdp', 'unemployment', 'industrial_production', 'trade_balance'],
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
JAPAN_CENTRAL_BANK_TOOLS = {
    'boj_get_jgb_yield': BoJGetJGBYieldTool,
    'boj_get_policy_rate': BoJGetPolicyRateTool,
    'boj_get_exchange_rate': BoJGetExchangeRateTool,
    'boj_get_money_supply': BoJGetMoneySupplyTool,
    'boj_get_inflation': BoJGetInflationTool,
    'boj_get_economic_indicator': BoJGetEconomicIndicatorTool,
    'boj_list_series': BoJListSeriesTools,
}
