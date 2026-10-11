"""
SAJHA MCP Server — Business Intelligence: the arithmetic of the analysis tools (§4).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Each analysis tool compiles one or a few metric queries (``compiler.run``) and does the
arithmetic here, in Python, on the bounded result: comparisons, shares and Pareto sets,
two-way tables with margins, cumulative and rolling values, and contribution analysis.

Contribution analysis (``explain_change``) is exact for additive metrics (sum, count: each
member's change, which add up to the total change) and, for ratio metrics, splits the change of
the overall ratio into a rate effect and a mix effect per member that also add up exactly:

    R = sum_i w_i * r_i     (w_i = member's share of the denominator, r_i = member's ratio)
    dR = sum_i w1_i * (r1_i - r0_i)   [rate]   +   sum_i (w1_i - w0_i) * (r0_i - R0)   [mix]

(the mix term is centred on the old overall ratio R0, so a member that gains weight adds to the
ratio only when its own ratio was above average; a new member's old ratio is taken as R0).

Other types (count_distinct, avg, min, max) are not additive: members are ranked by their own
change and no share of the total is claimed.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sajha.bi.metrics import Metric, MetricError

ROLLING_FNS = ('sum', 'avg', 'min', 'max')


def _r(v: Optional[float], nd: int = 6) -> Optional[float]:
    if v is None or (isinstance(v, int) and not isinstance(v, bool)):
        return v
    f = round(float(v), nd)
    return int(f) if f.is_integer() and isinstance(v, float) and v.is_integer() else f


def _key(row: Dict[str, Any], by: Sequence[str]) -> Tuple:
    return tuple(row.get(b) for b in by)


def pct(change: Optional[float], base: Optional[float]) -> Optional[float]:
    if change is None or base in (None, 0):
        return None
    return _r(100.0 * change / abs(base), 4)


def compare(cur: List[Dict[str, Any]], prev: List[Dict[str, Any]], by: Sequence[str]) -> List[Dict[str, Any]]:
    """One row per member of either side: value, comparison value, change and percent change."""
    a = {_key(r, by): r for r in cur}
    b = {_key(r, by): r for r in prev}
    keys = list(a) + [k for k in b if k not in a]
    out = []
    for k in keys:
        v = a.get(k, {}).get('value')
        w = b.get(k, {}).get('value')
        change = (v or 0) - (w or 0) if (v is not None or w is not None) else None
        out.append({**dict(zip(by, k)), 'value': _r(v), 'comparison': _r(w), 'change': _r(change),
                    'pct_change': pct(change, w)})
    out.sort(key=lambda r: -(r['value'] if r['value'] is not None else float('-inf')))
    return out


def top_n(rows: List[Dict[str, Any]], dim: str, n: int, total: Optional[float], additive: bool,
          pareto: Optional[float] = None) -> Tuple[List[Dict[str, Any]], Optional[List[Any]]]:
    """The top ``n`` members with share and cumulative share; with ``pareto`` (percent), the members
    whose cumulative share first reaches it."""
    ranked = sorted((r for r in rows if r.get('value') is not None), key=lambda r: -r['value'])
    out, cum = [], 0.0
    share_ok = additive and total not in (None, 0)
    pareto_set: Optional[List[Any]] = [] if (pareto is not None and share_ok) else None
    for i, r in enumerate(ranked):
        share = (100.0 * r['value'] / total) if share_ok else None
        if share is not None:
            if pareto_set is not None and cum < pareto:
                pareto_set.append(r.get(dim))
            cum += share
        if i < n:
            out.append({'rank': i + 1, dim: r.get(dim), 'value': _r(r['value']), 'share_pct': _r(share, 4),
                        'cumulative_share_pct': _r(cum, 4) if share is not None else None})
    return out, pareto_set


def crosstab(cells: List[Dict[str, Any]], rows_dim: str, cols_dim: str,
             row_totals: Optional[Dict[Any, float]] = None, col_totals: Optional[Dict[Any, float]] = None,
             grand: Optional[float] = None, normalize: Optional[str] = None) -> Dict[str, Any]:
    """A two-way table: row and column headers, a cell matrix (None for an empty cell) and margins."""
    row_keys = sorted({c.get(rows_dim) for c in cells}, key=lambda x: (x is None, str(x)))
    col_keys = sorted({c.get(cols_dim) for c in cells}, key=lambda x: (x is None, str(x)))
    idx = {(c.get(rows_dim), c.get(cols_dim)): c.get('value') for c in cells}
    matrix = [[idx.get((r, k)) for k in col_keys] for r in row_keys]
    if normalize:
        def base(i, j):
            if normalize == 'row':
                return (row_totals or {}).get(row_keys[i])
            if normalize == 'column':
                return (col_totals or {}).get(col_keys[j])
            return grand
        matrix = [[(100.0 * v / base(i, j)) if v is not None and base(i, j) else None
                   for j, v in enumerate(row)] for i, row in enumerate(matrix)]
    out: Dict[str, Any] = {'row_dimension': rows_dim, 'column_dimension': cols_dim,
                           'row_headers': row_keys, 'column_headers': col_keys,
                           'cells': [[_r(v) for v in row] for row in matrix]}
    if row_totals is not None:
        out['row_totals'] = [_r(row_totals.get(r)) for r in row_keys]
        out['column_totals'] = [_r((col_totals or {}).get(k)) for k in col_keys]
        out['grand_total'] = _r(grand)
    return out


def _reset_key(d: date, unit: str, fiscal_start: int) -> Tuple:
    from sajha.bi.periods import _unit_start
    return (_unit_start(d, unit, fiscal_start),)


def cumulative(rows: List[Dict[str, Any]], by: Sequence[str], kind: str, grain: str, m: Metric) -> None:
    """Add ``cumulative``: the running total that restarts each year (ytd), quarter (qtd) or month (mtd)."""
    unit = {'ytd': 'year', 'qtd': 'quarter', 'mtd': 'month'}.get(kind)
    if unit is None:
        raise MetricError('cumulative is ytd, qtd or mtd')
    if not m.additive:
        raise MetricError(f'cumulative values need an additive metric (sum or count); {m.name} is {m.type}')
    order = ['day', 'week', 'month', 'quarter', 'year']
    if not grain or order.index(grain) >= order.index(unit) or (grain == 'week' and unit == 'month'):
        raise MetricError(f'cumulative {kind} needs a grain finer than a {unit}'
                          + (' (day for mtd)' if unit == 'month' else ''))
    running: Dict[Tuple, Tuple[Tuple, float]] = {}
    for r in sorted(rows, key=lambda x: (_key(x, by), x.get('period_start') or '')):
        d = date.fromisoformat(str(r['period_start'])[:10])
        k, reset = _key(r, by), _reset_key(d, unit, m.fiscal_year_start)
        last = running.get(k)
        total = (last[1] if last and last[0] == reset else 0.0) + (r.get('value') or 0)
        running[k] = (reset, total)
        r['cumulative'] = _r(total)


def rolling(rows: List[Dict[str, Any]], by: Sequence[str], window: int, fn: str) -> None:
    """Add ``rolling``: ``fn`` over this and the previous ``window - 1`` rows of the same member
    (rows, not calendar periods: a period with no data is not a row)."""
    if fn not in ROLLING_FNS:
        raise MetricError(f'rolling.fn is one of {", ".join(ROLLING_FNS)}')
    hist: Dict[Tuple, List[float]] = {}
    for r in sorted(rows, key=lambda x: (_key(x, by), x.get('period_start') or '')):
        h = hist.setdefault(_key(r, by), [])
        if r.get('value') is not None:
            h.append(r['value'])
        win = h[-window:]
        if not win:
            r['rolling'] = None
            continue
        r['rolling'] = _r({'sum': sum(win), 'avg': sum(win) / len(win), 'min': min(win), 'max': max(win)}[fn])


def _explains(members: List[Dict[str, Any]], total_change: float, field: str, share: float = 80.0) -> List[Any]:
    """The fewest members, largest first in the direction of the change, whose contributions reach
    ``share`` percent of the total change."""
    if not total_change:
        return []
    sign = 1 if total_change > 0 else -1
    picked, cum = [], 0.0
    for r in sorted(members, key=lambda x: -sign * (x[field] or 0)):
        if sign * (r[field] or 0) <= 0 or cum >= share / 100.0 * abs(total_change):
            break
        picked.append(r['member'])
        cum += sign * r[field]
    return picked


def explain_change(m: Metric, dim: str, cur: List[Dict[str, Any]], prev: List[Dict[str, Any]],
                   total_cur: Optional[float], total_prev: Optional[float], top: int) -> Dict[str, Any]:
    """Contribution of each member of ``dim`` to the change from ``prev`` to ``cur``."""
    a = {r.get(dim): r for r in cur}
    b = {r.get(dim): r for r in prev}
    keys = list(a) + [k for k in b if k not in a]
    total_change = (total_cur or 0) - (total_prev or 0)
    members: List[Dict[str, Any]] = []
    if m.type == 'ratio':
        den1 = sum((r.get('denominator') or 0) for r in cur) or 0
        den0 = sum((r.get('denominator') or 0) for r in prev) or 0
        for k in keys:
            r1, r0 = a.get(k, {}), b.get(k, {})
            w1 = (r1.get('denominator') or 0) / den1 if den1 else 0.0
            w0 = (r0.get('denominator') or 0) / den0 if den0 else 0.0
            v1, v0 = r1.get('value'), r0.get('value')
            base = total_prev or 0.0
            r0v = base if v0 is None else v0          # a new member counts as the old average
            rate = w1 * ((v1 or 0) - r0v) if v1 is not None else 0.0
            mix = (w1 - w0) * (r0v - base)
            members.append({'member': k, 'value': _r(v1), 'comparison': _r(v0),
                            'weight': _r(w1), 'comparison_weight': _r(w0),
                            'rate_effect': _r(rate), 'mix_effect': _r(mix), 'contribution': _r(rate + mix),
                            'share_of_change_pct': (_r(100.0 * (rate + mix) / total_change, 4)
                                                    if total_change else None)})
        field = 'contribution'
    else:
        for k in keys:
            v1, v0 = a.get(k, {}).get('value'), b.get(k, {}).get('value')
            change = (v1 or 0) - (v0 or 0)
            members.append({'member': k, 'value': _r(v1), 'comparison': _r(v0), 'change': _r(change),
                            'pct_change': pct(change, v0),
                            'share_of_change_pct': (_r(100.0 * change / total_change, 4)
                                                    if m.additive and total_change else None)})
        field = 'change'
    members.sort(key=lambda r: -abs(r[field] or 0))
    out = {'dimension': dim, 'members': members[:top],
           'explains_most': _explains(members, total_change, field) if (m.additive or m.type == 'ratio') else [],
           'member_count': len(members)}
    if m.type == 'ratio':
        out['rate_effect'] = _r(sum(r['rate_effect'] or 0 for r in members))
        out['mix_effect'] = _r(sum(r['mix_effect'] or 0 for r in members))
    elif not m.additive:
        out['note'] = (f'{m.name} is a {m.type} metric, which does not add up over members: members are '
                       f'ranked by their own change and no share of the total is given')
    return out
