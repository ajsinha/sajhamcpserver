"""
SAJHA MCP Server — CFTC Commitments of Traders tools (tool folder ``cftc``; Open Data Tools §4, L32).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The CFTC publishes the weekly Commitments of Traders (COT) reports as Socrata datasets on
``publicreporting.cftc.gov``: one dataset per report (legacy, disaggregated, traders in financial
futures) and kind (futures only, or futures and options combined). The data is a US government
work in the public domain; the CFTC asks to be acknowledged, so every result carries ``source``.

No key is needed. Without a Socrata app token every caller behind the organisation's egress IP
shares one anonymous pool, so an operator may set ``CFTC_APP_TOKEN`` (sent as ``X-App-Token``);
either way every request first takes a slot in one sliding window kept in the state store, so all
workers share one budget, and each tool's ``cache_ttl`` caches its results. Every fetch goes
through the outbound fetch guard and HTTP proxy (``open_data_common.get``). Requests always sort
newest first.

Positions are numbers of contracts; percentages are percent of open interest.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl.open_data_common import OpenDataTool, env_key, get, number, take_slot
from sajha.tools.impl.us_treasury_tools import parse_date, parse_period

BASE = 'https://publicreporting.cftc.gov/resource'
SOURCE = 'Source: CFTC Commitments of Traders (publicreporting.cftc.gov)'
LABEL = 'CFTC Commitments of Traders'
TOKEN_ENV = 'CFTC_APP_TOKEN'
THROTTLE_KEY = 'opendata:cftc:requests'
THROTTLE_LIMIT = 60            # requests per minute across every worker (Socrata publishes no figure)
THROTTLE_WINDOW = 60.0
THROTTLE_WAIT = 15.0
UNITS = 'positions in contracts; pct_* and net_pct_of_open_interest in percent of open interest'

DATASETS = {
    ('legacy', 'futures_only'): '6dca-aqww', ('legacy', 'combined'): 'jun7-fc8e',
    ('disaggregated', 'futures_only'): '72hh-3qpy', ('disaggregated', 'combined'): 'kh3c-gbw2',
    ('tff', 'futures_only'): 'gpe5-46if', ('tff', 'combined'): 'yw9f-hn96',
}
REPORT_NAMES = {'legacy': 'Legacy', 'disaggregated': 'Disaggregated', 'tff': 'Traders in Financial Futures'}

# category -> (long, short, spread, change long, change short, pct long, pct short, traders long, traders short)
_NONREPT = ('nonrept_positions_long_all', 'nonrept_positions_short_all', None, 'change_in_nonrept_long_all',
            'change_in_nonrept_short_all', 'pct_of_oi_nonrept_long_all', 'pct_of_oi_nonrept_short_all', None, None)
_OTHER = ('other_rept_positions_long', 'other_rept_positions_short', 'other_rept_positions_spread',
          'change_in_other_rept_long', 'change_in_other_rept_short', 'pct_of_oi_other_rept_long',
          'pct_of_oi_other_rept_short', 'traders_other_rept_long_all', 'traders_other_rept_short')
CATEGORIES: Dict[str, Dict[str, Tuple[Optional[str], ...]]] = {
    'legacy': {
        'noncommercial': ('noncomm_positions_long_all', 'noncomm_positions_short_all', 'noncomm_postions_spread_all',
                          'change_in_noncomm_long_all', 'change_in_noncomm_short_all', 'pct_of_oi_noncomm_long_all',
                          'pct_of_oi_noncomm_short_all', 'traders_noncomm_long_all', 'traders_noncomm_short_all'),
        'commercial': ('comm_positions_long_all', 'comm_positions_short_all', None, 'change_in_comm_long_all',
                       'change_in_comm_short_all', 'pct_of_oi_comm_long_all', 'pct_of_oi_comm_short_all',
                       'traders_comm_long_all', 'traders_comm_short_all'),
        'nonreportable': _NONREPT,
    },
    'disaggregated': {
        'producer_merchant': ('prod_merc_positions_long', 'prod_merc_positions_short', None, 'change_in_prod_merc_long',
                              'change_in_prod_merc_short', 'pct_of_oi_prod_merc_long', 'pct_of_oi_prod_merc_short',
                              'traders_prod_merc_long_all', 'traders_prod_merc_short_all'),
        'swap_dealers': ('swap_positions_long_all', 'swap__positions_short_all', 'swap__positions_spread_all',
                         'change_in_swap_long_all', 'change_in_swap_short_all', 'pct_of_oi_swap_long_all',
                         'pct_of_oi_swap_short_all', 'traders_swap_long_all', 'traders_swap_short_all'),
        'managed_money': ('m_money_positions_long_all', 'm_money_positions_short_all', 'm_money_positions_spread',
                          'change_in_m_money_long_all', 'change_in_m_money_short_all', 'pct_of_oi_m_money_long_all',
                          'pct_of_oi_m_money_short_all', 'traders_m_money_long_all', 'traders_m_money_short_all'),
        'other_reportables': _OTHER,
        'nonreportable': _NONREPT,
    },
    'tff': {
        'dealers': ('dealer_positions_long_all', 'dealer_positions_short_all', 'dealer_positions_spread_all',
                    'change_in_dealer_long_all', 'change_in_dealer_short_all', 'pct_of_oi_dealer_long_all',
                    'pct_of_oi_dealer_short_all', 'traders_dealer_long_all', 'traders_dealer_short_all'),
        'asset_managers': ('asset_mgr_positions_long', 'asset_mgr_positions_short', 'asset_mgr_positions_spread',
                           'change_in_asset_mgr_long', 'change_in_asset_mgr_short', 'pct_of_oi_asset_mgr_long',
                           'pct_of_oi_asset_mgr_short', 'traders_asset_mgr_long_all', 'traders_asset_mgr_short_all'),
        'leveraged_funds': ('lev_money_positions_long', 'lev_money_positions_short', 'lev_money_positions_spread',
                            'change_in_lev_money_long', 'change_in_lev_money_short', 'pct_of_oi_lev_money_long',
                            'pct_of_oi_lev_money_short', 'traders_lev_money_long_all', 'traders_lev_money_short_all'),
        'other_reportables': _OTHER,
        'nonreportable': _NONREPT,
    },
}
_FIELDS = ('long', 'short', 'spread', 'change_long', 'change_short', 'pct_long', 'pct_short',
           'traders_long', 'traders_short')
_BASE_COLS = ('market_and_exchange_names', 'report_date_as_yyyy_mm_dd', 'cftc_contract_market_code',
              'commodity_name', 'contract_units', 'open_interest_all', 'change_in_open_interest_all',
              'traders_tot_all')
_CODE = re.compile(r'^[0-9A-Z]{6}$')


def _throttle() -> None:
    take_slot(THROTTLE_KEY, THROTTLE_LIMIT, THROTTLE_WINDOW, THROTTLE_WAIT, LABEL)


def socrata(dataset: str, params: Dict[str, Any], token: Optional[str] = None) -> List[Dict[str, Any]]:
    """One SoQL query on a COT dataset: the rows."""
    _throttle()
    headers = {'X-App-Token': token} if token else {}
    r = get(f'{BASE}/{dataset}.json', LABEL, params=list(params.items()), headers=headers)
    if r.status_code >= 400:
        detail = ''
        try:
            detail = (r.json() or {}).get('message') or ''
        except Exception:
            pass
        if r.status_code == 429:
            raise ValueError(f'{LABEL}: rate limit reached (HTTP 429); set {TOKEN_ENV} for a token of your own')
        raise ValueError(f'{LABEL} answered HTTP {r.status_code}{": " + detail if detail else ""}')
    rows = r.json()
    if not isinstance(rows, list):
        raise ValueError(f'{LABEL}: unexpected answer')
    return rows


def _quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _report(arguments: Dict[str, Any]) -> Tuple[str, str, str]:
    report = str(arguments.get('report') or 'legacy').strip().lower()
    kind = str(arguments.get('kind') or 'futures_only').strip().lower()
    if (report, kind) not in DATASETS:
        raise ValueError("report must be legacy, disaggregated or tff and kind futures_only or combined")
    return report, kind, DATASETS[(report, kind)]


def _day(value: Any) -> Optional[str]:
    return str(value)[:10] if value else None


def market_matches(dataset: str, search: str, token: Optional[str], limit: int = 20,
                   since: Optional[str] = None) -> List[Dict[str, Any]]:
    """Markets whose name contains every word of ``search`` (or whose code is ``search``),
    with their latest report date, newest first."""
    words = [w for w in re.split(r'\s+', str(search or '').strip().upper()) if w]
    if not words:
        raise ValueError('search is required (part of a market name, e.g. "GOLD", or a CFTC code)')
    clauses = [f"upper(market_and_exchange_names) like {_quote('%' + w + '%')}" for w in words]
    where = '(' + ' AND '.join(clauses) + ')'
    if len(words) == 1 and _CODE.match(words[0]):
        where = f"({where} OR cftc_contract_market_code={_quote(words[0])})"
    if since:
        where += f" AND report_date_as_yyyy_mm_dd >= {_quote(since + 'T00:00:00.000')}"
    rows = socrata(dataset, {
        '$select': 'cftc_contract_market_code,market_and_exchange_names,commodity_name,'
                   'max(report_date_as_yyyy_mm_dd) as latest_report',
        '$where': where,
        '$group': 'cftc_contract_market_code,market_and_exchange_names,commodity_name',
        '$order': 'latest_report DESC',
        '$limit': str(limit),
    }, token)
    return [{'code': (r.get('cftc_contract_market_code') or '').strip(),
             'name': r.get('market_and_exchange_names'),
             'commodity': r.get('commodity_name'),
             'latest_report': _day(r.get('latest_report'))} for r in rows]


def resolve_market(dataset: str, market: str, token: Optional[str]) -> str:
    """A CFTC contract market code from a code or a name; an ambiguous name is refused with the
    candidates, so a call never silently picks the wrong contract."""
    m = str(market or '').strip()
    if not m:
        raise ValueError('market is required: a CFTC contract market code (e.g. 13874A) or a market name')
    if _CODE.match(m.upper()) and any(ch.isdigit() for ch in m):
        return m.upper()
    found = market_matches(dataset, m, token, limit=50)
    if not found:
        raise ValueError(f'No COT market matches {market!r}; try cftc_cot_markets')
    newest = max(f['latest_report'] or '' for f in found)
    current = [f for f in found if (f['latest_report'] or '') == newest]
    exact = [f for f in current if str(f['name'] or '').upper() == m.upper()
             or str(f['name'] or '').split(' - ')[0].upper() == m.upper()]
    pick = exact or current
    codes = list(dict.fromkeys(f['code'] for f in pick))
    if len(codes) == 1:
        return codes[0]
    sample = '; '.join(f"{f['code']} {f['name']}" for f in pick[:8])
    raise ValueError(f'{market!r} matches {len(codes)} current markets; pass one code: {sample}')


def _columns(report: str) -> str:
    cols = list(_BASE_COLS)
    for fields in CATEGORIES[report].values():
        cols += [f for f in fields if f and f not in cols]
    return ','.join(cols)


def _int(v: Any) -> Optional[int]:
    n = number(v)
    return None if n is None else int(n)


def _row_out(report: str, row: Dict[str, Any], categories: Optional[List[str]] = None) -> Dict[str, Any]:
    oi = _int(row.get('open_interest_all'))
    cats = {}
    for name, fields in CATEGORIES[report].items():
        if categories and name not in categories:
            continue
        c: Dict[str, Any] = {}
        for key, col in zip(_FIELDS, fields):
            if col is None:
                continue
            c[key] = number(row.get(col)) if key.startswith('pct') else _int(row.get(col))
        long_, short_ = c.get('long'), c.get('short')
        c['net'] = None if long_ is None or short_ is None else long_ - short_
        c['net_pct_of_open_interest'] = (round(100.0 * c['net'] / oi, 2)
                                         if c['net'] is not None and oi else None)
        cats[name] = c
    return {
        'report_date': _day(row.get('report_date_as_yyyy_mm_dd')),
        'market': row.get('market_and_exchange_names'),
        'code': (row.get('cftc_contract_market_code') or '').strip() or None,
        'commodity': row.get('commodity_name'),
        'contract_units': row.get('contract_units'),
        'open_interest': oi,
        'change_in_open_interest': _int(row.get('change_in_open_interest_all')),
        'traders_total': _int(row.get('traders_tot_all')),
        'categories': cats,
    }


def _history(dataset: str, report: str, code: str, start: Optional[date], end: Optional[date],
             limit: int, token: Optional[str]) -> List[Dict[str, Any]]:
    where = f"cftc_contract_market_code={_quote(code)}"
    if start:
        where += f" AND report_date_as_yyyy_mm_dd >= {_quote(start.isoformat() + 'T00:00:00.000')}"
    if end:
        where += f" AND report_date_as_yyyy_mm_dd <= {_quote(end.isoformat() + 'T00:00:00.000')}"
    return socrata(dataset, {'$select': _columns(report), '$where': where,
                             '$order': 'report_date_as_yyyy_mm_dd DESC', '$limit': str(limit)}, token)


class CftcBaseTool(OpenDataTool):
    keyless_fallback = True        # the app token only raises Socrata's limit

    def _token(self) -> Optional[str]:
        return env_key(TOKEN_ENV, self.config, 'app_token')

    def _head(self, report: str, kind: str, dataset: str) -> Dict[str, Any]:
        return {'report': report, 'report_name': REPORT_NAMES[report], 'kind': kind, 'dataset': dataset,
                'source': SOURCE, 'units': UNITS}


class CftcCotLatestTool(CftcBaseTool):
    """cftc_cot_latest: the newest weekly COT positions for one market."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        report, kind, dataset = _report(arguments)
        token = self._token()
        code = resolve_market(dataset, arguments.get('market'), token)
        rows = _history(dataset, report, code, None, None, 1, token)
        out = self._head(report, kind, dataset)
        if not rows:
            out.update({'code': code, 'note': f'No {REPORT_NAMES[report]} report for market {code} '
                                              f'({kind.replace("_", " ")}); try the other report or kind'})
            return out
        out.update(_row_out(report, rows[0]))
        return out


