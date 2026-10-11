"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

US Treasury tools (tool folder ``us_treasury``; Open Data Tools §4, L29).

Two keyless sources, both US government works:

* Fiscal Data (``api.fiscaldata.treasury.gov``): debt to the penny, average interest rates,
  auctions, the Daily Treasury Statement and the Treasury reporting rates of exchange;
* the daily par yield curve feeds on ``home.treasury.gov`` (CSV, one file per year).

Every fetch goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``).
Fiscal Data answers every value as a string, with the literal ``"null"`` for no value; the tools
turn them into numbers and nulls.
"""

from __future__ import annotations

import calendar
import csv
import io
import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sajha.core import outbound
from sajha.tools.base_mcp_tool import BaseMCPTool

FISCAL_DATA = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service'
YIELD_CSV = ('https://home.treasury.gov/resource-center/data-chart-center/interest-rates/'
             'daily-treasury-rates.csv/{year}/all')
SOURCE_FISCAL = 'U.S. Department of the Treasury, Fiscal Data (fiscaldata.treasury.gov)'
SOURCE_CURVE = 'U.S. Department of the Treasury, Daily Treasury Rates (home.treasury.gov)'
HEADERS = {'User-Agent': 'SAJHA-MCP-Server (open data tools)', 'Accept': 'application/json, text/csv'}
TIMEOUT = 30
PAGE_MAX = 10000
MAX_CURVE_YEARS = 10


# ── periods: 2025, 2025-Q3, 2025-07, last 12 months ──────────────────────────

_LAST = re.compile(r'^last\s+(\d{1,3})\s+(day|week|month|quarter|year)s?$', re.I)


def parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be a date as YYYY-MM-DD, not {value!r}')


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def parse_period(period: Any, today: Optional[date] = None) -> Tuple[date, date]:
    """``2025`` · ``2025-Q3`` · ``2025-07`` · ``2025-07-01:2025-09-30`` · ``last N days|weeks|months|quarters|years``
    -> (first day, last day)."""
    text = str(period or '').strip()
    today = today or date.today()
    if re.fullmatch(r'\d{4}', text):
        return date(int(text), 1, 1), date(int(text), 12, 31)
    m = re.fullmatch(r'(\d{4})-?Q([1-4])', text, re.I)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        return date(y, 3 * q - 2, 1), _month_end(y, 3 * q)
    m = re.fullmatch(r'(\d{4})-(\d{2})', text)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1), _month_end(y, mo)
    if ':' in text:
        a, b = text.split(':', 1)
        start, end = parse_date(a, 'period start'), parse_date(b, 'period end')
        if end < start:
            raise ValueError('the period ends before it starts')
        return start, end
    m = _LAST.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit in ('day', 'week'):
            return today - timedelta(days=n * (7 if unit == 'week' else 1)), today
        months = n * {'month': 1, 'quarter': 3, 'year': 12}[unit]
        return _months_back(today, months), today
    raise ValueError(f'period {text!r} is not understood: use 2025, 2025-Q3, 2025-07, '
                     f'2025-01-01:2025-06-30 or "last 12 months"')


# ── values ───────────────────────────────────────────────────────────────────

def number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if not s or s.lower() in ('null', 'n/a', 'na', 'nan'):
        return None
    try:
        f = float(s.replace(',', ''))
    except ValueError:
        return None
    return int(f) if f.is_integer() and re.fullmatch(r'-?\d+', s) else f


def text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return None if s.strip().lower() == 'null' or not s.strip() else s


def get(url: str, params=None) -> outbound.Response:
    try:
        r = outbound.request('GET', url, params=params, headers=HEADERS, timeout=TIMEOUT)
    except outbound.FetchTimeout:
        raise ValueError(f'the US Treasury did not answer within {TIMEOUT} seconds')
    except (outbound.Refused, outbound.FetchError) as e:
        raise ValueError(f'US Treasury request failed: {e}')
    if r.status_code >= 400:
        detail = ''
        try:
            body = r.json()
            detail = body.get('message') or body.get('error') or ''
        except Exception:
            pass
        raise ValueError(f'US Treasury answered HTTP {r.status_code}{": " + detail if detail else ""}')
    return r


def fiscal(endpoint: str, *, filters: Iterable[str] = (), fields: Iterable[str] = (), sort: str = '-record_date',
           size: int = PAGE_MAX) -> Tuple[List[Dict[str, Any]], int]:
    """One Fiscal Data page: (rows, total-count)."""
    params = {'sort': sort, 'page[size]': str(max(1, min(size, PAGE_MAX))), 'page[number]': '1'}
    if filters:
        params['filter'] = ','.join(filters)
    if fields:
        params['fields'] = ','.join(fields)
    body = get(f'{FISCAL_DATA}/{endpoint}', params).json()
    meta = body.get('meta') or {}
    rows = body.get('data') or []
    return rows, int(meta.get('total-count') or len(rows))


def _range_filters(field: str, start: Optional[date], end: Optional[date]) -> List[str]:
    out = []
    if start:
        out.append(f'{field}:gte:{start.isoformat()}')
    if end:
        out.append(f'{field}:lte:{end.isoformat()}')
    return out


def _dates(arguments: Dict[str, Any]) -> Tuple[Optional[date], Optional[date]]:
    """``date`` alone, or ``from``/``to``; (None, None) means the latest."""
    one, frm, to = arguments.get('date'), arguments.get('from'), arguments.get('to')
    if one and (frm or to):
        raise ValueError('give date, or from/to, not both')
    if one:
        d = parse_date(one, 'date')
        return d, d
    start = parse_date(frm, 'from') if frm else None
    end = parse_date(to, 'to') if to else None
    if start and end and end < start:
        raise ValueError('to is before from')
    return start, end


class UsTreasuryBaseTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})


# ── the par yield curve ──────────────────────────────────────────────────────

CURVES = {'nominal': 'daily_treasury_yield_curve', 'real': 'daily_treasury_real_yield_curve',
          'bills': 'daily_treasury_bill_rates'}


def tenor_of(column: str) -> Optional[str]:
    """'1 Mo' -> 1M, '1.5 Month' -> 1.5M, '10 Yr' -> 10Y, '4 WEEKS ...' -> 4W."""
    m = re.match(r'^\s*([\d.]+)\s*(mo|month|yr|year|week)', column, re.I)
    if not m:
        return None
    unit = m.group(2).lower()
    return m.group(1) + ('M' if unit.startswith('mo') else 'W' if unit.startswith('week') else 'Y')


def parse_curve_csv(body: str, curve: str) -> List[Dict[str, Any]]:
    rows = list(csv.reader(io.StringIO(body)))
    if not rows or not rows[0] or rows[0][0].strip().lower() != 'date':
        return []
    header = rows[0]
    out = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        mm, dd, yy = row[0].strip().split('/')
        obs: Dict[str, Any] = {'date': f'{yy}-{mm.zfill(2)}-{dd.zfill(2)}', 'yields': {}}
        if curve == 'bills':
            obs['bank_discount'] = {}
        for col, val in zip(header[1:], row[1:]):
            tenor = tenor_of(col)
            if not tenor:
                continue
            v = number(val)
            if curve == 'bills' and 'DISCOUNT' in col.upper():
                obs['bank_discount'][tenor] = v
            else:
                obs['yields'][tenor] = v
        out.append(obs)
    out.sort(key=lambda o: o['date'])
    return out


class UstYieldCurveTool(UsTreasuryBaseTool):
    """ust_yield_curve: the daily Treasury par yield curve (nominal, real) or bill rates, in percent."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        curve = arguments.get('curve') or 'nominal'
        if curve not in CURVES:
            raise ValueError('curve must be nominal, real or bills')
        start, end = _dates(arguments)
        wanted = [str(t).strip().upper() for t in (arguments.get('tenors') or [])]
        today = date.today()
        if start is None and end is None:                   # the latest curve
            obs = self._year(curve, today.year) or self._year(curve, today.year - 1)
            obs = obs[-1:]
        else:
            first = start or date((end or today).year, 1, 1)
            last = end or today
            if last.year - first.year >= MAX_CURVE_YEARS:
                raise ValueError(f'a range spans at most {MAX_CURVE_YEARS} calendar years')
            obs = []
            for year in range(first.year, last.year + 1):
                obs.extend(self._year(curve, year))
            if arguments.get('date'):
                # the curve of that day, or of the last business day before it
                obs = [o for o in obs if o['date'] <= last.isoformat()][-1:]
                if not obs and first.month == 1:
                    obs = [o for o in self._year(curve, first.year - 1)][-1:]
            else:
                obs = [o for o in obs if first.isoformat() <= o['date'] <= last.isoformat()]
        if wanted:
            for o in obs:
                missing = [t for t in wanted if t not in o['yields']]
                if missing and o is obs[0]:
                    raise ValueError(f'{curve} curve has no tenor {", ".join(missing)}; it has '
                                     f'{", ".join(o["yields"])}')
                o['yields'] = {t: o['yields'].get(t) for t in wanted}
                if 'bank_discount' in o:
                    o['bank_discount'] = {t: o['bank_discount'].get(t) for t in wanted}
        tenors = list(obs[-1]['yields']) if obs else []
        return {'curve': curve, 'units': 'percent' + (' (yields: coupon equivalent; bank_discount: bank discount '
                                                      'rate)' if curve == 'bills' else ' (par yields)'),
                'tenors': tenors, 'count': len(obs), 'observations': obs, 'source': SOURCE_CURVE}

    @staticmethod
    def _year(curve: str, year: int) -> List[Dict[str, Any]]:
        r = get(YIELD_CSV.format(year=year), {'type': CURVES[curve], 'field_tdr_date_value': str(year),
                                               'page': '', '_format': 'csv'})
        return parse_curve_csv(r.text, curve)


# ── Fiscal Data tools ────────────────────────────────────────────────────────

class UstDebtToThePennyTool(UsTreasuryBaseTool):
    """ust_debt_to_the_penny: total public debt outstanding, daily."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        start, end = _dates({'from': arguments.get('from'), 'to': arguments.get('to')})
        filters = _range_filters('record_date', start, end)
        rows, total = fiscal('v2/accounting/od/debt_to_penny', filters=filters,
                             fields=('record_date', 'debt_held_public_amt', 'intragov_hold_amt',
                                     'tot_pub_debt_out_amt'),
                             size=PAGE_MAX if filters else 1)
        records = [{'date': r.get('record_date'),
                    'total_public_debt_outstanding': number(r.get('tot_pub_debt_out_amt')),
                    'debt_held_by_the_public': number(r.get('debt_held_public_amt')),
                    'intragovernmental_holdings': number(r.get('intragov_hold_amt'))} for r in rows]
        records.sort(key=lambda x: x['date'] or '')
        return {'units': 'US dollars', 'count': len(records), 'truncated': bool(filters) and total > len(records),
                'records': records, 'source': SOURCE_FISCAL}


class UstAverageInterestRatesTool(UsTreasuryBaseTool):
    """ust_average_interest_rates: average interest rates on Treasury securities, monthly, in percent."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        period = arguments.get('period')
        if period:
            start, end = parse_period(period)
            rows, total = fiscal('v2/accounting/od/avg_interest_rates',
                                 filters=_range_filters('record_date', start, end))
        else:                                               # the latest month
            latest, _ = fiscal('v2/accounting/od/avg_interest_rates', fields=('record_date',), size=1)
            if not latest:
                return {'units': 'percent', 'count': 0, 'records': [], 'source': SOURCE_FISCAL}
            rows, total = fiscal('v2/accounting/od/avg_interest_rates',
                                 filters=[f'record_date:eq:{latest[0]["record_date"]}'])
        want = str(arguments.get('security_type') or '').strip().lower()
        records = []
        for r in rows:
            kind, desc = r.get('security_type_desc') or '', r.get('security_desc') or ''
            if want and want not in kind.lower() and want not in desc.lower():
                continue
            records.append({'date': r.get('record_date'), 'security_type': kind, 'security': desc,
                            'average_interest_rate': number(r.get('avg_interest_rate_amt'))})
        records.sort(key=lambda x: (x['date'] or '', x['security_type'], x['security']))
        return {'units': 'percent', 'count': len(records), 'truncated': total > len(rows),
                'records': records, 'source': SOURCE_FISCAL}


AUCTION_FIELDS = ('cusip', 'security_type', 'security_term', 'original_security_term', 'reopening',
                  'inflation_index_security', 'floating_rate', 'announcemt_date', 'auction_date',
                  'issue_date', 'maturity_date', 'offering_amt', 'total_tendered', 'total_accepted',
                  'bid_to_cover_ratio', 'int_rate', 'high_yield', 'high_discnt_rate', 'high_investment_rate',
                  'high_discnt_margin', 'high_price', 'indirect_bidder_accepted', 'direct_bidder_accepted',
                  'primary_dealer_accepted')
AUCTION_TEXT = {'cusip', 'security_type', 'security_term', 'original_security_term', 'reopening',
                'inflation_index_security', 'floating_rate', 'announcemt_date', 'auction_date', 'issue_date',
                'maturity_date'}
AUCTION_RENAME = {'announcemt_date': 'announcement_date', 'offering_amt': 'offering_amount',
                  'int_rate': 'interest_rate', 'high_discnt_rate': 'high_discount_rate',
                  'high_discnt_margin': 'high_discount_margin', 'inflation_index_security': 'tips',
                  'floating_rate': 'frn'}


class UstAuctionsTool(UsTreasuryBaseTool):
    """ust_auctions: announced and completed Treasury auctions and their results."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        kind = arguments.get('security_type')
        filters = {'Bill': ['security_type:eq:Bill'],
                   'Note': ['security_type:eq:Note', 'inflation_index_security:eq:No', 'floating_rate:eq:No'],
                   'Bond': ['security_type:eq:Bond', 'inflation_index_security:eq:No'],
                   'TIPS': ['inflation_index_security:eq:Yes'],
                   'FRN': ['floating_rate:eq:Yes']}.get(kind)
        if filters is None:
            raise ValueError('security_type must be Bill, Note, Bond, TIPS or FRN')
        filters = list(filters)
        term = str(arguments.get('term') or '').strip()
        if term:
            # a reopening's security_term is the remaining term (9-Year 10-Month); its original term is
            # the one people name. Bills carry only security_term.
            filters.append(f'{"security_term" if kind == "Bill" else "original_security_term"}:eq:{term}')
        start, end = _dates({'from': arguments.get('from'), 'to': arguments.get('to')})
        filters += _range_filters('auction_date', start, end)
        limit = int(arguments.get('limit') or 20)
        rows, total = fiscal('v1/accounting/od/auctions_query', filters=filters, fields=AUCTION_FIELDS,
                             sort='-auction_date', size=limit)
        auctions = []
        for r in rows:
            a = {}
            for f in AUCTION_FIELDS:
                v = text(r.get(f)) if f in AUCTION_TEXT else number(r.get(f))
                a[AUCTION_RENAME.get(f, f)] = v
            a['tips'] = a.get('tips') == 'Yes'
            a['frn'] = a.get('frn') == 'Yes'
            a['reopening'] = a.get('reopening') == 'Yes'
            a['results_published'] = a.get('total_accepted') is not None
            auctions.append(a)
        return {'security_type': kind, 'units': 'rates and yields in percent; amounts in US dollars; '
                                                 'high_price per 100 of par',
                'count': len(auctions), 'total': total, 'truncated': total > len(auctions),
                'auctions': auctions, 'source': SOURCE_FISCAL}


DTS_TABLES = {
    'operating_cash_balance': 'Table I: Operating Cash Balance',
    'deposits_withdrawals_operating_cash': 'Table II: Deposits and Withdrawals of Operating Cash',
    'public_debt_transactions': 'Table IIIA: Public Debt Transactions',
    'adjustment_public_debt_transactions_cash_basis': 'Table IIIB: Adjustment of Public Debt Transactions to Cash Basis',
    'debt_subject_to_limit': 'Table IIIC: Debt Subject to Limit',
    'inter_agency_tax_transfers': 'Table IV: Inter-agency Tax Transfers',
    'income_tax_refunds_issued': 'Table V: Income Tax Refunds Issued',
}
DTS_DROP = {'table_nbr', 'table_nm', 'src_line_nbr', 'record_fiscal_year', 'record_fiscal_quarter',
            'record_calendar_year', 'record_calendar_quarter', 'record_calendar_month', 'record_calendar_day'}
DTS_AMOUNT = re.compile(r'(_amt|_bal)$')


class UstDailyTreasuryStatementTool(UsTreasuryBaseTool):
    """ust_daily_treasury_statement: one table of the Daily Treasury Statement, in millions of dollars."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        table = arguments.get('table')
        if table not in DTS_TABLES:
            raise ValueError(f'table must be one of {", ".join(DTS_TABLES)}')
        endpoint = f'v1/accounting/dts/{table}'
        start, end = _dates(arguments)
        if start is None and end is None:
            latest, _ = fiscal(endpoint, fields=('record_date',), size=1)
            if not latest:
                return {'table': table, 'title': DTS_TABLES[table], 'units': 'millions of US dollars',
                        'count': 0, 'truncated': False, 'rows': [], 'source': SOURCE_FISCAL}
            filters = [f'record_date:eq:{latest[0]["record_date"]}']
        else:
            filters = _range_filters('record_date', start, end)
        rows, total = fiscal(endpoint, filters=filters, sort='record_date,src_line_nbr')
        out = []
        for r in rows:
            row = {}
            for k, v in r.items():
                if k in DTS_DROP:
                    continue
                if k == 'record_date':
                    row['date'] = v
                else:
                    row[k] = number(v) if DTS_AMOUNT.search(k) else text(v)
            out.append(row)
        return {'table': table, 'title': DTS_TABLES[table], 'units': 'millions of US dollars',
                'count': len(out), 'truncated': total > len(out), 'rows': out, 'source': SOURCE_FISCAL}


# ISO 4217 codes of the currencies people ask for most, to Fiscal Data's country-currency names
CURRENCY_CODES = {
    'EUR': 'Euro Zone-Euro', 'JPY': 'Japan-Yen', 'GBP': 'United Kingdom-Pound', 'CAD': 'Canada-Dollar',
    'CNY': 'China-Renminbi', 'CHF': 'Switzerland-Franc', 'AUD': 'Australia-Dollar', 'INR': 'India-Rupee',
    'MXN': 'Mexico-Peso', 'BRL': 'Brazil-Real', 'KRW': 'Korea-Won', 'HKD': 'Hong Kong-Dollar',
    'SGD': 'Singapore-Dollar', 'SEK': 'Sweden-Krona', 'NOK': 'Norway-Krone', 'DKK': 'Denmark-Krone',
    'NZD': 'New Zealand-Dollar', 'ZAR': 'South Africa-Rand', 'TRY': 'Turkey-New Lira', 'RUB': 'Russia-Ruble',
}


# ISO 3166 codes whose Fiscal Data country name differs from the UN name in country_codes
FISCAL_COUNTRY = {
    'BA': 'Bosnia', 'BO': 'Bolivia', 'CD': 'Democratic Republic Of Congo', 'CG': 'Congo',
    'CI': "Cote D'Ivoire", 'CV': 'Cape Verde', 'CZ': 'Czech Republic', 'GB': 'United Kingdom',
    'HK': 'Hong Kong', 'IR': 'Iran', 'KR': 'Korea', 'LA': 'Laos', 'MD': 'Moldova',
    'MK': 'Republic Of North Macedonia', 'RU': 'Russia', 'SO': 'Somali', 'SY': 'Syria', 'SZ': 'Eswatini',
    'TL': 'Timor', 'TR': 'Turkey', 'TW': 'Taiwan', 'TZ': 'Tanzania', 'VE': 'Venezuela', 'VN': 'Vietnam',
    'WS': 'Western Samoa', 'EA': 'Euro Zone', 'EU': 'Euro Zone', 'EMU': 'Euro Zone',
}


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower())


def country_matcher(country: str):
    """A predicate on a Fiscal Data row for an ISO 3166 code or a country name."""
    c = country.strip()
    target = FISCAL_COUNTRY.get(c.upper())
    if target is None and len(c) in (2, 3) and c.isalpha():
        from sajha.tools.impl import country_codes
        a3 = country_codes.to_alpha3(c)
        a2 = country_codes.COUNTRIES[a3][0] if a3 else None
        target = FISCAL_COUNTRY.get(a2 or '') or country_codes.name(c)
    want = _norm(target or c)
    return lambda r: _norm(r.get('country') or '') == want


class UstExchangeRatesTool(UsTreasuryBaseTool):
    """ust_exchange_rates: Treasury reporting rates of exchange, foreign currency units per US dollar."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country, currency = arguments.get('country'), arguments.get('currency')
        if bool(country) == bool(currency):
            raise ValueError('give exactly one of country (e.g. CA or Canada) or currency (e.g. EUR or Euro)')
        period = arguments.get('period')
        if period:
            start, end = parse_period(period)
            filters = _range_filters('record_date', start, end)
        else:
            latest, _ = fiscal('v1/accounting/od/rates_of_exchange', fields=('record_date',), size=1)
            filters = [f'record_date:eq:{latest[0]["record_date"]}'] if latest else []
        code_desc = CURRENCY_CODES.get(str(currency or '').strip().upper())
        if code_desc:                                       # narrow on the server when the name is known
            filters = filters + [f'country_currency_desc:eq:{code_desc}']
        rows, total = fiscal('v1/accounting/od/rates_of_exchange', filters=filters,
                             fields=('record_date', 'country', 'currency', 'country_currency_desc',
                                     'exchange_rate', 'effective_date'))
        if country:
            keep = country_matcher(str(country))
        else:
            cur = str(currency).strip()
            desc = CURRENCY_CODES.get(cur.upper())
            keep = (lambda r: r.get('country_currency_desc') == desc) if desc else (
                lambda r: (r.get('currency') or '').lower() == cur.lower()
                or (r.get('country_currency_desc') or '').lower() == cur.lower())
        rates = [{'date': r.get('record_date'), 'effective_date': r.get('effective_date'),
                  'country': r.get('country'), 'currency': r.get('currency'),
                  'country_currency': r.get('country_currency_desc'),
                  'units_per_usd': number(r.get('exchange_rate'))} for r in rows if keep(r)]
        rates.sort(key=lambda x: (x['date'] or '', x['country_currency'] or ''))
        return {'units': 'foreign currency units per 1 US dollar (Treasury reporting rates, quarterly)',
                'count': len(rates), 'truncated': total > len(rows), 'rates': rates, 'source': SOURCE_FISCAL}
