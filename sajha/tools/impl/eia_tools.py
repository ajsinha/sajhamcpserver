"""
SAJHA MCP Server — US Energy Information Administration tools (tool folder ``eia``; Open Data Tools §4 P2, L35).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The EIA Open Data API v2 (``api.eia.gov/v2``) is a tree of routes (``petroleum/pri/spt``); a leaf
route has data columns (``value``, ``price`` ...), facets (``series``, ``stateid`` ...) and
frequencies. A key goes in the query string: the environment variable ``EIA_API_KEY`` (free
registration). Without it the tools use the api.data.gov ``DEMO_KEY``, which EIA accepts with a
very small allowance (10 requests, then a ``Retry-After`` of about a day, on 2026-10-12) for the whole
organisation's IP, and say so in ``note``. The class does not set ``keyless_fallback``: an allowance
that small would be spent by the daily live tool check, so the check reports the tools
``not_configured`` until ``EIA_API_KEY`` is set.

EIA answers at most 5,000 rows a page; :func:`fetch_rows` follows the pages (``offset``/``length``)
up to the caller's row cap. EIA's published limits (about 9,000 requests an hour, 5 a second) are
per key and IP: every request first takes a slot in sliding windows kept in the state store, so all
workers share them. Results are cached by each tool's ``cache_ttl``. EIA data are US government
works in the public domain; every result carries ``source``. Every fetch goes through the outbound
fetch guard and HTTP proxy.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl import open_data_common as odc
from sajha.tools.impl.us_treasury_tools import parse_period

BASE = 'https://api.eia.gov/v2'
KEY_ENV = 'EIA_API_KEY'
DEMO_KEY = 'DEMO_KEY'
SOURCE = 'Source: U.S. Energy Information Administration (EIA Open Data API, api.eia.gov)'
PAGE = 5000
DEMO_NOTE = ('No EIA_API_KEY is set: the shared api.data.gov DEMO_KEY was used, which allows only about ten '
             'requests a day for the whole organisation. Register a free key at '
             'https://www.eia.gov/opendata/register.php and set EIA_API_KEY.')
WINDOWS = {'keyed': [('opendata:eia:second', 5, 1.0, 5.0), ('opendata:eia:hour', 9000, 3600.0, 0)],
           'demo': [('opendata:eia:demo:day', 10, 86400.0, 0)]}
FREQUENCIES = ('daily', 'weekly', 'monthly', 'quarterly', 'annual')


def _key(config) -> Tuple[str, bool]:
    key = odc.env_key(KEY_ENV, config)
    return (key, True) if key else (DEMO_KEY, False)


def _route(route: Any) -> str:
    r = str(route or '').strip().strip('/')
    if r.endswith('/data'):
        r = r[:-5]
    if r and not re.fullmatch(r'[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*', r):
        raise ValueError(f'route {route!r} is not an EIA route such as petroleum/pri/spt')
    return r


def call(path: str, params: List[Tuple[str, str]], config) -> Tuple[Dict[str, Any], bool]:
    """One EIA request: (the ``response`` object, whether a real key was used)."""
    key, keyed = _key(config)
    for name, limit, window, wait in WINDOWS['keyed' if keyed else 'demo']:
        odc.take_slot(name, limit, window, wait, 'EIA' if keyed else 'EIA DEMO_KEY')
    url = f'{BASE}/{path}' if path else f'{BASE}/'
    r = odc.get(url, 'EIA', params=list(params) + [('api_key', key)])
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get('error') if isinstance(body, dict) else None
    if isinstance(err, dict):
        code, msg = err.get('code') or '', err.get('message') or ''
    else:
        code, msg = '', str(err or '')
    if r.status_code == 429 or code == 'OVER_RATE_LIMIT':
        raise ValueError('EIA: rate limit reached (HTTP 429)' + ('' if keyed else '; the DEMO_KEY allows only about '
                         'ten requests a day: set EIA_API_KEY'))
    if code in ('API_KEY_INVALID', 'API_KEY_MISSING') or r.status_code in (401, 403):
        raise ValueError(f'EIA refused the API key ({code or r.status_code}): set EIA_API_KEY to a valid key')
    if r.status_code >= 400 or (err and not body.get('response')):
        raise ValueError(f'EIA answered HTTP {r.status_code}: {msg or code or "no detail"}')
    return body.get('response') or {}, keyed


def period_bounds(period: Optional[str], frequency: str) -> Tuple[Optional[str], Optional[str]]:
    """A human period as EIA start/end for the frequency (daily and weekly: dates; monthly: YYYY-MM)."""
    if not period:
        return None, None
    start, end = parse_period(period)
    if frequency in ('daily', 'weekly'):
        return start.isoformat(), end.isoformat()
    if frequency == 'monthly':
        return start.strftime('%Y-%m'), end.strftime('%Y-%m')
    if frequency == 'quarterly':
        return f'{start.year}-Q{(start.month - 1) // 3 + 1}', f'{end.year}-Q{(end.month - 1) // 3 + 1}'
    return str(start.year), str(end.year)


def fetch_rows(route: str, config, *, data: List[str], facets: Dict[str, List[str]], frequency: str,
               start: Optional[str], end: Optional[str], max_rows: int) -> Dict[str, Any]:
    """Rows of a leaf route, newest first, following EIA's 5,000-row pages up to ``max_rows``."""
    params: List[Tuple[str, str]] = [('frequency', frequency)]
    params += [(f'data[{i}]', c) for i, c in enumerate(data)]
    for facet, values in sorted((facets or {}).items()):
        if not re.fullmatch(r'[A-Za-z0-9_\-]+', str(facet)):
            raise ValueError(f'facet name {facet!r} is not valid')
        for v in ([values] if isinstance(values, str) else values or []):
            params.append((f'facets[{facet}][]', str(v)))
    if start:
        params.append(('start', start))
    if end:
        params.append(('end', end))
    params += [('sort[0][column]', 'period'), ('sort[0][direction]', 'desc')]
    rows: List[Dict[str, Any]] = []
    total, keyed, offset, description = 0, True, 0, None
    while True:
        length = min(PAGE, max_rows - len(rows))
        resp, keyed = call(f'{route}/data/', params + [('offset', str(offset)), ('length', str(length))], config)
        page = resp.get('data') or []
        total = int(odc.number(resp.get('total')) or 0)
        description = description or resp.get('description')
        rows.extend(page)
        offset += len(page)
        if not page or len(rows) >= max_rows or offset >= total:
            break
    return {'rows': rows, 'total': total, 'keyed': keyed, 'description': description}