class CftcCotHistoryTool(CftcBaseTool):
    """cftc_cot_history: weekly COT positions for one market between two dates, newest first."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        report, kind, dataset = _report(arguments)
        token = self._token()
        start = parse_date(arguments['from'], 'from') if arguments.get('from') else None
        end = parse_date(arguments['to'], 'to') if arguments.get('to') else None
        if start and end and end < start:
            raise ValueError('to is before from')
        limit = int(arguments.get('limit') or 104)
        code = resolve_market(dataset, arguments.get('market'), token)
        rows = _history(dataset, report, code, start, end, limit, token)
        cats = arguments.get('categories') or None
        if cats:
            unknown = [c for c in cats if c not in CATEGORIES[report]]
            if unknown:
                raise ValueError(f'unknown categories for the {report} report: {unknown}; use '
                                 f'{sorted(CATEGORIES[report])}')
        reports = [_row_out(report, r, cats) for r in rows]
        out = self._head(report, kind, dataset)
        out.update({'code': code, 'market': reports[0]['market'] if reports else None,
                    'from': start.isoformat() if start else None, 'to': end.isoformat() if end else None,
                    'count': len(reports), 'reports': reports})
        if len(reports) >= limit:
            out['truncated'] = True
        if not reports:
            out['note'] = 'No reports for this market and range.'
        return out


class CftcCotMarketsTool(CftcBaseTool):
    """cftc_cot_markets: find COT markets (code, name, latest report) by part of the name."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        report, kind, dataset = _report(arguments)
        since = None
        if arguments.get('active_only', True):
            since = date.fromordinal(date.today().toordinal() - 35).isoformat()
        found = market_matches(dataset, arguments.get('search'), self._token(),
                               limit=int(arguments.get('limit') or 25), since=since)
        out = self._head(report, kind, dataset)
        out.update({'search': arguments.get('search'), 'count': len(found), 'markets': found})
        if not found:
            out['note'] = 'No market matches; try a shorter name, or active_only false for discontinued markets.'
        return out


