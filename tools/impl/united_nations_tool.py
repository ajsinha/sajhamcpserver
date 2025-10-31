"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
United Nations MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool

class UnitedNationsTool(BaseMCPTool):
    """
    United Nations API tool for retrieving global statistics and SDG data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize United Nations tool"""
        default_config = {
            'name': 'united_nations',
            'description': 'Retrieve global statistics and SDG data from United Nations',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # UN Data API endpoints
        self.comtrade_url = "https://comtradeapi.un.org/data/v1"
        self.sdg_url = "https://unstats.un.org/sdgapi/v1/sdg"
        
        # Sustainable Development Goals (SDGs)
        self.sdgs = {
            '1': 'No Poverty',
            '2': 'Zero Hunger',
            '3': 'Good Health and Well-being',
            '4': 'Quality Education',
            '5': 'Gender Equality',
            '6': 'Clean Water and Sanitation',
            '7': 'Affordable and Clean Energy',
            '8': 'Decent Work and Economic Growth',
            '9': 'Industry, Innovation and Infrastructure',
            '10': 'Reduced Inequalities',
            '11': 'Sustainable Cities and Communities',
            '12': 'Responsible Consumption and Production',
            '13': 'Climate Action',
            '14': 'Life Below Water',
            '15': 'Life on Land',
            '16': 'Peace, Justice and Strong Institutions',
            '17': 'Partnerships for the Goals'
        }
        
        # Common trade classifications
        self.trade_flows = {
            'export': 'X',
            'import': 'M',
            're_export': 'RX',
            're_import': 'RM'
        }
        
        # Common commodity groups (HS codes)
        self.commodity_groups = {
            'all': 'TOTAL',
            'agricultural': '01-24',
            'mineral': '25-27',
            'chemicals': '28-38',
            'plastics_rubber': '39-40',
            'textiles': '50-63',
            'footwear': '64-67',
            'metals': '72-83',
            'machinery': '84-85',
            'vehicles': '86-89',
            'optical_instruments': '90-92'
        }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for United Nations tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_sdgs",
                        "get_sdg_indicators",
                        "get_sdg_data",
                        "get_sdg_targets",
                        "get_trade_data",
                        "get_country_trade",
                        "get_trade_balance",
                        "compare_trade",
                        "get_sdg_progress"
                    ]
                },
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code (1-17)",
                    "enum": list(self.sdgs.keys())
                },
                "indicator_code": {
                    "type": "string",
                    "description": "SDG indicator code (e.g., 1.1.1, 3.2.1)"
                },
                "target_code": {
                    "type": "string",
                    "description": "SDG target code (e.g., 1.1, 3.2)"
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO3 country code (e.g., USA, CHN, IND)"
                },
                "country_codes": {
                    "type": "array",
                    "description": "List of country codes for comparison",
                    "items": {"type": "string"}
                },
                "reporter_code": {
                    "type": "string",
                    "description": "Reporter country code for trade data"
                },
                "partner_code": {
                    "type": "string",
                    "description": "Partner country code for trade data"
                },
                "trade_flow": {
                    "type": "string",
                    "description": "Type of trade flow",
                    "enum": ["export", "import", "re_export", "re_import"]
                },
                "commodity_code": {
                    "type": "string",
                    "description": "HS commodity code or group",
                    "enum": list(self.commodity_groups.keys())
                },
                "year": {
                    "type": "integer",
                    "description": "Year for data retrieval",
                    "minimum": 1962,
                    "maximum": 2030
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year for data retrieval",
                    "minimum": 2000,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year for data retrieval",
                    "minimum": 2000,
                    "maximum": 2030
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute United Nations tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            UN statistics and SDG data
        """
        action = arguments.get('action')
        
        if action == 'get_sdgs':
            return self._get_sdgs()
            
        elif action == 'get_sdg_indicators':
            sdg_code = arguments.get('sdg_code')
            return self._get_sdg_indicators(sdg_code)
            
        elif action == 'get_sdg_data':
            indicator_code = arguments.get('indicator_code')
            country_code = arguments.get('country_code')
            
            if not indicator_code:
                raise ValueError("'indicator_code' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            
            return self._get_sdg_data(indicator_code, country_code, start_year, end_year)
            
        elif action == 'get_sdg_targets':
            sdg_code = arguments.get('sdg_code')
            if not sdg_code:
                raise ValueError("'sdg_code' is required")
            
            return self._get_sdg_targets(sdg_code)
            
        elif action == 'get_trade_data':
            reporter_code = arguments.get('reporter_code')
            partner_code = arguments.get('partner_code', 'all')
            trade_flow = arguments.get('trade_flow', 'export')
            commodity_code = arguments.get('commodity_code', 'all')
            year = arguments.get('year', datetime.now().year - 1)
            
            if not reporter_code:
                raise ValueError("'reporter_code' is required")
            
            return self._get_trade_data(reporter_code, partner_code, trade_flow, commodity_code, year)
            
        elif action == 'get_country_trade':
            country_code = arguments.get('country_code')
            year = arguments.get('year', datetime.now().year - 1)
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            return self._get_country_trade(country_code, year)
            
        elif action == 'get_trade_balance':
            country_code = arguments.get('country_code')
            partner_code = arguments.get('partner_code')
            year = arguments.get('year', datetime.now().year - 1)
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            return self._get_trade_balance(country_code, partner_code, year)
            
        elif action == 'compare_trade':
            country_codes = arguments.get('country_codes', [])
            trade_flow = arguments.get('trade_flow', 'export')
            year = arguments.get('year', datetime.now().year - 1)
            
            if not country_codes or len(country_codes) < 2:
                raise ValueError("At least 2 country codes required in 'country_codes'")
            
            return self._compare_trade(country_codes, trade_flow, year)
            
        elif action == 'get_sdg_progress':
            country_code = arguments.get('country_code')
            sdg_code = arguments.get('sdg_code')
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            return self._get_sdg_progress(country_code, sdg_code)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _get_sdgs(self) -> Dict:
        """
        Get list of Sustainable Development Goals
        
        Returns:
            List of SDGs
        """
        sdgs_list = []
        for code, title in self.sdgs.items():
            sdgs_list.append({
                'code': code,
                'title': title,
                'full_title': f"Goal {code}: {title}"
            })
        
        return {
            'sdgs': sdgs_list,
            'count': len(sdgs_list)
        }
    
    def _get_sdg_indicators(self, sdg_code: Optional[str] = None) -> Dict:
        """
        Get SDG indicators
        
        Args:
            sdg_code: SDG code (optional)
            
        Returns:
            List of SDG indicators
        """
        try:
            url = f"{self.sdg_url}/Indicator/List"
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                indicators = []
                for item in data:
                    if isinstance(item, dict):
                        code = item.get('code', '')
                        
                        # Filter by SDG if specified
                        if sdg_code and not code.startswith(f"{sdg_code}."):
                            continue
                        
                        indicators.append({
                            'code': code,
                            'description': item.get('description'),
                            'goal': item.get('goal'),
                            'target': item.get('target'),
                            'uri': item.get('uri')
                        })
                
                return {
                    'sdg_code': sdg_code,
                    'indicators': indicators,
                    'count': len(indicators)
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get SDG indicators: {e}")
            return {
                'sdg_code': sdg_code,
                'error': str(e),
                'note': 'Failed to retrieve SDG indicators from UN API'
            }
    
    def _get_sdg_data(
        self,
        indicator_code: str,
        country_code: Optional[str] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> Dict:
        """
        Get SDG indicator data
        
        Args:
            indicator_code: SDG indicator code
            country_code: Country code (optional)
            start_year: Start year
            end_year: End year
            
        Returns:
            SDG indicator data
        """
        try:
            url = f"{self.sdg_url}/Indicator/Data"
            
            params = {
                'indicator': indicator_code
            }
            
            if country_code:
                params['areaCode'] = country_code
            if start_year:
                params['startYear'] = start_year
            if end_year:
                params['endYear'] = end_year
            
            url += '?' + urllib.parse.urlencode(params)
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                formatted_data = []
                for item in data:
                    if isinstance(item, dict):
                        formatted_data.append({
                            'indicator': item.get('indicator'),
                            'goal': item.get('goal'),
                            'target': item.get('target'),
                            'series_code': item.get('seriesCode'),
                            'series_description': item.get('seriesDescription'),
                            'geo_area_code': item.get('geoAreaCode'),
                            'geo_area_name': item.get('geoAreaName'),
                            'time_period': item.get('timePeriod'),
                            'value': item.get('value'),
                            'units': item.get('units'),
                            'nature': item.get('nature')
                        })
                
                return {
                    'indicator_code': indicator_code,
                    'country_code': country_code,
                    'data': formatted_data,
                    'count': len(formatted_data)
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get SDG data: {e}")
            return {
                'indicator_code': indicator_code,
                'country_code': country_code,
                'error': str(e),
                'note': 'Failed to retrieve SDG data from UN API'
            }
    
    def _get_sdg_targets(self, sdg_code: str) -> Dict:
        """
        Get targets for a specific SDG
        
        Args:
            sdg_code: SDG code
            
        Returns:
            SDG targets
        """
        try:
            url = f"{self.sdg_url}/Target/List"
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                targets = []
                for item in data:
                    if isinstance(item, dict):
                        code = item.get('code', '')
                        
                        # Filter by SDG
                        if code.startswith(f"{sdg_code}."):
                            targets.append({
                                'code': code,
                                'title': item.get('title'),
                                'description': item.get('description'),
                                'uri': item.get('uri')
                            })
                
                return {
                    'sdg_code': sdg_code,
                    'sdg_title': self.sdgs.get(sdg_code),
                    'targets': targets,
                    'count': len(targets)
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get SDG targets: {e}")
            return {
                'sdg_code': sdg_code,
                'error': str(e),
                'note': 'Failed to retrieve SDG targets from UN API'
            }
    
    def _get_trade_data(
        self,
        reporter_code: str,
        partner_code: str = 'all',
        trade_flow: str = 'export',
        commodity_code: str = 'all',
        year: int = None
    ) -> Dict:
        """
        Get UN Comtrade data
        
        Args:
            reporter_code: Reporter country code
            partner_code: Partner country code
            trade_flow: Trade flow type
            commodity_code: Commodity code
            year: Year
            
        Returns:
            Trade data
        """
        if year is None:
            year = datetime.now().year - 1
        
        # Convert trade flow to code
        flow_code = self.trade_flows.get(trade_flow, 'X')
        
        # Convert commodity group to code
        commodity = self.commodity_groups.get(commodity_code, commodity_code)
        
        return {
            'reporter': reporter_code,
            'partner': partner_code,
            'trade_flow': trade_flow,
            'commodity': commodity,
            'year': year,
            'note': 'UN Comtrade API requires authentication. This is a placeholder implementation.',
            'data': []
        }
    
    def _get_country_trade(self, country_code: str, year: int) -> Dict:
        """
        Get comprehensive trade data for a country
        
        Args:
            country_code: Country code
            year: Year
            
        Returns:
            Country trade data
        """
        return {
            'country_code': country_code,
            'year': year,
            'exports': self._get_trade_data(country_code, 'all', 'export', 'all', year),
            'imports': self._get_trade_data(country_code, 'all', 'import', 'all', year),
            'note': 'UN Comtrade API requires authentication for full data access.'
        }
    
    def _get_trade_balance(
        self,
        country_code: str,
        partner_code: Optional[str] = None,
        year: int = None
    ) -> Dict:
        """
        Calculate trade balance
        
        Args:
            country_code: Country code
            partner_code: Partner country code (optional)
            year: Year
            
        Returns:
            Trade balance
        """
        if year is None:
            year = datetime.now().year - 1
        
        partner = partner_code or 'all'
        
        return {
            'country_code': country_code,
            'partner_code': partner,
            'year': year,
            'note': 'Trade balance calculation requires full Comtrade API access.',
            'data': {
                'exports': None,
                'imports': None,
                'balance': None
            }
        }
    
    def _compare_trade(
        self,
        country_codes: List[str],
        trade_flow: str,
        year: int
    ) -> Dict:
        """
        Compare trade data across countries
        
        Args:
            country_codes: List of country codes
            trade_flow: Trade flow type
            year: Year
            
        Returns:
            Trade comparison
        """
        comparison = {
            'trade_flow': trade_flow,
            'year': year,
            'countries': []
        }
        
        for country_code in country_codes:
            data = self._get_trade_data(country_code, 'all', trade_flow, 'all', year)
            comparison['countries'].append(data)
        
        return comparison
    
    def _get_sdg_progress(self, country_code: str, sdg_code: Optional[str] = None) -> Dict:
        """
        Get SDG progress for a country
        
        Args:
            country_code: Country code
            sdg_code: SDG code (optional)
            
        Returns:
            SDG progress data
        """
        if sdg_code:
            # Get indicators for specific SDG
            indicators_data = self._get_sdg_indicators(sdg_code)
            
            progress = {
                'country_code': country_code,
                'sdg_code': sdg_code,
                'sdg_title': self.sdgs.get(sdg_code),
                'indicators': []
            }
            
            # Get data for each indicator
            for indicator in indicators_data.get('indicators', [])[:5]:  # Limit to 5 indicators
                indicator_code = indicator.get('code')
                try:
                    data = self._get_sdg_data(indicator_code, country_code)
                    progress['indicators'].append({
                        'indicator_code': indicator_code,
                        'description': indicator.get('description'),
                        'latest_data': data.get('data', [])[-1] if data.get('data') else None
                    })
                except Exception as e:
                    self.logger.warning(f"Failed to get data for indicator {indicator_code}: {e}")
            
            return progress
        else:
            # Get overall progress summary
            return {
                'country_code': country_code,
                'note': 'Specify sdg_code for detailed progress on a specific goal',
                'available_sdgs': list(self.sdgs.keys())
            }
