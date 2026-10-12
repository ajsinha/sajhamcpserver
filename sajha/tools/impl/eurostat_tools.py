"""
SAJHA MCP Server — Eurostat tools (tool folder ``eurostat``; Open Data Tools §4, P2; Roadmap L33).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Eurostat publishes its database over SDMX 2.1 REST at
``ec.europa.eu/eurostat/api/dissemination/sdmx/2.1``. The data tools are a ``eurostat`` host profile
on the shared SDMX client (``sajha/tools/impl/sdmx_client.py``, registered below), read as SDMX-CSV
(``format=SDMX-CSV``). ``eurostat_search`` reads Eurostat's table of contents (the catalogue API,
``/catalogue/toc/txt``), cached per process for a day. Every fetch goes through the outbound fetch
guard and HTTP proxy. No key.

Terms (the Eurostat copyright notice, checked 2026-10-11): reuse is allowed with acknowledgement
(CC BY 4.0); data that Eurostat marks as belonging to sources other than Eurostat, which includes
figures for countries outside the EU, EFTA and the candidate countries (for example the United States
or Japan), may not be reused commercially. Every result carries ``source``; a result that contains
such a country also carries ``reuse_note``.

Eurostat validates every code in a key against the dataset's structure and refuses the whole query
when one is not allowed (HTTP 400 ``INVALID_QUERY_DIMENSION_VALUE``); the message is passed on. The
euro area is ``EA21`` (Bulgaria joined on 1 January 2026), the EU ``EU27_2020``, Greece ``EL`` and the
United Kingdom ``UK`` in Eurostat's own codes; the tools accept ISO codes and names and convert them.
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl import sdmx_client
from sajha.tools.impl.bis_tools import area_code, period_params
from sajha.tools.impl.open_data_common import OpenDataTool, get

BASE = 'https://ec.europa.eu/eurostat/api/dissemination'
SOURCE = 'Source: Eurostat (ec.europa.eu/eurostat), reused under the Eurostat copyright notice (CC BY 4.0)'
REUSE_NOTE = ('Eurostat data for countries outside the EU, EFTA and the candidate countries comes from other '
              'sources and may not be reused commercially (Eurostat copyright notice).')
HOST = sdmx_client.register_host(sdmx_client.SdmxHost(
    name='eurostat', base_url=f'{BASE}/sdmx/2.1', csv_format='SDMX-CSV',
    csv_accept='application/vnd.sdmx.data+csv;version=1.0.0', source=SOURCE))

EURO_AREA, EU = 'EA21', 'EU27_2020'
_EU27 = {'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'EL', 'ES', 'FI', 'FR', 'HR', 'HU', 'IE', 'IT', 'LT',
         'LU', 'LV', 'MT', 'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK'}
_EFTA_CANDIDATES = {'IS', 'LI', 'NO', 'CH', 'AL', 'BA', 'GE', 'MD', 'ME', 'MK', 'RS', 'TR', 'UA', 'XK'}
EUROPEAN = _EU27 | _EFTA_CANDIDATES
_ISO_TO_ESTAT = {'GR': 'EL', 'GB': 'UK', 'XM': EURO_AREA}
_NAMED = {'euro area': EURO_AREA, 'eurozone': EURO_AREA, 'ea': EURO_AREA, 'eu': EU, 'european union': EU,
          'eu27': EU, 'greece': 'EL', 'united kingdom': 'UK', 'uk': 'UK'}

UNITS = {
    'RCH_A': 'Annual rate of change, percent',
    'RCH_M': 'Monthly rate of change, percent',
    'RCH_Q': 'Quarterly rate of change, percent',
    'I25': 'Index, 2025 = 100',
    'I15': 'Index, 2015 = 100',
    'I15_Q': 'Index, 2015 = 100',
    'CLV_PCH_PRE': 'Percentage change on previous period (chain-linked volumes)',
    'CLV_PCH_SM': 'Percentage change on same period of previous year (chain-linked volumes)',
    'CP_MEUR': 'Current prices, million euro',
    'PC_ACT': 'Percentage of the labour force',
    'PC_GDP': 'Percentage of GDP',
    'MIO_EUR': 'Million euro',
    'THS_PER': 'Thousand persons',
}
FLAGS = {'b': 'break in time series', 'c': 'confidential', 'd': 'definition differs', 'e': 'estimated',
         'f': 'forecast', 'n': 'not significant', 'p': 'provisional', 'r': 'revised', 's': 'Eurostat estimate',
         'u': 'low reliability', 'z': 'not applicable'}
_DIM_TTL = 86400.0
_TOC_TTL = 86400.0
_LAST_UPDATE = re.compile(r'^(\d{2})/(\d{2})/(\d{2})')


def geo_code(value: Any) -> str:
    """A Eurostat geo code from an ISO alpha-2 or alpha-3 code, a name, or a Eurostat code (EA21,
    EU27_2020, EL, UK)."""
    v = str(value or '').strip()
    if not v:
        raise ValueError('an empty country code')
    named = _NAMED.get(v.lower())
    if named:
        return named
    up = v.upper()
    if re.fullmatch(r'(EA|EU)\d{2}(_\d{4})?', up):
        return up
    code = area_code(v)
    return _ISO_TO_ESTAT.get(code, code)


def geos(arguments: Dict[str, Any]) -> str:
    countries = arguments.get('countries') or []
    if isinstance(countries, str):
        countries = [c for c in re.split(r'[,+]+|\s{2,}', countries) if c.strip()]
    if not countries:
        raise ValueError('countries is required (one or more codes, e.g. ["DE", "FR", "EA"])')
    return '+'.join(dict.fromkeys(geo_code(c) for c in countries))


# ── structure (the dimension order of a dataset) ───────────────────────────

_dims_cache: Dict[str, Tuple[float, List[str]]] = {}
_lock = threading.Lock()


def dimension_ids(dataset: str, timeout: float = 30.0) -> List[str]:
    """The dataset's dimensions in key order (from its data structure definition, cached a day)."""
    ds = dataset.strip().upper()
    now = time.monotonic()
    with _lock:
        hit = _dims_cache.get(ds)
        if hit and now - hit[0] < _DIM_TTL:
            return hit[1]
    try:
        root = sdmx_client._structure(HOST, f'datastructure/ESTAT/{ds}/latest', timeout)
    except sdmx_client.SdmxError as e:
        raise ValueError(f'Eurostat: unknown dataset {dataset!r} ({e})') from e
    ns = '{http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure}'
    dims = sorted(((int(d.get('position') or 0), d.get('id')) for d in root.iter(f'{ns}Dimension')),
                  key=lambda x: x[0])
    ids = [i for _, i in dims if i]
    if not ids:
        raise ValueError(f'Eurostat: dataset {dataset!r} has no dimensions in its structure')
    with _lock:
        _dims_cache[ds] = (now, ids)
    return ids


