"""
SAJHA MCP Server — API Import: plan, test, deploy, delete.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Stateless: each call re-reads the source (a URL is fetched again; uploaded text is sent
again by the page), so several workers can serve the Studio page without shared state.

* :func:`plan`     the preview: API facts, one entry per operation (tool name, flags,
                   annotations, diff status against the last import), removed operations.
* :func:`test_call` one operation called once without deploying it.
* :func:`deploy`   writes the selected tools' configs (storage backend), hot-loads them,
                   removes the operations selected for removal, saves the import record.
* :func:`delete_api` removes every tool of an import and its record.

The design is docs/architecture/API Import.md.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from sajha.api_import import fetch, naming, settings, store
from sajha.api_import.openapi import OpenAPIDocument, SpecError, load as load_openapi, matches

logger = logging.getLogger(__name__)

IMPLEMENTATION = 'sajha.api_import.executor.ImportedAPITool'
AUTHOR = 'MCP Studio - API Import'
AUTH_TYPES = ('apiKey', 'bearer', 'basic', 'oauth2_client_credentials', 'connected_account')
_SECRET_FIELDS = {'apiKey': 'value_ref', 'bearer': 'token_ref', 'basic': 'password_ref',
                  'oauth2_client_credentials': 'client_secret_ref'}


class APIImportError(ValueError):
    """A request API Import cannot carry out (bad input, unsafe URL, cap exceeded, ...)."""


def connected_accounts_available() -> bool:
    try:
        return importlib.util.find_spec('sajha.accounts') is not None
    except (ImportError, ValueError):
        return False


# ── the request ──────────────────────────────────────────────────────

@dataclass
class ImportRequest:
    kind: str = 'openapi'                    # 'openapi' | 'graphql'
    url: str = ''                            # spec URL, or the GraphQL endpoint
    text: str = ''                           # uploaded / pasted spec or introspection result
    prefix: str = ''
    server_index: int = 0
    server_variables: Dict[str, str] = field(default_factory=dict)
    base_url: str = ''
    auth: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 0
    rate_limit_per_minute: int = 0
    graphql_depth: int = 0
    names: Dict[str, str] = field(default_factory=dict)       # op key -> tool name
    selected: List[str] = field(default_factory=list)         # op keys to deploy
    remove: List[str] = field(default_factory=list)           # op keys whose tools to delete

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ImportRequest':
        d = d or {}

        def _int(key):
            try:
                return int(d.get(key) or 0)
            except (TypeError, ValueError):
                raise APIImportError(f'{key} must be a whole number')
        kind = str(d.get('kind') or 'openapi').lower()
        if kind not in ('openapi', 'graphql'):
            raise APIImportError("kind must be 'openapi' or 'graphql'")
        return cls(kind=kind, url=str(d.get('url') or '').strip(), text=str(d.get('text') or ''),
                   prefix=str(d.get('prefix') or '').strip().lower(), server_index=_int('server_index'),
                   server_variables={str(k): str(v) for k, v in (d.get('server_variables') or {}).items()},
                   base_url=str(d.get('base_url') or '').strip(),
                   auth={str(k): dict(v) for k, v in (d.get('auth') or {}).items() if isinstance(v, dict)},
                   filters=dict(d.get('filters') or {}), timeout_seconds=_int('timeout_seconds'),
                   rate_limit_per_minute=_int('rate_limit_per_minute'), graphql_depth=_int('graphql_depth'),
                   names={str(k): str(v).strip().lower() for k, v in (d.get('names') or {}).items() if v},
                   selected=[str(x) for x in d.get('selected') or []],
                   remove=[str(x) for x in d.get('remove') or []])


# ── the source ───────────────────────────────────────────────────────

def _check_size(text: str) -> None:
    if len(text.encode('utf-8', errors='ignore')) > settings.max_spec_bytes():
        raise APIImportError(f'the document exceeds {settings.max_spec_bytes()} bytes (api_import.max_spec_bytes)')


def _fetch_text(url: str) -> str:
    try:
        return fetch.fetch_document(url)[0]
    except fetch.UnsafeURLError as e:
        raise APIImportError(f'spec URL refused: {e}')
    except fetch.FetchError as e:
        raise APIImportError(f'could not fetch {url}: {e}')


def _ref_fetcher(url: str) -> str:
    try:
        return fetch.fetch_document(url)[0]
    except (fetch.UnsafeURLError, fetch.FetchError) as e:
        from sajha.api_import.refs import RefError
        raise RefError(f'referenced document {url} refused or unreadable: {e}')


def _introspect(endpoint: str, auth: Dict[str, Any]) -> Any:
    from sajha.api_import import executor
    from sajha.api_import.graphql import INTROSPECTION_QUERY
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': executor.USER_AGENT}
    query: List[Tuple[str, str]] = []
    cookies: Dict[str, str] = {}
    timeout = float(settings.timeout_seconds())
    try:
        used = executor.apply_auth({'auth': auth, 'security': None}, headers, query, cookies, timeout)
    except executor.APICallError as e:
        raise APIImportError(str(e))
    if cookies:
        headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in cookies.items())
    try:
        resp = fetch.request('POST', endpoint, params=query, headers=headers,
                             content=json.dumps({'query': INTROSPECTION_QUERY}).encode(), timeout=timeout,
                             max_bytes=settings.max_spec_bytes(), follow_redirects=False)
    except fetch.UnsafeURLError as e:
        raise APIImportError(f'GraphQL endpoint refused: {e}')
    except fetch.FetchError as e:
        raise APIImportError(executor._redact(f'GraphQL introspection failed: {e}', used))
    if resp.status != 200:
        raise APIImportError(f'GraphQL introspection answered HTTP {resp.status}')
    try:
        return json.loads(resp.content)
    except ValueError:
        raise APIImportError('GraphQL introspection did not answer JSON')


def load_document(req: ImportRequest):
    """(document object, spec URL or '') for the request's source."""
    if req.kind == 'graphql':
        from sajha.api_import.graphql import GraphQLDocument, GraphQLSchemaError
        depth = req.graphql_depth or settings.graphql_depth()
        if req.text.strip():
            _check_size(req.text)
            try:
                data = json.loads(req.text)
            except ValueError:
                raise APIImportError('the uploaded GraphQL schema must be an introspection result in JSON')
        elif req.url:
            data = _introspect(req.url, normalize_auth(req.auth, {}, graphql=True))
        else:
            raise APIImportError('give the GraphQL endpoint URL or upload an introspection result')
        try:
            return GraphQLDocument(data, depth=min(5, max(1, depth))), req.url
        except GraphQLSchemaError as e:
            raise APIImportError(str(e))
    if req.text.strip():
        text, spec_url = req.text, req.url
    elif req.url:
        text = _fetch_text(req.url)
        spec_url = req.url
    else:
        raise APIImportError('give a spec URL or upload a spec')
    _check_size(text)
    try:
        doc = load_openapi(text, spec_url or None)
    except SpecError as e:
        raise APIImportError(str(e))
    return OpenAPIDocument(doc, spec_url or None, _ref_fetcher, settings.max_ref_documents()), spec_url


# ── auth, servers ────────────────────────────────────────────────────

def normalize_auth(auth: Dict[str, Dict[str, Any]], schemes: Dict[str, Any],
                   graphql: bool = False) -> Dict[str, Dict[str, Any]]:
    """Credentials the administrator gave, checked and completed from the spec's schemes.
    Secrets must be references (env:, file:, db:); a literal secret is refused."""
    from sajha.api_import.executor import is_secret_ref
    out = {}
    for name, raw in (auth or {}).items():
        cfg = {k: v for k, v in raw.items() if v not in (None, '')}
        if not cfg or cfg.get('type') in (None, '', 'none'):
            continue
        declared = schemes.get(name) or {}
        kind = cfg.get('type')
        if kind not in AUTH_TYPES:
            raise APIImportError(f"auth {name}: type must be one of {', '.join(AUTH_TYPES)}")
        secret_field = _SECRET_FIELDS.get(kind)
        if secret_field and not is_secret_ref(cfg.get(secret_field)):
            raise APIImportError(f'auth {name}: {secret_field} must be a secret reference such as '
                               f'env:NAME, file:/path or db:llm_providers/<type>, not the secret itself')
        entry: Dict[str, Any] = {'type': kind}
        if kind == 'apiKey':
            entry['in'] = cfg.get('in') or declared.get('in') or 'header'
            entry['name'] = cfg.get('name') or declared.get('name') or 'X-API-Key'
            if entry['in'] not in ('header', 'query', 'cookie'):
                raise APIImportError(f'auth {name}: in must be header, query or cookie')
            entry['value_ref'] = cfg['value_ref']
        elif kind == 'bearer':
            entry['token_ref'] = cfg['token_ref']
        elif kind == 'basic':
            entry['username'] = str(cfg.get('username') or '')
            entry['password_ref'] = cfg['password_ref']
        elif kind == 'oauth2_client_credentials':
            entry['token_url'] = cfg.get('token_url') or declared.get('token_url') or ''
            if not entry['token_url']:
                raise APIImportError(f'auth {name}: token_url is required')
            try:
                fetch.check_url(entry['token_url'])
            except fetch.UnsafeURLError as e:
                raise APIImportError(f'auth {name}: token_url refused: {e}')
            entry['client_id'] = str(cfg.get('client_id') or '')
            entry['client_secret_ref'] = cfg['client_secret_ref']
            scopes = cfg.get('scopes', cfg.get('scope', ''))
            entry['scopes'] = scopes if isinstance(scopes, list) else [s for s in str(scopes).split() if s]
        elif kind == 'connected_account':
            if not connected_accounts_available():
                raise APIImportError(f'auth {name}: per-user connected accounts are not available on this '
                                   f'server (sajha.accounts is not installed); use a static credential')
            entry['provider'] = str(cfg.get('provider') or name)
            try:
                from sajha.accounts.service import get_service
                get_service().provider(entry['provider'], require_configured=False)
            except Exception as e:
                raise APIImportError(f"auth {name}: {entry['provider']!r} is not a connected-accounts "
                                     f"provider ({e})")
            scopes = cfg.get('scopes', '')
            entry['scopes'] = scopes if isinstance(scopes, list) else [s for s in str(scopes).split() if s]
        if graphql or name not in schemes:
            entry['global'] = True
        out[name] = entry
    return out


def _substitute_server(server: Dict[str, Any], values: Dict[str, str]) -> str:
    url = server['url']
    for var, spec in (server.get('variables') or {}).items():
        value = values.get(var, spec.get('default', ''))
        if spec.get('enum') and value not in spec['enum']:
            raise APIImportError(f"server variable {var} must be one of {', '.join(spec['enum'])}")
        url = url.replace('{' + var + '}', value)
    return url


def _absolute(url: str, spec_url: str) -> str:
    if urlsplit(url).scheme:
        return url
    if not spec_url:
        raise APIImportError(f'the server URL {url!r} is relative and the spec was uploaded; give a base URL')
    return urljoin(spec_url, url)


def resolve_base_url(req: ImportRequest, info: Dict[str, Any], spec_url: str) -> str:
    if req.base_url:
        url = req.base_url
    elif req.kind == 'graphql':
        url = req.url
        if not url:
            raise APIImportError('give the GraphQL endpoint URL (the base URL)')
    else:
        servers = info.get('servers') or []
        if servers:
            idx = req.server_index if 0 <= req.server_index < len(servers) else 0
            url = _absolute(_substitute_server(servers[idx], req.server_variables), spec_url)
        elif spec_url:
            url = urljoin(spec_url, '/')
        else:
            raise APIImportError('the spec declares no servers and was uploaded; give a base URL')
    try:
        fetch.check_url(url)
    except fetch.UnsafeURLError as e:
        raise APIImportError(f'base URL refused: {e}')
    return url.rstrip('/')


# ── operation → tool config ──────────────────────────────────────────

def annotations_for(op: Dict[str, Any]) -> Dict[str, Any]:
    gql = op.get('graphql')
    method = op['method']
    ann: Dict[str, Any] = {}
    if op.get('summary'):
        ann['title'] = op['summary'][:120]
    if gql:
        if gql['operation_type'] == 'query':
            ann['readOnlyHint'] = True
        else:
            ann['readOnlyHint'] = False
            ann['destructiveHint'] = True
    elif method in ('GET', 'HEAD', 'OPTIONS'):
        ann['readOnlyHint'] = True
    else:
        ann['readOnlyHint'] = False
        ann['destructiveHint'] = method in ('DELETE', 'PUT', 'PATCH')
        if method in ('PUT', 'DELETE'):
            ann['idempotentHint'] = True
    ann['openWorldHint'] = True
    return ann


