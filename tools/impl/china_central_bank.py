"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
People's Bank of China (PBoC) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class PeoplesBankOfChinaBaseTool(BaseMCPTool):
    """
    Base class for People's Bank of China tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize People's Bank of China base tool"""
        super().__init__(config)
        
        # PBoC Data API endpoint
        self.api_url = "http://www.pbc.gov.cn/diaochatongjisi/resource/cms/api"
        
        # Common data series mapping
        self.common_series = {
            # Policy Rates
            'lpr_1y': 'LPR_1Y',  # Loan Prime Rate 1-year
            'lpr_5y': 'LPR_5Y',  # Loan Prime Rate 5-year
            'mlf_rate': 'MLF_RATE',  # Medium-term Lending Facility rate
            'omo_rate': 'OMO_7D',  # 7-day Open Market Operation rate
            'required_reserve_ratio': 'RRR',
            
            # Bond Yields (China Government Bonds)
            'cgb_1y': 'CGB_1Y',
            'cgb_5y': 'CGB_5Y',
            'cgb_10y': 'CGB_10Y',
            'cgb_30y': 'CGB_30Y',
            
            # Exchange Rates (CNY per foreign currency)
            'usd_cny': 'USD_CNY',
            'eur_cny': 'EUR_CNY',
            'jpy_cny': 'JPY_CNY',
            'hkd_cny': 'HKD_CNY',
            
            # Money Supply
            'm0': 'M0',  # Currency in circulation
            'm1': 'M1',
            'm2': 'M2',
            
            # Economic Indicators
            'cpi': 'CPI_ALL',
            'ppi': 'PPI_ALL',
            'forex_reserves': 'FOREX_RESERVES',
            'gold_reserves': 'GOLD_RESERVES',
        }
    
    def _fetch_series(
        self,
        series_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from PBoC API
        
        Args:
            series_code: PBoC series code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        params = {
            'seriesCode': series_code,
            'format': 'json'
        }
        
        if start_date:
            params['startDate'] = start_date
        if end_date:
            params['endDate'] = end_date
        
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


class PBoCGetCGBYieldTool(PeoplesBankOfChinaBaseTool):
    """Tool to retrieve China Government Bond yields"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_cgb_yield',
            'description': 'Retrieve China Government Bond yields for various maturities',
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
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["bond_term"]
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
        bond_term = arguments.get('bond_term', '10y')
        term_mapping = {'1y': 'cgb_1y', '5y': 'cgb_5y', '10y': 'cgb_10y', '30y': 'cgb_30y'}
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


class PBoCGetLPRTool(PeoplesBankOfChinaBaseTool):
    """Tool to retrieve Loan Prime Rate (LPR)"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_lpr',
            'description': 'Retrieve China Loan Prime Rate (LPR) for 1-year and 5-year tenors',
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
                "tenor": {
                    "type": "string",
                    "enum": ["1y", "5y"],
                    "default": "1y"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["tenor"]
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
        tenor = arguments.get('tenor', '1y')
        tenor_mapping = {'1y': 'lpr_1y', '5y': 'lpr_5y'}
        indicator = tenor_mapping.get(tenor)
        if not indicator:
            raise ValueError(f"Invalid tenor: {tenor}")
        
        series_code = self.common_series[indicator]
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class PBoCGetExchangeRateTool(PeoplesBankOfChinaBaseTool):
    """Tool to retrieve CNY exchange rates"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_exchange_rate',
            'description': 'Retrieve Chinese Yuan exchange rates against major currencies',
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
                    "enum": ["usd_cny", "eur_cny", "jpy_cny", "hkd_cny"],
                    "default": "usd_cny"
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
        currency_pair = arguments.get('currency_pair', 'usd_cny')
        series_code = self.common_series.get(currency_pair)
        if not series_code:
            raise ValueError(f"Invalid currency pair: {currency_pair}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class PBoCGetMoneySupplyTool(PeoplesBankOfChinaBaseTool):
    """Tool to retrieve money supply data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_money_supply',
            'description': 'Retrieve Chinese money supply indicators (M0, M1, M2)',
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
                "aggregate": {
                    "type": "string",
                    "enum": ["m0", "m1", "m2"],
                    "default": "m2"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["aggregate"]
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
        aggregate = arguments.get('aggregate', 'm2')
        series_code = self.common_series.get(aggregate)
        if not series_code:
            raise ValueError(f"Invalid aggregate: {aggregate}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class PBoCGetForexReservesTool(PeoplesBankOfChinaBaseTool):
    """Tool to retrieve foreign exchange reserves"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'pboc_get_forex_reserves',
            'description': 'Retrieve China foreign exchange and gold reserves',
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
                "reserve_type": {
                    "type": "string",
                    "enum": ["forex_reserves", "gold_reserves"],
                    "default": "forex_reserves"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["reserve_type"]
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
        reserve_type = arguments.get('reserve_type', 'forex_reserves')
        series_code = self.common_series.get(reserve_type)
        if not series_code:
            raise ValueError(f"Invalid reserve type: {reserve_type}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


# Tool registry
PEOPLES_BANK_OF_CHINA_TOOLS = {
    'pboc_get_cgb_yield': PBoCGetCGBYieldTool,
    'pboc_get_lpr': PBoCGetLPRTool,
    'pboc_get_exchange_rate': PBoCGetExchangeRateTool,
    'pboc_get_money_supply': PBoCGetMoneySupplyTool,
    'pboc_get_forex_reserves': PBoCGetForexReservesTool
}
