"""
SAJHA MCP Server — cron expressions for workflow schedules (timezone-aware, no dependency).

Five fields: minute hour day-of-month month day-of-week. Each field takes ``*``, a number,
a range ``a-b``, a step ``*/n`` or ``a-b/n``, and comma lists; months and weekdays also
take names (``jan``, ``mon``). Day of week is 0-7 (0 and 7 are Sunday). When both
day-of-month and day-of-week are restricted, a day matching either fires (classic cron).
Shortcuts: ``@yearly @annually @monthly @weekly @daily @midnight @hourly``.

Times are evaluated in the schedule's IANA timezone (``zoneinfo``). A wall-clock time that
does not exist (the spring-forward gap) is skipped; one that happens twice (fall back)
fires once, at its first occurrence.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

_SHORTCUTS = {'@yearly': '0 0 1 1 *', '@annually': '0 0 1 1 *', '@monthly': '0 0 1 * *',
              '@weekly': '0 0 * * 0', '@daily': '0 0 * * *', '@midnight': '0 0 * * *', '@hourly': '0 * * * *'}
_MONTHS = {m: i + 1 for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}
_DAYS = {d: i for i, d in enumerate('sun mon tue wed thu fri sat'.split())}
_BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


class CronError(ValueError):
    """An expression that is not a valid five-field cron schedule."""


def _zone(name: Optional[str]):
    if not name or name.upper() == 'UTC':
        return timezone.utc
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise CronError(f'unknown timezone {name!r} (use an IANA name such as Europe/London)') from e


def _value(tok: str, idx: int) -> int:
    names = _MONTHS if idx == 3 else _DAYS if idx == 4 else {}
    t = tok.lower()
    if t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f'bad cron value {tok!r}')
    return int(t)


def _field(text: str, idx: int) -> Set[int]:
    lo, hi = _BOUNDS[idx]
    out: Set[int] = set()
    for part in text.split(','):
        step = 1
        if '/' in part:
            part, s = part.split('/', 1)
            if not s.isdigit() or int(s) < 1:
                raise CronError(f'bad cron step {s!r}')
            step = int(s)
        if part == '*':
            a, b = lo, hi
        elif '-' in part:
            a, b = (_value(x, idx) for x in part.split('-', 1))
        else:
            a = _value(part, idx)
            b = hi if step > 1 else a
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise CronError(f'cron field {text!r} is outside {lo}-{hi}')
        out.update(range(a, b + 1, step))
    if idx == 4 and 7 in out:
        out.discard(7)
        out.add(0)
    return out


class CronSchedule:
    """A parsed cron expression in one timezone."""

    def __init__(self, expr: str, tz: Optional[str] = None):
        self.expr = (expr or '').strip()
        text = _SHORTCUTS.get(self.expr.lower(), self.expr)
        parts = text.split()
        if len(parts) != 5:
            raise CronError(f'cron needs five fields (minute hour day month weekday), got {self.expr!r}')
        self.minutes, self.hours, self.days, self.months, self.weekdays = (
            _field(p, i) for i, p in enumerate(parts))
        self.dom_any = parts[2] == '*'
        self.dow_any = parts[4] == '*'
        self.tz_name = tz or 'UTC'
        self.tz = _zone(tz)

    def _day_ok(self, d: datetime) -> bool:
        dom = d.day in self.days
        dow = ((d.weekday() + 1) % 7) in self.weekdays
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow
        if self.dow_any:
            return dom
        return dom or dow

    def _exists(self, local: datetime) -> bool:
        """False for a wall-clock time skipped by a DST change."""
        aware = local.replace(tzinfo=self.tz)
        back = aware.astimezone(timezone.utc).astimezone(self.tz).replace(tzinfo=None)
        return back == local

    def next_after(self, after: datetime) -> datetime:
        """The first fire time strictly after ``after`` (aware), as an aware UTC datetime."""
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
        local = after.astimezone(self.tz).replace(tzinfo=None, second=0, microsecond=0) + timedelta(minutes=1)
        limit = local + timedelta(days=366 * 5)
        while local < limit:
            if local.month not in self.months:
                y, m = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
                local = datetime(y, m, 1)
                continue
            if not self._day_ok(local):
                local = datetime(local.year, local.month, local.day) + timedelta(days=1)
                continue
            if local.hour not in self.hours:
                local = local.replace(minute=0) + timedelta(hours=1)
                continue
            if local.minute not in self.minutes:
                local += timedelta(minutes=1)
                continue
            if not self._exists(local):
                local += timedelta(minutes=1)
                continue
            fire = local.replace(tzinfo=self.tz, fold=0).astimezone(timezone.utc)
            if fire <= after:          # the repeated hour after a fall-back: fired already
                local += timedelta(minutes=1)
                continue
            return fire
        raise CronError(f'cron {self.expr!r} never fires')

    def latest_due(self, since: datetime, now: datetime) -> Optional[datetime]:
        """The latest fire time in (since, now], or None. Missed slots coalesce into one."""
        t = self.next_after(since)
        if t > now:
            return None
        last = t
        for _ in range(100000):
            nxt = self.next_after(last)
            if nxt > now:
                break
            last = nxt
        return last

    def upcoming(self, n: int = 3, after: Optional[datetime] = None) -> List[datetime]:
        t = after or datetime.now(timezone.utc)
        out = []
        for _ in range(n):
            t = self.next_after(t)
            out.append(t)
        return out
