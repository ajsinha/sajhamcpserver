"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
European Central Bank (ECB) MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool


class EuropeanCentralBankBaseTool(BaseMCPTool):
    """
    Base class for European Central Bank tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize European Central Bank base tool"""
        super().__init__(config)
        
        # ECB Statistical Data Warehouse API endpoint
        self.api_url = "https://data-api.ecb.europa.eu/service/data"
        
        # Common data series with ECB flow and key identifiers
        self.common_series = {
            # Exchange Rates (EXR - Exchange Rates)
            'eur_usd': {
                'flow': 'EXR',
                'key': 'D.USD.EUR.SP00.A',
                'description': 'EUR/USD Exchange Rate Daily'
            },
            'eur_gbp': {
                'flow': 'EXR',
                'key': 'D.GBP.EUR.SP00.A',
                'description': 'EUR/GBP Exchange Rate Daily'
            },
            'eur_jpy': {
                'flow': 'EXR',
                'key': 'D.JPY.EUR.SP00.A',
                'description': 'EUR/JPY Exchange Rate Daily'
            },
            'eur_cny': {
                'flow': 'EXR',
                'key': 'D.CNY.EUR.SP00.A',
                'description': 'EUR/CNY Exchange Rate Daily'
            },
            'eur_chf': {
                'flow': 'EXR',
                'key': 'D.CHF.EUR.SP00.A',
                'description': 'EUR/CHF Exchange Rate Daily'
            },
            
            # Interest Rates (FM - Financial Market Data)
            'main_refinancing_rate': {
                'flow': 'FM',
                'key': 'B.U2.EUR.4F.KR.MRR_FR.LEV',
                'description': 'Main Refinancing Operations Rate'
            },
            'deposit_facility_rate': {
                'flow': 'FM',
                'key': 'B.U2.EUR.4F.KR.DFR.LEV',
                'description': 'Deposit Facility Rate'
            },
            'marginal_lending_rate': {
                'flow': 'FM',
                'key': 'B.U2.EUR.4F.KR.MLFR.LEV',
                'description': 'Marginal Lending Facility Rate'
            },
            'eonia': {
                'flow': 'FM',
                'key': 'D.U2.EUR.4F.KR.EON.LEV',
                'description': 'Euro OverNight Index Average (EONIA)'
            },
            'ester': {
                'flow': 'FM',
                'key': 'D.U2.EUR.4F.KR.ESTER.LEV',
                'description': 'Euro Short-Term Rate (€STR)'
            },
            
            # Bond Yields (YC - Yield Curves)
            'bond_2y': {
                'flow': 'YC',
                'key': 'B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y',
                'description': '2-Year Euro Area Government Bond Yield'
            },
            'bond_5y': {
                'flow': 'YC',
                'key': 'B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y',
                'description': '5-Year Euro Area Government Bond Yield'
            },
            'bond_10y': {
                'flow': 'YC',
                'key': 'B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y',
                'description': '10-Year Euro Area Government Bond Yield'
            },
            
            # Inflation (ICP - HICP - Harmonised Index of Consumer Prices)
            'hicp_overall': {
                'flow': 'ICP',
                'key': 'M.U2.N.000000.4.ANR',
                'description': 'HICP - Overall Index'
            },
            'hicp_core': {
                'flow': 'ICP',
                'key': 'M.U2.N.XEF000.4.ANR',
                'description': 'HICP - All items excluding energy and food'
            },
            'hicp_energy': {
                'flow': 'ICP',
                'key': 'M.U2.N.NRG000.4.ANR',
                'description': 'HICP - Energy'
            },
            
            # GDP (MNA - Quarterly National Accounts)
            'gdp': {
                'flow': 'MNA',
                'key': 'Q.Y.I8.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N',
                'description': 'GDP at market prices'
            },
            
            # Money Supply (BSI - Balance Sheet Items)
            'm1': {
                'flow': 'BSI',
                'key': 'M.U2.Y.V.M10.X.1.U2.2300.Z01.E',
                'description': 'Monetary aggregate M1'
            },
            'm2': {
                'flow': 'BSI',
                'key': 'M.U2.Y.V.M20.X.1.U2.2300.Z01.E',
                'description': 'Monetary aggregate M2'
            },
            'm3': {
                'flow': 'BSI',
                'key': 'M.U2.Y.V.M30.X.1.U2.2300.Z01.E',
                'description': 'Monetary aggregate M3'
            },
            
            # Unemployment Rate (LFSI - Labour Force Survey Indicators)
            'unemployment_rate': {
                'flow': 'LFSI',
                'key': 'M.U2.N.S.UNEH.RTT000.4.AV3',
                'description': 'Unemployment Rate - Total'
            }
        }
    
    def _fetch_series(
        self,
        flow: str,
        key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = 10
    ) -> Dict:
        """
        Fetch time series data from ECB API
        
        Args:
            flow: ECB data flow identifier
            key: Series key
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        url = f"{self.api_url}/{flow}/{key}"
        
        params = {
            'format': 'jsondata',
            'detail': 'dataonly'
        }
        
        # Calculate date range
        if end_date:
            params['endPeriod'] = end_date
        
        if start_date:
            params['startPeriod'] = start_date
        elif not end_date and recent_periods:
            # If no dates specified, get recent data
            start = datetime.now() - timedelta(days=recent_periods * 40)
            params['startPeriod'] = start.strftime('%Y-%m-%d')
        
        url += '?' + urllib.parse.urlencode(params)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Parse ECB JSON structure
                if 'dataSets' not in data or not data['dataSets']:
                    return {
                        'flow': flow,
                        'key': key,
                        'observations': [],
                        'observation_count': 0,
                        'error': 'No data available'
                    }
                
                dataset = data['dataSets'][0]
                series_data = dataset.get('series', {})
                
                if not series_data:
                    return {
                        'flow': flow,
                        'key': key,
                        'observations': [],
                        'observation_count': 0
                    }
                
                # Get first (and usually only) series
                series_key = list(series_data.keys())[0]
                observations_dict = series_data[series_key].get('observations', {})
                
                # Get dimensions for time periods
                structure = data.get('structure', {})
                dimensions = structure.get('dimensions', {}).get('observation', [])
                time_dimension = None
                for dim in dimensions:
                    if dim.get('id') == 'TIME_PERIOD':
                        time_dimension = dim
                        break
                
                # Format observations
                formatted_obs = []
                if time_dimension:
                    time_values = time_dimension.get('values', [])
                    for idx, obs_data in observations_dict.items():
                        time_idx = int(idx)
                        if time_idx < len(time_values):
                            date = time_values[time_idx].get('id', time_values[time_idx].get('name', ''))
                            value = obs_data[0] if obs_data and len(obs_data) > 0 else None
                            formatted_obs.append({
                                'date': date,
                                'value': float(value) if value is not None else None
                            })
                
                # Sort by date and limit to recent_periods if needed
                formatted_obs.sort(key=lambda x: x['date'])
                if not (start_date and end_date) and len(formatted_obs) > recent_periods:
                    formatted_obs = formatted_obs[-recent_periods:]
                
                # Get series name/description
                series_name = key
                description = self._get_series_description(flow, key)
                
                return {
                    'flow': flow,
                    'key': key,
                    'series_name': series_name,
                    'description': description,
                    'observation_count': len(formatted_obs),
                    'observations': formatted_obs
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Series not found: {flow}/{key}")
            else:
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except urllib.error.URLError as e:
            raise ValueError(f"Failed to connect to ECB API: {str(e)}")
        except Exception as e:
            raise ValueError(f"Failed to get series data: {str(e)}")
    
    def _get_series_description(self, flow: str, key: str) -> str:
        """Get description for a series by matching common series"""
        for indicator, info in self.common_series.items():
            if info['flow'] == flow and info['key'] == key:
                return info['description']
        return f"{flow} - {key}"


class ECBGetSeriesTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve time series data from European Central Bank
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_series',
            'description': 'Retrieve time series economic data from European Central Bank by flow/key or indicator',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for retrieving time series data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow identifier (e.g., 'EXR' for exchange rates, 'FM' for financial markets, 'ICP' for inflation)"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key (e.g., 'D.USD.EUR.SP00.A' for USD/EUR daily)"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand name for convenience",
                    "enum": ["eur_usd", "eur_gbp", "eur_jpy", "eur_cny", "eur_chf",
                            "main_refinancing_rate", "deposit_facility_rate", "marginal_lending_rate", "eonia", "ester",
                            "bond_2y", "bond_5y", "bond_10y",
                            "hicp_overall", "hicp_core", "hicp_energy",
                            "gdp", "m1", "m2", "m3", "unemployment_rate"]
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (e.g., '2024-01-01')"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (e.g., '2024-12-31')"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of most recent observations to retrieve (1-100). Used when start_date and end_date are not specified.",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "oneOf": [
                {"required": ["flow", "key"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for time series data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow identifier"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the data series"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of observations returned"
                },
                "observations": {
                    "type": "array",
                    "description": "Time series observations",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Observation date (YYYY-MM-DD format)"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Observation value (null if not available)"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get series operation"""
        flow = arguments.get('flow')
        key = arguments.get('key')
        indicator = arguments.get('indicator')
        
        # Convert indicator to flow/key if provided
        if indicator and not (flow and key):
            series_info = self.common_series.get(indicator)
            if not series_info:
                raise ValueError(f"Unknown indicator: {indicator}")
            flow = series_info['flow']
            key = series_info['key']
        
        if not (flow and key):
            raise ValueError("Either 'flow' and 'key' or 'indicator' is required")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(flow, key, start_date, end_date, recent_periods)


class ECBGetExchangeRateTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve foreign exchange rates from European Central Bank
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_exchange_rate',
            'description': 'Retrieve foreign exchange rates for Euro against other currencies',
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
                    "description": "Currency pair in format 'EUR/XXX' (e.g., 'EUR/USD', 'EUR/GBP'). Always quotes EUR against other currency."
                },
                "indicator": {
                    "type": "string",
                    "description": "Pre-defined currency pair shorthand",
                    "enum": ["eur_usd", "eur_gbp", "eur_jpy", "eur_cny", "eur_chf"]
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
                    "description": "Number of recent observations to retrieve (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                }
            },
            "oneOf": [
                {"required": ["currency_pair"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for exchange rate data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow (EXR for exchange rates)"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Exchange rate series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Exchange rate description"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of exchange rate observations"
                },
                "observations": {
                    "type": "array",
                    "description": "Historical exchange rate data points",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Date of exchange rate"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Exchange rate value (units of foreign currency per EUR)"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get exchange rate operation"""
        currency_pair = arguments.get('currency_pair')
        indicator = arguments.get('indicator')
        
        if indicator:
            series_info = self.common_series.get(indicator)
            if not series_info:
                raise ValueError(f"Unknown currency indicator: {indicator}")
            flow = series_info['flow']
            key = series_info['key']
        elif currency_pair:
            # Parse currency pair (e.g., EUR/USD -> USD)
            if '/' in currency_pair:
                parts = currency_pair.split('/')
                if parts[0].upper() != 'EUR':
                    raise ValueError("Currency pair must start with EUR (e.g., EUR/USD)")
                currency = parts[1].upper()
            else:
                currency = currency_pair[-3:].upper()
            
            flow = 'EXR'
            key = f'D.{currency}.EUR.SP00.A'
        else:
            raise ValueError("Either 'currency_pair' or 'indicator' is required")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(flow, key, start_date, end_date, recent_periods)


class ECBGetInterestRateTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve interest rates from European Central Bank
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_interest_rate',
            'description': 'Retrieve ECB interest rates including main refinancing rate, deposit facility, and money market rates',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for interest rates"""
        return {
            "type": "object",
            "properties": {
                "rate_type": {
                    "type": "string",
                    "description": "Type of interest rate to retrieve",
                    "enum": ["main_refinancing_rate", "deposit_facility_rate", "marginal_lending_rate", "eonia", "ester"]
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
        """Get output schema for interest rate data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow (FM for financial markets)"
                },
                "key": {
                    "type": "string",
                    "description": "Interest rate series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Interest rate series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Description of the interest rate"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of rate observations"
                },
                "observations": {
                    "type": "array",
                    "description": "Historical interest rate values",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Effective date of the rate"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Interest rate percentage"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get interest rate operation"""
        rate_type = arguments.get('rate_type')
        
        series_info = self.common_series.get(rate_type)
        if not series_info:
            raise ValueError(f"Unknown rate type: {rate_type}")
        
        flow = series_info['flow']
        key = series_info['key']
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(flow, key, start_date, end_date, recent_periods)


class ECBGetBondYieldTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve Euro Area government bond yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_bond_yield',
            'description': 'Retrieve Euro Area government bond yields for various maturities',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for bond yields"""
        return {
            "type": "object",
            "properties": {
                "bond_term": {
                    "type": "string",
                    "description": "Bond maturity term",
                    "enum": ["2y", "5y", "10y"]
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
        """Get output schema for bond yield data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow (YC for yield curves)"
                },
                "key": {
                    "type": "string",
                    "description": "Bond yield series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Bond yield series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Bond description"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of yield observations"
                },
                "observations": {
                    "type": "array",
                    "description": "Historical bond yield values",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Date of yield observation"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Bond yield percentage"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get bond yield operation"""
        bond_term = arguments.get('bond_term')
        indicator_key = f'bond_{bond_term}'
        
        series_info = self.common_series.get(indicator_key)
        if not series_info:
            raise ValueError(f"Unknown bond term: {bond_term}")
        
        flow = series_info['flow']
        key = series_info['key']
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(flow, key, start_date, end_date, recent_periods)


class ECBGetInflationTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve HICP (Harmonised Index of Consumer Prices) inflation data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_inflation',
            'description': 'Retrieve HICP inflation measures for the Euro Area including overall, core, and energy inflation',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for inflation data"""
        return {
            "type": "object",
            "properties": {
                "inflation_type": {
                    "type": "string",
                    "description": "Type of inflation measure",
                    "enum": ["overall", "core", "energy"],
                    "default": "overall"
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
                    "default": 12
                }
            },
            "required": ["inflation_type"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for inflation data"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow (ICP for inflation)"
                },
                "key": {
                    "type": "string",
                    "description": "Inflation series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Inflation series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Description of inflation measure"
                },
                "observation_count": {
                    "type": "integer",
                    "description": "Number of inflation observations"
                },
                "observations": {
                    "type": "array",
                    "description": "Historical inflation values (annual rate of change)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "Date of inflation reading (YYYY-MM format for monthly)"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Annual inflation rate (%)"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get inflation operation"""
        inflation_type = arguments.get('inflation_type', 'overall')
        indicator_key = f'hicp_{inflation_type}'
        
        series_info = self.common_series.get(indicator_key)
        if not series_info:
            raise ValueError(f"Unknown inflation type: {inflation_type}")
        
        flow = series_info['flow']
        key = series_info['key']
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 12)
        
        return self._fetch_series(flow, key, start_date, end_date, recent_periods)


class ECBGetLatestTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve the latest observation for a specific series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_latest',
            'description': 'Retrieve the most recent observation for any European Central Bank data series',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for latest observation"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow identifier"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand",
                    "enum": ["eur_usd", "eur_gbp", "eur_jpy", "eur_cny", "eur_chf",
                            "main_refinancing_rate", "deposit_facility_rate", "marginal_lending_rate", "eonia", "ester",
                            "bond_2y", "bond_5y", "bond_10y",
                            "hicp_overall", "hicp_core", "hicp_energy",
                            "gdp", "m1", "m2", "m3", "unemployment_rate"]
                }
            },
            "oneOf": [
                {"required": ["flow", "key"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for latest observation"""
        return {
            "type": "object",
            "properties": {
                "flow": {
                    "type": "string",
                    "description": "ECB data flow identifier"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key"
                },
                "series_name": {
                    "type": "string",
                    "description": "Series identifier"
                },
                "description": {
                    "type": "string",
                    "description": "Series description"
                },
                "date": {
                    "type": "string",
                    "description": "Date of the latest observation"
                },
                "value": {
                    "type": ["number", "null"],
                    "description": "Latest observation value"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get latest operation"""
        flow = arguments.get('flow')
        key = arguments.get('key')
        indicator = arguments.get('indicator')
        
        if indicator and not (flow and key):
            series_info = self.common_series.get(indicator)
            if not series_info:
                raise ValueError(f"Unknown indicator: {indicator}")
            flow = series_info['flow']
            key = series_info['key']
        
        if not (flow and key):
            raise ValueError("Either 'flow' and 'key' or 'indicator' is required")
        
        # Fetch the most recent observation
        series_data = self._fetch_series(flow, key, recent_periods=1)
        
        if series_data.get('observations'):
            latest = series_data['observations'][-1]
            return {
                'flow': flow,
                'key': key,
                'series_name': series_data.get('series_name', key),
                'description': series_data.get('description', ''),
                'date': latest['date'],
                'value': latest['value']
            }
        else:
            raise ValueError(f"No data available for series: {flow}/{key}")


class ECBSearchSeriesTool(EuropeanCentralBankBaseTool):
    """
    Tool to search and discover available ECB data series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_search_series',
            'description': 'Search and discover available European Central Bank data series by category',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for series search"""
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (optional)",
                    "enum": ["Exchange Rates", "Interest Rates", "Bond Yields", "Inflation (HICP)", "Economic Indicators", "Money Supply", "all"]
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for series search results"""
        return {
            "type": "object",
            "properties": {
                "categories": {
                    "type": "object",
                    "description": "Available series organized by category",
                    "additionalProperties": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "indicator": {
                                    "type": "string",
                                    "description": "Shorthand indicator name"
                                },
                                "flow": {
                                    "type": "string",
                                    "description": "ECB data flow identifier"
                                },
                                "key": {
                                    "type": "string",
                                    "description": "ECB series key"
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Description of the data series"
                                }
                            }
                        }
                    }
                },
                "total_series": {
                    "type": "integer",
                    "description": "Total number of available series"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the search series operation"""
        category_filter = arguments.get('category', 'all')
        
        series_info = {}
        categories = {
            'Exchange Rates': [
                'eur_usd', 'eur_gbp', 'eur_jpy', 'eur_cny', 'eur_chf'
            ],
            'Interest Rates': [
                'main_refinancing_rate', 'deposit_facility_rate',
                'marginal_lending_rate', 'eonia', 'ester'
            ],
            'Bond Yields': ['bond_2y', 'bond_5y', 'bond_10y'],
            'Inflation (HICP)': ['hicp_overall', 'hicp_core', 'hicp_energy'],
            'Economic Indicators': ['gdp', 'unemployment_rate'],
            'Money Supply': ['m1', 'm2', 'm3']
        }
        
        # Filter categories if requested
        if category_filter != 'all' and category_filter in categories:
            categories = {category_filter: categories[category_filter]}
        
        # Build series info
        for category, indicators in categories.items():
            series_info[category] = []
            for indicator in indicators:
                info = self.common_series.get(indicator)
                if info:
                    series_info[category].append({
                        'indicator': indicator,
                        'flow': info['flow'],
                        'key': info['key'],
                        'description': info['description']
                    })
        
        return {
            'categories': series_info,
            'total_series': sum(len(v) for v in series_info.values())
        }


class ECBGetCommonIndicatorsTool(EuropeanCentralBankBaseTool):
    """
    Tool to retrieve multiple common economic indicators with their latest values
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'ecb_get_common_indicators',
            'description': 'Retrieve a dashboard of key Euro Area economic indicators with their latest values',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for common indicators"""
        return {
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "array",
                    "description": "Specific indicators to retrieve (optional, defaults to key indicators)",
                    "items": {
                        "type": "string",
                        "enum": ["eur_usd", "eur_gbp", "main_refinancing_rate", "deposit_facility_rate",
                                "bond_2y", "bond_5y", "bond_10y",
                                "hicp_overall", "hicp_core", "gdp", "unemployment_rate",
                                "m1", "m2", "m3"]
                    }
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for common indicators"""
        return {
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "object",
                    "description": "Key economic indicators with latest values",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "flow": {
                                "type": "string",
                                "description": "ECB data flow"
                            },
                            "key": {
                                "type": "string",
                                "description": "ECB series key"
                            },
                            "description": {
                                "type": "string",
                                "description": "Indicator description"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Latest value"
                            },
                            "date": {
                                "type": "string",
                                "description": "Date of latest value"
                            },
                            "error": {
                                "type": "string",
                                "description": "Error message if retrieval failed"
                            }
                        }
                    }
                },
                "last_updated": {
                    "type": "string",
                    "description": "Timestamp when this data was retrieved (ISO format)"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get common indicators operation"""
        requested_indicators = arguments.get('indicators', [
            'eur_usd', 'main_refinancing_rate', 'bond_10y', 
            'hicp_overall', 'unemployment_rate'
        ])
        
        indicators = {}
        
        for indicator in requested_indicators:
            try:
                series_info = self.common_series.get(indicator)
                if not series_info:
                    indicators[indicator] = {
                        'error': f'Unknown indicator: {indicator}'
                    }
                    continue
                
                flow = series_info['flow']
                key = series_info['key']
                
                # Fetch latest observation
                series_data = self._fetch_series(flow, key, recent_periods=1)
                
                if series_data.get('observations'):
                    latest = series_data['observations'][-1]
                    indicators[indicator] = {
                        'flow': flow,
                        'key': key,
                        'description': series_info['description'],
                        'value': latest['value'],
                        'date': latest['date']
                    }
                else:
                    indicators[indicator] = {
                        'flow': flow,
                        'key': key,
                        'description': series_info['description'],
                        'error': 'No data available'
                    }
                    
            except Exception as e:
                self.logger.warning(f"Failed to get {indicator}: {e}")
                series_info = self.common_series.get(indicator, {})
                indicators[indicator] = {
                    'flow': series_info.get('flow'),
                    'key': series_info.get('key'),
                    'description': series_info.get('description', ''),
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }


# Tool registry for easy access
EUROPEAN_CENTRAL_BANK_TOOLS = {
    'ecb_get_series': ECBGetSeriesTool,
    'ecb_get_exchange_rate': ECBGetExchangeRateTool,
    'ecb_get_interest_rate': ECBGetInterestRateTool,
    'ecb_get_bond_yield': ECBGetBondYieldTool,
    'ecb_get_inflation': ECBGetInflationTool,
    'ecb_get_latest': ECBGetLatestTool,
    'ecb_search_series': ECBSearchSeriesTool,
    'ecb_get_common_indicators': ECBGetCommonIndicatorsTool
}
