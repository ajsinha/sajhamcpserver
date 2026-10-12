"""
SAJHA MCP Server — GLEIF LEI tools (Open Data Tools §4, P1; Roadmap L27).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The Global LEI Foundation's JSON:API at api.gleif.org/api/v1 (no key; LEI data is CC0). Every
fetch goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``), and
only to that base URL. A 404 on a parent relationship means "no parent reported", not an error:
the entity either filed a reporting exception (fetched and returned) or has nothing to report.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sajha.core import outbound
from sajha.tools.base_mcp_tool import BaseMCPTool

BASE_URL = 'https://api.gleif.org/api/v1'
SOURCE = 'Source: GLEIF LEI data (api.gleif.org), CC0'
USER_AGENT = 'SAJHA-MCP-Server (GLEIF tools)'
_LEI = re.compile(r'^[A-Z0-9]{18}[0-9]{2}$')
_ISIN = re.compile(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$')


class GleifError(ValueError):
    pass


def get(path: str, params: Optional[List[Tuple[str, str]]] = None,
        timeout: float = 30.0) -> Tuple[int, Any]:
    """(status, JSON body or None). 404 gives (404, None); other errors raise GleifError."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/vnd.api+json'}
    try:
        r = outbound.request('GET', url, params=params or [], headers=headers, timeout=timeout)
    except outbound.FetchTimeout:
        raise GleifError(f'GLEIF did not answer within {timeout:g} s')
    except (outbound.Refused, outbound.FetchError) as e:
        raise GleifError(f'could not reach GLEIF: {e}')
    if r.status_code == 404:
        return 404, None
    if r.status_code >= 400:
        raise GleifError(f'GLEIF answered HTTP {r.status_code} for {path}')
    try:
        return r.status_code, r.json()
    except ValueError:
        raise GleifError(f'GLEIF sent an unreadable answer for {path}')


def check_lei(value: Any) -> str:
    lei = str(value or '').strip().upper()
    if not _LEI.match(lei):
        raise ValueError(f'{value!r} is not an LEI (20 characters: 18 letters or digits, then 2 check digits)')
    return lei