def input_schema_for(op: Dict[str, Any]) -> Dict[str, Any]:
    props, required = {}, []
    for p in op.get('params') or []:
        props[p['arg']] = p['schema']
        if p.get('required'):
            required.append(p['arg'])
    body = op.get('body')
    if body:
        props[body['arg']] = body['schema']
        if body.get('required'):
            required.append(body['arg'])
    schema: Dict[str, Any] = {'type': 'object', 'properties': props, 'additionalProperties': False}
    if required:
        schema['required'] = required
    return schema


def output_schema_for(op: Dict[str, Any]) -> Dict[str, Any]:
    body = op.get('response_schema')
    props: Dict[str, Any] = {
        'status': {'type': 'integer', 'description': 'HTTP status of the answer'},
        'body': body if body else {'description': 'The response body (JSON parsed, otherwise text)'},
    }
    if op.get('graphql'):
        props['errors'] = {'type': 'array', 'description': 'GraphQL errors returned with partial data'}
    else:
        props['next_page'] = {'type': 'string', 'description': 'The next page URL (Link rel="next")'}
    return {'type': 'object', 'properties': props, 'required': ['status', 'body']}


def fingerprint(op: Dict[str, Any]) -> str:
    """A hash of what the API description says about the operation (not server or auth)."""
    parts = {k: op.get(k) for k in ('method', 'path', 'params', 'body', 'response_schema',
                                    'response_content_type', 'security', 'summary', 'description',
                                    'deprecated', 'graphql')}
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _description(op: Dict[str, Any]) -> str:
    gql = op.get('graphql')
    head = op.get('summary') or ''
    body = op.get('description') or ''
    if head and body:
        text = body if body.startswith(head) else f'{head}. {body}'
    else:
        text = head or body
    text = text.strip()
    where = f"GraphQL {gql['operation_type']} {gql['field']}" if gql else f"{op['method']} {op['path']}"
    text = f'{text} ({where})' if text else where
    if op.get('pagination'):
        text += f"; paginated with {', '.join(op['pagination'])}"
    if op.get('deprecated'):
        text = '[deprecated] ' + text
    return text[:2000]


