"""
SAJHA MCP Server — US Bureau of Economic Analysis tools (tool folder ``bea``; Open Data Tools §4 P2, L35).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The BEA Data API (``apps.bea.gov/api/data``) needs a free 36-character UserID, read from the
environment variable ``BEA_API_KEY`` (never from application.yml). There is no keyless tier: without
the key every tool fails with a message saying the API key is not configured, which the live tool
check reports as ``not_configured``.

BEA throttles at 100 requests, 100 MB and 30 errors a minute per UserID and IP (HTTP 429 with
Retry-After): every request first takes a slot in one sliding window kept in the state store, so all
workers share the budget. Results are cached by each tool's ``cache_ttl``.

The API terms of service require every application to display "This product uses the Bureau of
Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.": every result carries it in
``source``. Every fetch goes through the outbound fetch guard and HTTP proxy.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl import open_data_common as odc

URL = 'https://apps.bea.gov/api/data'
KEY_ENV = 'BEA_API_KEY'
SOURCE = ('Source: U.S. Bureau of Economic Analysis (BEA Data API, apps.bea.gov). This product uses the Bureau of '
          'Economic Analysis (BEA) Data API but is not endorsed or certified by BEA.')
NOT_CONFIGURED = ('BEA API key not configured: set the BEA_API_KEY environment variable to your BEA UserID '
                  '(free registration at https://apps.bea.gov/API/signup/).')
THROTTLE = ('opendata:bea:requests', 100, 60.0, 15.0)
MAX_YEARS = 20
_MULT = {'0': None, '3': 'thousands', '6': 'millions', '9': 'billions', '12': 'trillions'}
FREQ = {'annual': 'A', 'quarterly': 'Q', 'monthly': 'M'}


def user_id(config) -> str:
    key = odc.env_key(KEY_ENV, config)
    if not key:
        raise ValueError(NOT_CONFIGURED)
    return key


def _error(results: Any) -> Optional[Dict[str, Any]]:
    if isinstance(results, list):
        results = results[0] if results else {}
    return results.get('Error') if isinstance(results, dict) else None


def call(params: Dict[str, Any], config) -> Any:
    """One BEA request; returns ``BEAAPI.Results`` (a dict, or a list for GDPbyIndustry)."""
    key = user_id(config)
    odc.take_slot(*THROTTLE[:3], THROTTLE[3], 'BEA')
    q = [('UserID', key)] + [(k, str(v)) for k, v in params.items() if v not in (None, '')] + \
        [('ResultFormat', 'JSON')]
    r = odc.get(URL, 'BEA', params=q, timeout=60.0)
    if r.status_code == 429:
        raise ValueError(f'BEA: rate limit reached (HTTP 429); retry after {r.headers.get("retry-after") or 60} s')
    try:
        body = r.json()
    except ValueError:
        raise ValueError(f'BEA answered HTTP {r.status_code} without JSON')
    api = (body or {}).get('BEAAPI') or {}
    results = api.get('Results')
    err = api.get('Error') or _error(results)
    if err:
        code = str(err.get('APIErrorCode') or '')
        desc = err.get('APIErrorDescription') or ''
        detail = (err.get('ErrorDetail') or {}).get('Description') if isinstance(err.get('ErrorDetail'), dict) else ''
        if code == '1' or 'userid' in desc.lower().replace(' ', ''):
            raise ValueError(f'BEA refused the API key ({desc.strip()}): check BEA_API_KEY')
        if code == '7' or 'quota' in desc.lower():
            raise ValueError(f'BEA: rate limit reached ({desc.strip()})')
        raise ValueError(f'BEA error {code}: {desc.strip()}' + (f' ({detail})' if detail else ''))
    if r.status_code >= 400:
        raise ValueError(f'BEA answered HTTP {r.status_code}')
    return results


def years_param(arguments: Dict[str, Any], default_n: int = 3) -> Tuple[str, List[int]]:
    years = arguments.get('years')
    if not years:
        this = date.today().year
        years = list(range(this - default_n + 1, this + 1))
    if isinstance(years, (int, str)):
        years = [years]
    try:
        years = sorted({int(y) for y in years})
    except (TypeError, ValueError):
        raise ValueError('years must be a list of years such as [2024, 2025]')
    if len(years) > MAX_YEARS:
        raise ValueError(f'ask for at most {MAX_YEARS} years in one call')
    return ','.join(str(y) for y in years), years


def human_period(p: Any) -> str:
    s = str(p or '').strip()
    m = re.fullmatch(r'(\d{4})Q([1-4])', s)
    if m:
        return f'{m.group(1)}-Q{m.group(2)}'
    m = re.fullmatch(r'(\d{4})M(\d{1,2})', s)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}'
    return s


def _data_and_notes(results: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    if isinstance(results, list):            # GDPbyIndustry answers a list of result blocks
        data, notes = [], []
        for block in results:
            data += block.get('Data') or []
            notes += block.get('Notes') or []
        return data, notes, (results[0] if results else {})
    results = results or {}
    return results.get('Data') or [], results.get('Notes') or [], results


def group(results: Any, key_fields: Tuple[str, ...], describe) -> Dict[str, Any]:
    """Data rows grouped into series by ``key_fields``; ``describe(row)`` gives each series' fields."""
    data, notes, meta = _data_and_notes(results)
    by: Dict[str, Dict[str, Any]] = {}
    for row in data:
        key = '.'.join(str(row.get(k) or '') for k in key_fields)
        s = by.get(key)
        if s is None:
            s = by[key] = {'key': key, **describe(row),
                           'unit': row.get('CL_UNIT') or meta.get('UnitOfMeasure'),
                           'unit_multiplier': _MULT.get(str(row.get('UNIT_MULT')), row.get('UNIT_MULT')),
                           'observations': []}
        s['observations'].append({'date': human_period(row.get('TimePeriod') or row.get('Year')),
                                  'value': odc.number(row.get('DataValue'))})
    series = list(by.values())
    for s in series:
        s['observations'].sort(key=lambda o: o['date'])
        s['observation_count'] = len(s['observations'])
    title = next((n.get('NoteText') for n in notes if str(n.get('NoteRef')) in (data[0].get('NoteRef', '').split(',')
                                                                                 if data else [])), None)
    return {'title': meta.get('PublicTable') or meta.get('Statistic') or title, 'series': series,
            'notes': [n.get('NoteText') for n in notes if n.get('NoteText')][:10]}


