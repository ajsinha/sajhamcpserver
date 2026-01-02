"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
IMF (International Monetary Fund) MCP Tool Implementation - Refactored with Individual Tools
"""

import json
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL


class IMFBaseTool(BaseMCPTool):
    """
    Base class for IMF tools with shared functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize IMF base tool"""
        super().__init__(config)
        
        # IMF Data API endpoint
        self.api_url = "http://dataservices.imf.org/REST/SDMX_JSON.svc"
        
        # Major IMF Databases
        self.databases = {
            'IFS': 'International Financial Statistics',
            'DOT': 'Direction of Trade Statistics',
            'BOP': 'Balance of Payments',
            'GFSR': 'Global Financial Stability Report',
            'FSI': 'Financial Soundness Indicators',
            'WEO': 'World Economic Outlook',
            'GFSMAB': 'Government Finance Statistics',
            'CDIS': 'Coordinated Direct Investment Survey',
            'CPIS': 'Coordinated Portfolio Investment Survey',
            'WHDREO': 'World Economic Outlook Historical'
        }
        
        # Common IFS indicators
        self.ifs_indicators = {
            'exchange_rate': 'ENDA_XDC_USD_RATE',
            'exchange_rate_avg': 'EREA_XDC_USD_RATE',
            'policy_rate': 'FPOLM_PA',
            'treasury_bill_rate': 'FITB_PA',
            'deposit_rate': 'FDBR_PA',
            'lending_rate': 'FILR_PA',
            'cpi': 'PCPI_IX',
            'core_cpi': 'PCCOR_IX',
            'ppi': 'PPPI_IX',
            'money_supply_m1': 'FM1_XDC',
            'money_supply_m2': 'FM2_XDC',
            'money_supply_m3': 'FM3_XDC',
            'reserve_money': 'FMRM_XDC',
            'international_reserves': 'RAXG_USD',
            'gold_reserves': 'RAFZ_USD',
            'foreign_reserves': 'RAER_USD',
            'gdp_current': 'NGDP_XDC',
            'gdp_constant': 'NGDP_R_XDC',
            'industrial_production': 'PINDUST_IX',
            'exports': 'BXG_FOB_USD',
            'imports': 'BMG_BP6_USD',
            'unemployment_rate': 'LUR_PT',
        }
        
        # WEO indicators
        self.weo_indicators = {
            'gdp_growth': 'NGDP_RPCH',
            'gdp_per_capita': 'NGDPDPC',
            'inflation_avg': 'PCPIPCH',
            'inflation_eop': 'PCPIEPCH',
            'unemployment': 'LUR',
            'current_account': 'BCA_NGDPD',
            'fiscal_balance': 'GGXCNL_NGDP',
            'public_debt': 'GGXWDG_NGDP',
            'exports_volume': 'TXG_RPCH',
            'imports_volume': 'TMG_RPCH',
            'population': 'LP',
        }
        
        # Country codes mapping
        self.common_countries = {
            'US': 'United States',
            'CN': 'China',
            'JP': 'Japan',
            'DE': 'Germany',
            'GB': 'United Kingdom',
            'FR': 'France',
            'IN': 'India',
            'IT': 'Italy',
            'BR': 'Brazil',
            'CA': 'Canada'
        }
    
    def _get_data(
        self,
        database: str,
        country_code: str,
        indicator_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        frequency: str = 'A'
    ) -> Dict:
        """Get data from IMF database"""
        try:
            dimension = f"{frequency}.{country_code}.{indicator_code}"
            url = f"{self.api_url}/CompactData/{database}/{dimension}"
            
            if start_year or end_year:
                start = start_year or 1950
                end = end_year or datetime.now().year
                url += f"?startPeriod={start}&endPeriod={end}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = safe_json_response(response, ENCODINGS_ALL)
                
                compact_data = data.get('CompactData', {})
                dataset = compact_data.get('DataSet', {})
                series = dataset.get('Series', {})
                
                if not series:
                    return {
                        'database': database,
                        'country_code': country_code,
                        'indicator_code': indicator_code,
                        'data': [],
                        'count': 0,
                        'note': 'No data available'
                    }
                
                observations = series.get('Obs', [])
                if not isinstance(observations, list):
                    observations = [observations]
                
                formatted_data = []
                for obs in observations:
                    if isinstance(obs, dict):
                        formatted_data.append({
                            'period': obs.get('@TIME_PERIOD'),
                            'value': float(obs.get('@OBS_VALUE')) if obs.get('@OBS_VALUE') else None
                        })
                
                return {
                    'database': database,
                    'country_code': country_code,
                    'indicator_code': indicator_code,
                    'frequency': frequency,
                    'data': formatted_data,
                    'count': len(formatted_data)
                }
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"Data not found for {country_code}/{indicator_code} in {database}")
            else:
                raise ValueError(f"Failed to get data: HTTP {e.code}")
        except Exception as e:
            self.logger.error(f"Failed to get IMF data: {e}")
            raise ValueError(f"Failed to get IMF data: {str(e)}")


class IMFGetDatabasesTool(IMFBaseTool):
    """Tool to list available IMF databases"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_databases',
            'description': 'List all available IMF databases and their descriptions',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {}
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "databases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "name": {"type": "string"}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        databases_list = []
        for code, name in self.databases.items():
            databases_list.append({'code': code, 'name': name})
        
        return {
            'databases': databases_list,
            'count': len(databases_list)
        }


