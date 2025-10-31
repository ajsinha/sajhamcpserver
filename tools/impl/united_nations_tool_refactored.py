"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
United Nations MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class UnitedNationsBaseTool(BaseMCPTool):
    """
    Base class for United Nations tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize United Nations base tool"""
        super().__init__(config)
        
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
    
    def _fetch_sdg_api(self, endpoint: str) -> List:
        """Fetch data from UN SDG API"""
        try:
            url = f"{self.sdg_url}/{endpoint}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            self.logger.error(f"Failed to fetch from SDG API: {e}")
            raise


class UNGetSDGsTool(UnitedNationsBaseTool):
    """Tool to retrieve list of all Sustainable Development Goals"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_sdgs',
            'description': 'Retrieve list of all 17 UN Sustainable Development Goals',
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
                "include_details": {
                    "type": "boolean",
                    "description": "Include detailed description for each SDG",
                    "default": False
                }
            }
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "sdgs": {
                    "type": "array",
                    "description": "List of all Sustainable Development Goals",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "SDG code (1-17)"
                            },
                            "title": {
                                "type": "string",
                                "description": "SDG title"
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description (if requested)"
                            },
                            "color": {
                                "type": "string",
                                "description": "SDG official color code"
                            },
                            "uri": {
                                "type": "string",
                                "description": "UN SDG API URI"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Total number of SDGs"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get SDGs operation"""
        include_details = arguments.get('include_details', False)
        
        try:
            data = self._fetch_sdg_api('Goal/List')
            
            sdgs = []
            for item in data:
                if isinstance(item, dict):
                    sdg = {
                        'code': item.get('code'),
                        'title': item.get('title'),
                        'color': item.get('colorInfo', {}).get('hex'),
                        'uri': item.get('uri')
                    }
                    
                    if include_details:
                        sdg['description'] = item.get('description', '')
                    
                    sdgs.append(sdg)
            
            return {
                'sdgs': sdgs,
                'count': len(sdgs)
            }
        except Exception as e:
            return {
                'error': str(e),
                'note': 'Failed to retrieve SDG data from UN API'
            }


class UNGetSDGIndicatorsTool(UnitedNationsBaseTool):
    """Tool to retrieve indicators for a specific SDG"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_sdg_indicators',
            'description': 'Retrieve indicators and metrics for a specific Sustainable Development Goal',
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
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code (1-17)",
                    "enum": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17"]
                }
            },
            "required": ["sdg_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code"
                },
                "sdg_title": {
                    "type": "string",
                    "description": "SDG title"
                },
                "indicators": {
                    "type": "array",
                    "description": "List of indicators for this SDG",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Indicator code (e.g., 1.1.1)"
                            },
                            "description": {
                                "type": "string",
                                "description": "Indicator description"
                            },
                            "tier": {
                                "type": "string",
                                "description": "Indicator tier classification"
                            },
                            "uri": {
                                "type": "string",
                                "description": "UN SDG API URI"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of indicators"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get SDG indicators operation"""
        sdg_code = arguments.get('sdg_code')
        
        try:
            data = self._fetch_sdg_api('Indicator/List')
            
            indicators = []
            for item in data:
                if isinstance(item, dict):
                    code = item.get('code', '')
                    
                    # Filter by SDG (indicators start with SDG code)
                    if code.startswith(f"{sdg_code}."):
                        indicators.append({
                            'code': code,
                            'description': item.get('description'),
                            'tier': item.get('tier'),
                            'uri': item.get('uri')
                        })
            
            return {
                'sdg_code': sdg_code,
                'sdg_title': self.sdgs.get(sdg_code),
                'indicators': indicators,
                'count': len(indicators)
            }
        except Exception as e:
            return {
                'sdg_code': sdg_code,
                'error': str(e),
                'note': 'Failed to retrieve SDG indicators from UN API'
            }