NET_DEFAULT = {'legacy': 'noncommercial', 'disaggregated': 'managed_money', 'tff': 'leveraged_funds'}


class CftcCotNetPositioningTool(CftcBaseTool):
    """cftc_cot_net_positioning: one category's net long as a percent of open interest, week by week."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        report, kind, dataset = _report(arguments)
        category = arguments.get('category') or NET_DEFAULT[report]
        if category not in CATEGORIES[report]:
            raise ValueError(f'category {category!r} is not in the {report} report; use '
                             f'{sorted(CATEGORIES[report])}')
        start, end = parse_period(arguments.get('period') or 'last 12 months')
        token = self._token()
        code = resolve_market(dataset, arguments.get('market'), token)
        rows = _history(dataset, report, code, start, end, 520, token)
        points = []
        for r in rows:
            o = _row_out(report, r, [category])
            c = o['categories'][category]
            points.append({'report_date': o['report_date'], 'open_interest': o['open_interest'],
                           'long': c.get('long'), 'short': c.get('short'), 'net': c.get('net'),
                           'net_pct_of_open_interest': c.get('net_pct_of_open_interest')})
        values = [p['net_pct_of_open_interest'] for p in points if p['net_pct_of_open_interest'] is not None]
        out = self._head(report, kind, dataset)
        out.update({'code': code, 'market': rows[0].get('market_and_exchange_names') if rows else None,
                    'category': category, 'period': arguments.get('period') or 'last 12 months',
                    'from': start.isoformat(), 'to': end.isoformat(), 'count': len(points),
                    'latest': points[0] if points else None,
                    'summary': ({'min': min(values), 'max': max(values),
                                 'average': round(sum(values) / len(values), 2),
                                 'percentile_of_latest': round(100.0 * sum(v <= values[0] for v in values)
                                                               / len(values), 1)} if values else None),
                    'observations': points})
        if not points:
            out['note'] = 'No reports for this market and period.'
        return out
