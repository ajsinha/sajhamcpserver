"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Federal Reserve Economic Data (FRED) MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool


class FedReserveBaseTool(BaseMCPTool):
    """
    Base class for Federal Reserve tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Federal Reserve base tool"""
        super().__init__(config)
        
        # FRED API endpoint
        self.api_url = "https://api.stlouisfed.org/fred"
        
        # API key (optional for basic usage)
        self.api_key = config.get('api_key', 'demo') if config else 'demo'
        
        # Common economic indicators
        self.common_series = {
            'gdp': 'GDP',  # Gross Domestic Product
            'unemployment': 'UNRATE',  # Unemployment Rate
            'inflation': 'CPIAUCSL',  # Consumer Price Index
            'fed_rate': 'DFF',  # Federal Funds Rate
            'treasury_10y': 'DGS10',  # 10-Year Treasury Rate
            'treasury_2y': 'DGS2',  # 2-Year Treasury Rate
            'sp500': 'SP500',  # S&P 500 Index
            'housing': 'HOUST',  # Housing Starts
            'retail': 'RSXFS',  # Retail Sales
            'industrial': 'INDPRO',  # Industrial Production Index
            'm2': 'M2SL',  # M2 Money Supply
            'pce': 'PCEPI'  # Personal Consumption Expenditures Price Index
        }
    
    def _get_series_data(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict:
        """
        Get time series data from FRED
        
        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            limit: Number of observations
            
        Returns:
            Time series data
        """
        # For demo mode, return mock data
        if self.api_key == 'demo':
            return self._get_demo_series(series_id, start_date, end_date, limit)
        
        params = {
            'series_id': series_id,
            'api_key': self.api_key,
            'file_type': 'json',
            'limit': limit
        }
        
        if start_date:
            params['observation_start'] = start_date
        if end_date:
            params['observation_end'] = end_date
        
        url = f"{self.api_url}/series/observations?{urllib.parse.urlencode(params)}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                observations = data.get('observations', [])
                
                # Format observations
                formatted_obs = []
                for obs in observations:
                    formatted_obs.append({
                        'date': obs.get('date'),
                        'value': float(obs.get('value')) if obs.get('value') != '.' else None
                    })
                
                # Get series info
                info_url = f"{self.api_url}/series?series_id={series_id}&api_key={self.api_key}&file_type=json"
                with urllib.request.urlopen(info_url) as info_response:
                    info_data = json.loads(info_response.read().decode('utf-8'))
                    series_info = info_data.get('seriess', [{}])[0]
                
                return {
                    'series_id': series_id,
                    'title': series_info.get('title', series_id),
                    'units': series_info.get('units', ''),
                    'frequency': series_info.get('frequency', ''),
                    'last_updated': series_info.get('last_updated', ''),
                    'observation_count': len(formatted_obs),
                    'observations': formatted_obs
                }
                
        except Exception as e:
            self.logger.error(f"FRED API error: {e}")
            raise ValueError(f"Failed to get series data: {str(e)}")
    
    def _get_demo_series(self, series_id: str, start_date: str, end_date: str, limit: int) -> Dict:
        """Get demo series data"""
        observations = []
        base_value = 100.0
        
        for i in range(min(limit, 10)):
            date = (datetime.now() - timedelta(days=i*30)).strftime('%Y-%m-%d')
            value = base_value + (i * 0.5)
            observations.append({
                'date': date,
                'value': round(value, 2)
            })
        
        observations.reverse()
        
        return {
            'series_id': series_id,
            'title': f'Demo Series: {series_id}',
            'units': 'Index',
            'frequency': 'Monthly',
            'last_updated': datetime.now().isoformat(),
            'observation_count': len(observations),
            'observations': observations,
            'note': 'Demo mode - Configure API key for real FRED data'
        }


class FedGetSeriesTool(FedReserveBaseTool):
    """
    Tool to retrieve time series data from FRED
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fed_get_series',
            'description': 'Retrieve time series economic data from Federal Reserve FRED database',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "FRED series ID (e.g., 'GDP', 'UNRATE', 'DGS10'). Use this for direct series access."
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand name for convenience",
                    "enum": list(self.common_series.keys())
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of observations to return",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 1000
                }
            },
            "oneOf": [
                {"required": ["series_id"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "FRED series identifier"
                },
                "title": {
                    "type": "string",
                    "description": "Series title/name"
                },
                "units": {
                    "type": "string",
                    "description": "Units of measurement"
                },
                "frequency": {
                    "type": "string",
                    "description": "Data frequency (Daily, Monthly, Quarterly, Annual)"
                },
                "last_updated": {
                    "type": "string",
                    "description": "When the series was last updated"
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
        series_id = arguments.get('series_id')
        indicator = arguments.get('indicator')
        
        # Convert indicator to series_id if provided
        if indicator and not series_id:
            series_id = self.common_series.get(indicator)
        
        if not series_id:
            raise ValueError("Either 'series_id' or 'indicator' is required")
        
        start_date = arguments.get('start_date')
        end_date = arguments.get('end_date')
        limit = arguments.get('limit', 100)
        
        return self._get_series_data(series_id, start_date, end_date, limit)


class FedGetLatestTool(FedReserveBaseTool):
    """
    Tool to retrieve the latest observation for a FRED series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fed_get_latest',
            'description': 'Retrieve the most recent observation for a FRED economic data series',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "FRED series ID (e.g., 'GDP', 'UNRATE')"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator shorthand name",
                    "enum": list(self.common_series.keys())
                }
            },
            "oneOf": [
                {"required": ["series_id"]},
                {"required": ["indicator"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "FRED series identifier"
                },
                "title": {
                    "type": "string",
                    "description": "Series title"
                },
                "units": {
                    "type": "string",
                    "description": "Units of measurement"
                },
                "frequency": {
                    "type": "string",
                    "description": "Data frequency"
                },
                "date": {
                    "type": "string",
                    "description": "Date of latest observation"
                },
                "value": {
                    "type": ["number", "null"],
                    "description": "Latest observation value"
                },
                "last_updated": {
                    "type": "string",
                    "description": "When the series was last updated"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get latest operation"""
        series_id = arguments.get('series_id')
        indicator = arguments.get('indicator')
        
        # Convert indicator to series_id if provided
        if indicator and not series_id:
            series_id = self.common_series.get(indicator)
        
        if not series_id:
            raise ValueError("Either 'series_id' or 'indicator' is required")
        
        # Get last observation
        series_data = self._get_series_data(series_id, limit=1)
        
        if series_data['observations']:
            latest = series_data['observations'][-1]
            return {
                'series_id': series_id,
                'title': series_data['title'],
                'units': series_data['units'],
                'frequency': series_data['frequency'],
                'date': latest['date'],
                'value': latest['value'],
                'last_updated': series_data['last_updated']
            }
        else:
            raise ValueError(f"No data available for series: {series_id}")


class FedSearchSeriesTool(FedReserveBaseTool):
    """
    Tool to search for FRED data series
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fed_search_series',
            'description': 'Search for economic data series in the FRED database',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'unemployment rate', 'GDP', 'treasury yield')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query used"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results returned"
                },
                "results": {
                    "type": "array",
                    "description": "Search results",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Series ID"
                            },
                            "title": {
                                "type": "string",
                                "description": "Series title"
                            },
                            "units": {
                                "type": "string",
                                "description": "Units of measurement"
                            },
                            "frequency": {
                                "type": "string",
                                "description": "Data frequency"
                            },
                            "popularity": {
                                "type": "integer",
                                "description": "Popularity score"
                            },
                            "observation_start": {
                                "type": "string",
                                "description": "First observation date"
                            },
                            "observation_end": {
                                "type": "string",
                                "description": "Last observation date"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the search series operation"""
        query = arguments.get('query')
        if not query:
            raise ValueError("'query' is required")
        
        limit = arguments.get('limit', 20)
        
        # Demo mode
        if self.api_key == 'demo':
            return self._get_demo_search(query, limit)
        
        params = {
            'search_text': query,
            'api_key': self.api_key,
            'file_type': 'json',
            'limit': limit
        }
        
        url = f"{self.api_url}/series/search?{urllib.parse.urlencode(params)}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                series = data.get('seriess', [])
                
                results = []
                for s in series:
                    results.append({
                        'id': s.get('id'),
                        'title': s.get('title'),
                        'units': s.get('units'),
                        'frequency': s.get('frequency'),
                        'popularity': s.get('popularity', 0),
                        'observation_start': s.get('observation_start'),
                        'observation_end': s.get('observation_end')
                    })
                
                return {
                    'query': query,
                    'count': len(results),
                    'results': results
                }
                
        except Exception as e:
            self.logger.error(f"FRED search error: {e}")
            raise ValueError(f"Search failed: {str(e)}")
    
    def _get_demo_search(self, query: str, limit: int) -> Dict:
        """Get demo search results"""
        demo_results = [
            {
                'id': 'GDP',
                'title': 'Gross Domestic Product',
                'units': 'Billions of Dollars',
                'frequency': 'Quarterly',
                'popularity': 100,
                'observation_start': '1947-01-01',
                'observation_end': '2025-07-01'
            },
            {
                'id': 'UNRATE',
                'title': 'Unemployment Rate',
                'units': 'Percent',
                'frequency': 'Monthly',
                'popularity': 95,
                'observation_start': '1948-01-01',
                'observation_end': '2025-09-01'
            }
        ]
        
        return {
            'query': query,
            'count': len(demo_results[:limit]),
            'results': demo_results[:limit],
            'note': 'Demo mode - Configure API key for real FRED search'
        }


class FedGetCommonIndicatorsTool(FedReserveBaseTool):
    """
    Tool to retrieve multiple common economic indicators with their latest values
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fed_get_common_indicators',
            'description': 'Retrieve a dashboard of key US economic indicators with their latest values',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return {
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "array",
                    "description": "Specific indicators to retrieve (optional, defaults to key indicators)",
                    "items": {
                        "type": "string",
                        "enum": list(self.common_series.keys())
                    }
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "object",
                    "description": "Key economic indicators with latest values",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "series_id": {
                                "type": "string"
                            },
                            "title": {
                                "type": "string"
                            },
                            "value": {
                                "type": ["number", "null"]
                            },
                            "date": {
                                "type": "string"
                            },
                            "units": {
                                "type": "string"
                            },
                            "error": {
                                "type": "string"
                            }
                        }
                    }
                },
                "last_updated": {
                    "type": "string",
                    "description": "Timestamp when this data was retrieved"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute the get common indicators operation"""
        requested_indicators = arguments.get('indicators', list(self.common_series.keys()))
        
        indicators = {}
        
        for indicator in requested_indicators:
            series_id = self.common_series.get(indicator)
            if not series_id:
                indicators[indicator] = {'error': f'Unknown indicator: {indicator}'}
                continue
            
            try:
                series_data = self._get_series_data(series_id, limit=1)
                
                if series_data['observations']:
                    latest = series_data['observations'][-1]
                    indicators[indicator] = {
                        'series_id': series_id,
                        'title': series_data['title'],
                        'value': latest['value'],
                        'date': latest['date'],
                        'units': series_data['units']
                    }
                else:
                    indicators[indicator] = {
                        'series_id': series_id,
                        'error': 'No data available'
                    }
                    
            except Exception as e:
                self.logger.warning(f"Failed to get {indicator}: {e}")
                indicators[indicator] = {
                    'series_id': series_id,
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }


# Tool registry
FED_RESERVE_TOOLS = {
    'fed_get_series': FedGetSeriesTool,
    'fed_get_latest': FedGetLatestTool,
    'fed_search_series': FedSearchSeriesTool,
    'fed_get_common_indicators': FedGetCommonIndicatorsTool
}
