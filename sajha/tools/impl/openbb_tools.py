"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
OpenBB Platform MCP Tool Implementations

Uses the OpenBB Python SDK (pip install openbb). Docs: https://docs.openbb.co/platform/

Every tool names one OpenBB command (``TOOL_COMMANDS``). A call:

* resolves the command in the installed OpenBB; a command that is not there answers with an
  error naming it and raises the info notice ``tools.openbb_command:<tool>``;
* uses the provider the caller chose, else the schema's ``provider`` default, and refuses a
  provider the command does not offer;
* sends only the parameters the command accepts for that provider (the rest are listed in
  ``ignored_arguments``);
* returns rows with their dates (OpenBB keeps the date in the DataFrame index, so rows are
  taken from the result models, not ``to_dataframe()``).

Keys: OpenBB reads provider credentials from ~/.openbb_platform/user_settings.json. SAJHA also
hands OpenBB the keys it already has (``fmp.api.key``, ``fred.api.key``,
``alpha_vantage.api.key``, normally from FMP_API_KEY, FRED_API_KEY and ALPHA_VANTAGE_API_KEY)
for any credential that user_settings.json leaves empty. OpenBB commands take no per-call
credentials, so the keys are set once on the OpenBB session.
"""

import copy
import logging
import math
import threading
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)

# Lazy import: openbb is heavy (several seconds), so it loads on the first call.
_obb = None
_obb_lock = threading.Lock()

#: OpenBB credential name -> SAJHA config key that holds the same secret
SAJHA_CREDENTIALS = (
    ('fmp_api_key', 'fmp.api.key'),
    ('fred_api_key', 'fred.api.key'),
    ('alpha_vantage_api_key', 'alpha_vantage.api.key'),
)

#: Providers that need no key in OpenBB 4.6
KEYLESS_PROVIDERS = frozenset({'yfinance', 'federal_reserve', 'oecd', 'sec', 'imf', 'econdb', 'nasdaq',
                               'government_us', 'ecb', 'cftc'})

DEFAULT_ROWS = 100
MAX_ROWS = 1000

#: tool name -> (OpenBB command path, {SAJHA argument: OpenBB parameter})
TOOL_COMMANDS: Dict[str, Tuple[str, Dict[str, str]]] = {
    'openbb_balance_sheet': ('equity.fundamental.balance', {}),
    'openbb_cash_flow': ('equity.fundamental.cash', {}),
    'openbb_income_statement': ('equity.fundamental.income', {}),
    'openbb_commodity_price': ('commodity.price.spot', {}),
    'openbb_company_news': ('news.company', {}),
    'openbb_crypto_price': ('crypto.price.historical', {}),
    'openbb_crypto_search': ('crypto.search', {}),
    'openbb_currency_snapshots': ('currency.snapshots', {}),
    'openbb_derivatives_futures_curve': ('derivatives.futures.curve', {}),
    'openbb_derivatives_futures_historical': ('derivatives.futures.historical', {}),
    'openbb_dividends': ('equity.fundamental.dividends', {}),
    'openbb_earnings': ('equity.fundamental.historical_eps', {}),
    'openbb_economic_indicators': ('economy.indicators', {}),
    'openbb_economy_available_indicators': ('economy.available_indicators', {}),
    'openbb_economy_calendar': ('economy.calendar', {}),
    'openbb_economy_cpi': ('economy.cpi', {}),
    'openbb_economy_gdp': ('economy.gdp.nominal', {}),
    'openbb_economy_interest_rate': ('economy.interest_rates', {}),
    'openbb_economy_leading': ('economy.composite_leading_indicator', {}),
    'openbb_economy_risk_premium': ('economy.risk_premium', {}),
    'openbb_equity_calendar_dividend': ('equity.calendar.dividend', {}),
    'openbb_equity_calendar_earnings': ('equity.calendar.earnings', {}),
    'openbb_equity_compare_peers': ('equity.compare.peers', {}),
    'openbb_equity_discovery_active': ('equity.discovery.active', {}),
    'openbb_equity_discovery_gainers': ('equity.discovery.gainers', {}),
    'openbb_equity_discovery_losers': ('equity.discovery.losers', {}),
    'openbb_equity_estimates_consensus': ('equity.estimates.consensus', {}),
    'openbb_equity_fundamental_ratios': ('equity.fundamental.ratios', {}),
    'openbb_equity_management': ('equity.fundamental.management', {}),
    'openbb_equity_metrics': ('equity.fundamental.metrics', {}),
    'openbb_equity_price': ('equity.price.historical', {}),
    'openbb_equity_price_performance': ('equity.price.performance', {}),
    'openbb_equity_profile': ('equity.profile', {}),
    'openbb_equity_revenue_geographic': ('equity.fundamental.revenue_per_geography', {}),
    'openbb_equity_revenue_segment': ('equity.fundamental.revenue_per_segment', {}),
    'openbb_equity_screener': ('equity.screener', {'market_cap_min': 'mktcap_min', 'market_cap_max': 'mktcap_max'}),
    'openbb_equity_search': ('equity.search', {}),
    'openbb_equity_share_statistics': ('equity.ownership.share_statistics', {}),
    'openbb_etf_countries': ('etf.countries', {}),
    'openbb_etf_equity_exposure': ('etf.equity_exposure', {}),
    'openbb_etf_holdings': ('etf.holdings', {}),
    'openbb_etf_info': ('etf.info', {}),
    'openbb_etf_search': ('etf.search', {}),
    'openbb_etf_sectors': ('etf.sectors', {}),
    'openbb_fixedincome_effr': ('fixedincome.rate.effr', {}),
    'openbb_fixedincome_estr': ('fixedincome.rate.estr', {}),
    'openbb_fixedincome_ice_bofa': ('fixedincome.bond_indices', {}),
    'openbb_fixedincome_iorb': ('fixedincome.rate.iorb', {}),
    'openbb_fixedincome_sofr': ('fixedincome.rate.sofr', {}),
    'openbb_fixedincome_treasury_auctions': ('fixedincome.government.treasury_auctions', {}),
    'openbb_forex_historical': ('currency.price.historical', {}),
    'openbb_index_available': ('index.available', {}),
    'openbb_index_constituents': ('index.constituents', {'index': 'symbol'}),
    'openbb_index_price_historical': ('index.price.historical', {}),
    'openbb_insider_trading': ('equity.ownership.insider_trading', {}),
    'openbb_institutional_ownership': ('equity.ownership.institutional', {}),
    'openbb_market_news': ('news.world', {}),
    'openbb_options_chains': ('derivatives.options.chains', {}),
    'openbb_regulators_sec_filings': ('equity.fundamental.filings', {}),
    'openbb_regulators_sec_search': ('regulators.sec.institutions_search', {}),
    'openbb_treasury_rates': ('fixedincome.government.treasury_rates', {}),
    'openbb_unemployment': ('economy.unemployment', {}),
    'openbb_yield_curve': ('fixedincome.government.yield_curve', {}),
}


class OpenBBCallError(Exception):
    """A call OpenBB refused or could not answer; the message is shown to the caller."""


def _secret(value) -> str:
    if value is None:
        return ''
    get = getattr(value, 'get_secret_value', None)
    return str(get() if callable(get) else value)


def apply_sajha_credentials(obb) -> List[str]:
    """Copy SAJHA's FMP, FRED and Alpha Vantage keys into OpenBB's session credentials, but only
    where OpenBB has none (user_settings.json wins). Returns the credential names set."""
    try:
        from sajha.core.config import _get
    except Exception:       # pragma: no cover - config always importable in SAJHA
        return []
    creds = getattr(getattr(obb, 'user', None), 'credentials', None)
    if creds is None:
        return []
    done = []
    for name, key in SAJHA_CREDENTIALS:
        value = str(_get(key, '') or '').strip()
        if not value or value.startswith('${'):
            continue
        try:
            if _secret(getattr(creds, name, None)).strip():
                continue
            setattr(creds, name, value)
            done.append(name)
        except Exception as e:      # an OpenBB without this credential field
            logger.debug(f'OpenBB credential {name} not set: {e}')
    if done:
        logger.info(f'OpenBB credentials from SAJHA configuration: {", ".join(done)}')
    return done


def _get_obb():
    """Lazy-load the OpenBB SDK (once) and give it SAJHA's keys."""
    global _obb
    if _obb is None:
        with _obb_lock:
            if _obb is None:
                try:
                    from openbb import obb
                except ImportError:
                    raise ImportError('OpenBB SDK not installed. Run: pip install openbb')
                apply_sajha_credentials(obb)
                _obb = obb
                logger.info('OpenBB SDK loaded')
    return _obb


