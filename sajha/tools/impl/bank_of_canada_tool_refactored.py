"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Bank of Canada (BoC) MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool


class BankOfCanadaBaseTool(BaseMCPTool):
    """
    Base class for Bank of Canada tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Bank of Canada base tool"""
        super().__init__(config)
        
        # Bank of Canada Valet API endpoint
        self.api_url = "https://www.bankofcanada.ca/valet"
        
        # Common data series mapping
        self.common_series = {
            # Exchange Rates
            'usd_cad': 'FXUSDCAD',
            'eur_cad': 'FXEURCAD',
            'gbp_cad': 'FXGBPCAD',
            'jpy_cad': 'FXJPYCAD',
            'cny_cad': 'FXCNYCAD',
            
            # Interest Rates
            'policy_rate': 'POLICY_RATE',
            'overnight_rate': 'CORRA',
            'prime_rate': 'V122530',
            
            # Bond Yields
            'bond_2y': 'V122531',
            'bond_5y': 'V122533',
            'bond_10y': 'V122539',
            'bond_30y': 'V122546',
            
            # Economic Indicators
            'cpi': 'V41690973',
            'core_cpi': 'V41690914',
            'gdp': 'V65201210',
        }
    
    def _fetch_series(
        self,
        series_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        recent_periods: Optional[int] = None
    ) -> Dict:
        """
        Fetch time series data from Bank of Canada API
        
        Args:
            series_name: BoC series name
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            recent_periods: Number of recent periods
            
        Returns:
            Time series data
        """
        url = f"{self.api_url}/observations/{series_name}/json"
        
        params = {}
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        if recent_periods and not start_date and not end_date:
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
                
                series_detail = data.get('seriesDetail', {}).get(series_name, {})
                observations = data.get('observations', [])
                
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
                raise ValueError(f"Failed to get series data: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to get series data: {str(e)}")


class BoCGetSeriesTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve time series data from Bank of Canada
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_series',
            'description': 'Retrieve time series economic data from Bank of Canada by series name or indicator',
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
                "series_name": {
                    "type": "string",
                    "description": "Bank of Canada series name (e.g., 'FXUSDCAD', 'POLICY_RATE'). Use this for direct series access."
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand name for convenience",
                    "enum": ["usd_cad", "eur_cad", "gbp_cad", "jpy_cad", "cny_cad", 
                            "policy_rate", "overnight_rate", "prime_rate",
                            "bond_2y", "bond_5y", "bond_10y", "bond_30y",
                            "cpi", "core_cpi", "gdp"]
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
                {"required": ["series_name"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for time series data"""
        return {
            "type": "object",
            "properties": {
                "series_name": {
                    "type": "string",
                    "description": "Bank of Canada series identifier"
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable label for the series"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the data series"
                },
                "dimension": {
                    "type": "object",
                    "description": "Dimensional metadata about the series (units, frequency, etc.)"
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
                                "description": "Observation date (YYYY-MM-DD)"
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
        series_name = arguments.get('series_name')
        indicator = arguments.get('indicator')
        
        # Convert indicator to series name if provided
        if indicator and not series_name:
            series_name = self.common_series.get(indicator)
            if not series_name:
                raise ValueError(f"Unknown indicator: {indicator}")
        
        if not series_name:
            raise ValueError("Either 'series_name' or 'indicator' is required")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(series_name, start_date, end_date, recent_periods)


class BoCGetExchangeRateTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve foreign exchange rates from Bank of Canada
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_exchange_rate',
            'description': 'Retrieve foreign exchange rates between Canadian Dollar and other currencies',
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
                    "description": "Currency pair in format 'XXX/CAD' (e.g., 'USD/CAD', 'EUR/CAD'). Always quotes in terms of CAD."
                },
                "indicator": {
                    "type": "string",
                    "description": "Pre-defined currency pair shorthand",
                    "enum": ["usd_cad", "eur_cad", "gbp_cad", "jpy_cad", "cny_cad"]
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
                "series_name": {
                    "type": "string",
                    "description": "Bank of Canada FX series identifier"
                },
                "label": {
                    "type": "string",
                    "description": "Exchange rate description"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed information about the exchange rate"
                },
                "dimension": {
                    "type": "object",
                    "description": "Currency units and frequency metadata"
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
                                "description": "Exchange rate value (CAD per unit of foreign currency)"
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
            series_name = self.common_series.get(indicator)
            if not series_name:
                raise ValueError(f"Unknown currency indicator: {indicator}")
        elif currency_pair:
            base = currency_pair.split('/')[0].upper() if '/' in currency_pair else currency_pair[:3].upper()
            series_name = f'FX{base}CAD'
        else:
            raise ValueError("Either 'currency_pair' or 'indicator' is required")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(series_name, start_date, end_date, recent_periods)


class BoCGetInterestRateTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve interest rates from Bank of Canada
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_interest_rate',
            'description': 'Retrieve Bank of Canada interest rates including policy rate, overnight rate, and prime rate',
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
                    "enum": ["policy_rate", "overnight_rate", "prime_rate"],
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
        """Get output schema for interest rate data"""
        return {
            "type": "object",
            "properties": {
                "series_name": {
                    "type": "string",
                    "description": "Interest rate series identifier"
                },
                "label": {
                    "type": "string",
                    "description": "Interest rate name"
                },
                "description": {
                    "type": "string",
                    "description": "Description of the interest rate"
                },
                "dimension": {
                    "type": "object",
                    "description": "Rate units and frequency (typically percentage, daily/monthly)"
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
        rate_type = arguments.get('rate_type', 'policy_rate')
        series_name = self.common_series.get(rate_type)
        
        if not series_name:
            raise ValueError(f"Unknown rate type: {rate_type}")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(series_name, start_date, end_date, recent_periods)


class BoCGetBondYieldTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve Government of Canada bond yields
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_bond_yield',
            'description': 'Retrieve Government of Canada benchmark bond yields for various maturities',
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
        """Get output schema for bond yield data"""
        return {
            "type": "object",
            "properties": {
                "series_name": {
                    "type": "string",
                    "description": "Bond yield series identifier"
                },
                "label": {
                    "type": "string",
                    "description": "Bond description"
                },
                "description": {
                    "type": "string",
                    "description": "Detailed bond information"
                },
                "dimension": {
                    "type": "object",
                    "description": "Yield units and frequency (percentage, daily)"
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
        bond_term = arguments.get('bond_term', '10y')
        indicator_key = f'bond_{bond_term}'
        series_name = self.common_series.get(indicator_key)
        
        if not series_name:
            raise ValueError(f"Unknown bond term: {bond_term}")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        recent_periods = arguments.get('recent_periods', 10)
        
        return self._fetch_series(series_name, start_date, end_date, recent_periods)


class BoCGetLatestTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve the latest observation for a specific series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_latest',
            'description': 'Retrieve the most recent observation for any Bank of Canada data series',
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
                "series_name": {
                    "type": "string",
                    "description": "Bank of Canada series name (e.g., 'FXUSDCAD', 'POLICY_RATE')"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand",
                    "enum": ["usd_cad", "eur_cad", "gbp_cad", "jpy_cad", "cny_cad",
                            "policy_rate", "overnight_rate", "prime_rate",
                            "bond_2y", "bond_5y", "bond_10y", "bond_30y",
                            "cpi", "core_cpi", "gdp"]
                }
            },
            "oneOf": [
                {"required": ["series_name"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for latest observation"""
        return {
            "type": "object",
            "properties": {
                "series_name": {
                    "type": "string",
                    "description": "Series identifier"
                },
                "label": {
                    "type": "string",
                    "description": "Series label"
                },
                "description": {
                    "type": "string",
                    "description": "Series description"
                },
                "date": {
                    "type": "string",
                    "description": "Date of the latest observation (YYYY-MM-DD)"
                },
                "value": {
                    "type": ["number", "null"],
                    "description": "Latest observation value"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get latest operation"""
        series_name = arguments.get('series_name')
        indicator = arguments.get('indicator')
        
        if indicator and not series_name:
            series_name = self.common_series.get(indicator)
            if not series_name:
                raise ValueError(f"Unknown indicator: {indicator}")
        
        if not series_name:
            raise ValueError("Either 'series_name' or 'indicator' is required")
        
        # Fetch the most recent observation
        series_data = self._fetch_series(series_name, recent_periods=1)
        
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


class BoCSearchSeriesTool(BankOfCanadaBaseTool):
    """
    Tool to search and discover available Bank of Canada data series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_search_series',
            'description': 'Search and discover available Bank of Canada economic data series by category',
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
                    "enum": ["Exchange Rates", "Interest Rates", "Bond Yields", "Economic Indicators", "all"]
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
                                "series_name": {
                                    "type": "string",
                                    "description": "Official BoC series identifier"
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
            'Exchange Rates': ['usd_cad', 'eur_cad', 'gbp_cad', 'jpy_cad', 'cny_cad'],
            'Interest Rates': ['policy_rate', 'overnight_rate', 'prime_rate'],
            'Bond Yields': ['bond_2y', 'bond_5y', 'bond_10y', 'bond_30y'],
            'Economic Indicators': ['cpi', 'core_cpi', 'gdp']
        }
        
        # Filter categories if requested
        if category_filter != 'all' and category_filter in categories:
            categories = {category_filter: categories[category_filter]}
        
        # Build series info
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
            'total_series': sum(len(v) for v in series_info.values())
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


class BoCGetCommonIndicatorsTool(BankOfCanadaBaseTool):
    """
    Tool to retrieve multiple common economic indicators with their latest values
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'boc_get_common_indicators',
            'description': 'Retrieve a dashboard of key Canadian economic indicators with their latest values',
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
                        "enum": ["usd_cad", "eur_cad", "policy_rate", "overnight_rate",
                                "bond_2y", "bond_5y", "bond_10y", "bond_30y",
                                "cpi", "core_cpi", "gdp"]
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
                            "series_name": {
                                "type": "string",
                                "description": "BoC series identifier"
                            },
                            "label": {
                                "type": "string",
                                "description": "Indicator name"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Latest value"
                            },
                            "date": {
                                "type": "string",
                                "description": "Date of latest value"
                            },
                            "description": {
                                "type": "string",
                                "description": "Indicator description"
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
            'usd_cad', 'policy_rate', 'bond_10y', 'cpi'
        ])
        
        indicators = {}
        
        for indicator in requested_indicators:
            try:
                series_name = self.common_series.get(indicator)
                if not series_name:
                    indicators[indicator] = {
                        'error': f'Unknown indicator: {indicator}'
                    }
                    continue
                
                # Fetch latest observation
                series_data = self._fetch_series(series_name, recent_periods=1)
                
                if series_data['observations']:
                    latest = series_data['observations'][-1]
                    indicators[indicator] = {
                        'series_name': series_name,
                        'label': series_data['label'],
                        'value': latest['value'],
                        'date': latest['date'],
                        'description': self._get_indicator_description(indicator)
                    }
                else:
                    indicators[indicator] = {
                        'series_name': series_name,
                        'error': 'No data available'
                    }
                    
            except Exception as e:
                self.logger.warning(f"Failed to get {indicator}: {e}")
                indicators[indicator] = {
                    'series_name': self.common_series.get(indicator),
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }
    
    def _get_indicator_description(self, indicator: str) -> str:
        """Get description for an indicator"""
        descriptions = {
            'usd_cad': 'US Dollar to Canadian Dollar Exchange Rate',
            'eur_cad': 'Euro to Canadian Dollar Exchange Rate',
            'policy_rate': 'Bank of Canada Policy Interest Rate',
            'overnight_rate': 'Canadian Overnight Repo Rate Average (CORRA)',
            'bond_2y': '2-Year Government of Canada Bond Yield',
            'bond_5y': '5-Year Government of Canada Bond Yield',
            'bond_10y': '10-Year Government of Canada Bond Yield',
            'bond_30y': '30-Year Government of Canada Bond Yield',
            'cpi': 'Consumer Price Index',
            'core_cpi': 'CPI Common (Core Inflation)',
            'gdp': 'Gross Domestic Product'
        }
        return descriptions.get(indicator, indicator)


# Tool registry for easy access
BANK_OF_CANADA_TOOLS = {
    'boc_get_series': BoCGetSeriesTool,
    'boc_get_exchange_rate': BoCGetExchangeRateTool,
    'boc_get_interest_rate': BoCGetInterestRateTool,
    'boc_get_bond_yield': BoCGetBondYieldTool,
    'boc_get_latest': BoCGetLatestTool,
    'boc_search_series': BoCSearchSeriesTool,
    'boc_get_common_indicators': BoCGetCommonIndicatorsTool
}
