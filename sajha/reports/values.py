"""
SAJHA MCP Server — report values: how a number is displayed, and the precision it is displayed at.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Formats (a KPI's or column's ``format``): ``number`` (default; 2 decimals unless an integer),
``integer``, ``percent`` (the value is already in percent: 4.5 -> "4.50%"), ``ratio`` (a fraction
shown as a percent: 0.045 -> "4.50%"), ``currency`` (2 decimals, with ``currency: USD`` as a
prefix), ``bps`` (basis points), ``date`` and ``text`` (as is). ``decimals`` overrides the places.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float('inf'), float('-inf'))


def to_number(v: Any) -> Optional[float]:
    if is_number(v):
        return v
    if isinstance(v, str):
        s = v.strip().replace(',', '')
        if s.endswith('%'):
            s = s[:-1]
        try:
            f = float(s)
            return f if f == f else None
        except ValueError:
            return None
    return None


def decimals_for(spec: Dict[str, Any], value: Any) -> Optional[int]:
    """Decimal places the value is displayed at (None for text and dates)."""
    fmt = spec.get('format') or 'number'
    if fmt in ('text', 'date') or not is_number(value):
        return None
    if isinstance(spec.get('decimals'), int):
        return max(0, min(10, spec['decimals']))
    if fmt == 'integer':
        return 0
    if fmt == 'bps':
        return 0 if float(value).is_integer() else 1
    if fmt == 'number' and isinstance(value, int):
        return 0
    return 2


def display(value: Any, spec: Optional[Dict[str, Any]] = None) -> str:
    spec = spec or {}
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    fmt = spec.get('format') or 'number'
    if not is_number(value) or fmt in ('text', 'date'):
        if isinstance(value, (dict, list)):
            import json
            s = json.dumps(value, default=str)
            return s if len(s) <= 200 else s[:197] + '...'
        return str(value)
    d = decimals_for(spec, value)
    v = float(value) * 100 if fmt == 'ratio' else value
    if fmt in ('percent', 'ratio'):
        return f'{v:,.{d}f}%'
    if fmt == 'bps':
        return f'{v:,.{d}f} bp'
    if fmt == 'currency':
        cur = spec.get('currency')
        return (f'{cur} ' if cur else '') + f'{v:,.{d}f}'
    return f'{v:,.{d}f}'


def displayed_value(value: Any, spec: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """The number a reader sees (rounded as displayed; a ratio in percent), or None for text."""
    spec = spec or {}
    if not is_number(value):
        return None
    d = decimals_for(spec, value)
    v = float(value) * 100 if spec.get('format') == 'ratio' else float(value)
    return round(v, d if d is not None else 2)
