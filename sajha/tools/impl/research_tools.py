"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Research literature tools (tool folder ``research``; Open Data Tools §4, L37).

* **OpenAlex** (``api.openalex.org``, CC0). Usage-priced: without a key a shared budget of about
  US$0.10 a day per IP, with a free key US$1 a day (each list call cost US$0.001 when checked on
  2026-10-11, filter or search alike; a single work cost nothing). An operator's free key goes in the
  environment variable ``OPENALEX_API_KEY`` and is sent as ``api_key``. Results report the budget
  OpenAlex says remains. Nothing is bought (Open Data Tools §6).
* **Crossref** (``api.crossref.org``): metadata usable for any purpose. A contact address in
  ``CROSSREF_MAILTO`` is sent as ``mailto`` (the polite pool). Throttled to 3 requests a second.
* **arXiv** (``export.arxiv.org/api/query``): metadata CC0; e-prints may not be stored or served, so
  results carry links only. arXiv allows one request every 3 seconds across all machines: every call
  takes the one slot in a 3-second window in the state store.

Every fetch goes through the outbound fetch guard (``sajha/core/outbound.py``); results are cached
(``cache_ttl`` in each config).
"""

from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sajha.tools.impl.open_data_common import OpenDataTool, fetch, get_json, take_slot

OPENALEX = 'https://api.openalex.org'
OPENALEX_SOURCE = 'OpenAlex (openalex.org), CC0'
OPENALEX_KEY_ENV = 'OPENALEX_API_KEY'
CROSSREF = 'https://api.crossref.org'
CROSSREF_SOURCE = 'Crossref (api.crossref.org)'
CROSSREF_MAILTO_ENV = 'CROSSREF_MAILTO'
ARXIV = 'https://export.arxiv.org/api/query'
ARXIV_SOURCE = 'arXiv (arxiv.org); metadata CC0; links only, e-prints are not stored or served'

_DOI = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)?(10\.\d{4,9}/\S+)$', re.I)


def _doi(value: Any) -> Optional[str]:
    m = _DOI.match(str(value or '').strip())
    return m.group(1) if m else None


# ── OpenAlex ────────────────────────────────────────────────────────────────

OA_SELECT = ('id,doi,title,publication_year,publication_date,type,primary_location,authorships,'
             'cited_by_count,open_access')
OA_SORT = {'relevance': 'relevance_score:desc', 'cited_by_count': 'cited_by_count:desc',
           'publication_date': 'publication_date:desc'}


def _openalex(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    key = os.environ.get(OPENALEX_KEY_ENV, '').strip()
    if key:
        params = dict(params, api_key=key)
    take_slot('opendata:openalex:requests', 10, 1.0, 10.0, 'OpenAlex')
    r = fetch('OpenAlex', 'GET', f'{OPENALEX}{path}', params=params)
    body = r.json()
    remaining = r.headers.get('x-ratelimit-remaining-usd')
    body['_budget'] = {'cost_usd': _f(r.headers.get('x-ratelimit-cost-usd')),
                       'remaining_usd': _f(remaining), 'keyed': bool(key)}
    return body


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _oa_work(w: Dict[str, Any]) -> Dict[str, Any]:
    loc = w.get('primary_location') or {}
    src = loc.get('source') or {}
    oa = w.get('open_access') or {}
    authors = [((a.get('author') or {}).get('display_name')) for a in (w.get('authorships') or [])]
    authors = [a for a in authors if a]
    return {
        'id': (w.get('id') or '').rsplit('/', 1)[-1] or None,
        'doi': _doi(w.get('doi')) if w.get('doi') else None,
        'title': w.get('title') or w.get('display_name'),
        'publication_year': w.get('publication_year'), 'publication_date': w.get('publication_date'),
        'type': w.get('type'), 'venue': src.get('display_name'),
        'authors': authors[:10], 'author_count': len(authors),
        'cited_by_count': w.get('cited_by_count'),
        'open_access': bool(oa.get('is_oa')), 'open_access_url': oa.get('oa_url'),
        'landing_page': loc.get('landing_page_url'),
    }


class ResearchSearchWorksTool(OpenDataTool):
    """research_search_works: scholarly works from OpenAlex, by title-and-abstract filter or full search."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        query = str(arguments.get('query') or '').strip()
        if not query:
            raise ValueError('query is required')
        filters = []
        if not arguments.get('full_text_search'):
            filters.append('title_and_abstract.search:' + query.replace(',', ' '))
        y0, y1 = arguments.get('from_year'), arguments.get('to_year')
        if y0 and y1:
            filters.append(f'publication_year:{int(y0)}-{int(y1)}')
        elif y0:
            filters.append(f'publication_year:>{int(y0) - 1}')
        elif y1:
            filters.append(f'publication_year:<{int(y1) + 1}')
        if arguments.get('type'):
            filters.append(f'type:{arguments["type"]}')
        if arguments.get('open_access') is not None:
            filters.append(f'is_oa:{str(bool(arguments["open_access"])).lower()}')
        sort = arguments.get('sort') or 'relevance'
        params = {'filter': ','.join(filters) or None, 'search': query if arguments.get('full_text_search') else None,
                  'per-page': int(arguments.get('limit') or 10), 'select': OA_SELECT, 'sort': OA_SORT.get(sort)}
        body = _openalex('/works', params)
        works = [_oa_work(w) for w in body.get('results') or []]
        total = int((body.get('meta') or {}).get('count') or len(works))
        return {'query': query, 'mode': 'search' if arguments.get('full_text_search') else 'filter',
                'count': len(works), 'total': total, 'truncated': total > len(works), 'works': works,
                'budget': body['_budget'], 'source': OPENALEX_SOURCE}


