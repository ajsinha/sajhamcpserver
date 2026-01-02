"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Banque de France / ECB MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool


class BanqueDeFranceBaseTool(BaseMCPTool):
    """
    Base class for Banque de France / ECB tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Banque de France base tool"""
        super().__init__(config)
        
        # Banque de France Webstat API endpoint
        self.bdf_api_url = "https://webstat.banque-france.fr/ws/rest/data"
        # ECB Statistical Data Warehouse API
        self.ecb_api_url = "https://sdw-wsrest.ecb.europa.eu/service/data"
        
        # Common data series mapping
        self.common_series = {
            # ECB Policy Rates
            'ecb_main_refi': 'FM.B.U2.EUR.4F.KR.MRR_FR.LEV',  # Main refinancing rate
            'ecb_deposit': 'FM.B.U2.EUR.4F.KR.DFR.LEV',  # Deposit facility rate
            'ecb_marginal_lending': 'FM.B.U2.EUR.4F.KR.MLFR.LEV',  # Marginal lending rate
            
            # French Government Bond Yields (OAT - Obligations Assimilables du Trésor)
            'oat_2y': 'IRS.M.FR.L.L40.CI.0000.EUR.N.Z',
            'oat_5y': 'IRS.M.FR.L.L40.CI.0000.EUR.N.Z',
            'oat_10y': 'IRS.M.FR.L.L40.CI.0000.EUR.N.Z',
            'oat_30y': 'IRS.M.FR.L.L40.CI.0000.EUR.N.Z',
            
            # Exchange Rates (EUR based)
            'eur_usd': 'EXR.D.USD.EUR.SP00.A',
            'eur_gbp': 'EXR.D.GBP.EUR.SP00.A',
            'eur_jpy': 'EXR.D.JPY.EUR.SP00.A',
            'eur_cny': 'EXR.D.CNY.EUR.SP00.A',
            
            # French Economic Indicators
            'fr_cpi': 'ICP.M.FR.N.000000.4.ANR',  # France CPI
            'fr_gdp': 'MNA.Q.Y.FR.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N',
            'fr_unemployment': 'LFSI.M.FR.S.UNEHRT.TOTAL0.15_74.T',
            
            # Eurozone Aggregates
            'ez_cpi': 'ICP.M.U2.N.000000.4.ANR',
            'ez_gdp': 'MNA.Q.Y.I8.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N',
            'm3': 'BSI.M.U2.N.A.A20.A.1.U2.2240.Z01.E',  # Eurozone M3
        }
    
    def _fetch_series_ecb(
        self,
        series_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from ECB API
        
        Args:
            series_code: ECB series code
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        url = f"{self.ecb_api_url}/{series_code}"
        params = {'format': 'jsondata'}
        
        if start_date:
            params['startPeriod'] = start_date
        if end_date:
            params['endPeriod'] = end_date
        
        url += '?' + urllib.parse.urlencode(params)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                observations = []
                if 'dataSets' in data and data['dataSets']:
                    obs_data = data['dataSets'][0].get('series', {}).get('0:0:0:0:0:0:0:0:0', {}).get('observations', {})
                    structure = data.get('structure', {})
                    dimensions = structure.get('dimensions', {}).get('observation', [])
                    time_values = next((d['values'] for d in dimensions if d.get('id') == 'TIME_PERIOD'), [])
                    
                    for idx, obs in obs_data.items():
                        time_idx = int(idx)
                        if time_idx < len(time_values):
                            observations.append({
                                'date': time_values[time_idx]['id'],
                                'value': float(obs[0]) if obs and obs[0] else None
                            })
                
                # Apply recent_periods filter if specified
                if recent_periods and not start_date and not end_date:
                    observations = observations[-recent_periods:]
                
                return {
                    'series_code': series_code,
                    'label': series_code,
                    'description': '',
                    'unit': '%',
                    'frequency': 'Daily',
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

    _fetch_series = _fetch_series_ecb  # Default to ECB API


class BdFGetOATYieldTool(BanqueDeFranceBaseTool):
    """Tool to retrieve French Government Bond (OAT) yields"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'bdf_get_oat_yield',
            'description': 'Retrieve French Government Bond (OAT) yields for various maturities',
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
                    "enum": ["2y", "5y", "10y", "30y"],
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
        term_mapping = {'2y': 'oat_2y', '5y': 'oat_5y', '10y': 'oat_10y', '30y': 'oat_30y'}
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


class BdFGetECBPolicyRateTool(BanqueDeFranceBaseTool):
    """Tool to retrieve ECB policy rates"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'bdf_get_ecb_policy_rate',
            'description': 'Retrieve ECB policy rates including main refinancing, deposit, and marginal lending rates',
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
                    "enum": ["ecb_main_refi", "ecb_deposit", "ecb_marginal_lending"],
                    "default": "ecb_main_refi"
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
        rate_type = arguments.get('rate_type', 'ecb_main_refi')
        series_code = self.common_series.get(rate_type)
        if not series_code:
            raise ValueError(f"Invalid rate type: {rate_type}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class BdFGetExchangeRateTool(BanqueDeFranceBaseTool):
    """Tool to retrieve EUR exchange rates"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'bdf_get_exchange_rate',
            'description': 'Retrieve Euro exchange rates against major currencies',
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
                    "enum": ["eur_usd", "eur_gbp", "eur_jpy", "eur_cny"],
                    "default": "eur_usd"
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
        currency_pair = arguments.get('currency_pair', 'eur_usd')
        series_code = self.common_series.get(currency_pair)
        if not series_code:
            raise ValueError(f"Invalid currency pair: {currency_pair}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class BdFGetFrenchEconomicIndicatorTool(BanqueDeFranceBaseTool):
    """Tool to retrieve French economic indicators"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'bdf_get_french_indicator',
            'description': 'Retrieve French economic indicators including CPI, GDP, and unemployment',
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
                "indicator": {
                    "type": "string",
                    "enum": ["fr_cpi", "fr_gdp", "fr_unemployment"],
                    "default": "fr_cpi"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["indicator"]
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
        indicator = arguments.get('indicator', 'fr_cpi')
        series_code = self.common_series.get(indicator)
        if not series_code:
            raise ValueError(f"Invalid indicator: {indicator}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


class BdFGetEurozoneIndicatorTool(BanqueDeFranceBaseTool):
    """Tool to retrieve Eurozone-wide economic indicators"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'bdf_get_eurozone_indicator',
            'description': 'Retrieve Eurozone economic indicators including CPI, GDP, and M3',
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
                "indicator": {
                    "type": "string",
                    "enum": ["ez_cpi", "ez_gdp", "m3"],
                    "default": "ez_cpi"
                },
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
            },
            "required": ["indicator"]
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
        indicator = arguments.get('indicator', 'ez_cpi')
        series_code = self.common_series.get(indicator)
        if not series_code:
            raise ValueError(f"Invalid indicator: {indicator}")
        
        return self._fetch_series(
            series_code,
            arguments.get('start_date'),
            arguments.get('end_date'),
            arguments.get('recent_periods', 10)
        )


# Tool registry
BANQUE_DE_FRANCE_TOOLS = {
    'bdf_get_oat_yield': BdFGetOATYieldTool,
    'bdf_get_ecb_policy_rate': BdFGetECBPolicyRateTool,
    'bdf_get_exchange_rate': BdFGetExchangeRateTool,
    'bdf_get_french_indicator': BdFGetFrenchEconomicIndicatorTool,
    'bdf_get_eurozone_indicator': BdFGetEurozoneIndicatorTool
}
