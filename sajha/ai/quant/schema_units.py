"""
SAJHA MCP Server — units declared in a tool's ``outputSchema`` (Quantitative Planners §2.2).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A tool declares the unit of a result field with the keyword ``x-sajha-unit`` on that property of
its ``outputSchema``, written in the unit grammar of §2.2::

    "rate":  {"type": "number", "x-sajha-unit": "percent"}
    "sales": {"type": "number", "x-sajha-unit": "USD mn"}
    "value": {"type": "string", "x-sajha-unit": "percent"}     # a number sent as text (FRED)

JSON Schema validation ignores the keyword (an ``x-`` keyword is an annotation). The workspace
reads it: when a planner reads a value from a tool result at a JSONPath, :func:`schema_unit` finds
the property that path selects and returns its unit, and the quantity records
``unit_from: "schema"`` instead of the model's declaration. Lint checks every declaration
(:func:`schema_unit_marks`, rule ``unit``; Tool Quality §3).

The keyword applies to the property it is on, to the items of an array it is on, and through
``allOf``/``anyOf``/``oneOf`` and local ``$ref``s. When a path could select properties that declare
different units (a wildcard over several fields, a recursive ``..name``), no unit is returned: the
planner's declaration stands.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

KEYWORD = "x-sajha-unit"
MAX_DEPTH = 40


def _deref(node: Any, root: Dict[str, Any], depth: int = 0) -> Any:
    """``node`` with a local ``$ref`` (``#/$defs/x``, ``#/definitions/x``) followed."""
    while isinstance(node, dict) and isinstance(node.get("$ref"), str) and depth < 10:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return node
        target: Any = root
        for part in ref[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
        depth += 1
    return node


def _alternatives(node: Any, root: Dict[str, Any], depth: int = 0) -> List[Dict[str, Any]]:
    """``node`` and every schema an ``allOf``/``anyOf``/``oneOf`` of it may apply."""
    node = _deref(node, root)
    if not isinstance(node, dict) or depth > 8:
        return []
    out = [node]
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in node.get(key) or [] if isinstance(node.get(key), list) else []:
            out.extend(_alternatives(sub, root, depth + 1))
    return out


def _children(node: Dict[str, Any], key: Optional[str], root: Dict[str, Any]) -> List[Any]:
    """The subschemas a step selects: a property by name (``key``), or every child (``key`` None)."""
    out: List[Any] = []
    for alt in _alternatives(node, root):
        props = alt.get("properties") if isinstance(alt.get("properties"), dict) else {}
        if key is None:
            out.extend(props.values())
            if isinstance(alt.get("items"), dict):
                out.append(alt["items"])
            for sub in alt.get("prefixItems") or [] if isinstance(alt.get("prefixItems"), list) else []:
                out.append(sub)
        elif key in props:
            out.append(props[key])
        if isinstance(alt.get("additionalProperties"), dict) and (key is None or key not in props):
            out.append(alt["additionalProperties"])
        if isinstance(alt.get("patternProperties"), dict) and key is not None and key not in props:
            import re
            for pat, sub in alt["patternProperties"].items():
                try:
                    if re.search(pat, key):
                        out.append(sub)
                except re.error:
                    continue
    return out


def _items(node: Dict[str, Any], index: Optional[int], root: Dict[str, Any]) -> List[Any]:
    out: List[Any] = []
    for alt in _alternatives(node, root):
        prefix = alt.get("prefixItems") if isinstance(alt.get("prefixItems"), list) else []
        if index is not None and 0 <= index < len(prefix):
            out.append(prefix[index])
        elif isinstance(alt.get("items"), dict):
            out.append(alt["items"])
    return out


def _deep(node: Any, name: Optional[str], root: Dict[str, Any], depth: int = 0) -> List[Any]:
    """Every subschema under ``node`` that ``..name`` (or ``..*``) may select."""
    if depth > MAX_DEPTH:
        return []
    out: List[Any] = []
    for alt in _alternatives(node, root):
        props = alt.get("properties") if isinstance(alt.get("properties"), dict) else {}
        for k, sub in props.items():
            if name is None or k == name:
                out.append(sub)
            out.extend(_deep(sub, name, root, depth + 1))
        if isinstance(alt.get("items"), dict):
            if name is None:
                out.append(alt["items"])
            out.extend(_deep(alt["items"], name, root, depth + 1))
    return out


def _declared(node: Any, root: Dict[str, Any]) -> Set[str]:
    """The units ``node`` declares: its own keyword, or (an array) its items' keyword."""
    units: Set[str] = set()
    for alt in _alternatives(node, root):
        if isinstance(alt.get(KEYWORD), str) and alt[KEYWORD].strip():
            units.add(alt[KEYWORD].strip())
    if not units:
        for alt in _alternatives(node, root):
            items = _deref(alt.get("items"), root)
            if isinstance(items, dict):
                units |= _declared(items, root)
    return units


def schema_unit(schema: Any, path: str) -> Optional[str]:
    """The unit ``schema`` declares (``x-sajha-unit``) for the value a JSONPath ``path`` selects, or
    None (no declaration, a path the schema does not describe, or declarations that disagree). The
    unit is returned as written; :func:`sajha.ai.quant.parse_unit` parses it."""
    if not isinstance(schema, dict) or not isinstance(path, str) or not path.strip():
        return None
    from sajha.quality.jsonpath import JSONPathError, parse
    try:
        steps = parse(path)
    except JSONPathError:
        return None
    nodes: List[Any] = [schema]
    for kind, arg in steps:
        nxt: List[Any] = []
        for n in nodes:
            n = _deref(n, schema)
            if not isinstance(n, dict):
                continue
            if kind == "key":
                nxt.extend(_children(n, str(arg), schema))
            elif kind == "index":
                nxt.extend(_items(n, int(arg), schema))
            elif kind == "wild":
                nxt.extend(_children(n, None, schema))
            elif kind == "deep":
                nxt.extend(_deep(n, arg, schema))
        nodes = nxt[:200]
        if not nodes:
            return None
    units: Set[str] = set()
    for n in nodes:
        found = _declared(n, schema)
        if not found:
            return None             # one of the selected fields declares nothing: no certainty
        units |= found
    if len(units) != 1:
        return None
    from sajha.ai.quant.errors import UnitError
    from sajha.ai.quant.units import parse_unit
    unit = units.pop()
    try:
        parse_unit(unit)
    except UnitError:
        return None                 # lint reports it; an unknown unit never reaches the workspace
    return unit


def schema_unit_marks(schema: Any) -> Iterator[Tuple[str, Any, Dict[str, Any]]]:
    """``(location, value, subschema)`` for every ``x-sajha-unit`` in ``schema`` (for lint and docs)."""
    seen: Set[int] = set()

    def walk(node: Any, where: str, depth: int) -> Iterator[Tuple[str, Any, Dict[str, Any]]]:
        if not isinstance(node, dict) or depth > MAX_DEPTH or id(node) in seen:
            return
        seen.add(id(node))
        if KEYWORD in node:
            yield where or "(root)", node[KEYWORD], node
        for key in ("properties", "$defs", "definitions", "patternProperties"):
            sub = node.get(key)
            if isinstance(sub, dict):
                for name, s in sub.items():
                    yield from walk(s, f"{where}/{key}/{name}" if where else f"{key}/{name}", depth + 1)
        for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains"):
            if isinstance(node.get(key), dict):
                yield from walk(node[key], f"{where}/{key}" if where else key, depth + 1)
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            if isinstance(node.get(key), list):
                for i, s in enumerate(node[key]):
                    yield from walk(s, f"{where}/{key}/{i}" if where else f"{key}/{i}", depth + 1)
    yield from walk(schema, "", 0)


def unit_problem(value: Any, subschema: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """``(error, warning)`` for one ``x-sajha-unit`` declaration: an error when it is not a unit of
    §2.2, a warning when it sits on a property that cannot hold a number."""
    from sajha.ai.quant.errors import UnitError
    from sajha.ai.quant.units import parse_unit
    if not isinstance(value, str) or not value.strip():
        return f"{KEYWORD} must be a unit such as 'percent', 'bp', 'USD mn' or 'count', not {value!r}", None
    try:
        parse_unit(value)
    except UnitError as e:
        return str(e), None
    types = subschema.get("type")
    types = [types] if isinstance(types, str) else list(types or []) if isinstance(types, list) else []
    if types and not set(types) & {"number", "integer", "string", "array"}:
        return None, f"{KEYWORD} {value!r} is on a property of type {'/'.join(types)}, which holds no number"
    return None, None
