"""
SAJHA MCP Server — workflow parameter mapping and conditions.

Mapping extends the composite syntax (sajha/core/composition.py::resolve_source):

    "$input.x" / "$.input.x"   the run's input
    "$steps.<id>"              a finished step's output ("$steps.<id>.a.0.b" digs into it)
    "$item" / "$item.x"        the current element inside a foreach step ("$index" its position)
    "$run.id", "$run.workflow" the run itself
    "$.x"                      the current element (as in a composite fan-out), else literal
    "text {{$input.x}} text"   interpolation inside a longer string
    anything else              a literal

Dicts and lists are resolved recursively. A condition is a string ``"<ref> <op> <value>"``,
a dict ``{left, op, right}``, ``{all: [...]}``, ``{any: [...]}``, ``{not: ...}``, a bare
reference (truthiness) or a boolean.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

_TEMPLATE = re.compile(r'\{\{\s*(\$[^{}]+?)\s*\}\}')
_COND = re.compile(r'^\s*(\S+)\s+(==|!=|>=|<=|>|<|not_in|in|contains|startswith)\s+(.+?)\s*$')
_UNARY = re.compile(r'^\s*(exists|not_exists|truthy|falsy)\s+(\S+)\s*$')
_MISSING = object()

OPS = ('==', '!=', '>', '>=', '<', '<=', 'in', 'not_in', 'contains', 'startswith',
       'exists', 'not_exists', 'truthy', 'falsy')


def _dig(data: Any, path: str) -> Any:
    if not path:
        return data
    for key in path.split('.'):
        if isinstance(data, dict) and key in data:
            data = data[key]
        elif isinstance(data, list) and key.lstrip('-').isdigit() and -len(data) <= int(key) < len(data):
            data = data[int(key)]
        else:
            return _MISSING
    return data


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith('$') and ' ' not in value.strip()


def resolve_ref(expr: str, ctx: Dict[str, Any]) -> Any:
    """One reference; a missing path is None ("$input.x" keeps the composite rule: "")."""
    expr = expr.strip()
    for prefix, root in (('$steps.', 'steps'), ('$run.', 'run')):
        if expr.startswith(prefix):
            v = _dig(ctx.get(root) or {}, expr[len(prefix):])
            return None if v is _MISSING else v
    if expr == '$item':
        return ctx.get('item')
    if expr.startswith('$item.'):
        v = _dig(ctx.get('item'), expr[len('$item.'):])
        return None if v is _MISSING else v
    if expr == '$index':
        return ctx.get('index')
    if expr in ('$input', '$.input'):
        return ctx.get('input') or {}
    from sajha.core.composition import resolve_source
    item = ctx.get('item')
    return resolve_source(expr, master_input=ctx.get('input') or {},
                          record=item if isinstance(item, (dict, list)) else {})


def resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    """Resolve a mapping value (recursively through dicts and lists)."""
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if not isinstance(value, str):
        return value
    if is_ref(value):
        return resolve_ref(value, ctx)
    if '{{' in value:
        def sub(m):
            v = resolve_ref(m.group(1), ctx)
            return v if isinstance(v, str) else json.dumps(v, default=str)
        return _TEMPLATE.sub(sub, value)
    return value


def refs_in(value: Any):
    """Every ``$steps.<id>`` step id a mapping value reads (for implicit dependencies)."""
    out = set()
    if isinstance(value, dict):
        for v in value.values():
            out |= refs_in(v)
    elif isinstance(value, list):
        for v in value:
            out |= refs_in(v)
    elif isinstance(value, str):
        for m in re.finditer(r'\$steps\.([A-Za-z][A-Za-z0-9_]*)', value):
            out.add(m.group(1))
    return out


def _literal(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text.strip('\'"') if len(text) >= 2 and text[0] == text[-1] and text[0] in '\'"' else text


def _operand(v: Any, ctx: Dict[str, Any]) -> Any:
    return resolve(v, ctx)


def _compare(left: Any, op: str, right: Any) -> bool:
    try:
        if op == '==':
            return left == right
        if op == '!=':
            return left != right
        if op in ('>', '>=', '<', '<='):
            if isinstance(left, str) and isinstance(right, (int, float)):
                left = float(left)
            if isinstance(right, str) and isinstance(left, (int, float)):
                right = float(right)
            return {'>': left > right, '>=': left >= right, '<': left < right, '<=': left <= right}[op]
        if op == 'in':
            return left in (right or [])
        if op == 'not_in':
            return left not in (right or [])
        if op == 'contains':
            return right in (left or [])
        if op == 'startswith':
            return str(left or '').startswith(str(right))
        if op == 'exists':
            return left is not None and left != ''
        if op == 'not_exists':
            return left is None or left == ''
        if op == 'truthy':
            return bool(left)
        if op == 'falsy':
            return not left
    except (TypeError, ValueError):
        return False
    raise ValueError(f'unknown condition operator {op!r} (one of {", ".join(OPS)})')


def evaluate(cond: Any, ctx: Dict[str, Any]) -> bool:
    """Evaluate a condition against the run context."""
    if isinstance(cond, bool):
        return cond
    if cond is None:
        return False
    if isinstance(cond, dict):
        if 'all' in cond:
            return all(evaluate(c, ctx) for c in cond['all'] or [])
        if 'any' in cond:
            return any(evaluate(c, ctx) for c in cond['any'] or [])
        if 'not' in cond:
            return not evaluate(cond['not'], ctx)
        op = cond.get('op', 'truthy')
        return _compare(_operand(cond.get('left'), ctx), op, _operand(cond.get('right'), ctx))
    if isinstance(cond, str):
        m = _UNARY.match(cond)
        if m:
            return _compare(_operand(m.group(2), ctx), m.group(1), None)
        m = _COND.match(cond)
        if m:
            left, op, right = m.groups()
            r = _operand(right.strip(), ctx) if is_ref(right.strip()) else _literal(right)
            return _compare(_operand(left, ctx), op, r)
        return bool(_operand(cond.strip(), ctx))
    return bool(cond)


def check_condition(cond: Any) -> None:
    """Raise ValueError for a condition that can never evaluate (bad operator, bad shape)."""
    if isinstance(cond, (bool, type(None))):
        return
    if isinstance(cond, dict):
        for key in ('all', 'any'):
            if key in cond:
                if not isinstance(cond[key], list):
                    raise ValueError(f'condition "{key}" must be a list')
                for c in cond[key]:
                    check_condition(c)
                return
        if 'not' in cond:
            return check_condition(cond['not'])
        if cond.get('op', 'truthy') not in OPS:
            raise ValueError(f'unknown condition operator {cond.get("op")!r} (one of {", ".join(OPS)})')
        return
    if not isinstance(cond, str):
        raise ValueError('a condition is a string, a {left, op, right} object, all/any/not, or a boolean')