def build_key(dataset: str, filters: Dict[str, Any]) -> str:
    """A dotted SDMX key from ``{dimension: code or [codes]}``; a dimension left out matches all."""
    ids = dimension_ids(dataset)
    lower = {i.lower(): i for i in ids}
    chosen: Dict[str, str] = {}
    for k, v in (filters or {}).items():
        dim = lower.get(str(k).strip().lower())
        if dim is None:
            raise ValueError(f'Eurostat dataset {dataset} has no dimension {k!r}; its dimensions are '
                             f'{", ".join(ids)}')
        values = v if isinstance(v, (list, tuple)) else re.split(r'[+,]', str(v))
        codes = [str(x).strip() for x in values if str(x).strip()]
        if dim == 'geo':
            codes = [geo_code(c) for c in codes]
        chosen[dim] = '+'.join(codes)
    return '.'.join(chosen.get(i, '') for i in ids)


# ── data ─────────────────────────────────────────────────────────────────────

def _iso_date(stamp: Any) -> Optional[str]:
    m = _LAST_UPDATE.match(str(stamp or ''))
    return f'20{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def _series_out(s: Dict[str, Any]) -> Dict[str, Any]:
    dims = dict(s.get('dimensions') or {})
    last_update = _iso_date(dims.pop('LAST UPDATE', None) or (s.get('attributes') or {}).get('LAST UPDATE'))
    unit = dims.get('unit')
    obs = []
    for o in s.get('observations') or []:
        item = {'date': o['period'], 'value': o['value']}
        flag = str(o.get('status') or o.get('OBS_FLAG') or '').strip()
        if flag:
            item['flag'] = flag
        obs.append(item)
    return {
        'key': '.'.join(str(v or '') for v in dims.values()),
        'country': dims.get('geo'),
        'unit': UNITS.get(unit, unit),
        'unit_code': unit,
        'frequency': sdmx_client._FREQ.get(dims.get('freq') or '', dims.get('freq')),
        'last_update': last_update,
        'dimensions': dims,
        'observation_count': len(obs),
        'observations': obs,
    }


