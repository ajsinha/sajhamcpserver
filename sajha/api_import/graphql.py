"""
SAJHA MCP Server — API Import: GraphQL introspection → operations.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One operation per field of the query type and of the mutation type. Arguments become
the variables schema (JSON Schema 2020-12); the selection set is generated to a depth
limit (``api_import.graphql_depth``): scalar and enum fields, object fields that need no
required arguments (recursively), and ``__typename`` plus inline fragments for unions.
The operation dicts share the OpenAPI shape (sajha/api_import/openapi.py) so the service
treats both alike; a GraphQL one carries ``graphql: {document, field, operation_type}``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sajha.api_import import naming

INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types { ...FullType }
  }
}
fragment FullType on __Type {
  kind name description
  fields(includeDeprecated: true) {
    name description isDeprecated deprecationReason
    args { ...InputValue }
    type { ...TypeRef }
  }
  inputFields { ...InputValue }
  interfaces { ...TypeRef }
  enumValues(includeDeprecated: true) { name description isDeprecated }
  possibleTypes { ...TypeRef }
}
fragment InputValue on __InputValue { name description type { ...TypeRef } defaultValue }
fragment TypeRef on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name
    ofType { kind name ofType { kind name ofType { kind name } } } } } } }
}
"""

_SCALARS = {'Int': {'type': 'integer'}, 'Float': {'type': 'number'}, 'String': {'type': 'string'},
            'ID': {'type': 'string'}, 'Boolean': {'type': 'boolean'}}
INPUT_DEPTH = 5


class GraphQLSchemaError(ValueError):
    pass


def schema_from(data: Any) -> Dict[str, Any]:
    """The ``__schema`` object from an introspection result (with or without ``data``)."""
    if isinstance(data, dict) and isinstance(data.get('data'), dict):
        data = data['data']
    if not isinstance(data, dict) or not isinstance(data.get('__schema'), dict):
        raise GraphQLSchemaError('not a GraphQL introspection result (no __schema)')
    return data['__schema']


def _unwrap(t: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, int]:
    """(named type, outer NON_NULL, list depth)."""
    non_null = bool(t) and t.get('kind') == 'NON_NULL'
    lists = 0
    while t and t.get('kind') in ('NON_NULL', 'LIST'):
        if t['kind'] == 'LIST':
            lists += 1
        t = t.get('ofType') or {}
    return t or {}, non_null, lists


def type_literal(t: Dict[str, Any]) -> str:
    if not t:
        return 'String'
    if t.get('kind') == 'NON_NULL':
        return type_literal(t.get('ofType') or {}) + '!'
    if t.get('kind') == 'LIST':
        return '[' + type_literal(t.get('ofType') or {}) + ']'
    return str(t.get('name') or 'String')


