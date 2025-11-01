"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Reserve Bank of India (RBI) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class ReserveBankOfIndiaBaseTool(BaseMCPTool):
    """
    Base class for Reserve Bank of India tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Reserve Bank of India base tool"""
        super().__init__(config)
        
        # RBI Database on Indian Economy (DBIE) API endpoint
        self.api_url = "https://rbi.org.in/Scripts/api/dbie"
        
        # Common data series mapping (RBI series codes)
        self.common_series = {
            # Policy Rates
            'repo_rate': 'RBI_REPO',
            'reverse_repo_rate': 'RBI_REV_REPO',
            'bank_rate': 'RBI_BANK_RATE',
            'crr': 'RBI_CRR',  # Cash Reserve Ratio
            'slr': 'RBI_SLR',  # Statutory Liquidity Ratio
            
            # Government Bond Yields
            'gsec_1y': 'GSEC_1Y',
            'gsec_5y': 'GSEC_5Y',
            'gsec_10y': 'GSEC_10Y',
            'gsec_30y': 'GSEC_30Y',
            
            # Exchange Rates (INR per foreign currency)
            'usd_inr': 'USD_INR',
            'eur_inr': 'EUR_INR',
            'gbp_inr': 'GBP_INR',
            'jpy_inr': 'JPY_INR',
            
            # Inflation
            'cpi': 'CPI_ALL',
            'wpi': 'WPI_ALL',
            'core_cpi': 'CPI_CORE',
            
            # Economic Indicators
            'gdp': 'GDP_CURRENT',
            'iip': 'IIP_GENERAL',  # Index of Industrial Production
            'forex_reserves': 'FOREX_RESERVES',
        }
    
    def _fetch_series(
        self,
        series_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from RBI API
        
        Args:
            series_code: RBI series code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        params = {
            'series': series_code,
            'format': 'json'
        }
        
        if start_date:
            params['fromDate'] = start_date
        if end_date:
            params['toDate'] = end_date
        
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                observations = []
                if 'data' in data:
                    for item in data['data']:
                        observations.append({
                            'date': item.get('date'),
                            'value': float(item.get('value')) if item.get('value') else None
                        })
                
                # Apply recent_periods filter if specified
                if recent_periods and not start_date and not end_date:
                    observations = observations[-recent_periods:]
                
                return {
                    'series_code': series_code,
                    'label': data.get('seriesName', series_code),
                    'description': data.get('description', ''),
                    'unit': data.get('unit', ''),
                    'frequency': data.get('frequency', ''),
                    'observation_count': len(observations),
                    'observations': observations
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Series not found: {series_code}")
            else:
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to get series data: {str(e)}")


class RBIGetGSecYieldTool(ReserveBankOfIndiaBaseTool):
    """
    Tool to retrieve Indian Government Securities (G-Sec) yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'rbi_get_gsec_yield',
            'description': 'Retrieve Indian Government Securities (G-Sec) yields for various maturities',
            'version': '1.0.0',
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
                    "enum": ["1y", "5y", "10y", "30y"],
                    "default": "10y"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "required": ["bond_term"]
        }
    
    def get_output_schema(self) -> Dict:
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
        bond_term = arguments.get('bond_term', '10y')
        term_mapping = {'1y': 'gsec_1y', '5y': 'gsec_5y', '10y': 'gsec_10y', '30y': 'gsec_30y'}
        indicator = term_mapping.get(bond_term)
        if not indicator:
            raise ValueError(f"Invalid bond term: {bond_term}")
        
        series_code = self.common_series[indicator]
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class RBIGetPolicyRateTool(ReserveBankOfIndiaBaseTool):
    """Tool to retrieve RBI policy rates"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'rbi_get_policy_rate',
            'description': 'Retrieve RBI policy rates including repo, reverse repo, and bank rate',
            'version': '1.0.0',
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
                    "enum": ["repo_rate", "reverse_repo_rate", "bank_rate", "crr", "slr"],
                    "default": "repo_rate"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["rate_type"]
        }
    
    def get_output_schema(self) -> Dict:
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
        rate_type = arguments.get('rate_type', 'repo_rate')
        series_code = self.common_series.get(rate_type)
        if not series_code:
            raise ValueError(f"Invalid rate type: {rate_type}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class RBIGetExchangeRateTool(ReserveBankOfIndiaBaseTool):
    """Tool to retrieve INR exchange rates"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'rbi_get_exchange_rate',
            'description': 'Retrieve Indian Rupee exchange rates against major currencies',
            'version': '1.0.0',
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
                    "enum": ["usd_inr", "eur_inr", "gbp_inr", "jpy_inr"],
                    "default": "usd_inr"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["currency_pair"]
        }
    
    def get_output_schema(self) -> Dict:
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
        currency_pair = arguments.get('currency_pair', 'usd_inr')
        series_code = self.common_series.get(currency_pair)
        if not series_code:
            raise ValueError(f"Invalid currency pair: {currency_pair}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class RBIGetInflationTool(ReserveBankOfIndiaBaseTool):
    """Tool to retrieve Indian inflation data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'rbi_get_inflation',
            'description': 'Retrieve Indian inflation data including CPI and WPI',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "index_type": {
                    "type": "string",
                    "enum": ["cpi", "wpi", "core_cpi"],
                    "default": "cpi"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["index_type"]
        }
    
    def get_output_schema(self) -> Dict:
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
        index_type = arguments.get('index_type', 'cpi')
        series_code = self.common_series.get(index_type)
        if not series_code:
            raise ValueError(f"Invalid index type: {index_type}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class RBIGetForexReservesTool(ReserveBankOfIndiaBaseTool):
    """Tool to retrieve India's foreign exchange reserves"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'rbi_get_forex_reserves',
            'description': 'Retrieve India foreign exchange reserves data',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            }
        }
    
    def get_output_schema(self) -> Dict:
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
        series_code = self.common_series['forex_reserves']
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


# Tool registry
RESERVE_BANK_OF_INDIA_TOOLS = {
    'rbi_get_gsec_yield': RBIGetGSecYieldTool,
    'rbi_get_policy_rate': RBIGetPolicyRateTool,
    'rbi_get_exchange_rate': RBIGetExchangeRateTool,
    'rbi_get_inflation': RBIGetInflationTool,
    'rbi_get_forex_reserves': RBIGetForexReservesTool
}
