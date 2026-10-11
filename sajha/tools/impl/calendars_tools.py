"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Holiday and business-day calendars (tool folder ``calendars``; Open Data Tools §4, L26).

Offline: every answer comes from the rules of the MIT-licensed ``holidays`` package
(github.com/vacanza/holidays), an optional dependency the configs declare in ``requires``.
A calendar code is a country (ISO 3166 alpha-2 or alpha-3, e.g. ``US``), a country with a
subdivision (``CA-ON``), or a market (ISO 10383 MIC such as ``XNYS``, or one of the package's
aliases such as ``NYSE``). A day is a business day when it is not a weekend day of the
calendar and not one of its holidays; with several calendars, only when it is one in all.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool

SOURCE = 'holidays Python package (vacanza/holidays, MIT licence); rules-based, computed offline'
MAX_DAYS = 10000                 # business days to add or subtract
MAX_SPAN_YEARS = 50              # a holiday list or a business-day count spans at most this
WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
SETTLEMENT = {'T+0': 0, 'T+1': 1, 'T+2': 2, 'T+3': 3}


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be a date as YYYY-MM-DD, not {value!r}')


def _markets() -> Dict[str, Any]:
    import holidays
    return {code.upper(): code for code in holidays.list_supported_financial()}


class Calendar:
    """One resolved calendar: its code, kind (country or market) and the holidays object."""

    def __init__(self, code: str):
        import holidays
        raw = str(code or '').strip()
        if not raw:
            raise ValueError('a calendar code is empty')
        upper = raw.upper()
        markets = _markets()
        if upper in markets:
            self.kind = 'market'
            self.code = upper
            self.holidays = holidays.financial_holidays(markets[upper])
        else:
            country, _, subdiv = upper.partition('-')
            country = self._country(country)
            supported = holidays.list_supported_countries()
            if country not in supported:
                raise ValueError(
                    f'unknown calendar {raw!r}: use an ISO 3166 country code (US, CA, GB), a country '
                    f'with a subdivision (CA-ON) or an ISO 10383 market code (XNYS, XLON, XECB)')
            subdivision = None
            if subdiv:
                subdivision = next((s for s in supported[country] if str(s).upper() == subdiv), None)
                if subdivision is None:
                    raise ValueError(f'{country} has no subdivision {subdiv!r}; it has '
                                     f'{", ".join(map(str, supported[country])) or "none"}')
            self.kind = 'country'
            self.code = f'{country}-{subdivision}' if subdivision else country
            self.holidays = holidays.country_holidays(country, subdiv=subdivision)
        self.weekend = set(getattr(self.holidays, 'weekend', None) or {5, 6})

    @staticmethod
    def _country(code: str) -> str:
        if len(code) == 3:
            from sajha.tools.impl.country_codes import COUNTRIES
            if code in COUNTRIES and COUNTRIES[code][0]:
                return COUNTRIES[code][0]
        return code

    def closed_reason(self, d: date) -> Optional[str]:
        """Why ``d`` is not a business day here (a holiday's name, or 'weekend'); None when it is one."""
        name = self.holidays.get(d)
        if name:
            return name
        if d.weekday() in self.weekend:
            return 'weekend'
        return None


def resolve(codes: Any) -> List[Calendar]:
    if isinstance(codes, str):
        codes = [codes]
    if not codes:
        raise ValueError('name at least one calendar (a country such as US or a market such as XNYS)')
    out, seen = [], set()
    for code in codes:
        cal = Calendar(code)
        if cal.code not in seen:
            seen.add(cal.code)
            out.append(cal)
    return out


def is_business_day(d: date, cals: List[Calendar]) -> bool:
    return all(c.closed_reason(d) is None for c in cals)


def step(d: date, n: int, cals: List[Calendar]) -> date:
    """Move ``n`` business days from ``d`` (backwards when negative)."""
    if abs(n) > MAX_DAYS:
        raise ValueError(f'days must be between -{MAX_DAYS} and {MAX_DAYS}')
    sign = 1 if n >= 0 else -1
    remaining = abs(n)
    cur = d
    while remaining:
        cur += timedelta(days=sign)
        if is_business_day(cur, cals):
            remaining -= 1
    return cur


def roll(d: date, cals: List[Calendar], forward: bool = True) -> date:
    delta = timedelta(days=1 if forward else -1)
    cur = d
    for _ in range(366):
        if is_business_day(cur, cals):
            return cur
        cur += delta
    raise ValueError(f'no business day within a year of {d.isoformat()} in these calendars')


def _codes(cals: List[Calendar]) -> List[str]:
    return [c.code for c in cals]


class CalendarsBaseTool(BaseMCPTool):
    """Shared plumbing: schemas come from the JSON config."""

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})


