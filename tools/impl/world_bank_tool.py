"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
World Bank MCP Tool Implementation
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool

class WorldBankTool(BaseMCPTool):
    """
    World Bank API tool for retrieving global development indicators and data
    """
    
    def __init__(self, config: Dict = None):
        """Initialize World Bank tool"""
        default_config = {
            'name': 'world_bank',
            'description': 'Retrieve global development indicators from World Bank',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # World Bank API endpoint
        self.api_url = "https://api.worldbank.org/v2"
        
        # Common indicators
        self.common_indicators = {
            # GDP & Growth
            'gdp': 'NY.GDP.MKTP.CD',  # GDP (current US$)
            'gdp_per_capita': 'NY.GDP.PCAP.CD',  # GDP per capita (current US$)
            'gdp_growth': 'NY.GDP.MKTP.KD.ZG',  # GDP growth (annual %)
            'gdp_ppp': 'NY.GDP.MKTP.PP.CD',  # GDP, PPP (current international $)
            
            # Population
            'population': 'SP.POP.TOTL',  # Population, total
            'population_growth': 'SP.POP.GROW',  # Population growth (annual %)
            'urban_population': 'SP.URB.TOTL.IN.ZS',  # Urban population (% of total)
            'life_expectancy': 'SP.DYN.LE00.IN',  # Life expectancy at birth
            'birth_rate': 'SP.DYN.CBRT.IN',  # Birth rate (per 1,000 people)
            'death_rate': 'SP.DYN.CDRT.IN',  # Death rate (per 1,000 people)
            
            # Poverty & Inequality
            'poverty_rate': 'SI.POV.DDAY',  # Poverty headcount ratio at $2.15/day
            'gini_index': 'SI.POV.GINI',  # Gini index
            'income_share_lowest_20': 'SI.DST.FRST.20',  # Income share held by lowest 20%
            
            # Education
            'literacy_rate': 'SE.ADT.LITR.ZS',  # Literacy rate, adult total
            'primary_enrollment': 'SE.PRM.ENRR',  # School enrollment, primary
            'secondary_enrollment': 'SE.SEC.ENRR',  # School enrollment, secondary
            'tertiary_enrollment': 'SE.TER.ENRR',  # School enrollment, tertiary
            
            # Health
            'infant_mortality': 'SP.DYN.IMRT.IN',  # Infant mortality rate
            'maternal_mortality': 'SH.STA.MMRT',  # Maternal mortality ratio
            'health_expenditure': 'SH.XPD.CHEX.GD.ZS',  # Current health expenditure (% of GDP)
            'hospital_beds': 'SH.MED.BEDS.ZS',  # Hospital beds (per 1,000 people)
            
            # Employment & Labor
            'unemployment': 'SL.UEM.TOTL.ZS',  # Unemployment, total (% of labor force)
            'labor_force': 'SL.TLF.TOTL.IN',  # Labor force, total
            'female_labor_force': 'SL.TLF.CACT.FE.ZS',  # Female labor force participation
            
            # Trade & Finance
            'exports': 'NE.EXP.GNFS.CD',  # Exports of goods and services (current US$)
            'imports': 'NE.IMP.GNFS.CD',  # Imports of goods and services (current US$)
            'trade_gdp': 'NE.TRD.GNFS.ZS',  # Trade (% of GDP)
            'fdi_inflow': 'BX.KLT.DINV.CD.WD',  # Foreign direct investment, net inflows
            'external_debt': 'DT.DOD.DECT.CD',  # External debt stocks, total
            
            # Energy & Environment
            'co2_emissions': 'EN.ATM.CO2E.KT',  # CO2 emissions (kt)
            'co2_per_capita': 'EN.ATM.CO2E.PC',  # CO2 emissions (metric tons per capita)
            'renewable_energy': 'EG.FEC.RNEW.ZS',  # Renewable energy consumption
            'electricity_access': 'EG.ELC.ACCS.ZS',  # Access to electricity (% of population)
            'forest_area': 'AG.LND.FRST.ZS',  # Forest area (% of land area)
            
            # Infrastructure
            'internet_users': 'IT.NET.USER.ZS',  # Individuals using the Internet (% of population)
            'mobile_subscriptions': 'IT.CEL.SETS.P2',  # Mobile cellular subscriptions (per 100 people)
            'roads_paved': 'IS.ROD.PVED.ZS',  # Roads, paved (% of total roads)
            
            # Inflation & Prices
            'inflation': 'FP.CPI.TOTL.ZG',  # Inflation, consumer prices (annual %)
            'food_price_inflation': 'FP.CPI.FOOD.ZG',  # Food price inflation (annual %)
        }
        
        # Region codes
        self.regions = {
            'EAS': 'East Asia & Pacific',
            'ECS': 'Europe & Central Asia',
            'LCN': 'Latin America & Caribbean',
            'MEA': 'Middle East & North Africa',
            'NAC': 'North America',
            'SAS': 'South Asia',
            'SSF': 'Sub-Saharan Africa',
            'WLD': 'World'
        }
        
        # Income level codes
        self.income_levels = {
            'HIC': 'High income',
            'UMC': 'Upper middle income',
            'LMC': 'Lower middle income',
            'LIC': 'Low income'
        }
    
    def get_input_schema(self) -> Dict:
        """Get input schema for World Bank tool"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "get_countries",
                        "get_indicators",
                        "get_country_data",
                        "get_indicator_data",
                        "search_indicators",
                        "get_income_levels",
                        "get_lending_types",
                        "get_regions",
                        "compare_countries",
                        "get_topic_indicators"
                    ]
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO2 or ISO3 country code (e.g., US, USA, CHN)"
                },
                "country_codes": {
                    "type": "array",
                    "description": "List of country codes for comparison",
                    "items": {"type": "string"}
                },
                "indicator_code": {
                    "type": "string",
                    "description": "World Bank indicator code"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator name",
                    "enum": list(self.common_indicators.keys())
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year for data retrieval",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year for data retrieval",
                    "minimum": 1960,
                    "maximum": 2030
                },
                "per_page": {
                    "type": "integer",
                    "description": "Number of results per page",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 1000
                },
                "search_term": {
                    "type": "string",
                    "description": "Search term for indicators"
                },
                "income_level": {
                    "type": "string",
                    "description": "Income level code",
                    "enum": list(self.income_levels.keys())
                },
                "region": {
                    "type": "string",
                    "description": "Region code",
                    "enum": list(self.regions.keys())
                },
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID for indicators (1-21)",
                    "minimum": 1,
                    "maximum": 21
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute World Bank tool
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Development indicators and data from World Bank
        """
        action = arguments.get('action')
        
        if action == 'get_countries':
            per_page = arguments.get('per_page', 300)
            income_level = arguments.get('income_level')
            region = arguments.get('region')
            return self._get_countries(per_page, income_level, region)
            
        elif action == 'get_indicators':
            per_page = arguments.get('per_page', 100)
            return self._get_indicators(per_page)
            
        elif action == 'get_country_data':
            country_code = arguments.get('country_code')
            if not country_code:
                raise ValueError("'country_code' is required")
            return self._get_country_data(country_code)
            
        elif action == 'get_indicator_data':
            country_code = arguments.get('country_code')
            indicator_code = arguments.get('indicator_code')
            indicator = arguments.get('indicator')
            
            if not country_code:
                raise ValueError("'country_code' is required")
            
            if indicator and not indicator_code:
                indicator_code = self.common_indicators.get(indicator)
            
            if not indicator_code:
                raise ValueError("Either 'indicator_code' or 'indicator' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            
            return self._get_indicator_data(country_code, indicator_code, start_year, end_year)
            
        elif action == 'search_indicators':
            search_term = arguments.get('search_term')
            if not search_term:
                raise ValueError("'search_term' is required")
            per_page = arguments.get('per_page', 50)
            return self._search_indicators(search_term, per_page)
            
        elif action == 'get_income_levels':
            return self._get_income_levels()
            
        elif action == 'get_lending_types':
            return self._get_lending_types()
            
        elif action == 'get_regions':
            return self._get_regions()
            
        elif action == 'compare_countries':
            country_codes = arguments.get('country_codes', [])
            indicator_code = arguments.get('indicator_code')
            indicator = arguments.get('indicator')
            
            if not country_codes or len(country_codes) < 2:
                raise ValueError("At least 2 country codes required in 'country_codes'")
            
            if indicator and not indicator_code:
                indicator_code = self.common_indicators.get(indicator)
            
            if not indicator_code:
                raise ValueError("Either 'indicator_code' or 'indicator' is required")
            
            start_year = arguments.get('start_year')
            end_year = arguments.get('end_year')
            
            return self._compare_countries(country_codes, indicator_code, start_year, end_year)
            
        elif action == 'get_topic_indicators':
            topic_id = arguments.get('topic_id')
            if not topic_id:
                raise ValueError("'topic_id' is required")
            per_page = arguments.get('per_page', 100)
            return self._get_topic_indicators(topic_id, per_page)
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Any:
        """
        Make request to World Bank API
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            
        Returns:
            API response data
        """
        url = f"{self.api_url}/{endpoint}"
        
        # Add format parameter
        if params is None:
            params = {}
        params['format'] = 'json'
        params['per_page'] = params.get('per_page', 1000)
        
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
                
                # World Bank API returns array with metadata and data
                if isinstance(data, list) and len(data) > 1:
                    return data[1]  # Return the data portion
                return data
                
        except urllib.error.HTTPError as e:
            self.logger.error(f"World Bank API error: {e}")
            raise ValueError(f"Failed to fetch data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"World Bank API error: {e}")
            raise ValueError(f"Failed to fetch data: {str(e)}")
    
    def _get_countries(self, per_page: int = 300, income_level: str = None, region: str = None) -> Dict:
        """
        Get list of countries
        
        Args:
            per_page: Number of results per page
            income_level: Filter by income level
            region: Filter by region
            
        Returns:
            List of countries
        """
        params = {'per_page': per_page}
        
        if income_level:
            endpoint = f"incomelevel/{income_level}/country"
        elif region:
            endpoint = f"region/{region}/country"
        else:
            endpoint = "country"
        
        countries = self._make_request(endpoint, params)
        
        if not countries:
            return {'countries': [], 'count': 0}
        
        formatted_countries = []
        for country in countries:
            if isinstance(country, dict):
                formatted_countries.append({
                    'id': country.get('id'),
                    'iso2Code': country.get('iso2Code'),
                    'name': country.get('name'),
                    'region': country.get('region', {}).get('value') if isinstance(country.get('region'), dict) else None,
                    'income_level': country.get('incomeLevel', {}).get('value') if isinstance(country.get('incomeLevel'), dict) else None,
                    'capital_city': country.get('capitalCity'),
                    'longitude': country.get('longitude'),
                    'latitude': country.get('latitude')
                })
        
        return {
            'countries': formatted_countries,
            'count': len(formatted_countries)
        }
    
    def _get_indicators(self, per_page: int = 100) -> Dict:
        """
        Get list of indicators
        
        Args:
            per_page: Number of results per page
            
        Returns:
            List of indicators
        """
        params = {'per_page': per_page}
        indicators = self._make_request("indicator", params)
        
        if not indicators:
            return {'indicators': [], 'count': 0}
        
        formatted_indicators = []
        for indicator in indicators:
            if isinstance(indicator, dict):
                formatted_indicators.append({
                    'id': indicator.get('id'),
                    'name': indicator.get('name'),
                    'source': indicator.get('source', {}).get('value') if isinstance(indicator.get('source'), dict) else None,
                    'unit': indicator.get('unit'),
                    'sourceOrganization': indicator.get('sourceOrganization')
                })
        
        return {
            'indicators': formatted_indicators,
            'count': len(formatted_indicators),
            'note': f'Showing first {per_page} indicators. Use search_indicators for specific topics.'
        }
    
    def _get_country_data(self, country_code: str) -> Dict:
        """
        Get country information
        
        Args:
            country_code: Country code
            
        Returns:
            Country information
        """
        countries = self._make_request(f"country/{country_code}")
        
        if not countries or len(countries) == 0:
            raise ValueError(f"Country not found: {country_code}")
        
        country = countries[0] if isinstance(countries, list) else countries
        
        return {
            'id': country.get('id'),
            'iso2Code': country.get('iso2Code'),
            'name': country.get('name'),
            'region': country.get('region', {}).get('value') if isinstance(country.get('region'), dict) else None,
            'income_level': country.get('incomeLevel', {}).get('value') if isinstance(country.get('incomeLevel'), dict) else None,
            'lending_type': country.get('lendingType', {}).get('value') if isinstance(country.get('lendingType'), dict) else None,
            'capital_city': country.get('capitalCity'),
            'longitude': country.get('longitude'),
            'latitude': country.get('latitude')
        }
    
    def _get_indicator_data(
        self,
        country_code: str,
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> Dict:
        """
        Get indicator data for a country
        
        Args:
            country_code: Country code
            indicator_code: Indicator code
            start_year: Start year
            end_year: End year
            
        Returns:
            Indicator data
        """
        params = {'per_page': 1000}
        
        if start_year and end_year:
            params['date'] = f"{start_year}:{end_year}"
        elif start_year:
            params['date'] = f"{start_year}:{datetime.now().year}"
        elif end_year:
            params['date'] = f"1960:{end_year}"
        
        endpoint = f"country/{country_code}/indicator/{indicator_code}"
        data = self._make_request(endpoint, params)
        
        if not data:
            return {
                'country_code': country_code,
                'indicator_code': indicator_code,
                'data': [],
                'count': 0
            }
        
        formatted_data = []
        for item in data:
            if isinstance(item, dict) and item.get('value') is not None:
                formatted_data.append({
                    'year': item.get('date'),
                    'value': item.get('value'),
                    'country': item.get('country', {}).get('value') if isinstance(item.get('country'), dict) else None
                })
        
        # Sort by year descending
        formatted_data.sort(key=lambda x: x['year'], reverse=True)
        
        return {
            'country_code': country_code,
            'indicator_code': indicator_code,
            'indicator_name': data[0].get('indicator', {}).get('value') if data and isinstance(data[0], dict) else None,
            'data': formatted_data,
            'count': len(formatted_data)
        }
    
    def _search_indicators(self, search_term: str, per_page: int = 50) -> Dict:
        """
        Search for indicators
        
        Args:
            search_term: Search term
            per_page: Number of results per page
            
        Returns:
            Matching indicators
        """
        # Get all indicators and filter locally
        indicators = self._get_indicators(per_page=1000)
        
        search_lower = search_term.lower()
        matches = []
        
        for indicator in indicators['indicators']:
            name = indicator.get('name', '').lower()
            source_org = indicator.get('sourceOrganization', '').lower()
            
            if search_lower in name or search_lower in source_org:
                matches.append(indicator)
                if len(matches) >= per_page:
                    break
        
        return {
            'search_term': search_term,
            'matches': matches,
            'count': len(matches)
        }
    
    def _get_income_levels(self) -> Dict:
        """Get list of income levels"""
        levels = self._make_request("incomelevel")
        
        formatted_levels = []
        for level in levels:
            if isinstance(level, dict):
                formatted_levels.append({
                    'id': level.get('id'),
                    'code': level.get('iso2code'),
                    'value': level.get('value')
                })
        
        return {
            'income_levels': formatted_levels,
            'count': len(formatted_levels)
        }
    
    def _get_lending_types(self) -> Dict:
        """Get list of lending types"""
        types = self._make_request("lendingtype")
        
        formatted_types = []
        for lending_type in types:
            if isinstance(lending_type, dict):
                formatted_types.append({
                    'id': lending_type.get('id'),
                    'code': lending_type.get('iso2code'),
                    'value': lending_type.get('value')
                })
        
        return {
            'lending_types': formatted_types,
            'count': len(formatted_types)
        }
    
    def _get_regions(self) -> Dict:
        """Get list of regions"""
        regions = self._make_request("region")
        
        formatted_regions = []
        for region in regions:
            if isinstance(region, dict):
                formatted_regions.append({
                    'id': region.get('id'),
                    'code': region.get('code'),
                    'name': region.get('name')
                })
        
        return {
            'regions': formatted_regions,
            'count': len(formatted_regions)
        }
    
    def _compare_countries(
        self,
        country_codes: List[str],
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> Dict:
        """
        Compare indicator data across multiple countries
        
        Args:
            country_codes: List of country codes
            indicator_code: Indicator code
            start_year: Start year
            end_year: End year
            
        Returns:
            Comparison data
        """
        comparison = {
            'indicator_code': indicator_code,
            'countries': []
        }
        
        for country_code in country_codes:
            try:
                data = self._get_indicator_data(country_code, indicator_code, start_year, end_year)
                comparison['countries'].append(data)
            except Exception as e:
                self.logger.warning(f"Failed to get data for {country_code}: {e}")
                comparison['countries'].append({
                    'country_code': country_code,
                    'error': str(e)
                })
        
        return comparison
    
    def _get_topic_indicators(self, topic_id: int, per_page: int = 100) -> Dict:
        """
        Get indicators for a specific topic
        
        Args:
            topic_id: Topic ID
            per_page: Number of results per page
            
        Returns:
            Topic indicators
        """
        params = {'per_page': per_page}
        endpoint = f"topic/{topic_id}/indicator"
        indicators = self._make_request(endpoint, params)
        
        if not indicators:
            return {'indicators': [], 'count': 0}
        
        formatted_indicators = []
        for indicator in indicators:
            if isinstance(indicator, dict):
                formatted_indicators.append({
                    'id': indicator.get('id'),
                    'name': indicator.get('name'),
                    'source': indicator.get('source', {}).get('value') if isinstance(indicator.get('source'), dict) else None,
                    'unit': indicator.get('unit')
                })
        
        return {
            'topic_id': topic_id,
            'indicators': formatted_indicators,
            'count': len(formatted_indicators)
        }
