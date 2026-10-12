"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
CoinGecko MCP Tools — Cryptocurrency Market Data

API: https://docs.coingecko.com/reference/introduction
Keyless use is CoinGecko's public API, limited to a few calls a minute per address and to the past
365 days of history; a free demo key (COINGECKO_API_KEY, application.yml ``coingecko.api.key``)
raises the limit to 30 calls a minute. Every call goes through the outbound fetch guard and a
throttle shared by all workers through the state store (``coingecko.calls_per_minute``), so SAJHA
stops before CoinGecko answers 429. Results are cached per tool (``cache_ttl`` in each tool config).
"""

import json, time, urllib.error, urllib.parse, urllib.request, logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, ENCODINGS_ALL
from sajha.core import outbound

logger = logging.getLogger(__name__)
CG_BASE = "https://api.coingecko.com/api/v3"
KEY_SETTING = 'coingecko.api.key'
RATE_SETTING = 'coingecko.calls_per_minute'
KEYLESS_CALLS_PER_MINUTE = 5            # CoinGecko's public API allows "5 to 15" depending on load
KEYED_CALLS_PER_MINUTE = 30             # the demo plan
THROTTLE_KEY = 'tools:coingecko:calls'
COOLDOWN_KEY = 'tools:coingecko:cooldown'   # set from a 429's Retry-After: no call until it passes


def _api_key(config) -> str:
    """The configured CoinGecko demo key ('' when none): the tool config's api_key, then coingecko.api.key."""
    from sajha.core.config import _get
    for v in ((config or {}).get('api_key'), _get(KEY_SETTING, '')):
        if isinstance(v, str) and v.strip() and not v.strip().startswith('${'):
            return v.strip()
    return ''


def calls_per_minute(keyed: bool) -> int:
    from sajha.core.config import _get
    raw = _get(RATE_SETTING, None)
    try:
        n = int(raw)
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    return KEYED_CALLS_PER_MINUTE if keyed else KEYLESS_CALLS_PER_MINUTE


def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def cooldown_remaining() -> float:
    """Seconds left of the wait CoinGecko last asked for (429 Retry-After), shared by all workers."""
    try:
        until = _store().get(COOLDOWN_KEY)
        return max(0.0, float(until) - time.time()) if until else 0.0
    except Exception:
        return 0.0


def _start_cooldown(seconds: float) -> None:
    seconds = max(1.0, min(float(seconds), 300.0))
    try:
        _store().set(COOLDOWN_KEY, time.time() + seconds, ttl=seconds)
    except Exception as e:
        logger.debug(f"coingecko cooldown not stored: {e}")


def _take_slot(keyed: bool) -> None:
    """One call against the shared per-minute budget; raises ValueError when it is spent, or while
    CoinGecko's last 429 asks every worker to wait."""
    wait = cooldown_remaining()
    if wait > 0:
        raise ValueError(f"CoinGecko rate limit: CoinGecko asked SAJHA to wait; try again in {wait:.0f} s"
                         + ("" if keyed else ". A free CoinGecko demo key (COINGECKO_API_KEY) raises the limit"))
    limit = calls_per_minute(keyed)
    try:
        allowed, _ = _store().window_add(THROTTLE_KEY, 60.0, limit)
    except Exception as e:                       # no state store: CoinGecko's own 429 still applies
        logger.debug(f"coingecko throttle unavailable: {e}")
        return
    if not allowed:
        hint = '' if keyed else ' A free CoinGecko demo key (COINGECKO_API_KEY) raises the limit to 30.'
        raise ValueError(f"CoinGecko rate limit: SAJHA allows {limit} CoinGecko calls a minute "
                         f"({RATE_SETTING}) and they are used; try again in a minute.{hint}")


def _error_detail(body: bytes) -> str:
    try:
        data = json.loads(body.decode('utf-8', errors='replace'))
    except ValueError:
        return ''
    err = data.get('error') if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str((err.get('status') or {}).get('error_message') or err.get('message') or '')
    if isinstance(err, str):
        return err
    st = data.get('status') if isinstance(data, dict) else None
    return str(st.get('error_message') or '') if isinstance(st, dict) else ''