def _abstract(inverted: Optional[Dict[str, List[int]]]) -> Optional[str]:
    if not inverted:
        return None
    pos = {}
    for word, places in inverted.items():
        for p in places:
            pos[p] = word
    return ' '.join(pos[i] for i in sorted(pos))


class ResearchGetWorkTool(OpenDataTool):
    """research_get_work: one work from OpenAlex by DOI or OpenAlex id, with its abstract and topics."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ident = str(arguments.get('id') or '').strip()
        doi = _doi(ident)
        if doi:
            path = '/works/doi:' + quote(doi, safe='/')
        elif re.fullmatch(r'(https?://openalex\.org/)?W\d+', ident, re.I):
            path = '/works/' + ident.rsplit('/', 1)[-1].upper()
        else:
            raise ValueError('id must be a DOI (10.xxxx/...) or an OpenAlex work id (W123...)')
        w = _openalex(path, {})
        out = _oa_work(w)
        out.update({
            'abstract': _abstract(w.get('abstract_inverted_index')),
            'topics': [t.get('display_name') for t in (w.get('topics') or []) if t.get('display_name')][:10],
            'referenced_works_count': w.get('referenced_works_count'),
            'language': w.get('language'),
            'is_retracted': bool(w.get('is_retracted')),
            'publisher': ((w.get('primary_location') or {}).get('source') or {}).get('host_organization_name'),
        })
        return {'work': out, 'budget': w['_budget'], 'source': OPENALEX_SOURCE}


# ── Crossref ────────────────────────────────────────────────────────────────

def _crossref(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    mailto = os.environ.get(CROSSREF_MAILTO_ENV, '').strip()
    if mailto:
        params = dict(params, mailto=mailto)
    take_slot('opendata:crossref:requests', 3, 1.0, 10.0, 'Crossref')
    body = get_json('Crossref', f'{CROSSREF}{path}', params=params)
    return body.get('message') or {}


def _text(value: Optional[str]) -> Optional[str]:
    """Crossref strings may carry HTML entities and JATS tags."""
    return html.unescape(re.sub(r'<[^>]+>', '', value)).strip() if value else value


def _date_parts(d: Optional[Dict[str, Any]]) -> Optional[str]:
    parts = ((d or {}).get('date-parts') or [[None]])[0]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    return '-'.join([f'{parts[0]:04d}'] + [f'{p:02d}' for p in parts[1:]])


def _cr_item(it: Dict[str, Any]) -> Dict[str, Any]:
    authors = []
    for a in it.get('author') or []:
        name = ' '.join(x for x in (a.get('given'), a.get('family')) if x) or a.get('name')
        if name:
            authors.append(name)
    published = it.get('published') or it.get('published-print') or it.get('published-online') or it.get('issued')
    return {
        'doi': it.get('DOI'), 'title': _text((it.get('title') or [None])[0]),
        'type': it.get('type'), 'published': _date_parts(published),
        'venue': _text((it.get('container-title') or [None])[0]), 'publisher': _text(it.get('publisher')),
        'authors': authors[:10], 'author_count': len(authors),
        'cited_by_count': it.get('is-referenced-by-count'), 'url': it.get('URL'),
    }


CR_SORT = {'relevance': ('relevance', 'desc'), 'published': ('published', 'desc'),
           'cited_by_count': ('is-referenced-by-count', 'desc')}


class ResearchCrossrefWorksTool(OpenDataTool):
    """research_crossref_works: works registered with Crossref, by query and filters."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        query = str(arguments.get('query') or '').strip()
        if not query:
            raise ValueError('query is required')
        filters = []
        if arguments.get('from'):
            filters.append(f'from-pub-date:{arguments["from"]}')
        if arguments.get('to'):
            filters.append(f'until-pub-date:{arguments["to"]}')
        if arguments.get('type'):
            filters.append(f'type:{arguments["type"]}')
        sort, order = CR_SORT.get(arguments.get('sort') or 'relevance', CR_SORT['relevance'])
        msg = _crossref('/works', {'query': query, 'filter': ','.join(filters) or None,
                                   'rows': int(arguments.get('limit') or 10), 'sort': sort, 'order': order,
                                   'select': 'DOI,title,type,published,published-print,published-online,issued,'
                                             'container-title,publisher,author,is-referenced-by-count,URL'})
        items = [_cr_item(i) for i in msg.get('items') or []]
        total = int(msg.get('total-results') or len(items))
        return {'query': query, 'count': len(items), 'total': total, 'truncated': total > len(items),
                'works': items, 'source': CROSSREF_SOURCE}


