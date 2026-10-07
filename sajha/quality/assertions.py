"""
SAJHA MCP Server — the assertion language of tool test cases.

One assertion is a dict (docs/architecture/Tool Quality.md, section 2.2):

    {schema: output | {...}}                         the result validates (JSON Schema 2020-12)
    {path: <jsonpath>, exists | equals | not_equals | contains | regex | type | min | max |
                       length | min_length | max_length, tolerance?}
    {latency_ms: n}                                  the call took at most n ms

``check(spec, result, latency_ms, output_schema)`` returns an :class:`Outcome`; it never raises
for a failing assertion, only for a malformed one (:class:`AssertionSpecError`).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sajha.quality import jsonpath

PATH_OPS = ('exists', 'equals', 'not_equals', 'contains', 'regex', 'type', 'min', 'max',
            'length', 'min_length', 'max_length')
_TYPES = {'string': str, 'boolean': bool, 'object': dict, 'array': list}


class AssertionSpecError(ValueError):
    """An assertion that is not in the language."""


@dataclass
class Outcome:
    ok: bool
    assertion: str
    message: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {'ok': self.ok, 'assertion': self.assertion, 'message': self.message}


def describe(spec: Dict[str, Any]) -> str:
    try:
        return json.dumps(spec, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(spec)


def validate_spec(spec: Any) -> None:
    """Raise AssertionSpecError when ``spec`` is not a valid assertion."""
    if not isinstance(spec, dict) or not spec:
        raise AssertionSpecError(f'an assertion must be a non-empty object, got {spec!r}')
    if 'schema' in spec:
        s = spec['schema']
        if s != 'output' and not isinstance(s, dict):
            raise AssertionSpecError('schema must be "output" or a JSON Schema object')
        if isinstance(s, dict):
            from jsonschema import Draft202012Validator
            from jsonschema.exceptions import SchemaError
            try:
                Draft202012Validator.check_schema(s)
            except SchemaError as e:
                raise AssertionSpecError(f'schema is not valid JSON Schema 2020-12: {e.message}') from e
        return
    if 'latency_ms' in spec:
        if not isinstance(spec['latency_ms'], (int, float)) or isinstance(spec['latency_ms'], bool):
            raise AssertionSpecError('latency_ms must be a number')
        return
    if 'path' not in spec:
        raise AssertionSpecError(f'an assertion needs schema, latency_ms or path: {describe(spec)}')
    jsonpath.parse(str(spec['path']))
    ops = [k for k in PATH_OPS if k in spec]
    if not ops:
        raise AssertionSpecError(f'a path assertion needs one of {", ".join(PATH_OPS)}: {describe(spec)}')
    unknown = set(spec) - set(PATH_OPS) - {'path', 'tolerance'}
    if unknown:
        raise AssertionSpecError(f'unknown keys {sorted(unknown)} in {describe(spec)}')
    if 'regex' in spec:
        try:
            re.compile(str(spec['regex']))
        except re.error as e:
            raise AssertionSpecError(f'bad regex {spec["regex"]!r}: {e}') from e
    if 'type' in spec and spec['type'] not in ('string', 'number', 'integer', 'boolean', 'object', 'array', 'null'):
        raise AssertionSpecError(f'unknown type {spec["type"]!r}')


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def values_equal(a: Any, b: Any, tolerance: Optional[float] = None) -> bool:
    """Deep equality; numbers compare within ``tolerance`` (absolute) when it is given."""
    if _is_number(a) and _is_number(b):
        if tolerance is not None:
            return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=float(tolerance))
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(values_equal(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(values_equal(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def contains(haystack: Any, needle: Any, tolerance: Optional[float] = None) -> bool:
    if isinstance(haystack, str):
        return str(needle) in haystack
    if isinstance(haystack, list):
        return any(values_equal(x, needle, tolerance) or (isinstance(needle, dict) and isinstance(x, dict)
                                                          and contains(x, needle, tolerance))
                   for x in haystack)
    if isinstance(haystack, dict):
        if isinstance(needle, dict):
            return all(k in haystack and (values_equal(haystack[k], v, tolerance) or contains(haystack[k], v, tolerance)
                                          if isinstance(v, (dict, list)) else values_equal(haystack[k], v, tolerance))
                       for k, v in needle.items())
        return needle in haystack
    return values_equal(haystack, needle, tolerance)


def _type_ok(v: Any, t: str) -> bool:
    if t == 'null':
        return v is None
    if t == 'number':
        return _is_number(v)
    if t == 'integer':
        return _is_number(v) and float(v).is_integer()
    return isinstance(v, _TYPES[t]) and not (t != 'boolean' and isinstance(v, bool))


def _short(v: Any, n: int = 160) -> str:
    try:
        s = json.dumps(v, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(v)
    return s if len(s) <= n else s[:n] + '...'


def normalise_result(result: Any) -> Any:
    """A tool's return value as JSON: a JSON string is parsed, other values round-trip through json."""
    if isinstance(result, (bytes, bytearray)):
        result = result.decode('utf-8', 'replace')
    if isinstance(result, str):
        t = result.strip()
        if t[:1] in ('{', '[') or t in ('true', 'false', 'null'):
            try:
                return json.loads(t)
            except ValueError:
                return result
        return result
    try:
        return json.loads(json.dumps(result, default=str))
    except (TypeError, ValueError):
        return result


def check(spec: Dict[str, Any], result: Any, latency_ms: float = 0.0,
          output_schema: Optional[Dict[str, Any]] = None) -> Outcome:
    validate_spec(spec)
    label = describe(spec)
    if 'schema' in spec:
        schema = output_schema if spec['schema'] == 'output' else spec['schema']
        if not isinstance(schema, dict) or not schema:
            return Outcome(False, label, 'the tool has no outputSchema to validate against')
        from jsonschema import Draft202012Validator
        errors = sorted(Draft202012Validator(schema).iter_errors(result), key=lambda e: list(e.absolute_path))
        if errors:
            e = errors[0]
            where = '/'.join(str(p) for p in e.absolute_path) or '(root)'
            more = f' (+{len(errors) - 1} more)' if len(errors) > 1 else ''
            return Outcome(False, label, f'schema: at {where}: {e.message}{more}')
        return Outcome(True, label)
    if 'latency_ms' in spec:
        budget = float(spec['latency_ms'])
        if latency_ms > budget:
            return Outcome(False, label, f'took {latency_ms:.0f} ms, budget {budget:.0f} ms')
        return Outcome(True, label)

    path = str(spec['path'])
    found = jsonpath.find(result, path)
    tol = spec.get('tolerance')
    tol = float(tol) if tol is not None else None
    value = found[0] if len(found) == 1 else found
    fails: List[str] = []
    if 'exists' in spec:
        if bool(found) != bool(spec['exists']):
            fails.append(f'{path} {"matched nothing" if not found else "matched " + _short(value)}')
    if not found and any(k in spec for k in PATH_OPS if k != 'exists'):
        return Outcome(False, label, f'{path} matched nothing')
    if 'equals' in spec and not values_equal(value, spec['equals'], tol):
        fails.append(f'{path} is {_short(value)}, expected {_short(spec["equals"])}'
                     + (f' (tolerance {tol})' if tol is not None else ''))
    if 'not_equals' in spec and values_equal(value, spec['not_equals'], tol):
        fails.append(f'{path} is {_short(value)}, expected anything else')
    if 'contains' in spec and not contains(value, spec['contains'], tol):
        fails.append(f'{path} ({_short(value)}) does not contain {_short(spec["contains"])}')
    if 'regex' in spec:
        rx = re.compile(str(spec['regex']))
        bad = [v for v in found if not rx.search(v if isinstance(v, str) else _short(v, 10_000))]
        if bad:
            fails.append(f'{path}: {_short(bad[0])} does not match /{spec["regex"]}/')
    if 'type' in spec:
        bad = [v for v in found if not _type_ok(v, spec['type'])]
        if bad:
            fails.append(f'{path}: {_short(bad[0])} is not {spec["type"]}')
    for op, cmp_ in (('min', lambda v, b: v >= b), ('max', lambda v, b: v <= b)):
        if op in spec:
            bound = float(spec[op])
            bad = [v for v in found if not _is_number(v) or not cmp_(float(v), bound)]
            if bad:
                fails.append(f'{path}: {_short(bad[0])} is not {">=" if op == "min" else "<="} {bound:g}')
    for op in ('length', 'min_length', 'max_length'):
        if op in spec:
            target = value
            try:
                n = len(target)
            except TypeError:
                fails.append(f'{path}: {_short(target)} has no length')
                continue
            want = int(spec[op])
            if (op == 'length' and n != want) or (op == 'min_length' and n < want) or (op == 'max_length' and n > want):
                fails.append(f'{path}: length {n}, {op.replace("_", " ")} {want}')
    if fails:
        return Outcome(False, label, '; '.join(fails))
    return Outcome(True, label)
