"""
SAJHA MCP Server — API Import: OpenAPI schema objects → JSON Schema 2020-12.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

OpenAPI 3.1 schemas are JSON Schema 2020-12 already; 3.0 (and converted Swagger 2.0)
schemas differ in a few keywords: ``nullable``, boolean ``exclusiveMinimum`` /
``exclusiveMaximum``, ``example``, and Swagger's ``type: file``. OpenAPI-only keywords
(``discriminator``, ``xml``, ``externalDocs``) and ``x-*`` extensions are dropped. In an
input schema ``readOnly`` properties are removed (the server sets them), in an output
schema ``writeOnly`` ones. Input is expected to be $ref-free (refs.RefResolver.deref).
"""

from __future__ import annotations

from typing import Any, Dict

_DROP = {'discriminator', 'xml', 'externalDocs', 'nullable', 'example', 'x-nullable'}
_SUBSCHEMA_MAPS = ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas')
_SUBSCHEMA_LISTS = ('allOf', 'anyOf', 'oneOf', 'prefixItems')
_SUBSCHEMA_ONE = ('items', 'additionalProperties', 'not', 'contains', 'propertyNames', 'if', 'then',
                  'else', 'unevaluatedProperties', 'unevaluatedItems', 'additionalItems')
MAX_DEPTH = 40


def to_json_schema(schema: Any, openapi_31: bool = False, mode: str = 'input', _depth: int = 0) -> Any:
    """``mode``: 'input' (drop readOnly properties) or 'output' (drop writeOnly ones)."""
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, dict):
        return {}
    if _depth > MAX_DEPTH:
        return {}
    out: Dict[str, Any] = {}
    for key, value in schema.items():
        if key in _DROP or (isinstance(key, str) and key.startswith('x-')):
            continue
        out[key] = value

    if not openapi_31:
        # 3.0: boolean exclusive bounds modify minimum/maximum
        for flag, bound in (('exclusiveMinimum', 'minimum'), ('exclusiveMaximum', 'maximum')):
            if isinstance(out.get(flag), bool):
                if out[flag] and bound in out:
                    out[flag] = out.pop(bound)
                else:
                    out.pop(flag)
        if schema.get('nullable') is True or schema.get('x-nullable') is True:
            t = out.get('type')
            if isinstance(t, str):
                out['type'] = [t, 'null']
            elif isinstance(t, list) and 'null' not in t:
                out['type'] = t + ['null']
            if isinstance(out.get('enum'), list) and None not in out['enum']:
                out['enum'] = out['enum'] + [None]
    if 'example' in schema and 'examples' not in out:
        out['examples'] = [schema['example']]
    elif isinstance(out.get('examples'), dict):        # an OpenAPI examples map is not JSON Schema
        out['examples'] = [v.get('value') for v in out['examples'].values() if isinstance(v, dict)]
    if out.get('type') == 'file':
        out['type'] = 'string'
        out.setdefault('format', 'binary')

    for key in _SUBSCHEMA_MAPS:
        if isinstance(out.get(key), dict):
            out[key] = {k: to_json_schema(v, openapi_31, mode, _depth + 1) for k, v in out[key].items()}
    for key in _SUBSCHEMA_LISTS:
        if isinstance(out.get(key), list):
            out[key] = [to_json_schema(v, openapi_31, mode, _depth + 1) for v in out[key]]
    for key in _SUBSCHEMA_ONE:
        if key in out and isinstance(out[key], (dict, bool)):
            out[key] = to_json_schema(out[key], openapi_31, mode, _depth + 1)
    if isinstance(out.get('items'), list):              # tuple form is not 2020-12
        out['prefixItems'] = [to_json_schema(v, openapi_31, mode, _depth + 1) for v in out.pop('items')]

    props = out.get('properties')
    if isinstance(props, dict):
        hidden = 'readOnly' if mode == 'input' else 'writeOnly'
        drop = [k for k, v in props.items() if isinstance(v, dict) and v.get(hidden) is True]
        for k in drop:
            props.pop(k)
        if drop and isinstance(out.get('required'), list):
            out['required'] = [r for r in out['required'] if r not in drop]
    if isinstance(out.get('required'), list) and not out['required']:
        out.pop('required')
    return out


def limit_depth(schema: Any, max_depth: int = 8, _depth: int = 0) -> Any:
    """Cut a schema to ``max_depth`` levels of nesting (deeper parts become ``{}``)."""
    if not isinstance(schema, dict):
        return schema
    if _depth >= max_depth:
        return {k: v for k, v in schema.items() if k in ('type', 'description', 'title')
                and not isinstance(v, (dict, list))} or {}
    out = {}
    for k, v in schema.items():
        if k in _SUBSCHEMA_MAPS and isinstance(v, dict):
            out[k] = {pk: limit_depth(pv, max_depth, _depth + 1) for pk, pv in v.items()}
        elif k in _SUBSCHEMA_LISTS and isinstance(v, list):
            out[k] = [limit_depth(x, max_depth, _depth + 1) for x in v]
        elif k in _SUBSCHEMA_ONE and isinstance(v, dict):
            out[k] = limit_depth(v, max_depth, _depth + 1)
        else:
            out[k] = v
    return out


def is_valid_schema(schema: Any) -> bool:
    try:
        import jsonschema
        jsonschema.Draft202012Validator.check_schema(schema)
        return True
    except Exception:
        return False