class ResearchCrossrefDoiTool(OpenDataTool):
    """research_crossref_doi: the Crossref record of one DOI."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        doi = _doi(arguments.get('doi'))
        if not doi:
            raise ValueError('doi must look like 10.xxxx/... (a doi.org URL is accepted)')
        it = _crossref('/works/' + quote(doi, safe='/'), {})
        out = _cr_item(it)
        out.update({
            'abstract': _text(it.get('abstract')),
            'subjects': it.get('subject') or [],
            'references_count': it.get('references-count'),
            'issn': it.get('ISSN') or [], 'isbn': it.get('ISBN') or [],
            'licenses': [lic.get('URL') for lic in (it.get('license') or []) if lic.get('URL')],
        })
        return {'work': out, 'source': CROSSREF_SOURCE}


# ── arXiv ───────────────────────────────────────────────────────────────────

ATOM = '{http://www.w3.org/2005/Atom}'
ARXIV_NS = '{http://arxiv.org/schemas/atom}'
OPENSEARCH = '{http://a9.com/-/spec/opensearch/1.1/}'
ARXIV_SORT = {'relevance': 'relevance', 'submitted': 'submittedDate', 'updated': 'lastUpdatedDate'}


def _clean(text: Optional[str]) -> Optional[str]:
    return re.sub(r'\s+', ' ', text).strip() if text else None


class ResearchArxivSearchTool(OpenDataTool):
    """research_arxiv_search: arXiv preprints by query and category; links only."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        from defusedxml import ElementTree as DET
        query = str(arguments.get('query') or '').strip()
        category = str(arguments.get('category') or '').strip()
        if not query and not category:
            raise ValueError('give a query, a category, or both')
        if category and not re.fullmatch(r'[a-z\-]+(\.[A-Za-z\-]+)?', category):
            raise ValueError('category must be an arXiv category such as q-fin.RM or stat.ML')
        parts = []
        if query:
            words = [w for w in re.split(r'\s+', query.replace('"', ' ')) if w]
            parts.append(' AND '.join(f'all:{w}' for w in words))
        if category:
            parts.append(f'cat:{category}')
        sort = arguments.get('sort') or 'relevance'
        params = {'search_query': ' AND '.join(f'({p})' if ' ' in p else p for p in parts),
                  'start': 0, 'max_results': int(arguments.get('max_results') or 10),
                  'sortBy': ARXIV_SORT.get(sort, 'relevance'), 'sortOrder': 'descending'}
        take_slot('opendata:arxiv:requests', 1, 3.0, 30.0, 'arXiv')
        r = fetch('arXiv', 'GET', ARXIV, params=params, accept='application/atom+xml', timeout=60)
        try:
            root = DET.fromstring(r.content)
        except Exception as e:
            raise ValueError(f'arXiv answered with unreadable XML: {e}')
        papers = []
        for e in root.findall(f'{ATOM}entry'):
            ident = (e.findtext(f'{ATOM}id') or '').strip()
            arxiv_id = ident.rsplit('/abs/', 1)[-1] if '/abs/' in ident else ident
            primary = e.find(f'{ARXIV_NS}primary_category')
            papers.append({
                'arxiv_id': arxiv_id, 'title': _clean(e.findtext(f'{ATOM}title')),
                'authors': [_clean(a.findtext(f'{ATOM}name')) for a in e.findall(f'{ATOM}author')][:10],
                'published': (e.findtext(f'{ATOM}published') or '')[:10] or None,
                'updated': (e.findtext(f'{ATOM}updated') or '')[:10] or None,
                'primary_category': primary.get('term') if primary is not None else None,
                'categories': [c.get('term') for c in e.findall(f'{ATOM}category') if c.get('term')],
                'summary': _clean(e.findtext(f'{ATOM}summary')),
                'doi': _clean(e.findtext(f'{ARXIV_NS}doi')),
                'abs_url': f'https://arxiv.org/abs/{arxiv_id}' if arxiv_id else None,
            })
        total_text = root.findtext(f'{OPENSEARCH}totalResults')
        total = int(total_text) if total_text and total_text.isdigit() else len(papers)
        return {'query': query or None, 'category': category or None, 'count': len(papers), 'total': total,
                'truncated': total > len(papers), 'papers': papers, 'source': ARXIV_SOURCE}
