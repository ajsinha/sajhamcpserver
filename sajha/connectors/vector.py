"""
SAJHA MCP Server — Data Connectors: vector databases and search engines.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Three adapters, none needing an extra Python package:

* ``pgvector``: a PostgreSQL table with a ``vector`` column, searched with a parameterised
  ``ORDER BY <col> <=> $vector LIMIT k`` on the connection's read-only session;
* ``qdrant``: the Qdrant REST API (collections, collection info, point search);
* ``elasticsearch`` / ``opensearch``: the REST API (``_cat/indices``, ``_mapping``, ``_search``),
  full-text ``simple_query_string``, plus k-NN when ``vector.vector_field`` is set.

The caller sends a query text (embedded through the intelligence layer's LLM factory) or a
vector, ``top_k`` and equality ``filters`` on metadata; SAJHA writes the request, so no query
DSL comes from the caller. Results are ``{id, score, text, metadata}`` with masking applied.
Design: docs/architecture/Data Connectors.md, section 9.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from sajha.connectors import masking
from sajha.connectors.drivers import ConnectorError
from sajha.connectors.model import Connection

_FIELD = re.compile(r'^[A-Za-z0-9_.@-]{1,128}$')
_transport = None              # tests: an httpx transport (httpx.MockTransport)


def set_transport(transport) -> None:
    global _transport
    _transport = transport


class VectorAdapter:
    """What a search kind provides."""

    def list_collections(self, conn: Connection) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def describe(self, conn: Connection, name: str) -> Dict[str, Any]:
        raise NotImplementedError

    def search(self, conn: Connection, name: str, text: str, vector: Optional[List[float]], top_k: int,
               filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def version(self, conn: Connection) -> str:
        return ''


# ── HTTP ────────────────────────────────────────────────────────────────

def _secret(conn: Connection, name: str) -> str:
    ref = conn.secrets.get(name)
    if not ref:
        return ''
    from sajha.federation.security import secrets
    v = secrets().resolve(ref) or ''
    if not v:
        raise ConnectorError(f'{conn.id}: secrets.{name}: the reference {ref} resolves to nothing')
    return v


def _redact(text: str, extra: List[str]) -> str:
    from sajha.federation.security import redact
    return redact(text, [e for e in extra if e])


class _HTTP:
    def __init__(self, conn: Connection, headers: Dict[str, str], auth: Optional[Tuple[str, str]] = None,
                 used: Optional[List[str]] = None):
        self.conn = conn
        self.base = str(conn.options.get('url') or '').rstrip('/')
        if not re.match(r'^https?://', self.base):
            raise ConnectorError(f'{conn.id}: options.url must be an http(s) URL')
        self.headers = {'Accept': 'application/json', 'User-Agent': 'SAJHA-Connector', **headers}
        self.auth = auth
        self.used = used or []

    def call(self, method: str, path: str, body: Any = None) -> Any:
        import httpx
        verify = self.conn.options.get('verify_tls', True)
        try:
            with httpx.Client(timeout=float(self.conn.timeout_seconds), transport=_transport, verify=bool(verify),
                              follow_redirects=False) as c:
                from sajha.observability.tracing import inject as _inject_trace
                r = c.request(method, self.base + path, headers=_inject_trace(dict(self.headers)), auth=self.auth,
                              content=None if body is None else json.dumps(body).encode())
        except httpx.TimeoutException:
            from sajha.connectors.drivers import QueryTimeout
            raise QueryTimeout(f'{self.conn.id}: the request timed out after {self.conn.timeout_seconds}s') from None
        except httpx.HTTPError as e:
            raise ConnectorError(_redact(f'{self.conn.id}: {e.__class__.__name__}: {e}', self.used)) from None
        if r.status_code >= 400:
            raise ConnectorError(_redact(f'{self.conn.id}: HTTP {r.status_code} from {method} {path}: '
                                         f'{r.text[:300]}', self.used))
        if len(r.content) > self.conn.max_bytes * 4:
            raise ConnectorError(f'{self.conn.id}: the answer is larger than the connection allows')
        try:
            return r.json()
        except ValueError:
            raise ConnectorError(f'{self.conn.id}: the answer is not JSON') from None


# ── Qdrant ──────────────────────────────────────────────────────────────

class QdrantAdapter(VectorAdapter):
    def _http(self, conn: Connection) -> _HTTP:
        key = _secret(conn, 'api_key')
        return _HTTP(conn, {'api-key': key, 'Content-Type': 'application/json'} if key else
                     {'Content-Type': 'application/json'}, used=[key])

    def version(self, conn):
        data = self._http(conn).call('GET', '/')
        return f"Qdrant {data.get('version', '')}".strip()

    def list_collections(self, conn):
        data = self._http(conn).call('GET', '/collections')
        cols = ((data or {}).get('result') or {}).get('collections') or []
        return [{'name': c.get('name'), 'type': 'collection'} for c in cols if c.get('name')]

    def describe(self, conn, name):
        data = self._http(conn).call('GET', f'/collections/{quote(name, safe="")}')
        res = (data or {}).get('result') or {}
        params = ((res.get('config') or {}).get('params') or {})
        return {'points': res.get('points_count'), 'status': res.get('status'), 'vectors': params.get('vectors'),
                'fields': sorted((res.get('payload_schema') or {}).keys())}

    def search(self, conn, name, text, vector, top_k, filters):
        if vector is None:
            raise ConnectorError('a Qdrant search needs a vector: pass "query" (embedded by the gateway) or "vector"')
        vname = conn.vector.get('vector_name')
        body: Dict[str, Any] = {'vector': {'name': vname, 'vector': vector} if vname else vector,
                                'limit': top_k, 'with_payload': True}
        if filters:
            body['filter'] = {'must': [{'key': k, 'match': {'value': v}} for k, v in filters.items()]}
        data = self._http(conn).call('POST', f'/collections/{quote(name, safe="")}/points/search', body)
        text_field = conn.vector.get('text_field') or 'text'
        out = []
        for hit in (data or {}).get('result') or []:
            payload = dict(hit.get('payload') or {})
            out.append({'id': hit.get('id'), 'score': hit.get('score'), 'text': payload.pop(text_field, None),
                        'metadata': payload})
        return out


# ── Elasticsearch / OpenSearch ──────────────────────────────────────────

class ElasticAdapter(VectorAdapter):
    def _http(self, conn: Connection) -> _HTTP:
        key = _secret(conn, 'api_key')
        if key:
            return _HTTP(conn, {'Authorization': f'ApiKey {key}', 'Content-Type': 'application/json'}, used=[key])
        pw = _secret(conn, 'password')
        auth = (str(conn.options.get('user') or ''), pw) if pw else None
        return _HTTP(conn, {'Content-Type': 'application/json'}, auth=auth, used=[pw])

    def version(self, conn):
        data = self._http(conn).call('GET', '/')
        v = (data or {}).get('version') or {}
        return f"{v.get('distribution') or conn.kind} {v.get('number', '')}".strip()

    def list_collections(self, conn):
        data = self._http(conn).call('GET', '/_cat/indices?format=json&h=index,docs.count,health')
        return [{'name': d.get('index'), 'type': 'index', 'documents': d.get('docs.count')}
                for d in data or [] if d.get('index') and not str(d.get('index')).startswith('.')]

    def describe(self, conn, name):
        data = self._http(conn).call('GET', f'/{quote(name, safe="")}/_mapping')
        props = {}
        for idx in (data or {}).values():
            props.update(((idx or {}).get('mappings') or {}).get('properties') or {})
        return {'fields': {k: (v or {}).get('type', 'object') for k, v in props.items()}}

    def search(self, conn, name, text, vector, top_k, filters):
        flt = [{'term': {k: v}} for k, v in (filters or {}).items()]
        vf = conn.vector.get('vector_field')
        body: Dict[str, Any] = {'size': top_k}
        if vf and vector is not None:
            if conn.kind == 'opensearch':
                body['query'] = {'bool': {'must': [{'knn': {vf: {'vector': vector, 'k': top_k}}}], 'filter': flt}}
            else:
                body['knn'] = {'field': vf, 'query_vector': vector, 'k': top_k,
                               'num_candidates': int(conn.vector.get('num_candidates') or max(50, top_k * 10))}
                if flt:
                    body['knn']['filter'] = {'bool': {'filter': flt}}
        else:
            if not text:
                raise ConnectorError('a full-text search needs "query"')
            sq: Dict[str, Any] = {'query': text}
            if conn.vector.get('fields'):
                sq['fields'] = list(conn.vector['fields'])
            body['query'] = {'bool': {'must': [{'simple_query_string': sq}], 'filter': flt}}
        if vf:
            body['_source'] = {'excludes': [vf]}
        data = self._http(conn).call('POST', f'/{quote(name, safe="")}/_search', body)
        text_field = conn.vector.get('text_field') or 'text'
        out = []
        for hit in ((data or {}).get('hits') or {}).get('hits') or []:
            src = dict(hit.get('_source') or {})
            out.append({'id': hit.get('_id'), 'score': hit.get('_score'), 'text': src.pop(text_field, None),
                        'metadata': src})
        return out


ADAPTERS: Dict[str, VectorAdapter] = {'qdrant': QdrantAdapter(), 'elasticsearch': ElasticAdapter(),
                                      'opensearch': ElasticAdapter()}


# ── shared ──────────────────────────────────────────────────────────────

def _embed(conn: Connection, text: str) -> List[float]:
    from sajha.ai.llm import SajhaRequest, llm_factory
    f = llm_factory()
    if f is None:
        raise ConnectorError('no LLM factory is running to embed the query; pass "vector" instead')
    try:
        model = f.model(str(conn.vector.get('embedding_model') or 'embedding'), kind='embedding')
        vecs = model.embeddings_create(input=[text], sajha=SajhaRequest(input_purpose='query')).vectors
    except Exception as e:
        raise ConnectorError(f'embedding the query failed: {e.__class__.__name__}: {e}') from None
    return [float(x) for x in vecs[0]]


def _args(conn: Connection, args: Dict[str, Any]) -> Tuple[str, Optional[List[float]], int, Dict[str, Any]]:
    text = args.get('query')
    vector = args.get('vector')
    if text is not None and not isinstance(text, str):
        raise ConnectorError('query must be text')
    if vector is not None:
        if not isinstance(vector, list) or not vector or len(vector) > 8192 or \
                not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector):
            raise ConnectorError('vector must be a list of 1 to 8192 numbers')
        vector = [float(x) for x in vector]
    if not text and vector is None:
        raise ConnectorError('pass "query" (text) or "vector"')
    try:
        top_k = int(args.get('top_k') or 5)
    except (TypeError, ValueError):
        raise ConnectorError('top_k must be a whole number') from None
    top_k = max(1, min(top_k, 100, conn.max_rows))
    filters = args.get('filters') or {}
    if not isinstance(filters, dict):
        raise ConnectorError('filters must be an object of field -> value')
    for k, v in filters.items():
        if not _FIELD.match(str(k)) or isinstance(v, (dict, list)):
            raise ConnectorError(f'filter {k!r}: a field name and a single value')
    return text or '', vector, top_k, filters


def _masked_hits(conn: Connection, hits: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    tables = [('', name)]
    out = []
    for h in hits:
        meta = masking.apply_mapping(conn, h.get('metadata') or {}, tables)
        text = h.get('text')
        rule = conn.mask_rules_for(conn.vector.get('text_field') or conn.vector.get('text_column') or 'text', tables)
        if rule is not None and text is not None:
            text = None if rule.mode == 'hide' else masking.mask_value(conn, rule, text)
        from sajha.connectors.engine import jsonable
        out.append({'id': jsonable(h.get('id')), 'score': h.get('score'), 'text': jsonable(text),
                    'metadata': jsonable(meta)})
    return out


def _allowed(conn: Connection, refresh: bool = False) -> List[Dict[str, Any]]:
    from sajha.connectors import catalog
    adapter = ADAPTERS[conn.kind]
    items, _ = catalog.tables(conn, lambda: [dict(c, schema='') for c in adapter.list_collections(conn)], refresh)
    return items


def _pick(conn: Connection, name: Optional[str]) -> str:
    allowed = [c['name'] for c in _allowed(conn)]
    if not name:
        default = conn.options.get('collection') or conn.options.get('index')
        if default and default in allowed:
            return default
        if len(allowed) == 1:
            return allowed[0]
        raise ConnectorError(f'name the collection (one of: {", ".join(allowed[:30])})')
    if name not in allowed:
        raise ConnectorError(f'collection {name} is not available on connection {conn.id} '
                             f'(see {conn.id}__list_collections)')
    return name


def list_collections(conn: Connection, refresh: bool = False, tool: str = '') -> Dict[str, Any]:
    from sajha.connectors.engine import _timed

    def run():
        items = [{k: v for k, v in c.items() if k != 'schema'} for c in _allowed(conn, bool(refresh))]
        return {'connection': conn.id, 'kind': conn.kind, 'collections': items, 'row_count': len(items),
                'next': f'Call {conn.id}__describe_collection for its fields, then {conn.id}__search.'}
    return _timed(conn, 'list_collections', tool, run)


def describe_collection(conn: Connection, name: Optional[str], tool: str = '') -> Dict[str, Any]:
    from sajha.connectors.engine import _timed

    def run():
        n = _pick(conn, name)
        info = ADAPTERS[conn.kind].describe(conn, n)
        fields = info.get('fields')
        hidden = []
        if isinstance(fields, dict):
            for f in list(fields):
                r = conn.mask_rules_for(f, [('', n)])
                if r is not None and r.mode == 'hide':
                    hidden.append(f)
                    fields.pop(f)
        return {'connection': conn.id, 'collection': n, **info, 'hidden_fields': hidden,
                'next': f'Search it with {conn.id}__search.'}
    return _timed(conn, 'describe_collection', tool, run)


def search(conn: Connection, args: Dict[str, Any], tool: str = '') -> Dict[str, Any]:
    from sajha.connectors.engine import _timed
    if not conn.tool_enabled('search'):
        raise ConnectorError(f'search is turned off for {conn.id}')

    def run():
        text, vector, top_k, filters = _args(conn, args or {})
        if conn.kind == 'pgvector':
            return pgvector_search(conn, text, vector, top_k, filters)
        n = _pick(conn, args.get('collection'))
        for k in filters:
            if conn.mask_rules_for(k, [('', n)]) is not None:
                raise ConnectorError(f'field {k} is masked and cannot be a filter')
        needs_vector = conn.kind == 'qdrant' or bool(conn.vector.get('vector_field'))
        if vector is None and needs_vector:
            vector = _embed(conn, text)
        hits = ADAPTERS[conn.kind].search(conn, n, text, vector, top_k, filters)
        hits = _masked_hits(conn, hits[:top_k], n)
        return {'connection': conn.id, 'collection': n, 'results': hits, 'row_count': len(hits)}
    return _timed(conn, 'search', tool, run, {'top_k': (args or {}).get('top_k'),
                                              'filters': sorted(((args or {}).get('filters') or {}).keys())
                                              if isinstance((args or {}).get('filters'), dict) else []})


# ── pgvector ────────────────────────────────────────────────────────────

_DIST_OP = {'cosine': '<=>', 'l2': '<->', 'inner': '<#>'}


def pgvector_search(conn: Connection, text: str, vector: Optional[List[float]], top_k: int,
                    filters: Dict[str, Any]) -> Dict[str, Any]:
    from sajha.connectors import engine, guard, sqltext
    from sajha.connectors.drivers import get_driver
    v = conn.vector
    allowed, _ = engine.allowed_tables(conn)
    schema, table = engine.resolve_table(conn, v['table'], allowed)
    detail = engine.table_detail(conn, schema, table)
    cmap = {c['name'].lower(): c['name'] for c in detail.get('columns') or []}

    def col(name: str) -> str:
        real = cmap.get(str(name).lower())
        if real is None:
            raise ConnectorError(f'vector: column {name} is not in {schema}.{table}')
        return real
    tables = [(schema, table)]
    vec_col, text_col = col(v['vector_column']), col(v['text_column'])
    id_col = col(v['id_column']) if v.get('id_column') else None
    meta_cols = [col(c) for c in v.get('metadata_columns') or []]
    for c in [text_col] + meta_cols:
        r = conn.mask_rules_for(c, tables)
        if r is not None and r.mode == 'hide':
            raise ConnectorError(f'vector: column {c} is hidden and cannot be returned')
    if vector is None:
        vector = _embed(conn, text)
    drv = get_driver(conn.kind)
    q = drv.quote
    select = [f'{q(id_col)} AS "_id"' if id_col else 'NULL AS "_id"', f'{q(text_col)} AS "_text"'] + \
        [q(c) for c in meta_cols]
    op = _DIST_OP[v.get('distance', 'cosine')]
    where, params = [], {'qv': '[' + ','.join(f'{x:.7g}' for x in vector) + ']'}
    for i, (k, val) in enumerate(filters.items()):
        real = cmap.get(str(k).lower())
        if real is None or real not in meta_cols:
            raise ConnectorError(f'filter {k}: filters apply to the metadata columns '
                                 f'({", ".join(meta_cols) or "none configured"})')
        if conn.mask_rules_for(real, tables) is not None:
            raise ConnectorError(f'filter {k}: the column is masked')
        where.append(f'{q(real)} = :f{i}')
        params[f'f{i}'] = val
    sql = (f'SELECT {", ".join(select)}, {q(vec_col)} {op} CAST(:qv AS vector) AS "_distance" '
           f'FROM {drv.qualified(schema, table)}' + (f' WHERE {" AND ".join(where)}' if where else '') +
           f' ORDER BY "_distance" LIMIT {int(top_k)}')
    text_sql, bound = sqltext.bind_params(sql, params, drv.paramstyle, guard.DIALECTS[conn.kind])
    with engine.session(conn) as (d, dbc, state):
        res = engine._execute(conn, d, dbc, state, text_sql, bound, top_k, conn.max_bytes)
    hits = []
    for r in res['rows']:
        dist = r.get('_distance')
        try:
            dist = float(dist)
        except (TypeError, ValueError):
            dist = None
        score = None if dist is None else (1.0 - dist if op == '<=>' else -dist)
        meta = {c: r.get(c) for c in meta_cols}
        hits.append({'id': r.get('_id'), 'score': score, 'text': r.get('_text'), 'metadata': meta})
    out = []
    for h in hits:
        meta = masking.apply_mapping(conn, h['metadata'], tables)
        rule = conn.mask_rules_for(text_col, tables)
        t = h['text'] if rule is None else masking.mask_value(conn, rule, h['text'])
        out.append({**h, 'text': t, 'metadata': meta})
    return {'connection': conn.id, 'table': f'{schema}.{table}', 'results': out, 'row_count': len(out),
            'tables': [f'{schema}.{table}']}


def test(conn: Connection) -> Dict[str, Any]:
    t0 = time.perf_counter()
    adapter = ADAPTERS[conn.kind]
    try:
        version = adapter.version(conn)
    except ConnectorError:
        raise
    except Exception as e:
        version = f'(version unavailable: {e.__class__.__name__})'
    items = _allowed(conn, refresh=True)
    return {'success': True, 'connection': conn.id, 'kind': conn.kind, 'server_version': version,
            'tables': len(items), 'truncated': False, 'ms': int((time.perf_counter() - t0) * 1000)}