class IMFGetDataflowsTool(IMFBaseTool):
    """Tool to get dataflows for a specific IMF database"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_dataflows',
            'description': 'Get available dataflows and indicators for a specific IMF database',
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
                "database": {
                    "type": "string",
                    "description": "IMF database code",
                    "enum": list(self.databases.keys()),
                    "default": "IFS"
                }
            },
            "required": ["database"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "dataflows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        database = arguments.get('database', 'IFS')
        
        try:
            url = f"{self.api_url}/Dataflow/{database}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = safe_json_response(response, ENCODINGS_ALL)
                
                structure = data.get('Structure', {})
                dataflows = structure.get('Dataflows', {}).get('Dataflow', [])
                
                formatted_dataflows = []
                if isinstance(dataflows, list):
                    for df in dataflows:
                        formatted_dataflows.append({
                            'id': df.get('@id'),
                            'name': df.get('Name', {}).get('#text')
                        })
                elif isinstance(dataflows, dict):
                    formatted_dataflows.append({
                        'id': dataflows.get('@id'),
                        'name': dataflows.get('Name', {}).get('#text')
                    })
                
                return {
                    'database': database,
                    'dataflows': formatted_dataflows,
                    'count': len(formatted_dataflows)
                }
        except Exception as e:
            self.logger.error(f"Failed to get dataflows: {e}")
            return {
                'database': database,
                'error': str(e),
                'note': 'Failed to retrieve dataflows'
            }


class IMFGetDataTool(IMFBaseTool):
    """Tool to retrieve data from any IMF database"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_data',
            'description': 'Retrieve economic data from any IMF database for a specific country and indicator',
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
                "database": {
                    "type": "string",
                    "description": "IMF database code",
                    "enum": list(self.databases.keys())
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO 2-letter country code"
                },
                "indicator_code": {
                    "type": "string",
                    "description": "IMF indicator code"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "frequency": {
                    "type": "string",
                    "enum": ["A", "Q", "M"],
                    "default": "A",
                    "description": "A=Annual, Q=Quarterly, M=Monthly"
                }
            },
            "required": ["database", "country_code", "indicator_code"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "country_code": {"type": "string"},
                "indicator_code": {"type": "string"},
                "frequency": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "period": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        database = arguments.get('database')
        country_code = arguments.get('country_code')
        indicator_code = arguments.get('indicator_code')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        frequency = arguments.get('frequency', 'A')
        
        return self._get_data(database, country_code, indicator_code, start_year, end_year, frequency)


class IMFGetIFSDataTool(IMFBaseTool):
    """Tool to retrieve International Financial Statistics data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_ifs_data',
            'description': 'Retrieve International Financial Statistics (IFS) data including exchange rates, interest rates, prices, and monetary indicators',
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
                    "description": "ISO 2-letter country code"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common IFS indicator name",
                    "enum": list(self.ifs_indicators.keys())
                },
                "indicator_code": {
                    "type": "string",
                    "description": "IFS indicator code (use if specific code needed)"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "frequency": {
                    "type": "string",
                    "enum": ["A", "Q", "M"],
                    "default": "M",
                    "description": "A=Annual, Q=Quarterly, M=Monthly"
                }
            },
            "required": ["country_code"],
            "oneOf": [
                {"required": ["indicator"]},
                {"required": ["indicator_code"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "country_code": {"type": "string"},
                "indicator_code": {"type": "string"},
                "frequency": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "period": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_code = arguments.get('country_code')
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        
        if indicator and not indicator_code:
            indicator_code = self.ifs_indicators.get(indicator)
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' is required")
        
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        frequency = arguments.get('frequency', 'M')
        
        return self._get_data('IFS', country_code, indicator_code, start_year, end_year, frequency)


class IMFGetWEODataTool(IMFBaseTool):
    """Tool to retrieve World Economic Outlook data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_weo_data',
            'description': 'Retrieve World Economic Outlook (WEO) data including GDP growth, inflation, unemployment, and fiscal indicators',
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
                    "description": "ISO 2-letter country code"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common WEO indicator name",
                    "enum": list(self.weo_indicators.keys())
                },
                "indicator_code": {
                    "type": "string",
                    "description": "WEO indicator code (use if specific code needed)"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                }
            },
            "required": ["country_code"],
            "oneOf": [
                {"required": ["indicator"]},
                {"required": ["indicator_code"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "country_code": {"type": "string"},
                "indicator_code": {"type": "string"},
                "frequency": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "period": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_code = arguments.get('country_code')
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        
        if indicator and not indicator_code:
            indicator_code = self.weo_indicators.get(indicator)
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' is required")
        
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        
        return self._get_data('WEO', country_code, indicator_code, start_year, end_year, 'A')


class IMFGetBOPDataTool(IMFBaseTool):
    """Tool to retrieve Balance of Payments data"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_bop_data',
            'description': 'Retrieve Balance of Payments (BOP) data including trade balance, current account, and capital flows',
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
                    "description": "ISO 2-letter country code"
                },
                "indicator_code": {
                    "type": "string",
                    "description": "BOP indicator code"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "frequency": {
                    "type": "string",
                    "enum": ["A", "Q"],
                    "default": "A",
                    "description": "A=Annual, Q=Quarterly"
                }
            },
            "required": ["country_code", "indicator_code"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "country_code": {"type": "string"},
                "indicator_code": {"type": "string"},
                "frequency": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "period": {"type": "string"},
                            "value": {"type": ["number", "null"]}
                        }
                    }
                },
                "count": {"type": "integer"}
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_code = arguments.get('country_code')
        indicator_code = arguments.get('indicator_code')
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        frequency = arguments.get('frequency', 'A')
        
        return self._get_data('BOP', country_code, indicator_code, start_year, end_year, frequency)


class IMFCompareCountriesTool(IMFBaseTool):
    """Tool to compare economic indicators across multiple countries"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_compare_countries',
            'description': 'Compare economic indicators across multiple countries for cross-country analysis',
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
                    "description": "List of ISO 2-letter country codes (minimum 2)",
                    "items": {"type": "string"},
                    "minItems": 2
                },
                "database": {
                    "type": "string",
                    "description": "IMF database to use",
                    "enum": list(self.databases.keys()),
                    "default": "IFS"
                },
                "indicator": {
                    "type": "string",
                    "description": "Common indicator name"
                },
                "indicator_code": {
                    "type": "string",
                    "description": "Specific indicator code"
                },
                "start_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "end_year": {
                    "type": "integer",
                    "minimum": 1950,
                    "maximum": 2030
                },
                "frequency": {
                    "type": "string",
                    "enum": ["A", "Q", "M"],
                    "default": "A"
                }
            },
            "required": ["country_codes"],
            "oneOf": [
                {"required": ["indicator"]},
                {"required": ["indicator_code"]}
            ]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "database": {"type": "string"},
                "indicator_code": {"type": "string"},
                "frequency": {"type": "string"},
                "countries": {
                    "type": "array",
                    "description": "Data for each country",
                    "items": {
                        "type": "object",
                        "properties": {
                            "country_code": {"type": "string"},
                            "data": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "period": {"type": "string"},
                                        "value": {"type": ["number", "null"]}
                                    }
                                }
                            },
                            "error": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_codes = arguments.get('country_codes', [])
        database = arguments.get('database', 'IFS')
        indicator = arguments.get('indicator')
        indicator_code = arguments.get('indicator_code')
        
        if indicator and not indicator_code:
            if database == 'WEO':
                indicator_code = self.weo_indicators.get(indicator)
            else:
                indicator_code = self.ifs_indicators.get(indicator)
        
        if not indicator_code:
            raise ValueError("Either 'indicator' or 'indicator_code' is required")
        
        start_year = arguments.get('start_year')
        end_year = arguments.get('end_year')
        frequency = arguments.get('frequency', 'A')
        
        comparison = {
            'database': database,
            'indicator_code': indicator_code,
            'frequency': frequency,
            'countries': []
        }
        
        for country_code in country_codes:
            try:
                data = self._get_data(database, country_code, indicator_code, start_year, end_year, frequency)
                comparison['countries'].append(data)
            except Exception as e:
                self.logger.warning(f"Failed to get data for {country_code}: {e}")
                comparison['countries'].append({
                    'country_code': country_code,
                    'error': str(e)
                })
        
        return comparison


