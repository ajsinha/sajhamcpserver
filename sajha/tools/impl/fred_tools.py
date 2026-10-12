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
from sajha.tools.impl.fred_key import fred_api_key
from sajha.core import outbound

logger = logging.getLogger(__name__)
FRED_BASE = "https://api.stlouisfed.org/fred"

class FREDBaseTool(BaseMCPTool):
    #: limit used when neither the call nor the tool's schema gives one
    DEFAULT_LIMIT = 30

    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = config.get('api_key', '') if config else ''

    def _fred_get(self, endpoint, **params):
        # No key: a configuration error that names FRED_API_KEY (sajha/tools/impl/fred_key.py)
        params['api_key'] = fred_api_key(self.config)
        params['file_type'] = 'json'
        url = f"{FRED_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url)
            with outbound.urlopen(req, timeout=30) as resp:
                return safe_json_response(resp, ENCODINGS_ALL)
        except Exception as e:
            return {"error": str(e)}

    def _schema_default(self, name):
        return ((self._input_schema or {}).get('properties') or {}).get(name, {}).get('default')

    def _limit(self, a):
        """The call's limit, else the schema default (what the client was told), else 30."""
        return a.get('limit') or self._schema_default('limit') or self.DEFAULT_LIMIT

    def _series(self, series_id, **extra):
        """The most recent observations of a series, newest first.

        Every FRED tool here means "the latest N observations": FRED's own default is
        ascending order, where ``limit`` would return the *oldest* N (GDP from 1947).
        """
        params = {'series_id': series_id, 'sort_order': 'desc'}
        params.update(extra)
        return self._fred_get('series/observations', **params)
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

# Each tool fetches a specific well-known FRED series
class FREDGDPTool(FREDBaseTool):
    def execute(self, a): return {"series": "GDP", "data": self._series('GDP', limit=self._limit(a))}
class FREDGDPGrowthTool(FREDBaseTool):
    def execute(self, a): return {"series": "A191RL1Q225SBEA", "data": self._series('A191RL1Q225SBEA', limit=self._limit(a))}
class FREDUnemploymentTool(FREDBaseTool):
    def execute(self, a): return {"series": "UNRATE", "data": self._series('UNRATE', limit=self._limit(a))}
class FREDCPITool(FREDBaseTool):
    def execute(self, a): return {"series": "CPIAUCSL", "data": self._series('CPIAUCSL', limit=self._limit(a))}
class FREDPCETool(FREDBaseTool):
    def execute(self, a): return {"series": "PCE", "data": self._series('PCE', limit=self._limit(a))}
class FREDFedFundsRateTool(FREDBaseTool):
    def execute(self, a): return {"series": "FEDFUNDS", "data": self._series('FEDFUNDS', limit=self._limit(a))}
class FREDPrimeRateTool(FREDBaseTool):
    def execute(self, a): return {"series": "DPRIME", "data": self._series('DPRIME', limit=self._limit(a))}
class FRED10YTreasuryTool(FREDBaseTool):
    def execute(self, a): return {"series": "DGS10", "data": self._series('DGS10', limit=self._limit(a))}
class FRED2YTreasuryTool(FREDBaseTool):
    def execute(self, a): return {"series": "DGS2", "data": self._series('DGS2', limit=self._limit(a))}
class FRED30YMortgageTool(FREDBaseTool):
    def execute(self, a): return {"series": "MORTGAGE30US", "data": self._series('MORTGAGE30US', limit=self._limit(a))}
class FREDHousingStartsTool(FREDBaseTool):
    def execute(self, a): return {"series": "HOUST", "data": self._series('HOUST', limit=self._limit(a))}
class FREDBuildingPermitsTool(FREDBaseTool):
    def execute(self, a): return {"series": "PERMIT", "data": self._series('PERMIT', limit=self._limit(a))}
class FREDExistingHomeSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "EXHOSLUSM495S", "data": self._series('EXHOSLUSM495S', limit=self._limit(a))}
class FREDNewHomeSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "HSN1F", "data": self._series('HSN1F', limit=self._limit(a))}
class FREDIndustrialProductionTool(FREDBaseTool):
    def execute(self, a): return {"series": "INDPRO", "data": self._series('INDPRO', limit=self._limit(a))}
class FREDCapacityUtilizationTool(FREDBaseTool):
    def execute(self, a): return {"series": "TCU", "data": self._series('TCU', limit=self._limit(a))}
class FREDRetailSalesTool(FREDBaseTool):
    def execute(self, a): return {"series": "RSAFS", "data": self._series('RSAFS', limit=self._limit(a))}
class FREDPersonalIncomeTool(FREDBaseTool):
    def execute(self, a): return {"series": "PI", "data": self._series('PI', limit=self._limit(a))}
class FREDConsumerSentimentTool(FREDBaseTool):
    def execute(self, a): return {"series": "UMCSENT", "data": self._series('UMCSENT', limit=self._limit(a))}
class FREDPMITool(FREDBaseTool):
    def execute(self, a): return {"series": "MANEMP", "data": self._series('MANEMP', limit=self._limit(a))}
class FREDInitialClaimsTool(FREDBaseTool):
    def execute(self, a): return {"series": "ICSA", "data": self._series('ICSA', limit=self._limit(a))}
class FREDContinuingClaimsTool(FREDBaseTool):
    def execute(self, a): return {"series": "CCSA", "data": self._series('CCSA', limit=self._limit(a))}
class FREDM2MoneySupplyTool(FREDBaseTool):
    def execute(self, a): return {"series": "M2SL", "data": self._series('M2SL', limit=self._limit(a))}
class FREDNationalDebtTool(FREDBaseTool):
    def execute(self, a): return {"series": "GFDEBTN", "data": self._series('GFDEBTN', limit=self._limit(a))}
class FREDTradeBalanceTool(FREDBaseTool):
    def execute(self, a): return {"series": "BOPGSTB", "data": self._series('BOPGSTB', limit=self._limit(a))}
class FREDSP500Tool(FREDBaseTool):
    def execute(self, a): return {"series": "SP500", "data": self._series('SP500', limit=self._limit(a))}
class FREDVIXTool(FREDBaseTool):
    def execute(self, a): return {"series": "VIXCLS", "data": self._series('VIXCLS', limit=self._limit(a))}
class FREDDollarIndexTool(FREDBaseTool):
    def execute(self, a): return {"series": "DTWEXBGS", "data": self._series('DTWEXBGS', limit=self._limit(a))}
class FREDOilPriceTool(FREDBaseTool):
    def execute(self, a): return {"series": "DCOILWTICO", "data": self._series('DCOILWTICO', limit=self._limit(a))}
class FREDCustomSeriesTool(FREDBaseTool):
    """Any FRED series by id. The preset tools (fred_5yr_treasury, fred_core_cpi, ...) use this class
    with their series as the schema default of series_id, so a call without one reads that series."""
    def execute(self, a):
        series_id = a.get('series_id') or self._schema_default('series_id')
        if not series_id:
            raise ValueError("series_id is required (a FRED series id such as UNRATE)")
        return {"series": series_id, "data": self._series(series_id, limit=self._limit(a))}
