"""
SAJHA MCP Server — the operation library (Quantitative Planners §2.3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Pure functions over :class:`Quantity` values. Each runs a unit check first and raises
:class:`QuantError` (or its subclass :class:`UnitError`) with a message for the model when its
inputs do not fit; otherwise it returns a new Quantity whose ``lineage`` names the operation, its
inputs (workspace names, or the literal values) and its arguments. ``regression`` returns a dict
of quantities (``slope`` or ``slope_1``..``slope_k``, ``intercept``, ``r2``).

The model names operations; it never writes the arithmetic. ``npv``, ``irr`` and ``pct_change``
agree with the calculator tools ``calc_npv``, ``calc_irr`` and ``calc_percentage_change``
(tests/ai/test_quant.py proves it).
"""

from __future__ import annotations

import math
import statistics
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from sajha.ai.quant.errors import QuantError, UnitError
from sajha.ai.quant.quantity import Quantity
from sajha.ai.quant.units import (RATE_FACTORS, Unit, UnitLike, conversion_factor, days_per_year, parse_unit,
                                  per_unit)

_OPS: Dict[str, Callable[..., Any]] = {}
SIGNATURES: Dict[str, str] = {}
PERIODS = {"day": None, "week": 7.0, "month": 1 / 12, "quarter": 0.25, "half": 0.5, "half_year": 0.5, "year": 1.0}
CONVENTIONS = ("simple", "compound", "sqrt_time")


def _op(name: str, signature: str):
    def deco(fn):
        _OPS[name] = fn
        SIGNATURES[name] = signature
        return fn
    return deco


def operations() -> Dict[str, str]:
    """Operation name -> its signature, for prompts and validation."""
    return dict(SIGNATURES)


def operation(name: str) -> Callable[..., Any]:
    if name not in _OPS:
        raise QuantError(f"there is no operation {name!r}; the operations are: {', '.join(sorted(_OPS))}",
                         "unknown_operation")
    return _OPS[name]


# ── helpers ──────────────────────────────────────────────────────

def _day_count() -> str:
    from sajha.ai.quant.settings import quant_settings
    return quant_settings().day_count


def _q(x: Any, op: str, what: str, unit: UnitLike = None) -> Quantity:
    """``x`` as a Quantity (a bare number or list becomes a constant in ``unit``)."""
    if isinstance(x, Quantity):
        return x
    if x is None:
        raise QuantError(f"{op}: {what} is required", "missing_input")
    if isinstance(x, (int, float, list, tuple)) and not isinstance(x, bool):
        return Quantity.of(list(x) if isinstance(x, tuple) else x, unit)
    raise QuantError(f"{op}: {what} must be a quantity or a number, not {x!r}", "bad_input")


def _ref(q: Quantity) -> Any:
    return q.name if q.name else {"value": q.value, "unit": str(q.unit), "source": q.source}


def _as_of(inputs: Sequence[Quantity]) -> Optional[str]:
    dates = [q.as_of for q in inputs if q.as_of]
    return max(dates) if dates else None


def _result(value: Any, unit: UnitLike, op: str, inputs: Sequence[Quantity], args: Optional[Dict[str, Any]] = None,
            as_of: Optional[str] = None) -> Quantity:
    return Quantity(value, parse_unit(unit), as_of if as_of is not None else _as_of(inputs),
                    {"kind": "operation", "op": op},
                    {"op": op, "inputs": [_ref(q) for q in inputs], "args": dict(args or {})})


def _factor(src: Unit, dst: Unit, op: str) -> float:
    try:
        return conversion_factor(src, dst, _day_count())
    except UnitError as e:
        raise UnitError(f"{op}: {src} and {dst} cannot be combined: {e}", e.code)


def _scale(v: Any, f: float) -> Any:
    if isinstance(v, list):
        return [_scale(x, f) for x in v]
    return v * f


def _map2(a: Any, b: Any, fn: Callable[[float, float], float], op: str) -> Any:
    """Element-wise ``fn`` over scalars, equal-length columns, or a column and a scalar."""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            raise QuantError(f"{op}: the two columns have different lengths ({len(a)} and {len(b)})", "shape")
        return [_map2(x, y, fn, op) for x, y in zip(a, b)]
    if isinstance(a, list):
        return [_map2(x, b, fn, op) for x in a]
    if isinstance(b, list):
        return [_map2(a, y, fn, op) for y in b]
    return fn(a, b)