def resolve_command(obb, path: str):
    """The callable for ``path`` (e.g. 'fixedincome.rate.effr'), or None when OpenBB lacks it."""
    node = obb
    for part in path.split('.'):
        node = getattr(node, part, None)
        if node is None:
            return None
    return node if callable(node) else None


def command_providers(obb, path: str) -> Optional[List[str]]:
    """Providers the installed OpenBB offers for a command (None when OpenBB cannot say)."""
    try:
        return list(obb.coverage.commands.get('.' + path) or []) or None
    except Exception:
        return None


def command_parameters(obb, path: str, provider: str) -> Optional[set]:
    """Parameter names a command accepts for one provider (None when OpenBB cannot say)."""
    try:
        params = obb.reference['paths']['/' + path.replace('.', '/')]['parameters']
    except Exception:
        return None
    names = {p['name'] for p in params.get('standard', [])}
    names |= {p['name'] for p in params.get(provider, [])}
    return names


def _clean(value):
    """JSON-safe value: NaN and infinities become None, dates become ISO strings."""
    if type(value).__module__ == 'numpy' and hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _to_records(result) -> List[Dict]:
    """Rows of an OBBject, with every field (the date included, which to_dataframe() moves into
    the index). Falls back to the DataFrame for results that are not models."""
    results = getattr(result, 'results', None)
    items = results if isinstance(results, list) else None
    if items is None and isinstance(results, dict):
        items = [results]
    # a single model (e.g. an option chain held as columns) goes through the DataFrame below
    if items is not None:
        rows = []
        for item in items:
            if hasattr(item, 'model_dump'):
                rows.append(_clean(item.model_dump(mode='json')))
            elif isinstance(item, dict):
                rows.append(_clean(item))
            else:
                rows.append({'value': _clean(item)})
        return rows
    try:
        df = result.to_dataframe()
        if df.index.name is not None or getattr(df.index, 'names', [None])[0] is not None:
            df = df.reset_index()
        for col in df.columns:
            if hasattr(df[col], 'dt'):
                df[col] = df[col].astype(str)
        return [_clean(r) for r in df.to_dict(orient='records')]
    except Exception:
        return [{'data': str(result)}]