def fetch(dataset: str, key: str, period: Optional[str], max_series: int = 50) -> Dict[str, Any]:
    q = period_params(period)
    try:
        result = sdmx_client.fetch('eurostat', dataset.strip().lower(), key, **q)
    except sdmx_client.SdmxError as e:
        raise ValueError(f'Eurostat: {e}') from e
    series = [_series_out(s) for s in result['series']]
    series.sort(key=lambda s: s['key'])
    out: Dict[str, Any] = {'dataset': dataset.strip().lower(), 'key': key, 'period': period or None,
                           'source': SOURCE, 'series_count': len(series), 'series': series[:max_series]}
    flags = sorted({o['flag'] for s in series for o in s['observations'] if o.get('flag')})
    if flags:
        out['flags'] = {f: FLAGS.get(f[:1].lower(), f) for f in flags}
    if any(s['country'] and s['country'] not in EUROPEAN and not s['country'].startswith(('EA', 'EU'))
           for s in series):
        out['reuse_note'] = REUSE_NOTE
    if len(series) > max_series:
        out['truncated'] = True
        out['note'] = f'{len(series)} series matched; the first {max_series} are returned. Narrow the filters.'
    elif not series:
        out['note'] = 'Eurostat returned no data for this selection and period.'
    return out


class EurostatBaseTool(OpenDataTool):
    pass