def tool_config(op: Dict[str, Any], name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    gql = op.get('graphql')
    server = ctx['server_url']
    if op.get('servers'):
        server = _absolute(op['servers'][0], ctx.get('spec_url') or server).rstrip('/')
    spec = {
        'api_id': ctx['api_id'], 'kind': 'graphql' if gql else 'openapi', 'operation': op['key'],
        'operation_id': op.get('operation_id', ''), 'method': op['method'], 'path': op['path'],
        'server_url': server,
        'params': [{k: p[k] for k in ('arg', 'name', 'in', 'style', 'explode')} for p in op.get('params') or []],
        'body': ({k: op['body'][k] for k in ('arg', 'content_type')} if op.get('body') else None),
        'response_content_type': op.get('response_content_type') or 'application/json',
        'security': op.get('security'), 'auth': copy.deepcopy(ctx.get('auth') or {}),
        'timeout_seconds': ctx.get('timeout_seconds') or settings.timeout_seconds(),
        'rate_limit_per_minute': ctx.get('rate_limit_per_minute') or 0,
        'pagination': op.get('pagination') or [], 'fingerprint': fingerprint(op),
    }
    if gql:
        spec['graphql'] = dict(gql)
    config: Dict[str, Any] = {
        'name': name,
        'implementation': IMPLEMENTATION,
        'description': _description(op),
        'version': '1.0.0',
        'enabled': True,
        'inputSchema': input_schema_for(op),
        'outputSchema': output_schema_for(op),
        'annotations': annotations_for(op),
        'metadata': {
            'author': AUTHOR, 'category': 'Imported API',
            'tags': ['api-import', ctx['api_id']] + [t for t in op.get('tags') or [] if t][:5],
            'source': 'api_import', 'api_id': ctx['api_id'], 'api_title': ctx.get('title', ''),
            'method': op['method'], 'path': op['path'], 'requiresApiKey': bool(ctx.get('auth')),
        },
        'api_import': spec,
    }
    if op.get('summary'):
        config['title'] = op['summary'][:120]
    connected = [c for c in (ctx.get('auth') or {}).values() if c.get('type') == 'connected_account']
    if connected:
        # the connected-accounts binding (read by sajha.accounts when it is installed)
        config['auth'] = {'connected_account': connected[0]['provider'],
                          'scopes': connected[0].get('scopes') or []}
    return config


# ── ownership of tool names ──────────────────────────────────────────

def _owner_of(name: str, registry) -> Tuple[bool, Optional[str]]:
    """(exists, api_id owning it or None)."""
    cfg = None
    if registry is not None:
        cfg = (getattr(registry, 'tool_configs', {}) or {}).get(name)
        if cfg is None and name in (getattr(registry, 'tools', {}) or {}):
            return True, None
    if cfg is None:
        try:
            from sajha.core.storage import get_storage
            st = get_storage()
            rel = f'config/tools/{name}.json'
            if st.exists(rel):
                cfg = st.read_json(rel)
        except Exception:
            cfg = {'name': name}
    if cfg is None:
        return False, None
    spec = cfg.get('api_import') if isinstance(cfg, dict) else None
    return True, (spec or {}).get('api_id') if isinstance(spec, dict) else None


# ── plan ─────────────────────────────────────────────────────────────

@dataclass
class Plan:
    req: ImportRequest
    info: Dict[str, Any]
    spec_url: str
    prefix: str
    server_url: str
    server_error: str
    auth: Dict[str, Any]
    ops: List[Dict[str, Any]]                 # filtered operations, each with 'name' and 'status'
    removed: List[Dict[str, Any]]
    record: Optional[Dict[str, Any]]
    total: int

    def ctx(self) -> Dict[str, Any]:
        return {'api_id': self.prefix, 'server_url': self.server_url, 'spec_url': self.spec_url,
                'auth': self.auth, 'timeout_seconds': self.req.timeout_seconds,
                'rate_limit_per_minute': self.req.rate_limit_per_minute, 'title': self.info.get('title', '')}

    def op(self, key: str) -> Dict[str, Any]:
        for op in self.ops:
            if op['key'] == key:
                return op
        raise APIImportError(f'no operation {key!r} in this import (check the filter)')


def build_plan(req: ImportRequest, registry=None) -> Plan:
    doc, spec_url = load_document(req)
    info = doc.info()
    prefix = req.prefix or ('graphql' if req.kind == 'graphql' else naming.prefix_from(info.get('title') or 'api'))
    if not naming.valid_prefix(prefix):
        raise APIImportError('prefix must be 2-31 characters: a lowercase letter, then lowercase letters, '
                           'digits or underscores')
    try:
        server_url, server_error = resolve_base_url(req, info, spec_url), ''
    except APIImportError as e:
        server_url, server_error = '', str(e)
    auth = normalize_auth(req.auth, info.get('security_schemes') or {}, graphql=req.kind == 'graphql')
    record = store.load(prefix)
    if record and record.get('kind') and record['kind'] != req.kind:
        raise APIImportError(f"prefix {prefix} is already used by a {record['kind']} import")
    all_ops = doc.operations()
    ops = [op for op in all_ops if matches(op, req.filters)]
    taken: set = set()
    recorded = (record or {}).get('operations') or {}
    for op in ops:
        wanted = req.names.get(op['key']) or (recorded.get(op['key']) or {}).get('tool_name') \
            or naming.tool_name(prefix, op['base_name'])
        if not naming.TOOL_NAME_RE.match(wanted):
            raise APIImportError(f"tool name {wanted!r} for {op['key']} must be 3-64 characters: a lowercase "
                               f"letter, then lowercase letters, digits or underscores, never '__'")
        name = naming.dedupe(wanted, taken)
        taken.add(name)
        op['name'] = name
        op['fingerprint'] = fingerprint(op)
        exists, owner = _owner_of(name, registry)
        op['conflict'] = (owner or 'another tool') if exists and owner != prefix else ''
        rec = recorded.get(op['key'])
        deployed = bool(rec) and _owner_of(rec.get('tool_name', ''), registry) == (True, prefix)
        if not deployed:
            op['status'] = 'new'
        elif rec.get('fingerprint') != op['fingerprint'] or rec.get('tool_name') != name:
            op['status'] = 'changed'
        else:
            op['status'] = 'unchanged'
    present = {op['key'] for op in all_ops}
    removed = [{'key': k, 'name': v.get('tool_name'), 'status': 'removed'}
               for k, v in sorted(recorded.items()) if k not in present]
    return Plan(req, info, spec_url, prefix, server_url, server_error, auth, ops, removed, record, len(all_ops))


def _deployed_count(plan: Plan) -> int:
    return sum(1 for op in plan.ops if op['status'] in ('changed', 'unchanged'))


def plan(data: Dict[str, Any], registry=None) -> Dict[str, Any]:
    """The preview the Studio page and the CLI show."""
    req = ImportRequest.from_dict(data)
    p = build_plan(req, registry)
    cap = settings.max_tools()
    reimport = p.record is not None
    room = cap - _deployed_count(p)
    previews = []
    for op in p.ops:
        selectable = not op.get('unsupported') and not op['conflict']
        if reimport:
            default = op['status'] in ('changed', 'unchanged') and selectable
        else:
            default = selectable and room > 0
            if default:
                room -= 1
        previews.append({
            'key': op['key'], 'name': op['name'], 'method': op['method'], 'path': op['path'],
            'operation_id': op.get('operation_id', ''), 'summary': op.get('summary', ''),
            'tags': op.get('tags') or [], 'deprecated': op.get('deprecated', False),
            'annotations': annotations_for(op), 'unsupported': op.get('unsupported') or '',
            'conflict': op['conflict'], 'status': op['status'], 'flagged': op.get('flagged', False),
            'params': [{'arg': x['arg'], 'in': x['in'], 'required': x['required']} for x in op.get('params') or []],
            'body': (op['body'] or {}).get('content_type', '') if op.get('body') else '',
            'security': op.get('security'), 'pagination': op.get('pagination') or [],
            'selectable': selectable, 'selected': default,
            'input_schema': input_schema_for(op),
        })
    warnings = []
    if p.server_error:
        warnings.append(p.server_error)
    if len(p.ops) > cap:
        warnings.append(f'{len(p.ops)} operations match; at most {cap} tools per API (api_import.max_tools). '
                        f'Narrow the filter or select fewer.')
    unsupported = sum(1 for op in p.ops if op.get('unsupported'))
    if unsupported:
        warnings.append(f'{unsupported} operation(s) cannot be imported (see the flag on each)')
    if any(op.get('flagged') for op in p.ops):
        warnings.append('Some descriptions contained text that looks like instructions to a model; it was removed')
    return {
        'success': True,
        'api': {**p.info, 'prefix': p.prefix, 'spec_url': p.spec_url, 'base_url': p.server_url,
                'connected_accounts': connected_accounts_available()},
        'operations': previews, 'removed': p.removed, 'reimport': reimport,
        'counts': {'total': p.total, 'shown': len(p.ops), 'unsupported': unsupported,
                   'conflicts': sum(1 for op in p.ops if op['conflict'])},
        'max_tools': cap, 'warnings': warnings,
    }


# ── test call ────────────────────────────────────────────────────────

def test_call(data: Dict[str, Any], registry=None) -> Dict[str, Any]:
    from sajha.api_import.executor import APICallError, ImportedAPITool
    from sajha.tools.base_mcp_tool import ToolArgumentError
    req = ImportRequest.from_dict(data)
    p = build_plan(req, registry)
    if p.server_error:
        raise APIImportError(p.server_error)
    op = p.op(str(data.get('operation') or ''))
    if op.get('unsupported'):
        raise APIImportError(f"{op['key']} cannot be imported: {op['unsupported']}")
    config = tool_config(op, op['name'], p.ctx())
    tool = ImportedAPITool(config)
    arguments = data.get('arguments') or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or '{}')
        except ValueError:
            raise APIImportError('arguments must be a JSON object')
    try:
        tool.validate_arguments(arguments)
        if config.get('auth'):              # a per-user connected account: bind the caller's token
            from sajha.accounts.injection import bind
            with bind(tool, arguments):
                result = tool.execute(arguments)
        else:
            result = tool.execute(arguments)
    except ToolArgumentError as e:
        return {'success': False, 'error': str(e), 'tool_name': op['name']}
    except APICallError as e:
        return {'success': False, 'error': str(e), 'status': e.status, 'tool_name': op['name']}
    except Exception as e:                  # e.g. ConnectedAccountRequired: the admin has not linked one
        return {'success': False, 'error': f'{e.__class__.__name__}: {e}', 'tool_name': op['name']}
    return {'success': True, 'tool_name': op['name'], 'result': result}


# ── deploy / delete ──────────────────────────────────────────────────

def _write_config(name: str, config: Dict[str, Any]) -> None:
    from sajha.core.storage import write_tool_config
    write_tool_config(f'{name}.json', config)


def _remove_config(name: str) -> bool:
    from sajha.core.storage import get_storage
    try:
        return bool(get_storage().delete(f'config/tools/{name}.json'))
    except FileNotFoundError:
        return False


def _hot_load(registry, name: str) -> Tuple[bool, str]:
    if registry is None:
        return True, ''
    registry.load_tool_from_config(f'{name}.json')
    if name in registry.tools:
        return True, ''
    return False, (registry.tool_errors or {}).get(name, 'the tool did not load')


def _unload(registry, name: str) -> None:
    if registry is None:
        return
    if name in registry.tools:
        registry.unregister_tool(name)
    lock = getattr(registry, '_tools_lock', None)
    if lock is None:
        return
    with lock:
        registry.tool_configs.pop(name, None)
        registry.tool_errors.pop(name, None)
        try:
            registry._file_timestamps.pop(registry._config_rel(f'{name}.json'), None)
        except Exception:
            pass


def _reindex(registry) -> None:
    """Tell the registry's reload listeners (the Ask SAJHA / semantic tool-search index) that
    tools changed: a hot-load alone does not, so new tools would not be shortlisted."""
    notify = getattr(registry, '_notify_reload', None) if registry is not None else None
    if callable(notify):
        try:
            notify()
        except Exception as e:
            logger.debug(f'tool index refresh: {e}')


