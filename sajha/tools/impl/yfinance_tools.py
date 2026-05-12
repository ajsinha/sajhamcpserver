"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Yahoo Finance MCP Tool Implementations

Uses the yfinance Python library (pip install yfinance).
No API key required — free data from Yahoo Finance.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)
_yf = None

def _get_yf():
    global _yf
    if _yf is None:
        try:
            import yfinance as yf
            _yf = yf
        except ImportError:
            raise ImportError('yfinance not installed. Run: pip install yfinance')
    return _yf

def _ticker(symbol):
    return _get_yf().Ticker(symbol)

def _df_to_records(df, limit=100):
    if df is None or (hasattr(df, 'empty') and df.empty):
        return []
    try:
        df = df.reset_index()
        for col in df.columns:
            if hasattr(df[col], 'dt'):
                df[col] = df[col].astype(str)
        return df.head(limit).to_dict(orient='records')
    except Exception as e:
        logger.warning(f"Error handled: {e}", exc_info=True)
        return []


class YFBaseTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config)
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

# 1-5: Core stock data
class YFStockInfoTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        info = t.info or {}
        return {"symbol": args['symbol'], "info": {k: v for k, v in info.items() if not callable(v)}}

class YFStockHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        period = args.get('period', '1y')
        interval = args.get('interval', '1d')
        df = t.history(period=period, interval=interval)
        return {"symbol": args['symbol'], "data_points": len(df), "prices": _df_to_records(df, 500)}

class YFIncomeStatementTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        df = t.quarterly_income_stmt if args.get('quarterly') else t.income_stmt
        return {"symbol": args['symbol'], "statements": _df_to_records(df.T if df is not None else None)}

class YFBalanceSheetTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        df = t.quarterly_balance_sheet if args.get('quarterly') else t.balance_sheet
        return {"symbol": args['symbol'], "statements": _df_to_records(df.T if df is not None else None)}

class YFCashFlowTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        df = t.quarterly_cashflow if args.get('quarterly') else t.cashflow
        return {"symbol": args['symbol'], "statements": _df_to_records(df.T if df is not None else None)}

# 6-10: Dividends, splits, actions
class YFDividendsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "dividends": _df_to_records(t.dividends)}

class YFSplitsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "splits": _df_to_records(t.splits)}

class YFActionsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "actions": _df_to_records(t.actions)}

class YFCalendarTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        try:
            cal = t.calendar
            if hasattr(cal, 'to_dict'):
                return {"symbol": args['symbol'], "calendar": cal.to_dict()}
            return {"symbol": args['symbol'], "calendar": cal if isinstance(cal, dict) else str(cal)}
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            return {"symbol": args['symbol'], "calendar": {}}

class YFSustainabilityTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "sustainability": _df_to_records(t.sustainability)}

# 11-15: Holders and ownership
class YFInstitutionalHoldersTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "holders": _df_to_records(t.institutional_holders)}

class YFMajorHoldersTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "holders": _df_to_records(t.major_holders)}

class YFMutualFundHoldersTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "holders": _df_to_records(t.mutualfund_holders)}

class YFInsiderTransactionsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "transactions": _df_to_records(t.insider_transactions)}

class YFInsiderPurchasesTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "purchases": _df_to_records(t.insider_purchases)}

# 16-20: Analyst data
class YFRecommendationsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "recommendations": _df_to_records(t.recommendations, 50)}

class YFAnalystPriceTargetsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        try:
            targets = t.analyst_price_targets
            if hasattr(targets, 'to_dict'):
                return {"symbol": args['symbol'], "targets": targets.to_dict()}
            return {"symbol": args['symbol'], "targets": targets if isinstance(targets, dict) else {}}
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            return {"symbol": args['symbol'], "targets": {}}

class YFUpgradesDowngradesTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "upgrades_downgrades": _df_to_records(t.upgrades_downgrades, 30)}

class YFEarningsHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "earnings": _df_to_records(t.earnings_history)}

class YFEarningsDatesTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "dates": _df_to_records(t.earnings_dates)}

# 21-25: Options
class YFOptionsExpiriesTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "expiries": list(t.options)}

class YFOptionsChainTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        expiry = args.get('expiry')
        if not expiry:
            opts = t.options
            expiry = opts[0] if opts else None
        if not expiry:
            return {"error": "No options available"}
        chain = t.option_chain(expiry)
        return {"symbol": args['symbol'], "expiry": expiry,
                "calls": _df_to_records(chain.calls, 50),
                "puts": _df_to_records(chain.puts, 50)}

class YFSharesOutstandingTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "shares": _df_to_records(t.get_shares_full())}

class YFNewsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        news = t.news or []
        return {"symbol": args['symbol'], "articles": news[:args.get('limit', 10)]}

class YFFastInfoTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        fi = t.fast_info
        return {"symbol": args['symbol'], "fast_info": {
            "market_cap": getattr(fi, 'market_cap', None),
            "last_price": getattr(fi, 'last_price', None),
            "fifty_day_average": getattr(fi, 'fifty_day_average', None),
            "two_hundred_day_average": getattr(fi, 'two_hundred_day_average', None),
            "year_high": getattr(fi, 'year_high', None),
            "year_low": getattr(fi, 'year_low', None),
            "shares_outstanding": getattr(fi, 'shares', None),
        }}

# 26-30: Market screeners
class YFScreenerTool(YFBaseTool):
    """Screen stocks using yfinance screener — gainers, losers, most active, etc."""
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        screen_type = args.get('screen_type', 'day_gainers')
        try:
            screener = yf.Screener()
            screener.set_default_body(screen_type)
            data = screener.response
            quotes = data.get('finance', {}).get('result', [{}])[0].get('quotes', [])
            return {"screen_type": screen_type, "count": len(quotes), "results": quotes[:50]}
        except Exception as e:
            return {"screen_type": screen_type, "error": str(e)}

class YFSectorPerformanceTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        sectors = {
            'XLK': 'Technology', 'XLF': 'Financials', 'XLV': 'Health Care',
            'XLY': 'Consumer Discretionary', 'XLP': 'Consumer Staples',
            'XLE': 'Energy', 'XLI': 'Industrials', 'XLB': 'Materials',
            'XLU': 'Utilities', 'XLRE': 'Real Estate', 'XLC': 'Communication',
        }
        results = []
        for sym, name in sectors.items():
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                results.append({"sector": name, "etf": sym, "price": getattr(fi, 'last_price', None)})
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
                pass
        return {"sectors": results}

class YFCryptoInfoTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        sym = args.get('symbol', 'BTC-USD')
        if not sym.endswith('-USD'):
            sym = f'{sym}-USD'
        t = _ticker(sym)
        info = t.info or {}
        return {"symbol": sym, "info": {k: v for k, v in info.items() if not callable(v)}}

class YFForexHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        pair = args.get('pair', 'EURUSD=X')
        if '=X' not in pair:
            pair = f'{pair}=X'
        t = _ticker(pair)
        df = t.history(period=args.get('period', '3mo'))
        return {"pair": pair, "data_points": len(df), "rates": _df_to_records(df)}

class YFIndexHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        index = args.get('index', '^GSPC')
        t = _ticker(index)
        df = t.history(period=args.get('period', '1y'))
        return {"index": index, "data_points": len(df), "prices": _df_to_records(df)}

# 31-35: ETF specific
class YFETFInfoTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        info = t.info or {}
        return {"symbol": args['symbol'], "etf_info": {k: v for k, v in info.items()
                if k in ('shortName','longName','category','fundFamily','totalAssets','yield','ytdReturn',
                         'threeYearAverageReturn','fiveYearAverageReturn','expenseRatio') and not callable(v)}}

class YFMultiTickerHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        symbols = args.get('symbols', 'AAPL MSFT GOOGL')
        df = yf.download(symbols, period=args.get('period', '1mo'), group_by='ticker')
        results = {}
        if isinstance(symbols, str):
            syms = symbols.split()
        else:
            syms = symbols
        for s in syms:
            try:
                sub = df[s] if len(syms) > 1 else df
                results[s] = _df_to_records(sub, 30)
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
                results[s] = []
        return {"symbols": syms, "data": results}

class YFTrendingTickersTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        try:
            trending = yf.Screener()
            trending.set_default_body('most_actives')
            data = trending.response
            quotes = data.get('finance', {}).get('result', [{}])[0].get('quotes', [])
            return {"trending": quotes[:20]}
        except Exception as e:
            return {"error": str(e)}

class YFMarketSummaryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        indices = {'^GSPC': 'S&P 500', '^DJI': 'Dow Jones', '^IXIC': 'NASDAQ',
                   '^RUT': 'Russell 2000', '^VIX': 'VIX', '^TNX': '10Y Treasury'}
        results = []
        for sym, name in indices.items():
            try:
                t = _ticker(sym)
                fi = t.fast_info
                results.append({"index": name, "symbol": sym,
                               "price": getattr(fi, 'last_price', None)})
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
                pass
        return {"market_summary": results}

class YFCompareStocksTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        symbols = args.get('symbols', 'AAPL,MSFT,GOOGL').split(',')
        results = []
        for sym in symbols[:10]:
            try:
                t = _ticker(sym.strip())
                info = t.info or {}
                results.append({
                    "symbol": sym.strip(),
                    "name": info.get('shortName', ''),
                    "market_cap": info.get('marketCap'),
                    "pe_ratio": info.get('trailingPE'),
                    "dividend_yield": info.get('dividendYield'),
                    "52w_high": info.get('fiftyTwoWeekHigh'),
                    "52w_low": info.get('fiftyTwoWeekLow'),
                })
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
                pass
        return {"comparison": results}
