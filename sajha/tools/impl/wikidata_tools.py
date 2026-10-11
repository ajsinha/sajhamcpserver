"""
SAJHA MCP Server — Wikidata tools in the wikipedia folder (Open Data Tools §5; Roadmap L37).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Wikidata's Action API (www.wikidata.org/w/api.php) and its SPARQL endpoints: the main graph
(query.wikidata.org) and, since the 2025 graph split, the scholarly graph
(query-scholarly.wikidata.org). No key; Wikimedia requires a meaningful User-Agent. Data is CC0.
Every fetch goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from sajha.core import outbound
from sajha.tools.base_mcp_tool import BaseMCPTool

API_URL = 'https://www.wikidata.org/w/api.php'
SPARQL_URLS = {'main': 'https://query.wikidata.org/sparql',
               'scholarly': 'https://query-scholarly.wikidata.org/sparql'}
SOURCE = 'Source: Wikidata (CC0)'
USER_AGENT = 'SAJHA-MCP-Server/8 (https://github.com/ajsinha/sajhamcpserver; Wikidata tools) httpx'
_QID = re.compile(r'^Q[1-9]\d*$')
_PID = re.compile(r'^P[1-9]\d*$')
MAX_VALUES = 20
_WRITE = re.compile(r'\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD)\b', re.I)
_FORM = re.compile(r'^\s*(?:(?:PREFIX\s+[\w-]*:|BASE)\s*<[^>]*>\s*|#[^\n]*\n\s*)*(SELECT|ASK)\b', re.I)

# identifiers of a company (wikidata_company_identifiers)
P_LEI, P_ISIN, P_WEBSITE, P_EXCHANGE, P_TICKER = 'P1278', 'P946', 'P856', 'P414', 'P249'


def _request(url: str, params: List, accept: str, timeout: float) -> Any:
    headers = {'User-Agent': USER_AGENT, 'Accept': accept}
    try:
        r = outbound.request('GET', url, params=params, headers=headers, timeout=timeout)
    except outbound.FetchTimeout:
        raise ValueError(f'Wikidata did not answer within {timeout:g} s')
    except (outbound.Refused, outbound.FetchError) as e:
        raise ValueError(f'could not reach Wikidata: {e}')
    if r.status_code >= 400:
        detail = re.sub(r'\s+', ' ', r.text or '')[:300]
        raise ValueError(f'Wikidata answered HTTP {r.status_code}: {detail}')
    try:
        return r.json()
    except ValueError:
        raise ValueError('Wikidata sent an unreadable answer')


def api(params: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    body = _request(API_URL, list({**params, 'format': 'json'}.items()), 'application/json', timeout)
    if isinstance(body, dict) and body.get('error'):
        raise ValueError(f"Wikidata: {body['error'].get('info') or body['error'].get('code')}")
    return body


def check_qid(value: Any) -> str:
    q = str(value or '').strip().upper()
    if q.startswith('HTTP') and '/' in q:
        q = q.rstrip('/').rsplit('/', 1)[-1]
    if not _QID.match(q):
        raise ValueError(f'{value!r} is not a Wikidata item id (Q followed by digits, e.g. Q66048)')
    return q


def entities(ids: List[str], props: str, language: str) -> Dict[str, Any]:
    if not ids:
        return {}
    body = api({'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': props,
                'languages': language, 'sitefilter': f'{language}wiki'})
    return body.get('entities') or {}


def labels(ids: Iterable[str], language: str, limit: int = 150) -> Dict[str, str]:
    """Labels of items and properties, 50 ids a request, at most ``limit`` ids."""
    ids = list(dict.fromkeys(i for i in ids if i))[:limit]
    out: Dict[str, str] = {}
    for i in range(0, len(ids), 50):
        for eid, e in entities(ids[i:i + 50], 'labels', language).items():
            lab = ((e.get('labels') or {}).get(language) or {}).get('value')
            if lab:
                out[eid] = lab
    return out


def _value(snak: Dict[str, Any]) -> Any:
    """A claim's main value in plain form; None for 'no value' / 'unknown value'."""
    dv = snak.get('datavalue') or {}
    v, t = dv.get('value'), dv.get('type')
    if t == 'wikibase-entityid':
        return {'id': v.get('id')}
    if t == 'time':
        s = str(v.get('time') or '').lstrip('+')
        return s[:10] if s.endswith('T00:00:00Z') else s
    if t == 'quantity':
        unit = str(v.get('unit') or '')
        out = {'amount': float(v.get('amount'))}
        if unit and unit != '1':
            out['unit'] = unit.rsplit('/', 1)[-1]
        return out
    if t == 'monolingualtext':
        return v.get('text')
    if t == 'globecoordinate':
        return {'latitude': v.get('latitude'), 'longitude': v.get('longitude')}
    return v