def _bulk(registry):
    from contextlib import nullcontext
    bulk = getattr(registry, 'bulk', None) if registry is not None else None
    return bulk() if callable(bulk) else nullcontext()


def deploy(data: Dict[str, Any], registry=None, user: str = '') -> Dict[str, Any]:
    req = ImportRequest.from_dict(data)
    p = build_plan(req, registry)
    selected = list(dict.fromkeys(req.selected))
    if not selected and not req.remove:
        raise APIImportError('select at least one operation to deploy (or one to remove)')
    if selected and p.server_error:
        raise APIImportError(p.server_error)
    ops = [p.op(k) for k in selected]
    for op in ops:
        if op.get('unsupported'):
            raise APIImportError(f"{op['key']} cannot be imported: {op['unsupported']}")
        if op['conflict']:
            raise APIImportError(f"tool name {op['name']} for {op['key']} is already used by {op['conflict']}; "
                               f"rename it")
    recorded = dict((p.record or {}).get('operations') or {})
    removing = set(req.remove)
    for key in removing:
        if key not in recorded:
            raise APIImportError(f'{key} is not a deployed operation of {p.prefix}')
    final = {k for k, v in recorded.items()
             if k not in removing and _owner_of(v.get('tool_name', ''), registry) == (True, p.prefix)}
    final |= set(selected)
    cap = settings.max_tools()
    if len(final) > cap:
        raise APIImportError(f'this would give {p.prefix} {len(final)} tools; at most {cap} '
                           f'(api_import.max_tools)')
    if ops:
        for url in {tool_config(op, op['name'], p.ctx())['api_import']['server_url'] for op in ops}:
            try:
                fetch.guard(url)
            except fetch.UnsafeURLError as e:
                raise APIImportError(f'base URL refused: {e}')

    deployed, updated, removed, failed = [], [], [], []
    ctx = p.ctx()
    with _bulk(registry):
        for key in sorted(removing):
            name = recorded[key].get('tool_name', '')
            if _owner_of(name, registry) == (True, p.prefix):
                _unload(registry, name)
                _remove_config(name)
                _unload(registry, name)
                removed.append(name)
            recorded.pop(key, None)
        for op in ops:
            name = op['name']
            previous = (recorded.get(op['key']) or {}).get('tool_name')
            config = tool_config(op, name, ctx)
            try:
                _write_config(name, config)
            except Exception as e:
                failed.append({'name': name, 'key': op['key'], 'error': f'could not write the config: {e}'})
                continue
            ok, err = _hot_load(registry, name)
            if not ok:
                _remove_config(name)
                _unload(registry, name)
                failed.append({'name': name, 'key': op['key'], 'error': err})
                continue
            if previous and previous != name and _owner_of(previous, registry) == (True, p.prefix):
                _unload(registry, previous)
                _remove_config(previous)
                _unload(registry, previous)
            (updated if op['status'] in ('changed', 'unchanged') else deployed).append(name)
            recorded[op['key']] = {'tool_name': name, 'fingerprint': op['fingerprint']}

    if deployed or updated or removed:
        _reindex(registry)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        'api_id': p.prefix, 'kind': req.kind, 'title': p.info.get('title', ''),
        'version': p.info.get('version', ''),
        'source': {'url': req.url, 'uploaded': bool(req.text.strip())},
        'server_url': p.server_url, 'server_index': req.server_index, 'server_variables': req.server_variables,
        'base_url': req.base_url, 'auth': p.auth, 'filters': req.filters,
        'timeout_seconds': req.timeout_seconds, 'rate_limit_per_minute': req.rate_limit_per_minute,
        'graphql_depth': req.graphql_depth,
        'operations': recorded, 'created_at': (p.record or {}).get('created_at') or now,
        'updated_at': now, 'updated_by': user,
        'created_by': (p.record or {}).get('created_by') or user,
    }
    if recorded:
        store.save(record)
    else:
        store.delete(p.prefix)
    return {'success': not failed, 'api_id': p.prefix, 'deployed': deployed, 'updated': updated,
            'removed': removed, 'failed': failed,
            'message': (f"{p.prefix}: {len(deployed)} added, {len(updated)} updated, {len(removed)} removed"
                        + (f", {len(failed)} failed" if failed else ''))}


