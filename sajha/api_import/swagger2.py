"""
SAJHA MCP Server — API Import: Swagger 2.0 → OpenAPI 3.0.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Converts the parts API Import reads: servers (host, basePath, schemes), schemas
(``definitions`` → ``components/schemas``, every ``$ref`` rewritten), parameters
(``in: body`` and ``in: formData`` → ``requestBody``; ``collectionFormat`` → style and
explode), responses (``schema`` → ``content`` per ``produces`` type) and security
definitions. Shared ``#/parameters/...`` and ``#/responses/...`` are inlined.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

_METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch')
_PARAM_SCHEMA_KEYS = ('type', 'format', 'items', 'enum', 'default', 'minimum', 'maximum',
                      'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength', 'pattern',
                      'minItems', 'maxItems', 'uniqueItems', 'multipleOf', 'x-nullable')
_COLLECTION = {
    'csv': ('form', False), 'ssv': ('spaceDelimited', False), 'tsv': ('form', False),
    'pipes': ('pipeDelimited', False), 'multi': ('form', True),
}


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == '$ref' and isinstance(v, str):
            v = v.replace('#/definitions/', '#/components/schemas/')
        out[k] = _rewrite_refs(v)
    return out


def _inline(doc: Dict[str, Any], node: Any, section: str) -> Any:
    if isinstance(node, dict) and isinstance(node.get('$ref'), str) and \
            node['$ref'].startswith(f'#/{section}/'):
        name = node['$ref'][len(f'#/{section}/'):].replace('~1', '/').replace('~0', '~')
        return copy.deepcopy((doc.get(section) or {}).get(name) or {})
    return node


def _param_schema(p: Dict[str, Any]) -> Dict[str, Any]:
    schema = {k: copy.deepcopy(p[k]) for k in _PARAM_SCHEMA_KEYS if k in p}
    items = schema.get('items')
    if isinstance(items, dict):
        items.pop('collectionFormat', None)
    return schema


def _servers(doc: Dict[str, Any], source_url: Optional[str]) -> List[Dict[str, Any]]:
    src = urlsplit(source_url or '')
    host = doc.get('host') or src.netloc
    base_path = doc.get('basePath') or ''
    schemes = doc.get('schemes') or ([src.scheme] if src.scheme in ('http', 'https') else ['https'])
    if not host:
        return [{'url': base_path or '/'}]
    return [{'url': f'{s}://{host}{base_path}'} for s in schemes if s in ('http', 'https')]


def _security_schemes(defs: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for name, d in (defs or {}).items():
        if not isinstance(d, dict):
            continue
        t = d.get('type')
        if t == 'basic':
            out[name] = {'type': 'http', 'scheme': 'basic', 'description': d.get('description', '')}
        elif t == 'apiKey':
            out[name] = {'type': 'apiKey', 'in': d.get('in', 'header'), 'name': d.get('name', ''),
                         'description': d.get('description', '')}
        elif t == 'oauth2':
            flow = d.get('flow')
            scopes = d.get('scopes') or {}
            if flow == 'application':
                flows = {'clientCredentials': {'tokenUrl': d.get('tokenUrl', ''), 'scopes': scopes}}
            elif flow == 'accessCode':
                flows = {'authorizationCode': {'authorizationUrl': d.get('authorizationUrl', ''),
                                               'tokenUrl': d.get('tokenUrl', ''), 'scopes': scopes}}
            elif flow == 'password':
                flows = {'password': {'tokenUrl': d.get('tokenUrl', ''), 'scopes': scopes}}
            else:
                flows = {'implicit': {'authorizationUrl': d.get('authorizationUrl', ''), 'scopes': scopes}}
            out[name] = {'type': 'oauth2', 'flows': flows, 'description': d.get('description', '')}
    return out


def _operation(doc: Dict[str, Any], op: Dict[str, Any], path_params: List[Any]) -> Dict[str, Any]:
    consumes = op.get('consumes') or doc.get('consumes') or ['application/json']
    produces = op.get('produces') or doc.get('produces') or ['application/json']
    new = {k: copy.deepcopy(v) for k, v in op.items()
           if k not in ('parameters', 'responses', 'consumes', 'produces', 'schemes')}
    merged: Dict[tuple, Dict[str, Any]] = {}
    for raw in list(path_params or []) + list(op.get('parameters') or []):
        p = _inline(doc, raw, 'parameters')
        if isinstance(p, dict):
            merged[(p.get('name'), p.get('in'))] = p
    params, form_props, form_required, has_file = [], {}, [], False
    for p in merged.values():
        where = p.get('in')
        if where == 'body':
            schema = p.get('schema') or {}
            new['requestBody'] = {'required': bool(p.get('required')), 'description': p.get('description', ''),
                                  'content': {ct: {'schema': copy.deepcopy(schema)} for ct in consumes}}
        elif where == 'formData':
            s = _param_schema(p)
            if p.get('description'):
                s['description'] = p['description']
            if s.get('type') == 'file':
                has_file = True
            form_props[p['name']] = s
            if p.get('required'):
                form_required.append(p['name'])
        elif where in ('path', 'query', 'header'):
            q = {'name': p.get('name'), 'in': where, 'required': bool(p.get('required')) or where == 'path',
                 'schema': _param_schema(p)}
            if p.get('description'):
                q['description'] = p['description']
            cf = p.get('collectionFormat')
            if p.get('type') == 'array' and cf in _COLLECTION:
                q['style'], q['explode'] = _COLLECTION[cf]
            elif p.get('type') == 'array' and where == 'query':
                q['style'], q['explode'] = 'form', False         # Swagger default: csv
            params.append(q)
    if form_props:
        ct = 'multipart/form-data' if has_file or 'multipart/form-data' in consumes and \
            'application/x-www-form-urlencoded' not in consumes else 'application/x-www-form-urlencoded'
        body_schema = {'type': 'object', 'properties': form_props}
        if form_required:
            body_schema['required'] = form_required
        new['requestBody'] = {'required': bool(form_required), 'content': {ct: {'schema': body_schema}}}
    if params:
        new['parameters'] = params
    responses = {}
    for code, raw in (op.get('responses') or {}).items():
        r = _inline(doc, raw, 'responses')
        if not isinstance(r, dict):
            continue
        out = {'description': r.get('description', '')}
        if r.get('schema') is not None:
            out['content'] = {ct: {'schema': copy.deepcopy(r['schema'])} for ct in produces}
        responses[str(code)] = out
    new['responses'] = responses
    return new


def convert(doc: Dict[str, Any], source_url: Optional[str] = None) -> Dict[str, Any]:
    """A Swagger 2.0 document as an OpenAPI 3.0 document (the parts API Import reads)."""
    out: Dict[str, Any] = {
        'openapi': '3.0.3',
        'info': copy.deepcopy(doc.get('info') or {}),
        'servers': _servers(doc, source_url),
        'paths': {},
        'components': {'schemas': copy.deepcopy(doc.get('definitions') or {}),
                       'securitySchemes': _security_schemes(doc.get('securityDefinitions') or {})},
        'x-converted-from': 'swagger 2.0',
    }
    if doc.get('security') is not None:
        out['security'] = copy.deepcopy(doc['security'])
    if doc.get('tags'):
        out['tags'] = copy.deepcopy(doc['tags'])
    for path, item in (doc.get('paths') or {}).items():
        if not isinstance(item, dict):
            continue
        path_params = item.get('parameters') or []
        new_item = {}
        for method in _METHODS:
            if isinstance(item.get(method), dict):
                new_item[method] = _operation(doc, item[method], path_params)
        out['paths'][path] = new_item
    return _rewrite_refs(out)
