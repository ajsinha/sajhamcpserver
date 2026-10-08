"""
Data classes and field-level redaction (protocol §17, feature ``residency``; design §12).

A **data class** is a label on data (``eu-personal``, ``confidential``, ``public``, ...). A tool's
schema marks argument and result fields with ``x-sajha-data-class`` (a string or a list of strings);
a whole tool may declare classes for its arguments and results; an operator may add classes from
configuration without touching the tool. This module only reads marks and moves data: it does not
decide. Decisions are SAJHA's (``sajha/net/integration/residency.py``) or another rule evaluator's.

* :func:`schema_marks` turns a JSON Schema into ``{path: [classes]}``; a path is dotted property
  names, ``[]`` stands for every item of an array (``rows.[].email``) and ``*`` for the whole value.
* :func:`classes_present` gives the classes of the fields actually present in a value.
* :func:`necessary_classes` gives the classes every call of a tool sends (tool-level classes and
  marks on required top-level properties), used for residency-aware shortlists.
* :func:`redact_fields` replaces the values of fields of the given classes with
  ``[REDACTED:<class>]`` and returns the paths it touched; :func:`redact_result` does that to a
  ``CallToolResult``: ``structuredContent``, and text blocks that hold JSON (re-serialised) or
  that quote a removed value (the value replaced in the text).

It imports nothing from the rest of SAJHA.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import fnmatch
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

MARK = 'x-sajha-data-class'
WHOLE = '*'
ITEMS = '[]'
MAX_DEPTH = 32

Marks = Dict[str, List[str]]


def as_classes(v: Any) -> List[str]:
    """A mark's value as a list of class names (a string, a list of strings, or nothing)."""
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if isinstance(x, (str, int)) and str(x).strip()]
    return []


def _add(marks: Marks, path: str, classes: Iterable[str]) -> None:
    cur = marks.setdefault(path, [])
    for c in classes:
        if c not in cur:
            cur.append(c)


def schema_marks(schema: Any) -> Marks:
    """``{path: [classes]}`` of every ``x-sajha-data-class`` in a JSON Schema."""
    out: Marks = {}

    def walk(s: Any, path: str, depth: int) -> None:
        if not isinstance(s, dict) or depth > MAX_DEPTH:
            return
        if MARK in s:
            _add(out, path or WHOLE, as_classes(s[MARK]))
        props = s.get('properties')
        if isinstance(props, dict):
            for k, sub in props.items():
                walk(sub, f'{path}.{k}' if path else str(k), depth + 1)
        items = s.get('items')
        if isinstance(items, dict):
            walk(items, f'{path}.{ITEMS}' if path else ITEMS, depth + 1)
        for key in ('allOf', 'anyOf', 'oneOf'):
            for sub in s.get(key) or []:
                walk(sub, path, depth + 1)
    walk(schema, '', 0)
    return {k: v for k, v in out.items() if v}


def merge_marks(*parts: Optional[Marks]) -> Marks:
    out: Marks = {}
    for p in parts:
        for k, v in (p or {}).items():
            _add(out, k, as_classes(v))
    return out


def _values_at(value: Any, parts: List[str]) -> List[Any]:
    if not parts:
        return [value]
    head, rest = parts[0], parts[1:]
    if head == ITEMS:
        return [x for item in value for x in _values_at(item, rest)] if isinstance(value, list) else []
    if isinstance(value, dict) and head in value:
        return _values_at(value[head], rest)
    return []


def classes_present(value: Any, marks: Marks) -> List[str]:
    """The classes of the marked fields present in ``value`` (``*`` always counts when ``value`` is set)."""
    out: List[str] = []
    for path, classes in marks.items():
        if path == WHOLE:
            hit = value is not None
        else:
            hit = bool(_values_at(value, path.split('.')))
        if hit:
            for c in classes:
                if c not in out:
                    out.append(c)
    return out


def necessary_classes(input_schema: Any, tool_level: Iterable[str] = (), extra_marks: Optional[Marks] = None) -> List[str]:
    """The classes every call of a tool sends: tool-level argument classes and the classes of required
    top-level properties (a call can leave an optional field out)."""
    out = [c for c in tool_level if c]
    marks = merge_marks(schema_marks(input_schema), extra_marks)
    required = set((input_schema or {}).get('required') or []) if isinstance(input_schema, dict) else set()
    for path, classes in marks.items():
        if path == WHOLE or path.split('.')[0] in required:
            for c in classes:
                if c not in out:
                    out.append(c)
    return out


def matches_class(cls: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(cls, p) for p in patterns)


def placeholder(cls: str) -> str:
    return f'[REDACTED:{cls}]'


def redact_fields(value: Any, marks: Marks, classes: Iterable[str]) -> Tuple[Any, List[str], List[Any]]:
    """(copy of ``value`` with the fields of ``classes`` replaced, paths touched, values removed).

    ``classes`` may hold glob patterns. A ``*`` mark of a listed class cannot be redacted field by
    field; the caller sees it in the returned paths as ``*`` and decides (SAJHA refuses)."""
    pats = list(classes)
    out = copy.deepcopy(value)
    touched: List[str] = []
    removed: List[Any] = []
    for path, cls in sorted(marks.items()):
        hit = next((c for c in cls if matches_class(c, pats)), None)
        if hit is None:
            continue
        if path == WHOLE:
            if value is not None:
                touched.append(WHOLE)
            continue
        if _replace(out, path.split('.'), placeholder(hit), removed):
            touched.append(path)
    return out, touched, removed


def _replace(value: Any, parts: List[str], text: str, removed: List[Any]) -> bool:
    head, rest = parts[0], parts[1:]
    if head == ITEMS:
        if not isinstance(value, list):
            return False
        hit = False
        for i, item in enumerate(value):
            if not rest:
                removed.append(item)
                value[i] = text
                hit = True
            elif _replace(item, rest, text, removed):
                hit = True
        return hit
    if not isinstance(value, dict) or head not in value:
        return False
    if not rest:
        removed.append(value[head])
        value[head] = text
        return True
    return _replace(value[head], rest, text, removed)


def _scalars(values: List[Any]) -> List[str]:
    out: List[str] = []

    def add(v: Any, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            return
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            if len(json.dumps(v)) >= 3:
                out.append(json.dumps(v))
        elif isinstance(v, str):
            if len(v) >= 3:
                out.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                add(x, depth + 1)
        elif isinstance(v, list):
            for x in v:
                add(x, depth + 1)
    for v in values:
        add(v)
    return sorted(set(out), key=len, reverse=True)


def redact_result(result: Dict[str, Any], marks: Marks, classes: Iterable[str]) -> Tuple[Dict[str, Any], List[str]]:
    """A ``CallToolResult`` with the fields of ``classes`` replaced (see the module docstring)."""
    pats = list(classes)
    out = dict(result or {})
    touched: List[str] = []
    removed: List[Any] = []
    if isinstance(out.get('structuredContent'), (dict, list)):
        out['structuredContent'], t, r = redact_fields(out['structuredContent'], marks, pats)
        touched += t
        removed += r
    blocks = []
    for b in out.get('content') or []:
        if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str):
            text = b['text']
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                red, t, r = redact_fields(parsed, marks, pats)
                if t:
                    touched += [p for p in t if p not in touched]
                    removed += r
                    b = dict(b, text=json.dumps(red, indent=2, ensure_ascii=False))
            blocks.append(b)
        else:
            blocks.append(b)
    hidden = _scalars(removed)
    if hidden:
        hit = next((c for cls in marks.values() for c in cls if matches_class(c, pats)), 'data')
        for i, b in enumerate(blocks):
            if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str):
                text = b['text']
                for s in hidden:
                    text = text.replace(s, placeholder(hit))
                blocks[i] = dict(b, text=text)
    if 'content' in out:
        out['content'] = blocks
    return out, sorted(set(touched))
