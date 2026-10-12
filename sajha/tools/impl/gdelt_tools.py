"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

GDELT tools (tool folder ``gdelt``; Open Data Tools §4, L38): the DOC 2.0 and Context 2.0 APIs at
``api.gdeltproject.org/api/v2``. Keyless; GDELT's terms allow unlimited use, commercial included,
with a citation of the GDELT Project and a link to https://www.gdeltproject.org/, which every result
carries in ``source``. GEO 2.0 answers 404 and is not offered; TV 2.0 answers but has
held no data since October 2024 (checked 2026-10-12), so it is not offered either.

GDELT allows one request every 5 seconds (stated only in its 429 message), so every call takes the one
slot in a 5-second window in the state store, shared by every worker, and waits up to 30 seconds for it.
A 429 answer is retried once, in the next slot.
Results are cached (``cache_ttl`` in each config). Every fetch goes through the outbound fetch guard
(``sajha/core/outbound.py``).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sajha.tools.impl.open_data_common import OpenDataTool, fetch, take_slot
from sajha.tools.impl.us_treasury_tools import parse_date

BASE = 'https://api.gdeltproject.org/api/v2'
SOURCE = 'The GDELT Project (https://www.gdeltproject.org/)'
THROTTLE_KEY = 'opendata:gdelt:requests'
SORTS = {'date': 'datedesc', 'relevance': 'hybridrel', 'tone_ascending': 'toneasc', 'tone_descending': 'tonedesc'}


def _range(arguments: Dict[str, Any], default_days: int = 7, max_days: Optional[int] = None):
    to = parse_date(arguments['to'], 'to') if arguments.get('to') else date.today()
    frm = parse_date(arguments['from'], 'from') if arguments.get('from') else to - timedelta(days=default_days)
    if frm > to:
        raise ValueError('from is after to')
    if max_days and (to - frm).days > max_days:
        raise ValueError(f'this GDELT API covers at most {max_days} days per call')
    return frm, to


def _stamp(d: date, end: bool = False) -> str:
    return d.strftime('%Y%m%d') + ('235959' if end else '000000')


def _seen(value: Any) -> Optional[str]:
    """GDELT's ``20261012T034649Z`` or ``20261012034649`` as ISO 8601 UTC."""
    s = str(value or '').strip()
    m = re.fullmatch(r'(\d{4})(\d{2})(\d{2})T?(\d{2})(\d{2})(\d{2})Z?', s)
    if not m:
        return s or None
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}Z'


def gdelt(api: str, params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params, format='json')
    for attempt in (1, 2):
        take_slot(THROTTLE_KEY, 1, 5.0, 30.0, 'GDELT')
        try:
            r = fetch('GDELT', 'GET', f'{BASE}/{api}', params=params, timeout=60)
            break
        except ValueError as e:
            # GDELT answers 429 often even at its stated pace; one more try in the next slot
            if attempt == 2 or 'HTTP 429' not in str(e):
                raise
    text = r.text.strip()
    if not text:
        return {}
    if not text.startswith('{'):
        # GDELT answers query errors as plain text with HTTP 200
        raise ValueError(f'GDELT refused the query: {text[:300]}')
    try:
        return r.json()
    except ValueError:
        raise ValueError(f'GDELT answered with unreadable JSON: {text[:200]}')


def _query(arguments: Dict[str, Any]) -> str:
    q = str(arguments.get('query') or '').strip()
    if not q:
        raise ValueError('query is required')
    if arguments.get('source_country'):
        q += f' sourcecountry:{str(arguments["source_country"]).strip()}'
    if arguments.get('language'):
        q += f' sourcelang:{str(arguments["language"]).strip()}'
    if arguments.get('domain'):
        q += f' domain:{str(arguments["domain"]).strip()}'
    return q


class GdeltTool(OpenDataTool):
    # The live tool check spaces GDELT calls a minute apart: on 2026-10-12 the DOC API refused (429)
    # calls far slower than its stated one every 5 seconds, and took them a minute or more apart.
    check_pause_seconds = 60.0


def _article(a: Dict[str, Any]) -> Dict[str, Any]:
    return {'url': a.get('url'), 'title': a.get('title'), 'seen_at': _seen(a.get('seendate')),
            'domain': a.get('domain'), 'language': a.get('language'),
            'source_country': a.get('sourcecountry') or None}


class GdeltArticlesTool(GdeltTool):
    """gdelt_articles: news articles worldwide that match a query (DOC 2.0)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        frm, to = _range(arguments, max_days=92)
        limit = int(arguments.get('max_records') or 25)
        body = gdelt('doc/doc', {'query': _query(arguments), 'mode': 'artlist', 'maxrecords': limit,
                                 'sort': SORTS.get(arguments.get('sort') or 'date', 'datedesc'),
                                 'startdatetime': _stamp(frm), 'enddatetime': _stamp(to, True)})
        arts = [_article(a) for a in body.get('articles') or []]
        return {'query': arguments['query'], 'from': frm.isoformat(), 'to': to.isoformat(), 'count': len(arts),
                'truncated': len(arts) >= limit, 'articles': arts, 'source': SOURCE}


def _timeline(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for series in body.get('timeline') or []:
        pts = [{'date': _seen(p.get('date')), 'value': p.get('value'),
                **({'total': p['norm']} if 'norm' in p else {})} for p in series.get('data') or []]
        out.append({'series': series.get('series'), 'points': pts})
    return out


class GdeltCoverageTimelineTool(GdeltTool):
    """gdelt_coverage_timeline: how much of the world's news covers a query, or its average tone, over time."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        frm, to = _range(arguments, default_days=30, max_days=92)
        measure = arguments.get('measure') or 'volume'
        mode = {'volume': 'timelinevol', 'article_count': 'timelinevolraw', 'tone': 'timelinetone'}.get(measure)
        if not mode:
            raise ValueError('measure must be volume, article_count or tone')
        body = gdelt('doc/doc', {'query': _query(arguments), 'mode': mode, 'startdatetime': _stamp(frm),
                                 'enddatetime': _stamp(to, True)})
        units = {'volume': 'percent of all articles GDELT monitored in each interval',
                 'article_count': 'number of matching articles in each interval (total: all articles monitored)',
                 'tone': 'average tone of matching articles, about -10 (very negative) to +10 (very positive)'}[measure]
        timeline = _timeline(body)
        return {'query': arguments['query'], 'measure': measure, 'from': frm.isoformat(), 'to': to.isoformat(),
                'units': units, 'count': sum(len(s['points']) for s in timeline), 'timeline': timeline,
                'source': SOURCE}


class GdeltContextTool(GdeltTool):
    """gdelt_context: sentences from recent news that mention a query, with their context (Context 2.0)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        limit = int(arguments.get('max_records') or 25)
        params: Dict[str, Any] = {'query': _query(arguments), 'mode': 'artlist', 'maxrecords': limit}
        if arguments.get('from') or arguments.get('to'):
            frm, to = _range(arguments, default_days=3)
            params.update({'startdatetime': _stamp(frm), 'enddatetime': _stamp(to, True)})
        body = gdelt('context/context', params)
        out = []
        for a in body.get('articles') or []:
            item = _article(a)
            item.update({'sentence': a.get('sentence'), 'context': a.get('context'), 'is_quote': bool(a.get('isquote'))})
            out.append(item)
        return {'query': arguments['query'], 'count': len(out), 'truncated': len(out) >= limit,
                'articles': out, 'source': SOURCE}
