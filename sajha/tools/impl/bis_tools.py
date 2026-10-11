"""
SAJHA MCP Server — BIS statistics tools (Open Data Tools §4, P1; Roadmap L28).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The Bank for International Settlements publishes its statistics over SDMX 2.1 REST at
stats.bis.org/api/v1. These tools are a ``bis`` host profile on the shared SDMX client
(``sajha/tools/impl/sdmx_client.py``, registered below), so every fetch goes through the
outbound fetch guard and HTTP proxy. The BIS terms ask that the BIS be cited: every result
carries ``source: "Source: BIS ..."`` (Open Data Tools §6).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl import sdmx_client
from sajha.tools.impl.country_codes import COUNTRIES

SOURCE = 'Source: BIS (Bank for International Settlements, stats.bis.org)'

sdmx_client.register_host(sdmx_client.SdmxHost(
    name='bis', base_url='https://stats.bis.org/api/v1', agency='BIS',
    csv_accept='application/vnd.sdmx.data+csv;version=1.0.0', source=SOURCE))

# BIS unit codes seen in these dataflows (codelist CL_BIS_UNIT); others are returned as the code
UNITS = {
    '367': 'Per cent',
    '368': 'Per cent per year',
    '770': 'Percentage of GDP',
    '628': 'Index, 2010 = 100',
    '771': 'Year-on-year change, per cent',
    '882': 'Index, 2020 = 100',
    'XDC': 'Domestic currency',
    'USD': 'US dollar',
}
_MULT = {'0': None, '3': 'thousands', '6': 'millions', '9': 'billions', '12': 'trillions'}
_TITLE_ATTRS = ('TITLE', 'TITLE_TS', 'TITLE_GRP')
_AREA_DIMS = ('REF_AREA', 'BORROWERS_CTY')
_UNIT_KEYS = ('UNIT_MEASURE', 'UNIT_TYPE')
_NAMES = {v[2].lower(): v[0] for v in COUNTRIES.values() if v[0]}
_NAMES.update({'euro area': 'XM', 'eurozone': 'XM', 'united states': 'US', 'usa': 'US',
               'united kingdom': 'GB', 'uk': 'GB', 'britain': 'GB', 'south korea': 'KR', 'korea': 'KR',
               'russia': 'RU', 'turkey': 'TR', 'czech republic': 'CZ', 'hong kong': 'HK', 'taiwan': 'TW',
               'vietnam': 'VN'})
_LAST = re.compile(r'^last\s+(\d+)\s+(day|week|month|quarter|year)s?$', re.I)
_PERIOD = re.compile(r'^\d{4}(-(Q[1-4]|S[12]|\d{2}(-\d{2})?))?$')


def area_code(value: str) -> str:
    """A BIS area code from an ISO alpha-2 (or BIS aggregate such as XM, 5A), ISO alpha-3 or
    a country name."""
    v = str(value or '').strip()
    up = v.upper()
    if len(up) == 2 and up.isalnum():
        return up
    if up in COUNTRIES and COUNTRIES[up][0]:
        return COUNTRIES[up][0]
    code = _NAMES.get(v.lower())
    if code:
        return code
    raise ValueError(f"Unknown country {value!r}: use an ISO 3166 code (US, GB, XM for the euro area) "
                     f"or a country name")


def period_params(period: Optional[str], today: Optional[date] = None) -> Dict[str, Any]:
    """``latest``, ``last N days|weeks|months|quarters|years``, one period (2025, 2025-Q3,
    2025-07, 2025-07-15) or a range ``A/B`` (or ``A to B``) as start/end/last_n for the client."""
    p = str(period or '').strip()
    if not p:
        return {}
    if p.lower() == 'latest':
        return {'last_n': 1}
    m = _LAST.match(p)
    if m:
        n, unit, t = int(m.group(1)), m.group(2).lower(), today or date.today()
        if unit in ('day', 'week'):
            return {'start': (t - timedelta(days=n * (7 if unit == 'week' else 1))).isoformat()}
        if unit == 'year':
            return {'start': str(t.year - n)}
        months = t.year * 12 + t.month - 1 - n * (3 if unit == 'quarter' else 1)
        y, mo = divmod(months, 12)
        # the period n months (quarters) before this one, as a period of the series' own kind
        return {'start': f'{y}-Q{mo // 3 + 1}' if unit == 'quarter' else f'{y}-{mo + 1:02d}'}
    parts = [x.strip() for x in re.split(r'\s*/\s*|\s+to\s+', p) if x.strip()]
    if len(parts) == 1:
        parts = [p, p]
    if len(parts) != 2 or not all(_PERIOD.match(x) for x in parts):
        raise ValueError(f"Unreadable period {period!r}: use latest, 'last 12 months', 2025, 2025-Q3, "
                         f"2025-07, 2025-07-15 or a range such as 2020-Q1/2025-Q4")
    return {'start': parts[0], 'end': parts[1]}


def _series_out(s: Dict[str, Any]) -> Dict[str, Any]:
    dims, attrs = s.get('dimensions') or {}, s.get('attributes') or {}
    unit = next((src[k] for src in (dims, attrs) for k in _UNIT_KEYS if src.get(k)), None)   # dimension first
    area = next((dims[k] for k in _AREA_DIMS if dims.get(k)), None)
    freq = dims.get('FREQ') or ''
    obs = [{'date': o['period'], 'value': o['value']} for o in s.get('observations') or []]
    title = next((str(attrs[a]).strip() for a in _TITLE_ATTRS if attrs.get(a)), None)
    return {
        'key': s.get('key'),
        'country': area,
        'title': title,
        'unit': UNITS.get(str(unit), unit),
        'unit_multiplier': _MULT.get(str(attrs.get('UNIT_MULT')), attrs.get('UNIT_MULT')),
        'frequency': sdmx_client._FREQ.get(freq, freq or None),
        'dimensions': dims,
        'observation_count': len(obs),
        'observations': obs,
    }


def fetch(flow: str, key: str, period: Optional[str], default_last_n: Optional[int] = None,
          max_series: int = 50) -> Dict[str, Any]:
    q = period_params(period)
    if not q and default_last_n:
        q = {'last_n': default_last_n}
    result = sdmx_client.fetch('bis', flow, key, **q)
    series = [_series_out(s) for s in result['series']]
    out: Dict[str, Any] = {'dataflow': flow, 'key': key, 'period': period or None, 'source': SOURCE,
                           'series_count': len(series), 'series': series[:max_series]}
    if len(series) > max_series:
        out['truncated'] = True
        out['note'] = f'{len(series)} series matched; the first {max_series} are returned. Narrow the key.'
    elif not series:
        out['note'] = 'The BIS returned no data for this selection and period.'
    return out


def _areas(arguments: Dict[str, Any]) -> str:
    countries = arguments.get('countries') or []
    if isinstance(countries, str):
        countries = [c for c in re.split(r'[,\s+]+', countries) if c]
    if not countries:
        raise ValueError('countries is required (one or more ISO codes, e.g. ["US", "GB"])')
    return '+'.join(dict.fromkeys(area_code(c) for c in countries))


class BisBaseTool(BaseMCPTool):
    """Shared plumbing; each tool builds a dataflow and key."""

    def get_input_schema(self) -> Dict:
        return {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return {'type': 'object'}

    def _call(self, flow: str, key: str, arguments: Dict[str, Any], **kw) -> Dict[str, Any]:
        try:
            return fetch(flow, key, arguments.get('period'), **kw)
        except sdmx_client.SdmxError as e:
            raise ValueError(f'BIS: {e}') from e


class BisPolicyRatesTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        freq = 'D' if arguments.get('frequency') == 'daily' else 'M'
        return self._call('WS_CBPOL', f'{freq}.{_areas(arguments)}', arguments)


class BisCreditGapTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        # private non-financial sector, all lenders, gap (actual minus HP-filter trend)
        out = self._call('WS_CREDIT_GAP', f'Q.{_areas(arguments)}.P.A.C', arguments)
        for s in out['series']:
            s['unit'] = 'Percentage points of GDP'      # a gap between two ratios to GDP
        return out


TC_SECTORS = {'private_non_financial': 'P', 'households': 'H', 'non_financial_corporations': 'N',
              'government': 'G', 'non_financial': 'C'}
TC_UNITS = {'percent_of_gdp': '770', 'domestic_currency': 'XDC', 'usd': 'USD'}


class BisTotalCreditTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        sector = TC_SECTORS[arguments.get('sector') or 'private_non_financial']
        unit = TC_UNITS[arguments.get('unit') or 'percent_of_gdp']
        # all lenders; valuation left open (government debt has market and nominal value); break-adjusted
        return self._call('WS_TC', f'Q.{_areas(arguments)}.{sector}.A..{unit}.A', arguments)


DSR_SECTORS = {'private_non_financial': 'P', 'households': 'H', 'non_financial_corporations': 'N'}


class BisDebtServiceRatioTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        sector = DSR_SECTORS[arguments.get('sector') or 'private_non_financial']
        return self._call('WS_DSR', f'Q.{_areas(arguments)}.{sector}', arguments)


class BisPropertyPricesTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        areas = _areas(arguments)
        if (arguments.get('type') or 'residential') == 'commercial':
            # WS_CPP: every published commercial series of the country (nominal indices)
            return self._call('WS_CPP', f'Q.{areas}.......', arguments)
        value = 'N' if arguments.get('real') is False else 'R'
        unit = '771' if arguments.get('measure') == 'yoy_change' else '628'
        return self._call('WS_SPP', f'Q.{areas}.{value}.{unit}', arguments)


class BisEffectiveExchangeRatesTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        real = arguments.get('real') is not False
        freq = 'D' if arguments.get('frequency') == 'daily' else 'M'
        if real and freq == 'D':
            raise ValueError('Real effective exchange rates are monthly only; use frequency monthly '
                             'or real false')
        basket = 'N' if arguments.get('basket') == 'narrow' else 'B'
        return self._call('WS_EER', f"{freq}.{'R' if real else 'N'}.{basket}.{_areas(arguments)}",
                          arguments)


class BisGetSeriesTool(BisBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        flow = str(arguments.get('dataflow') or '').strip().upper()
        key = str(arguments.get('key') or '').strip()
        return self._call(flow, key, arguments, default_last_n=None,
                          max_series=int(arguments.get('max_series') or 20))
