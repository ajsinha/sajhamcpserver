"""
SAJHA MCP Server — a small JSONPath subset for test assertions (no dependency).

Supported: ``$`` (the root), ``.key`` and ``['key']`` / ``["key"]``, ``[n]`` and negative
``[-1]``, ``[*]`` and ``.*`` (every child), ``..key`` (recursive descent) and ``..*``.
Filters, slices and scripts are not supported (a path using them is a ``JSONPathError``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_NAME = re.compile(r'[A-Za-z_$@][\w$@\-]*')


class JSONPathError(ValueError):
    """A path outside the supported subset."""


def parse(path: str) -> List[Tuple[str, Any]]:
    """``path`` as steps: ('key', name) | ('index', n) | ('wild', None) | ('deep', name-or-None)."""
    p = (path or '').strip()
    if not p.startswith('$'):
        p = '$.' + p if p and not p.startswith('[') else '$' + p
    i, steps = 1, []
    while i < len(p):
        c = p[i]
        if p.startswith('..', i):
            i += 2
            if i < len(p) and p[i] == '*':
                steps.append(('deep', None))
                i += 1
                continue
            if i < len(p) and p[i] == '[':
                name, i = _bracket(p, i)
                if name[0] != 'key':
                    raise JSONPathError(f'only a name may follow ".." in {path!r}')
                steps.append(('deep', name[1]))
                continue
            m = _NAME.match(p, i)
            if not m:
                raise JSONPathError(f'expected a name after ".." at {i} in {path!r}')
            steps.append(('deep', m.group(0)))
            i = m.end()
        elif c == '.':
            i += 1
            if i < len(p) and p[i] == '*':
                steps.append(('wild', None))
                i += 1
                continue
            m = _NAME.match(p, i)
            if not m:
                raise JSONPathError(f'expected a name at {i} in {path!r}')
            steps.append(('key', m.group(0)))
            i = m.end()
        elif c == '[':
            step, i = _bracket(p, i)
            steps.append(step)
        else:
            raise JSONPathError(f'unexpected {c!r} at {i} in {path!r}')
    return steps


def _bracket(p: str, i: int) -> Tuple[Tuple[str, Any], int]:
    end = p.find(']', i)
    if end < 0:
        raise JSONPathError(f'unclosed [ in {p!r}')
    inner = p[i + 1:end].strip()
    if inner == '*':
        return ('wild', None), end + 1
    if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in '\'"':
        return ('key', inner[1:-1]), end + 1
    if re.fullmatch(r'-?\d+', inner):
        return ('index', int(inner)), end + 1
    raise JSONPathError(f'unsupported selector [{inner}] in {p!r} (filters and slices are not supported)')


def _children(v: Any) -> List[Any]:
    if isinstance(v, dict):
        return list(v.values())
    if isinstance(v, list):
        return list(v)
    return []


def _descend(v: Any) -> List[Any]:
    out = [v]
    for c in _children(v):
        out.extend(_descend(c))
    return out


def find(data: Any, path: str) -> List[Any]:
    """Every value ``path`` selects in ``data`` (an empty list when none)."""
    current = [data]
    for kind, arg in parse(path):
        nxt: List[Any] = []
        for v in current:
            if kind == 'key':
                if isinstance(v, dict) and arg in v:
                    nxt.append(v[arg])
            elif kind == 'index':
                if isinstance(v, list) and -len(v) <= arg < len(v):
                    nxt.append(v[arg])
            elif kind == 'wild':
                nxt.extend(_children(v))
            elif kind == 'deep':
                for d in _descend(v):
                    if arg is None:
                        nxt.extend(_children(d))
                    elif isinstance(d, dict) and arg in d:
                        nxt.append(d[arg])
        current = nxt
    return current