def _numeric(row: Dict[str, Any], columns: List[str]) -> Dict[str, Any]:
    out = dict(row)
    for c in columns:
        if c in out:
            out[c] = odc.number(out[c])
    return out


def _envelope(keyed: bool) -> Dict[str, Any]:
    return {'source': SOURCE} if keyed else {'source': SOURCE, 'note': DEMO_NOTE}


class EiaBaseTool(odc.OpenDataTool):
    """Without EIA_API_KEY a call uses the DEMO_KEY (about ten requests a day for the organisation)."""


class EiaBrowseTool(EiaBaseTool):
    """eia_browse: what a route holds (child routes, or a leaf's frequencies, facets and data columns)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        route = _route(arguments.get('route'))
        facet = str(arguments.get('facet') or '').strip()
        if facet:
            if not re.fullmatch(r'[A-Za-z0-9_\-]+', facet):
                raise ValueError(f'facet {facet!r} is not valid')
            resp, keyed = call(f'{route}/facet/{facet}/', [], self.config)
            out = _envelope(keyed)
            vals = [{'id': f.get('id'), 'name': f.get('name') or f.get('alias')} for f in resp.get('facets') or []]
            out.update({'route': route, 'facet': facet, 'value_count': len(vals), 'values': vals})
            return out
        resp, keyed = call(f'{route}/' if route else '', [], self.config)
        out = _envelope(keyed)
        out.update({
            'route': route, 'name': resp.get('name') or None, 'description': (resp.get('description') or '').strip()
            or None,
            'routes': [{'id': r.get('id'), 'route': f'{route}/{r.get("id")}'.strip('/'), 'name': r.get('name'),
                        'description': (r.get('description') or '').strip() or None}
                       for r in resp.get('routes') or []],
            'frequencies': [{'id': f.get('id'), 'description': f.get('description'), 'format': f.get('format')}
                            for f in resp.get('frequency') or []],
            'facets': [{'id': f.get('id'), 'description': f.get('description')} for f in resp.get('facets') or []],
            'data_columns': [{'id': k, 'name': (v or {}).get('alias'), 'units': (v or {}).get('units')}
                             for k, v in (resp.get('data') or {}).items()],
            'start_period': resp.get('startPeriod'), 'end_period': resp.get('endPeriod'),
            'default_frequency': resp.get('defaultFrequency'),
        })
        return out


class EiaSeriesTool(EiaBaseTool):
    """eia_series: rows of any leaf route, filtered by facets and period."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        route = _route(arguments.get('route'))
        if not route:
            raise ValueError('route is required (a leaf such as petroleum/pri/spt; use eia_browse to find one)')
        frequency = arguments.get('frequency') or 'monthly'
        data = arguments.get('data') or ['value']
        start, end = period_bounds(arguments.get('period'), frequency)
        max_rows = int(arguments.get('max_rows') or 500)
        res = fetch_rows(route, self.config, data=data, facets=arguments.get('facets') or {}, frequency=frequency,
                         start=start, end=end, max_rows=max_rows)
        rows = [_numeric(r, data) for r in reversed(res['rows'])]
        out = _envelope(res['keyed'])
        out.update({'route': route, 'frequency': frequency, 'period': arguments.get('period') or None,
                    'total': res['total'], 'returned': len(rows), 'truncated': res['total'] > len(rows),
                    'rows': rows})
        return out


