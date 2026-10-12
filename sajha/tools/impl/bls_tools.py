"""
SAJHA MCP Server — US Bureau of Labor Statistics tools (tool folder ``bls``; Open Data Tools §4 P2, L35).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The BLS Public Data API (``api.bls.gov/publicAPI``) has two tiers:

* **v2**, with a free registration key (environment variable ``BLS_API_KEY``): 500 queries a day,
  50 series and 20 years a query, and series titles (``catalog``);
* **v1**, keyless: 25 queries a day, 25 series and 10 years a query. Without a key the tools use v1
  and say so in ``api_version`` and ``note`` (``keyless_fallback``).

The daily budget is per IP address, so the whole organisation behind one egress IP shares it: every
query first takes a slot in a sliding window kept in the state store (one window per tier, plus a
burst window). Results are cached by each tool's ``cache_ttl``.

BLS data are public domain. The BLS terms of service require users of the API to cite the date the
data were retrieved and to state that "BLS.gov cannot vouch for the data or analyses derived from
these data after the data have been retrieved from BLS.gov": every result carries ``retrieved``,
``disclaimer`` and ``source``. Every fetch goes through the outbound fetch guard and HTTP proxy.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl import open_data_common as odc
from sajha.tools.impl.us_treasury_tools import parse_period

URL = {'v2': 'https://api.bls.gov/publicAPI/v2/timeseries/data/',
       'v1': 'https://api.bls.gov/publicAPI/v1/timeseries/data/'}
KEY_ENV = 'BLS_API_KEY'
SOURCE = 'Source: U.S. Bureau of Labor Statistics (BLS Public Data API, api.bls.gov)'
DISCLAIMER = ('BLS.gov cannot vouch for the data or analyses derived from these data after the data have '
              'been retrieved from BLS.gov.')
LIMITS = {'v2': {'series': 50, 'years': 20, 'daily': 500}, 'v1': {'series': 25, 'years': 10, 'daily': 25}}
BURST = (50, 10.0)            # 50 queries per 10 seconds (BLS v2 FAQ), across every worker
BURST_WAIT = 10.0
KEYLESS_NOTE = ('No BLS_API_KEY is set: the keyless v1 API was used (25 queries a day for the whole '
                'organisation, 10 years and 25 series a query, no series titles). Register a free key at '
                'https://data.bls.gov/registrationEngine/ and set BLS_API_KEY.')


def _tier(config) -> Tuple[str, Optional[str]]:
    key = odc.env_key(KEY_ENV, config)
    return ('v2', key) if key else ('v1', None)


def _date_of(year: str, period: str) -> Optional[str]:
    """BLS period codes as human periods; annual averages (M13, Q05, S03) give None."""
    p = (period or '').upper()
    if re.fullmatch(r'M(0[1-9]|1[0-2])', p):
        return f'{year}-{p[1:]}'
    if re.fullmatch(r'Q0[1-4]', p):
        return f'{year}-Q{p[2]}'
    if re.fullmatch(r'S0[12]', p):
        return f'{year}-S{p[2]}'
    if p == 'A01':
        return str(year)
    return None


def _frequency(dates: List[str]) -> Optional[str]:
    d = dates[0] if dates else ''
    if re.fullmatch(r'\d{4}-\d{2}', d):
        return 'Monthly'
    if '-Q' in d:
        return 'Quarterly'
    if '-S' in d:
        return 'Semiannual'
    return 'Annual' if d else None


def query(series: List[str], start_year: int, end_year: int, config=None) -> Dict[str, Any]:
    """One BLS query: ``{api_version, series: [{series_id, label, observations}], messages}``."""
    tier, key = _tier(config)
    lim = LIMITS[tier]
    series = list(dict.fromkeys(s.strip().upper() for s in series if s and s.strip()))
    if not series:
        raise ValueError('series is required: one or more BLS series ids such as CUUR0000SA0')
    if len(series) > lim['series']:
        raise ValueError(f'BLS {tier} takes at most {lim["series"]} series a query; {len(series)} given')
    if end_year < start_year:
        raise ValueError('to_year is before from_year')
    if end_year - start_year + 1 > lim['years']:
        raise ValueError(f'BLS {tier} returns at most {lim["years"]} years a query; ask for a shorter range'
                         + ('' if key else ' (or set BLS_API_KEY for 20 years)'))
    odc.take_slot(f'opendata:bls:{tier}:daily', lim['daily'], 86400.0, 0, f'BLS {tier} daily')
    odc.take_slot('opendata:bls:burst', BURST[0], BURST[1], BURST_WAIT, 'BLS')
    body: Dict[str, Any] = {'seriesid': series, 'startyear': str(start_year), 'endyear': str(end_year)}
    if key:
        body.update({'registrationkey': key, 'catalog': True})
    r = odc.get(URL[tier], 'BLS', method='POST', json=body, headers={'Content-Type': 'application/json'})
    if r.status_code == 429:
        raise ValueError('BLS: rate limit reached (HTTP 429); try again later')
    if r.status_code >= 400:
        raise ValueError(f'BLS answered HTTP {r.status_code}')
    try:
        data = r.json()
    except ValueError:
        raise ValueError('BLS answered with something other than JSON')
    messages = [str(m) for m in (data.get('message') or []) if m
                and not (not key and str(m).startswith('Unable to get Catalog Data'))]   # v1 has no catalog
    if data.get('status') != 'REQUEST_SUCCEEDED':
        text = '; '.join(messages) or str(data.get('status'))
        if 'threshold' in text.lower():
            raise ValueError(f'BLS daily rate limit reached: {text}')
        raise ValueError(f'BLS did not process the request: {text}')
    out = []
    for s in (data.get('Results') or {}).get('series') or []:
        obs = []
        for row in s.get('data') or []:
            d = _date_of(row.get('year'), row.get('period'))
            if d is None:
                continue
            notes = [f.get('text') for f in row.get('footnotes') or [] if isinstance(f, dict) and f.get('text')]
            obs.append({'date': d, 'value': odc.number(row.get('value')),
                        'preliminary': any((f.get('code') or '') == 'P' for f in row.get('footnotes') or []
                                           if isinstance(f, dict)),
                        **({'footnotes': notes} if notes else {})})
        obs.sort(key=lambda o: o['date'])
        catalog = s.get('catalog') or {}
        out.append({'series_id': s.get('seriesID'), 'label': catalog.get('series_title'), 'observations': obs})
    return {'api_version': tier, 'series': out, 'messages': messages}


def envelope(tier: str) -> Dict[str, Any]:
    out = {'source': SOURCE, 'disclaimer': DISCLAIMER, 'retrieved': date.today().isoformat(),
           'api_version': 'v2' if tier == 'v2' else 'v1 (keyless)'}
    if tier != 'v2':
        out['note'] = KEYLESS_NOTE
    return out


class BlsBaseTool(odc.OpenDataTool):
    keyless_fallback = True          # v1 answers without a key (25 queries a day)


class BlsSeriesTool(BlsBaseTool):
    """bls_series: any BLS series ids for a span of years."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        series = arguments.get('series') or []
        if isinstance(series, str):
            series = [s for s in re.split(r'[,\s]+', series) if s]
        this_year = date.today().year
        end = int(arguments.get('to_year') or this_year)
        start = int(arguments.get('from_year') or end - 2)
        res = query(series, start, end, self.config)
        out = envelope(res['api_version'])
        series_out = []
        for s in res['series']:
            series_out.append({'series_id': s['series_id'], 'label': s['label'],
                               'frequency': _frequency([o['date'] for o in s['observations']]),
                               'observation_count': len(s['observations']), 'observations': s['observations']})
        out.update({'from_year': start, 'to_year': end, 'series_count': len(series_out), 'series': series_out,
                    'messages': res['messages']})
        return out


