"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
European Central Bank (ECB) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools.base_mcp_tool import BaseMCPTool

class EuropeanCentralBankTool(BaseMCPTool):
    """
    European Central Bank (ECB) Statistical Data Warehouse API tool for retrieving 
    European economic and financial data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize European Central Bank tool"""
        default_config = {
            'name': 'european_central_bank',
            'description': 'Retrieve economic and financial data from European Central Bank',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
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
    
    def get_input_schema(self) -> Dict:
        """Get input schema for European Central Bank tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_series",
                        "get_exchange_rate",
                        "get_interest_rate",
                        "get_bond_yield",
                        "get_inflation",
                        "get_latest",
                        "get_common_indicators",
                        "search_series"
                    ]
                },
                "flow": {
                    "type": "string",
                    "description": "ECB data flow identifier (e.g., EXR, FM, ICP)"
                },
                "key": {
                    "type": "string",
                    "description": "ECB series key"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator name",
                    "enum": list(self.common_series.keys())
                },
                "currency_pair": {
                    "type": "string",
                    "description": "Currency pair for exchange rates (e.g., EUR/USD)"
                },
                "rate_type": {
                    "type": "string",
                    "description": "Type of interest rate",
                    "enum": [
                        "main_refinancing_rate",
                        "deposit_facility_rate",
                        "marginal_lending_rate",
                        "eonia",
                        "ester"
                    ]
                },
                "bond_term": {
                    "type": "string",
                    "description": "Bond term/maturity",
                    "enum": ["2y", "5y", "10y"]
                },
                "inflation_type": {
                    "type": "string",
                    "description": "Type of inflation measure",
                    "enum": ["overall", "core", "energy"]
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD format)"
                },
                "recent_periods": {
                    "type": "integer",
                    "description": "Number of recent periods to retrieve",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute European Central Bank tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Economic/financial data from European Central Bank
        """
        action = arguments.get('action')
        
        if action == 'get_series':
            flow = arguments.get('flow')
            key = arguments.get('key')
            indicator = arguments.get('indicator')
            
            # Convert indicator to flow and key if provided
            if indicator and not (flow and key):
                series_info = self.common_series.get(indicator)
                if series_info:
                    flow = series_info['flow']
                    key = series_info['key']
            
            if not (flow and key):
                raise ValueError("Either 'flow' and 'key', or 'indicator' is required")
            
            start_date = arguments.get('start_date')
            end_date = arguments.get('end_date')
            recent_periods = arguments.get('recent_periods', 10)
            
            return self._get_series(flow, key, start_date, end_date, recent_periods)
            
        elif action == 'get_exchange_rate':
            currency_pair = arguments.get('currency_pair')
            indicator = arguments.get('indicator')
            
            if indicator:
                series_info = self.common_series.get(indicator)
                if series_info:
                    flow = series_info['flow']
                    key = series_info['key']
                else:
                    raise ValueError(f"Unknown indicator: {indicator}")
            elif currency_pair:
                # Convert currency pair to ECB format
                # ECB format: EUR/USD means 1 EUR = X USD
                parts = currency_pair.replace('/', ' ').split()
                if len(parts) == 2 and parts[0].upper() == 'EUR':
                    currency = parts[1].upper()
                    flow = 'EXR'
                    key = f'D.{currency}.EUR.SP00.A'
                else:
                    raise ValueError(f"Invalid currency pair format: {currency_pair}. Must be EUR/XXX")
            else:
                raise ValueError("Either 'currency_pair' or 'indicator' is required")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(flow, key, recent_periods=recent_periods)
            
        elif action == 'get_interest_rate':
            rate_type = arguments.get('rate_type', 'main_refinancing_rate')
            series_info = self.common_series.get(rate_type)
            
            if not series_info:
                raise ValueError(f"Unknown rate type: {rate_type}")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_info['flow'], series_info['key'], recent_periods=recent_periods)
            
        elif action == 'get_bond_yield':
            bond_term = arguments.get('bond_term', '10y')
            indicator_key = f'bond_{bond_term}'
            series_info = self.common_series.get(indicator_key)
            
            if not series_info:
                raise ValueError(f"Unknown bond term: {bond_term}")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_info['flow'], series_info['key'], recent_periods=recent_periods)
            
        elif action == 'get_inflation':
            inflation_type = arguments.get('inflation_type', 'overall')
            indicator_key = f'hicp_{inflation_type}'
            series_info = self.common_series.get(indicator_key)
            
            if not series_info:
                raise ValueError(f"Unknown inflation type: {inflation_type}")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_info['flow'], series_info['key'], recent_periods=recent_periods)
            
        elif action == 'get_latest':
            flow = arguments.get('flow')
            key = arguments.get('key')
            indicator = arguments.get('indicator')
            
            if indicator and not (flow and key):
                series_info = self.common_series.get(indicator)
                if series_info:
                    flow = series_info['flow']
                    key = series_info['key']
            
            if not (flow and key):
                raise ValueError("Either 'flow' and 'key', or 'indicator' is required")
            
            return self._get_latest_observation(flow, key)
            
        elif action == 'search_series':
            return self._get_available_series()
            
        elif action == 'get_common_indicators':
            return self._get_common_indicators()
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_series(
        self,
        flow: str,
        key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: int = 10
    ) -> Dict:
        """
        Get time series data from ECB
        
        Args:
            flow: ECB data flow identifier
            key: Series key
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        # Build URL
        url = f"{self.api_url}/{flow}/{key}"
        
        # Add parameters
        params = {
            'format': 'jsondata',
            'detail': 'dataonly'
        }
        
        # Calculate date range if not using recent periods
        if start_date and end_date:
            params['startPeriod'] = start_date
            params['endPeriod'] = end_date
        elif not start_date and not end_date:
            # Get recent data by setting a start date
            days_back = recent_periods * 35  # Approximate for monthly data
            start = datetime.now() - timedelta(days=days_back)
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
                self.logger.error(f"ECB API error: {e}")
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except urllib.error.URLError as e:
            self.logger.error(f"ECB API connection error: {e}")
            raise ValueError(f"Failed to connect to ECB API: {str(e)}")
        except Exception as e:
            self.logger.error(f"ECB API error: {e}")
            raise ValueError(f"Failed to get series data: {str(e)}")
    
    def _get_latest_observation(self, flow: str, key: str) -> Dict:
        """
        Get latest observation for a series
        
        Args:
            flow: ECB data flow identifier
            key: Series key
            
        Returns:
            Latest observation
        """
        series_data = self._get_series(flow, key, recent_periods=1)
        
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
    
    def _get_series_description(self, flow: str, key: str) -> str:
        """Get description for a series by matching common series"""
        for indicator, info in self.common_series.items():
            if info['flow'] == flow and info['key'] == key:
                return info['description']
        return f"{flow} - {key}"
    
    def _get_available_series(self) -> Dict:
        """
        Get list of available common series
        
        Returns:
            Dictionary of available series
        """
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
            'total_series': len(self.common_series)
        }
    
    def _get_common_indicators(self) -> Dict:
        """
        Get common economic indicators with latest values
        
        Returns:
            Common indicators with latest values
        """
        indicators = {}
        
        # Define which indicators to fetch
        key_indicators = [
            'eur_usd', 'main_refinancing_rate', 'bond_10y', 
            'hicp_overall', 'unemployment_rate'
        ]
        
        for indicator in key_indicators:
            try:
                series_info = self.common_series[indicator]
                latest = self._get_latest_observation(
                    series_info['flow'], 
                    series_info['key']
                )
                indicators[indicator] = {
                    'flow': series_info['flow'],
                    'key': series_info['key'],
                    'description': series_info['description'],
                    'value': latest['value'],
                    'date': latest['date']
                }
            except Exception as e:
                self.logger.warning(f"Failed to get {indicator}: {e}")
                indicators[indicator] = {
                    'flow': self.common_series[indicator]['flow'],
                    'key': self.common_series[indicator]['key'],
                    'description': self.common_series[indicator]['description'],
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }
