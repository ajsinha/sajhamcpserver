"""
SAJHA MCP Server — Data Connectors: save, test, sync tools, delete, catalog.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* :func:`save`        validate a connection, write its record, regenerate its tools
* :func:`test`        connect with an unsaved definition: server version, allowed tables
* :func:`sync`        make ``config/tools/<id>__*.json`` match the connection (write, hot-load, remove)
* :func:`sync_all`    every connection at start-up (and the page's "Sync tools"); orphans removed
* :func:`delete`      a connection, its tools, its pooled connections and its catalog
* :func:`tool_configs` the generated tool configs (planner-friendly descriptions, schemas, annotations)

Tool configs are written through the storage backend like API Import's; the registry
hot-loads them. Design: docs/architecture/Data Connectors.md, sections 8, 12 and 13.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sajha.connectors import catalog, pool, settings, store
from sajha.connectors.model import (KINDS, PER_USER_KINDS, Connection, ConnectorConfigError, View, parse,
                                    to_record)

logger = logging.getLogger(__name__)

IMPLEMENTATION = 'sajha.connectors.tools.ConnectorTool'
AUTHOR = 'Data Connectors'
ANNOTATIONS = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False}
_DIALECT_NAMES = {'postgresql': 'PostgreSQL', 'pgvector': 'PostgreSQL', 'redshift': 'Amazon Redshift',
                  'mysql': 'MySQL', 'mariadb': 'MariaDB', 'sqlserver': 'SQL Server (T-SQL)', 'oracle': 'Oracle',
                  'snowflake': 'Snowflake', 'bigquery': 'BigQuery (GoogleSQL)', 'databricks': 'Databricks SQL',
                  'sqlite': 'SQLite', 'duckdb': 'DuckDB', 'qdrant': 'Qdrant', 'elasticsearch': 'Elasticsearch',
                  'opensearch': 'OpenSearch'}
_PACKAGES = {'postgresql': ('psycopg2', 'psycopg2-binary'), 'pgvector': ('psycopg2', 'psycopg2-binary'),
             'redshift': ('psycopg2', 'psycopg2-binary'), 'mysql': ('pymysql', 'pymysql'),
             'mariadb': ('pymysql', 'pymysql'), 'sqlserver': ('pyodbc', 'pyodbc'),
             'oracle': ('oracledb', 'oracledb'), 'snowflake': ('snowflake.connector', 'snowflake-connector-python'),
             'bigquery': ('google.cloud.bigquery', 'google-cloud-bigquery'),
             'databricks': ('databricks.sql', 'databricks-sql-connector'), 'sqlite': ('sqlite3', ''),
             'duckdb': ('duckdb', 'duckdb'), 'qdrant': ('', ''), 'elasticsearch': ('', ''), 'opensearch': ('', '')}


_ARR = {'type': 'array'}
_ROWS = {'columns': {'type': 'array', 'items': {'type': 'object'}}, 'rows': {'type': 'array', 'items': {'type': 'object'}},
         'row_count': {'type': 'integer'}, 'truncated': {'type': 'boolean'}, 'truncated_reason': {'type': 'string'},
         'masked_columns': _ARR, 'tables': _ARR, 'elapsed_ms': {'type': 'integer'}}
#: operation -> (required keys, properties) of its structured result
OUTPUTS = {
    'list_tables': (['connection', 'tables'], {'tables': {'type': 'array', 'items': {'type': 'object'}},
                                               'truncated': {'type': 'boolean'}}),
    'describe_table': (['connection', 'table', 'columns'], {'schema': {'type': 'string'}, 'table': {'type': 'string'},
                                                            'columns': _ARR, 'primary_key': _ARR,
                                                            'sample_rows': _ARR}),
    'query': (['connection', 'columns', 'rows', 'row_count', 'truncated'], dict(_ROWS, guard={'type': 'string'})),
    'view': (['connection', 'columns', 'rows', 'row_count', 'truncated'], dict(_ROWS, view={'type': 'string'})),
    'search': (['connection', 'results'], {'results': {'type': 'array', 'items': {'type': 'object'}},
                                           'row_count': {'type': 'integer'}}),
    'list_collections': (['connection', 'collections'], {'collections': _ARR}),
    'describe_collection': (['connection', 'collection'], {'collection': {'type': 'string'}}),
}


def output_schema(op: str) -> Dict[str, Any]:
    required, props = OUTPUTS[op]
    return {'type': 'object', 'required': list(required),
            'properties': dict({'connection': {'type': 'string'}}, **props)}


class ConnectorServiceError(ValueError):
    """A request the Data Connectors service cannot carry out (bad input, name conflict, ...)."""


# ── tool configs ────────────────────────────────────────────────────────

def _about(conn: Connection) -> str:
    s = f'{conn.label} ({_DIALECT_NAMES.get(conn.kind, conn.kind)})'
    return s + (f': {conn.description}' if conn.description else '')


def _base(conn: Connection, name: str, op: str, title: str, description: str, schema: Dict[str, Any],
          view: Optional[str] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {'connection': conn.id, 'op': op}
    if view:
        spec['view'] = view
    cfg: Dict[str, Any] = {
        'name': name, 'implementation': IMPLEMENTATION, 'title': title[:120], 'description': description[:2000],
        'version': '1.0.0', 'enabled': True, 'inputSchema': schema, 'outputSchema': output_schema(op),
        'annotations': dict(ANNOTATIONS, title=title[:120]),
        'metadata': {'author': AUTHOR, 'category': 'Data Connectors',
                     'tags': ['data-connector', conn.id, conn.kind], 'source': 'connector',
                     'connection': conn.id, 'kind': conn.kind},
        'connector': spec,
    }
    if conn.cache_ttl:
        cfg['cache_ttl'] = conn.cache_ttl
    if conn.per_user:
        cfg['auth'] = {'connected_account': conn.auth['provider'], 'scopes': list(conn.auth.get('scopes') or [])}
    return cfg


def _sql_tools(conn: Connection, details: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    from sajha.connectors.engine import view_input_schema
    p = conn.id
    out: Dict[str, Dict[str, Any]] = {}
    if conn.tool_enabled('list_tables'):
        out[f'{p}__list_tables'] = _base(
            conn, f'{p}__list_tables', 'list_tables', f'{conn.label}: list tables',
            f'List the tables and views you may query in {_about(conn)}. Start here; then call '
            f'{p}__describe_table for a table\'s columns, then {p}__query (or a {p}__ view tool) for its rows.',
            {'type': 'object', 'additionalProperties': False, 'properties': {
                'schema': {'type': 'string', 'maxLength': 128, 'description': 'Only tables in this schema.'},
                'pattern': {'type': 'string', 'maxLength': 128,
                            'description': 'A table-name filter: a substring, or a glob such as order*.'},
                'refresh': {'type': 'boolean', 'description': 'Re-read the catalog from the database.'}}})
    if conn.tool_enabled('describe_table'):
        out[f'{p}__describe_table'] = _base(
            conn, f'{p}__describe_table', 'describe_table', f'{conn.label}: describe a table',
            f'Describe one table of {conn.label}: columns, types, nullability, comments, primary key and a few '
            f'sample rows (masked columns stay masked). Get table names from {p}__list_tables first; use what this '
            f'returns to write a query for {p}__query.',
            {'type': 'object', 'additionalProperties': False, 'required': ['table'], 'properties': {
                'table': {'type': 'string', 'minLength': 1, 'maxLength': 300,
                          'description': 'schema.table, or table when the name is unique.'},
                'samples': {'type': 'integer', 'minimum': 0, 'maximum': 20,
                            'description': 'Sample rows to include (default set by the server).'},
                'refresh': {'type': 'boolean', 'description': 'Re-read the table\'s columns from the database.'}}})
    if conn.tool_enabled('query'):
        dialect = _DIALECT_NAMES.get(conn.kind, conn.kind)
        out[f'{p}__query'] = _base(
            conn, f'{p}__query', 'query', f'{conn.label}: read-only SQL',
            f'Run one read-only SQL SELECT against {_about(conn)} and get the rows (at most {conn.max_rows}; the '
            f'result says when it was truncated). Write {dialect} SQL. Call {p}__list_tables and {p}__describe_table '
            f'first to learn the tables and columns; only those tables may be read. Put every value in a :name '
            f'placeholder and give its value in "params" (e.g. WHERE status = :status with params '
            f'{{"status": "paid"}}); never write values into the SQL. Writes, multiple statements and file or '
            f'network functions are refused.',
            {'type': 'object', 'additionalProperties': False, 'required': ['sql'], 'properties': {
                'sql': {'type': 'string', 'minLength': 1, 'maxLength': 100000,
                        'description': 'One SELECT (or WITH ... SELECT) statement, with :name placeholders.'},
                'params': {'type': 'object', 'description': 'Values for the :name placeholders.',
                           'additionalProperties': {'type': ['string', 'number', 'integer', 'boolean', 'null']}},
                'max_rows': {'type': 'integer', 'minimum': 1, 'maximum': conn.max_rows,
                             'description': f'Fewer rows than the connection\'s cap ({conn.max_rows}).'}}})
    for v in conn.views:
        name = f'{p}__{v.name}'
        try:
            schema = view_input_schema(conn, v, details.get(v.table))
        except Exception as e:
            raise ConnectorServiceError(str(e))
        if v.table not in details:
            # no catalog to hand (start-up, Sync tools): keep the typed schema written when the view was saved
            prev = _stored(name)
            spec = (prev or {}).get('connector') or {}
            if spec.get('connection') == conn.id and spec.get('view') == v.name and \
                    set((prev.get('inputSchema') or {}).get('properties') or {}) == set(schema['properties']):
                schema = prev['inputSchema']
        filters = ', '.join(f.column for f in v.filters) or 'none'
        desc = (v.description or v.title or f'Rows of {v.table}') + \
            f' (curated view of {v.table} in {conn.label}; filters: {filters}; at most ' \
            f'{min(conn.max_rows, v.max_rows or conn.max_rows)} rows).'
        out[name] = _base(conn, name, 'view', v.title or f'{conn.label}: {v.name}', desc, schema, view=v.name)
    if conn.kind == 'pgvector' and conn.tool_enabled('search'):
        out[f'{p}__search'] = _search_tool(conn, False)
    return out


def _search_tool(conn: Connection, collections: bool) -> Dict[str, Any]:
    p = conn.id
    props: Dict[str, Any] = {
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 4000,
                  'description': 'What to look for (embedded by the server, or matched as full text).'},
        'vector': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 1, 'maxItems': 8192,
                   'description': 'A query vector, instead of "query".'},
        'top_k': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': 'How many results (default 5).'},
        'filters': {'type': 'object', 'description': 'Equality filters on metadata fields: {"field": value}.',
                    'additionalProperties': {'type': ['string', 'number', 'integer', 'boolean']}},
    }
    if collections:
        props['collection'] = {'type': 'string', 'maxLength': 255,
                               'description': f'The collection or index (from {p}__list_collections).'}
    what = 'nearest-neighbour' if conn.kind in ('qdrant', 'pgvector') or conn.vector.get('vector_field') \
        else 'full-text'
    first = f'Call {p}__list_collections first to find collections. ' if collections else ''
    return _base(conn, f'{p}__search', 'search', f'{conn.label}: search',
                 f'Search {_about(conn)} ({what}) and get the best matches with their text, score and metadata. '
                 f'{first}Pass "query" as text, or "vector".',
                 {'type': 'object', 'additionalProperties': False, 'properties': props})


def _collection_tools(conn: Connection) -> Dict[str, Dict[str, Any]]:
    p = conn.id
    out = {}
    if conn.tool_enabled('list_tables'):
        out[f'{p}__list_collections'] = _base(
            conn, f'{p}__list_collections', 'list_collections', f'{conn.label}: list collections',
            f'List the collections (indices) you may search in {_about(conn)}. Start here; then '
            f'{p}__describe_collection for fields, then {p}__search.',
            {'type': 'object', 'additionalProperties': False,
             'properties': {'refresh': {'type': 'boolean', 'description': 'Re-read the list from the server.'}}})
    if conn.tool_enabled('describe_table'):
        out[f'{p}__describe_collection'] = _base(
            conn, f'{p}__describe_collection', 'describe_collection', f'{conn.label}: describe a collection',
            f'Describe one collection of {conn.label}: its fields (hidden fields left out) and size.',
            {'type': 'object', 'additionalProperties': False, 'properties': {
                'collection': {'type': 'string', 'maxLength': 255,
                               'description': f'From {p}__list_collections; optional when there is one.'}}})
    if conn.tool_enabled('search'):
        out[f'{p}__search'] = _search_tool(conn, True)
    return out


def _view_details(conn: Connection) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Catalog details of the views' tables, when the database answers (types for the schemas)."""
    details, warnings = {}, []
    if not conn.views:
        return details, warnings
    from sajha.connectors import engine
    try:
        allowed, _ = engine.allowed_tables(conn)
    except Exception as e:
        return details, [f'views: the database did not answer ({e}); filter types default to text until the next sync']
    for v in conn.views:
        try:
            schema, table = engine.resolve_table(conn, v.table, allowed)
            detail = engine.table_detail(conn, schema, table)
            engine._view_columns(conn, v, schema, table, detail)
            details[v.table] = detail
        except Exception as e:
            raise ConnectorServiceError(f'view {v.name}: {e}')
    return details, warnings


