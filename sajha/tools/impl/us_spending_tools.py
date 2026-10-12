"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

US federal spending and the data.gov catalogue (tool folder ``us_spending``; Open Data Tools §4, L39).

* **USAspending** (``api.usaspending.gov/api/v2``): keyless, a US government work, no published limit.
  Searches cover award dates from 2007-10-01 (USAspending's own floor). Amounts are US dollars.
* **data.gov catalogue** (``catalog.data.gov``): the new catalogue API (``/search`` and
  ``/api/dataset/{slug_or_id}``, OpenAPI "Datagov Catalog" 0.1.0); the old CKAN API at ``/api/3``
  answers 404. Metadata is public domain; each dataset carries its own licence. The API is
  undocumented beyond its OpenAPI file, so ``tests/test_open_data_p3.py`` pins its shape.

Every fetch goes through the outbound fetch guard (``sajha/core/outbound.py``); results are cached
(``cache_ttl`` in each config).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from sajha.tools.impl.open_data_common import OpenDataTool, get_json, post_json
from sajha.tools.impl.us_treasury_tools import parse_date

USA = 'https://api.usaspending.gov/api/v2'
USA_SOURCE = 'USAspending.gov (U.S. Department of the Treasury)'
DATAGOV = 'https://catalog.data.gov'
DATAGOV_SOURCE = 'data.gov catalog (catalog.data.gov); each dataset carries its own licence'
FLOOR = date(2007, 10, 1)

AWARD_TYPES = {
    'contracts': ['A', 'B', 'C', 'D'],
    'idvs': ['IDV_A', 'IDV_B', 'IDV_B_A', 'IDV_B_B', 'IDV_B_C', 'IDV_C', 'IDV_D', 'IDV_E'],
    'grants': ['02', '03', '04', '05'],
    'direct_payments': ['06', '10'],
    'loans': ['07', '08'],
    'other': ['09', '11', '-1'],
}
CATEGORIES = ('awarding_agency', 'awarding_subagency', 'funding_agency', 'recipient', 'cfda', 'naics', 'psc',
              'country', 'state_territory', 'county', 'district', 'federal_account')


def _fiscal_year_start(d: date) -> date:
    return date(d.year if d.month >= 10 else d.year - 1, 10, 1)


def _period(arguments: Dict[str, Any]):
    to = parse_date(arguments['to'], 'to') if arguments.get('to') else date.today()
    frm = parse_date(arguments['from'], 'from') if arguments.get('from') else _fiscal_year_start(to)
    if frm < FLOOR:
        raise ValueError('USAspending searches start on 2007-10-01 at the earliest')
    if frm > to:
        raise ValueError('from is after to')
    return frm, to


def _filters(arguments: Dict[str, Any], default_types: Optional[str] = None) -> Dict[str, Any]:
    frm, to = _period(arguments)
    f: Dict[str, Any] = {'time_period': [{'start_date': frm.isoformat(), 'end_date': to.isoformat()}]}
    kw = arguments.get('keywords')
    if isinstance(kw, str):
        kw = [kw]
    kw = [str(k).strip() for k in (kw or []) if str(k).strip()]
    if kw:
        f['keywords'] = kw
    if arguments.get('agency'):
        f['agencies'] = [{'type': 'awarding', 'tier': 'toptier', 'name': str(arguments['agency']).strip()}]
    if arguments.get('recipient'):
        f['recipient_search_text'] = [str(arguments['recipient']).strip()]
    types = arguments.get('award_types') or ([default_types] if default_types else [])
    if isinstance(types, str):
        types = [types]
    codes: List[str] = []
    for t in types:
        if t not in AWARD_TYPES:
            raise ValueError(f'award_types must be from {", ".join(AWARD_TYPES)}, not {t!r}')
        codes += AWARD_TYPES[t]
    if codes:
        f['award_type_codes'] = codes
    return f


def _check_group(types: List[str]) -> None:
    groups = {('contracts' if t in ('contracts',) else 'idvs' if t == 'idvs' else
               'loans' if t == 'loans' else 'assistance') for t in types}
    if len(groups) > 1:
        raise ValueError('USAspending lists one award group at a time: contracts, idvs, loans, or assistance '
                         '(grants, direct_payments, other); call once per group')


AWARD_FIELDS = ['Award ID', 'Recipient Name', 'recipient_id', 'Award Amount', 'Description', 'Awarding Agency',
                'Awarding Sub Agency', 'Start Date', 'End Date', 'generated_internal_id']
LOAN_FIELDS = ['Award ID', 'Recipient Name', 'recipient_id', 'Loan Value', 'Subsidy Cost', 'Description',
               'Awarding Agency', 'Awarding Sub Agency', 'Issued Date', 'generated_internal_id']


class UsaspendingAwardsTool(OpenDataTool):
    """usaspending_awards: the largest federal awards matching keywords, agency and recipient."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        types = arguments.get('award_types') or ['contracts']
        if isinstance(types, str):
            types = [types]
        _check_group(types)
        filters = _filters(dict(arguments, award_types=types))
        loans = types == ['loans']
        limit = int(arguments.get('limit') or 25)
        sort_by = arguments.get('sort') or 'amount'
        sort_field = {'amount': 'Loan Value' if loans else 'Award Amount',
                      'start_date': 'Issued Date' if loans else 'Start Date'}.get(sort_by, 'Award Amount')
        body = post_json('USAspending', f'{USA}/search/spending_by_award/', {
            'filters': filters, 'fields': LOAN_FIELDS if loans else AWARD_FIELDS, 'limit': limit, 'page': 1,
            'sort': sort_field, 'order': 'desc'})
        awards = []
        for r in body.get('results') or []:
            gid = r.get('generated_internal_id')
            awards.append({
                'award_id': r.get('Award ID'), 'recipient': r.get('Recipient Name'),
                'recipient_id': r.get('recipient_id'),
                'amount': r.get('Loan Value') if loans else r.get('Award Amount'),
                'description': r.get('Description'), 'awarding_agency': r.get('Awarding Agency'),
                'awarding_sub_agency': r.get('Awarding Sub Agency'),
                'start_date': r.get('Issued Date') if loans else r.get('Start Date'),
                'end_date': None if loans else r.get('End Date'),
                'url': f'https://www.usaspending.gov/award/{gid}' if gid else None})
        meta = body.get('page_metadata') or {}
        return {'award_types': types, 'from': filters['time_period'][0]['start_date'],
                'to': filters['time_period'][0]['end_date'],
                'units': 'US dollars (loans: face value); awards whose action dates fall in the period',
                'count': len(awards), 'truncated': bool(meta.get('hasNext')), 'awards': awards,
                'source': USA_SOURCE}


class UsaspendingByCategoryTool(OpenDataTool):
    """usaspending_by_category: federal obligations totalled by agency, recipient, industry, place and more."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        category = arguments.get('category') or 'awarding_agency'
        if category not in CATEGORIES:
            raise ValueError(f'category must be one of {", ".join(CATEGORIES)}')
        filters = _filters(arguments)
        limit = int(arguments.get('limit') or 10)
        body = post_json('USAspending', f'{USA}/search/spending_by_category/{category}/',
                         {'filters': filters, 'limit': limit, 'page': 1})
        rows = [{'name': r.get('name'), 'code': r.get('code'), 'id': r.get('id'), 'amount': r.get('amount')}
                for r in body.get('results') or []]
        meta = body.get('page_metadata') or {}
        return {'category': category, 'from': filters['time_period'][0]['start_date'],
                'to': filters['time_period'][0]['end_date'], 'units': 'US dollars obligated in the period',
                'count': len(rows), 'truncated': bool(meta.get('hasNext')), 'results': rows, 'source': USA_SOURCE}


class UsaspendingOverTimeTool(OpenDataTool):
    """usaspending_over_time: federal obligations by fiscal year, quarter or month, split by award group."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        group = arguments.get('group') or 'fiscal_year'
        if group not in ('fiscal_year', 'quarter', 'month'):
            raise ValueError('group must be fiscal_year, quarter or month')
        filters = _filters(arguments)
        body = post_json('USAspending', f'{USA}/search/spending_over_time/', {'group': group, 'filters': filters})
        points = []
        for r in body.get('results') or []:
            tp = r.get('time_period') or {}
            label = str(tp.get('fiscal_year') or '')
            if group == 'quarter' and tp.get('quarter'):
                label += f'-Q{tp["quarter"]}'
            elif group == 'month' and tp.get('month'):
                label += f'-M{int(tp["month"]):02d}'
            points.append({'period': label, 'total': r.get('aggregated_amount'),
                           'contracts': r.get('Contract_Obligations'), 'idvs': r.get('Idv_Obligations'),
                           'grants': r.get('Grant_Obligations'), 'direct_payments': r.get('Direct_Obligations'),
                           'loans': r.get('Loan_Obligations'), 'other': r.get('Other_Obligations')})
        return {'group': group, 'from': filters['time_period'][0]['start_date'],
                'to': filters['time_period'][0]['end_date'],
                'units': 'US dollars obligated; periods are US federal fiscal years (October to September); '
                         'a month is the fiscal month (M01 is October)',
                'count': len(points), 'points': points, 'source': USA_SOURCE}


_RECIPIENT_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-[PCR]$', re.I)


class UsaspendingRecipientTool(OpenDataTool):
    """usaspending_recipient: find a federal award recipient by name, or read one recipient's profile."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        rid = str(arguments.get('id') or '').strip()
        name = str(arguments.get('name') or '').strip()
        if rid:
            if not _RECIPIENT_ID.match(rid):
                raise ValueError('id is a USAspending recipient id: a UUID with a -P, -C or -R suffix')
            year = str(arguments.get('year') or 'latest')
            if not re.fullmatch(r'latest|all|\d{4}', year):
                raise ValueError('year must be latest, all or a fiscal year such as 2025')
            p = get_json('USAspending', f'{USA}/recipient/{rid}/', params={'year': year})
            loc = p.get('location') or {}
            profile = {
                'id': p.get('recipient_id'), 'name': p.get('name'), 'uei': p.get('uei'), 'duns': p.get('duns'),
                'level': {'P': 'parent', 'C': 'child', 'R': 'recipient'}.get(p.get('recipient_level'), p.get('recipient_level')),
                'parent_id': p.get('parent_id'), 'parent_name': p.get('parent_name'),
                'alternate_names': p.get('alternate_names') or [], 'business_types': p.get('business_types') or [],
                'city': loc.get('city_name'), 'state': loc.get('state_code'), 'country': loc.get('country_name'),
                'total_amount': p.get('total_transaction_amount'), 'total_transactions': p.get('total_transactions'),
                'url': f'https://www.usaspending.gov/recipient/{rid}/latest'}
            return {'year': year, 'units': 'US dollars, transactions in the fiscal year (latest: the last 12 months)',
                    'recipient': profile, 'source': USA_SOURCE}
        if not name:
            raise ValueError('give a recipient name to search, or an id')
        limit = int(arguments.get('limit') or 10)
        body = post_json('USAspending', f'{USA}/recipient/', {'keyword': name, 'limit': limit, 'page': 1,
                                                              'award_type': 'all', 'order': 'desc', 'sort': 'amount'})
        matches = [{'id': r.get('id'), 'name': r.get('name'), 'uei': r.get('uei'), 'duns': r.get('duns'),
                    'level': {'P': 'parent', 'C': 'child', 'R': 'recipient'}.get(r.get('recipient_level'), r.get('recipient_level')),
                    'amount': r.get('amount')} for r in body.get('results') or []]
        meta = body.get('page_metadata') or {}
        total = int(meta.get('total') or len(matches))
        return {'name': name, 'units': 'US dollars, awards in the last 12 months', 'count': len(matches),
                'total': total, 'truncated': total > len(matches), 'matches': matches, 'source': USA_SOURCE}


# ── data.gov catalogue ─────────────────────────────────────────────────────

def _dg_summary(d: Dict[str, Any]) -> Dict[str, Any]:
    dcat = d.get('dcat') or {}
    org = d.get('organization') or {}
    desc = d.get('description') or dcat.get('description') or ''
    return {
        'id': d.get('slug'), 'title': d.get('title') or dcat.get('title'),
        'organization': org.get('name'), 'organization_slug': org.get('slug'),
        'publisher': d.get('publisher') or (dcat.get('publisher') or {}).get('name'),
        'description': desc[:500] + ('...' if len(desc) > 500 else ''),
        'modified': dcat.get('modified'), 'access_level': d.get('access_level') or dcat.get('accessLevel'),
        'keywords': (d.get('keyword') or [])[:15], 'has_download': bool(d.get('has_download')),
        'landing_page': dcat.get('landingPage'),
        'url': f'https://catalog.data.gov/dataset/{d["slug"]}' if d.get('slug') else None,
    }


class DatagovSearchTool(OpenDataTool):
    """datagov_search: datasets in the data.gov catalogue, by text, organization and keyword."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        q = str(arguments.get('query') or '').strip()
        if not q and not arguments.get('organization') and not arguments.get('keyword'):
            raise ValueError('give a query, an organization or a keyword')
        limit = int(arguments.get('limit') or 10)
        body = get_json('data.gov catalog', f'{DATAGOV}/search', params={
            'q': q or None, 'org_slug': arguments.get('organization'), 'keyword': arguments.get('keyword'),
            'per_page': limit, 'after': arguments.get('after')})
        if not isinstance(body, dict) or 'results' not in body:
            raise ValueError('the data.gov catalog answered in an unexpected shape (its API may have changed)')
        rows = [_dg_summary(d) for d in body.get('results') or []]
        return {'query': q or None, 'count': len(rows), 'after': body.get('after'),
                'truncated': bool(body.get('after')), 'datasets': rows, 'source': DATAGOV_SOURCE}


class DatagovDatasetTool(OpenDataTool):
    """datagov_dataset: one data.gov dataset with its distributions (files and APIs) and licence."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ident = str(arguments.get('id') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_\-]{0,199}', ident):
            raise ValueError('id is a data.gov dataset slug (from datagov_search) or UUID')
        body = get_json('data.gov catalog', f'{DATAGOV}/api/dataset/{ident}')
        results = body.get('results') if isinstance(body, dict) else None
        if not results:
            raise ValueError(f'no data.gov dataset {ident!r}')
        d = results[0]
        dcat = d.get('dcat') or {}
        out = _dg_summary(d)
        desc = d.get('description') or dcat.get('description')
        out.update({
            'description': desc,
            'identifier': dcat.get('identifier') or d.get('identifier'),
            'license': dcat.get('license'), 'rights': dcat.get('rights') or dcat.get('accessRights'),
            'update_frequency': dcat.get('accrualPeriodicity'), 'temporal': dcat.get('temporal'),
            'spatial': dcat.get('spatial') if isinstance(dcat.get('spatial'), str) else None,
            'contact': (dcat.get('contactPoint') or {}).get('fn'),
            'contact_email': str((dcat.get('contactPoint') or {}).get('hasEmail') or '').replace('mailto:', '') or None,
            'described_by': dcat.get('describedBy'),
            'distributions': [{
                'title': x.get('title'), 'format': x.get('format') or x.get('mediaType'),
                'download_url': x.get('downloadURL'), 'access_url': x.get('accessURL'),
                'description': (x.get('description') or '')[:300] or None,
            } for x in dcat.get('distribution') or [] if isinstance(x, dict)],
        })
        return {'dataset': out, 'source': DATAGOV_SOURCE}
