"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
FBI Crime Data Explorer MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools.base_mcp_tool import BaseMCPTool

class FBITool(BaseMCPTool):
    """
    FBI Crime Data Explorer API tool for retrieving US crime statistics and data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize FBI tool"""
        default_config = {
            'name': 'fbi',
            'description': 'Retrieve US crime statistics and data from FBI Crime Data Explorer',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # FBI Crime Data Explorer API endpoint
        self.api_url = "https://api.usa.gov/crime/fbi/cde"
        
        # Crime offense types
        self.offense_types = {
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
        
        # US State abbreviations
        self.states = {
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
    
    def get_input_schema(self) -> Dict:
        """Get input schema for FBI tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_national_statistics",
                        "get_state_statistics",
                        "get_agency_statistics",
                        "search_agencies",
                        "get_offense_data",
                        "get_participation_rate",
                        "get_agency_details",
                        "get_crime_trend",
                        "compare_states"
                    ]
                },
                "state": {
                    "type": "string",
                    "description": "US State abbreviation (e.g., CA, NY, TX)"
                },
                "offense_type": {
                    "type": "string",
                    "description": "Type of crime offense",
                    "enum": list(self.offense_types.keys())
                },
                "ori": {
                    "type": "string",
                    "description": "Originating Agency Identifier (ORI) code"
                },
                "agency_name": {
                    "type": "string",
                    "description": "Name of law enforcement agency to search"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for crime statistics (e.g., 2022)"
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year for trend analysis"
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year for trend analysis"
                },
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of state abbreviations to compare"
                },
                "per_capita": {
                    "type": "boolean",
                    "description": "Return statistics per capita (per 100,000 population)",
                    "default": False
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute FBI tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Crime statistics and data from FBI
        """
        action = arguments.get('action')
        
        if action == 'get_national_statistics':
            year = arguments.get('year', self._get_latest_year())
            offense_type = arguments.get('offense_type', 'violent_crime')
            per_capita = arguments.get('per_capita', False)
            
            return self._get_national_statistics(year, offense_type, per_capita)
            
        elif action == 'get_state_statistics':
            state = arguments.get('state')
            if not state:
                raise ValueError("'state' parameter is required")
            
            year = arguments.get('year', self._get_latest_year())
            offense_type = arguments.get('offense_type', 'violent_crime')
            per_capita = arguments.get('per_capita', False)
            
            return self._get_state_statistics(state, year, offense_type, per_capita)
            
        elif action == 'get_agency_statistics':
            ori = arguments.get('ori')
            if not ori:
                raise ValueError("'ori' parameter is required")
            
            year = arguments.get('year', self._get_latest_year())
            offense_type = arguments.get('offense_type', 'violent_crime')
            
            return self._get_agency_statistics(ori, year, offense_type)
            
        elif action == 'search_agencies':
            state = arguments.get('state')
            agency_name = arguments.get('agency_name')
            
            return self._search_agencies(state, agency_name)
            
        elif action == 'get_offense_data':
            year = arguments.get('year', self._get_latest_year())
            state = arguments.get('state')
            
            return self._get_offense_data(year, state)
            
        elif action == 'get_participation_rate':
            year = arguments.get('year', self._get_latest_year())
            state = arguments.get('state')
            
            return self._get_participation_rate(year, state)
            
        elif action == 'get_agency_details':
            ori = arguments.get('ori')
            if not ori:
                raise ValueError("'ori' parameter is required")
            
            return self._get_agency_details(ori)
            
        elif action == 'get_crime_trend':
            state = arguments.get('state')
            offense_type = arguments.get('offense_type', 'violent_crime')
            start_year = arguments.get('start_year', self._get_latest_year() - 5)
            end_year = arguments.get('end_year', self._get_latest_year())
            per_capita = arguments.get('per_capita', False)
            
            return self._get_crime_trend(state, offense_type, start_year, end_year, per_capita)
            
        elif action == 'compare_states':
            states = arguments.get('states', [])
            if not states or len(states) < 2:
                raise ValueError("At least 2 states required for comparison")
            
            year = arguments.get('year', self._get_latest_year())
            offense_type = arguments.get('offense_type', 'violent_crime')
            per_capita = arguments.get('per_capita', True)
            
            return self._compare_states(states, year, offense_type, per_capita)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """
        Make HTTP request to FBI API
        
        Args:
            endpoint: API endpoint
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
                return json.loads(response.read().decode('utf-8'))
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Resource not found: {endpoint}")
            else:
                self.logger.error(f"FBI API error: {e}")
                raise ValueError(f"Failed to fetch data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"FBI API error: {e}")
            raise ValueError(f"Failed to fetch data: {str(e)}")
    
    def _get_national_statistics(
        self,
        year: int,
        offense_type: str,
        per_capita: bool
    ) -> Dict:
        """
        Get national crime statistics
        
        Args:
            year: Year for statistics
            offense_type: Type of crime
            per_capita: Return per capita statistics
            
        Returns:
            National crime statistics
        """
        offense = self.offense_types.get(offense_type, offense_type)
        endpoint = f"summarized/national/{offense}/{year}"
        
        data = self._make_request(endpoint)
        
        return {
            'year': year,
            'offense_type': offense_type,
            'offense_category': offense,
            'per_capita': per_capita,
            'data': data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_state_statistics(
        self,
        state: str,
        year: int,
        offense_type: str,
        per_capita: bool
    ) -> Dict:
        """
        Get state crime statistics
        
        Args:
            state: State abbreviation
            year: Year for statistics
            offense_type: Type of crime
            per_capita: Return per capita statistics
            
        Returns:
            State crime statistics
        """
        state = state.upper()
        if state not in self.states:
            raise ValueError(f"Invalid state abbreviation: {state}")
        
        offense = self.offense_types.get(offense_type, offense_type)
        endpoint = f"summarized/state/{state}/{offense}/{year}"
        
        data = self._make_request(endpoint)
        
        return {
            'state': state,
            'state_name': self.states[state],
            'year': year,
            'offense_type': offense_type,
            'offense_category': offense,
            'per_capita': per_capita,
            'data': data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_agency_statistics(
        self,
        ori: str,
        year: int,
        offense_type: str
    ) -> Dict:
        """
        Get agency crime statistics
        
        Args:
            ori: Originating Agency Identifier
            year: Year for statistics
            offense_type: Type of crime
            
        Returns:
            Agency crime statistics
        """
        offense = self.offense_types.get(offense_type, offense_type)
        endpoint = f"summarized/agency/{ori}/{offense}/{year}"
        
        data = self._make_request(endpoint)
        
        return {
            'ori': ori,
            'year': year,
            'offense_type': offense_type,
            'offense_category': offense,
            'data': data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _search_agencies(
        self,
        state: Optional[str] = None,
        agency_name: Optional[str] = None
    ) -> Dict:
        """
        Search for law enforcement agencies
        
        Args:
            state: Filter by state
            agency_name: Filter by agency name
            
        Returns:
            List of matching agencies
        """
        endpoint = "agencies"
        params = {}
        
        if state:
            state = state.upper()
            if state not in self.states:
                raise ValueError(f"Invalid state abbreviation: {state}")
            params['state'] = state
        
        if agency_name:
            params['name'] = agency_name
        
        data = self._make_request(endpoint, params)
        
        return {
            'search_criteria': {
                'state': state,
                'agency_name': agency_name
            },
            'agencies': data.get('results', []),
            'total_count': len(data.get('results', [])),
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_offense_data(
        self,
        year: int,
        state: Optional[str] = None
    ) -> Dict:
        """
        Get detailed offense data
        
        Args:
            year: Year for statistics
            state: Optional state filter
            
        Returns:
            Offense data
        """
        results = {}
        
        for offense_name, offense_code in self.offense_types.items():
            try:
                if state:
                    endpoint = f"summarized/state/{state.upper()}/{offense_code}/{year}"
                else:
                    endpoint = f"summarized/national/{offense_code}/{year}"
                
                data = self._make_request(endpoint)
                results[offense_name] = data
            except Exception as e:
                self.logger.warning(f"Failed to get {offense_name} data: {e}")
                results[offense_name] = {'error': str(e)}
        
        return {
            'year': year,
            'state': state,
            'offenses': results,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_participation_rate(
        self,
        year: int,
        state: Optional[str] = None
    ) -> Dict:
        """
        Get agency participation rate in UCR reporting
        
        Args:
            year: Year for statistics
            state: Optional state filter
            
        Returns:
            Participation rate data
        """
        if state:
            state = state.upper()
            if state not in self.states:
                raise ValueError(f"Invalid state abbreviation: {state}")
            endpoint = f"participation/state/{state}/{year}"
        else:
            endpoint = f"participation/national/{year}"
        
        data = self._make_request(endpoint)
        
        return {
            'year': year,
            'state': state,
            'state_name': self.states.get(state) if state else 'National',
            'participation_data': data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_agency_details(self, ori: str) -> Dict:
        """
        Get detailed information about an agency
        
        Args:
            ori: Originating Agency Identifier
            
        Returns:
            Agency details
        """
        endpoint = f"agencies/{ori}"
        
        data = self._make_request(endpoint)
        
        return {
            'ori': ori,
            'agency_details': data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_crime_trend(
        self,
        state: Optional[str],
        offense_type: str,
        start_year: int,
        end_year: int,
        per_capita: bool
    ) -> Dict:
        """
        Get crime trend over multiple years
        
        Args:
            state: Optional state filter
            offense_type: Type of crime
            start_year: Start year
            end_year: End year
            per_capita: Return per capita statistics
            
        Returns:
            Crime trend data
        """
        offense = self.offense_types.get(offense_type, offense_type)
        trend_data = []
        
        for year in range(start_year, end_year + 1):
            try:
                if state:
                    state = state.upper()
                    if state not in self.states:
                        raise ValueError(f"Invalid state abbreviation: {state}")
                    endpoint = f"summarized/state/{state}/{offense}/{year}"
                else:
                    endpoint = f"summarized/national/{offense}/{year}"
                
                data = self._make_request(endpoint)
                trend_data.append({
                    'year': year,
                    'data': data
                })
            except Exception as e:
                self.logger.warning(f"Failed to get {year} data: {e}")
                trend_data.append({
                    'year': year,
                    'error': str(e)
                })
        
        return {
            'state': state,
            'state_name': self.states.get(state) if state else 'National',
            'offense_type': offense_type,
            'offense_category': offense,
            'start_year': start_year,
            'end_year': end_year,
            'per_capita': per_capita,
            'trend': trend_data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _compare_states(
        self,
        states: List[str],
        year: int,
        offense_type: str,
        per_capita: bool
    ) -> Dict:
        """
        Compare crime statistics across multiple states
        
        Args:
            states: List of state abbreviations
            year: Year for comparison
            offense_type: Type of crime
            per_capita: Return per capita statistics
            
        Returns:
            Comparison data
        """
        offense = self.offense_types.get(offense_type, offense_type)
        comparison_data = {}
        
        for state in states:
            state = state.upper()
            if state not in self.states:
                self.logger.warning(f"Invalid state abbreviation: {state}")
                continue
            
            try:
                endpoint = f"summarized/state/{state}/{offense}/{year}"
                data = self._make_request(endpoint)
                comparison_data[state] = {
                    'state_name': self.states[state],
                    'data': data
                }
            except Exception as e:
                self.logger.warning(f"Failed to get {state} data: {e}")
                comparison_data[state] = {
                    'state_name': self.states[state],
                    'error': str(e)
                }
        
        return {
            'year': year,
            'offense_type': offense_type,
            'offense_category': offense,
            'per_capita': per_capita,
            'states': comparison_data,
            'source': 'FBI Crime Data Explorer',
            'retrieved_at': datetime.now().isoformat()
        }
    
    def _get_latest_year(self) -> int:
        """Get the latest available year (typically current year - 2)"""
        return datetime.now().year - 2