def tool_configs(conn: Connection, details: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    if not conn.enabled or not settings.enabled():
        return {}
    if conn.family == 'sql':
        return _sql_tools(conn, details or {})
    return _collection_tools(conn)


# ── registry plumbing (as API Import) ───────────────────────────────────

def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def _owner(name: str, registry) -> Tuple[bool, Optional[str]]:
    """(exists, connection id owning it or None)."""
    cfg = None
    if registry is not None:
        cfg = (getattr(registry, 'tool_configs', {}) or {}).get(name)
        if cfg is None and name in (getattr(registry, 'tools', {}) or {}):
            return True, None
    if cfg is None:
        try:
            rel = f'config/tools/{name}.json'
            st = _storage()
            if st.exists(rel):
                cfg = st.read_json(rel)
        except Exception:
            cfg = {'name': name}
    if cfg is None:
        return False, None
    spec = cfg.get('connector') if isinstance(cfg, dict) else None
    return True, (spec.get('connection') if isinstance(spec, dict) else None)


def _stored(name: str) -> Optional[Dict[str, Any]]:
    try:
        rel = f'config/tools/{name}.json'
        st = _storage()
        return st.read_json(rel) if st.exists(rel) else None
    except Exception:
        return None


def _write(name: str, cfg: Dict[str, Any]) -> None:
    from sajha.core.storage import write_tool_config
    write_tool_config(f'{name}.json', cfg)


def _remove(name: str) -> None:
    try:
        _storage().delete(f'config/tools/{name}.json')
    except FileNotFoundError:
        pass


def _load(registry, name: str) -> Tuple[bool, str]:
    if registry is None:
        return True, ''
    registry.load_tool_from_config(f'{name}.json')
    if name in registry.tools:
        return True, ''
    return False, (getattr(registry, 'tool_errors', {}) or {}).get(name, 'the tool did not load')


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
        getattr(registry, 'tool_errors', {}).pop(name, None)
        try:
            registry._file_timestamps.pop(registry._config_rel(f'{name}.json'), None)
        except Exception:
            pass


def _bulk(registry):
    bulk = getattr(registry, 'bulk', None) if registry is not None else None
    return bulk() if callable(bulk) else nullcontext()


def _reindex(registry) -> None:
    notify = getattr(registry, '_notify_reload', None) if registry is not None else None
    if callable(notify):
        try:
            notify()
        except Exception as e:
            logger.debug(f'tool index refresh: {e}')


def _owned_names(cid: str, registry) -> List[str]:
    names = set()
    if registry is not None:
        for n, cfg in list((getattr(registry, 'tool_configs', {}) or {}).items()):
            spec = cfg.get('connector') if isinstance(cfg, dict) else None
            if isinstance(spec, dict) and spec.get('connection') == cid:
                names.add(n)
    try:
        for rel in _storage().list_files('config/tools', f'{cid}__*.json'):
            n = rel.rsplit('/', 1)[-1][:-len('.json')]
            if _owner(n, registry) == (True, cid):
                names.add(n)
    except Exception:
        pass
    return sorted(names)


def _invalidate_cache(names: List[str]) -> None:
    try:
        from sajha.core.cache import get_tool_cache
        cache = get_tool_cache()
        for n in names:
            cache.invalidate(n)
    except Exception as e:
        logger.debug(f'connector cache invalidation: {e}')


def sync(conn: Connection, registry=None, details: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    desired = tool_configs(conn, details)
    owned = _owned_names(conn.id, registry)
    added, updated, removed, kept, failed = [], [], [], [], []
    with _bulk(registry):
        for name in owned:
            if name not in desired:
                _unload(registry, name)
                _remove(name)
                _unload(registry, name)
                removed.append(name)
        for name, cfg in desired.items():
            exists, owner = _owner(name, registry)
            if exists and owner != conn.id:
                failed.append({'name': name, 'error': f'{name} already exists and does not belong to {conn.id}'})
                continue
            current = _stored(name)
            if current == cfg:
                if registry is not None and name not in registry.tools:
                    ok, err = _load(registry, name)
                    if not ok:
                        failed.append({'name': name, 'error': err})
                        continue
                kept.append(name)
                continue
            try:
                _write(name, cfg)
            except Exception as e:
                failed.append({'name': name, 'error': f'could not write the config: {e}'})
                continue
            _unload(registry, name)
            ok, err = _load(registry, name)
            if not ok:
                failed.append({'name': name, 'error': err})
                continue
            (updated if current is not None else added).append(name)
    if added or updated or removed:
        _reindex(registry)
    return {'connection': conn.id, 'added': added, 'updated': updated, 'removed': removed, 'unchanged': kept,
            'failed': failed, 'tools': sorted(desired)}


def remove_tools(cid: str, registry=None) -> List[str]:
    removed = []
    with _bulk(registry):
        for name in _owned_names(cid, registry):
            _unload(registry, name)
            _remove(name)
            _unload(registry, name)
            removed.append(name)
    if removed:
        _reindex(registry)
    return removed


# ── public operations ───────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(data: Dict[str, Any], registry=None, user: str = '', create: bool = False) -> Dict[str, Any]:
    try:
        conn = parse({k: v for k, v in (data or {}).items() if k not in ('created_at', 'updated_at', 'updated_by')})
    except ConnectorConfigError as e:
        raise ConnectorServiceError(str(e))
    previous = store.load_raw(conn.id)
    if create and previous is not None:
        raise ConnectorServiceError(f'a connection called {conn.id} already exists')
    details, warnings = _view_details(conn) if conn.enabled else ({}, [])
    tool_configs(conn, details)                       # a view whose arguments collide fails here, unsaved
    record = to_record(conn)
    record['created_at'] = (previous or {}).get('created_at') or _now()
    record['updated_at'] = _now()
    record['updated_by'] = user
    store.save(record)
    pool.clear(conn.id)
    catalog.invalidate(conn.id)
    conn.raw.update(record)
    result = sync(conn, registry, details)
    _invalidate_cache(result['tools'])
    result.update(success=not result['failed'], warnings=warnings,
                  message=f"{conn.id}: saved; {len(result['tools'])} tool(s)"
                          + (f", {len(result['failed'])} failed" if result['failed'] else ''))
    return result


def delete(cid: str, registry=None) -> Dict[str, Any]:
    if store.load_raw(cid) is None:
        raise ConnectorServiceError(f'no connection {cid!r}')
    removed = remove_tools(cid, registry)
    store.delete(cid)
    pool.clear(cid)
    catalog.invalidate(cid)
    _invalidate_cache(removed)
    return {'success': True, 'connection': cid, 'removed': removed,
            'message': f'{cid}: removed with {len(removed)} tool(s)'}


def test(data: Dict[str, Any]) -> Dict[str, Any]:
    from sajha.connectors import engine
    from sajha.connectors.drivers import ConnectorError, DriverMissing
    try:
        conn = parse({k: v for k, v in (data or {}).items() if k not in ('created_at', 'updated_at', 'updated_by')})
    except ConnectorConfigError as e:
        return {'success': False, 'error': str(e)}
    if conn.per_user:
        return {'success': False, 'error': 'a per-user connection signs in as each caller; test it by calling '
                                           'its tools as a user with a connected account'}
    try:
        out = engine.test(conn)
    except (ConnectorError, DriverMissing) as e:
        return {'success': False, 'error': str(e)}
    except Exception as e:
        from sajha.federation.security import redact
        return {'success': False, 'error': redact(f'{e.__class__.__name__}: {e}')}
    finally:
        pool.clear(conn.id)
        catalog.invalidate(conn.id)
    return out


def sync_all(registry=None) -> Dict[str, Any]:
    ids = store.ids()
    results, errors = [], {}
    for cid in ids:
        conn, err = store.get(cid)
        if conn is None:
            errors[cid] = err
            continue
        try:
            results.append(sync(conn, registry))          # no database is opened here
        except Exception as e:
            errors[cid] = f'{e.__class__.__name__}: {e}'
    # tools of connections that no longer exist
    orphans = []
    if registry is not None:
        for name, cfg in list((getattr(registry, 'tool_configs', {}) or {}).items()):
            spec = cfg.get('connector') if isinstance(cfg, dict) else None
            if isinstance(spec, dict) and spec.get('connection') not in ids:
                orphans.append(name)
        with _bulk(registry):
            for name in orphans:
                _unload(registry, name)
                _remove(name)
                _unload(registry, name)
        if orphans:
            _reindex(registry)
    return {'success': not errors, 'connections': results, 'errors': errors, 'orphans_removed': orphans}


def kinds() -> List[Dict[str, Any]]:
    from sajha.connectors.drivers import driver_installed
    out = []
    for kind, family in sorted(KINDS.items()):
        module, pip = _PACKAGES.get(kind, ('', ''))
        out.append({'kind': kind, 'name': _DIALECT_NAMES.get(kind, kind), 'family': family, 'module': module,
                    'pip': pip, 'installed': driver_installed(kind), 'per_user': kind in PER_USER_KINDS})
    return out


def list_connections(registry=None) -> List[Dict[str, Any]]:
    from sajha.connectors.drivers import driver_installed
    out = []
    for cid in store.ids():
        raw = store.load_raw(cid) or {}
        conn, err = store.get(cid)
        tools = _owned_names(cid, registry)
        out.append({
            'id': cid, 'title': raw.get('title') or cid, 'kind': raw.get('kind'), 'enabled': raw.get('enabled', True),
            'valid': conn is not None, 'error': err, 'description': raw.get('description') or '',
            'installed': driver_installed(str(raw.get('kind') or '')),
            'per_user': bool(conn and conn.per_user), 'views': len(raw.get('views') or []),
            'tools': [{'name': t, 'loaded': registry is not None and t in registry.tools} for t in tools],
            'limits': raw.get('limits') or {}, 'masking': len(raw.get('masking') or []),
            'updated_at': raw.get('updated_at'), 'updated_by': raw.get('updated_by'),
            'idle_connections': pool.stats().get(cid, 0),
        })
    return out


def get(cid: str) -> Dict[str, Any]:
    raw = store.load_raw(cid)
    if raw is None:
        raise ConnectorServiceError(f'no connection {cid!r}')
    return raw


def _conn(cid: str) -> Connection:
    conn, err = store.get(cid)
    if conn is None:
        raise ConnectorServiceError(err)
    return conn


def refresh(cid: str) -> Dict[str, Any]:
    from sajha.connectors import engine, vector
    conn = _conn(cid)
    catalog.invalidate(cid)
    if conn.family == 'sql':
        tables, truncated = engine.allowed_tables(conn, refresh=True)
    else:
        tables, truncated = vector._allowed(conn, refresh=True), False
    return {'success': True, 'connection': cid, 'tables': len(tables), 'truncated': truncated}


def tables(cid: str) -> Dict[str, Any]:
    from sajha.connectors import engine, vector
    conn = _conn(cid)
    if conn.family == 'sql':
        items, truncated = engine.allowed_tables(conn)
    else:
        items, truncated = vector._allowed(conn), False
    return {'success': True, 'connection': cid, 'family': conn.family, 'truncated': truncated,
            'tables': [{'schema': t.get('schema') or '', 'name': t['name'], 'type': t.get('type') or '',
                        'comment': t.get('comment') or ''} for t in items]}


def describe(cid: str, table: str) -> Dict[str, Any]:
    from sajha.connectors import engine, vector
    conn = _conn(cid)
    if conn.family == 'sql':
        return dict(engine.describe_table(conn, table, tool='admin:describe'), success=True)
    return dict(vector.describe_collection(conn, table, tool='admin:describe'), success=True)


def view_schema_preview(data: Dict[str, Any]) -> Dict[str, Any]:
    """The input schema a view would get (for the page's view builder), without saving."""
    from sajha.connectors.engine import view_input_schema
    try:
        conn = parse(data.get('connection') or {})
    except ConnectorConfigError as e:
        raise ConnectorServiceError(str(e))
    if not conn.views:
        raise ConnectorServiceError('no view to preview')
    v: View = conn.views[-1]
    details, _w = _view_details(conn)
    return {'success': True, 'tool': f'{conn.id}__{v.name}', 'inputSchema': view_input_schema(conn, v,
                                                                                            details.get(v.table))}
