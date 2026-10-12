"""
SAJHA MCP Server — OECD tools (tool folder ``oecd``; Open Data Tools §4, P2; Roadmap L33).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The OECD Data Explorer answers SDMX 2.1 REST at ``sdmx.oecd.org/public/rest``. These tools are an
``oecd`` host profile on the shared SDMX client (``sajha/tools/impl/sdmx_client.py``, registered
below): flow references are ``AGENCY,ID[,VERSION]`` (``OECD.SDD.STES,DSD_STES@DF_CLI``) and SDMX-CSV
is selected with ``format=csvfile``. Every fetch goes through the outbound fetch guard and HTTP proxy.
No key.

**One shared hourly budget.** The OECD asks API users to stay at about 60 downloads an hour per IP.
Every request (data, the dataflow list) first takes a slot in one sliding window kept in the state
store (``opendata:oecd:requests``), so all workers behind the organisation's egress IP share the
budget; results are cached by each tool's ``cache_ttl`` (hours) and the dataflow list for a day.

Terms: OECD material published from July 2024 is CC BY 4.0 (the open-by-default policy); every result
carries ``source``. Countries are ISO 3166 alpha-3 on the wire; alpha-2 codes and names are converted.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl import sdmx_client
from sajha.tools.impl.bis_tools import area_code, period_params
from sajha.tools.impl.country_codes import COUNTRIES
from sajha.tools.impl.open_data_common import OpenDataTool, take_slot

SOURCE = 'Source: OECD Data Explorer (sdmx.oecd.org), licensed under CC BY 4.0'
HOST = sdmx_client.register_host(sdmx_client.SdmxHost(
    name='oecd', base_url='https://sdmx.oecd.org/public/rest', agency='OECD', agency_flow_ref=True,
    csv_format='csvfile', csv_accept='application/vnd.sdmx.data+csv', source=SOURCE))

THROTTLE_KEY = 'opendata:oecd:requests'
THROTTLE_LIMIT = 50            # requests an hour across every worker (the OECD asks for about 60)
THROTTLE_WINDOW = 3600.0
THROTTLE_WAIT = 5.0            # an hourly budget: waiting longer does not help
_FLOWS_TTL = 86400.0

AGGREGATES = {'OECD', 'G20', 'G7', 'EA20', 'EA21', 'EU27_2020', 'OECDE', 'G7M', 'OECD_REP', 'W'}
_ALPHA3 = {a2: a3 for a3, (a2, _m49, _name) in COUNTRIES.items() if a2}
_NAMED = {'euro area': 'EA20', 'eurozone': 'EA20', 'xm': 'EA20', 'ea': 'EA20', 'oecd': 'OECD',
          'g20': 'G20', 'g7': 'G7', 'eu': 'EU27_2020', 'european union': 'EU27_2020', 'world': 'W'}

UNITS = {'PA': 'Percent per year', 'PT_LF': 'Percent of the labour force', 'GR': 'Growth rate, percent',
         'IX': 'Index', 'PC': 'Percent', 'XDC': 'National currency', 'USD_PPP': 'US dollars, PPP',
         'PT_B1GQ': 'Percent of GDP', 'USD_EXC': 'US dollars, exchange rates', 'NUM': 'Number'}
_MULT = {'0': None, '3': 'thousands', '6': 'millions', '9': 'billions', '12': 'trillions'}


def ref_area(value: Any) -> str:
    """An OECD area code (ISO alpha-3, or an aggregate such as OECD, G20, EA20)."""
    v = str(value or '').strip()
    named = _NAMED.get(v.lower())
    if named:
        return named
    up = v.upper()
    if up in AGGREGATES:
        return up
    if len(up) == 3 and up in COUNTRIES:
        return up
    a2 = area_code(v)
    if a2 == 'XM':
        return 'EA20'
    a3 = _ALPHA3.get(a2)
    if not a3:
        raise ValueError(f'Unknown country {value!r}: use an ISO 3166 code (USA, DE) or OECD, G20, EA20')
    return a3


def areas(arguments: Dict[str, Any]) -> str:
    countries = arguments.get('countries') or []
    if isinstance(countries, str):
        countries = [c for c in re.split(r'[,+]+', countries) if c.strip()]
    if not countries:
        raise ValueError('countries is required (one or more codes, e.g. ["USA", "DEU", "OECD"])')
    return '+'.join(dict.fromkeys(ref_area(c) for c in countries))


def _slot() -> None:
    take_slot(THROTTLE_KEY, THROTTLE_LIMIT, THROTTLE_WINDOW, THROTTLE_WAIT, 'OECD')


def _series_out(s: Dict[str, Any]) -> Dict[str, Any]:
    dims, attrs = s.get('dimensions') or {}, s.get('attributes') or {}
    unit = dims.get('UNIT_MEASURE') or attrs.get('UNIT_MEASURE')
    obs = [{'date': o['period'], 'value': o['value']} for o in s.get('observations') or []]
    freq = dims.get('FREQ') or ''
    return {
        'key': s.get('key'),
        'country': dims.get('REF_AREA'),
        'unit': UNITS.get(str(unit), unit),
        'unit_code': unit,
        'unit_multiplier': _MULT.get(str(attrs.get('UNIT_MULT')), attrs.get('UNIT_MULT')),
        'base_period': attrs.get('BASE_PER') or attrs.get('REF_YEAR_PRICE'),
        'frequency': sdmx_client._FREQ.get(freq, freq or None),
        'dimensions': dims,
        'observation_count': len(obs),
        'observations': obs,
    }


def fetch(flow: str, key: str, period: Optional[str], max_series: int = 50,
          keep=None) -> Dict[str, Any]:
    """One data query; ``keep(dimensions) -> bool`` drops series the key's ``+`` lists cross-matched."""
    q = period_params(period)
    _slot()
    try:
        result = sdmx_client.fetch('oecd', flow, key, timeout=60.0, **q)
    except sdmx_client.SdmxError as e:
        raise ValueError(f'OECD: {e}') from e
    raw = [s for s in result['series'] if keep is None or keep(s.get('dimensions') or {})]
    series = sorted((_series_out(s) for s in raw), key=lambda s: s['key'] or '')
    out: Dict[str, Any] = {'dataflow': result['flow'], 'key': key, 'period': period or None, 'source': SOURCE,
                           'series_count': len(series), 'series': series[:max_series]}
    if len(series) > max_series:
        out['truncated'] = True
        out['note'] = f'{len(series)} series matched; the first {max_series} are returned. Narrow the key.'
    elif not series:
        out['note'] = 'The OECD returned no data for this selection and period.'
    return out


