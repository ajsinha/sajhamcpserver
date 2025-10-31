"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Bank of Canada (BoC) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools.base_mcp_tool import BaseMCPTool

class BankOfCanadaTool(BaseMCPTool):
    """
    Bank of Canada (BoC) Valet API tool for retrieving Canadian economic and financial data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Bank of Canada tool"""
        default_config = {
            'name': 'bank_of_canada',
            'description': 'Retrieve economic and financial data from Bank of Canada',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Bank of Canada Valet API endpoint
        self.api_url = "https://www.bankofcanada.ca/valet"
        
        # Common data series
        self.common_series = {
            # Exchange Rates
            'usd_cad': 'FXUSDCAD',  # US Dollar to Canadian Dollar
            'eur_cad': 'FXEURCAD',  # Euro to Canadian Dollar
            'gbp_cad': 'FXGBPCAD',  # British Pound to Canadian Dollar
            'jpy_cad': 'FXJPYCAD',  # Japanese Yen to Canadian Dollar
            'cny_cad': 'FXCNYCAD',  # Chinese Yuan to Canadian Dollar
            
            # Interest Rates
            'policy_rate': 'POLICY_RATE',  # Bank of Canada Policy Interest Rate
            'overnight_rate': 'CORRA',  # Canadian Overnight Repo Rate Average
            'prime_rate': 'V122530',  # Prime Business Rate
            
            # Bond Yields
            'bond_2y': 'V122531',  # 2-Year Government of Canada Bond Yield
            'bond_5y': 'V122533',  # 5-Year Government of Canada Bond Yield
            'bond_10y': 'V122539',  # 10-Year Government of Canada Bond Yield
            'bond_30y': 'V122546',  # 30-Year Government of Canada Bond Yield
            
            # Economic Indicators
            'cpi': 'V41690973',  # Consumer Price Index
            'core_cpi': 'V41690914',  # CPI Common
            'gdp': 'V65201210',  # Gross Domestic Product
            
            # Commodities
            'oil_price': 'CRUDE_OIL_PRICE',  # Crude Oil Price
        }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Bank of Canada tool"""
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
                        "search_series",
                        "get_latest",
                        "get_common_indicators"
                    ]
                },
                "series_name": {
                    "type": "string",
                    "description": "BoC series name (e.g., FXUSDCAD, POLICY_RATE)",
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator name",
                    "enum": list(self.common_series.keys())
                },
                "currency_pair": {
                    "type": "string",
                    "description": "Currency pair for exchange rates (e.g., USD/CAD)",
                },
                "rate_type": {
                    "type": "string",
                    "description": "Type of interest rate",
                    "enum": ["policy_rate", "overnight_rate", "prime_rate"]
                },
                "bond_term": {
                    "type": "string",
                    "description": "Bond term/maturity",
                    "enum": ["2y", "5y", "10y", "30y"]
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
        Execute Bank of Canada tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Economic/financial data from Bank of Canada
        """
        action = arguments.get('action')
        
        if action == 'get_series':
            series_name = arguments.get('series_name')
            indicator = arguments.get('indicator')
            
            # Convert indicator to series name if provided
            if indicator and not series_name:
                series_name = self.common_series.get(indicator)
            
            if not series_name:
                raise ValueError("Either 'series_name' or 'indicator' is required")
            
            start_date = arguments.get('start_date')
            end_date = arguments.get('end_date')
            recent_periods = arguments.get('recent_periods', 10)
            
            return self._get_series(series_name, start_date, end_date, recent_periods)
            
        elif action == 'get_exchange_rate':
            currency_pair = arguments.get('currency_pair')
            indicator = arguments.get('indicator')
            
            if indicator:
                series_name = self.common_series.get(indicator)
            elif currency_pair:
                # Convert currency pair to series name (e.g., USD/CAD -> FXUSDCAD)
                base = currency_pair.split('/')[0].upper() if '/' in currency_pair else currency_pair[:3].upper()
                series_name = f'FX{base}CAD'
            else:
                raise ValueError("Either 'currency_pair' or 'indicator' is required")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_name, recent_periods=recent_periods)
            
        elif action == 'get_interest_rate':
            rate_type = arguments.get('rate_type', 'policy_rate')
            series_name = self.common_series.get(rate_type)
            
            if not series_name:
                raise ValueError(f"Unknown rate type: {rate_type}")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_name, recent_periods=recent_periods)
            
        elif action == 'get_bond_yield':
            bond_term = arguments.get('bond_term', '10y')
            indicator_key = f'bond_{bond_term}'
            series_name = self.common_series.get(indicator_key)
            
            if not series_name:
                raise ValueError(f"Unknown bond term: {bond_term}")
            
            recent_periods = arguments.get('recent_periods', 10)
            return self._get_series(series_name, recent_periods=recent_periods)
            
        elif action == 'get_latest':
            series_name = arguments.get('series_name')
            indicator = arguments.get('indicator')
            
            if indicator and not series_name:
                series_name = self.common_series.get(indicator)
            
            if not series_name:
                raise ValueError("Either 'series_name' or 'indicator' is required")
            
            return self._get_latest_observation(series_name)
            
        elif action == 'search_series':
            # Note: BoC Valet API doesn't have built-in search, return common series
            return self._get_available_series()
            
        elif action == 'get_common_indicators':
            return self._get_common_indicators()
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_series(
        self,
        series_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: int = 10
    ) -> Dict:
        """
        Get time series data
        
        Args:
            series_name: BoC series name
            start_date: Start date
            end_date: End date
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        # Build URL
        url = f"{self.api_url}/observations/{series_name}/json"
        
        # Add date filters if provided
        params = {}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        if not start_date and not end_date:
            params['recent'] = recent_periods
        
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Parse response
                series_detail = data.get('seriesDetail', {}).get(series_name, {})
                observations = data.get('observations', [])
                
                # Format observations
                formatted_obs = []
                for obs in observations:
                    value = obs.get(series_name, {}).get('v')
                    formatted_obs.append({
                        'date': obs.get('d'),
                        'value': float(value) if value else None
                    })
                
                return {
                    'series_name': series_name,
                    'label': series_detail.get('label', series_name),
                    'description': series_detail.get('description', ''),
                    'dimension': series_detail.get('dimension', {}),
                    'observation_count': len(formatted_obs),
                    'observations': formatted_obs
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Series not found: {series_name}")
            else:
                self.logger.error(f"BoC API error: {e}")
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"BoC API error: {e}")
            raise ValueError(f"Failed to get series data: {str(e)}")
    
    def _get_latest_observation(self, series_name: str) -> Dict:
        """
        Get latest observation for a series
        
        Args:
            series_name: BoC series name
            
        Returns:
            Latest observation
        """
        series_data = self._get_series(series_name, recent_periods=1)
        
        if series_data['observations']:
            latest = series_data['observations'][-1]
            return {
                'series_name': series_name,
                'label': series_data['label'],
                'description': series_data['description'],
                'date': latest['date'],
                'value': latest['value']
            }
        else:
            raise ValueError(f"No data available for series: {series_name}")
    
    def _get_available_series(self) -> Dict:
        """
        Get list of available common series
        
        Returns:
            Dictionary of available series
        """
        series_info = {}
        
        categories = {
            'Exchange Rates': ['usd_cad', 'eur_cad', 'gbp_cad', 'jpy_cad', 'cny_cad'],
            'Interest Rates': ['policy_rate', 'overnight_rate', 'prime_rate'],
            'Bond Yields': ['bond_2y', 'bond_5y', 'bond_10y', 'bond_30y'],
            'Economic Indicators': ['cpi', 'core_cpi', 'gdp']
        }
        
        for category, indicators in categories.items():
            series_info[category] = []
            for indicator in indicators:
                series_info[category].append({
                    'indicator': indicator,
                    'series_name': self.common_series.get(indicator),
                    'description': self._get_indicator_description(indicator)
                })
        
        return {
            'categories': series_info,
            'total_series': len(self.common_series)
        }
    
    def _get_indicator_description(self, indicator: str) -> str:
        """Get description for an indicator"""
        descriptions = {
            'usd_cad': 'US Dollar to Canadian Dollar Exchange Rate',
            'eur_cad': 'Euro to Canadian Dollar Exchange Rate',
            'gbp_cad': 'British Pound to Canadian Dollar Exchange Rate',
            'jpy_cad': 'Japanese Yen to Canadian Dollar Exchange Rate',
            'cny_cad': 'Chinese Yuan to Canadian Dollar Exchange Rate',
            'policy_rate': 'Bank of Canada Policy Interest Rate',
            'overnight_rate': 'Canadian Overnight Repo Rate Average (CORRA)',
            'prime_rate': 'Prime Business Rate',
            'bond_2y': '2-Year Government of Canada Bond Yield',
            'bond_5y': '5-Year Government of Canada Bond Yield',
            'bond_10y': '10-Year Government of Canada Bond Yield',
            'bond_30y': '30-Year Government of Canada Bond Yield',
            'cpi': 'Consumer Price Index',
            'core_cpi': 'CPI Common (Core Inflation)',
            'gdp': 'Gross Domestic Product'
        }
        return descriptions.get(indicator, indicator)
    
    def _get_common_indicators(self) -> Dict:
        """
        Get common economic indicators with latest values
        
        Returns:
            Common indicators with latest values
        """
        indicators = {}
        
        # Define which indicators to fetch
        key_indicators = [
            'usd_cad', 'policy_rate', 'bond_10y', 'cpi'
        ]
        
        for indicator in key_indicators:
            try:
                series_name = self.common_series[indicator]
                latest = self._get_latest_observation(series_name)
                indicators[indicator] = {
                    'series_name': series_name,
                    'label': latest['label'],
                    'value': latest['value'],
                    'date': latest['date'],
                    'description': self._get_indicator_description(indicator)
                }
            except Exception as e:
                self.logger.warning(f"Failed to get {indicator}: {e}")
                indicators[indicator] = {
                    'series_name': self.common_series[indicator],
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }
