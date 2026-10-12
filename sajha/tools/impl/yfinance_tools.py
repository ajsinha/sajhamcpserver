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
from sajha.core import outbound

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

DEFAULT_ROWS = 100
MAX_ROWS = 1000


def _row_limit(args, default=DEFAULT_ROWS, maximum=MAX_ROWS) -> int:
    """The caller's ``limit`` (else ``default``), within 1..``maximum``."""
    try:
        n = int(args.get('limit') if args.get('limit') is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, maximum))


def _df_to_records(df, limit=DEFAULT_ROWS, newest=False):
    """Rows of a DataFrame (index included). ``newest`` keeps the last ``limit`` rows (a time
    series in ascending order), else the first. Use _df_rows when the caller must know about the cut."""
    return _df_rows(df, limit, newest)[0]


def _df_rows(df, limit=DEFAULT_ROWS, newest=False):
    """(rows, total rows, truncated) of a DataFrame, index included."""
    if df is None or (hasattr(df, 'empty') and df.empty):
        return [], 0, False
    try:
        total = len(df)
        df = df.tail(limit) if newest else df.head(limit)
        df = df.reset_index()
        for col in df.columns:
            if hasattr(df[col], 'dt'):
                df[col] = df[col].astype(str)
        df = df.astype(object).where(df.notna(), None)
        return df.to_dict(orient='records'), total, total > limit
    except Exception as e:
        logger.warning(f"Error handled: {e}", exc_info=True)
        return [], 0, False


def _series_result(key, df, args, default=DEFAULT_ROWS, newest=True, **head):
    """{**head, data_points, truncated, key: rows}: the most recent ``limit`` rows of a time series,
    oldest first."""
    rows, total, truncated = _df_rows(df, _row_limit(args, default), newest)
    return {**head, "data_points": total, "truncated": truncated, key: rows}


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
        return _series_result("prices", df, args, 500, symbol=args['symbol'], period=period, interval=interval)

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
        return _series_result("dividends", t.dividends, args, symbol=args['symbol'])

class YFSplitsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return _series_result("splits", t.splits, args, symbol=args['symbol'])

class YFActionsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return _series_result("actions", t.actions, args, symbol=args['symbol'])

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

# yf_sustainability was removed in 8.14.0: Yahoo no longer serves ESG scores (quoteSummary esgScores
# answers 404 "No fundamentals data found" for every symbol), so the tool could only return nothing.

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
        return _series_result("recommendations", t.recommendations, args, 50, newest=False, symbol=args['symbol'])

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
        # newest first, as Yahoo returns it
        return _series_result("upgrades_downgrades", t.upgrades_downgrades, args, 30, newest=False, symbol=args['symbol'])

class YFEarningsHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return {"symbol": args['symbol'], "earnings": _df_to_records(t.earnings_history)}

class YFEarningsDatesTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        # newest (scheduled) first, as Yahoo returns it
        return _series_result("dates", t.earnings_dates, args, 12, newest=False, symbol=args['symbol'])

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
        n = _row_limit(args, 50, 500)
        calls, n_calls, cut_calls = _df_rows(chain.calls, n)
        puts, n_puts, cut_puts = _df_rows(chain.puts, n)
        return {"symbol": args['symbol'], "expiry": expiry, "total_calls": n_calls, "total_puts": n_puts,
                "truncated": cut_calls or cut_puts, "calls": calls, "puts": puts}

class YFSharesOutstandingTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        return _series_result("shares", t.get_shares_full(), args, symbol=args['symbol'])

class YFNewsTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        limit = _row_limit(args, 10, 50)
        news = []
        try:
            news = _ticker(args['symbol']).news or []
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
        if not news:
            # Ticker.news has come back empty from Yahoo at times; the search endpoint still lists news
            news = _get_yf().Search(args['symbol'], news_count=limit, max_results=1).news or []
        return {"symbol": args['symbol'], "articles": news[:limit]}

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
#: fields kept from each Yahoo screener quote
SCREEN_FIELDS = ('symbol', 'shortName', 'longName', 'exchange', 'quoteType', 'currency', 'regularMarketPrice',
                 'regularMarketChange', 'regularMarketChangePercent', 'regularMarketVolume', 'averageDailyVolume3Month',
                 'marketCap', 'trailingPE', 'forwardPE', 'fiftyTwoWeekHigh', 'fiftyTwoWeekLow')


class YFScreenerTool(YFBaseTool):
    """Yahoo's predefined screens through yf.screen (yfinance 0.2.54 and later)."""
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        screen_type = args.get('screen_type', 'day_gainers')
        count = _row_limit(args, 25, 250)
        try:
            data = yf.screen(screen_type, count=count) or {}
        except Exception as e:
            return {"screen_type": screen_type, "error": str(e)}
        quotes = data.get('quotes') or []
        results = [{k: q.get(k) for k in SCREEN_FIELDS if k in q} for q in quotes[:count]]
        return {"screen_type": screen_type, "title": data.get('title'), "total": data.get('total'),
                "count": len(results), "results": results}

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
        sym = str(args.get('symbol') or 'BTC-USD').upper().strip()
        if '-' not in sym:
            sym = f'{sym}-USD'          # BTC -> BTC-USD; BTC-EUR stays as given
        t = _ticker(sym)
        info = t.info or {}
        return {"symbol": sym, "info": {k: v for k, v in info.items() if not callable(v)}}

class YFForexHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        pair = str(args.get('pair') or 'EURUSD=X').upper().replace('/', '').replace(' ', '')
        if not pair.endswith('=X'):
            pair = f'{pair}=X'
        period = args.get('period', '3mo')
        df = _ticker(pair).history(period=period)
        return _series_result("rates", df, args, pair=pair, period=period)

class YFIndexHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        index = args.get('index', '^GSPC')
        period = args.get('period', '1y')
        df = _ticker(index).history(period=period)
        return _series_result("prices", df, args, 260, index=index, period=period)

# 31-35: ETF specific
class YFETFInfoTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        t = _ticker(args['symbol'])
        info = t.info or {}
        return {"symbol": args['symbol'], "etf_info": {k: v for k, v in info.items()
                if k in ('shortName','longName','category','fundFamily','totalAssets','yield','ytdReturn',
                         'threeYearAverageReturn','fiveYearAverageReturn','expenseRatio') and not callable(v)}}

MAX_TICKERS = 10


class YFMultiTickerHistoryTool(YFBaseTool):
    def execute(self, args: Dict[str, Any]) -> Dict:
        yf = _get_yf()
        symbols = args.get('symbols', 'AAPL MSFT GOOGL')
        raw = symbols.replace(',', ' ').split() if isinstance(symbols, str) else list(symbols)
        syms = list(dict.fromkeys(s.strip().upper() for s in raw if str(s).strip()))
        if len(syms) > MAX_TICKERS:
            return {"error": f"at most {MAX_TICKERS} tickers per call; got {len(syms)}"}
        if not syms:
            return {"error": "no tickers given"}
        period = args.get('period', '1mo')
        limit = _row_limit(args, 30, 500)
        df = yf.download(syms, period=period, group_by='ticker', auto_adjust=False, progress=False)
        results, totals, truncated = {}, {}, False
        for s in syms:
            try:
                sub = df[s] if len(syms) > 1 else (df[s] if s in getattr(df.columns, 'levels', [[]])[0] else df)
                sub = sub.dropna(how='all')
                rows, total, cut = _df_rows(sub, limit, newest=True)
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
                rows, total, cut = [], 0, False
            results[s], totals[s] = rows, total
            truncated = truncated or cut
        return {"symbols": syms, "period": period, "data_points": totals, "truncated": truncated, "data": results}


TRENDING_URL = 'https://query1.finance.yahoo.com/v1/finance/trending/{region}'


class YFTrendingTickersTool(YFBaseTool):
    """Yahoo Finance's trending tickers for a region (yfinance has no call for it; the endpoint
    needs no cookie)."""
    def execute(self, args: Dict[str, Any]) -> Dict:
        import json as _json
        import urllib.parse
        import urllib.request
        region = str(args.get('region') or 'US').upper()
        count = _row_limit(args, 20, 50)
        url = TRENDING_URL.format(region=urllib.parse.quote(region)) + '?' + urllib.parse.urlencode({'count': count})
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                                                 'AppleWebKit/537.36'})
        try:
            with outbound.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {"region": region, "error": f"Yahoo trending request failed: {e}"}
        result = ((data.get('finance') or {}).get('result') or [{}])[0] or {}
        symbols = [q.get('symbol') for q in result.get('quotes') or [] if q.get('symbol')]
        return {"region": region, "count": len(symbols[:count]), "symbols": symbols[:count]}


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