class CGBaseTool(BaseMCPTool):
    #: keyless use is CoinGecko's public API (the live check still calls the tools)
    keyless_fallback = True

    @property
    def check_pause_seconds(self) -> float:
        """The live check calls CoinGecko tools no faster than the shared per-minute budget allows, and
        not before a wait CoinGecko asked for (429 Retry-After) has passed."""
        return max(60.0 / calls_per_minute(bool(self.api_key or _api_key(None))), cooldown_remaining())

    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = _api_key(config)

    def _cg_get(self, path, **params):
        """GET one CoinGecko endpoint; raises ValueError with CoinGecko's reason on any failure."""
        url = f"{CG_BASE}/{path}"
        if params:
            url += '?' + urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
        headers = {'Accept': 'application/json'}
        key = self.api_key or _api_key(None)
        if key:
            headers['x-cg-demo-api-key'] = key
        _take_slot(bool(key))
        try:
            req = urllib.request.Request(url, headers=headers)
            with outbound.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = _error_detail(e.read() or b'')
            if e.code == 429:
                retry = e.headers.get('Retry-After') if e.headers else None
                try:
                    _start_cooldown(float(retry) if retry else 60.0)
                except ValueError:
                    _start_cooldown(60.0)
                raise ValueError("CoinGecko rate limit (HTTP 429): too many calls from this address"
                                 + (f"; retry after {retry} s" if retry else "; try again in a minute")
                                 + ("" if key else ". A free CoinGecko demo key (COINGECKO_API_KEY) raises the limit"))
            if e.code in (401, 403) and not detail:
                detail = 'this endpoint or range needs a CoinGecko API key or a paid plan'
            raise ValueError(f"CoinGecko HTTP {e.code}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise ValueError(f"CoinGecko request failed: {e.reason}")
        except ValueError as e:
            if isinstance(e, outbound.Refused):
                raise
            raise ValueError(f"CoinGecko returned a response that is not JSON: {e}")

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
    """A past day's snapshot. Without ``date``, yesterday (UTC). Keyless and demo keys reach only the
    past 365 days; CoinGecko answers 401 (error 10012) further back, which becomes a clear error."""
    def execute(self, a):
        date = a.get('date') or (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%d-%m-%Y')
        try:
            when = datetime.strptime(date, '%d-%m-%Y').replace(tzinfo=timezone.utc)
        except ValueError:
            raise ValueError(f"date {date!r} is not DD-MM-YYYY (e.g. 31-12-2025)")
        try:
            return self._cg_get(f"coins/{a.get('id','bitcoin')}/history", date=date, localization='false')
        except ValueError as e:
            if 'HTTP 401' in str(e) and (datetime.now(timezone.utc) - when).days > 365:
                raise ValueError(f"{e}. CoinGecko's public API and demo keys reach only the past 365 days; "
                                 "older dates need a paid CoinGecko plan")
            raise
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
class _CGMoversTool(CGBaseTool):
    """24-hour movers among the 250 largest coins by market cap. CoinGecko documents no
    price-change order for coins/markets, so SAJHA ranks the market-cap page itself."""
    UNIVERSE = 250
    descending = True

    def execute(self, a):
        limit = max(1, min(int(a.get('limit') or 20), 100))
        coins = self._cg_get('coins/markets', vs_currency='usd', order='market_cap_desc', per_page=self.UNIVERSE)
        ranked = [c for c in coins or [] if isinstance(c, dict) and c.get('price_change_percentage_24h') is not None]
        ranked.sort(key=lambda c: c['price_change_percentage_24h'], reverse=self.descending)
        return {"coins": ranked[:limit], "universe": f"top {self.UNIVERSE} coins by market cap",
                "ranked_by": "price_change_percentage_24h " + ("descending" if self.descending else "ascending")}
class CGTopGainersTool(_CGMoversTool):
    descending = True
class CGTopLosersTool(_CGMoversTool):
    descending = False
class CGDerivativesTool(CGBaseTool):
    def execute(self, a): return {"derivatives": self._cg_get('derivatives')}
class CGDerivativesExchangesTool(CGBaseTool):
    def execute(self, a): return {"exchanges": self._cg_get('derivatives/exchanges')}
class CGExchangeRatesTool(CGBaseTool):
    def execute(self, a): return self._cg_get('exchange_rates')
class CGCompaniesHoldingsTool(CGBaseTool):
    def execute(self, a): return self._cg_get(f"companies/public_treasury/{a.get('coin_id','bitcoin')}")
