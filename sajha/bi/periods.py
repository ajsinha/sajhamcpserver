"""
SAJHA MCP Server — Business Intelligence: human periods as date ranges.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A period is a half-open range of dates ``[start, end)``. Forms (Business Intelligence §3.2):

    2025-Q3, 2025-07, 2025, 2025-07-15      calendar quarter, month, year, day
    FY2025                                  the fiscal year that ends in 2025 (the metric's
                                            fiscal_year_start; with 1 it is the calendar year)
    YTD, QTD, MTD                           from the start of the (fiscal) year, quarter or month
                                            to today, inclusive
    last 12 months, last 8 quarters,        the N whole units before the current one; days and
    last 2 years, last 30 days, last 4 weeks  weeks end today, inclusive
    {"from": "2025-01-01", "to": "2025-03-31"}  inclusive dates

``previous`` is the period of the same length just before (a quarter's previous quarter; YTD's
previous is the same span one year earlier; a date range shifts by its own length in days);
``last_year`` shifts by twelve months. Relative forms are relative to ``today`` (the server's date).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

GRAINS = ('day', 'week', 'month', 'quarter', 'year')
_UNIT_MONTHS = {'month': 1, 'quarter': 3, 'year': 12}


class PeriodError(ValueError):
    """A period the caller wrote could not be read."""


@dataclass(frozen=True)
class Period:
    start: date
    end: date                      # exclusive
    label: str
    unit: str = ''                 # month | quarter | year (shift by whole units), else by days
    units: int = 1

    @property
    def to(self) -> date:
        """The last day, inclusive."""
        return self.end - timedelta(days=1)

    def as_dict(self) -> dict:
        return {'label': self.label, 'from': self.start.isoformat(), 'to': self.to.isoformat()}

    def shifted_months(self, months: int, label: str) -> 'Period':
        return Period(add_months(self.start, months), add_months(self.end, months), label, self.unit, self.units)

    def previous(self) -> 'Period':
        if self.unit in _UNIT_MONTHS:
            p = self.shifted_months(-_UNIT_MONTHS[self.unit] * self.units, '')
            return Period(p.start, p.end, f'{p.start.isoformat()} to {p.to.isoformat()}', self.unit, self.units)
        days = (self.end - self.start).days
        s, e = self.start - timedelta(days=days), self.start
        return Period(s, e, f'{s.isoformat()} to {(e - timedelta(days=1)).isoformat()}')

    def last_year(self) -> 'Period':
        p = self.shifted_months(-12, '')
        return Period(p.start, p.end, f'{p.start.isoformat()} to {p.to.isoformat()}', self.unit, self.units)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + months, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _unit_start(d: date, unit: str, fiscal_start: int = 1) -> date:
    if unit == 'month':
        return date(d.year, d.month, 1)
    offset = (fiscal_start - 1) if unit in ('year', 'quarter') else 0
    shifted = add_months(date(d.year, d.month, 1), -offset)
    if unit == 'quarter':
        shifted = date(shifted.year, 3 * ((shifted.month - 1) // 3) + 1, 1)
    else:
        shifted = date(shifted.year, 1, 1)
    return add_months(shifted, offset)


def _iso(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        raise PeriodError(f'{field} must be a date as YYYY-MM-DD, not {value!r}') from None


_LAST = re.compile(r'^last\s+(\d{1,4})\s+(day|week|month|quarter|year)s?$')


def parse(value: Any, fiscal_year_start: int = 1, today: Optional[date] = None) -> Period:
    """The period ``value`` names, or :class:`PeriodError`."""
    today = today or date.today()
    fs = int(fiscal_year_start or 1)
    if isinstance(value, dict):
        if 'from' not in value or 'to' not in value:
            raise PeriodError('a date range needs both from and to (YYYY-MM-DD, inclusive)')
        s, t = _iso(value['from'], 'from'), _iso(value['to'], 'to')
        if t < s:
            raise PeriodError('to is before from')
        return Period(s, t + timedelta(days=1), f'{s.isoformat()} to {t.isoformat()}')
    if not isinstance(value, str) or not value.strip():
        raise PeriodError('period is required: 2025-Q3, 2025-07, 2025, FY2025, YTD, QTD, MTD, '
                          'last 12 months or {"from": ..., "to": ...}')
    text = ' '.join(value.strip().split())
    low = text.lower()
    m = re.fullmatch(r'(\d{4})-?q([1-4])', low)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        s = date(y, 3 * (q - 1) + 1, 1)
        return Period(s, add_months(s, 3), f'{y}-Q{q}', 'quarter')
    m = re.fullmatch(r'(\d{4})-(\d{2})', low)
    if m and 1 <= int(m.group(2)) <= 12:
        s = date(int(m.group(1)), int(m.group(2)), 1)
        return Period(s, add_months(s, 1), s.strftime('%Y-%m'), 'month')
    m = re.fullmatch(r'(\d{4})', low)
    if m:
        s = date(int(m.group(1)), 1, 1)
        return Period(s, add_months(s, 12), m.group(1), 'year')
    m = re.fullmatch(r'fy\s*(\d{4})', low)
    if m:
        y = int(m.group(1))
        end = date(y, fs, 1) if fs != 1 else date(y + 1, 1, 1)
        return Period(add_months(end, -12), end, f'FY{y}', 'year')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', low):
        d = _iso(low, 'period')
        return Period(d, d + timedelta(days=1), d.isoformat())
    if low in ('ytd', 'qtd', 'mtd'):
        unit = {'ytd': 'year', 'qtd': 'quarter', 'mtd': 'month'}[low]
        s = _unit_start(today, unit, fs)
        return Period(s, today + timedelta(days=1), f'{low.upper()} to {today.isoformat()}', unit)
    m = _LAST.fullmatch(low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if n < 1:
            raise PeriodError('last N needs N of at least 1')
        if unit in ('day', 'week'):
            days = n * (7 if unit == 'week' else 1)
            s = today - timedelta(days=days - 1)
            return Period(s, today + timedelta(days=1), text)
        end = _unit_start(today, unit, fs if unit != 'month' else 1)
        months = _UNIT_MONTHS[unit] * n
        return Period(add_months(end, -months), end, text, unit, n)
    raise PeriodError(f'cannot read the period {value!r}: use 2025-Q3, 2025-07, 2025, FY2025, YTD, QTD, MTD, '
                      f'last 12 months, last 8 quarters or {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}}')


def against(period: Period, value: Any, fiscal_year_start: int = 1, today: Optional[date] = None) -> Period:
    """The comparison period: previous_period, same_period_last_year, or a period of its own."""
    if value in (None, '', 'previous_period'):
        return period.previous()
    if value == 'same_period_last_year':
        return period.last_year()
    return parse(value, fiscal_year_start, today)


def bucket_label(d: Any, grain: str) -> str:
    """The display label of a grain bucket that starts on ``d``."""
    if not isinstance(d, date):
        try:
            d = date.fromisoformat(str(d)[:10])
        except ValueError:
            return str(d)
    if grain == 'month':
        return d.strftime('%Y-%m')
    if grain == 'quarter':
        return f'{d.year}-Q{(d.month - 1) // 3 + 1}'
    if grain == 'year':
        return str(d.year)
    return d.isoformat()
