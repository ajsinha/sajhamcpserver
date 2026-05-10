"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Alpha Vantage MCP Tools — Stock, Forex, Crypto, Technical Indicators, Economic Data

API: https://www.alphavantage.co/documentation/
Free tier: 25 requests/day. Set ALPHA_VANTAGE_API_KEY in application.yml.
"""

import json, urllib.request, urllib.parse, logging
from typing import Dict, Any
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL

logger = logging.getLogger(__name__)
AV_BASE = "https://www.alphavantage.co/query"

class AVBaseTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = config.get('api_key', '') if config else ''
    def _av_get(self, function, **params):
        params['function'] = function
        params['apikey'] = self.api_key or 'demo'
        url = f"{AV_BASE}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return safe_json_response(resp, ENCODINGS_ALL)
        except Exception as e:
            return {"error": str(e)}
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

# Stock Data (5)
class AVStockQuoteTool(AVBaseTool):
    def execute(self, a): return self._av_get('GLOBAL_QUOTE', symbol=a['symbol'])
class AVStockDailyTool(AVBaseTool):
    def execute(self, a): return self._av_get('TIME_SERIES_DAILY', symbol=a['symbol'], outputsize=a.get('outputsize','compact'))
class AVStockWeeklyTool(AVBaseTool):
    def execute(self, a): return self._av_get('TIME_SERIES_WEEKLY', symbol=a['symbol'])
class AVStockMonthlyTool(AVBaseTool):
    def execute(self, a): return self._av_get('TIME_SERIES_MONTHLY', symbol=a['symbol'])
class AVStockIntradayTool(AVBaseTool):
    def execute(self, a): return self._av_get('TIME_SERIES_INTRADAY', symbol=a['symbol'], interval=a.get('interval','5min'))

# Fundamentals (5)
class AVCompanyOverviewTool(AVBaseTool):
    def execute(self, a): return self._av_get('OVERVIEW', symbol=a['symbol'])
class AVEarningsTool(AVBaseTool):
    def execute(self, a): return self._av_get('EARNINGS', symbol=a['symbol'])
class AVIncomeStatementTool(AVBaseTool):
    def execute(self, a): return self._av_get('INCOME_STATEMENT', symbol=a['symbol'])
class AVBalanceSheetTool(AVBaseTool):
    def execute(self, a): return self._av_get('BALANCE_SHEET', symbol=a['symbol'])
class AVCashFlowTool(AVBaseTool):
    def execute(self, a): return self._av_get('CASH_FLOW', symbol=a['symbol'])

# Technical Indicators (14)
class AVSMATool(AVBaseTool):
    def execute(self, a): return self._av_get('SMA', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',20), series_type='close')
class AVEMATool(AVBaseTool):
    def execute(self, a): return self._av_get('EMA', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',20), series_type='close')
class AVRSITool(AVBaseTool):
    def execute(self, a): return self._av_get('RSI', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',14), series_type='close')
class AVMACDTool(AVBaseTool):
    def execute(self, a): return self._av_get('MACD', symbol=a['symbol'], interval=a.get('interval','daily'), series_type='close')
class AVBBandsTool(AVBaseTool):
    def execute(self, a): return self._av_get('BBANDS', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',20), series_type='close')
class AVStochTool(AVBaseTool):
    def execute(self, a): return self._av_get('STOCH', symbol=a['symbol'], interval=a.get('interval','daily'))
class AVADXTool(AVBaseTool):
    def execute(self, a): return self._av_get('ADX', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',14))
class AVCCITool(AVBaseTool):
    def execute(self, a): return self._av_get('CCI', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',20))
class AVAroonTool(AVBaseTool):
    def execute(self, a): return self._av_get('AROON', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',14))
class AVOBVTool(AVBaseTool):
    def execute(self, a): return self._av_get('OBV', symbol=a['symbol'], interval=a.get('interval','daily'))
class AVATRTool(AVBaseTool):
    def execute(self, a): return self._av_get('ATR', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',14))
class AVWilliamsRTool(AVBaseTool):
    def execute(self, a): return self._av_get('WILLR', symbol=a['symbol'], interval=a.get('interval','daily'), time_period=a.get('time_period',14))
class AVADLineTool(AVBaseTool):
    def execute(self, a): return self._av_get('AD', symbol=a['symbol'], interval=a.get('interval','daily'))
class AVVWAPTool(AVBaseTool):
    def execute(self, a): return self._av_get('VWAP', symbol=a['symbol'], interval=a.get('interval','15min'))

# Forex (3)
class AVForexRateTool(AVBaseTool):
    def execute(self, a): return self._av_get('CURRENCY_EXCHANGE_RATE', from_currency=a.get('from','EUR'), to_currency=a.get('to','USD'))
class AVForexDailyTool(AVBaseTool):
    def execute(self, a): return self._av_get('FX_DAILY', from_symbol=a.get('from','EUR'), to_symbol=a.get('to','USD'))
class AVForexWeeklyTool(AVBaseTool):
    def execute(self, a): return self._av_get('FX_WEEKLY', from_symbol=a.get('from','EUR'), to_symbol=a.get('to','USD'))

# Crypto (2)
class AVCryptoDailyTool(AVBaseTool):
    def execute(self, a): return self._av_get('DIGITAL_CURRENCY_DAILY', symbol=a.get('symbol','BTC'), market=a.get('market','USD'))
class AVCryptoWeeklyTool(AVBaseTool):
    def execute(self, a): return self._av_get('DIGITAL_CURRENCY_WEEKLY', symbol=a.get('symbol','BTC'), market=a.get('market','USD'))

# Economic Indicators (6)
class AVGDPTool(AVBaseTool):
    def execute(self, a): return self._av_get('REAL_GDP', interval=a.get('interval','annual'))
class AVInflationTool(AVBaseTool):
    def execute(self, a): return self._av_get('INFLATION')
class AVUnemploymentTool(AVBaseTool):
    def execute(self, a): return self._av_get('UNEMPLOYMENT')
class AVCPITool(AVBaseTool):
    def execute(self, a): return self._av_get('CPI', interval=a.get('interval','monthly'))
class AVFedFundsRateTool(AVBaseTool):
    def execute(self, a): return self._av_get('FEDERAL_FUNDS_RATE', interval=a.get('interval','monthly'))
class AVTreasuryYieldTool(AVBaseTool):
    def execute(self, a): return self._av_get('TREASURY_YIELD', interval=a.get('interval','monthly'), maturity=a.get('maturity','10year'))