def series_view(route: str, config, arguments: Dict[str, Any], *, ids: List[str], facet: str, frequency: str,
                default_period: Optional[str], labels: Dict[str, str], id_field: str = 'series',
                start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    """Rows of one value column grouped into series by ``id_field``, oldest first."""
    period = arguments.get('period') or default_period
    if start is None and end is None:
        start, end = period_bounds(period, frequency)
    res = fetch_rows(route, config, data=['value'], facets={facet: ids}, frequency=frequency, start=start, end=end,
                     max_rows=int(arguments.get('max_rows') or 2000))
    by: Dict[str, Dict[str, Any]] = {}
    for row in reversed(res['rows']):
        sid = row.get(id_field)
        s = by.setdefault(sid, {'series_id': sid, 'name': labels.get(sid),
                                'label': row.get('series-description') or row.get('seriesDescription'),
                                'unit': row.get('units') or row.get('unit'), 'observations': []})
        s['observations'].append({'date': row.get('period'), 'value': odc.number(row.get('value'))})
    series = []
    for sid in ids:
        s = by.get(sid) or {'series_id': sid, 'name': labels.get(sid), 'label': None, 'unit': None,
                            'observations': []}
        s['observation_count'] = len(s['observations'])
        series.append(s)
    out = _envelope(res['keyed'])
    out.update({'route': route, 'frequency': frequency, 'period': period or f'{start} to {end}',
                'truncated': res['total'] > len(res['rows']), 'series_count': len(series), 'series': series})
    return out


def _pick(arguments: Dict[str, Any], key: str, table: Dict[str, str], default: List[str]) -> List[str]:
    names = arguments.get(key) or default
    if isinstance(names, str):
        names = [names]
    bad = [n for n in names if n not in table]
    if bad:
        raise ValueError(f'unknown {key} {bad}; use {sorted(table)}')
    return list(dict.fromkeys(names))


SPOT = {'wti': 'RWTC', 'brent': 'RBRTE',
        'ny_harbor_gasoline': 'EER_EPMRU_PF4_Y35NY_DPG', 'gulf_coast_gasoline': 'EER_EPMRU_PF4_RGC_DPG',
        'los_angeles_rbob': 'EER_EPMRR_PF4_Y05LA_DPG', 'ny_harbor_heating_oil': 'EER_EPD2F_PF4_Y35NY_DPG',
        'ny_harbor_ulsd': 'EER_EPD2DXL0_PF4_Y35NY_DPG', 'gulf_coast_ulsd': 'EER_EPD2DXL0_PF4_RGC_DPG',
        'los_angeles_carb_diesel': 'EER_EPD2DC_PF4_Y05LA_DPG', 'gulf_coast_jet_fuel': 'EER_EPJK_PF4_RGC_DPG',
        'mont_belvieu_propane': 'EER_EPLLPA_PF4_Y44MB_DPG'}


class EiaPetroleumSpotPricesTool(EiaBaseTool):
    """eia_petroleum_spot_prices: crude oil and product spot prices (petroleum/pri/spt)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = _pick(arguments, 'products', SPOT, ['wti', 'brent'])
        return series_view('petroleum/pri/spt', self.config, arguments, ids=[SPOT[n] for n in names],
                           facet='series', frequency=arguments.get('frequency') or 'daily',
                           default_period='last 30 days', labels={SPOT[n]: n for n in names})


STOCKS = {'crude_oil_excluding_spr': 'WCESTUS1', 'crude_oil_spr': 'WCSSTUS1', 'gasoline': 'WGTSTUS1',
          'distillate': 'WDISTUS1', 'jet_fuel': 'WKJSTUS1', 'propane': 'WPRSTUS1'}


class EiaPetroleumStocksTool(EiaBaseTool):
    """eia_petroleum_stocks: weekly US ending stocks, thousand barrels (petroleum/stoc/wstk)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = _pick(arguments, 'products', STOCKS, ['crude_oil_excluding_spr'])
        return series_view('petroleum/stoc/wstk', self.config, arguments, ids=[STOCKS[n] for n in names],
                           facet='series', frequency='weekly', default_period='last 3 months',
                           labels={STOCKS[n]: n for n in names})


STORAGE = {'lower_48': 'NW2_EPG0_SWO_R48_BCF', 'east': 'NW2_EPG0_SWO_R31_BCF', 'midwest': 'NW2_EPG0_SWO_R32_BCF',
           'south_central': 'NW2_EPG0_SWO_R33_BCF', 'mountain': 'NW2_EPG0_SWO_R34_BCF',
           'pacific': 'NW2_EPG0_SWO_R35_BCF', 'salt': 'NW2_EPG0_SSO_R33_BCF', 'nonsalt': 'NW2_EPG0_SNO_R33_BCF'}


class EiaNaturalGasStorageTool(EiaBaseTool):
    """eia_natural_gas_storage: weekly working gas in underground storage, Bcf (natural-gas/stor/wkly)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = _pick(arguments, 'regions', STORAGE, ['lower_48'])
        out = series_view('natural-gas/stor/wkly', self.config, arguments, ids=[STORAGE[n] for n in names],
                          facet='series', frequency='weekly', default_period='last 3 months',
                          labels={STORAGE[n]: n for n in names})
        for s in out['series']:              # the weekly injection (+) or withdrawal (-)
            prev = None
            for o in s['observations']:
                o['change'] = (o['value'] - prev) if o['value'] is not None and prev is not None else None
                prev = o['value']
        return out


SECTORS = {'residential': 'RES', 'commercial': 'COM', 'industrial': 'IND', 'transportation': 'TRA',
           'other': 'OTH', 'all': 'ALL'}
RETAIL_MEASURES = ('price', 'sales', 'revenue', 'customers')


class EiaElectricityRetailSalesTool(EiaBaseTool):
    """eia_electricity_retail_sales: monthly retail electricity price, sales, revenue, customers by state and sector."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        states = arguments.get('states') or ['US']
        states = [str(s).strip().upper() for s in ([states] if isinstance(states, str) else states)]
        for s in states:
            if not re.fullmatch(r'[A-Z]{2}', s):
                raise ValueError(f'state {s!r} must be a two-letter code (US for the national total)')
        sectors = _pick(arguments, 'sectors', SECTORS, ['all'])
        measures = arguments.get('measures') or ['price', 'sales']
        bad = [m for m in measures if m not in RETAIL_MEASURES]
        if bad:
            raise ValueError(f'unknown measures {bad}; use {list(RETAIL_MEASURES)}')
        period = arguments.get('period') or 'last 12 months'
        start, end = period_bounds(period, 'monthly')
        res = fetch_rows('electricity/retail-sales', self.config, data=list(measures),
                         facets={'stateid': states, 'sectorid': [SECTORS[s] for s in sectors]},
                         frequency='monthly', start=start, end=end, max_rows=int(arguments.get('max_rows') or 2000))
        by: Dict[str, Dict[str, Any]] = {}
        for row in reversed(res['rows']):
            for m in measures:
                key = f"{row.get('stateid')}.{row.get('sectorid')}.{m}"
                s = by.setdefault(key, {'series_id': key, 'state': row.get('stateid'),
                                        'state_name': row.get('stateDescription'), 'sector': row.get('sectorName'),
                                        'measure': m, 'unit': row.get(f'{m}-units'), 'observations': []})
                s['observations'].append({'date': row.get('period'), 'value': odc.number(row.get(m))})
        series = sorted(by.values(), key=lambda s: s['series_id'])
        for s in series:
            s['observation_count'] = len(s['observations'])
        out = _envelope(res['keyed'])
        out.update({'route': 'electricity/retail-sales', 'frequency': 'monthly', 'period': period,
                    'truncated': res['total'] > len(res['rows']), 'series_count': len(series), 'series': series})
        return out


STEO = {'brent': 'BREPUUS', 'wti': 'WTIPUUS', 'henry_hub': 'NGHHUUS', 'gasoline_retail': 'MGRARUS',
        'us_crude_production': 'COPRPUS', 'us_dry_gas_production': 'NGPRPUS',
        'us_petroleum_consumption': 'PATCPUSX', 'world_petroleum_production': 'PAPR_WORLD',
        'residential_electricity_price': 'ESRCUUS'}


class EiaShortTermOutlookTool(EiaBaseTool):
    """eia_short_term_outlook: Short-Term Energy Outlook history and monthly forecasts (steo)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = _pick(arguments, 'series', STEO, ['brent', 'henry_hub'])
        ids = [STEO[n] for n in names]
        for raw in arguments.get('series_ids') or []:
            raw = str(raw).strip().upper()
            if not re.fullmatch(r'[A-Z0-9_]+', raw):
                raise ValueError(f'series id {raw!r} is not a STEO series id')
            ids.append(raw)
        ids = list(dict.fromkeys(ids))
        start = end = None
        if not arguments.get('period'):          # default: this month to the end of next year (the forecast)
            today = date.today()
            start, end = today.strftime('%Y-%m'), f'{today.year + 1}-12'
        out = series_view('steo', self.config, arguments, ids=ids, facet='seriesId', frequency='monthly',
                          default_period=None, labels={v: k for k, v in STEO.items()}, id_field='seriesId',
                          start=start, end=end)
        out['note_forecast'] = ('Periods after the latest published month are EIA forecasts from the current '
                                'Short-Term Energy Outlook.')
        return out
