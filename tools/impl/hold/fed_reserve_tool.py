"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Federal Reserve Economic Data (FRED) MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List
from datetime import datetime, timedelta
from ..base_mcp_tool import BaseMCPTool

class FedReserveTool(BaseMCPTool):
    """
    Federal Reserve Economic Data (FRED) retrieval tool
    """
    
    def __init__(self, config: Dict = None):
        """Initialize Fed Reserve tool"""
        default_config = {
            'name': 'fed_reserve',
            'description': 'Retrieve economic data from Federal Reserve (FRED)',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
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
    
    def get_input_schema(self) -> Dict:
        """Get input schema for Fed Reserve tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["get_series", "search_series", "get_latest", "get_common_indicators"]
                },
                "series_id": {
                    "type": "string",
                    "description": "FRED series ID (e.g., GDP, UNRATE)"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common economic indicator name",
                    "enum": list(self.common_series.keys())
                },
                "query": {
                    "type": "string",
                    "description": "Search query for series"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD format)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD format)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of observations to return",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 1000
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute Fed Reserve tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Economic data from FRED
        """
        action = arguments.get('action')
        
        if action == 'get_series':
            series_id = arguments.get('series_id')
            indicator = arguments.get('indicator')
            
            # Convert indicator name to series ID if provided
            if indicator and not series_id:
                series_id = self.common_series.get(indicator)
            
            if not series_id:
                raise ValueError("Either 'series_id' or 'indicator' is required")
            
            start_date = arguments.get('start_date')
            end_date = arguments.get('end_date')
            limit = arguments.get('limit', 100)
            
            return self._get_series(series_id, start_date, end_date, limit)
            
        elif action == 'get_latest':
            series_id = arguments.get('series_id')
            indicator = arguments.get('indicator')
            
            # Convert indicator name to series ID if provided
            if indicator and not series_id:
                series_id = self.common_series.get(indicator)
            
            if not series_id:
                raise ValueError("Either 'series_id' or 'indicator' is required")
            
            return self._get_latest_observation(series_id)
            
        elif action == 'search_series':
            query = arguments.get('query')
            if not query:
                raise ValueError("'query' is required for search_series")
            
            return self._search_series(query)
            
        elif action == 'get_common_indicators':
            return self._get_common_indicators()
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_series(self, series_id: str, start_date: str = None, end_date: str = None, limit: int = 100) -> Dict:
        """
        Get time series data
        
        Args:
            series_id: FRED series ID
            start_date: Start date
            end_date: End date
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
    
    def _get_latest_observation(self, series_id: str) -> Dict:
        """
        Get latest observation for a series
        
        Args:
            series_id: FRED series ID
            
        Returns:
            Latest observation
        """
        # For demo mode, return mock data
        if self.api_key == 'demo':
            return self._get_demo_latest(series_id)
        
        # Get last 1 observation
        series_data = self._get_series(series_id, limit=1)
        
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
    
    def _search_series(self, query: str) -> Dict:
        """
        Search for FRED series
        
        Args:
            query: Search query
            
        Returns:
            Search results
        """
        # For demo mode, return mock results
        if self.api_key == 'demo':
            return self._get_demo_search(query)
        
        params = {
            'search_text': query,
            'api_key': self.api_key,
            'file_type': 'json',
            'limit': 20
        }
        
        url = f"{self.api_url}/series/search?{urllib.parse.urlencode(params)}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                series = data.get('seriess', [])
                
                # Format results
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
    
    def _get_common_indicators(self) -> Dict:
        """
        Get common economic indicators
        
        Returns:
            Common indicators with latest values
        """
        indicators = {}
        
        for name, series_id in self.common_series.items():
            try:
                latest = self._get_latest_observation(series_id)
                indicators[name] = {
                    'series_id': series_id,
                    'title': latest['title'],
                    'value': latest['value'],
                    'date': latest['date'],
                    'units': latest['units']
                }
            except Exception as e:
                self.logger.warning(f"Failed to get {name}: {e}")
                indicators[name] = {
                    'series_id': series_id,
                    'error': str(e)
                }
        
        return {
            'indicators': indicators,
            'last_updated': datetime.now().isoformat()
        }
    
    def _get_demo_series(self, series_id: str, start_date: str, end_date: str, limit: int) -> Dict:
        """Get demo series data"""
        # Generate some demo data
        observations = []
        base_value = 100.0
        
        for i in range(min(limit, 10)):
            date = (datetime.now() - timedelta(days=i*30)).strftime('%Y-%m-%d')
            value = base_value + (i * 0.5)  # Simple trend
            observations.append({
                'date': date,
                'value': round(value, 2)
            })
        
        observations.reverse()  # Chronological order
        
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
    
    def _get_demo_latest(self, series_id: str) -> Dict:
        """Get demo latest observation"""
        return {
            'series_id': series_id,
            'title': f'Demo Series: {series_id}',
            'units': 'Index',
            'frequency': 'Monthly',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'value': 105.5,
            'last_updated': datetime.now().isoformat(),
            'note': 'Demo mode - Configure API key for real FRED data'
        }
    
    def _get_demo_search(self, query: str) -> Dict:
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
            'count': len(demo_results),
            'results': demo_results,
            'note': 'Demo mode - Configure API key for real FRED search'
        }