def delete_api(api_id: str, registry=None) -> Dict[str, Any]:
    record = store.load(api_id)
    if not record:
        raise APIImportError(f'no import {api_id!r}')
    removed = []
    with _bulk(registry):
        for v in (record.get('operations') or {}).values():
            name = v.get('tool_name', '')
            if name and _owner_of(name, registry) == (True, api_id):
                _unload(registry, name)
                _remove_config(name)
                _unload(registry, name)
                removed.append(name)
    store.delete(api_id)
    if removed:
        _reindex(registry)
    return {'success': True, 'api_id': api_id, 'removed': removed,
            'message': f'{api_id}: removed {len(removed)} tool(s) and the import record'}


def list_apis(registry=None) -> List[Dict[str, Any]]:
    out = []
    for r in store.list_records():
        tools = [v.get('tool_name') for v in (r.get('operations') or {}).values()]
        out.append({'api_id': r.get('api_id'), 'kind': r.get('kind'), 'title': r.get('title'),
                    'version': r.get('version'), 'source': r.get('source') or {},
                    'server_url': r.get('server_url'), 'tools': sorted(t for t in tools if t),
                    'auth': sorted((r.get('auth') or {}).keys()), 'updated_at': r.get('updated_at'),
                    'loaded': sum(1 for t in tools if registry is not None and t in registry.tools)})
    return out


def reimport_request(api_id: str) -> Dict[str, Any]:
    """The request that re-reads an import's source with its saved settings (for the page and CLI)."""
    r = store.load(api_id)
    if not r:
        raise APIImportError(f'no import {api_id!r}')
    return {'kind': r.get('kind'), 'url': (r.get('source') or {}).get('url', ''), 'prefix': api_id,
            'server_index': r.get('server_index', 0), 'server_variables': r.get('server_variables') or {},
            'base_url': r.get('base_url', ''), 'auth': r.get('auth') or {}, 'filters': r.get('filters') or {},
            'timeout_seconds': r.get('timeout_seconds', 0), 'graphql_depth': r.get('graphql_depth', 0),
            'rate_limit_per_minute': r.get('rate_limit_per_minute', 0),
            'uploaded': bool((r.get('source') or {}).get('uploaded'))}