class BeaBaseTool(odc.OpenDataTool):
    """The key is read from the config's ``api_key`` (``${BEA_API_KEY:}``) or the environment."""


def _out(dataset: str, extra: Dict[str, Any], grouped: Dict[str, Any], max_series: int) -> Dict[str, Any]:
    series = grouped['series']
    out = {'source': SOURCE, 'dataset': dataset, **extra, 'title': grouped['title'],
           'series_count': len(series), 'series': series[:max_series], 'notes': grouped['notes']}
    if len(series) > max_series:
        out['truncated'] = True
        out['note'] = f'{len(series)} series matched; the first {max_series} are returned.'
    return out


class BeaDatasetsTool(BeaBaseTool):
    """bea_datasets: the datasets the BEA API offers."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        results = call({'method': 'GETDATASETLIST'}, self.config)
        sets = [{'name': d.get('DatasetName'), 'description': d.get('DatasetDescription')}
                for d in (results or {}).get('Dataset') or []]
        return {'source': SOURCE, 'dataset_count': len(sets), 'datasets': sets}


class BeaNipaTableTool(BeaBaseTool):
    """bea_nipa_table: one National Income and Product Accounts table (T10101 real GDP growth, ...)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        table = str(arguments.get('table') or '').strip().upper()
        if not re.fullmatch(r'[A-Z0-9]{3,12}', table):
            raise ValueError('table must be a NIPA table name such as T10101')
        freq = arguments.get('frequency') or 'quarterly'
        years, ys = years_param(arguments)
        results = call({'method': 'GetData', 'DataSetName': 'NIPA', 'TableName': table, 'Frequency': FREQ[freq],
                        'Year': years}, self.config)
        grouped = group(results, ('LineNumber', 'SeriesCode'), lambda r: {
            'line': int(odc.number(r.get('LineNumber')) or 0), 'series_code': r.get('SeriesCode'),
            'description': r.get('LineDescription'), 'metric': r.get('METRIC_NAME') or r.get('Metric_Name')})
        grouped['series'].sort(key=lambda s: s['line'])
        return _out('NIPA', {'table': table, 'frequency': freq, 'years': ys}, grouped,
                    int(arguments.get('max_series') or 100))