class GraphQLDocument:
    def __init__(self, introspection: Any, depth: int = 2):
        self.schema = schema_from(introspection)
        self.types = {t['name']: t for t in self.schema.get('types') or [] if isinstance(t, dict) and t.get('name')}
        self.depth = depth

    def info(self) -> Dict[str, Any]:
        return {'kind': 'graphql', 'title': 'GraphQL API', 'version': '', 'description': '',
                'spec_version': 'graphql introspection', 'servers': [], 'security_schemes': {},
                'security': None, 'tags': ['query', 'mutation']}

    # ── JSON Schema ────────────────────────────────────────────────
    def _input_schema(self, t: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
        if not t:
            return {}
        if t.get('kind') == 'NON_NULL':
            return self._input_schema(t.get('ofType') or {}, depth)
        if t.get('kind') == 'LIST':
            return {'type': 'array', 'items': self._input_schema(t.get('ofType') or {}, depth)}
        named = self.types.get(t.get('name')) or t
        kind = named.get('kind')
        if kind == 'SCALAR':
            return dict(_SCALARS.get(named.get('name'), {'description': f"{named.get('name')} scalar"}))
        if kind == 'ENUM':
            return {'type': 'string', 'enum': [v['name'] for v in named.get('enumValues') or []]}
        if kind == 'INPUT_OBJECT':
            if depth >= INPUT_DEPTH:
                return {'type': 'object'}
            props, required = {}, []
            for f in named.get('inputFields') or []:
                s = self._input_schema(f.get('type') or {}, depth + 1)
                if f.get('description'):
                    s = {**s, 'description': _screen(f['description'])}
                props[f['name']] = s
                if (f.get('type') or {}).get('kind') == 'NON_NULL' and f.get('defaultValue') is None:
                    required.append(f['name'])
            out = {'type': 'object', 'properties': props, 'additionalProperties': False}
            if required:
                out['required'] = required
            return out
        return {}

    def _output_schema(self, t: Dict[str, Any], depth: int) -> Dict[str, Any]:
        named, non_null, lists = _unwrap(t)
        named = self.types.get(named.get('name')) or named
        kind = named.get('kind')
        if kind == 'SCALAR':
            s = dict(_SCALARS.get(named.get('name'), {}))
        elif kind == 'ENUM':
            s = {'type': 'string'}
        elif kind in ('OBJECT', 'INTERFACE') and depth > 0:
            props = {}
            for f in named.get('fields') or []:
                if self._needs_args(f):
                    continue
                inner, _, _ = _unwrap(f.get('type') or {})
                inner_kind = (self.types.get(inner.get('name')) or inner).get('kind')
                if inner_kind in ('SCALAR', 'ENUM') or depth > 1:
                    props[f['name']] = self._output_schema(f.get('type') or {}, depth - 1)
            s = {'type': 'object', 'properties': props}
        else:
            s = {'type': 'object'}
        for _ in range(lists):
            s = {'type': 'array', 'items': s}
        if not non_null and s.get('type') and isinstance(s['type'], str):
            s = {**s, 'type': [s['type'], 'null']}
        return s

    # ── selection sets ─────────────────────────────────────────────
    @staticmethod
    def _needs_args(field: Dict[str, Any]) -> bool:
        return any((a.get('type') or {}).get('kind') == 'NON_NULL' and a.get('defaultValue') is None
                   for a in field.get('args') or [])

    def selection(self, type_name: str, depth: int, _seen: Tuple[str, ...] = ()) -> str:
        named = self.types.get(type_name) or {}
        kind = named.get('kind')
        if kind == 'UNION':
            parts = ['__typename']
            if depth > 0:
                for pt in named.get('possibleTypes') or []:
                    sub = self.selection(pt.get('name'), depth - 1, _seen)
                    if sub and sub != '__typename':
                        parts.append(f"... on {pt.get('name')} {{ {sub} }}")
            return ' '.join(parts)
        if kind not in ('OBJECT', 'INTERFACE'):
            return ''
        parts = []
        for f in named.get('fields') or []:
            if self._needs_args(f):
                continue
            inner, _, _ = _unwrap(f.get('type') or {})
            inner_named = self.types.get(inner.get('name')) or inner
            ik = inner_named.get('kind')
            if ik in ('SCALAR', 'ENUM'):
                parts.append(f['name'])
            elif ik in ('OBJECT', 'INTERFACE', 'UNION') and depth > 1 and inner.get('name') not in _seen:
                sub = self.selection(inner.get('name'), depth - 1, _seen + (type_name,))
                if sub:
                    parts.append(f"{f['name']} {{ {sub} }}")
        return ' '.join(parts) or '__typename'

    # ── operations ─────────────────────────────────────────────────
    def operations(self) -> List[Dict[str, Any]]:
        out = []
        for op_type, key in (('query', 'queryType'), ('mutation', 'mutationType')):
            root_name = (self.schema.get(key) or {}).get('name')
            root = self.types.get(root_name) if root_name else None
            if not root:
                continue
            for f in root.get('fields') or []:
                if not f.get('name') or f['name'].startswith('__'):
                    continue
                out.append(self._operation(op_type, f))
        return out

    def _operation(self, op_type: str, field: Dict[str, Any]) -> Dict[str, Any]:
        name = field['name']
        params, var_defs, call_args = [], [], []
        for a in field.get('args') or []:
            t = a.get('type') or {}
            schema = self._input_schema(t)
            if a.get('description'):
                schema = {**schema, 'description': _screen(a['description'])}
            required = t.get('kind') == 'NON_NULL' and a.get('defaultValue') is None
            params.append({'arg': naming.arg_name(a['name']), 'name': a['name'], 'in': 'variable',
                           'required': required, 'schema': schema, 'style': '', 'explode': False,
                           'description': schema.get('description', '')})
            var_defs.append(f"${a['name']}: {type_literal(t)}")
            call_args.append(f"{a['name']}: ${a['name']}")
        inner, _, _ = _unwrap(field.get('type') or {})
        sub = self.selection(inner.get('name'), self.depth)
        op_name = ''.join(w.capitalize() for w in naming.snake(name).split('_')) or 'Op'
        head = f"{op_type} {op_name}" + (f"({', '.join(var_defs)})" if var_defs else '')
        call = name + (f"({', '.join(call_args)})" if call_args else '')
        document = f"{head} {{ {call}" + (f" {{ {sub} }}" if sub else '') + ' }'
        description = _screen(field.get('description') or '')
        return {
            'key': f'{op_type} {name}', 'operation_id': name, 'method': 'POST', 'path': '',
            'summary': (description.split('\n')[0][:200] if description else f'GraphQL {op_type} {name}'),
            'description': description, 'tags': [op_type], 'deprecated': bool(field.get('isDeprecated')),
            'params': params, 'body': None,
            'response_schema': self._output_schema(field.get('type') or {}, self.depth),
            'response_content_type': 'application/json', 'security': None, 'servers': [],
            'pagination': [], 'unsupported': None, 'flagged': False,
            'base_name': naming.snake(name) or 'op',
            'graphql': {'document': document, 'field': name, 'operation_type': op_type,
                        'operation_name': op_name},
        }


def _screen(text: Any) -> str:
    from sajha.federation.security import screen_text
    return screen_text(text, 1024)[0]
