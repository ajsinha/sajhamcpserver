"""
SAJHA MCP Server — Australian Bureau of Statistics tools (tool folder ``abs``; Open Data Tools §4,
P2; Roadmap L34).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The ABS Data API answers SDMX 2.1 REST at ``data.api.abs.gov.au/rest`` (no key since 2024). These
tools are an ``abs`` host profile on the shared SDMX client (``sajha/tools/impl/sdmx_client.py``,
registered below): flow references are ``ABS,<ID>`` and SDMX-CSV is selected with the
``Accept: application/vnd.sdmx.data+csv`` header. Every fetch goes through the outbound fetch guard
and HTTP proxy. A response is limited to 30 seconds and 10 MB, so the curated tools ask for one
fully specified key; a 404 ``NoRecordsFound`` means no data, not an error.

Terms: ABS material is CC BY 4.0 (the ABS copyright page, checked 2026-10-11); every result carries
``source`` ("Source: Australian Bureau of Statistics").
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sajha.tools.impl import sdmx_client
from sajha.tools.impl.bis_tools import period_params
from sajha.tools.impl.open_data_common import OpenDataTool

SOURCE = 'Source: Australian Bureau of Statistics (data.api.abs.gov.au), licensed under CC BY 4.0'
HOST = sdmx_client.register_host(sdmx_client.SdmxHost(
    name='abs', base_url='https://data.api.abs.gov.au/rest', agency='ABS', agency_flow_ref=True,
    csv_accept='application/vnd.sdmx.data+csv;version=1.0.0', source=SOURCE))

UNITS = {'IN': 'Index', 'PCT': 'Percent', 'NUM': 'Number', 'AUD': 'Australian dollars', 'PCPT': 'Percentage points'}
_MULT = {'0': None, '3': 'thousands', '6': 'millions', '9': 'billions'}
ADJUSTMENT = {'original': '10', 'seasonally_adjusted': '20', 'trend': '30'}
_ADJ_NAMES = {v: k for k, v in ADJUSTMENT.items()}

# capital cities in the CPI's REGION codelist; 50 is the weighted average of the eight
CPI_REGIONS = {'australia': '50', 'sydney': '1', 'melbourne': '2', 'brisbane': '3', 'adelaide': '4', 'perth': '5',
               'hobart': '6', 'darwin': '7', 'canberra': '8'}
STATES = {'australia': 'AUS', 'nsw': '1', 'new_south_wales': '1', 'vic': '2', 'victoria': '2', 'qld': '3',
          'queensland': '3', 'sa': '4', 'south_australia': '4', 'wa': '5', 'western_australia': '5', 'tas': '6',
          'tasmania': '6', 'nt': '7', 'northern_territory': '7', 'act': '8', 'australian_capital_territory': '8'}


def _series_out(s: Dict[str, Any]) -> Dict[str, Any]:
    dims, attrs = s.get('dimensions') or {}, s.get('attributes') or {}
    unit = attrs.get('UNIT_MEASURE') or dims.get('UNIT_MEASURE')
    obs = [{'date': o['period'], 'value': o['value']} for o in s.get('observations') or []]
    freq = dims.get('FREQ') or ''
    return {
        'key': s.get('key'),
        'region': dims.get('REGION'),
        'unit': UNITS.get(str(unit), unit),
        'unit_multiplier': _MULT.get(str(attrs.get('UNIT_MULT')), attrs.get('UNIT_MULT')),
        'adjustment': _ADJ_NAMES.get(str(dims.get('TSEST')), dims.get('TSEST')),
        'frequency': sdmx_client._FREQ.get(freq, freq or None),
        'dimensions': dims,
        'observation_count': len(obs),
        'observations': obs,
    }


def fetch(flow: str, key: str, period: Optional[str], max_series: int = 50,
          names: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Any]:
    """One data query; ``names`` maps ``{dimension: {code: friendly name}}`` onto each series."""
    q = period_params(period)
    try:
        result = sdmx_client.fetch('abs', flow, key, timeout=45.0, **q)
    except sdmx_client.SdmxError as e:
        raise ValueError(f'ABS: {e}') from e
    series = sorted((_series_out(s) for s in result['series']), key=lambda s: s['key'] or '')
    for s in series:
        for dim, mapping in (names or {}).items():
            code = s['dimensions'].get(dim)
            if code in mapping:
                s[dim.lower() if dim != 'MEASURE' else 'measure'] = mapping[code]
    out: Dict[str, Any] = {'dataflow': result['flow'], 'key': key, 'period': period or None, 'source': SOURCE,
                           'series_count': len(series), 'series': series[:max_series]}
    if len(series) > max_series:
        out['truncated'] = True
        out['note'] = f'{len(series)} series matched; the first {max_series} are returned. Narrow the key.'
    elif not series:
        out['note'] = 'The ABS returned no data for this selection and period (NoRecordsFound).'
    return out


def _code(mapping: Dict[str, str], value: Any, what: str) -> str:
    v = str(value or '').strip().lower().replace(' ', '_')
    if v in mapping:
        return mapping[v]
    raise ValueError(f'unknown {what} {value!r}; use one of {", ".join(mapping)}')


class AbsBaseTool(OpenDataTool):
    pass


class AbsGetSeriesTool(AbsBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        flow = str(arguments.get('dataflow') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.,]{2,80}', flow):
            raise ValueError(f'dataflow must be an ABS dataflow id such as CPI or LF, not {flow!r}')
        key = str(arguments.get('key') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_+.\-]*', key):
            raise ValueError('key is dimension codes joined by dots, + for several codes, empty for all')
        return fetch(flow.upper() if ',' not in flow else flow, key, arguments.get('period'),
                     max_series=int(arguments.get('max_series') or 20))


CPI_MEASURES = {'index': '1', 'period_change': '2', 'annual_change': '3'}


class AbsCpiTool(AbsBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        measure = CPI_MEASURES[arguments.get('measure') or 'annual_change']
        item = str(arguments.get('item') or '10001').strip()
        if not item.isdigit():
            raise ValueError('item is a CPI INDEX code, e.g. 10001 (All groups CPI)')
        regions = arguments.get('regions') or ['australia']
        region = '+'.join(dict.fromkeys(_code(CPI_REGIONS, r, 'region') for r in regions))
        adj = ADJUSTMENT[arguments.get('adjustment') or 'original']
        freq = {'monthly': 'M', 'quarterly': 'Q'}[arguments.get('frequency') or 'monthly']
        return fetch('CPI', f'{measure}.{item}.{adj}.{region}.{freq}', arguments.get('period'),
                     names={'REGION': {v: k for k, v in CPI_REGIONS.items()}})


LF_MEASURES = {'unemployment_rate': 'M13', 'employed': 'M3', 'unemployed': 'M6', 'participation_rate': 'M12',
               'employment_to_population': 'M16', 'underemployment_rate': 'M23', 'underutilisation_rate': 'M24',
               'labour_force': 'M9'}
_LF_NAMES = {v: k for k, v in LF_MEASURES.items()}
SEX = {'persons': '3', 'males': '1', 'females': '2'}


class AbsLabourForceTool(AbsBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ms = arguments.get('measures') or ['unemployment_rate']
        measure = '+'.join(dict.fromkeys(LF_MEASURES[m] for m in ms))
        sex = SEX[arguments.get('sex') or 'persons']
        region = _code(STATES, arguments.get('region') or 'australia', 'region')
        adj = ADJUSTMENT[arguments.get('adjustment') or 'seasonally_adjusted']
        return fetch('LF', f'{measure}.{sex}.1599.{adj}.{region}.M', arguments.get('period'),
                     names={'MEASURE': _LF_NAMES})


GDP_MEASURES = {'growth_qoq': 'M2', 'volume': 'M1', 'current_prices': 'M3', 'current_prices_growth': 'M4'}
GDP_ITEMS = {'gdp': 'GPM', 'gdp_per_capita': 'GPM_PCA', 'real_gross_domestic_income': 'RDI',
             'terms_of_trade': 'TTR', 'household_saving_ratio': 'HSR', 'domestic_final_demand': 'DFD'}
_GDP_NAMES = {v: k for k, v in GDP_MEASURES.items()}


class AbsGdpTool(AbsBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ms = arguments.get('measures') or ['growth_qoq']
        measure = '+'.join(dict.fromkeys(GDP_MEASURES[m] for m in ms))
        item = GDP_ITEMS[arguments.get('item') or 'gdp']
        adj = ADJUSTMENT[arguments.get('adjustment') or 'seasonally_adjusted']
        return fetch('ANA_AGG', f'{measure}.{item}.{adj}.AUS.Q', arguments.get('period'),
                     names={'MEASURE': _GDP_NAMES})