class CalHolidaysTool(CalendarsBaseTool):
    """cal_holidays: the holidays of one country (optionally a subdivision) or market."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country, market = arguments.get('country'), arguments.get('market')
        if bool(country) == bool(market):
            raise ValueError('give exactly one of country (e.g. US) or market (e.g. XNYS)')
        subdivision = arguments.get('subdivision')
        if market and subdivision:
            raise ValueError('subdivision applies to a country, not a market')
        if market and str(market).strip().upper() not in _markets():
            raise ValueError(f'unknown market {market!r}: use an ISO 10383 code such as XNYS, XLON or XECB')
        cal = Calendar(market if market else (f'{country}-{subdivision}' if subdivision else country))
        if country and cal.kind != 'country':
            raise ValueError(f'{country!r} is a market code; pass it as market')
        start, end = self._range(arguments)
        rows = []
        for year in range(start.year, end.year + 1):
            for d, name in self._year(cal, year):
                if start <= d <= end:
                    rows.append({'date': d.isoformat(), 'name': name, 'weekday': WEEKDAYS[d.weekday()]})
        return {'calendar': cal.code, 'kind': cal.kind, 'from': start.isoformat(), 'to': end.isoformat(),
                'count': len(rows), 'holidays': rows, 'source': SOURCE}

    @staticmethod
    def _year(cal: Calendar, year: int) -> List[Tuple[date, str]]:
        date(year, 1, 1) in cal.holidays            # a lookup makes the package compute that year
        return sorted((d, n) for d, n in cal.holidays.items() if d.year == year)

    @staticmethod
    def _range(arguments: Dict[str, Any]) -> Tuple[date, date]:
        year = arguments.get('year')
        frm, to = arguments.get('from'), arguments.get('to')
        if year is not None and (frm or to):
            raise ValueError('give year, or from/to dates, not both')
        if frm or to:
            start = _parse_date(frm, 'from') if frm else date(_parse_date(to, 'to').year, 1, 1)
            end = _parse_date(to, 'to') if to else date(start.year, 12, 31)
        else:
            y = int(year) if year is not None else date.today().year
            start, end = date(y, 1, 1), date(y, 12, 31)
        if end < start:
            raise ValueError('to is before from')
        if end.year - start.year >= MAX_SPAN_YEARS:
            raise ValueError(f'a range spans at most {MAX_SPAN_YEARS} years')
        return start, end


class CalIsBusinessDayTool(CalendarsBaseTool):
    """cal_is_business_day: whether a date is a business day in every named calendar."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        d = _parse_date(arguments.get('date'), 'date')
        cals = resolve(arguments.get('calendars'))
        detail = []
        for c in cals:
            reason = c.closed_reason(d)
            detail.append({'calendar': c.code, 'is_business_day': reason is None, 'reason': reason})
        return {'date': d.isoformat(), 'weekday': WEEKDAYS[d.weekday()],
                'is_business_day': all(x['is_business_day'] for x in detail), 'calendars': detail,
                'previous_business_day': step(d, -1, cals).isoformat(),
                'next_business_day': step(d, 1, cals).isoformat(), 'source': SOURCE}


class CalBusinessDaysBetweenTool(CalendarsBaseTool):
    """cal_business_days_between: business days from ``from`` (counted) to ``to`` (not counted)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        start = _parse_date(arguments.get('from'), 'from')
        end = _parse_date(arguments.get('to'), 'to')
        cals = resolve(arguments.get('calendars'))
        lo, hi = (start, end) if start <= end else (end, start)
        if (hi - lo).days > MAX_SPAN_YEARS * 366:
            raise ValueError(f'a range spans at most {MAX_SPAN_YEARS} years')
        count, closed = 0, []
        d = lo
        while d < hi:
            if is_business_day(d, cals):
                count += 1
            elif not all(d.weekday() in c.weekend for c in cals):
                # a holiday that removed a working day (holidays on a weekend change nothing)
                reasons = sorted({r for r in (c.closed_reason(d) for c in cals) if r and r != 'weekend'})
                if reasons:
                    closed.append({'date': d.isoformat(), 'reason': '; '.join(reasons)})
            d += timedelta(days=1)
        return {'from': start.isoformat(), 'to': end.isoformat(), 'calendars': _codes(cals),
                'business_days': count if start <= end else -count, 'calendar_days': (end - start).days,
                'holidays_on_weekdays': closed, 'source': SOURCE}


class CalAddBusinessDaysTool(CalendarsBaseTool):
    """cal_add_business_days: the date ``days`` business days after (or before) ``date``."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        d = _parse_date(arguments.get('date'), 'date')
        days = int(arguments.get('days'))
        cals = resolve(arguments.get('calendars'))
        result = step(d, days, cals) if days else roll(d, cals, True)
        return {'date': d.isoformat(), 'days': days, 'calendars': _codes(cals), 'result': result.isoformat(),
                'weekday': WEEKDAYS[result.weekday()], 'source': SOURCE}


class CalSettlementDateTool(CalendarsBaseTool):
    """cal_settlement_date: trade date plus the convention's business days."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        trade = _parse_date(arguments.get('trade_date'), 'trade_date')
        convention = str(arguments.get('convention') or 'T+1').upper().replace(' ', '')
        if convention not in SETTLEMENT:
            raise ValueError('convention must be T+0, T+1, T+2 or T+3')
        cals = resolve(arguments.get('calendars'))
        n = SETTLEMENT[convention]
        settle = step(trade, n, cals) if n else roll(trade, cals, True)
        out = {'trade_date': trade.isoformat(), 'convention': convention, 'calendars': _codes(cals),
               'settlement_date': settle.isoformat(), 'weekday': WEEKDAYS[settle.weekday()],
               'trade_date_is_business_day': is_business_day(trade, cals), 'source': SOURCE}
        return out


class CalAdjustDateTool(CalendarsBaseTool):
    """cal_adjust_date: roll a date to a business day by a business-day convention."""

    RULES = ('following', 'modified_following', 'preceding')

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        d = _parse_date(arguments.get('date'), 'date')
        rule = str(arguments.get('rule') or 'modified_following')
        if rule not in self.RULES:
            raise ValueError(f'rule must be one of {", ".join(self.RULES)}')
        cals = resolve(arguments.get('calendars'))
        if rule == 'preceding':
            adjusted = roll(d, cals, False)
        else:
            adjusted = roll(d, cals, True)
            if rule == 'modified_following' and adjusted.month != d.month:
                adjusted = roll(d, cals, False)
        return {'date': d.isoformat(), 'rule': rule, 'calendars': _codes(cals), 'adjusted': adjusted.isoformat(),
                'weekday': WEEKDAYS[adjusted.weekday()], 'changed': adjusted != d, 'source': SOURCE}