def _claim_values(claims: List[Dict[str, Any]]) -> List[Any]:
    """Preferred-rank values when any, else normal rank; deprecated ones never."""
    pref = [c for c in claims if c.get('rank') == 'preferred']
    use = pref or [c for c in claims if c.get('rank') != 'deprecated']
    return [v for v in (_value(c.get('mainsnak') or {}) for c in use) if v is not None]


class WikidataBaseTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return {'type': 'object'}


def search(name: str, limit: int, language: str) -> List[Dict[str, Any]]:
    body = api({'action': 'wbsearchentities', 'search': name, 'language': language,
                'uselang': language, 'type': 'item', 'limit': limit})
    return [{'qid': r.get('id'), 'label': r.get('label'), 'description': r.get('description'),
             'url': f"https://www.wikidata.org/wiki/{r.get('id')}",
             'matched': (r.get('match') or {}).get('text')}
            for r in body.get('search') or []]


class WikidataSearchTool(WikidataBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        name = str(arguments.get('name') or '').strip()
        if not name:
            raise ValueError('name is required')
        lang = str(arguments.get('language') or 'en')
        results = search(name, int(arguments.get('limit') or 10), lang)
        return {'query': name, 'result_count': len(results), 'results': results, 'source': SOURCE}


class WikidataEntityTool(WikidataBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        qid = check_qid(arguments.get('qid'))
        lang = str(arguments.get('language') or 'en')
        wanted = [str(p).strip().upper() for p in arguments.get('properties') or []]
        bad = [p for p in wanted if not _PID.match(p)]
        if bad:
            raise ValueError(f'Not property ids: {", ".join(bad)} (use P followed by digits, e.g. P1278)')
        e = entities([qid], 'labels|descriptions|aliases|claims|sitelinks/urls', lang).get(qid) or {}
        if not e or 'missing' in e:
            raise ValueError(f'No Wikidata item {qid}')
        claims = e.get('claims') or {}
        pids = [p for p in wanted if p in claims] if wanted else list(claims)
        values = {p: _claim_values(claims[p]) for p in pids}
        refs = [v['id'] for vs in values.values() for v in vs[:MAX_VALUES] if isinstance(v, dict) and 'id' in v]
        names = labels(pids + refs, lang)
        props = {}
        for p in pids:
            vs = values[p]
            for v in vs:
                if isinstance(v, dict) and v.get('id') in names:
                    v['label'] = names[v['id']]
            props[p] = {'property': names.get(p), 'values': vs[:MAX_VALUES], 'value_count': len(vs)}
        site = (e.get('sitelinks') or {}).get(f'{lang}wiki') or {}
        return {
            'qid': qid,
            'label': ((e.get('labels') or {}).get(lang) or {}).get('value'),
            'description': ((e.get('descriptions') or {}).get(lang) or {}).get('value'),
            'aliases': [a.get('value') for a in (e.get('aliases') or {}).get(lang) or []],
            'url': f'https://www.wikidata.org/wiki/{qid}',
            'wikipedia_url': site.get('url'),
            'property_count': len(pids),
            'missing_properties': [p for p in wanted if p not in claims],
            'properties': props,
            'source': SOURCE,
        }


class WikidataCompanyIdentifiersTool(WikidataBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        lang = 'en'
        if arguments.get('qid'):
            qid, matched_by = check_qid(arguments['qid']), 'qid'
        elif arguments.get('name'):
            hits = search(str(arguments['name']).strip(), 1, lang)
            if not hits:
                raise ValueError(f"No Wikidata item matches {arguments['name']!r}")
            qid, matched_by = hits[0]['qid'], 'name (top search result)'
        else:
            raise ValueError('Give name or qid')
        e = entities([qid], 'labels|descriptions|claims', lang).get(qid) or {}
        if not e or 'missing' in e:
            raise ValueError(f'No Wikidata item {qid}')
        claims = e.get('claims') or {}
        tickers = []
        for c in claims.get(P_EXCHANGE) or []:
            if c.get('rank') == 'deprecated' or (c.get('qualifiers') or {}).get('P582'):
                continue            # delisted (an end time) or deprecated
            ex = _value(c.get('mainsnak') or {}) or {}
            for q in (c.get('qualifiers') or {}).get(P_TICKER) or []:
                t = _value(q)
                if t:
                    tickers.append({'ticker': t, 'exchange_qid': ex.get('id')})
        for t in _claim_values(claims.get(P_TICKER) or []):
            if not any(x['ticker'] == t for x in tickers):
                tickers.append({'ticker': t, 'exchange_qid': None})
        names = labels([t['exchange_qid'] for t in tickers], lang)
        for t in tickers:
            t['exchange'] = names.get(t['exchange_qid'])
        lei = _claim_values(claims.get(P_LEI) or [])
        return {
            'qid': qid,
            'matched_by': matched_by,
            'label': ((e.get('labels') or {}).get(lang) or {}).get('value'),
            'description': ((e.get('descriptions') or {}).get(lang) or {}).get('value'),
            'lei': lei[0] if lei else None,
            'isins': _claim_values(claims.get(P_ISIN) or []),
            'tickers': tickers,
            'official_websites': _claim_values(claims.get(P_WEBSITE) or []),
            'source': SOURCE,
        }


def check_read_only(query: str) -> str:
    q = str(query or '').strip()
    if not q:
        raise ValueError('query is required')
    if not _FORM.match(q + '\n'):
        raise ValueError('Only SELECT and ASK queries are allowed')
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|<[^>\s]*>|#[^\n]*', ' ', q)
    if _WRITE.search(stripped):
        raise ValueError('The query is read-only: update operations are refused')
    return q


def _cell(b: Dict[str, Any]) -> Any:
    v = b.get('value')
    dt = str(b.get('datatype') or '')
    if dt.endswith(('#integer', '#decimal', '#double', '#float')):
        try:
            return float(v) if not dt.endswith('#integer') else int(v)
        except (TypeError, ValueError):
            return v
    return v


class WikidataSparqlTool(WikidataBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        query = check_read_only(arguments.get('query'))
        graph = 'scholarly' if arguments.get('graph') == 'scholarly' else 'main'
        max_rows = int(arguments.get('max_rows') or 100)
        timeout = float(arguments.get('timeout_seconds') or 30)
        if re.match(r'(?is)^.*\bSELECT\b', query) and not re.search(r'(?i)\bLIMIT\s+\d+\s*$', query):
            query = f'{query}\nLIMIT {max_rows + 1}'
        body = _request(SPARQL_URLS[graph], [('query', query), ('format', 'json')],
                        'application/sparql-results+json', timeout)
        if 'boolean' in body:
            return {'graph': graph, 'columns': [], 'boolean': bool(body['boolean']), 'rows': [],
                    'row_count': 0, 'truncated': False, 'source': SOURCE}
        cols = (body.get('head') or {}).get('vars') or []
        bindings = (body.get('results') or {}).get('bindings') or []
        rows = [{c: _cell(b[c]) for c in cols if c in b} for b in bindings[:max_rows]]
        return {'graph': graph, 'columns': cols, 'rows': rows, 'row_count': len(rows),
                'truncated': len(bindings) > max_rows, 'source': SOURCE}
