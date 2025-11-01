"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Bank of Japan (BoJ) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class BankOfJapanBaseTool(BaseMCPTool):
    """
    Base class for Bank of Japan tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Bank of Japan base tool"""
        super().__init__(config)
        
        # Bank of Japan Time-Series Data Search API endpoint
        self.api_url = "https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2"
        
        # Common data series mapping (BoJ uses statistical codes)
        self.common_series = {
            # Policy Rates
            'policy_rate': 'FM01_M_1_1',  # Uncollateralized overnight call rate
            'discount_rate': 'FM01_M_2_1',  # Basic discount rate and basic loan rate
            
            # JGB Yields (Japanese Government Bonds)
            'jgb_2y': 'FM08_D_1_3_1',  # 2-year JGB yield
            'jgb_5y': 'FM08_D_1_4_1',  # 5-year JGB yield
            'jgb_10y': 'FM08_D_1_5_1',  # 10-year JGB yield
            'jgb_30y': 'FM08_D_1_9_1',  # 30-year JGB yield
            
            # Exchange Rates (Yen per foreign currency)
            'usd_jpy': 'FM02_D_1_1',  # USD/JPY
            'eur_jpy': 'FM02_D_1_2',  # EUR/JPY
            'gbp_jpy': 'FM02_D_1_3',  # GBP/JPY
            'cny_jpy': 'FM02_D_1_11',  # CNY/JPY (100 yuan)
            
            # Money Stock
            'm1': 'MS01_M_1_1',  # M1 (seasonally adjusted)
            'm2': 'MS01_M_2_1',  # M2 (seasonally adjusted)
            'm3': 'MS01_M_3_1',  # M3 (seasonally adjusted)
            
            # Price Indices
            'cpi': 'PR01_M_1_1',  # CPI (nationwide, all items)
            'core_cpi': 'PR01_M_1_2',  # CPI excluding fresh food
            'ppi': 'PR02_M_1_1',  # Producer Price Index
        }
    
    def _fetch_series(
        self,
        series_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from Bank of Japan API
        
        Args:
            series_code: BoJ series code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        # Note: BoJ API requires specific formatting
        # This is a simplified implementation - actual API may require more complex handling
        
        params = {
            'LANG': 'EN',
            'SERIES_CODE': series_code,
            'OUTPUT': 'json'
        }
        
        if start_date:
            params['START_DATE'] = start_date.replace('-', '')
        if end_date:
            params['END_DATE'] = end_date.replace('-', '')
        
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Parse BoJ response format
                observations = []
                if 'TIME_SERIES' in data:
                    series = data['TIME_SERIES'].get(series_code, {})
                    obs_data = series.get('OBS', [])
                    
                    for obs in obs_data:
                        observations.append({
                            'date': obs.get('TIME_PERIOD'),
                            'value': float(obs.get('OBS_VALUE')) if obs.get('OBS_VALUE') else None
                        })
                    
                    # Apply recent_periods filter if specified
                    if recent_periods and not start_date and not end_date:
                        observations = observations[-recent_periods:]
                    
                    return {
                        'series_code': series_code,
                        'label': series.get('SERIES_NAME', series_code),
                        'description': series.get('DESCRIPTION', ''),
                        'unit': series.get('UNIT', ''),
                        'frequency': series.get('FREQ', ''),
                        'observation_count': len(observations),
                        'observations': observations
                    }
                else:
                    raise ValueError("Invalid response format from BoJ API")
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Series not found: {series_code}")
            else:
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to get series data: {str(e)}")


class BoJGetJGBYieldTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Japanese Government Bond (JGB) yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_jgb_yield',
            'description': 'Retrieve Japanese Government Bond (JGB) yields for various maturities',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for JGB yields"""
        return {
            "type": "object",
            "properties": {
                "bond_term": {
                    "type": "string",
                    "description": "JGB maturity term",
                    "enum": ["2y", "5y", "10y", "30y"],
                    "default": "10y"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["bond_term"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for JGB yields"""
        return {
            "type": "object",
            "properties": {
                "series_code": {
                    "type": "string",
                    "description": "JGB yield series code"
                },
                "label": {
                    "type": "string",
                    "description": "Bond description"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed bond information"
                },
                "unit": {
                    "type": "string",
                    "description": "Unit of measurement (typically percentage)"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of yield observations returned"
                },
                "observations": {
                    "type": "array",
                    "description": "Historical JGB yield values",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Date of yield observation"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "JGB yield percentage"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the JGB yield retrieval"""
        bond_term = arguments.get('bond_term', '10y')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        # Map bond term to series code
        term_mapping = {
            '2y': 'jgb_2y',
            '5y': 'jgb_5y',
            '10y': 'jgb_10y',
            '30y': 'jgb_30y'
        }
        
        indicator = term_mapping.get(bond_term)
        if not indicator:
            raise ValueError(f"Invalid bond term: {bond_term}")
        
        series_code = self.common_series[indicator]
        return self._fetch_series(series_code, start_date, end_date, recent_periods)


class BoJGetExchangeRateTool(BankOfJapanBaseTool):
    """
    Tool to retrieve JPY exchange rates
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_exchange_rate',
            'description': 'Retrieve Japanese Yen exchange rates against major currencies',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for exchange rates"""
        return {
            "type": "object",
            "properties": {
                "currency_pair": {
                    "type": "string",
                    "description": "Currency pair (foreign currency per JPY)",
                    "enum": ["usd_jpy", "eur_jpy", "gbp_jpy", "cny_jpy"],
                    "default": "usd_jpy"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["currency_pair"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for exchange rates"""
        return {
            "type": "object",
            "properties": {
                "series_code": {
                    "type": "string",
                    "description": "Exchange rate series code"
                },
                "label": {
                    "type": "string",
                    "description": "Currency pair description"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of observations returned"
                },
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute exchange rate retrieval"""
        currency_pair = arguments.get('currency_pair', 'usd_jpy')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        series_code = self.common_series.get(currency_pair)
        if not series_code:
            raise ValueError(f"Invalid currency pair: {currency_pair}")
        
        return self._fetch_series(series_code, start_date, end_date, recent_periods)


class BoJGetPolicyRateTool(BankOfJapanBaseTool):
    """
    Tool to retrieve Bank of Japan policy rate
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_policy_rate',
            'description': 'Retrieve Bank of Japan policy interest rate',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for policy rate"""
        return {
            "type": "object",
            "properties": {
                "rate_type": {
                    "type": "string",
                    "description": "Type of policy rate",
                    "enum": ["policy_rate", "discount_rate"],
                    "default": "policy_rate"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["rate_type"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for policy rate"""
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observation_count": {"type": "integer"},
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute policy rate retrieval"""
        rate_type = arguments.get('rate_type', 'policy_rate')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        series_code = self.common_series.get(rate_type)
        if not series_code:
            raise ValueError(f"Invalid rate type: {rate_type}")
        
        return self._fetch_series(series_code, start_date, end_date, recent_periods)


class BoJGetMoneyStockTool(BankOfJapanBaseTool):
    """
    Tool to retrieve money stock data (M1, M2, M3)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_money_stock',
            'description': 'Retrieve Japanese money stock indicators (M1, M2, M3)',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for money stock"""
        return {
            "type": "object",
            "properties": {
                "aggregate": {
                    "type": "string",
                    "description": "Money stock aggregate",
                    "enum": ["m1", "m2", "m3"],
                    "default": "m2"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["aggregate"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for money stock"""
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "unit": {"type": "string"},
                "observation_count": {"type": "integer"},
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute money stock retrieval"""
        aggregate = arguments.get('aggregate', 'm2')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        series_code = self.common_series.get(aggregate)
        if not series_code:
            raise ValueError(f"Invalid aggregate: {aggregate}")
        
        return self._fetch_series(series_code, start_date, end_date, recent_periods)


class BoJGetPriceIndexTool(BankOfJapanBaseTool):
    """
    Tool to retrieve price indices (CPI, PPI)
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boj_get_price_index',
            'description': 'Retrieve Japanese price indices including CPI and PPI',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for price indices"""
        return {
            "type": "object",
            "properties": {
                "index_type": {
                    "type": "string",
                    "description": "Type of price index",
                    "enum": ["cpi", "core_cpi", "ppi"],
                    "default": "cpi"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent observations (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["index_type"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for price indices"""
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "observation_count": {"type": "integer"},
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute price index retrieval"""
        index_type = arguments.get('index_type', 'cpi')
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        series_code = self.common_series.get(index_type)
        if not series_code:
            raise ValueError(f"Invalid index type: {index_type}")
        
        return self._fetch_series(series_code, start_date, end_date, recent_periods)


# Tool registry for easy access
BANK_OF_JAPAN_TOOLS = {
    'boj_get_jgb_yield': BoJGetJGBYieldTool,
    'boj_get_exchange_rate': BoJGetExchangeRateTool,
    'boj_get_policy_rate': BoJGetPolicyRateTool,
    'boj_get_money_stock': BoJGetMoneyStockTool,
    'boj_get_price_index': BoJGetPriceIndexTool
}