# ── the dataflow list (search, and an id without its agency) ────────────────

_flows: Dict[str, Any] = {'at': 0.0, 'rows': []}
_lock = threading.Lock()


def dataflows() -> List[Dict[str, str]]:
    now = time.monotonic()
    with _lock:
        if _flows['rows'] and now - _flows['at'] < _FLOWS_TTL:
            return _flows['rows']
    _slot()
    try:
        rows = sdmx_client.dataflows('oecd', timeout=90.0)
    except sdmx_client.SdmxError as e:
        raise ValueError(f'OECD: {e}') from e
    with _lock:
        _flows.update(at=now, rows=rows)
    return rows


def flow_ref(dataflow: str) -> str:
    """``AGENCY,ID[,VERSION]`` as given, or a bare id resolved through the dataflow list."""
    d = str(dataflow or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.@,\-]{3,120}', d):
        raise ValueError(f'dataflow must look like OECD.SDD.STES,DSD_STES@DF_CLI, not {dataflow!r}')
    if ',' in d:
        return d
    matches = [f for f in dataflows() if f['id'].upper() == d.upper() or f['id'].upper().endswith('@' + d.upper())]
    if len(matches) != 1:
        raise ValueError(f'OECD dataflow {d!r} is ' + ('unknown' if not matches else 'ambiguous') +
                         '; give AGENCY,ID (find it with oecd_search)')
    return f"{matches[0]['agency']},{matches[0]['id']}"


class OecdBaseTool(OpenDataTool):
    pass


class OecdSearchTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        text = str(arguments.get('text') or '').strip()
        words = [w for w in re.split(r'\W+', text.lower()) if w]
        if not words:
            raise ValueError('text is required (words to look for in dataflow names or ids)')
        limit = int(arguments.get('limit') or 20)
        hits = [f for f in dataflows() if all(w in f"{f['name']} {f['id']}".lower() for w in words)]
        hits.sort(key=lambda f: (f['name'].lower(), f['id']))
        out = {'text': text, 'source': SOURCE, 'count': len(hits),
               'dataflows': [{'dataflow': f"{f['agency']},{f['id']}", 'name': f['name'],
                              'version': f['version']} for f in hits[:limit]]}
        if len(hits) > limit:
            out['truncated'] = True
        if not hits:
            out['note'] = 'No OECD dataflow name or id contains all of these words.'
        return out


class OecdGetSeriesTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        key = str(arguments.get('key') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_+.\-]*', key):
            raise ValueError('key is dimension codes joined by dots, + for several codes, empty for all')
        return fetch(flow_ref(arguments.get('dataflow')), key, arguments.get('period'),
                     max_series=int(arguments.get('max_series') or 20))


CLI_MEASURES = {'cli': 'LI', 'business_confidence': 'BCICP', 'consumer_confidence': 'CCICP'}


class OecdLeadingIndicatorsTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ms = arguments.get('indicators') or ['cli']
        m = '+'.join(dict.fromkeys(CLI_MEASURES[x] for x in ms))
        # amplitude adjusted, long-term average = 100
        return fetch('OECD.SDD.STES,DSD_STES@DF_CLI', f'{areas(arguments)}.M.{m}.IX._Z.AA.IX._Z.H',
                     arguments.get('period'))


# indicator -> (MEASURE, UNIT_MEASURE, ACTIVITY, ADJUSTMENT, TRANSFORMATION) in DF_KEI
KEI = {
    'cpi_inflation': ('CP', 'GR', '_Z', '_Z', 'GY'),
    'unemployment_rate': ('UNEMP', 'PT_LF', '_T', 'Y', '_Z'),
    'long_term_rate': ('IRLT', 'PA', '_Z', '_Z', '_Z'),
    'short_term_rate': ('IR3TIB', 'PA', '_Z', '_Z', '_Z'),
    'industrial_production_growth': ('PRVM', 'GR', 'BTE', 'Y', 'GY'),
    'leading_indicator': ('LI', 'IX', '_T', 'AA', '_Z'),
}


class OecdMainEconomicIndicatorsTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = arguments.get('indicators') or ['cpi_inflation', 'unemployment_rate']
        chosen = [KEI[n] for n in dict.fromkeys(names)]
        wanted = set(chosen)
        parts = ['+'.join(dict.fromkeys(t[i] for t in chosen)) for i in range(5)]
        freq = {'monthly': 'M', 'quarterly': 'Q'}[arguments.get('frequency') or 'monthly']
        dims = ('MEASURE', 'UNIT_MEASURE', 'ACTIVITY', 'ADJUSTMENT', 'TRANSFORMATION')
        out = fetch('OECD.SDD.STES,DSD_KEI@DF_KEI', f"{areas(arguments)}.{freq}.{'.'.join(parts)}",
                    arguments.get('period'), keep=lambda d: tuple(d.get(x) for x in dims) in wanted)
        names_of = {v: k for k, v in KEI.items()}
        for s in out['series']:
            s['indicator'] = names_of.get(tuple(s['dimensions'].get(x) for x in dims))
        return out


# transaction -> (SECTOR, TRANSACTION, ACTIVITY, EXPENDITURE) in DF_QNA, table T0102
QNA = {
    'gdp': ('S1', 'B1GQ', '_Z', '_Z'),
    'household_consumption': ('S1M', 'P3', '_Z', '_T'),
    'government_consumption': ('S13', 'P3', '_Z', '_T'),
    'gross_fixed_capital_formation': ('S1', 'P51G', '_T', '_Z'),
    'exports': ('S1', 'P6', '_Z', '_Z'),
    'imports': ('S1', 'P7', '_Z', '_Z'),
}
# measure -> (UNIT_MEASURE, PRICE_BASE, TRANSFORMATION)
QNA_MEASURES = {
    'growth_qoq': ('PC', 'L', 'G1'),
    'growth_yoy': ('PC', 'L', 'GY'),
    'volume': ('XDC', 'L', 'N'),
    'current_prices': ('XDC', 'V', 'N'),
}


class OecdQuarterlyNationalAccountsTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        sector, tx, act, exp = QNA[arguments.get('transaction') or 'gdp']
        unit, price, transf = QNA_MEASURES[arguments.get('measure') or 'growth_qoq']
        key = f'Q.Y.{areas(arguments)}.{sector}.S1.{tx}._Z.{act}.{exp}.{unit}.{price}.{transf}.T0102'
        return fetch('OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA', key, arguments.get('period'))


EO = {
    'gdp_growth': 'GDPV_ANNPCT', 'inflation': 'CPI_YTYPCT', 'core_inflation': 'PCORE_YTYPCT',
    'unemployment_rate': 'UNR', 'fiscal_balance': 'NLGQ', 'government_debt': 'GGFLQ',
    'current_account': 'CBGDPR', 'short_term_rate': 'IRS', 'long_term_rate': 'IRL',
}


class OecdEconomicOutlookTool(OecdBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        names = arguments.get('indicators') or ['gdp_growth', 'inflation', 'unemployment_rate']
        measures = '+'.join(dict.fromkeys(EO[n] for n in names))
        out = fetch('OECD.ECO.MAD,DSD_EO@DF_EO', f'{areas(arguments)}.{measures}.A', arguments.get('period'))
        names_of = {v: k for k, v in EO.items()}
        this_year = date.today().year
        for s in out['series']:
            s['indicator'] = names_of.get(s['dimensions'].get('MEASURE'))
            for o in s['observations']:
                o['projection'] = bool(re.match(r'\d{4}', o['date'])) and int(o['date'][:4]) >= this_year
        out['note'] = out.get('note') or ('The latest OECD Economic Outlook; observations from the current year on '
                                          'are projections (projection: true).')
        return out