class IMFGetCountryProfileTool(IMFBaseTool):
    """Tool to get comprehensive country economic profile"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'imf_get_country_profile',
            'description': 'Get a comprehensive economic profile for a country with key indicators including GDP, inflation, unemployment, and fiscal data',
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
                    "description": "ISO 2-letter country code"
                }
            },
            "required": ["country_code"]
        }
    
    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "country_code": {"type": "string"},
                "country_name": {"type": "string"},
                "indicators": {
                    "type": "object",
                    "description": "Key economic indicators",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "latest_value": {"type": ["number", "null"]},
                            "latest_period": {"type": "string"},
                            "recent_data": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "period": {"type": "string"},
                                        "value": {"type": ["number", "null"]}
                                    }
                                }
                            },
                            "error": {"type": "string"}
                        }
                    }
                }
            }
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country_code = arguments.get('country_code')
        
        profile = {
            'country_code': country_code,
            'country_name': self.common_countries.get(country_code, country_code),
            'indicators': {}
        }
        
        # Key indicators to fetch
        key_indicators = {
            'GDP Growth': ('WEO', 'NGDP_RPCH', 'A'),
            'Inflation': ('WEO', 'PCPIPCH', 'A'),
            'Unemployment': ('WEO', 'LUR', 'A'),
            'Current Account': ('WEO', 'BCA_NGDPD', 'A'),
            'Public Debt': ('WEO', 'GGXWDG_NGDP', 'A')
        }
        
        current_year = datetime.now().year
        start_year = current_year - 5
        
        for name, (db, code, freq) in key_indicators.items():
            try:
                data = self._get_data(db, country_code, code, start_year, current_year, freq)
                if data['data']:
                    latest = data['data'][-1]
                    profile['indicators'][name] = {
                        'code': code,
                        'latest_value': latest['value'],
                        'latest_period': latest['period'],
                        'recent_data': data['data'][-3:] if len(data['data']) >= 3 else data['data']
                    }
            except Exception as e:
                self.logger.warning(f"Failed to get {name} for {country_code}: {e}")
                profile['indicators'][name] = {
                    'code': code,
                    'error': str(e)
                }
        
        return profile


# Tool registry
IMF_TOOLS = {
    'imf_get_databases': IMFGetDatabasesTool,
    'imf_get_dataflows': IMFGetDataflowsTool,
    'imf_get_data': IMFGetDataTool,
    'imf_get_ifs_data': IMFGetIFSDataTool,
    'imf_get_weo_data': IMFGetWEODataTool,
    'imf_get_bop_data': IMFGetBOPDataTool,
    'imf_compare_countries': IMFCompareCountriesTool,
    'imf_get_country_profile': IMFGetCountryProfileTool
}
