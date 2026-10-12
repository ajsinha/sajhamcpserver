"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

FDIC BankFind tools (tool folder ``fdic``; Open Data Tools §4, L31).

``api.fdic.gov/banks`` is keyless today (a US government work). Its documentation says a key may
become required; an operator who has one sets the environment variable ``FDIC_API_KEY`` and the
tools send it. Each tool's config sets ``cache_ttl`` (the shared result cache), and every request
first takes a slot in one sliding window kept in the state store, so all workers share FDIC's
published limit (``x-ratelimit-limit: 20``) behind the organisation's one egress IP. Every fetch
goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``).

Dollar amounts from BankFind are in thousands of US dollars.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sajha.core import outbound
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl.open_data_common import take_slot
from sajha.tools.impl.us_treasury_tools import parse_date, parse_period

BASE = 'https://api.fdic.gov/banks'
SOURCE = 'FDIC BankFind Suite (api.fdic.gov)'
HEADERS = {'User-Agent': 'SAJHA-MCP-Server (open data tools)', 'Accept': 'application/json'}
TIMEOUT = 30
KEY_ENV = 'FDIC_API_KEY'
THROTTLE_KEY = 'opendata:fdic:requests'
THROTTLE_LIMIT = 20            # requests ...
THROTTLE_WINDOW = 60.0         # ... per this many seconds, across every worker
THROTTLE_WAIT = 15.0           # how long a call waits for a free slot before it gives up
THOUSANDS = 'amounts in thousands of US dollars'


def _take_slot() -> None:
    """Wait (briefly) for a slot in the shared FDIC request window."""
    take_slot(THROTTLE_KEY, THROTTLE_LIMIT, THROTTLE_WINDOW, THROTTLE_WAIT, 'FDIC')


def fdic(endpoint: str, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """One BankFind query: (rows, total)."""
    params = {k: v for k, v in params.items() if v not in (None, '')}
    key = os.environ.get(KEY_ENV, '').strip()
    if key:
        params['api_key'] = key
    _take_slot()
    try:
        r = outbound.request('GET', f'{BASE}/{endpoint}', params=params, headers=HEADERS, timeout=TIMEOUT)
    except outbound.FetchTimeout:
        raise ValueError(f'FDIC BankFind did not answer within {TIMEOUT} seconds')
    except (outbound.Refused, outbound.FetchError) as e:
        raise ValueError(f'FDIC BankFind request failed: {e}')
    if r.status_code >= 400:
        detail = ''
        try:
            body = r.json()
            detail = body.get('message') or body.get('error') or ''
            if isinstance(detail, dict):
                detail = detail.get('message') or ''
        except Exception:
            pass
        if r.status_code in (401, 403):
            raise ValueError(f'FDIC BankFind refused the request (HTTP {r.status_code}); it may now need an '
                             f'API key: set {KEY_ENV}')
        raise ValueError(f'FDIC BankFind answered HTTP {r.status_code}{": " + str(detail) if detail else ""}')
    body = r.json()
    rows = [item.get('data') or {} for item in (body.get('data') or [])]
    total = (body.get('meta') or {}).get('total')
    if total is None:
        total = (body.get('totals') or {}).get('count', len(rows))
    return rows, int(total)


def us_date(value: Any) -> Optional[str]:
    """BankFind dates (``7/17/2026``, ``2026-09-22T00:00:00``, ``20260630``) as YYYY-MM-DD."""
    if value in (None, '', '0'):
        return None
    s = str(value).strip()
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if m:
        out = f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
        return None if out.startswith('9999') else out
    m = re.fullmatch(r'(\d{4})-?(\d{2})-?(\d{2})(T.*)?', s)
    if m:
        out = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        return None if out.startswith('9999') else out
    return s


def state_code(value: Any) -> str:
    s = str(value or '').strip().upper()
    if not re.fullmatch(r'[A-Z]{2}', s):
        raise ValueError(f'state must be a two-letter US state code such as NY, not {value!r}')
    return s


def _q(value: str) -> str:
    return '"' + str(value).replace('"', '') + '"'


def _pick(row: Dict[str, Any], mapping: Dict[str, str], dates=()) -> Dict[str, Any]:
    out = {}
    for friendly, code in mapping.items():
        v = row.get(code)
        out[friendly] = us_date(v) if friendly in dates else (None if v == '' else v)
    return out


class FdicBaseTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})