class BeaGdpByIndustryTool(BeaBaseTool):
    """bea_gdp_by_industry: value added (and other GDP-by-industry tables) by industry."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        inds = arguments.get('industries') or ['ALL']
        inds = [str(i).strip() for i in ([inds] if isinstance(inds, str) else inds)]
        freq = arguments.get('frequency') or 'annual'
        if freq not in ('annual', 'quarterly'):
            raise ValueError('frequency must be annual or quarterly')
        table_id = int(arguments.get('table_id') or 1)
        years, ys = years_param(arguments)
        results = call({'method': 'GetData', 'DataSetName': 'GDPbyIndustry', 'TableID': table_id,
                        'Frequency': FREQ[freq], 'Year': years, 'Industry': ','.join(inds)}, self.config)
        if isinstance(results, list):        # annual rows carry Year; quarterly rows Year and Quarter
            for block in results:
                for row in block.get('Data') or []:
                    q = _QUARTER.get(str(row.get('Quarter') or '').strip().upper().lstrip('Q'))
                    row['TimePeriod'] = f"{row.get('Year')}Q{q}" if q else row.get('Year')
        grouped = group(results, ('Industry',), lambda r: {
            'industry': r.get('Industry'),
            'description': r.get('IndustrYDescription') or r.get('IndustryDescription')})
        return _out('GDPbyIndustry', {'table_id': table_id, 'frequency': freq, 'years': ys}, grouped,
                    int(arguments.get('max_series') or 100))


_QUARTER = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, '1': 1, '2': 2, '3': 3, '4': 4}
ITA_FREQ = {'annual': 'A', 'quarterly_sa': 'QSA', 'quarterly_nsa': 'QNSA'}


class BeaInternationalTransactionsTool(BeaBaseTool):
    """bea_international_transactions: US international transactions (balance of payments, ITA)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        indicator = str(arguments.get('indicator') or 'BalGds').strip()
        area = str(arguments.get('area_or_country') or 'AllCountries').strip()
        freq = arguments.get('frequency') or 'quarterly_sa'
        years, ys = years_param(arguments)
        results = call({'method': 'GetData', 'DataSetName': 'ITA', 'Indicator': indicator, 'AreaOrCountry': area,
                        'Frequency': ITA_FREQ[freq], 'Year': years}, self.config)
        grouped = group(results, ('TimeSeriesId', 'AreaOrCountry'), lambda r: {
            'series_id': r.get('TimeSeriesId'), 'indicator': r.get('Indicator'),
            'area_or_country': r.get('AreaOrCountry'), 'description': r.get('TimeSeriesDescription')})
        return _out('ITA', {'indicator': indicator, 'area_or_country': area, 'frequency': freq, 'years': ys},
                    grouped, int(arguments.get('max_series') or 50))


class BeaRegionalTool(BeaBaseTool):
    """bea_regional: state, county and metro income, GDP and employment (Regional dataset)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        table = str(arguments.get('table') or '').strip().upper()
        if not re.fullmatch(r'[A-Z0-9\-]{3,16}', table):
            raise ValueError('table must be a Regional table name such as SAINC1 or SAGDP1')
        line = arguments.get('line_code', 1)
        geo = arguments.get('geography') or 'STATE'
        geo = ','.join(str(g).strip().upper() for g in ([geo] if isinstance(geo, str) else geo))
        years, ys = years_param(arguments)
        results = call({'method': 'GetData', 'DataSetName': 'Regional', 'TableName': table, 'LineCode': line,
                        'GeoFips': geo, 'Year': years}, self.config)
        grouped = group(results, ('Code', 'GeoFips'), lambda r: {
            'code': r.get('Code'), 'geo_fips': r.get('GeoFips'), 'geo_name': r.get('GeoName')})
        return _out('Regional', {'table': table, 'line_code': line, 'geography': geo, 'years': ys}, grouped,
                    int(arguments.get('max_series') or 100))
