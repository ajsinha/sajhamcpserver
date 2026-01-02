"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
World Bank MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL


class WorldBankBaseTool(BaseMCPTool):
    """
    Base class for World Bank tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize World Bank base tool"""
        super().__init__(config)
        
        # World Bank API v2 endpoint
        self.api_url = "https://api.worldbank.org/v2"
        
        # Common indicator mappings
        self.indicator_map = {
            # Economic
            'gdp': 'NY.GDP.MKTP.CD',
            'gdp_per_capita': 'NY.GDP.PCAP.CD',
            'gdp_growth': 'NY.GDP.MKTP.KD.ZG',
            'gdp_ppp': 'NY.GDP.MKTP.PP.CD',
            'inflation': 'FP.CPI.TOTL.ZG',
            'food_price_inflation': 'FP.CPI.FOOD.ZG',
            
            # Population & Demographics
            'population': 'SP.POP.TOTL',
            'population_growth': 'SP.POP.GROW',
            'urban_population': 'SP.URB.TOTL.IN.ZS',
            'life_expectancy': 'SP.DYN.LE00.IN',
            'birth_rate': 'SP.DYN.CBRT.IN',
            'death_rate': 'SP.DYN.CDRT.IN',
            
            # Social
            'poverty_rate': 'SI.POV.DDAY',
            'gini_index': 'SI.POV.GINI',
            'income_share_lowest_20': 'SI.DST.FRST.20',
            'literacy_rate': 'SE.ADT.LITR.ZS',
            'primary_enrollment': 'SE.PRM.NENR',
            'secondary_enrollment': 'SE.SEC.NENR',
            'tertiary_enrollment': 'SE.TER.ENRR',
            
            # Health
            'infant_mortality': 'SP.DYN.IMRT.IN',
            'maternal_mortality': 'SH.STA.MMRT',
            'health_expenditure': 'SH.XPD.CHEX.GD.ZS',
            'hospital_beds': 'SH.MED.BEDS.ZS',
            
            # Labor & Employment
            'unemployment': 'SL.UEM.TOTL.ZS',
            'labor_force': 'SL.TLF.TOTL.IN',
            'female_labor_force': 'SL.TLF.CACT.FE.ZS',
            
            # Trade & Finance
            'exports': 'NE.EXP.GNFS.CD',
            'imports': 'NE.IMP.GNFS.CD',
            'trade_gdp': 'NE.TRD.GNFS.ZS',
            'fdi_inflow': 'BX.KLT.DINV.CD.WD',
            'external_debt': 'DT.DOD.DECT.CD',
            
            # Environment
            'co2_emissions': 'EN.ATM.CO2E.KT',
            'co2_per_capita': 'EN.ATM.CO2E.PC',
            'renewable_energy': 'EG.FEC.RNEW.ZS',
            'electricity_access': 'EG.ELC.ACCS.ZS',
            'forest_area': 'AG.LND.FRST.ZS',
            
            # Technology & Infrastructure
            'internet_users': 'IT.NET.USER.ZS',
            'mobile_subscriptions': 'IT.CEL.SETS.P2',
            'roads_paved': 'IS.ROD.PAVE.ZP'
        }
    
    def _make_request(self, endpoint: str, params: Dict = None) -> List:
        """
        Make API request to World Bank
        
        Args:
            endpoint: API endpoint path
            params: Query parameters
            
        Returns:
            Parsed response data
        """
        url = f"{self.api_url}/{endpoint}"
        params = params or {}
        params['format'] = 'json'
        params['per_page'] = params.get('per_page', 100)
        
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as response:
                data = safe_json_response(response, ENCODINGS_ALL)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Resource not found: {endpoint}")
            else:
                raise ValueError(f"World Bank API request failed: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"World Bank API request failed: {str(e)}")


class WBGetCountriesTool(WorldBankBaseTool):
    """
    Tool to retrieve list of all countries and regions with metadata
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_countries',
            'description': 'Retrieve list of all countries and regions with their metadata',
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
                "income_level": {
                    "type": "string",
                    "enum": ["HIC", "UMC", "LMC", "LIC", "all"],
                    "default": "all"
                },
                "region": {
                    "type": "string",
                    "enum": ["EAS", "ECS", "LCN", "MEA", "NAC", "SAS", "SSF", "WLD", "all"],
                    "default": "all"
                },
                "lending_type": {
                    "type": "string",
                    "enum": ["IBD", "IDB", "IDX", "LNX", "all"],
                    "default": "all"
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 300
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "total_countries": {"type": "integer"},
                "filters_applied": {"type": "object"},
                "countries": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        income_level = arguments.get('income_level', 'all')
        region = arguments.get('region', 'all')
        lending_type = arguments.get('lending_type', 'all')
        per_page = arguments.get('per_page', 300)
        
        params = {'per_page': per_page}
        
        # Build endpoint with filters
        if income_level != 'all':
            params['incomeLevel'] = income_level
        if region != 'all':
            params['region'] = region
        if lending_type != 'all':
            params['lendingType'] = lending_type
        
        try:
            data = self._make_request('country', params)
            
            if len(data) < 2:
                return {
                    'total_countries': 0,
                    'filters_applied': {
                        'income_level': income_level,
                        'region': region,
                        'lending_type': lending_type
                    },
                    'countries': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            countries_data = data[1]
            countries = []
            
            for country in countries_data:
                countries.append({
                    'id': country.get('id'),
                    'iso3': country.get('iso2Code'),
                    'name': country.get('name'),
                    'capital': country.get('capitalCity'),
                    'region': country.get('region'),
                    'income_level': country.get('incomeLevel'),
                    'lending_type': country.get('lendingType'),
                    'longitude': country.get('longitude'),
                    'latitude': country.get('latitude')
                })
            
            return {
                'total_countries': len(countries),
                'filters_applied': {
                    'income_level': income_level,
                    'region': region,
                    'lending_type': lending_type
                },
                'countries': countries,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get countries: {e}")
            raise


class WBGetIndicatorsTool(WorldBankBaseTool):
    """
    Tool to retrieve list of all available indicators
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_indicators',
            'description': 'Retrieve list of all available World Bank development indicators',
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
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 21
                },
                "source": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "total_indicators": {"type": "integer"},
                "page": {"type": "integer"},
                "per_page": {"type": "integer"},
                "total_pages": {"type": "integer"},
                "indicators": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        per_page = arguments.get('per_page', 100)
        page = arguments.get('page', 1)
        
        params = {
            'per_page': per_page,
            'page': page
        }
        
        if 'topic_id' in arguments:
            params['topic'] = arguments['topic_id']
        if 'source' in arguments:
            params['source'] = arguments['source']
        
        try:
            data = self._make_request('indicator', params)
            
            if len(data) < 2:
                return {
                    'total_indicators': 0,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': 0,
                    'indicators': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            metadata = data[0]
            indicators_data = data[1]
            
            indicators = []
            for ind in indicators_data:
                indicators.append({
                    'id': ind.get('id'),
                    'name': ind.get('name'),
                    'source': ind.get('source'),
                    'source_note': ind.get('sourceNote'),
                    'source_organization': ind.get('sourceOrganization'),
                    'topics': ind.get('topics', [])
                })
            
            return {
                'total_indicators': metadata.get('total', len(indicators)),
                'page': metadata.get('page', page),
                'per_page': metadata.get('per_page', per_page),
                'total_pages': metadata.get('pages', 1),
                'indicators': indicators,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get indicators: {e}")
            raise


class WBGetCountryDataTool(WorldBankBaseTool):
    """
    Tool to retrieve specific indicator data for a single country
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_country_data',
            'description': 'Retrieve specific indicator data for a single country over time',
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
                "country_code": {
                    "type": "string",
                    "pattern": "^[A-Z]{2,3}$"
                },
                "indicator": {
                    "type": "string",
                    "enum": list(self.indicator_map.keys())
                },
                "indicator_code": {
                    "type": "string"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100
                }
            },
            "required": ["country_code"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "country": {"type": "object"},
                "indicator": {"type": "object"},
                "data_points": {"type": "integer"},
                "data": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_code = arguments['country_code'].upper()
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        per_page = arguments.get('per_page', 100)
        
        # Get indicator code
        if indicator and not indicator_code:
            indicator_code = self.indicator_map.get(indicator)
            if not indicator_code:
                raise ValueError(f"Unknown indicator: {indicator}")
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' must be provided")
        
        # Build endpoint
        endpoint = f"country/{country_code}/indicator/{indicator_code}"
        
        params = {'per_page': per_page}
        if start_year and end_year:
            params['date'] = f"{start_year}:{end_year}"
        
        try:
            data = self._make_request(endpoint, params)
            
            if len(data) < 2 or not data[1]:
                return {
                    'country': {'id': country_code, 'name': ''},
                    'indicator': {'id': indicator_code, 'name': ''},
                    'data_points': 0,
                    'data': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            results = data[1]
            
            formatted_data = []
            for item in results:
                if item.get('value') is not None:
                    formatted_data.append({
                        'year': int(item['date']),
                        'value': float(item['value']) if item['value'] else None,
                        'unit': '',
                        'decimal': item.get('decimal', 2)
                    })
            
            # Sort by year
            formatted_data.sort(key=lambda x: x['year'])
            
            return {
                'country': {
                    'id': country_code,
                    'name': results[0]['country']['value'] if results else ''
                },
                'indicator': {
                    'id': indicator_code,
                    'name': results[0]['indicator']['value'] if results else ''
                },
                'data_points': len(formatted_data),
                'data': formatted_data,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get country data: {e}")
            raise


class WBGetIndicatorDataTool(WorldBankBaseTool):
    """
    Tool to retrieve indicator data across all countries
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_indicator_data',
            'description': 'Retrieve a specific indicator across all countries for comparison',
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
                    "enum": list(self.indicator_map.keys())
                },
                "indicator_code": {
                    "type": "string"
                },
                "year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "income_level": {
                    "type": "string",
                    "enum": ["HIC", "UMC", "LMC", "LIC"]
                },
                "region": {
                    "type": "string",
                    "enum": ["EAS", "ECS", "LCN", "MEA", "NAC", "SAS", "SSF"]
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "indicator": {"type": "object"},
                "year_filter": {"type": ["integer", "object", "null"]},
                "filters_applied": {"type": "object"},
                "country_count": {"type": "integer"},
                "data": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        year = arguments.get('year')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        income_level = arguments.get('income_level')
        region = arguments.get('region')
        per_page = arguments.get('per_page', 100)
        
        # Get indicator code
        if indicator and not indicator_code:
            indicator_code = self.indicator_map.get(indicator)
            if not indicator_code:
                raise ValueError(f"Unknown indicator: {indicator}")
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' must be provided")
        
        # Build country filter
        country_filter = 'all'
        if income_level:
            country_filter = income_level
        elif region:
            country_filter = region
        
        endpoint = f"country/{country_filter}/indicator/{indicator_code}"
        
        params = {'per_page': per_page}
        if year:
            params['date'] = str(year)
        elif start_year and end_year:
            params['date'] = f"{start_year}:{end_year}"
        
        try:
            data = self._make_request(endpoint, params)
            
            if len(data) < 2 or not data[1]:
                return {
                    'indicator': {'id': indicator_code, 'name': ''},
                    'year_filter': year or {'start': start_year, 'end': end_year} if start_year else None,
                    'filters_applied': {
                        'income_level': income_level,
                        'region': region
                    },
                    'country_count': 0,
                    'data': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            results = data[1]
            
            formatted_data = []
            for item in results:
                if item.get('value') is not None:
                    formatted_data.append({
                        'country': {
                            'id': item['country']['id'],
                            'name': item['country']['value']
                        },
                        'year': int(item['date']),
                        'value': float(item['value']) if item['value'] else None,
                        'unit': ''
                    })
            
            return {
                'indicator': {
                    'id': indicator_code,
                    'name': results[0]['indicator']['value'] if results else ''
                },
                'year_filter': year or {'start': start_year, 'end': end_year} if start_year else None,
                'filters_applied': {
                    'income_level': income_level,
                    'region': region
                },
                'country_count': len(set(item['country']['id'] for item in formatted_data)),
                'data': formatted_data,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get indicator data: {e}")
            raise
"""
World Bank MCP Tool Implementation - Part 2 (Remaining Tools)
"""

from typing import Dict, Any, List
from datetime import datetime


class WBSearchIndicatorsTool(WorldBankBaseTool):
    """
    Tool to search indicators by keyword
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_search_indicators',
            'description': 'Search World Bank indicators by keyword or topic',
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
                "search_term": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 100
                },
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 21
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["search_term"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "search_term": {"type": "string"},
                "total_results": {"type": "integer"},
                "page": {"type": "integer"},
                "per_page": {"type": "integer"},
                "results": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        search_term = arguments['search_term'].lower()
        topic_id = arguments.get('topic_id')
        per_page = arguments.get('per_page', 50)
        page = arguments.get('page', 1)
        
        params = {
            'per_page': per_page,
            'page': page
        }
        
        if topic_id:
            params['topic'] = topic_id
        
        try:
            # Get all indicators
            data = self._make_request('indicator', params)
            
            if len(data) < 2:
                return {
                    'search_term': search_term,
                    'total_results': 0,
                    'page': page,
                    'per_page': per_page,
                    'results': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            indicators_data = data[1]
            
            # Filter by search term
            results = []
            for ind in indicators_data:
                name = ind.get('name', '').lower()
                source_note = ind.get('sourceNote', '').lower()
                
                if search_term in name or search_term in source_note:
                    # Calculate simple relevance score
                    relevance = 0.0
                    if search_term in name:
                        relevance += 0.6
                    if search_term in source_note:
                        relevance += 0.4
                    
                    results.append({
                        'id': ind.get('id'),
                        'name': ind.get('name'),
                        'source_note': ind.get('sourceNote'),
                        'source_organization': ind.get('sourceOrganization'),
                        'topics': ind.get('topics', []),
                        'relevance_score': relevance
                    })
            
            # Sort by relevance
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            return {
                'search_term': search_term,
                'total_results': len(results),
                'page': page,
                'per_page': per_page,
                'results': results[:per_page],
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to search indicators: {e}")
            raise


class WBCompareCountriesTool(WorldBankBaseTool):
    """
    Tool to compare multiple countries for a specific indicator
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_compare_countries',
            'description': 'Compare multiple countries side-by-side for a specific indicator',
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
                "country_codes": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^[A-Z]{2,3}$"},
                    "minItems": 2,
                    "maxItems": 10
                },
                "indicator": {
                    "type": "string",
                    "enum": list(self.indicator_map.keys())
                },
                "indicator_code": {
                    "type": "string"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "most_recent_year": {
                    "type": "boolean",
                    "default": False
                }
            },
            "required": ["country_codes"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "indicator": {"type": "object"},
                "year_range": {"type": "object"},
                "countries": {"type": "array"},
                "summary": {"type": "object"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_codes = [c.upper() for c in arguments['country_codes']]
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        most_recent = arguments.get('most_recent_year', False)
        
        # Get indicator code
        if indicator and not indicator_code:
            indicator_code = self.indicator_map.get(indicator)
            if not indicator_code:
                raise ValueError(f"Unknown indicator: {indicator}")
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' must be provided")
        
        try:
            countries_data = []
            
            # Fetch data for each country
            for country_code in country_codes:
                endpoint = f"country/{country_code}/indicator/{indicator_code}"
                
                params = {'per_page': 100}
                if start_year and end_year:
                    params['date'] = f"{start_year}:{end_year}"
                
                try:
                    data = self._make_request(endpoint, params)
                    
                    if len(data) < 2 or not data[1]:
                        countries_data.append({
                            'country': {
                                'id': country_code,
                                'name': country_code
                            },
                            'data': [],
                            'latest_value': None,
                            'latest_year': None,
                            'average': None,
                            'min': None,
                            'max': None
                        })
                        continue
                    
                    results = data[1]
                    
                    # Format data points
                    data_points = []
                    values = []
                    for item in results:
                        if item.get('value') is not None:
                            year = int(item['date'])
                            value = float(item['value'])
                            data_points.append({
                                'year': year,
                                'value': value
                            })
                            values.append(value)
                    
                    # Sort by year
                    data_points.sort(key=lambda x: x['year'])
                    
                    # Calculate statistics
                    latest = data_points[-1] if data_points else None
                    avg = sum(values) / len(values) if values else None
                    min_val = min(values) if values else None
                    max_val = max(values) if values else None
                    
                    countries_data.append({
                        'country': {
                            'id': country_code,
                            'name': results[0]['country']['value'] if results else country_code
                        },
                        'data': data_points,
                        'latest_value': latest['value'] if latest else None,
                        'latest_year': latest['year'] if latest else None,
                        'average': round(avg, 2) if avg else None,
                        'min': round(min_val, 2) if min_val else None,
                        'max': round(max_val, 2) if max_val else None
                    })
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get data for {country_code}: {e}")
                    countries_data.append({
                        'country': {
                            'id': country_code,
                            'name': country_code
                        },
                        'data': [],
                        'latest_value': None,
                        'latest_year': None,
                        'average': None,
                        'min': None,
                        'max': None
                    })
            
            # Calculate summary
            latest_values = [(c['country']['name'], c['latest_value']) 
                           for c in countries_data if c['latest_value'] is not None]
            
            summary = {}
            if latest_values:
                highest = max(latest_values, key=lambda x: x[1])
                lowest = min(latest_values, key=lambda x: x[1])
                avg_val = sum(v for _, v in latest_values) / len(latest_values)
                
                summary = {
                    'highest_country': {
                        'name': highest[0],
                        'value': highest[1]
                    },
                    'lowest_country': {
                        'name': lowest[0],
                        'value': lowest[1]
                    },
                    'average_across_countries': round(avg_val, 2)
                }
            
            indicator_name = countries_data[0]['data'][0] if countries_data and countries_data[0]['data'] else ''
            
            return {
                'indicator': {
                    'id': indicator_code,
                    'name': indicator_code  # Would need separate call to get full name
                },
                'year_range': {
                    'start': start_year,
                    'end': end_year
                } if start_year else {},
                'countries': countries_data,
                'summary': summary,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to compare countries: {e}")
            raise


class WBGetIncomeLevelsTool(WorldBankBaseTool):
    """
    Tool to retrieve income level classifications
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_income_levels',
            'description': 'Retrieve World Bank income level classifications and metadata',
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
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "total_levels": {"type": "integer"},
                "income_levels": {"type": "array"},
                "descriptions": {"type": "object"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        per_page = arguments.get('per_page', 50)
        
        params = {'per_page': per_page}
        
        try:
            data = self._make_request('incomeLevels', params)
            
            if len(data) < 2:
                return {
                    'total_levels': 0,
                    'income_levels': [],
                    'descriptions': {},
                    'last_updated': datetime.now().isoformat()
                }
            
            levels_data = data[1]
            
            income_levels = []
            for level in levels_data:
                income_levels.append({
                    'id': level.get('id'),
                    'iso2code': level.get('iso2code'),
                    'value': level.get('value')
                })
            
            descriptions = {
                'HIC': 'High Income Countries',
                'UMC': 'Upper Middle Income Countries',
                'LMC': 'Lower Middle Income Countries',
                'LIC': 'Low Income Countries'
            }
            
            return {
                'total_levels': len(income_levels),
                'income_levels': income_levels,
                'descriptions': descriptions,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get income levels: {e}")
            raise


class WBGetLendingTypesTool(WorldBankBaseTool):
    """
    Tool to retrieve lending type classifications
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_lending_types',
            'description': 'Retrieve World Bank lending type classifications and metadata',
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
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "total_types": {"type": "integer"},
                "lending_types": {"type": "array"},
                "descriptions": {"type": "object"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        per_page = arguments.get('per_page', 50)
        
        params = {'per_page': per_page}
        
        try:
            data = self._make_request('lendingTypes', params)
            
            if len(data) < 2:
                return {
                    'total_types': 0,
                    'lending_types': [],
                    'descriptions': {},
                    'last_updated': datetime.now().isoformat()
                }
            
            types_data = data[1]
            
            lending_types = []
            for ltype in types_data:
                lending_types.append({
                    'id': ltype.get('id'),
                    'iso2code': ltype.get('iso2code'),
                    'value': ltype.get('value')
                })
            
            descriptions = {
                'IBD': 'IBRD (International Bank for Reconstruction and Development)',
                'IDB': 'Blend (IBRD and IDA)',
                'IDX': 'IDA (International Development Association)',
                'LNX': 'Not classified'
            }
            
            return {
                'total_types': len(lending_types),
                'lending_types': lending_types,
                'descriptions': descriptions,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get lending types: {e}")
            raise


class WBGetRegionsTool(WorldBankBaseTool):
    """
    Tool to retrieve geographic region classifications
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_regions',
            'description': 'Retrieve World Bank geographic region classifications and metadata',
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
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "total_regions": {"type": "integer"},
                "regions": {"type": "array"},
                "descriptions": {"type": "object"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        per_page = arguments.get('per_page', 50)
        
        params = {'per_page': per_page}
        
        try:
            data = self._make_request('regions', params)
            
            if len(data) < 2:
                return {
                    'total_regions': 0,
                    'regions': [],
                    'descriptions': {},
                    'last_updated': datetime.now().isoformat()
                }
            
            regions_data = data[1]
            
            regions = []
            for region in regions_data:
                regions.append({
                    'id': region.get('id'),
                    'iso2code': region.get('iso2code'),
                    'value': region.get('name'),
                    'code': region.get('code')
                })
            
            descriptions = {
                'EAS': 'East Asia & Pacific',
                'ECS': 'Europe & Central Asia',
                'LCN': 'Latin America & Caribbean',
                'MEA': 'Middle East & North Africa',
                'NAC': 'North America',
                'SAS': 'South Asia',
                'SSF': 'Sub-Saharan Africa',
                'WLD': 'World'
            }
            
            return {
                'total_regions': len(regions),
                'regions': regions,
                'descriptions': descriptions,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get regions: {e}")
            raise


class WBGetTopicIndicatorsTool(WorldBankBaseTool):
    """
    Tool to retrieve indicators by topic
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'wb_get_topic_indicators',
            'description': 'Retrieve all indicators related to a specific topic',
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
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 21
                },
                "per_page": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 100
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["topic_id"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "topic": {"type": "object"},
                "total_indicators": {"type": "integer"},
                "page": {"type": "integer"},
                "per_page": {"type": "integer"},
                "total_pages": {"type": "integer"},
                "indicators": {"type": "array"},
                "last_updated": {"type": "string"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        topic_id = arguments['topic_id']
        per_page = arguments.get('per_page', 100)
        page = arguments.get('page', 1)
        
        params = {
            'per_page': per_page,
            'page': page,
            'topic': topic_id
        }
        
        # Topic names mapping
        topic_names = {
            1: 'Agriculture & Rural Development',
            2: 'Aid Effectiveness',
            3: 'Economy & Growth',
            4: 'Education',
            5: 'Energy & Mining',
            6: 'Environment',
            7: 'Financial Sector',
            8: 'Health',
            9: 'Infrastructure',
            10: 'Social Protection & Labor',
            11: 'Poverty',
            12: 'Private Sector',
            13: 'Public Sector',
            14: 'Science & Technology',
            15: 'Social Development',
            16: 'Urban Development',
            17: 'Gender',
            18: 'Trade',
            19: 'Climate Change',
            20: 'External Debt',
            21: 'Millennium Development Goals'
        }
        
        try:
            data = self._make_request('indicator', params)
            
            if len(data) < 2:
                return {
                    'topic': {
                        'id': topic_id,
                        'name': topic_names.get(topic_id, f'Topic {topic_id}'),
                        'description': ''
                    },
                    'total_indicators': 0,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': 0,
                    'indicators': [],
                    'last_updated': datetime.now().isoformat()
                }
            
            metadata = data[0]
            indicators_data = data[1]
            
            indicators = []
            for ind in indicators_data:
                indicators.append({
                    'id': ind.get('id'),
                    'name': ind.get('name'),
                    'source_note': ind.get('sourceNote'),
                    'source_organization': ind.get('sourceOrganization'),
                    'source': ind.get('source')
                })
            
            return {
                'topic': {
                    'id': topic_id,
                    'name': topic_names.get(topic_id, f'Topic {topic_id}'),
                    'description': f'Indicators related to {topic_names.get(topic_id, "this topic")}'
                },
                'total_indicators': metadata.get('total', len(indicators)),
                'page': metadata.get('page', page),
                'per_page': metadata.get('per_page', per_page),
                'total_pages': metadata.get('pages', 1),
                'indicators': indicators,
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get topic indicators: {e}")
            raise


# Tool registry for easy access
WORLD_BANK_TOOLS = {
    'wb_get_countries': WBGetCountriesTool,
    'wb_get_indicators': WBGetIndicatorsTool,
    'wb_get_country_data': WBGetCountryDataTool,
    'wb_get_indicator_data': WBGetIndicatorDataTool,
    'wb_search_indicators': WBSearchIndicatorsTool,
    'wb_compare_countries': WBCompareCountriesTool,
    'wb_get_income_levels': WBGetIncomeLevelsTool,
    'wb_get_lending_types': WBGetLendingTypesTool,
    'wb_get_regions': WBGetRegionsTool,
    'wb_get_topic_indicators': WBGetTopicIndicatorsTool
}