INSTITUTION = {'cert': 'CERT', 'name': 'NAME', 'city': 'CITY', 'state': 'STALP', 'active': 'ACTIVE',
               'total_assets': 'ASSET', 'total_deposits': 'DEP', 'net_income_ytd': 'NETINC',
               'report_date': 'REPDTE', 'bank_class': 'BKCLASS', 'regulator': 'REGAGNT',
               'holding_company': 'NAMEHCR', 'fed_rssd': 'FED_RSSD', 'website': 'WEBADDR',
               'established': 'ESTYMD', 'insured_since': 'INSDATE', 'offices': 'OFFICES'}


class FdicInstitutionsTool(FdicBaseTool):
    """fdic_institutions: FDIC-insured institutions by name, state, certificate number or status."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        filters, search = [], None
        if arguments.get('cert') is not None:
            filters.append(f'CERT:{int(arguments["cert"])}')
        if arguments.get('state'):
            filters.append(f'STALP:{state_code(arguments["state"])}')
        if arguments.get('active') is not None:
            filters.append(f'ACTIVE:{1 if arguments["active"] else 0}')
        name = str(arguments.get('name') or '').strip()
        if name:
            search = 'NAME:' + name.replace('"', '')
        limit = int(arguments.get('limit') or 25)
        rows, total = fdic('institutions', {
            'filters': ' AND '.join(filters), 'search': search, 'fields': ','.join(INSTITUTION.values()),
            'limit': limit, 'sort_by': None if search else 'ASSET', 'sort_order': None if search else 'DESC'})
        out = []
        for r in rows:
            item = _pick(r, INSTITUTION, dates=('report_date', 'established', 'insured_since'))
            item['active'] = bool(item.get('active'))
            item['cert'] = int(item['cert']) if item.get('cert') not in (None, '') else None
            out.append(item)
        return {'units': THOUSANDS + '; net_income_ytd is year to date at report_date',
                'count': len(out), 'total': total, 'truncated': total > len(out), 'institutions': out,
                'source': SOURCE}


# friendly Call Report names -> BankFind financial fields (any other BankFind code is accepted as is)
FINANCIAL_FIELDS = {
    'total_assets': ('ASSET', THOUSANDS), 'total_deposits': ('DEP', THOUSANDS),
    'domestic_deposits': ('DEPDOM', THOUSANDS), 'net_loans': ('LNLSNET', THOUSANDS),
    'equity': ('EQ', THOUSANDS), 'net_income': ('NETINC', THOUSANDS + ', year to date'),
    'net_interest_income': ('NIM', THOUSANDS + ', year to date'),
    'noncurrent_loans': ('NCLNLS', THOUSANDS), 'roa': ('ROA', 'percent, annualised'),
    'roe': ('ROE', 'percent, annualised'), 'net_interest_margin': ('NIMY', 'percent, annualised'),
    'efficiency_ratio': ('EEFFR', 'percent'), 'leverage_ratio': ('RBC1AAJ', 'percent'),
    'tier1_risk_based_ratio': ('RBCT1CER', 'percent'), 'total_risk_based_ratio': ('RBCRWAJ', 'percent'),
}
DEFAULT_FINANCIALS = ['total_assets', 'total_deposits', 'net_income', 'equity', 'roa', 'roe']


def _quarter_of(repdte: str) -> str:
    y, m = repdte[:4], int(repdte[4:6])
    return f'{y}-Q{(m - 1) // 3 + 1}'


class FdicFinancialsTool(FdicBaseTool):
    """fdic_financials: quarterly Call Report figures for one institution."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        cert = int(arguments['cert'])
        fields = arguments.get('fields') or DEFAULT_FINANCIALS
        codes, units = {}, {}
        for f in fields:
            name = str(f).strip()
            if name.lower() in FINANCIAL_FIELDS:
                code, unit = FINANCIAL_FIELDS[name.lower()]
                codes[name.lower()] = code
                units[name.lower()] = unit
            elif re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{1,30}', name):
                codes[name.upper()] = name.upper()
                units[name.upper()] = 'as BankFind reports it (dollar amounts in thousands)'
            else:
                raise ValueError(f'field {name!r} is neither a known name ({", ".join(FINANCIAL_FIELDS)}) '
                                 f'nor a BankFind field code')
        start, end = parse_period(arguments.get('period') or 'last 4 quarters')
        rng = f'REPDTE:[{start.strftime("%Y%m%d")} TO {end.strftime("%Y%m%d")}]'
        rows, total = fdic('financials', {
            'filters': f'CERT:{cert} AND {rng}', 'fields': ','.join(['CERT', 'REPDTE'] + list(dict.fromkeys(codes.values()))),
            'sort_by': 'REPDTE', 'sort_order': 'ASC', 'limit': 200})
        quarters = []
        for r in rows:
            rep = str(r.get('REPDTE') or '')
            q = {'report_date': us_date(rep), 'quarter': _quarter_of(rep) if len(rep) == 8 else None}
            for name, code in codes.items():
                q[name] = r.get(code)
            quarters.append(q)
        return {'cert': cert, 'from': start.isoformat(), 'to': end.isoformat(), 'units': units,
                'count': len(quarters), 'quarters': quarters, 'source': SOURCE}