class UNGetSDGDataTool(UnitedNationsBaseTool):
    """Tool to retrieve time series data for a specific SDG indicator"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_sdg_data',
            'description': 'Retrieve historical time series data for a specific SDG indicator and country',
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
                "indicator_code": {
                    "type": "string",
                    "description": "SDG indicator code (e.g., '1.1.1', '3.2.1')"
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO3 country code (e.g., 'USA', 'CHN', 'IND'). Optional - omit for global data."
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
            "required": ["indicator_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "indicator_code": {
                    "type": "string",
                    "description": "SDG indicator code"
                },
                "indicator_description": {
                    "type": "string",
                    "description": "Indicator description"
                },
                "country_code": {
                    "type": "string",
                    "description": "Country code (if specified)"
                },
                "country_name": {
                    "type": "string",
                    "description": "Country name (if applicable)"
                },
                "data": {
                    "type": "array",
                    "description": "Time series data points",
                    "items": {
                        "type": "object",
                        "properties": {
                            "year": {
                                "type": "integer",
                                "description": "Year of observation"
                            },
                            "value": {
                                "type": ["number", "null"],
                                "description": "Indicator value"
                            },
                            "unit": {
                                "type": "string",
                                "description": "Unit of measurement"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of data points"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get SDG data operation"""
        indicator_code = arguments.get('indicator_code')
        country_code = arguments.get('country_code')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        
        try:
            # Build API endpoint
            endpoint = f"Indicator/Data"
            params = {'indicator': indicator_code}
            
            if country_code:
                params['areaCode'] = country_code
            if start_year:
                params['startYear'] = start_year
            if end_year:
                params['endYear'] = end_year
            
            url = f"{self.sdg_url}/{endpoint}"
            if params:
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
                            'year': item.get('timePeriodStart'),
                            'value': item.get('value'),
                            'unit': item.get('units')
                        })
                
                return {
                    'indicator_code': indicator_code,
                    'indicator_description': data[0].get('seriesDescription') if data else '',
                    'country_code': country_code,
                    'country_name': data[0].get('geoAreaName') if data and country_code else None,
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


class UNGetSDGTargetsTool(UnitedNationsBaseTool):
    """Tool to retrieve targets for a specific SDG"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_sdg_targets',
            'description': 'Retrieve specific targets for a Sustainable Development Goal',
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
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code (1-17)",
                    "enum": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17"]
                }
            },
            "required": ["sdg_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code"
                },
                "sdg_title": {
                    "type": "string",
                    "description": "SDG title"
                },
                "targets": {
                    "type": "array",
                    "description": "List of targets for this SDG",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Target code (e.g., 1.1, 3.2)"
                            },
                            "title": {
                                "type": "string",
                                "description": "Target title"
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed target description"
                            },
                            "uri": {
                                "type": "string",
                                "description": "UN SDG API URI"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of targets"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get SDG targets operation"""
        sdg_code = arguments.get('sdg_code')
        
        try:
            data = self._fetch_sdg_api('Target/List')
            
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


class UNGetTradeDataTool(UnitedNationsBaseTool):
    """Tool to retrieve UN Comtrade data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_trade_data',
            'description': 'Retrieve bilateral trade data from UN Comtrade database',
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
                "reporter_code": {
                    "type": "string",
                    "description": "Reporter country ISO3 code (e.g., 'USA', 'CHN')"
                },
                "partner_code": {
                    "type": "string",
                    "description": "Partner country ISO3 code or 'all' for world",
                    "default": "all"
                },
                "trade_flow": {
                    "type": "string",
                    "description": "Type of trade flow",
                    "enum": ["export", "import", "re_export", "re_import"],
                    "default": "export"
                },
                "commodity_code": {
                    "type": "string",
                    "description": "HS commodity code or group",
                    "enum": [
                        "all", "agricultural", "mineral", "chemicals", "plastics_rubber",
                        "textiles", "footwear", "metals", "machinery", "vehicles", "optical_instruments"
                    ],
                    "default": "all"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for data retrieval",
                    "minimum": 1962,
                    "maximum": 2030
                }
            },
            "required": ["reporter_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "reporter": {
                    "type": "string",
                    "description": "Reporter country code"
                },
                "partner": {
                    "type": "string",
                    "description": "Partner country code"
                },
                "trade_flow": {
                    "type": "string",
                    "description": "Trade flow type"
                },
                "commodity": {
                    "type": "string",
                    "description": "Commodity classification"
                },
                "year": {
                    "type": "integer",
                    "description": "Data year"
                },
                "data": {
                    "type": "array",
                    "description": "Trade data records",
                    "items": {
                        "type": "object",
                        "properties": {
                            "trade_value": {
                                "type": "number",
                                "description": "Trade value in USD"
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Trade quantity"
                            }
                        }
                    }
                },
                "note": {
                    "type": "string",
                    "description": "API access note"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get trade data operation"""
        reporter_code = arguments.get('reporter_code')
        partner_code = arguments.get('partner_code', 'all')
        trade_flow = arguments.get('trade_flow', 'export')
        commodity_code = arguments.get('commodity_code', 'all')
        year = arguments.get('year', datetime.now().year - 1)
        
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


class UNGetCountryTradeTool(UnitedNationsBaseTool):
    """Tool to retrieve comprehensive trade summary for a country"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_country_trade',
            'description': 'Retrieve comprehensive trade summary (imports and exports) for a specific country',
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
                "country_code": {
                    "type": "string",
                    "description": "ISO3 country code (e.g., 'USA', 'DEU', 'JPN')"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for data retrieval (defaults to previous year)",
                    "minimum": 1962,
                    "maximum": 2030
                }
            },
            "required": ["country_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "country_code": {
                    "type": "string",
                    "description": "Country code"
                },
                "year": {
                    "type": "integer",
                    "description": "Data year"
                },
                "exports": {
                    "type": "object",
                    "description": "Export data summary"
                },
                "imports": {
                    "type": "object",
                    "description": "Import data summary"
                },
                "note": {
                    "type": "string",
                    "description": "Data access note"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get country trade operation"""
        country_code = arguments.get('country_code')
        year = arguments.get('year', datetime.now().year - 1)
        
        return {
            'country_code': country_code,
            'year': year,
            'exports': {
                'total_value': None,
                'top_partners': [],
                'note': 'Requires UN Comtrade authentication'
            },
            'imports': {
                'total_value': None,
                'top_partners': [],
                'note': 'Requires UN Comtrade authentication'
            },
            'note': 'UN Comtrade API requires authentication for full data access.'
        }


class UNGetTradeBalanceTool(UnitedNationsBaseTool):
    """Tool to calculate trade balance between countries"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_trade_balance',
            'description': 'Calculate trade balance (exports minus imports) for a country',
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
                "country_code": {
                    "type": "string",
                    "description": "ISO3 country code"
                },
                "partner_code": {
                    "type": "string",
                    "description": "Partner country code (optional, defaults to 'all' for world)"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for calculation",
                    "minimum": 1962,
                    "maximum": 2030
                }
            },
            "required": ["country_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "country_code": {
                    "type": "string",
                    "description": "Country code"
                },
                "partner_code": {
                    "type": "string",
                    "description": "Partner country code"
                },
                "year": {
                    "type": "integer",
                    "description": "Data year"
                },
                "data": {
                    "type": "object",
                    "properties": {
                        "exports": {
                            "type": ["number", "null"],
                            "description": "Total exports in USD"
                        },
                        "imports": {
                            "type": ["number", "null"],
                            "description": "Total imports in USD"
                        },
                        "balance": {
                            "type": ["number", "null"],
                            "description": "Trade balance (exports - imports)"
                        }
                    }
                },
                "note": {
                    "type": "string",
                    "description": "Data access note"
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute trade balance calculation"""
        country_code = arguments.get('country_code')
        partner_code = arguments.get('partner_code', 'all')
        year = arguments.get('year', datetime.now().year - 1)
        
        return {
            'country_code': country_code,
            'partner_code': partner_code,
            'year': year,
            'note': 'Trade balance calculation requires full Comtrade API access.',
            'data': {
                'exports': None,
                'imports': None,
                'balance': None
            }
        }


class UNCompareCountryTradeTool(UnitedNationsBaseTool):
    """Tool to compare trade data across multiple countries"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_compare_trade',
            'description': 'Compare trade statistics across multiple countries',
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
                "country_codes": {
                    "type": "array",
                    "description": "List of ISO3 country codes to compare (2-10 countries)",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 10
                },
                "trade_flow": {
                    "type": "string",
                    "description": "Trade flow to compare",
                    "enum": ["export", "import", "re_export", "re_import"],
                    "default": "export"
                },
                "year": {
                    "type": "integer",
                    "description": "Year for comparison",
                    "minimum": 1962,
                    "maximum": 2030
                }
            },
            "required": ["country_codes"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "trade_flow": {
                    "type": "string",
                    "description": "Trade flow type"
                },
                "year": {
                    "type": "integer",
                    "description": "Comparison year"
                },
                "countries": {
                    "type": "array",
                    "description": "Trade data for each country",
                    "items": {
                        "type": "object",
                        "properties": {
                            "country_code": {
                                "type": "string"
                            },
                            "total_value": {
                                "type": ["number", "null"]
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute trade comparison"""
        country_codes = arguments.get('country_codes', [])
        trade_flow = arguments.get('trade_flow', 'export')
        year = arguments.get('year', datetime.now().year - 1)
        
        comparison = {
            'trade_flow': trade_flow,
            'year': year,
            'countries': []
        }
        
        for country_code in country_codes:
            comparison['countries'].append({
                'country_code': country_code,
                'total_value': None,
                'note': 'Requires UN Comtrade authentication'
            })
        
        return comparison


class UNGetSDGProgressTool(UnitedNationsBaseTool):
    """Tool to retrieve SDG progress tracking for a country"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'un_get_sdg_progress',
            'description': 'Track country progress towards Sustainable Development Goals',
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
                "country_code": {
                    "type": "string",
                    "description": "ISO3 country code (e.g., 'USA', 'BRA', 'IND')"
                },
                "sdg_code": {
                    "type": "string",
                    "description": "Specific SDG code (optional, omit for overview of all SDGs)",
                    "enum": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17"]
                }
            },
            "required": ["country_code"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema"""
        return {
            "type": "object",
            "properties": {
                "country_code": {
                    "type": "string",
                    "description": "Country code"
                },
                "sdg_code": {
                    "type": "string",
                    "description": "SDG code (if specific goal requested)"
                },
                "sdg_title": {
                    "type": "string",
                    "description": "SDG title (if specific goal requested)"
                },
                "indicators": {
                    "type": "array",
                    "description": "Progress indicators",
                    "items": {
                        "type": "object",
                        "properties": {
                            "indicator_code": {
                                "type": "string"
                            },
                            "description": {
                                "type": "string"
                            },
                            "latest_data": {
                                "type": "object"
                            }
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute SDG progress tracking"""
        country_code = arguments.get('country_code')
        sdg_code = arguments.get('sdg_code')
        
        if sdg_code:
            return {
                'country_code': country_code,
                'sdg_code': sdg_code,
                'sdg_title': self.sdgs.get(sdg_code),
                'indicators': [],
                'note': 'Detailed progress tracking requires multiple API calls'
            }
        else:
            return {
                'country_code': country_code,
                'note': 'Specify sdg_code for detailed progress on a specific goal',
                'available_sdgs': list(self.sdgs.keys())
            }


# Tool registry for easy access
UNITED_NATIONS_TOOLS = {
    'un_get_sdgs': UNGetSDGsTool,
    'un_get_sdg_indicators': UNGetSDGIndicatorsTool,
    'un_get_sdg_data': UNGetSDGDataTool,
    'un_get_sdg_targets': UNGetSDGTargetsTool,
    'un_get_trade_data': UNGetTradeDataTool,
    'un_get_country_trade': UNGetCountryTradeTool,
    'un_get_trade_balance': UNGetTradeBalanceTool,
    'un_compare_trade': UNCompareCountryTradeTool,
    'un_get_sdg_progress': UNGetSDGProgressTool
}