def cap_rows(records: List[Dict], limit) -> Tuple[List[Dict], int, bool]:
    """At most ``limit`` rows (default 100, at most 1000). A dated series in ascending order keeps
    its most recent rows; anything else keeps the first rows. Returns (rows, total, truncated)."""
    total = len(records)
    try:
        n = int(limit) if limit is not None else DEFAULT_ROWS
    except (TypeError, ValueError):
        n = DEFAULT_ROWS
    n = max(1, min(n, MAX_ROWS))
    if total <= n:
        return records, total, False
    first, last = records[0], records[-1]
    key = _date_key(first)
    if key and isinstance(last, dict) and first.get(key) and last.get(key) and str(first[key]) < str(last[key]):
        return records[-n:], total, True
    return records[:n], total, True


def _date_key(row) -> Optional[str]:
    """The row's date field: 'date', else the first field named '*_date' or 'period_ending'."""
    if not isinstance(row, dict):
        return None
    if 'date' in row:
        return 'date'
    for k in row:
        if k.endswith('_date') or k == 'period_ending':
            return k
    return None


def _error_text(e: Exception) -> str:
    text = str(e).strip()
    for prefix in ('[Error] ->', '[Empty] ->', '[Unexpected Error] ->'):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text or e.__class__.__name__


class OpenBBBaseTool(BaseMCPTool):
    """Base class for all OpenBB tools: command resolution, provider choice, parameter filter."""

    #: default when the schema has no provider default
    fallback_provider = 'yfinance'

    def __init__(self, config: Dict = None):
        super().__init__(config)

    def get_input_schema(self) -> Dict:
        return self._input_schema

    def get_output_schema(self) -> Dict:
        return self._output_schema

    # ── command and provider ──────────────────────────────────────────────

    @property
    def command_path(self) -> Optional[str]:
        entry = TOOL_COMMANDS.get(self.name)
        return self.config.get('command') or (entry[0] if entry else None)

    @property
    def renames(self) -> Dict[str, str]:
        entry = TOOL_COMMANDS.get(self.name)
        return dict(entry[1]) if entry else {}

    @property
    def default_provider(self) -> str:
        props = (self._input_schema or {}).get('properties') or {}
        return (props.get('provider') or {}).get('default') or self.config.get('default_provider') \
            or self.fallback_provider

    def _provider(self, arguments: Dict[str, Any]) -> str:
        return arguments.get('provider') or self.default_provider

    def _with_schema_defaults(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """The arguments with the schema's defaults for absent keys, so a direct call behaves as a
        call through the platform (which fills them before execute)."""
        props = (self._input_schema or {}).get('properties') or {}
        out = dict(arguments)
        for k, p in props.items():
            if k not in out and isinstance(p, dict) and 'default' in p:
                out[k] = copy.deepcopy(p['default'])
        return out

    def _fetch(self, arguments: Dict[str, Any], extra: Optional[Dict[str, Any]] = None
               ) -> Tuple[List[Dict], str, List[str]]:
        """Run this tool's command. ``arguments`` are the caller's (``provider`` and SAJHA-only
        keys removed by the caller where needed); ``extra`` overrides them. Returns
        (rows, provider, ignored argument names); raises OpenBBCallError."""
        obb = _get_obb()
        path = self.command_path
        if not path:
            raise OpenBBCallError(f'no OpenBB command is mapped for {self.name}')
        fn = resolve_command(obb, path)
        if fn is None:
            self._notice_missing(path)
            raise OpenBBCallError(f'the installed OpenBB has no obb.{path}; this tool needs an OpenBB '
                                  f'version that provides it')
        arguments = self._with_schema_defaults(arguments)
        provider = self._provider(arguments)
        providers = command_providers(obb, path)
        if providers and provider not in providers:
            raise OpenBBCallError(f'provider {provider!r} is not available for obb.{path}; '
                                  f'choose one of: {", ".join(sorted(providers))}')
        params: Dict[str, Any] = {}
        for k, v in arguments.items():
            if k == 'provider' or v is None:
                continue
            params[self.renames.get(k, k)] = v
        params.update({k: v for k, v in (extra or {}).items() if v is not None})
        accepted = command_parameters(obb, path, provider)
        ignored: List[str] = []
        if accepted is not None:
            reverse = {v: k for k, v in self.renames.items()}
            for k in list(params):
                if k not in accepted:
                    params.pop(k)
                    if k != 'limit':        # limit is also SAJHA's row cap
                        ignored.append(reverse.get(k, k))
        try:
            result = fn(provider=provider, **params)
        except Exception as e:
            raise OpenBBCallError(_error_text(e))
        return _to_records(result), provider, sorted(ignored)

    def _notice_missing(self, path: str) -> None:
        try:
            from sajha import notices
            notices.raise_notice(
                f'tools.openbb_command:{self.name}', severity='info', source='tools',
                title=f'{self.name}: the installed OpenBB has no obb.{path}',
                detail=f'The tool answers with an error until OpenBB provides obb.{path}. Install the OpenBB '
                       f'version named in requirements.txt, or disable the tool.',
                link='/help/guides/OpenBB%20Tool%20Reference%20Guide.md', ttl_minutes=0)
        except Exception:
            pass

    @staticmethod
    def _with_ignored(out: Dict[str, Any], ignored: List[str]) -> Dict[str, Any]:
        if ignored:
            out['ignored_arguments'] = ignored
        return out


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


# ═══════════════════════════════════════════════════════════════════════════
# Generic tool: one OpenBB command, rows capped by ``limit``
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBGenericTool(OpenBBBaseTool):
    """Runs the tool's OpenBB command and returns its rows."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        try:
            rows, provider, ignored = self._fetch(arguments)
        except OpenBBCallError as e:
            return {"tool": self.name, "error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"tool": self.name, "provider": provider, "data_points": total,
                                   "truncated": truncated, "data": rows}, ignored)


class OpenBBEconomyCalendarTool(OpenBBGenericTool):
    """``economy.calendar`` with a window that always holds events: without dates, the past 7 days to
    the next 7 (the providers' own default is today only, empty on a weekend or holiday). A window
    with no events is an empty result with a note, not an error (nasdaq answers "No record found")."""

    window_days = 7

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = dict(arguments or {})
        if not arguments.get('start_date') and not arguments.get('end_date'):
            arguments['start_date'] = _days_ago(self.window_days)
            arguments['end_date'] = (datetime.now() + timedelta(days=self.window_days)).strftime('%Y-%m-%d')
        out = super().execute(arguments)
        if 'no record found' in str(out.get('error') or '').lower():
            out = {"tool": self.name, "provider": arguments.get('provider') or 'nasdaq', "data_points": 0,
                   "truncated": False, "data": [],
                   "note": "The provider lists no economic events in this window (future weeks are filled in "
                           "as the release schedule is published)."}
        out.setdefault('start_date', arguments.get('start_date'))
        out.setdefault('end_date', arguments.get('end_date'))
        return out


# ═══════════════════════════════════════════════════════════════════════════
# Tools with their own result shape
# ═══════════════════════════════════════════════════════════════════════════

class _PriceHistoryTool(OpenBBBaseTool):
    """symbol + start/end date (default window ``days``); every row in the range."""
    days = 365
    rows_key = 'prices'
    default_symbol = ''

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        symbol = str(arguments.get('symbol') or self.default_symbol).upper()
        if not symbol:
            return {"error": "symbol is required"}
        start_date = arguments.get('start_date') or _days_ago(self.days)
        end_date = arguments.get('end_date') or _today()
        try:
            rows, provider, ignored = self._fetch(arguments, {'symbol': symbol, 'start_date': start_date,
                                                              'end_date': end_date})
        except OpenBBCallError as e:
            return {"symbol": symbol, "error": str(e)}
        return self._with_ignored({"symbol": symbol, "provider": provider, "data_points": len(rows),
                                   "start_date": start_date, "end_date": end_date, self.rows_key: rows}, ignored)


class OpenBBEquityPriceTool(_PriceHistoryTool):
    """Daily OHLCV history for one stock."""


class OpenBBForexHistoricalTool(_PriceHistoryTool):
    """Daily exchange-rate history for one pair."""
    days = 90
    rows_key = 'rates'
    default_symbol = 'EURUSD'


class OpenBBCryptoPriceTool(_PriceHistoryTool):
    """Daily price history for one crypto pair."""
    days = 90
    default_symbol = 'BTCUSD'


class _SymbolTool(OpenBBBaseTool):
    """One symbol in, rows out under ``rows_key``; ``first_only`` returns one record."""
    rows_key = 'data'
    first_only = False

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        symbol = str(arguments.get('symbol') or '').upper()
        if not symbol:
            return {"error": "symbol is required"}
        try:
            rows, provider, ignored = self._fetch(arguments, {'symbol': symbol})
        except OpenBBCallError as e:
            return {"symbol": symbol, "error": str(e)}
        out: Dict[str, Any] = {"symbol": symbol, "provider": provider}
        if self.first_only:
            out[self.rows_key] = rows[0] if rows else {}
        else:
            rows, total, truncated = cap_rows(rows, arguments.get('limit'))
            out.update({"data_points": total, "truncated": truncated, self.rows_key: rows})
        return self._with_ignored(out, ignored)


class OpenBBEquityProfileTool(_SymbolTool):
    rows_key = 'profile'
    first_only = True


class OpenBBEquityMetricsTool(_SymbolTool):
    rows_key = 'metrics'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        out = super().execute(arguments)
        out.setdefault('period', arguments.get('period', 'annual'))
        return out


class OpenBBIncomeStatementTool(_SymbolTool):
    rows_key = 'statements'


class OpenBBBalanceSheetTool(_SymbolTool):
    rows_key = 'statements'


class OpenBBCashFlowTool(_SymbolTool):
    rows_key = 'statements'


class OpenBBDividendsTool(_SymbolTool):
    rows_key = 'dividends'


class OpenBBEarningsTool(_SymbolTool):
    rows_key = 'earnings'


class OpenBBCompanyNewsTool(_SymbolTool):
    rows_key = 'articles'


class OpenBBETFHoldingsTool(_SymbolTool):
    rows_key = 'holdings'


class OpenBBOptionsChainsTool(_SymbolTool):
    rows_key = 'chain'


class OpenBBInstitutionalOwnershipTool(_SymbolTool):
    rows_key = 'holders'


class OpenBBInsiderTradingTool(_SymbolTool):
    rows_key = 'transactions'


class _CountryTool(OpenBBBaseTool):
    """country in, rows out under ``rows_key``."""
    rows_key = 'data'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        country = arguments.get('country') or 'united_states'
        try:
            rows, provider, ignored = self._fetch(arguments, {'country': country})
        except OpenBBCallError as e:
            return {"country": country, "error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"country": country, "provider": provider, "data_points": total,
                                   "truncated": truncated, self.rows_key: rows}, ignored)


class OpenBBEconomyGDPTool(_CountryTool):
    rows_key = 'gdp_data'


class OpenBBEconomyCPITool(_CountryTool):
    rows_key = 'cpi_data'


class OpenBBUnemploymentTool(_CountryTool):
    rows_key = 'data'


class OpenBBEconomicIndicatorsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        symbol = arguments.get('symbol') or 'CPI'
        try:
            rows, provider, ignored = self._fetch(arguments, {'symbol': symbol})
        except OpenBBCallError as e:
            return {"indicator": symbol, "error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"indicator": symbol, "provider": provider, "data_points": total,
                                   "truncated": truncated, "data": rows}, ignored)


class OpenBBMarketNewsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        try:
            rows, provider, ignored = self._fetch(arguments)
        except OpenBBCallError as e:
            return {"error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"provider": provider, "articles_count": len(rows), "articles": rows}, ignored)


class OpenBBTreasuryRatesTool(OpenBBBaseTool):
    """US Treasury constant-maturity yields, one row per day with a column per maturity."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        start_date = arguments.get('start_date') or _days_ago(365)
        end_date = arguments.get('end_date') or _today()
        try:
            rows, provider, ignored = self._fetch(arguments, {'start_date': start_date, 'end_date': end_date})
        except OpenBBCallError as e:
            return {"error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"provider": provider, "data_points": total, "truncated": truncated,
                                   "start_date": start_date, "end_date": end_date, "rates": rows}, ignored)


class OpenBBYieldCurveTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        try:
            rows, provider, ignored = self._fetch(arguments)
        except OpenBBCallError as e:
            return {"error": str(e)}
        return self._with_ignored({"provider": provider, "date": rows[0].get('date') if rows else None,
                                   "yield_curve": rows}, ignored)


class OpenBBIndexConstituentsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        index = str(arguments.get('index') or 'sp500').lower()
        try:
            rows, provider, ignored = self._fetch(dict(arguments, index=index))
        except OpenBBCallError as e:
            return {"index": index, "error": str(e)}
        return self._with_ignored({"index": index, "provider": provider, "count": len(rows),
                                   "constituents": rows}, ignored)


class OpenBBCommodityPriceTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        commodity = arguments.get('commodity') or 'wti'
        start_date = arguments.get('start_date') or _days_ago(180)
        try:
            rows, provider, ignored = self._fetch(arguments, {'commodity': commodity, 'start_date': start_date})
        except OpenBBCallError as e:
            return {"commodity": commodity, "error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"commodity": commodity, "provider": provider, "data_points": total,
                                   "truncated": truncated, "prices": rows}, ignored)


class OpenBBEquityScreenerTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arguments = self._with_schema_defaults(arguments)
        try:
            rows, provider, ignored = self._fetch(arguments)
        except OpenBBCallError as e:
            return {"error": str(e)}
        rows, total, truncated = cap_rows(rows, arguments.get('limit'))
        return self._with_ignored({"provider": provider, "results_count": len(rows), "truncated": truncated,
                                   "results": rows}, ignored)
