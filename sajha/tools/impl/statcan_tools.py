"""
SAJHA MCP Server — Statistics Canada tools (tool folder ``statcan``; Open Data Tools §4, L34).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Statistics Canada's Web Data Service (WDS, ``www150.statcan.gc.ca/t1/wds/rest``) serves every
published table ("cube", product id such as ``18100004``, shown as ``18-10-0004-01``) and every
series in it (a "vector", ``v41690973``, or a table plus a coordinate of member ids such as
``2.2.0.0.0.0.0.0.0.0``). No key.

The Statistics Canada Open Licence allows commercial use with the source notice "Source:
Statistics Canada, <name of product>, <reference date>. Reproduced and distributed on an "as is"
basis with the permission of Statistics Canada." Every data result carries that notice, built from
the table's title and the newest reference period, in ``source``.

WDS allows 25 requests per second per IP; every request takes a slot in one window kept in the
state store (shared by every worker). The table list (``getAllCubesListLite``, about 5 MB), the
code sets and each table's metadata are cached per process; each tool's ``cache_ttl`` caches its
results. Every fetch goes through the outbound fetch guard and HTTP proxy (``open_data_common.get``).
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.impl.open_data_common import OpenDataTool, get, number, take_slot
from sajha.tools.impl.us_treasury_tools import parse_date, parse_period

BASE = 'https://www150.statcan.gc.ca/t1/wds/rest'
LABEL = 'Statistics Canada'
NOTICE = ('Reproduced and distributed on an "as is" basis with the permission of Statistics Canada.')
SOURCE = f'Source: Statistics Canada (www150.statcan.gc.ca). {NOTICE}'
THROTTLE_KEY = 'opendata:statcan:requests'
THROTTLE_LIMIT = 20            # per second across every worker (WDS allows 25 per IP)
THROTTLE_WINDOW = 1.0
THROTTLE_WAIT = 10.0
LIST_TTL = 6 * 3600.0          # the table list and the code sets
META_TTL = 3600.0              # one table's metadata

FREQUENCIES = {1: 'Daily', 2: 'Weekly', 4: 'Biweekly', 6: 'Monthly', 7: 'Bimonthly', 9: 'Quarterly',
               11: 'Semi-annual', 12: 'Annual', 13: 'Every 2 years', 14: 'Every 3 years', 15: 'Every 4 years',
               16: 'Every 5 years', 17: 'Every 10 years', 18: 'Occasional', 19: 'Occasional quarterly',
               20: 'Occasional monthly', 21: 'Occasional daily'}
SCALARS = {0: None, 1: 'tens', 2: 'hundreds', 3: 'thousands', 4: 'tens of thousands',
           5: 'hundreds of thousands', 6: 'millions', 7: 'tens of millions', 8: 'hundreds of millions',
           9: 'billions'}

_cache: Dict[Tuple, Tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: Tuple, ttl: float, build):
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = build()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def wds(endpoint: str, payload: Any = None, params: Optional[List] = None) -> Any:
    """One WDS call (POST with a JSON payload, else GET); the decoded body."""
    take_slot(THROTTLE_KEY, THROTTLE_LIMIT, THROTTLE_WINDOW, THROTTLE_WAIT, LABEL)
    url = f'{BASE}/{endpoint}'
    if payload is not None:
        r = get(url, LABEL, method='POST', json=payload, timeout=60)
    else:
        r = get(url, LABEL, params=params, timeout=90, max_bytes=40 * 1024 * 1024)
    if r.status_code == 409:
        raise ValueError(f'{LABEL}: not released yet ({endpoint})')
    if r.status_code >= 400:
        raise ValueError(f'{LABEL} answered HTTP {r.status_code} for {endpoint}')
    try:
        return r.json()
    except ValueError:
        raise ValueError(f'{LABEL}: unreadable answer from {endpoint}')


def _one(body: Any, what: str) -> Dict[str, Any]:
    item = body[0] if isinstance(body, list) and body else body
    if not isinstance(item, dict) or item.get('status') != 'SUCCESS':
        detail = item.get('object') if isinstance(item, dict) else None
        raise ValueError(f'{LABEL}: {what}: {detail or "failed"}')
    return item.get('object') or {}


# ── identifiers ──────────────────────────────────────────────────────────────

def product_id(table: Any) -> int:
    """``18-10-0004-01``, ``18-10-0004``, ``1810000401`` or ``18100004`` -> 18100004."""
    digits = re.sub(r'[\s-]', '', str(table or ''))
    if not digits.isdigit() or len(digits) not in (8, 10):
        raise ValueError(f'table must be a Statistics Canada table number such as 18-10-0004-01, not {table!r}')
    return int(digits[:8])


def table_number(pid: Any) -> str:
    s = str(pid)
    return f'{s[0:2]}-{s[2:4]}-{s[4:8]}-01' if len(s) == 8 else s


def vector_id(vector: Any) -> int:
    s = str(vector or '').strip().lower().lstrip('v')
    if not s.isdigit():
        raise ValueError(f'vector must be a Statistics Canada vector such as v41690973, not {vector!r}')
    return int(s)


def coordinate(value: Any) -> str:
    parts = [p for p in re.split(r'[.\s]+', str(value or '').strip()) if p]
    if not parts or not all(p.isdigit() for p in parts) or len(parts) > 10:
        raise ValueError(f'coordinate must be member ids joined by dots, e.g. 2.2 or 2.2.0.0.0.0.0.0.0.0, not {value!r}')
    return '.'.join(parts + ['0'] * (10 - len(parts)))


def ref_period(ref: str, freq: int) -> str:
    """A WDS reference period (first day of the period) in the period's own form."""
    d = str(ref or '')[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
        return d
    if freq in (6, 7, 20):
        return d[:7]
    if freq in (9, 19):
        return f'{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}'
    if freq in (12, 13, 14, 15, 16, 17):
        return d[:4]
    return d


# ── cached reference data ────────────────────────────────────────────────────

def cube_list() -> List[Dict[str, Any]]:
    return _cached(('cubes',), LIST_TTL, lambda: wds('getAllCubesListLite') or [])


def units() -> Dict[int, str]:
    def build():
        body = wds('getCodeSets')
        obj = (body or {}).get('object') or {}
        return {int(u['memberUomCode']): u.get('memberUomEn') for u in obj.get('uom') or []}
    return _cached(('uom',), LIST_TTL, build)


def cube_meta(pid: int) -> Dict[str, Any]:
    def build():
        o = _one(wds('getCubeMetadata', [{'productId': pid}]), f'table {table_number(pid)}')
        dims = []
        for d in sorted(o.get('dimension') or [], key=lambda x: x.get('dimensionPositionId') or 0):
            dims.append({'position': d.get('dimensionPositionId'), 'name': d.get('dimensionNameEn'),
                         'members': {int(m['memberId']): m.get('memberNameEn') for m in d.get('member') or []},
                         'uom': {int(m['memberId']): m.get('memberUomCode') for m in d.get('member') or []
                                 if m.get('memberUomCode') is not None}})
        return {'title': o.get('cubeTitleEn'), 'start': o.get('cubeStartDate'), 'end': o.get('cubeEndDate'),
                'release_time': o.get('releaseTime'), 'frequency': FREQUENCIES.get(o.get('frequencyCode')),
                'series_count': o.get('nbSeriesCube'), 'archived': str(o.get('archiveStatusCode')) == '1',
                'dimensions': dims}
    return _cached(('meta', pid), META_TTL, build)


def notice(title: Optional[str], pid: Any, reference: Optional[str]) -> str:
    product = f'Table {table_number(pid)} {title}'.strip() if title else f'Table {table_number(pid)}'
    ref = f', {reference}' if reference else ''
    return f'Source: Statistics Canada, {product}{ref}. {NOTICE}'


# ── one series ───────────────────────────────────────────────────────────────

def _range(period: str) -> Tuple[date, date]:
    return parse_period(period)


def series_data(info: Dict[str, Any], latest_n: Optional[int], period: Optional[str]) -> Dict[str, Any]:
    vid = int(info['vectorId'])
    freq = int(info.get('frequencyCode') or 0)
    if period:
        start, end = _range(period)
        body = wds('getDataFromVectorByReferencePeriodRange',
                   params=[('vectorIds', f'"{vid}"'), ('startRefPeriod', start.isoformat()),
                           ('endReferencePeriod', end.isoformat())])
    else:
        body = wds('getDataFromVectorsAndLatestNPeriods', [{'vectorId': vid, 'latestN': int(latest_n or 12)}])
    points = _one(body, f'vector v{vid}').get('vectorDataPoint') or []
    obs = []
    for p in sorted(points, key=lambda x: x.get('refPer') or ''):
        o = {'date': ref_period(p.get('refPer'), freq), 'value': number(p.get('value'))}
        if p.get('symbolCode') not in (0, None):
            o['symbol'] = {1: 'preliminary', 3: 'revised'}.get(p.get('symbolCode'), str(p.get('symbolCode')))
        obs.append(o)
    pid = info.get('productId')
    meta = cube_meta(int(pid))
    coord = [int(x) for x in str(info.get('coordinate') or '').split('.') if x.isdigit()]
    members = {}
    for d, mid in zip(meta['dimensions'], coord):
        if mid:
            members[d['name']] = d['members'].get(mid, str(mid))
    uom = info.get('memberUomCode')
    out = {
        'vector': f'v{vid}', 'table': table_number(pid), 'table_title': meta['title'],
        'coordinate': info.get('coordinate'), 'title': info.get('SeriesTitleEn'), 'members': members,
        'unit': units().get(int(uom)) if uom is not None else None,
        'unit_multiplier': SCALARS.get(int(info.get('scalarFactorCode') or 0)),
        'frequency': FREQUENCIES.get(freq), 'terminated': bool(info.get('terminated')),
        'release_time': max((p.get('releaseTime') or '' for p in points), default='') or None,
        'source': notice(meta['title'], pid, obs[-1]['date'] if obs else None),
        'observation_count': len(obs), 'observations': obs,
    }
    if not obs:
        out['note'] = 'Statistics Canada returned no observations for this series and period.'
    return out


def _check_choice(arguments: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
    if arguments.get('period') and arguments.get('latest_n'):
        raise ValueError('give latest_n or period, not both')
    return arguments.get('latest_n'), arguments.get('period')


class StatcanSearchTablesTool(OpenDataTool):
    """statcan_search_tables: find Statistics Canada tables by words in the title."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        text = str(arguments.get('text') or '').strip()
        words = [w.lower() for w in re.split(r'\s+', text) if w]
        if not words:
            raise ValueError('text is required, e.g. "consumer price index monthly"')
        include_archived = bool(arguments.get('include_archived'))
        hits = []
        for c in cube_list():
            title = str(c.get('cubeTitleEn') or '')
            low = title.lower()
            if not all(w in low for w in words):
                continue
            archived = str(c.get('archived')) == '1'
            if archived and not include_archived:
                continue
            hits.append({'table': table_number(c.get('productId')), 'title': title,
                         'frequency': FREQUENCIES.get(c.get('frequencyCode')),
                         'start': str(c.get('cubeStartDate') or '')[:10] or None,
                         'end': str(c.get('cubeEndDate') or '')[:10] or None,
                         'released': str(c.get('releaseTime') or '')[:10] or None, 'archived': archived})
        hits.sort(key=lambda h: (h['archived'], -(int((h['released'] or '0000')[:4])), h['table']))
        limit = int(arguments.get('limit') or 20)
        out = {'text': text, 'total': len(hits), 'count': min(len(hits), limit), 'tables': hits[:limit],
               'source': SOURCE}
        if not hits:
            out['note'] = 'No table title contains all the words; try fewer words.'
        return out


class StatcanVectorTool(OpenDataTool):
    """statcan_vector: one series by vector id, the latest N periods or a period."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        latest_n, period = _check_choice(arguments)
        vid = vector_id(arguments.get('vector'))
        info = _one(wds('getSeriesInfoFromVector', [{'vectorId': vid}]), f'vector v{vid}')
        return series_data(info, latest_n, period)


class StatcanTableTool(OpenDataTool):
    """statcan_table: one series of a table by coordinate, or the table's dimensions without one."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        pid = product_id(arguments.get('table'))
        if not arguments.get('coordinate'):
            meta = cube_meta(pid)
            limit = int(arguments.get('max_members') or 50)
            dims = []
            for d in meta['dimensions']:
                items = list(d['members'].items())
                dims.append({'position': d['position'], 'name': d['name'], 'member_count': len(items),
                             'members': [{'id': k, 'name': v} for k, v in items[:limit]]})
            return {'table': table_number(pid), 'table_title': meta['title'], 'frequency': meta['frequency'],
                    'start': str(meta['start'] or '')[:10] or None, 'end': str(meta['end'] or '')[:10] or None,
                    'series_count': meta['series_count'], 'archived': meta['archived'], 'dimensions': dims,
                    'source': notice(meta['title'], pid, str(meta['end'] or '')[:10] or None),
                    'note': 'No coordinate given: these are the dimensions. A coordinate is one member id per '
                            'dimension in this order, joined by dots (e.g. 2.2).'}
        latest_n, period = _check_choice(arguments)
        coord = coordinate(arguments.get('coordinate'))
        info = _one(wds('getSeriesInfoFromCubePidCoord', [{'productId': pid, 'coordinate': coord}]),
                    f'table {table_number(pid)} coordinate {coord}')
        return series_data(info, latest_n, period)


class StatcanChangedSeriesTool(OpenDataTool):
    """statcan_changed_series: the tables (and so their series) Statistics Canada released on a date."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        day = parse_date(arguments.get('date'), 'date')
        body = wds(f'getChangedCubeList/{day.isoformat()}')
        if not isinstance(body, dict) or body.get('status') != 'SUCCESS':
            raise ValueError(f'{LABEL}: no change list for {day.isoformat()}')
        titles = {}
        if arguments.get('with_titles'):
            titles = {int(c.get('productId')): c.get('cubeTitleEn') for c in cube_list()}
        tables = []
        for item in body.get('object') or []:
            pid = item.get('productId')
            t = {'table': table_number(pid), 'release_time': item.get('releaseTime')}
            if arguments.get('with_titles'):
                t['title'] = titles.get(int(pid))
            tables.append(t)
        tables.sort(key=lambda t: t['table'])
        out = {'date': day.isoformat(), 'count': len(tables), 'tables': tables, 'source': SOURCE}
        if not tables:
            out['note'] = 'Statistics Canada released no tables on this date (weekend or holiday?).'
        return out