FAILURE = {'cert': 'CERT', 'name': 'NAME', 'city': 'CITY', 'state': 'PSTALP', 'failure_date': 'FAILDATE',
           'resolution': 'RESTYPE', 'transaction_type': 'RESTYPE1', 'acquirer': 'BIDNAME',
           'total_assets': 'QBFASSET', 'total_deposits': 'QBFDEP', 'estimated_loss': 'COST', 'fund': 'SAVR'}


class FdicFailuresTool(FdicBaseTool):
    """fdic_failures: failed and assisted banks, newest first."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        filters = []
        frm, to = arguments.get('from'), arguments.get('to')
        if frm or to:
            a = parse_date(frm, 'from').isoformat() if frm else '1934-01-01'
            b = parse_date(to, 'to').isoformat() if to else date.today().isoformat()
            filters.append(f'FAILDATE:[{_q(a)} TO {_q(b)}]')
        if arguments.get('state'):
            filters.append(f'PSTALP:{state_code(arguments["state"])}')
        limit = int(arguments.get('limit') or 50)
        rows, total = fdic('failures', {'filters': ' AND '.join(filters), 'fields': ','.join(FAILURE.values()),
                                        'sort_by': 'FAILDATE', 'sort_order': 'DESC', 'limit': limit})
        out = [_pick(r, FAILURE, dates=('failure_date',)) for r in rows]
        return {'units': THOUSANDS + ' (estimated_loss: the latest estimate of the cost to the insurance fund)',
                'count': len(out), 'total': total, 'truncated': total > len(out), 'failures': out,
                'source': SOURCE}


LOCATION = {'office_number': 'OFFNUM', 'office_name': 'OFFNAME', 'main_office': 'MAINOFF',
            'service_type': 'SERVTYPE_DESC', 'address': 'ADDRESS', 'city': 'CITY', 'state': 'STALP', 'zip': 'ZIP',
            'county': 'COUNTY', 'established': 'ESTYMD', 'latitude': 'LATITUDE', 'longitude': 'LONGITUDE',
            'uninum': 'UNINUM'}


class FdicLocationsTool(FdicBaseTool):
    """fdic_locations: the offices (branches and main office) of one institution."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        cert = int(arguments['cert'])
        filters = [f'CERT:{cert}']
        if arguments.get('state'):
            filters.append(f'STALP:{state_code(arguments["state"])}')
        limit = int(arguments.get('limit') or 100)
        rows, total = fdic('locations', {'filters': ' AND '.join(filters),
                                         'fields': ','.join(['NAME'] + list(LOCATION.values())),
                                         'sort_by': 'OFFNUM', 'sort_order': 'ASC', 'limit': limit})
        out = []
        for r in rows:
            item = _pick(r, LOCATION, dates=('established',))
            item['main_office'] = bool(item.get('main_office'))
            out.append(item)
        return {'cert': cert, 'institution': rows[0].get('NAME') if rows else None, 'count': len(out),
                'total': total, 'truncated': total > len(out), 'offices': out, 'source': SOURCE}