class EurostatGetSeriesTool(EurostatBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        dataset = str(arguments.get('dataset') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_$]{2,40}', dataset):
            raise ValueError(f'dataset must be a Eurostat dataset code such as prc_hicp_minr, not {dataset!r}')
        key = build_key(dataset, arguments.get('filters') or {})
        return fetch(dataset, key, arguments.get('period'), int(arguments.get('max_series') or 20))


class EurostatHicpTool(EurostatBaseTool):
    MEASURES = {'annual_rate': 'RCH_A', 'monthly_rate': 'RCH_M', 'index': 'I25'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        unit = self.MEASURES[arguments.get('measure') or 'annual_rate']
        item = str(arguments.get('item') or 'TOTAL').strip().upper()
        return fetch('prc_hicp_minr', f'M.{unit}.{item}.{geos(arguments)}', arguments.get('period'))


class EurostatGdpTool(EurostatBaseTool):
    MEASURES = {'growth_qoq': 'CLV_PCH_PRE', 'growth_yoy': 'CLV_PCH_SM', 'current_prices': 'CP_MEUR'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        unit = self.MEASURES[arguments.get('measure') or 'growth_qoq']
        return fetch('namq_10_gdp', f'Q.{unit}.SCA.B1GQ.{geos(arguments)}', arguments.get('period'))


class EurostatUnemploymentTool(EurostatBaseTool):
    SEX = {'total': 'T', 'male': 'M', 'female': 'F'}
    AGE = {'total': 'TOTAL', 'under_25': 'Y_LT25', '25_74': 'Y25-74'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        sex = self.SEX[arguments.get('sex') or 'total']
        age = self.AGE[arguments.get('age') or 'total']
        return fetch('une_rt_m', f'M.SA.{age}.PC_ACT.{sex}.{geos(arguments)}', arguments.get('period'))


class EurostatGovernmentDebtTool(EurostatBaseTool):
    UNITS = {'percent_of_gdp': 'PC_GDP', 'million_eur': 'MIO_EUR'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        unit = self.UNITS[arguments.get('unit') or 'percent_of_gdp']
        return fetch('gov_10q_ggdebt', f'Q.GD.S13.{unit}.{geos(arguments)}', arguments.get('period'))


class EurostatHousePricesTool(EurostatBaseTool):
    MEASURES = {'annual_rate': 'RCH_A', 'quarterly_rate': 'RCH_Q', 'index': 'I15_Q'}
    PURCHASES = {'total': 'TOTAL', 'new': 'DW_NEW', 'existing': 'DW_EXST'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        unit = self.MEASURES[arguments.get('measure') or 'annual_rate']
        purchase = self.PURCHASES[arguments.get('dwellings') or 'total']
        return fetch('prc_hpi_q', f'Q.{purchase}.{unit}.{geos(arguments)}', arguments.get('period'))


# ── search: the table of contents ───────────────────────────────────────────

_toc: Dict[str, Any] = {'at': 0.0, 'rows': []}


def _parse_toc(text: str) -> List[Dict[str, Any]]:
    import csv
    import io
    rows = []
    reader = csv.reader(io.StringIO(text), delimiter='\t')
    next(reader, None)
    for r in reader:
        if len(r) < 7 or r[2].strip() not in ('dataset', 'table'):
            continue
        rows.append({'code': r[1].strip(), 'title': r[0].strip(), 'type': r[2].strip(),
                     'last_update': _toc_date(r[3]), 'data_start': r[5].strip() or None,
                     'data_end': r[6].strip() or None})
    return rows


def _toc_date(s: str) -> Optional[str]:
    m = re.match(r'\s*(\d{2})\.(\d{2})\.(\d{4})', s or '')
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else None


def table_of_contents() -> List[Dict[str, Any]]:
    now = time.monotonic()
    with _lock:
        if _toc['rows'] and now - _toc['at'] < _TOC_TTL:
            return _toc['rows']
    r = get(f'{BASE}/catalogue/toc/txt', 'Eurostat catalogue', params={'lang': 'en'},
            headers={'Accept': 'text/plain'}, timeout=60)
    if r.status_code >= 400:
        raise ValueError(f'Eurostat catalogue answered HTTP {r.status_code}')
    rows = _parse_toc(r.text)
    with _lock:
        _toc.update(at=now, rows=rows)
    return rows


class EurostatSearchTool(EurostatBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        text = str(arguments.get('text') or '').strip()
        words = [w for w in re.split(r'\W+', text.lower()) if w]
        if not words:
            raise ValueError('text is required (words to look for in dataset titles or codes)')
        limit = int(arguments.get('limit') or 20)
        seen, hits = set(), []
        for row in table_of_contents():
            if row['code'] in seen:
                continue          # a dataset appears under several themes
            hay = f"{row['title']} {row['code']}".lower()
            if all(w in hay for w in words):
                seen.add(row['code'])
                hits.append(row)
        hits.sort(key=lambda r: (r['type'] != 'dataset', not r['code'].lower().startswith(words[0]),
                                 r['code']))
        out = {'text': text, 'source': SOURCE, 'count': len(hits), 'datasets': hits[:limit]}
        if len(hits) > limit:
            out['truncated'] = True
        if not hits:
            out['note'] = 'No Eurostat dataset title or code contains all of these words.'
        return out