def _address(a: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not a:
        return None
    return {'lines': a.get('addressLines') or [], 'city': a.get('city'), 'region': a.get('region'),
            'country': a.get('country'), 'postal_code': a.get('postalCode')}


def summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The short form of an lei-records resource, used in lists."""
    a = rec.get('attributes') or {}
    e, reg = a.get('entity') or {}, a.get('registration') or {}
    return {'lei': a.get('lei') or rec.get('id'),
            'legal_name': (e.get('legalName') or {}).get('name'),
            'country': (e.get('legalAddress') or {}).get('country'),
            'jurisdiction': e.get('jurisdiction'),
            'entity_status': e.get('status'),
            'registration_status': reg.get('status')}


def record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The full form of an lei-records resource."""
    a = rec.get('attributes') or {}
    e, reg = a.get('entity') or {}, a.get('registration') or {}
    out = summary(rec)
    out.update({
        'other_names': [n.get('name') for n in e.get('otherNames') or [] if n.get('name')],
        'legal_address': _address(e.get('legalAddress')),
        'headquarters_address': _address(e.get('headquartersAddress')),
        'legal_form': (e.get('legalForm') or {}).get('id'),
        'category': e.get('category'),
        'registered_as': e.get('registeredAs'),
        'creation_date': e.get('creationDate'),
        'successor_lei': (e.get('successorEntity') or {}).get('lei'),
        'initial_registration_date': reg.get('initialRegistrationDate'),
        'last_update_date': reg.get('lastUpdateDate'),
        'next_renewal_date': reg.get('nextRenewalDate'),
        'managing_lou': reg.get('managingLou'),
        'corroboration_level': reg.get('corroborationLevel'),
        'bic': a.get('bic') or [],
    })
    return out


def _total(body: Dict[str, Any], rows: int) -> int:
    return int(((body.get('meta') or {}).get('pagination') or {}).get('total') or rows)


class GleifBaseTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return {'type': 'object'}

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        try:
            return self.run(arguments)
        except GleifError as e:
            raise ValueError(str(e)) from e

    def run(self, arguments: Dict[str, Any]) -> Dict:
        raise NotImplementedError

    @staticmethod
    def _record(lei: str) -> Dict[str, Any]:
        status, body = get(f'lei-records/{lei}')
        if status == 404 or not (body or {}).get('data'):
            raise ValueError(f'No LEI record for {lei}')
        return body['data']


class GleifLookupTool(GleifBaseTool):
    def run(self, arguments: Dict[str, Any]) -> Dict:
        if arguments.get('lei'):
            out = record(self._record(check_lei(arguments['lei'])))
        elif arguments.get('isin'):
            isin = str(arguments['isin']).strip().upper()
            if not _ISIN.match(isin):
                raise ValueError(f'{arguments["isin"]!r} is not an ISIN (12 characters, e.g. US0378331005)')
            _, body = get('lei-records', [('filter[isin]', isin)])
            data = (body or {}).get('data') or []
            if not data:
                raise ValueError(f'No LEI record is linked to ISIN {isin}')
            out = record(data[0])
            out['isin'] = isin
        else:
            raise ValueError('Give lei or isin')
        out['source'] = SOURCE
        return out


class GleifSearchTool(GleifBaseTool):
    def run(self, arguments: Dict[str, Any]) -> Dict:
        name = str(arguments.get('name') or '').strip()
        if not name:
            raise ValueError('name is required')
        limit = int(arguments.get('limit') or 10)
        filters = []
        if arguments.get('country'):
            filters.append(('filter[entity.legalAddress.country]', str(arguments['country']).strip().upper()))
        if arguments.get('status'):
            filters.append(('filter[entity.status]', str(arguments['status']).strip().upper()))
        page = [('page[size]', str(limit)), ('page[number]', '1')]
        _, body = get('lei-records', [('filter[entity.names]', name)] + filters + page)
        data = (body or {}).get('data') or []
        matched_by = 'name'
        total = _total(body or {}, len(data))
        matched_values: Dict[str, str] = {}
        if not data:
            # no name contains the words: GLEIF's fuzzy completion over every field, then over the
            # legal name alone (it tolerates about one typo per word), then those records in its order
            leis = []
            for field in ('fulltext', 'entity.legalName'):
                _, fz = get('fuzzycompletions', [('field', field), ('q', name)])
                for item in (fz or {}).get('data') or []:
                    ref = (((item.get('relationships') or {}).get('lei-records') or {}).get('data') or {})
                    if ref.get('id') and ref['id'] not in leis:
                        leis.append(ref['id'])
                        matched_values[ref['id']] = str((item.get('attributes') or {}).get('value') or '')
                if leis:
                    break
            if leis:
                _, body = get('lei-records', [('filter[lei]', ','.join(leis[:limit]))] + filters + page)
                data = (body or {}).get('data') or []
                rank = {lei: i for i, lei in enumerate(leis)}
                data.sort(key=lambda r: rank.get(r.get('id'), len(rank)))   # GLEIF's best match first
                total = len(data)
                matched_by = 'fuzzy'
        out = {'query': name, 'matched_by': matched_by, 'total': total, 'result_count': len(data),
               'results': [summary(r) for r in data], 'source': SOURCE}
        if matched_by == 'fuzzy':
            for r, raw in zip(out['results'], data):
                if matched_values.get(raw.get('id')):
                    r['matched_value'] = matched_values[raw['id']]       # the name or field GLEIF matched
        if not data:
            out['note'] = ('No LEI record matched, by name or by GLEIF\'s fuzzy match (about one typo per word). '
                           'Try fewer words, correct spelling, or the legal name in its local language.')
        return out


def _relation(lei: str, kind: str, rel_links: Dict[str, Any]) -> Dict[str, Any]:
    """One parent (kind: direct or ultimate): the parent, the reporting exception, or neither."""
    if not rel_links.get('reporting-exception'):        # links name the parent (lei-record) or nothing
        status, body = get(f'lei-records/{lei}/{kind}-parent')
        if status != 404 and (body or {}).get('data'):
            return {'status': 'reported', 'parent': summary(body['data'])}
    status, body = get(f'lei-records/{lei}/{kind}-parent-reporting-exception')
    if status != 404 and (body or {}).get('data'):
        a = body['data'].get('attributes') or {}
        return {'status': 'reporting_exception',
                'exception': {'category': a.get('category'), 'reason': a.get('reason'),
                              'reference': a.get('reference')}}
    return {'status': 'not_applicable'}


class GleifParentsTool(GleifBaseTool):
    def run(self, arguments: Dict[str, Any]) -> Dict:
        lei = check_lei(arguments.get('lei'))
        rec = self._record(lei)
        rels = rec.get('relationships') or {}
        out = {'lei': lei, 'legal_name': summary(rec)['legal_name']}
        for kind in ('direct', 'ultimate'):
            out[f'{kind}_parent'] = _relation(lei, kind, (rels.get(f'{kind}-parent') or {}).get('links') or {})
        out['source'] = SOURCE
        return out


class GleifChildrenTool(GleifBaseTool):
    def run(self, arguments: Dict[str, Any]) -> Dict:
        lei = check_lei(arguments.get('lei'))
        level = 'ultimate' if arguments.get('level') == 'ultimate' else 'direct'
        limit, page = int(arguments.get('limit') or 50), int(arguments.get('page') or 1)
        status, body = get(f'lei-records/{lei}/{level}-children',
                           [('page[size]', str(limit)), ('page[number]', str(page))])
        data = (body or {}).get('data') or [] if status != 404 else []
        total = _total(body or {}, len(data)) if data else 0
        return {'lei': lei, 'level': level, 'total': total, 'page': page, 'result_count': len(data),
                'more': total > (page - 1) * limit + len(data),
                'children': [summary(r) for r in data], 'source': SOURCE}


class GleifIsinsTool(GleifBaseTool):
    def run(self, arguments: Dict[str, Any]) -> Dict:
        lei = check_lei(arguments.get('lei'))
        limit, page = int(arguments.get('limit') or 100), int(arguments.get('page') or 1)
        status, body = get(f'lei-records/{lei}/isins', [('page[size]', str(limit)), ('page[number]', str(page))])
        data = (body or {}).get('data') or [] if status != 404 else []
        total = _total(body or {}, len(data)) if data else 0
        isins = [(r.get('attributes') or {}).get('isin') for r in data]
        return {'lei': lei, 'total': total, 'page': page, 'result_count': len(isins),
                'more': total > (page - 1) * limit + len(isins),
                'isins': [i for i in isins if i], 'source': SOURCE}
