"""
SAJHA MCP Server — UK Office for National Statistics tools (tool folder ``ons``; Open Data Tools §4, L34).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Two ONS services, both keyless and under the Open Government Licence v3.0:

* the search API of ``api.beta.ons.gov.uk/v1`` finds time series (a four-character CDID such as
  ``D7G7`` within a dataset such as ``MM23``) and their page URI;
* the website's time-series JSON (``www.ons.gov.uk/<uri>/data``) gives the whole series: annual,
  quarterly and monthly observations and the series description (unit, release dates). That path is
  not documented as an API (Open Data Tools §2 caveat); the tools find the URI through the search
  API rather than building it, so a moved series still resolves.

The OGL asks for an attribution statement: every result carries ``source``. ONS limits bots to 120
requests per 10 seconds and 200 per minute; every request takes a slot in both windows, kept in the
state store so every worker shares them, and each tool's ``cache_ttl`` caches its results. Every
fetch goes through the outbound fetch guard and HTTP proxy (``open_data_common.get``).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from sajha.tools.impl.open_data_common import OpenDataTool, get, number, take_slot
from sajha.tools.impl.us_treasury_tools import parse_period

SEARCH = 'https://api.beta.ons.gov.uk/v1/search'
SITE = 'https://www.ons.gov.uk'
SOURCE = ('Source: Office for National Statistics licensed under the Open Government Licence v3.0 '
          '(ons.gov.uk)')
LABEL = 'ONS'
WINDOWS = (('opendata:ons:10s', 100, 10.0), ('opendata:ons:60s', 180, 60.0))
THROTTLE_WAIT = 15.0
_CDID = re.compile(r'^[A-Z0-9]{4}$')
_MONTHS = {m: i for i, m in enumerate(('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT',
                                       'NOV', 'DEC'), 1)}
FREQ_KEYS = {'monthly': 'months', 'quarterly': 'quarters', 'annual': 'years'}


def _json(url: str, params: Optional[List] = None) -> Any:
    for key, limit, window in WINDOWS:
        take_slot(key, limit, window, THROTTLE_WAIT, LABEL)
    r = get(url, LABEL, params=params)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise ValueError(f'{LABEL} answered HTTP {r.status_code} for {url}')
    try:
        return r.json()
    except ValueError:
        raise ValueError(f'{LABEL}: unreadable answer from {url}')


def search(text: str, limit: int = 20) -> Dict[str, Any]:
    body = _json(SEARCH, [('q', text), ('content_type', 'timeseries'), ('limit', str(limit))]) or {}
    items = []
    for it in body.get('items') or []:
        items.append({'cdid': it.get('cdid'), 'dataset': it.get('dataset_id'), 'title': it.get('title'),
                      'release_date': str(it.get('release_date') or '')[:10] or None, 'uri': it.get('uri')})
    return {'total': body.get('count') or 0, 'series': items}


def ons_date(label: str) -> Optional[str]:
    """``2026 AUG`` -> ``2026-08``, ``2026 Q2`` -> ``2026-Q2``, ``2026`` -> ``2026``."""
    s = str(label or '').strip().upper()
    m = re.fullmatch(r'(\d{4})\s+([A-Z]{3})', s)
    if m and m.group(2) in _MONTHS:
        return f'{m.group(1)}-{_MONTHS[m.group(2)]:02d}'
    m = re.fullmatch(r'(\d{4})\s+(Q[1-4])', s)
    if m:
        return f'{m.group(1)}-{m.group(2)}'
    return s if re.fullmatch(r'\d{4}', s) else (s or None)


def _first_day(period: str) -> date:
    if re.fullmatch(r'\d{4}', period):
        return date(int(period), 1, 1)
    m = re.fullmatch(r'(\d{4})-Q([1-4])', period)
    if m:
        return date(int(m.group(1)), 3 * int(m.group(2)) - 2, 1)
    y, mo = period.split('-')
    return date(int(y), int(mo), 1)


class OnsSearchTool(OpenDataTool):
    """ons_search: find ONS time series (CDID and dataset) by words."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        text = str(arguments.get('text') or '').strip()
        if not text:
            raise ValueError('text is required, e.g. "CPI annual rate" or a CDID such as D7G7')
        out = search(text, int(arguments.get('limit') or 20))
        out.update({'text': text, 'source': SOURCE, 'count': len(out['series'])})
        if not out['series']:
            out['note'] = 'No time series matched; try fewer or other words.'
        return out


class OnsTimeseriesTool(OpenDataTool):
    """ons_timeseries: one ONS time series by CDID (and dataset), monthly, quarterly or annual."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        cdid = str(arguments.get('cdid') or '').strip().upper()
        if not _CDID.match(cdid):
            raise ValueError(f'cdid must be a four-character ONS series id such as D7G7, not {cdid!r}')
        dataset = str(arguments.get('dataset') or '').strip().upper() or None
        found = [s for s in search(cdid, 50)['series'] if (s['cdid'] or '').upper() == cdid]
        if not found:
            raise ValueError(f'No ONS time series {cdid}; find one with ons_search')
        datasets = [s['dataset'] for s in found]
        if dataset:
            pick = [s for s in found if (s['dataset'] or '').upper() == dataset]
            if not pick:
                raise ValueError(f'{cdid} is not in dataset {dataset}; it is in {", ".join(datasets)}')
        else:            # the most recently released copy of the series
            pick = sorted(found, key=lambda s: s['release_date'] or '', reverse=True)
        chosen = pick[0]
        data = _json(SITE + chosen['uri'].rstrip('/') + '/data')
        if not data:
            raise ValueError(f'ONS has no data page for {cdid} in {chosen["dataset"]}')
        desc = data.get('description') or {}
        freq = arguments.get('frequency') or 'auto'
        if freq == 'auto':
            freq = next((f for f, k in FREQ_KEYS.items() if data.get(k)), 'annual')
        rows = data.get(FREQ_KEYS[freq]) or []
        obs = [{'date': ons_date(r.get('date')), 'value': number(r.get('value'))} for r in rows]
        obs = [o for o in obs if o['date']]
        if arguments.get('period'):
            start, end = parse_period(arguments['period'])
            obs = [o for o in obs if start <= _first_day(o['date']) <= end]
        latest_n = arguments.get('latest_n')
        if latest_n:
            obs = obs[-int(latest_n):]
        unit = ''.join(x.strip() for x in (desc.get('preUnit'), desc.get('unit')) if x and x.strip()) or None
        out = {
            'cdid': cdid, 'dataset': chosen['dataset'], 'title': desc.get('title') or chosen['title'],
            'unit': unit, 'frequency': freq, 'release_date': str(desc.get('releaseDate') or '')[:10] or None,
            'next_release': desc.get('nextRelease') or None, 'note_text': (desc.get('keyNote') or '').strip() or None,
            'other_datasets': [d for d in datasets if d != chosen['dataset']],
            'uri': chosen['uri'], 'source': SOURCE, 'observation_count': len(obs), 'observations': obs,
        }
        if not obs:
            out['note'] = f'No {freq} observations for this series and period; try another frequency.'
        return out
