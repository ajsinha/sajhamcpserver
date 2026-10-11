"""
SAJHA MCP Server — units of the quantitative workspace (Quantitative Planners §2.2).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A :class:`Unit` is a kind plus, where the kind has them, a code and a scale:

==========  =====================================  ====================================
kind        written                                converts to
==========  =====================================  ====================================
currency    ``USD``, ``USD mn``, ``EUR bn``        the same currency at another scale
count       ``count``, ``count k``                 count at another scale
percent     ``percent`` (``%``)                    ``pp``, ``bp``, ``ratio`` (1% = 100 bp = 0.01)
pp          ``pp`` (percentage points)             ``percent``, ``bp``, ``ratio``
bp          ``bp`` (basis points)                  ``percent``, ``pp``, ``ratio``
ratio       ``ratio``                              ``percent``, ``pp``, ``bp``
index       ``index`` (index points)               nothing
days/years  ``days``, ``years``                    each other, by a day-count basis
unitless    ``unitless``                           nothing
per         ``USD/EUR``, ``USD/count``             nothing (an FX rate is ``<quote>/<base>``)
==========  =====================================  ====================================

Scales are ``k``, ``mn``, ``bn``, ``tn`` (currency and count only). SAJHA never converts between
currencies (an FX rate must be a quantity, used with ``fx_convert``) nor between a level
(currency, count, index) and a rate (percent, pp, bp, ratio).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Union

from sajha.ai.quant.errors import UnitError

SCALES = {"": 1.0, "k": 1e3, "mn": 1e6, "bn": 1e9, "tn": 1e12}
_SCALE_WORDS = {"k": "k", "thousand": "k", "thousands": "k", "m": "mn", "mn": "mn", "mm": "mn", "million": "mn",
                "millions": "mn", "b": "bn", "bn": "bn", "billion": "bn", "billions": "bn", "t": "tn", "tn": "tn",
                "trillion": "tn", "trillions": "tn"}
RATE_KINDS = ("percent", "pp", "bp", "ratio")
RATE_FACTORS = {"ratio": 1.0, "percent": 0.01, "pp": 0.01, "bp": 1e-4}      # value in each, as a ratio
TIME_KINDS = ("days", "years")
LEVEL_KINDS = ("currency", "count", "index")
KINDS = ("currency", "count", "index", "days", "years", "unitless", "per") + RATE_KINDS
DAY_COUNTS = {"act/365": 365.0, "act/360": 360.0, "30/360": 360.0, "act/365.25": 365.25}
_ALIASES = {"%": "percent", "pct": "percent", "percent": "percent", "per cent": "percent", "percentage": "percent",
            "pp": "pp", "ppt": "pp", "percentage point": "pp", "percentage points": "pp",
            "bp": "bp", "bps": "bp", "basis point": "bp", "basis points": "bp",
            "ratio": "ratio", "fraction": "ratio", "decimal": "ratio", "x": "ratio",
            "count": "count", "number": "count", "units": "count", "shares": "count",
            "index": "index", "index points": "index", "points": "index", "pts": "index",
            "days": "days", "day": "days", "d": "days", "years": "years", "year": "years", "yr": "years",
            "yrs": "years", "y": "years", "unitless": "unitless", "none": "unitless", "": "unitless", "1": "unitless"}
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")
_NOT_CURRENCY = {"day", "yrs", "pct", "pts", "ppt", "bps", "one", "per"}


@dataclass(frozen=True)
class Unit:
    """A unit: ``kind`` (see the module table), ``code`` (an ISO 4217 currency, or ``num/den`` for
    ``per``) and ``scale`` (``""``, ``k``, ``mn``, ``bn``, ``tn``)."""
    kind: str
    code: str = ""
    scale: str = ""

    def __str__(self) -> str:
        if self.kind == "currency":
            return f"{self.code} {self.scale}".strip()
        if self.kind == "count":
            return f"count {self.scale}".strip()
        if self.kind == "per":
            return self.code
        return self.kind

    @property
    def factor(self) -> float:
        """The scale's multiplier (``USD mn`` is 1e6)."""
        return SCALES.get(self.scale, 1.0)

    @property
    def is_rate(self) -> bool:
        return self.kind in RATE_KINDS

    @property
    def is_level(self) -> bool:
        return self.kind in LEVEL_KINDS

    @property
    def is_time(self) -> bool:
        return self.kind in TIME_KINDS

    @property
    def family(self) -> str:
        """Units of one family convert to each other: ``currency:USD``, ``count``, ``rate``, ``time``,
        else the unit itself."""
        if self.kind == "currency":
            return f"currency:{self.code}"
        if self.is_rate:
            return "rate"
        if self.is_time:
            return "time"
        if self.kind == "per":
            return f"per:{self.code}"
        return self.kind

    def base(self) -> "Unit":
        """The same unit without a scale."""
        return Unit(self.kind, self.code, "")

    def with_scale(self, scale: str) -> "Unit":
        return Unit(self.kind, self.code, scale)

    def to_json(self) -> str:
        return str(self)


UnitLike = Union[Unit, str, None]


