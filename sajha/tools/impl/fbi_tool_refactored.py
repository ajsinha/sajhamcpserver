"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
FBI Crime Data Explorer MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool


class FBIBaseTool(BaseMCPTool):
    """
    Base class for FBI tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize FBI base tool"""
        super().__init__(config)
        
        # FBI Crime Data Explorer API endpoint
        self.api_url = "https://api.usa.gov/crime/fbi/cde"
        
        # Offense type mapping to API codes
        self.offense_codes = {
            'violent_crime': 'violent-crime',
            'homicide': 'homicide',
            'rape': 'rape',
            'robbery': 'robbery',
            'aggravated_assault': 'aggravated-assault',
            'property_crime': 'property-crime',
            'burglary': 'burglary',
            'larceny': 'larceny',
            'motor_vehicle_theft': 'motor-vehicle-theft',
            'arson': 'arson'
        }
        
        # State name mapping
        self.state_names = {
            'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
            'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
            'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
            'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
            'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
            'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
            'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
            'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
            'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
            'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
            'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
            'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
            'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
        }
    
    def _make_api_request(self, endpoint: str, params: Dict = None) -> Dict:
        """
        Make API request to FBI Crime Data Explorer
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            API response data
        """
        url = f"{self.api_url}/{endpoint}"
        
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                return data
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Data not found: {endpoint}")
            else:
                raise ValueError(f"API request failed: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"API request failed: {str(e)}")
    
    def _calculate_per_capita(self, incidents: int, population: int) -> float:
        """Calculate per capita rate per 100,000 population"""
        if population == 0:
            return 0.0
        return round((incidents / population) * 100000, 2)
    
    def _get_current_year(self) -> int:
        """Get current year, defaulting to most recent FBI data year"""
        return min(datetime.now().year - 1, 2024)


class FBIGetNationalStatisticsTool(FBIBaseTool):
    """
    Tool to retrieve nationwide US crime statistics
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_national_statistics',
            'description': 'Retrieve nationwide US crime statistics for specified offense types and years',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema"""
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute national statistics retrieval"""
        offense_type = arguments['offense_type']
        year = arguments.get('year', self._get_current_year())
        per_capita = arguments.get('per_capita', False)
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            # Mock implementation - in production, would call real FBI API
            data = self._make_api_request(
                f'statistics/national/{offense_code}',
                {'year': year}
            )
            
            # Extract and format results
            total_incidents = data.get('total_incidents', 0)
            population = data.get('population', 331000000)
            
            result = {
                'offense_type': offense_type,
                'year': year,
                'national_data': {
                    'total_incidents': total_incidents,
                    'rate_per_100k': self._calculate_per_capita(total_incidents, population),
                    'population': population,
                    'reporting_agencies': data.get('reporting_agencies', 0),
                    'population_covered': data.get('population_covered', 0)
                },
                'metadata': {
                    'data_source': 'FBI UCR',
                    'last_updated': datetime.now().isoformat()
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get national statistics: {e}")
            raise


class FBIGetStateStatisticsTool(FBIBaseTool):
    """
    Tool to retrieve state-level crime statistics
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_state_statistics',
            'description': 'Retrieve crime statistics for a specific US state',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute state statistics retrieval"""
        state = arguments['state'].upper()
        offense_type = arguments['offense_type']
        year = arguments.get('year', self._get_current_year())
        per_capita = arguments.get('per_capita', False)
        
        if state not in self.state_names:
            raise ValueError(f"Invalid state code: {state}")
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            # Get state data
            state_data = self._make_api_request(
                f'statistics/state/{state}/{offense_code}',
                {'year': year}
            )
            
            # Get national data for comparison
            national_data = self._make_api_request(
                f'statistics/national/{offense_code}',
                {'year': year}
            )
            
            state_incidents = state_data.get('total_incidents', 0)
            state_population = state_data.get('population', 0)
            national_rate = national_data.get('rate_per_100k', 0)
            
            result = {
                'state': state,
                'state_name': self.state_names[state],
                'offense_type': offense_type,
                'year': year,
                'state_data': {
                    'total_incidents': state_incidents,
                    'rate_per_100k': self._calculate_per_capita(state_incidents, state_population),
                    'state_population': state_population,
                    'reporting_agencies': state_data.get('reporting_agencies', 0),
                    'national_rank': state_data.get('rank', 0)
                },
                'comparison': {
                    'national_rate': national_rate,
                    'percent_of_national': round(
                        (self._calculate_per_capita(state_incidents, state_population) / national_rate * 100)
                        if national_rate > 0 else 0, 2
                    )
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get state statistics: {e}")
            raise


class FBIGetAgencyStatisticsTool(FBIBaseTool):
    """
    Tool to retrieve agency-level crime statistics
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_agency_statistics',
            'description': 'Retrieve crime statistics for a specific law enforcement agency',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute agency statistics retrieval"""
        ori = arguments['ori'].upper()
        offense_type = arguments['offense_type']
        year = arguments.get('year', self._get_current_year())
        per_capita = arguments.get('per_capita', False)
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            # Get agency details
            agency_info = self._make_api_request(f'agencies/{ori}')
            
            # Get agency crime data
            agency_data = self._make_api_request(
                f'statistics/agency/{ori}/{offense_code}',
                {'year': year}
            )
            
            # Get comparison data
            state = ori[:2]
            state_data = self._make_api_request(
                f'statistics/state/{state}/{offense_code}',
                {'year': year}
            )
            
            national_data = self._make_api_request(
                f'statistics/national/{offense_code}',
                {'year': year}
            )
            
            agency_incidents = agency_data.get('total_incidents', 0)
            jurisdiction_pop = agency_info.get('population', 0)
            
            result = {
                'ori': ori,
                'agency_name': agency_info.get('agency_name', 'Unknown'),
                'agency_type': agency_info.get('agency_type', 'Unknown'),
                'state': state,
                'offense_type': offense_type,
                'year': year,
                'agency_data': {
                    'total_incidents': agency_incidents,
                    'rate_per_100k': self._calculate_per_capita(agency_incidents, jurisdiction_pop),
                    'jurisdiction_population': jurisdiction_pop,
                    'months_reported': agency_data.get('months_reported', 12)
                },
                'comparison': {
                    'state_rate': state_data.get('rate_per_100k', 0),
                    'national_rate': national_data.get('rate_per_100k', 0)
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get agency statistics: {e}")
            raise


class FBISearchAgenciesTool(FBIBaseTool):
    """
    Tool to search for law enforcement agencies
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_search_agencies',
            'description': 'Search for law enforcement agencies by name or location',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute agency search"""
        agency_name = arguments['agency_name']
        state = arguments.get('state', '').upper()
        agency_type = arguments.get('agency_type', 'all')
        limit = arguments.get('limit', 20)
        
        try:
            params = {
                'name': agency_name,
                'limit': limit
            }
            
            if state:
                params['state'] = state
            
            if agency_type != 'all':
                params['type'] = agency_type
            
            search_results = self._make_api_request('agencies/search', params)
            
            agencies = []
            for agency in search_results.get('results', [])[:limit]:
                agencies.append({
                    'ori': agency.get('ori'),
                    'agency_name': agency.get('agency_name'),
                    'agency_type': agency.get('agency_type'),
                    'state': agency.get('state'),
                    'state_name': self.state_names.get(agency.get('state', ''), ''),
                    'city': agency.get('city'),
                    'county': agency.get('county'),
                    'population': agency.get('population', 0)
                })
            
            result = {
                'search_query': agency_name,
                'total_results': len(agencies),
                'agencies': agencies
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to search agencies: {e}")
            raise


class FBIGetOffenseDataTool(FBIBaseTool):
    """
    Tool to retrieve detailed offense breakdown data
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_offense_data',
            'description': 'Retrieve detailed offense breakdown and subcategories',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute offense data retrieval"""
        offense_type = arguments['offense_type']
        state = arguments.get('state', '').upper()
        year = arguments.get('year', self._get_current_year())
        include_subcategories = arguments.get('include_subcategories', True)
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            endpoint = f'statistics/{"state/" + state if state else "national"}/offense-details/{offense_code}'
            
            offense_data = self._make_api_request(endpoint, {'year': year})
            
            scope = 'state' if state else 'national'
            
            result = {
                'offense_type': offense_type,
                'year': year,
                'scope': scope,
                'total_offenses': offense_data.get('total_offenses', 0)
            }
            
            if state:
                result['state'] = state
            
            if include_subcategories and 'subcategories' in offense_data:
                result['subcategories'] = offense_data['subcategories']
            
            if 'demographics' in offense_data:
                result['demographics'] = offense_data['demographics']
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get offense data: {e}")
            raise


class FBIGetParticipationRateTool(FBIBaseTool):
    """
    Tool to retrieve participation rates for crime reporting
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_participation_rate',
            'description': 'Retrieve participation rates showing agency reporting coverage',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute participation rate retrieval"""
        state = arguments.get('state', '').upper()
        year = arguments.get('year', self._get_current_year())
        
        try:
            scope = 'state' if state else 'national'
            endpoint = f'participation/{"state/" + state if state else "national"}'
            
            participation_data = self._make_api_request(endpoint, {'year': year})
            
            result = {
                'scope': scope,
                'year': year,
                'participation_data': {
                    'total_agencies': participation_data.get('total_agencies', 0),
                    'reporting_agencies': participation_data.get('reporting_agencies', 0),
                    'participation_rate': participation_data.get('participation_rate', 0),
                    'population_covered': participation_data.get('population_covered', 0),
                    'total_population': participation_data.get('total_population', 0),
                    'population_coverage_rate': participation_data.get('population_coverage_rate', 0)
                },
                'reporting_quality': {
                    'full_year_reporters': participation_data.get('full_year_reporters', 0),
                    'partial_year_reporters': participation_data.get('partial_year_reporters', 0),
                    'zero_reporters': participation_data.get('zero_reporters', 0)
                }
            }
            
            if state:
                result['state'] = state
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get participation rate: {e}")
            raise


class FBIGetAgencyDetailsTool(FBIBaseTool):
    """
    Tool to retrieve detailed information about a law enforcement agency
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_agency_details',
            'description': 'Retrieve detailed information about a specific law enforcement agency',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute agency details retrieval"""
        ori = arguments['ori'].upper()
        
        try:
            agency_data = self._make_api_request(f'agencies/{ori}')
            
            state = ori[:2]
            
            result = {
                'ori': ori,
                'agency_name': agency_data.get('agency_name', 'Unknown'),
                'agency_type': agency_data.get('agency_type', 'Unknown'),
                'location': {
                    'state': state,
                    'state_name': self.state_names.get(state, ''),
                    'city': agency_data.get('city', ''),
                    'county': agency_data.get('county', ''),
                    'region': agency_data.get('region', '')
                },
                'jurisdiction': {
                    'population': agency_data.get('population', 0),
                    'square_miles': agency_data.get('square_miles', 0)
                },
                'personnel': {
                    'total_officers': agency_data.get('total_officers', 0),
                    'total_civilians': agency_data.get('total_civilians', 0),
                    'officers_per_1000': round(
                        agency_data.get('total_officers', 0) / (agency_data.get('population', 1) / 1000),
                        2
                    ) if agency_data.get('population', 0) > 0 else 0
                },
                'reporting_status': {
                    'participates_in_ucr': agency_data.get('ucr_participant', False),
                    'participates_in_nibrs': agency_data.get('nibrs_participant', False),
                    'last_reported_year': agency_data.get('last_reported_year', 0)
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get agency details: {e}")
            raise


class FBIGetCrimeTrendTool(FBIBaseTool):
    """
    Tool to analyze crime trends over time
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_get_crime_trend',
            'description': 'Analyze crime trends over time for specified jurisdictions',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute crime trend analysis"""
        offense_type = arguments['offense_type']
        start_year = arguments['start_year']
        end_year = arguments['end_year']
        state = arguments.get('state', '').upper()
        ori = arguments.get('ori', '').upper()
        per_capita = arguments.get('per_capita', True)
        
        if start_year > end_year:
            raise ValueError("start_year must be less than or equal to end_year")
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            # Determine scope
            if ori:
                scope = 'agency'
                endpoint_base = f'statistics/agency/{ori}'
            elif state:
                scope = 'state'
                endpoint_base = f'statistics/state/{state}'
            else:
                scope = 'national'
                endpoint_base = 'statistics/national'
            
            # Collect time series data
            time_series = []
            for year in range(start_year, end_year + 1):
                try:
                    year_data = self._make_api_request(
                        f'{endpoint_base}/{offense_code}',
                        {'year': year}
                    )
                    
                    incidents = year_data.get('total_incidents', 0)
                    population = year_data.get('population', 0)
                    rate = self._calculate_per_capita(incidents, population) if per_capita else incidents
                    
                    # Calculate percent change from previous year
                    percent_change = 0
                    if len(time_series) > 0:
                        prev_rate = time_series[-1]['rate_per_100k']
                        if prev_rate > 0:
                            percent_change = round(((rate - prev_rate) / prev_rate) * 100, 2)
                    
                    time_series.append({
                        'year': year,
                        'total_incidents': incidents,
                        'rate_per_100k': rate,
                        'percent_change': percent_change
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get data for year {year}: {e}")
                    continue
            
            if not time_series:
                raise ValueError("No data available for the specified time period")
            
            # Calculate trend analysis
            first_rate = time_series[0]['rate_per_100k']
            last_rate = time_series[-1]['rate_per_100k']
            overall_change = round(((last_rate - first_rate) / first_rate) * 100, 2) if first_rate > 0 else 0
            
            rates = [item['rate_per_100k'] for item in time_series]
            peak_year = time_series[rates.index(max(rates))]['year']
            lowest_year = time_series[rates.index(min(rates))]['year']
            
            # Determine direction
            if overall_change > 5:
                direction = 'increasing'
            elif overall_change < -5:
                direction = 'decreasing'
            else:
                direction = 'stable'
            
            # Calculate volatility
            changes = [abs(item['percent_change']) for item in time_series[1:]]
            avg_change = sum(changes) / len(changes) if changes else 0
            volatility = 'high' if avg_change > 10 else 'medium' if avg_change > 5 else 'low'
            
            result = {
                'offense_type': offense_type,
                'scope': scope,
                'time_period': {
                    'start_year': start_year,
                    'end_year': end_year,
                    'years_analyzed': len(time_series)
                },
                'time_series': time_series,
                'trend_analysis': {
                    'overall_change': overall_change,
                    'average_annual_change': round(overall_change / len(time_series), 2) if len(time_series) > 0 else 0,
                    'direction': direction,
                    'peak_year': peak_year,
                    'lowest_year': lowest_year,
                    'volatility': volatility
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to analyze crime trend: {e}")
            raise


class FBICompareStatesTool(FBIBaseTool):
    """
    Tool to compare crime statistics across multiple states
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'fbi_compare_states',
            'description': 'Compare crime statistics across multiple US states',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})
    
    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute state comparison"""
        states = [s.upper() for s in arguments['states']]
        offense_type = arguments['offense_type']
        year = arguments.get('year', self._get_current_year())
        per_capita = arguments.get('per_capita', True)
        include_national = arguments.get('include_national_average', True)
        
        # Validate states
        for state in states:
            if state not in self.state_names:
                raise ValueError(f"Invalid state code: {state}")
        
        offense_code = self.offense_codes.get(offense_type)
        
        try:
            # Get national data if requested
            national_data = None
            if include_national:
                national_data = self._make_api_request(
                    f'statistics/national/{offense_code}',
                    {'year': year}
                )
            
            # Collect state data
            states_data = []
            for state in states:
                try:
                    state_data = self._make_api_request(
                        f'statistics/state/{state}/{offense_code}',
                        {'year': year}
                    )
                    
                    incidents = state_data.get('total_incidents', 0)
                    population = state_data.get('population', 0)
                    rate = self._calculate_per_capita(incidents, population)
                    
                    states_data.append({
                        'state': state,
                        'state_name': self.state_names[state],
                        'total_incidents': incidents,
                        'rate_per_100k': rate,
                        'state_population': population,
                        'percent_of_national': round(
                            (rate / national_data.get('rate_per_100k', 1)) * 100, 2
                        ) if national_data and national_data.get('rate_per_100k', 0) > 0 else 0
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get data for state {state}: {e}")
                    continue
            
            if not states_data:
                raise ValueError("No data available for any of the specified states")
            
            # Sort by rate and add ranks
            states_data.sort(key=lambda x: x['rate_per_100k'], reverse=True)
            for idx, state_info in enumerate(states_data, 1):
                state_info['rank'] = idx
            
            # Calculate summary
            rates = [s['rate_per_100k'] for s in states_data]
            
            result = {
                'offense_type': offense_type,
                'year': year,
                'comparison_type': 'per_capita' if per_capita else 'absolute',
                'states_compared': states_data,
                'comparison_summary': {
                    'highest_state': states_data[0]['state'],
                    'lowest_state': states_data[-1]['state'],
                    'range': round(max(rates) - min(rates), 2),
                    'average_of_compared': round(sum(rates) / len(rates), 2)
                }
            }
            
            if national_data:
                result['national_reference'] = {
                    'total_incidents': national_data.get('total_incidents', 0),
                    'rate_per_100k': national_data.get('rate_per_100k', 0)
                }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to compare states: {e}")
            raise


# Tool registry for easy access
FBI_TOOLS = {
    'fbi_get_national_statistics': FBIGetNationalStatisticsTool,
    'fbi_get_state_statistics': FBIGetStateStatisticsTool,
    'fbi_get_agency_statistics': FBIGetAgencyStatisticsTool,
    'fbi_search_agencies': FBISearchAgenciesTool,
    'fbi_get_offense_data': FBIGetOffenseDataTool,
    'fbi_get_participation_rate': FBIGetParticipationRateTool,
    'fbi_get_agency_details': FBIGetAgencyDetailsTool,
    'fbi_get_crime_trend': FBIGetCrimeTrendTool,
    'fbi_compare_states': FBICompareStatesTool
}