# ── curated tools ────────────────────────────────────────────────────────────
# measure -> (seasonally adjusted id, not seasonally adjusted id, label, unit, kind)
# kind: index (adds change_12m_percent), level (adds change from the previous period), rate (as published)

CPI = {
    'all_items': ('CUSR0000SA0', 'CUUR0000SA0', 'CPI-U, all items, U.S. city average'),
    'core': ('CUSR0000SA0L1E', 'CUUR0000SA0L1E', 'CPI-U, all items less food and energy (core)'),
    'food': ('CUSR0000SAF1', 'CUUR0000SAF1', 'CPI-U, food'),
    'energy': ('CUSR0000SA0E', 'CUUR0000SA0E', 'CPI-U, energy'),
    'shelter': ('CUSR0000SAH1', 'CUUR0000SAH1', 'CPI-U, shelter'),
}
PPI = {
    'final_demand': ('WPSFD4', 'WPUFD4', 'PPI, final demand'),
    'core': ('WPSFD49116', 'WPUFD49116', 'PPI, final demand less foods, energy and trade services'),
    'goods': ('WPSFD41', 'WPUFD41', 'PPI, final demand goods'),
    'services': ('WPSFD42', 'WPUFD42', 'PPI, final demand services'),
}
PAYROLLS = {        # CES, seasonally adjusted
    'total_nonfarm': ('CES0000000001', 'Total nonfarm employment', 'thousands of jobs', 'level'),
    'total_private': ('CES0500000001', 'Total private employment', 'thousands of jobs', 'level'),
    'manufacturing': ('CES3000000001', 'Manufacturing employment', 'thousands of jobs', 'level'),
    'average_hourly_earnings': ('CES0500000003', 'Average hourly earnings, all private employees',
                                'US dollars per hour', 'index'),
}
UNEMPLOYMENT = {    # CPS, seasonally adjusted, percent
    'u3': ('LNS14000000', 'Unemployment rate (U-3)'),
    'u6': ('LNS13327709', 'Total unemployed plus marginally attached and part time for economic reasons (U-6)'),
    'participation': ('LNS11300000', 'Labor force participation rate'),
    'employment_population': ('LNS12300000', 'Employment-population ratio'),
}
ECI = {             # civilian workers; (index SA, 12-month change NSA, 3-month change SA)
    'total_compensation': ('CIS1010000000000I', 'CIU1010000000000A', 'CIS1010000000000Q',
                           'ECI, total compensation, civilian workers'),
    'wages_and_salaries': ('CIS1020000000000I', 'CIU1020000000000A', 'CIS1020000000000Q',
                           'ECI, wages and salaries, civilian workers'),
    'benefits': ('CIS1030000000000I', 'CIU1030000000000A', 'CIS1030000000000Q',
                 'ECI, benefits, civilian workers'),
}
JOLTS = {           # total nonfarm, seasonally adjusted
    'openings': ('JTS000000000000000JOL', 'Job openings', 'thousands', 'level'),
    'hires': ('JTS000000000000000HIL', 'Hires', 'thousands', 'level'),
    'quits': ('JTS000000000000000QUL', 'Quits', 'thousands', 'level'),
    'layoffs': ('JTS000000000000000LDL', 'Layoffs and discharges', 'thousands', 'level'),
    'openings_rate': ('JTS000000000000000JOR', 'Job openings rate', 'percent', 'rate'),
    'quits_rate': ('JTS000000000000000QUR', 'Quits rate', 'percent', 'rate'),
}


