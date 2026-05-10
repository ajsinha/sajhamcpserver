"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
CoinGecko MCP Tools — Cryptocurrency Market Data

API: https://docs.coingecko.com/reference/introduction
Free tier: 30 calls/min. No API key needed for demo endpoints.
"""

import json, urllib.request, urllib.parse, logging
from typing import Dict, Any
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL

logger = logging.getLogger(__name__)
CG_BASE = "https://api.coingecko.com/api/v3"

class CGBaseTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = config.get('api_key', '') if config else ''
    def _cg_get(self, path, **params):
        url = f"{CG_BASE}/{path}"
        if params:
            url += '?' + urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
        headers = {'Accept': 'application/json'}
        if self.api_key:
            headers['x-cg-demo-api-key'] = self.api_key
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"error": str(e)}
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

class CGCoinPriceTool(CGBaseTool):
    def execute(self, a): return self._cg_get('simple/price', ids=a.get('ids','bitcoin'), vs_currencies=a.get('vs','usd'), include_24hr_change='true', include_market_cap='true')
class CGCoinMarketChartTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"coins/{a.get('id','bitcoin')}/market_chart", vs_currency=a.get('vs','usd'), days=a.get('days',30))
class CGCoinOHLCTool(CGBaseTool):
    def execute(self, a): return {"ohlc": self._cg_get(f"coins/{a.get('id','bitcoin')}/ohlc", vs_currency='usd', days=a.get('days',30))}
class CGCoinInfoTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"coins/{a.get('id','bitcoin')}", localization='false', tickers='false', community_data='false', developer_data='false')
class CGCoinHistoryTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"coins/{a.get('id','bitcoin')}/history", date=a['date'])
class CGCoinTickersTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"coins/{a.get('id','bitcoin')}/tickers")
class CGTrendingCoinsTool(CGBaseTool):
    def execute(self, a): return self._cg_get('search/trending')
class CGCoinListTool(CGBaseTool):
    def execute(self, a): return {"coins": self._cg_get('coins/list')}
class CGCoinCategoriesListTool(CGBaseTool):
    def execute(self, a): return {"categories": self._cg_get('coins/categories/list')}
class CGCoinCategoriesMarketTool(CGBaseTool):
    def execute(self, a): return {"categories": self._cg_get('coins/categories')}
class CGMarketGlobalTool(CGBaseTool):
    def execute(self, a): return self._cg_get('global')
class CGDefiGlobalTool(CGBaseTool):
    def execute(self, a): return self._cg_get('global/decentralized_finance_defi')
class CGExchangesListTool(CGBaseTool):
    def execute(self, a): return {"exchanges": self._cg_get('exchanges', per_page=a.get('limit',20))}
class CGExchangeInfoTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"exchanges/{a.get('id','binance')}")
class CGExchangeTickersTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"exchanges/{a.get('id','binance')}/tickers")
class CGNFTListTool(CGBaseTool):
    def execute(self, a): return {"nfts": self._cg_get('nfts/list')}
class CGSearchTool(CGBaseTool):
    def execute(self, a): return self._cg_get('search', query=a['query'])
class CGAssetPlatformsTool(CGBaseTool):
    def execute(self, a): return {"platforms": self._cg_get('asset_platforms')}
class CGCoinMarketsTool(CGBaseTool):
    def execute(self, a): return {"coins": self._cg_get('coins/markets', vs_currency='usd', order=a.get('order','market_cap_desc'), per_page=a.get('limit',50))}
class CGTopGainersTool(CGBaseTool):
    def execute(self, a): return {"coins": self._cg_get('coins/markets', vs_currency='usd', order='percent_change_24h_desc', per_page=20)}
class CGTopLosersTool(CGBaseTool):
    def execute(self, a): return {"coins": self._cg_get('coins/markets', vs_currency='usd', order='percent_change_24h_asc', per_page=20)}
class CGDerivativesTool(CGBaseTool):
    def execute(self, a): return {"derivatives": self._cg_get('derivatives')}
class CGDerivativesExchangesTool(CGBaseTool):
    def execute(self, a): return {"exchanges": self._cg_get('derivatives/exchanges')}
class CGExchangeRatesTool(CGBaseTool):
    def execute(self, a): return self._cg_get('exchange_rates')
class CGCompaniesHoldingsTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"companies/public_treasury/{a.get('coin_id','bitcoin')}")