def _scalar(q: Quantity, op: str, what: str) -> float:
    if not q.is_scalar:
        raise QuantError(f"{op}: {what} must be a single number, not a table", "shape")
    return float(q.value)            # type: ignore[arg-type]


def _column(q: Quantity, op: str, what: str, min_len: int = 1) -> List[float]:
    if q.is_scalar:
        vals = [float(q.value)]      # type: ignore[arg-type]
    elif q.is_column:
        vals = list(q.value)         # type: ignore[arg-type]
    else:
        raise QuantError(f"{op}: {what} must be a column (a list of numbers), not a grid", "shape")
    if len(vals) < min_len:
        raise QuantError(f"{op}: {what} needs at least {min_len} values; it has {len(vals)}", "shape")
    return vals


def _years(x: Any, op: str, what: str) -> Tuple[float, Optional[Quantity]]:
    """A length of time in years, from a time quantity, a number (years) or a period word."""
    if isinstance(x, str):
        word = x.lower().strip()
        if word not in PERIODS:
            raise QuantError(f"{op}: {what} {x!r} is not one of {', '.join(PERIODS)}", "bad_input")
        return (PERIODS[word] if PERIODS[word] is not None else 1.0 / days_per_year(_day_count())), None
    q = _q(x, op, what, "years")
    if q.unit.kind == "unitless":
        return _scalar(q, op, what), q
    if not q.unit.is_time:
        raise UnitError(f"{op}: {what} must be a time (days or years), not {q.unit}")
    return _scalar(q, op, what) * _factor(q.unit, Unit("years"), op), q


def _rate_ratio(q: Quantity, op: str, what: str) -> Any:
    if not q.unit.is_rate:
        raise UnitError(f"{op}: {what} must be a rate (percent, pp, bp or ratio), not {q.unit}")
    return _scale(q.value, RATE_FACTORS[q.unit.kind])


# ── differences and changes ──────────────────────────────────────

@_op("diff", "diff(a, b): a − b, same kind; percent − percent is pp")
def diff(a: Any, b: Any) -> Quantity:
    qa, qb = _q(a, "diff", "a"), _q(b, "diff", "b")
    f = _factor(qb.unit, qa.unit, "diff")
    unit = qa.unit
    if qa.unit.kind == "percent" and qb.unit.kind in ("percent", "ratio", "bp"):
        unit = Unit("pp")
    return _result(_map2(qa.value, _scale(qb.value, f), lambda x, y: x - y, "diff"), unit, "diff", [qa, qb])


@_op("pp", "pp(a, b): a − b for two rates, in percentage points")
def pp(a: Any, b: Any) -> Quantity:
    qa, qb = _q(a, "pp", "a"), _q(b, "pp", "b")
    ra, rb = _rate_ratio(qa, "pp", "a"), _rate_ratio(qb, "pp", "b")
    return _result(_map2(ra, rb, lambda x, y: (x - y) * 100.0, "pp"), "pp", "pp", [qa, qb])


@_op("pct_change", "pct_change(from, to[, of_rate]): (to − from) / |from| in percent")
def pct_change(frm: Any = None, to: Any = None, of_rate: bool = False, **kw: Any) -> Quantity:
    frm = kw.pop("from", frm)
    if kw:
        raise QuantError(f"pct_change: unknown argument(s) {sorted(kw)}", "bad_input")
    qf, qt = _q(frm, "pct_change", "from"), _q(to, "pct_change", "to")
    f = _factor(qf.unit, qt.unit, "pct_change")
    if qt.unit.is_rate and not of_rate:
        raise UnitError("pct_change: both values are rates; a percent change of a rate is rarely what is meant. "
                        "Use diff (percentage points) or bp_spread for the change in the rate, or pass "
                        "of_rate: true for the relative change", "rate_of_rate")

    def change(old: float, new: float) -> float:
        if old == 0:
            raise QuantError("pct_change: the starting value is zero, so the percent change is undefined",
                             "division_by_zero")
        return (new - old) / abs(old) * 100.0
    return _result(_map2(_scale(qf.value, f), qt.value, change, "pct_change"), "percent", "pct_change", [qf, qt],
                   {"of_rate": True} if of_rate else None, as_of=qt.as_of or _as_of([qf, qt]))