HISTORY = {'effective_date': 'EFFDATE', 'processed_date': 'PROCDATE', 'change_code': 'CHANGECODE',
           'event': 'CHANGECODE_DESC', 'institution': 'INSTNAME', 'office_name': 'OFF_NAME',
           'institution_city': 'PCITY', 'institution_state': 'PSTALP', 'acquirer': 'ACQ_INSTNAME', 'acquirer_cert': 'ACQ_CERT',
           'outgoing_institution': 'OUT_INSTNAME', 'outgoing_cert': 'OUT_CERT', 'level': 'ORG_ROLE_CDE'}


class FdicHistoryTool(FdicBaseTool):
    """fdic_history: structure events of one institution (mergers, charter and name changes; branch openings
    and closings on request), newest first."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        cert = int(arguments['cert'])
        limit = int(arguments.get('limit') or 50)
        filters = [f'CERT:{cert}']
        if not arguments.get('include_branches'):
            filters.append('NOT ORG_ROLE_CDE:BR')         # institution-level events only
        rows, total = fdic('history', {'filters': ' AND '.join(filters), 'fields': ','.join(HISTORY.values()),
                                       'sort_by': 'EFFDATE', 'sort_order': 'DESC', 'limit': limit})
        out = []
        for r in rows:
            item = _pick(r, HISTORY, dates=('effective_date', 'processed_date'))
            item['level'] = 'branch' if item.get('level') == 'BR' else 'institution'
            out.append(item)
        return {'cert': cert, 'count': len(out), 'total': total, 'truncated': total > len(out), 'events': out,
                'source': SOURCE}


SOD = {'cert': 'CERT', 'institution': 'NAMEFULL', 'branch_name': 'NAMEBR', 'branch_number': 'BRNUM',
       'address': 'ADDRESBR', 'city': 'CITYBR', 'state': 'STALPBR', 'zip': 'ZIPBR', 'deposits': 'DEPSUMBR',
       'main_office': 'BKMO', 'year': 'YEAR', 'uninum': 'UNINUMBR'}


class FdicSummaryOfDepositsTool(FdicBaseTool):
    """fdic_summary_of_deposits: branch deposits as of 30 June of a year, for one institution or one state."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        cert, state = arguments.get('cert'), arguments.get('state')
        if cert is None and not state:
            raise ValueError('give cert (one institution) or state (every branch in a state), or both')
        year = int(arguments['year'])
        filters = [f'YEAR:{year}']
        if cert is not None:
            filters.append(f'CERT:{int(cert)}')
        if state:
            filters.append(f'STALPBR:{state_code(state)}')
        limit = int(arguments.get('limit') or 100)
        rows, total = fdic('sod', {'filters': ' AND '.join(filters), 'fields': ','.join(SOD.values()),
                                   'sort_by': 'DEPSUMBR', 'sort_order': 'DESC', 'limit': limit})
        out = []
        for r in rows:
            item = _pick(r, SOD)
            item['main_office'] = bool(item.get('main_office'))
            out.append(item)
        return {'year': year, 'as_of': f'{year}-06-30', 'units': THOUSANDS, 'count': len(out), 'total': total,
                'truncated': total > len(out),
                'total_deposits_listed': sum(int(x['deposits'] or 0) for x in out), 'branches': out,
                'source': SOURCE}
