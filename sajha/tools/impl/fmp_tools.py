"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Financial Modeling Prep (FMP) MCP Tool Implementations

FMP API Base URL: https://financialmodelingprep.com/stable
Docs: https://site.financialmodelingprep.com/developer/docs

All tools use the /stable/ endpoint format (FMP's current standard).
Requires FMP_API_KEY configured in application.yml.
"""

import json
import urllib.parse
import urllib.request
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"


class FMPBaseTool(BaseMCPTool):
    """Base class for all FMP tools — handles API key, HTTP requests, error handling."""

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.api_key = config.get('api_key', '') if config else ''
        self.demo_mode = not self.api_key

    def _fmp_get(self, endpoint: str, params: Dict = None) -> Any:
        """Make a GET request to FMP API."""
        params = params or {}
        params['apikey'] = self.api_key

        url = f"{FMP_BASE_URL}/{endpoint}"
        if params:
            url += '?' + urllib.parse.urlencode(params)

        if self.demo_mode:
            return self._demo_response(endpoint, params)

        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as response:
                return safe_json_response(response, ENCODINGS_ALL)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"FMP API error {e.code}: {body}")
        except Exception as e:
            raise RuntimeError(f"FMP API request failed: {e}")

    def _demo_response(self, endpoint: str, params: Dict) -> Any:
        """Return demo data when no API key is configured."""
        return {"demo": True, "message": "Set fmp.api.key in application.yml for live data",
                "endpoint": endpoint, "params": {k: v for k, v in params.items() if k != 'apikey'}}

    def get_input_schema(self) -> Dict:
        return self._input_schema

    def get_output_schema(self) -> Dict:
        return self._output_schema


# ═══════════════════════════════════════════════════════════════════════════
# 1. Company Profile
# ═══════════════════════════════════════════════════════════════════════════

class FMPCompanyProfileTool(FMPBaseTool):
    """Get comprehensive company profile — market cap, sector, CEO, description, financials."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('profile', {'symbol': symbol})
        if isinstance(data, list) and data:
            return {"symbol": symbol, "profile": data[0]}
        return {"symbol": symbol, "profile": data}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Stock Quote
# ═══════════════════════════════════════════════════════════════════════════

class FMPStockQuoteTool(FMPBaseTool):
    """Get real-time stock quote — price, change, volume, market cap."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('quote', {'symbol': symbol})
        if isinstance(data, list) and data:
            return {"symbol": symbol, "quote": data[0]}
        return {"symbol": symbol, "quote": data}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Income Statement
# ═══════════════════════════════════════════════════════════════════════════

class FMPIncomeStatementTool(FMPBaseTool):
    """Get income statement — revenue, expenses, net income, EPS."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('income-statement', {
            'symbol': symbol, 'period': period, 'limit': limit
        })
        return {"symbol": symbol, "period": period, "statements": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 4. Balance Sheet
# ═══════════════════════════════════════════════════════════════════════════

class FMPBalanceSheetTool(FMPBaseTool):
    """Get balance sheet — assets, liabilities, equity, cash, debt."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('balance-sheet-statement', {
            'symbol': symbol, 'period': period, 'limit': limit
        })
        return {"symbol": symbol, "period": period, "statements": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cash Flow Statement
# ═══════════════════════════════════════════════════════════════════════════

class FMPCashFlowTool(FMPBaseTool):
    """Get cash flow statement — operating, investing, financing activities."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('cash-flow-statement', {
            'symbol': symbol, 'period': period, 'limit': limit
        })
        return {"symbol": symbol, "period": period, "statements": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 6. Key Metrics & Ratios
# ═══════════════════════════════════════════════════════════════════════════

class FMPKeyMetricsTool(FMPBaseTool):
    """Get key financial ratios — PE, PB, ROE, debt/equity, dividend yield, margins."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('ratios', {
            'symbol': symbol, 'period': period, 'limit': limit
        })
        return {"symbol": symbol, "period": period, "ratios": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 7. Stock Screener
# ═══════════════════════════════════════════════════════════════════════════

class FMPStockScreenerTool(FMPBaseTool):
    """Screen stocks by market cap, sector, price, beta, dividend yield, volume."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        for key in ['marketCapMoreThan', 'marketCapLowerThan', 'betaMoreThan', 'betaLowerThan',
                     'volumeMoreThan', 'volumeLowerThan', 'dividendMoreThan', 'dividendLowerThan',
                     'priceMoreThan', 'priceLowerThan', 'sector', 'industry', 'country',
                     'exchange', 'limit']:
            val = arguments.get(key)
            if val is not None:
                params[key] = val
        if not params:
            params['limit'] = 20
        data = self._fmp_get('stock-screener', params)
        return {"criteria": params, "results_count": len(data) if isinstance(data, list) else 0,
                "results": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 8. Stock News
# ═══════════════════════════════════════════════════════════════════════════

class FMPStockNewsTool(FMPBaseTool):
    """Get latest news articles for a specific stock or general market."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '')
        limit = arguments.get('limit', 10)
        params = {'limit': limit}
        if symbol:
            params['symbol'] = symbol.upper()
        data = self._fmp_get('stock-news', params)
        return {"symbol": symbol or "market", "articles_count": len(data) if isinstance(data, list) else 0,
                "articles": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 9. Analyst Estimates
# ═══════════════════════════════════════════════════════════════════════════

class FMPAnalystEstimatesTool(FMPBaseTool):
    """Get analyst consensus estimates — revenue, EPS, EBITDA forecasts."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('analyst-estimates', {
            'symbol': symbol, 'period': period, 'limit': limit
        })
        return {"symbol": symbol, "period": period,
                "estimates": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 10. Insider Trading
# ═══════════════════════════════════════════════════════════════════════════

class FMPInsiderTradingTool(FMPBaseTool):
    """Get insider trading activity — buys, sells, exercise by company executives."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        limit = arguments.get('limit', 20)
        if not symbol:
            return {"error": "Symbol is required"}
        data = self._fmp_get('insider-trading', {
            'symbol': symbol, 'limit': limit
        })
        return {"symbol": symbol, "transactions_count": len(data) if isinstance(data, list) else 0,
                "transactions": data if isinstance(data, list) else [data]}


# ═══════════════════════════════════════════════════════════════════════════
# 11. Historical Daily Price
# ═══════════════════════════════════════════════════════════════════════════

class FMPHistoricalPriceTool(FMPBaseTool):
    """Get historical daily OHLCV price data for a stock."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol:
            return {"error": "Symbol is required"}
        params = {'symbol': symbol}
        if arguments.get('from_date'):
            params['from'] = arguments['from_date']
        if arguments.get('to_date'):
            params['to'] = arguments['to_date']
        data = self._fmp_get('historical-price-eod/full', params)
        if isinstance(data, dict):
            return {"symbol": symbol, "data_points": len(data.get('historical', [])), "prices": data.get('historical', [])}
        return {"symbol": symbol, "prices": data}


# ═══════════════════════════════════════════════════════════════════════════
# 12-14. Market Movers
# ═══════════════════════════════════════════════════════════════════════════

class FMPMarketGainersTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        data = self._fmp_get('stock-market-gainers', {'limit': arguments.get('limit', 20)})
        return {"gainers": data if isinstance(data, list) else []}

class FMPMarketLosersTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        data = self._fmp_get('stock-market-losers', {'limit': arguments.get('limit', 20)})
        return {"losers": data if isinstance(data, list) else []}

class FMPMostActiveTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        data = self._fmp_get('stock-market-most-active', {'limit': arguments.get('limit', 20)})
        return {"most_active": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 15. Sector Performance
# ═══════════════════════════════════════════════════════════════════════════

class FMPSectorPerformanceTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        data = self._fmp_get('sector-performance')
        return {"sectors": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 16-18. Calendars
# ═══════════════════════════════════════════════════════════════════════════

class FMPEarningsCalendarTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        for k in ['from_date', 'to_date', 'symbol']:
            if arguments.get(k):
                params['from' if k == 'from_date' else 'to' if k == 'to_date' else k] = arguments[k]
        data = self._fmp_get('earning-calendar', params)
        return {"events": data if isinstance(data, list) else []}

class FMPDividendCalendarTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        if arguments.get('from_date'): params['from'] = arguments['from_date']
        if arguments.get('to_date'): params['to'] = arguments['to_date']
        data = self._fmp_get('dividend-calendar', params)
        return {"dividends": data if isinstance(data, list) else []}

class FMPIPOCalendarTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        if arguments.get('from_date'): params['from'] = arguments['from_date']
        if arguments.get('to_date'): params['to'] = arguments['to_date']
        data = self._fmp_get('ipo-calendar', params)
        return {"ipos": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 19-20. Analyst
# ═══════════════════════════════════════════════════════════════════════════

class FMPPriceTargetTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('price-target', {'symbol': symbol, 'limit': arguments.get('limit', 10)})
        return {"symbol": symbol, "targets": data if isinstance(data, list) else []}

class FMPUpgradesDowngradesTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('upgrades-downgrades', {'symbol': symbol, 'limit': arguments.get('limit', 10)})
        return {"symbol": symbol, "changes": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 21-22. DCF Valuation
# ═══════════════════════════════════════════════════════════════════════════

class FMPDCFValuationTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('discounted-cash-flow', {'symbol': symbol})
        return {"symbol": symbol, "dcf": data[0] if isinstance(data, list) and data else data}

class FMPHistoricalDCFTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('historical-discounted-cash-flow', {
            'symbol': symbol, 'period': arguments.get('period', 'annual'), 'limit': arguments.get('limit', 5)
        })
        return {"symbol": symbol, "historical_dcf": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 23-24. Company Data
# ═══════════════════════════════════════════════════════════════════════════

class FMPCompanyPeersTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('stock-peers', {'symbol': symbol})
        return {"symbol": symbol, "peers": data[0].get('peersList', []) if isinstance(data, list) and data else data}

class FMPExecCompensationTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('executive-compensation', {'symbol': symbol})
        return {"symbol": symbol, "executives": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 25-26. SEC & Ownership
# ═══════════════════════════════════════════════════════════════════════════

class FMPSECFilingsTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        params = {'symbol': symbol, 'limit': arguments.get('limit', 20)}
        if arguments.get('type'): params['type'] = arguments['type']
        data = self._fmp_get('sec-filings', params)
        return {"symbol": symbol, "filings": data if isinstance(data, list) else []}

class FMPInstitutionalHoldersTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('institutional-holder', {'symbol': symbol})
        return {"symbol": symbol, "holders": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 27-28. ETF & Senate
# ═══════════════════════════════════════════════════════════════════════════

class FMPETFHoldingsTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        data = self._fmp_get('etf-holder', {'symbol': symbol})
        return {"symbol": symbol, "holdings": data if isinstance(data, list) else []}

class FMPSenateTradingTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {'limit': arguments.get('limit', 20)}
        if arguments.get('symbol'): params['symbol'] = arguments['symbol'].upper()
        data = self._fmp_get('senate-trading', params)
        return {"trades": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# 29-30. Economics
# ═══════════════════════════════════════════════════════════════════════════

class FMPEconomicCalendarTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        if arguments.get('from_date'): params['from'] = arguments['from_date']
        if arguments.get('to_date'): params['to'] = arguments['to_date']
        data = self._fmp_get('economic-calendar', params)
        return {"events": data if isinstance(data, list) else []}

class FMPTreasuryRatesTool(FMPBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        params = {}
        if arguments.get('from_date'): params['from'] = arguments['from_date']
        if arguments.get('to_date'): params['to'] = arguments['to_date']
        data = self._fmp_get('treasury', params)
        return {"rates": data if isinstance(data, list) else []}


# ═══════════════════════════════════════════════════════════════════════════
# Generic FMP Tool — auto-maps tool name to FMP endpoint
# ═══════════════════════════════════════════════════════════════════════════

class FMPGenericTool(FMPBaseTool):
    """Generic FMP tool — maps tool config name to FMP stable endpoint."""

    # Map tool name patterns to FMP endpoints
    ENDPOINT_MAP = {
        'forex_quote': 'fx', 'forex_historical': 'historical-price-eod/full', 'forex_list': 'forex-list',
        'crypto_quote': 'cryptocurrency-quote', 'crypto_historical': 'historical-price-eod/full', 'crypto_list': 'cryptocurrency-list',
        'commodity_quote': 'commodity-quote', 'commodity_historical': 'historical-price-eod/full', 'commodity_list': 'commodity-list',
        'index_quote': 'index-quote', 'index_historical': 'historical-price-eod/full',
        'sp500_constituents': 'sp500-constituent', 'nasdaq_constituents': 'nasdaq-constituent', 'dowjones_constituents': 'dowjones-constituent',
        'esg_rating': 'esg-rating', '13f_filing': '13f',
        'earnings_transcript': 'earnings-call-transcript', 'social_sentiment': 'social-sentiment',
        'technical_sma': 'sma', 'technical_ema': 'ema', 'technical_rsi': 'rsi', 'technical_macd': 'macd',
        'technical_bbands': 'bbands', 'technical_stoch': 'stoch', 'technical_adx': 'adx',
        'technical_dema': 'dema', 'technical_tema': 'tema', 'technical_wma': 'wma',
        'technical_williams': 'williams', 'technical_stddev': 'standard-deviation',
        'available_sectors': 'available-sectors', 'available_industries': 'available-industries',
        'available_countries': 'available-countries', 'available_exchanges': 'available-exchanges',
        'available_indexes': 'available-indexes',
        'stock_list': 'stock-list', 'etf_list': 'etf-list', 'actively_trading': 'actively-trading-list',
        'cik_list': 'cik-list', 'symbol_search': 'search-symbol', 'symbol_changes': 'symbol-change',
        'enterprise_value': 'enterprise-value', 'financial_score': 'piotroski-score',
        'owner_earnings': 'owner-earnings', 'levered_dcf': 'levered-dcf',
        'grade': 'grade', 'rating': 'rating',
        'revenue_by_geography': 'revenue-geographic-segmentation', 'revenue_by_product': 'revenue-product-segmentation',
        'price_target_summary': 'price-target-summary', 'price_target_by_analyst': 'price-target-by-analyst',
        'upgrades_downgrades_consensus': 'upgrades-downgrades-consensus',
        'market_cap': 'market-capitalization', 'historical_market_cap': 'historical-market-cap',
        'employee_count': 'employee-count', 'share_float': 'shares-float',
        'etf_sector_weights': 'etf-sector-weightings', 'etf_country_weights': 'etf-country-weightings',
        'etf_stock_exposure': 'etf-stock-exposure', 'mutual_fund_holders': 'mutual-fund-holder',
        'market_hours': 'market-hours', 'market_risk_premium': 'market-risk-premium',
        'commitment_of_traders': 'cot-report',
        'crowdfunding_rss': 'crowdfunding-rss', 'equity_offering': 'equity-offering-rss',
        'stock_peers_bulk': 'stock-peers-bulk', 'key_executives': 'key-executives',
        'financial_growth': 'financial-growth', 'stock_split_calendar': 'stock-split-calendar',
        'press_releases': 'press-releases',
    }

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        # Extract endpoint from tool name (e.g., fmp_forex_quote → forex_quote)
        tool_name = self._name.replace('fmp_', '', 1)
        endpoint = self.ENDPOINT_MAP.get(tool_name, tool_name.replace('_', '-'))

        params = {}
        for k, v in arguments.items():
            if v is not None and k not in ('limit',):
                # Map common param names to FMP format
                if k == 'from_date': params['from'] = v
                elif k == 'to_date': params['to'] = v
                elif k == 'period': params['period'] = v
                else: params[k] = v
        if 'limit' in arguments:
            params['limit'] = arguments['limit']

        data = self._fmp_get(endpoint, params)
        return {"tool": self._name, "endpoint": endpoint, "data": data}