@_op("ratio", "ratio(a, b): a / b; ratio when the units match, else a per unit")
def ratio(a: Any, b: Any) -> Quantity:
    qa, qb = _q(a, "ratio", "a"), _q(b, "ratio", "b")

    def div(x: float, y: float) -> float:
        if y == 0:
            raise QuantError("ratio: the denominator is zero", "division_by_zero")
        return x / y
    if qa.unit.family == qb.unit.family:
        f = _factor(qb.unit, qa.unit, "ratio")
        return _result(_map2(qa.value, _scale(qb.value, f), div, "ratio"), "ratio", "ratio", [qa, qb])
    unit = per_unit(qa.unit, qb.unit)
    va, vb = _scale(qa.value, qa.unit.factor), _scale(qb.value, qb.unit.factor)
    return _result(_map2(va, vb, div, "ratio"), unit, "ratio", [qa, qb])


@_op("bp_spread", "bp_spread(a, b): rate a − rate b in basis points")
def bp_spread(a: Any, b: Any) -> Quantity:
    qa, qb = _q(a, "bp_spread", "a"), _q(b, "bp_spread", "b")
    ra, rb = _rate_ratio(qa, "bp_spread", "a"), _rate_ratio(qb, "bp_spread", "b")
    return _result(_map2(ra, rb, lambda x, y: (x - y) * 1e4, "bp_spread"), "bp", "bp_spread", [qa, qb])


# ── growth and time ──────────────────────────────────────────────

@_op("cagr", "cagr(start, end, years): (end/start)^(1/years) − 1 in percent")
def cagr(start: Any, end: Any, years: Any) -> Quantity:
    qs, qe = _q(start, "cagr", "start"), _q(end, "cagr", "end")
    f = _factor(qs.unit, qe.unit, "cagr")
    s, e = _scalar(qs, "cagr", "start") * f, _scalar(qe, "cagr", "end")
    yrs, qy = _years(years, "cagr", "years")
    if yrs <= 0:
        raise QuantError(f"cagr: the period must be more than zero years; it is {yrs:g}", "zero_period")
    if s <= 0 or e / s <= 0:
        raise QuantError("cagr: start and end must both be positive", "domain")
    inputs = [qs, qe] + ([qy] if qy is not None else [])
    return _result(((e / s) ** (1.0 / yrs) - 1.0) * 100.0, "percent", "cagr", inputs, {"years": yrs},
                   as_of=qe.as_of or _as_of(inputs))


@_op("annualise", "annualise(rate, period, convention[, periods_per_year]): simple | compound | sqrt_time")
def annualise(rate: Any, period: Any = None, convention: str = "compound",
              periods_per_year: Optional[float] = None) -> Quantity:
    q = _q(rate, "annualise", "rate")
    r = _rate_ratio(q, "annualise", "rate")
    if convention not in CONVENTIONS:
        raise QuantError(f"annualise: convention {convention!r} is not one of {', '.join(CONVENTIONS)}", "bad_input")
    if periods_per_year is not None:
        ppy = float(periods_per_year)
    else:
        yrs, _ = _years(period, "annualise", "period")
        if yrs <= 0:
            raise QuantError("annualise: the period must be more than zero", "zero_period")
        ppy = 1.0 / yrs
    if ppy <= 0:
        raise QuantError("annualise: periods_per_year must be more than zero", "zero_period")

    def one(x: float) -> float:
        if convention == "simple":
            return x * ppy * 100.0
        if convention == "sqrt_time":
            return x * math.sqrt(ppy) * 100.0
        if x <= -1:
            raise QuantError("annualise: a compound rate must be above −100%", "domain")
        return ((1.0 + x) ** ppy - 1.0) * 100.0
    value = [one(x) for x in r] if isinstance(r, list) else one(r)
    return _result(value, "percent", "annualise", [q], {"convention": convention, "periods_per_year": ppy})


# ── cash flows ───────────────────────────────────────────────────

def _npv_at(cfs: Sequence[float], r: float, period: float = 1.0) -> float:
    return sum(cf / (1.0 + r) ** (i * period) for i, cf in enumerate(cfs))


@_op("npv", "npv(cash_flows, rate[, period]): Σ CF_i / (1+r)^(i·period); first flow at time 0")
def npv(cash_flows: Any, rate: Any, period: Any = 1.0) -> Quantity:
    qc, qr = _q(cash_flows, "npv", "cash_flows"), _q(rate, "npv", "rate")
    if qc.unit.is_rate:
        raise UnitError(f"npv: cash flows must be amounts, not {qc.unit}")
    cfs = _column(qc, "npv", "cash_flows")
    r = _rate_ratio(qr, "npv", "rate")
    if isinstance(r, list):
        raise QuantError("npv: the rate must be a single number", "shape")
    if r <= -1:
        raise QuantError("npv: the rate must be above −100%", "domain")
    per, qp = _years(period, "npv", "period")
    if per <= 0:
        raise QuantError("npv: the period length must be more than zero", "zero_period")
    inputs = [qc, qr] + ([qp] if qp is not None else [])
    return _result(_npv_at(cfs, r, per), qc.unit, "npv", inputs, {"period_years": per})


@_op("irr", "irr(cash_flows): the rate per period at which npv is zero, in percent")
def irr(cash_flows: Any) -> Quantity:
    qc = _q(cash_flows, "irr", "cash_flows")
    cfs = _column(qc, "irr", "cash_flows", 2)
    if not (any(c > 0 for c in cfs) and any(c < 0 for c in cfs)):
        raise QuantError("irr: the cash flows need at least one negative and one positive flow", "no_root")
    lo, hi = -0.9999, 1.0
    f_lo = _npv_at(cfs, lo)
    f_hi = _npv_at(cfs, hi)
    while f_lo * f_hi > 0 and hi < 1e6:
        hi *= 2.0
        f_hi = _npv_at(cfs, hi)
    if f_lo * f_hi > 0:
        raise QuantError("irr: no rate between −99.99% and 1,000,000% makes the npv zero", "no_root")
    for _ in range(300):
        mid = (lo + hi) / 2.0
        f_mid = _npv_at(cfs, mid)
        if f_mid == 0 or (hi - lo) < 1e-14:
            break
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return _result(((lo + hi) / 2.0) * 100.0, "percent", "irr", [qc])


# ── aggregates and statistics ───────────────────────────────────

@_op("weighted_avg", "weighted_avg(values, weights): Σ v·w / Σ w in the values' unit")
def weighted_avg(values: Any, weights: Any) -> Quantity:
    qv, qw = _q(values, "weighted_avg", "values"), _q(weights, "weighted_avg", "weights")
    v, w = _column(qv, "weighted_avg", "values"), _column(qw, "weighted_avg", "weights")
    if len(v) != len(w):
        raise QuantError(f"weighted_avg: values and weights have different lengths ({len(v)} and {len(w)})", "shape")
    tw = sum(w)
    if tw == 0:
        raise QuantError("weighted_avg: the weights sum to zero", "division_by_zero")
    return _result(sum(x * y for x, y in zip(v, w)) / tw, qv.unit, "weighted_avg", [qv, qw])


def _aggregate(name: str, fn: Callable[[List[float]], float], min_len: int = 1):
    def run(column: Any) -> Quantity:
        q = _q(column, name, "column")
        return _result(fn(_column(q, name, "column", min_len)), q.unit, name, [q])
    run.__name__ = f"q_{name}"
    return run


q_sum = _op("sum", "sum(column)")(_aggregate("sum", lambda v: math.fsum(v)))
q_mean = _op("mean", "mean(column)")(_aggregate("mean", statistics.fmean))
q_median = _op("median", "median(column)")(_aggregate("median", statistics.median))
q_stdev = _op("stdev", "stdev(column): sample standard deviation (n − 1)")(_aggregate("stdev", statistics.stdev, 2))
q_min = _op("min", "min(column)")(_aggregate("min", min))
q_max = _op("max", "max(column)")(_aggregate("max", max))


def _solve(a: List[List[float]], b: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting; QuantError when singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise QuantError("regression: the x columns are constant or collinear, so the fit is not unique",
                             "singular")
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


@_op("regression", "regression(y, x): ordinary least squares; slope(s), intercept, r2")
def regression(y: Any, x: Any) -> Dict[str, Quantity]:
    qy = _q(y, "regression", "y")
    xs_in = x if isinstance(x, list) and x and isinstance(x[0], Quantity) else [x]
    qxs = [_q(c, "regression", "x") for c in xs_in]
    ys = _column(qy, "regression", "y")
    xs = [_column(q, "regression", "x") for q in qxs]
    n, k = len(ys), len(xs)
    if any(len(c) != n for c in xs):
        raise QuantError("regression: y and every x column must have the same length", "shape")
    if n < k + 2:
        raise QuantError(f"regression: {k} x column(s) need at least {k + 2} observations; there are {n}", "shape")
    rows = [[1.0] + [c[i] for c in xs] for i in range(n)]
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k + 1)] for i in range(k + 1)]
    xty = [sum(r[i] * yy for r, yy in zip(rows, ys)) for i in range(k + 1)]
    beta = _solve(xtx, xty)
    fitted = [sum(b * v for b, v in zip(beta, r)) for r in rows]
    ybar = statistics.fmean(ys)
    ss_tot = sum((v - ybar) ** 2 for v in ys)
    if ss_tot == 0:
        raise QuantError("regression: y is constant, so r2 is undefined", "singular")
    r2 = 1.0 - sum((v - f) ** 2 for v, f in zip(ys, fitted)) / ss_tot
    inputs = [qy] + qxs
    out = {"intercept": _result(beta[0], qy.unit, "regression", inputs, {"part": "intercept"}),
           "r2": _result(r2, "unitless", "regression", inputs, {"part": "r2"})}
    for i, q in enumerate(qxs):
        part = "slope" if k == 1 else f"slope_{i + 1}"
        out[part] = _result(beta[i + 1], per_unit(qy.unit, q.unit), "regression", inputs, {"part": part})
    return out


@_op("correlation", "correlation(a, b): Pearson correlation of two columns, unitless")
def correlation(a: Any, b: Any) -> Quantity:
    qa, qb = _q(a, "correlation", "a"), _q(b, "correlation", "b")
    va, vb = _column(qa, "correlation", "a", 2), _column(qb, "correlation", "b", 2)
    if len(va) != len(vb):
        raise QuantError(f"correlation: the columns have different lengths ({len(va)} and {len(vb)})", "shape")
    ma, mb = statistics.fmean(va), statistics.fmean(vb)
    sab = sum((x - ma) * (y - mb) for x, y in zip(va, vb))
    saa, sbb = sum((x - ma) ** 2 for x in va), sum((y - mb) ** 2 for y in vb)
    if saa == 0 or sbb == 0:
        raise QuantError("correlation: a column is constant, so the correlation is undefined", "singular")
    return _result(sab / math.sqrt(saa * sbb), "unitless", "correlation", [qa, qb])


# ── units and presentation ───────────────────────────────────────

@_op("convert", "convert(q, unit): only the conversions §2.2 allows")
def convert(q: Any, unit: UnitLike) -> Quantity:
    qq = _q(q, "convert", "q")
    target = parse_unit(unit)
    f = _factor(qq.unit, target, "convert")
    return _result(_scale(qq.value, f), target, "convert", [qq], {"unit": str(target)}, as_of=qq.as_of)


@_op("fx_convert", "fx_convert(amount, rate): an amount in one currency through an FX rate quantity (quote/base)")
def fx_convert(amount: Any, rate: Any) -> Quantity:
    qa, qr = _q(amount, "fx_convert", "amount"), _q(rate, "fx_convert", "rate")
    if qa.unit.kind != "currency":
        raise UnitError(f"fx_convert: the amount must be in a currency, not {qa.unit}")
    num, _, den = qr.unit.code.partition("/") if qr.unit.kind == "per" else ("", "", "")
    try:
        nu, du = parse_unit(num), parse_unit(den)
    except UnitError:
        nu = du = Unit("unitless")
    if qr.unit.kind != "per" or nu.kind != "currency" or du.kind != "currency":
        raise UnitError(f"fx_convert: the rate must be an FX rate quantity with a unit such as USD/EUR (USD per "
                        f"EUR), not {qr.unit}")
    r = _scalar(qr, "fx_convert", "rate")
    if r <= 0:
        raise QuantError("fx_convert: an FX rate must be positive", "domain")
    if qa.unit.code == du.code:
        value, unit = _scale(qa.value, r), Unit("currency", nu.code, qa.unit.scale)
    elif qa.unit.code == nu.code:
        value, unit = _scale(qa.value, 1.0 / r), Unit("currency", du.code, qa.unit.scale)
    else:
        raise UnitError(f"fx_convert: the amount is in {qa.unit.code} and the rate is {qr.unit}; the rate must "
                        f"quote {qa.unit.code} against the target currency", "cross_currency")
    return _result(value, unit, "fx_convert", [qa, qr])


def _round_half_up(x: float, places: int) -> float:
    return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


@_op("round", "round(q, places): half away from zero; the unit is unchanged")
def q_round(q: Any, places: int = 0) -> Quantity:
    qq = _q(q, "round", "q")
    if isinstance(places, bool) or not isinstance(places, int) or not -12 <= places <= 12:
        raise QuantError("round: places must be an integer from −12 to 12", "bad_input")

    def r(v: Any) -> Any:
        return [r(x) for x in v] if isinstance(v, list) else _round_half_up(v, places)
    return _result(r(qq.value), qq.unit, "round", [qq], {"places": places}, as_of=qq.as_of)


Number = Union[int, float]