def _measures(arguments: Dict[str, Any], table: Dict[str, Any], default: str) -> List[str]:
    measures = arguments.get('measures') or [default]
    if isinstance(measures, str):
        measures = [measures]
    bad = [m for m in measures if m not in table]
    if bad:
        raise ValueError(f'unknown measure(s) {bad}; use {sorted(table)}')
    return list(dict.fromkeys(measures))


def _in_range(d: str, start: date, end: date) -> bool:
    """Whether the period ``d`` (YYYY, YYYY-MM, YYYY-Qn, YYYY-Sn) overlaps [start, end]."""
    y = int(d[:4])
    if re.fullmatch(r'\d{4}-\d{2}', d):
        first = last = int(d[5:])
    elif '-Q' in d:
        q = int(d[-1])
        first, last = 3 * q - 2, 3 * q
    elif '-S' in d:
        first, last = (1, 6) if d.endswith('1') else (7, 12)
    else:
        first, last = 1, 12
    return (y, last) >= (start.year, start.month) and (y, first) <= (end.year, end.month)


def _lag_key(d: str, steps_back: int) -> str:
    """The period ``steps_back`` periods of its own kind before ``d`` (12 months, 4 quarters ...)."""
    y = int(d[:4])
    if re.fullmatch(r'\d{4}-\d{2}', d):
        m = y * 12 + int(d[5:]) - 1 - steps_back
        return f'{m // 12}-{m % 12 + 1:02d}'
    if '-Q' in d:
        q = y * 4 + int(d[-1]) - 1 - steps_back
        return f'{q // 4}-Q{q % 4 + 1}'
    return str(y - steps_back)


