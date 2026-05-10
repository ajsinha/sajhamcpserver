"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
FRED (Federal Reserve Economic Data) MCP Tools

API: https://fred.stlouisfed.org/docs/api/
Free API key at: https://fred.stlouisfed.org/docs/api/api_key.html
"""

import json, urllib.request, urllib.parse, logging
from typing import Dict, Any
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL

logger = logging.getLogger(__name__)
FRED_BASE = "https://api.stlouisfed.org/fred"

class FREDBaseTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = config.get('api_key', '') if config else ''
    def _fred_get(self, endpoint, **params):
        params['api_key'] = self.api_key or 'DEMO_KEY'
        params['file_type'] = 'json'
        url = f"{FRED_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return safe_json_response(resp, ENCODINGS_ALL)
        except Exception as e:
            return {"error": str(e)}
    def _series(self, series_id, **extra):
        params = {'series_id': series_id}
        params.update(extra)
        return self._fred_get('series/observations', **params)
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

# Each tool fetches a specific well-known FRED series
class FREDGDPTool(FREDBaseTool):
    def execute(self, a): return {"series": "GDP", "data": self._series('GDP', limit=a.get('limit',40))}
class FREDGDPGrowthTool(FREDBaseTool):
    def execute(self, a): return {"series": "A191RL1Q225SBEA", "data": self._series('A191RL1Q225SBEA', limit=a.get('limit',40))}
class FREDUnemploymentTool(FREDBaseTool):
    def execute(self, a): return {"series": "UNRATE", "data": self._series('UNRATE', limit=a.get('limit',60))}
class FREDCPITool(FREDBaseTool):
    def execute(self, a): return {"series": "CPIAUCSL", "data": self._series('CPIAUCSL', limit=a.get('limit',60))}
class FREDPCETool(FREDBaseTool):
    def execute(self, a): return {"series": "PCE", "data": self._series('PCE', limit=a.get('limit',60))}
class FREDFedFundsRateTool(FREDBaseTool):
    def execute(self, a): return {"series": "FEDFUNDS", "data": self._series('FEDFUNDS', limit=a.get('limit',60))}
class FREDPrimeRateTool(FREDBaseTool):
    def execute(self, a): return {"series": "DPRIME", "data": self._series('DPRIME', limit=a.get('limit',60))}
class FRED10YTreasuryTool(FREDBaseTool):
    def execute(self, a): return {"series": "DGS10", "data": self._series('DGS10', limit=a.get('limit',60))}
class FRED2YTreasuryTool(FREDBaseTool):
    def execute(self, a): return {"series": "DGS2", "data": self._series('DGS2', limit=a.get('limit',60))}
class FRED30YMortgageTool(FREDBaseTool):
    def execute(self, a): return {"series": "MORTGAGE30US", "data": self._series('MORTGAGE30US', limit=a.get('limit',60))}
class FREDHousingStartsTool(FREDBaseTool):
    def execute(self, a): return {"series": "HOUST", "data": self._series('HOUST', limit=a.get('limit',60))}
class FREDBuildingPermitsTool(FREDBaseTool):
    def execute(self, a): return {"series": "PERMIT", "data": self._series('PERMIT', limit=a.get('limit',60))}
class FREDExistingHomeSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "EXHOSLUSM495S", "data": self._series('EXHOSLUSM495S', limit=a.get('limit',60))}
class FREDNewHomeSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "HSN1F", "data": self._series('HSN1F', limit=a.get('limit',60))}
class FREDIndustrialProductionTool(FREDBaseTool):
    def execute(self, a): return {"series": "INDPRO", "data": self._series('INDPRO', limit=a.get('limit',60))}
class FREDCapacityUtilizationTool(FREDBaseTool):
    def execute(self, a): return {"series": "TCU", "data": self._series('TCU', limit=a.get('limit',60))}
class FREDRetailSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "RSAFS", "data": self._series('RSAFS', limit=a.get('limit',60))}
class FREDPersonalIncomeTool(FREDBaseTool):
    def execute(self, a): return {"series": "PI", "data": self._series('PI', limit=a.get('limit',60))}
class FREDConsumerSentimentTool(FREDBaseTool):
    def execute(self, a): return {"series": "UMCSENT", "data": self._series('UMCSENT', limit=a.get('limit',60))}
class FREDPMITool(FREDBaseTool):
    def execute(self, a): return {"series": "MANEMP", "data": self._series('MANEMP', limit=a.get('limit',60))}
class FREDInitialClaimsTool(FREDBaseTool):
    def execute(self, a): return {"series": "ICSA", "data": self._series('ICSA', limit=a.get('limit',60))}
class FREDContinuingClaimsTool(FREDBaseTool):
    def execute(self, a): return {"series": "CCSA", "data": self._series('CCSA', limit=a.get('limit',60))}
class FREDM2MoneySupplyTool(FREDBaseTool):
    def execute(self, a): return {"series": "M2SL", "data": self._series('M2SL', limit=a.get('limit',60))}
class FREDNationalDebtTool(FREDBaseTool):
    def execute(self, a): return {"series": "GFDEBTN", "data": self._series('GFDEBTN', limit=a.get('limit',40))}
class FREDTradeBalanceTool(FREDBaseTool):
    def execute(self, a): return {"series": "BOPGSTB", "data": self._series('BOPGSTB', limit=a.get('limit',60))}
class FREDSP500Tool(FREDBaseTool):
    def execute(self, a): return {"series": "SP500", "data": self._series('SP500', limit=a.get('limit',60))}
class FREDVIXTool(FREDBaseTool):
    def execute(self, a): return {"series": "VIXCLS", "data": self._series('VIXCLS', limit=a.get('limit',60))}
class FREDDollarIndexTool(FREDBaseTool):
    def execute(self, a): return {"series": "DTWEXBGS", "data": self._series('DTWEXBGS', limit=a.get('limit',60))}
class FREDOilPriceTool(FREDBaseTool):
    def execute(self, a): return {"series": "DCOILWTICO", "data": self._series('DCOILWTICO', limit=a.get('limit',60))}
class FREDCustomSeriesTool(FREDBaseTool):
    """Fetch any FRED series by ID — the universal tool for 800,000+ data series."""
    def execute(self, a): return {"series": a['series_id'], "data": self._series(a['series_id'], limit=a.get('limit',60))}
