"""
SAJHA MCP Server — API Import: OpenAPI 3.x (and converted Swagger 2.0) → operations.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:func:`load` reads a document (JSON or YAML, Swagger 2.0 converted first) and
:class:`OpenAPIDocument` lists its operations as plain dicts (``Operation`` below) with
every ``$ref`` inlined and every schema converted to JSON Schema 2020-12. The service
(:mod:`sajha.api_import.service`) turns an operation into a tool config.

Operation dict::

    key, operation_id, method, path, summary, description, tags, deprecated,
    params:  [{arg, name, in, required, schema, style, explode, description}],
    body:    {arg, content_type, required, schema, description} | None,
    response_schema, response_content_type, security ([[scheme, ...], ...] | None),
    servers (path- or operation-level server URLs), pagination ([param names]),
    unsupported (reason | None), flagged (text was screened), base_name
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.api_import import naming
from sajha.api_import.refs import RefError, RefResolver, parse_text
from sajha.api_import.schema import is_valid_schema, limit_depth, to_json_schema

METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
PAGER_PARAMS = {'page', 'per_page', 'perpage', 'page_size', 'pagesize', 'limit', 'offset', 'cursor',
                'page_token', 'pagetoken', 'next_token', 'nexttoken', 'after', 'before',
                'starting_after', 'ending_before', 'skip', 'top', 'marker', 'start'}
_IGNORED_HEADERS = {'accept', 'content-type', 'authorization'}
_JSON_CT = re.compile(r'^application/(?:[\w.+-]+\+)?json$|^application/json', re.I)
DESCRIPTION_LIMIT = 1024
SCHEMA_TEXT_LIMIT = 512
OUTPUT_DEPTH = 8


class SpecError(ValueError):
    """The document is not a usable OpenAPI or Swagger description."""


def load(text_or_data: Any, source_url: Optional[str] = None) -> Dict[str, Any]:
    """A parsed OpenAPI 3.x document (Swagger 2.0 converted). Raises SpecError."""
    try:
        data = parse_text(text_or_data) if isinstance(text_or_data, (str, bytes)) else text_or_data
    except RefError as e:
        raise SpecError(str(e))
    if isinstance(data, bytes):
        data = parse_text(data.decode('utf-8', errors='replace'))
    if not isinstance(data, dict):
        raise SpecError('the document is not a JSON or YAML object')
    if str(data.get('swagger', '')).startswith('2'):
        from sajha.api_import.swagger2 import convert
        return convert(data, source_url)
    version = str(data.get('openapi', ''))
    if not version.startswith('3.'):
        found = f"openapi: {version}" if version else ('a GraphQL introspection result' if
                                                        '__schema' in data or '__schema' in (data.get('data') or {})
                                                        else 'no openapi or swagger field')
        raise SpecError(f'not an OpenAPI 3.x or Swagger 2.0 document ({found})')
    return data


def _screen(text: Any, limit: int) -> Tuple[str, bool]:
    from sajha.federation.security import screen_text
    return screen_text(text, limit)


def _screen_schema(schema: Any) -> Tuple[Any, bool]:
    from sajha.federation.security import screen_schema
    return screen_schema(schema, SCHEMA_TEXT_LIMIT)


def _json_content(content: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    for ct, media in (content or {}).items():
        if _JSON_CT.match(ct.split(';')[0].strip()):
            return ct, media if isinstance(media, dict) else {}
    return None


class OpenAPIDocument:
    def __init__(self, doc: Dict[str, Any], source_url: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None, max_documents: int = 20):
        self.doc = doc
        self.source_url = source_url or ''
        self.is31 = str(doc.get('openapi', '')).startswith('3.1')
        self.resolver = RefResolver(doc, source_url, fetcher, max_documents)

    # ── API-level facts ────────────────────────────────────────────
    def info(self) -> Dict[str, Any]:
        info = self.doc.get('info') or {}
        title, _ = _screen(info.get('title') or 'API', 200)
        description, _ = _screen(info.get('description') or '', DESCRIPTION_LIMIT)
        tags = []
        for t in self.doc.get('tags') or []:
            if isinstance(t, dict) and t.get('name'):
                tags.append(str(t['name']))
        for item in (self.doc.get('paths') or {}).values():
            for m in METHODS:
                op = item.get(m) if isinstance(item, dict) else None
                for t in (op or {}).get('tags') or []:
                    if str(t) not in tags:
                        tags.append(str(t))
        return {'kind': 'openapi', 'title': title, 'version': str(info.get('version') or ''),
                'description': description,
                'spec_version': self.doc.get('x-converted-from') or f"openapi {self.doc.get('openapi')}",
                'servers': self.servers(), 'security_schemes': self.security_schemes(),
                'security': self.doc.get('security'), 'tags': tags}

    def servers(self) -> List[Dict[str, Any]]:
        out = []
        for s in self.doc.get('servers') or []:
            if not isinstance(s, dict) or not s.get('url'):
                continue
            variables = {}
            for name, v in (s.get('variables') or {}).items():
                if isinstance(v, dict):
                    variables[name] = {'default': str(v.get('default', '')),
                                       'enum': [str(x) for x in v.get('enum') or []],
                                       'description': _screen(v.get('description') or '', 200)[0]}
            out.append({'url': str(s['url']), 'description': _screen(s.get('description') or '', 200)[0],
                        'variables': variables})
        return out

    def security_schemes(self) -> Dict[str, Any]:
        raw = ((self.doc.get('components') or {}).get('securitySchemes')) or {}
        out = {}
        for name, scheme in raw.items():
            try:
                s = self.resolver.deref(scheme)
            except RefError:
                continue
            if not isinstance(s, dict):
                continue
            entry = {'type': s.get('type'), 'description': _screen(s.get('description') or '', 300)[0]}
            if s.get('type') == 'apiKey':
                entry.update({'in': s.get('in', 'header'), 'name': s.get('name', '')})
            elif s.get('type') == 'http':
                entry.update({'scheme': str(s.get('scheme', '')).lower(), 'bearerFormat': s.get('bearerFormat', '')})
            elif s.get('type') == 'oauth2':
                flows = s.get('flows') or {}
                entry['flows'] = sorted(flows)
                cc = flows.get('clientCredentials') or {}
                if cc:
                    entry['token_url'] = cc.get('tokenUrl', '')
                    entry['scopes'] = sorted((cc.get('scopes') or {}).keys())
                else:
                    entry['scopes'] = sorted({sc for f in flows.values() if isinstance(f, dict)
                                              for sc in (f.get('scopes') or {})})
            elif s.get('type') == 'openIdConnect':
                entry['openid_connect_url'] = s.get('openIdConnectUrl', '')
            out[name] = entry
        return out

    # ── operations ─────────────────────────────────────────────────
    def operations(self) -> List[Dict[str, Any]]:
        out = []
        for path, item in (self.doc.get('paths') or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                if '$ref' in item:
                    item = self.resolver.deref(item)
            except RefError as e:
                out.append(self._broken(path, 'get', str(e)))
                continue
            for method in METHODS:
                op = item.get(method)
                if not isinstance(op, dict):
                    continue
                try:
                    out.append(self._operation(path, method, item, op))
                except (RefError, RecursionError) as e:
                    out.append(self._broken(path, method, str(e) if isinstance(e, RefError)
                                            else 'schema too deeply nested'))
        return out

    def _broken(self, path: str, method: str, reason: str) -> Dict[str, Any]:
        return {'key': f'{method.upper()} {path}', 'operation_id': '', 'method': method.upper(), 'path': path,
                'summary': '', 'description': '', 'tags': [], 'deprecated': False, 'params': [], 'body': None,
                'response_schema': None, 'response_content_type': '', 'security': None, 'servers': [],
                'pagination': [], 'unsupported': reason, 'flagged': False,
                'base_name': naming.base_from_operation('', method, path)}

    def _schema(self, schema: Any, mode: str) -> Dict[str, Any]:
        converted = to_json_schema(self.resolver.deref(schema or {}), self.is31, mode)
        converted, _ = _screen_schema(converted)
        if mode == 'output':
            converted = limit_depth(converted, OUTPUT_DEPTH)
        if not is_valid_schema(converted):
            return {'description': 'schema from the API description was not valid JSON Schema; not enforced'}
        return converted

    def _operation(self, path: str, method: str, item: Dict[str, Any], op: Dict[str, Any]) -> Dict[str, Any]:
        flagged = False
        summary, f1 = _screen(op.get('summary') or '', 200)
        description, f2 = _screen(op.get('description') or '', DESCRIPTION_LIMIT)
        flagged = f1 or f2

        # parameters: path-level, then operation-level (the operation wins on name + location)
        merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for raw in list(item.get('parameters') or []) + list(op.get('parameters') or []):
            p = self.resolver.deref(raw)
            if isinstance(p, dict) and p.get('name') and p.get('in'):
                merged[(str(p['name']), str(p['in']))] = p
        params, used = [], set()
        for (name, where), p in merged.items():
            if where not in ('path', 'query', 'header', 'cookie'):
                continue
            if where == 'header' and name.lower() in _IGNORED_HEADERS:
                continue
            schema = p.get('schema')
            if schema is None and isinstance(p.get('content'), dict) and p['content']:
                schema = (next(iter(p['content'].values())) or {}).get('schema')
            js = self._schema(schema or {}, 'input')
            desc, f = _screen(p.get('description') or '', 400)
            flagged = flagged or f
            if desc and 'description' not in js:
                js = {**js, 'description': desc}
            if p.get('deprecated'):
                js = {**js, 'deprecated': True}
            arg = naming.arg_name(name)
            if arg in used:
                arg = naming.arg_name(f'{name}_{where}')
            n = 2
            while arg in used:
                arg, n = naming.arg_name(f'{name}_{where}_{n}'), n + 1
            used.add(arg)
            style = p.get('style') or ('simple' if where in ('path', 'header') else 'form')
            explode = p.get('explode') if isinstance(p.get('explode'), bool) else style == 'form'
            params.append({'arg': arg, 'name': name, 'in': where,
                           'required': bool(p.get('required')) or where == 'path',
                           'schema': js, 'style': style, 'explode': explode, 'description': desc})

        # request body
        body, unsupported = None, None
        rb = op.get('requestBody')
        if rb is not None:
            rb = self.resolver.deref(rb)
            content = (rb or {}).get('content') or {}
            chosen = _json_content(content)
            if chosen is None:
                for ct in ('application/x-www-form-urlencoded', 'text/plain'):
                    if ct in content:
                        chosen = (ct, content[ct] or {})
                        break
            if chosen is None and content:
                unsupported = (f"request body type {', '.join(sorted(content))} is not supported "
                               f"(multipart and binary bodies cannot be imported)")
            elif chosen is not None:
                ct, media = chosen
                arg = 'body' if 'body' not in used else 'request_body'
                schema = self._schema(media.get('schema') or {}, 'input')
                if ct == 'text/plain' and not schema:
                    schema = {'type': 'string'}
                rb_desc, f = _screen(rb.get('description') or '', 400)
                flagged = flagged or f
                if rb_desc and 'description' not in schema:
                    schema = {**schema, 'description': rb_desc}
                body = {'arg': arg, 'content_type': ct.split(';')[0].strip(),
                        'required': bool(rb.get('required')), 'schema': schema}

        # response: the first 2xx (then 2XX), JSON content
        response_schema, response_ct = None, ''
        responses = op.get('responses') or {}
        codes = sorted(str(c) for c in responses if str(c).startswith('2'))
        for code in codes:
            r = self.resolver.deref(responses.get(code) if code in responses else responses.get(int(code)))
            content = (r or {}).get('content') or {}
            chosen = _json_content(content)
            if chosen:
                response_ct = chosen[0]
                response_schema = self._schema(chosen[1].get('schema') or {}, 'output')
                break
            if content:
                response_ct = next(iter(content))
                break
            if r is not None:
                break

        security = op.get('security', self.doc.get('security'))
        security_req = None
        if isinstance(security, list):
            security_req = [sorted((req or {}).keys()) for req in security if isinstance(req, dict)]

        servers = [s.get('url') for s in (op.get('servers') or item.get('servers') or [])
                   if isinstance(s, dict) and s.get('url')]
        pagination = [p['name'] for p in params if p['in'] == 'query' and
                      naming.snake(p['name']).replace('_', '') in {x.replace('_', '') for x in PAGER_PARAMS}]
        return {
            'key': f'{method.upper()} {path}', 'operation_id': str(op.get('operationId') or ''),
            'method': method.upper(), 'path': path, 'summary': summary, 'description': description,
            'tags': [str(t) for t in op.get('tags') or []], 'deprecated': bool(op.get('deprecated')),
            'params': params, 'body': body, 'response_schema': response_schema,
            'response_content_type': response_ct, 'security': security_req, 'servers': servers,
            'pagination': pagination, 'unsupported': unsupported, 'flagged': flagged,
            'base_name': naming.base_from_operation(str(op.get('operationId') or ''), method, path),
        }


def matches(op: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """Tag (any of), method, path substring or glob, and deprecated filters."""
    filters = filters or {}
    tags = [t for t in filters.get('tags') or [] if t]
    if tags and not set(tags) & set(op.get('tags') or []):
        return False
    methods = [m.upper() for m in filters.get('methods') or [] if m]
    if methods and op['method'] not in methods:
        return False
    path = (filters.get('path') or '').strip()
    if path:
        if any(ch in path for ch in '*?['):
            if not fnmatch.fnmatchcase(op['path'], path):
                return False
        elif path not in op['path']:
            return False
    if filters.get('hide_deprecated') and op.get('deprecated'):
        return False
    return True