def curated(config, arguments: Dict[str, Any], specs: List[Dict[str, Any]], default_period: str) -> Dict:
    """Fetch the specs' series (one query), add derived changes, keep the asked period."""
    period = arguments.get('period') or default_period
    start, end = parse_period(period)
    need_lag = any(s['kind'] in ('index', 'level') for s in specs)
    first_year = start.year - (1 if need_lag else 0)
    tier, _ = _tier(config)
    years = LIMITS[tier]['years']
    if end.year - first_year + 1 > years:
        raise ValueError(f'the period spans more than the {years} years a BLS {tier} query returns'
                         + ('' if tier == 'v2' else '; set BLS_API_KEY for 20 years'))
    res = query([s['id'] for s in specs], first_year, end.year, config)
    by_id = {s['series_id']: s for s in res['series']}
    out = envelope(res['api_version'])
    series_out = []
    for spec in specs:
        s = by_id.get(spec['id']) or {'observations': []}
        obs = s['observations']
        values = {o['date']: o['value'] for o in obs}
        kept = []
        for i, o in enumerate(obs):
            if not _in_range(o['date'], start, end):
                continue
            o = dict(o)
            if spec['kind'] == 'index':
                lag = 12 if re.fullmatch(r'\d{4}-\d{2}', o['date']) else 4 if '-Q' in o['date'] else 1
                prev = values.get(_lag_key(o['date'], lag))
                o['change_12m_percent'] = (round((o['value'] / prev - 1) * 100, 2)
                                           if o['value'] is not None and prev else None)
            elif spec['kind'] == 'level':
                prev = values.get(_lag_key(o['date'], 1))
                o['change'] = (round(o['value'] - prev, 3) if o['value'] is not None and prev is not None
                               else None)
            kept.append(o)
        series_out.append({'measure': spec['measure'], 'series_id': spec['id'], 'label': spec['label'],
                           'unit': spec['unit'], 'seasonally_adjusted': spec.get('sa'),
                           'frequency': _frequency([o['date'] for o in kept]),
                           'observation_count': len(kept), 'observations': kept})
    out.update({'period': period, 'series_count': len(series_out), 'series': series_out,
                'messages': res['messages']})
    return out


class _PriceIndexTool(BlsBaseTool):
    TABLE: Dict[str, Tuple[str, str, str]] = {}
    UNIT = ''
    DEFAULT_PERIOD = 'last 24 months'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        sa = arguments.get('seasonally_adjusted', True) is not False
        specs = [{'measure': m, 'id': self.TABLE[m][0 if sa else 1], 'label': self.TABLE[m][2],
                  'unit': self.UNIT, 'kind': 'index', 'sa': sa}
                 for m in _measures(arguments, self.TABLE, next(iter(self.TABLE)))]
        return curated(self.config, arguments, specs, self.DEFAULT_PERIOD)


class BlsCpiTool(_PriceIndexTool):
    """bls_cpi: Consumer Price Index for All Urban Consumers (CPI-U), index 1982-84=100."""
    TABLE = CPI
    UNIT = 'index, 1982-84=100'


class BlsPpiTool(_PriceIndexTool):
    """bls_ppi: Producer Price Index, final demand, index November 2009=100."""
    TABLE = PPI
    UNIT = 'index, Nov 2009=100'


class _TableTool(BlsBaseTool):
    TABLE: Dict[str, Tuple[str, str, str, str]] = {}
    DEFAULT = ''
    DEFAULT_PERIOD = 'last 24 months'
    SA = True

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        specs = [{'measure': m, 'id': self.TABLE[m][0], 'label': self.TABLE[m][1], 'unit': self.TABLE[m][2],
                  'kind': self.TABLE[m][3], 'sa': self.SA}
                 for m in _measures(arguments, self.TABLE, self.DEFAULT)]
        return curated(self.config, arguments, specs, self.DEFAULT_PERIOD)


class BlsPayrollsTool(_TableTool):
    """bls_payrolls: Current Employment Statistics (nonfarm payrolls), seasonally adjusted."""
    TABLE = PAYROLLS
    DEFAULT = 'total_nonfarm'


class BlsUnemploymentRateTool(_TableTool):
    """bls_unemployment_rate: Current Population Survey rates, seasonally adjusted, percent."""
    TABLE = {k: (v[0], v[1], 'percent', 'rate') for k, v in UNEMPLOYMENT.items()}
    DEFAULT = 'u3'


class BlsJobOpeningsTool(_TableTool):
    """bls_job_openings: JOLTS, total nonfarm, seasonally adjusted."""
    TABLE = JOLTS
    DEFAULT = 'openings'


ECI_KINDS = {'index': (0, 'index, Dec 2005=100', 'index', True),
             '12_month_change': (1, 'percent change over 12 months', 'rate', False),
             '3_month_change': (2, 'percent change over 3 months', 'rate', True)}


class BlsEmploymentCostIndexTool(BlsBaseTool):
    """bls_employment_cost_index: ECI for civilian workers, quarterly."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        kind = arguments.get('series_type') or '12_month_change'
        if kind not in ECI_KINDS:
            raise ValueError(f'series_type must be one of {sorted(ECI_KINDS)}')
        pos, unit, k, sa = ECI_KINDS[kind]
        specs = [{'measure': m, 'id': ECI[m][pos], 'label': ECI[m][3], 'unit': unit,
                  'kind': 'rate' if k == 'rate' else 'index', 'sa': sa}
                 for m in _measures(arguments, ECI, 'total_compensation')]
        return curated(self.config, arguments, specs, 'last 3 years')