def parse_unit(u: UnitLike) -> Unit:
    """A :class:`Unit` from a Unit or a string (``"USD mn"``, ``"%"``, ``"bp"``, ``"USD/EUR"``, ``"years"``)."""
    if isinstance(u, Unit):
        return u
    if u is None:
        return Unit("unitless")
    if not isinstance(u, str):
        raise UnitError(f"a unit must be a string such as 'USD mn', 'percent' or 'bp', not {u!r}")
    text = " ".join(u.strip().split())
    low = text.lower()
    if low in _ALIASES:
        kind = _ALIASES[low]
        return Unit(kind)
    if "/" in text:
        num, _, den = text.partition("/")
        n, d = parse_unit(num), parse_unit(den)
        if n.kind == "per" or d.kind == "per":
            raise UnitError(f"unit {u!r}: only one '/' is allowed")
        return Unit("per", f"{n}/{d}")
    parts = text.split(" ")
    scale = ""
    if len(parts) == 2 and parts[1].lower() in _SCALE_WORDS:
        scale = _SCALE_WORDS[parts[1].lower()]
        head = parts[0]
    elif len(parts) == 1:
        head = parts[0]
    else:
        raise UnitError(f"unit {u!r} is not one SAJHA knows: use a currency code with an optional scale "
                        f"('USD', 'USD mn'), 'count', 'percent', 'pp', 'bp', 'ratio', 'index', 'days', 'years' "
                        f"or 'unitless'")
    hl = head.lower()
    if hl in ("count", "number", "units", "shares"):
        return Unit("count", "", scale)
    if _CURRENCY.match(head) and hl not in _NOT_CURRENCY and hl not in _ALIASES:
        return Unit("currency", head.upper(), scale)
    raise UnitError(f"unit {u!r} is not one SAJHA knows: use a currency code with an optional scale "
                    f"('USD', 'USD mn'), 'count', 'percent', 'pp', 'bp', 'ratio', 'index', 'days', 'years' "
                    f"or 'unitless'" + ("; a scale applies to currency and count only" if scale else ""))


def days_per_year(day_count: Optional[str] = None) -> float:
    """Days in a year under a day-count basis (``act/365`` when none is given)."""
    basis = (day_count or "act/365").lower().replace(" ", "")
    if basis not in DAY_COUNTS:
        raise UnitError(f"day-count basis {day_count!r} is not one of {', '.join(DAY_COUNTS)}")
    return DAY_COUNTS[basis]


def conversion_factor(src: UnitLike, dst: UnitLike, day_count: Optional[str] = None) -> float:
    """The multiplier from ``src`` to ``dst`` (value_in_dst = value_in_src × factor), or
    :class:`UnitError` when §2.2 does not allow the conversion."""
    a, b = parse_unit(src), parse_unit(dst)
    if a == b:
        return 1.0
    if a.kind == "currency" and b.kind == "currency":
        if a.code != b.code:
            raise UnitError(f"converting {a.code} to {b.code} needs an FX rate: read the rate from a tool as a "
                            f"quantity (unit {b.code}/{a.code}) and use fx_convert", "cross_currency")
        return a.factor / b.factor
    if a.kind == "count" and b.kind == "count":
        return a.factor / b.factor
    if a.is_rate and b.is_rate:
        return RATE_FACTORS[a.kind] / RATE_FACTORS[b.kind]
    if a.is_time and b.is_time:
        dpy = days_per_year(day_count)
        return dpy if (a.kind, b.kind) == ("years", "days") else 1.0 / dpy
    if (a.is_level and b.is_rate) or (a.is_rate and b.is_level):
        lvl, rate = (a, b) if a.is_level else (b, a)
        raise UnitError(f"{lvl} is a level and {rate} is a rate; SAJHA does not convert between a level and a "
                        f"rate (compute a rate from levels with pct_change or ratio)", "level_rate")
    raise UnitError(f"{a} cannot be converted to {b}")


def convert_value(value: Any, src: UnitLike, dst: UnitLike, day_count: Optional[str] = None) -> Any:
    """``value`` (a float or a nested list of floats) expressed in ``dst``."""
    f = conversion_factor(src, dst, day_count)
    return scale_value(value, f)


def scale_value(value: Any, f: float) -> Any:
    if isinstance(value, list):
        return [scale_value(v, f) for v in value]
    return float(value) * f if f != 1.0 else float(value)


def convertible(src: UnitLike, dst: UnitLike) -> bool:
    try:
        conversion_factor(src, dst)
        return True
    except UnitError:
        return False


def equivalents(unit: UnitLike) -> List[Unit]:
    """Every unit ``unit`` converts to, itself first (what a figure in an answer may be written in)."""
    u = parse_unit(unit)
    if u.kind == "currency":
        return [u] + [u.with_scale(s) for s in SCALES if s != u.scale]
    if u.kind == "count":
        return [u] + [u.with_scale(s) for s in SCALES if s != u.scale]
    if u.is_rate:
        return [u] + [Unit(k) for k in RATE_KINDS if k != u.kind]
    if u.is_time:
        return [u] + [Unit(k) for k in TIME_KINDS if k != u.kind]
    return [u]


def per_unit(num: UnitLike, den: UnitLike) -> Unit:
    """The unit of ``num`` divided by ``den`` (scales dropped: values are taken at base scale)."""
    n, d = parse_unit(num).base(), parse_unit(den).base()
    if n == d:
        return Unit("ratio")
    if d.kind == "unitless":
        return n
    return Unit("per", f"{n}/{d}")
