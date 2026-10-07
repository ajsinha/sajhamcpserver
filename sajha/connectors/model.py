"""
SAJHA MCP Server — Data Connectors: the connection record.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:func:`parse` turns a record (the JSON document at ``config/connectors/<id>.json``, or what the
admin page posts) into a validated :class:`Connection`, or raises :class:`ConnectorConfigError`
with the field at fault. Credentials are accepted only as secret references (``env:``,
``file:``, ``db:``). Design: docs/architecture/Data Connectors.md, section 3.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.connectors import settings

#: kind -> family. 'sql' kinds get list/describe/query (+ views); 'search' kinds get
#: list_collections/describe_collection/search.
KINDS: Dict[str, str] = {
    'postgresql': 'sql', 'pgvector': 'sql', 'redshift': 'sql', 'mysql': 'sql', 'mariadb': 'sql',
    'sqlserver': 'sql', 'oracle': 'sql', 'snowflake': 'sql', 'bigquery': 'sql', 'databricks': 'sql',
    'sqlite': 'sql', 'duckdb': 'sql',
    'qdrant': 'search', 'elasticsearch': 'search', 'opensearch': 'search',
}
#: kinds that can sign in as each user through a connected account
PER_USER_KINDS = ('snowflake', 'bigquery', 'databricks')
FILE_KINDS = ('sqlite', 'duckdb')
MASK_MODES = ('hide', 'null', 'redact', 'hash', 'partial', 'pii')
VIEW_OPERATORS = ('eq', 'in', 'gte', 'lte', 'gt', 'lt', 'contains')
TOOL_SWITCHES = ('list_tables', 'describe_table', 'query', 'search')
DISTANCES = ('cosine', 'l2', 'inner')

_ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
_VIEW_NAME = re.compile(r'^[a-z][a-z0-9_]{0,47}$')
_RESERVED_TOOL_NAMES = ('list_tables', 'describe_table', 'query', 'search', 'list_collections',
                        'describe_collection')
#: option keys that hold credentials: they belong under ``secrets`` as references
_SECRETISH = re.compile(r'(pass(word|wd|phrase)?|secret|token|private_?key|api_?key|credentials?(_json)?|'
                        r'access_?key|pwd)$', re.IGNORECASE)


class ConnectorConfigError(ValueError):
    """A connection record is not valid; the message names the field."""


def is_secret_ref(value: Any) -> bool:
    if not isinstance(value, str) or ':' not in value:
        return False
    scheme, rest = value.split(':', 1)
    return scheme.lower() in ('env', 'file', 'db') and bool(rest.strip())


@dataclass
class MaskRule:
    pattern: str            # glob over column | table.column | schema.table.column (lower case)
    mode: str

    @property
    def column_glob(self) -> str:
        return self.pattern.rsplit('.', 1)[-1]

    @property
    def table_glob(self) -> Optional[str]:
        parts = self.pattern.split('.')
        return '.'.join(parts[:-1]) if len(parts) > 1 else None

    def applies(self, column: str, tables: List[Tuple[str, str]]) -> bool:
        """Does this rule mask ``column`` in a result that reads ``tables`` [(schema, table)]?"""
        if not fnmatch.fnmatchcase(column.lower(), self.column_glob):
            return False
        tg = self.table_glob
        if tg is None:
            return True
        for schema, table in tables:
            full = f'{schema}.{table}'.lower() if schema else table.lower()
            if fnmatch.fnmatchcase(table.lower(), tg) or fnmatch.fnmatchcase(full, tg):
                return True
        return False


@dataclass
class ViewFilter:
    column: str
    operators: List[str]
    required: bool = False
    enum: List[Any] = field(default_factory=list)
    description: str = ''


@dataclass
class View:
    name: str
    table: str
    title: str = ''
    description: str = ''
    columns: List[str] = field(default_factory=list)
    filters: List[ViewFilter] = field(default_factory=list)
    order_by: List[Tuple[str, str]] = field(default_factory=list)
    max_rows: int = 0


@dataclass
class Connection:
    id: str
    kind: str
    title: str = ''
    description: str = ''
    enabled: bool = True
    options: Dict[str, Any] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    max_rows: int = 0
    max_bytes: int = 0
    timeout_seconds: int = 0
    allow_schemas: List[str] = field(default_factory=list)
    allow_tables: List[str] = field(default_factory=lambda: ['*'])
    deny_tables: List[str] = field(default_factory=list)
    masking: List[MaskRule] = field(default_factory=list)
    tools: Dict[str, bool] = field(default_factory=dict)
    views: List[View] = field(default_factory=list)
    vector: Dict[str, Any] = field(default_factory=dict)
    auth: Optional[Dict[str, Any]] = None
    cache_ttl: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def family(self) -> str:
        return KINDS[self.kind]

    @property
    def per_user(self) -> bool:
        return bool(self.auth and self.auth.get('type') == 'connected_account')

    @property
    def label(self) -> str:
        return self.title or self.id

    def tool_enabled(self, switch: str) -> bool:
        return bool(self.tools.get(switch, True))

    def fingerprint(self) -> str:
        """Hash of everything that decides how a connection is opened (the pool key)."""
        basis = {'kind': self.kind, 'options': self.options, 'secrets': self.secrets, 'auth': self.auth,
                 'timeout': self.timeout_seconds, 'schemas': self.allow_schemas}
        return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]

    # ── allowlist ─────────────────────────────────────────────────────
    def table_allowed(self, schema: str, table: str) -> bool:
        s, t = (schema or '').lower(), (table or '').lower()
        if self.allow_schemas and s not in [x.lower() for x in self.allow_schemas] and \
                not (not s and self.kind in FILE_KINDS):
            return False
        full = f'{s}.{t}' if s else t

        def hit(patterns):
            return any(fnmatch.fnmatchcase(t, p.lower()) or fnmatch.fnmatchcase(full, p.lower())
                       for p in patterns)
        if self.deny_tables and hit(self.deny_tables):
            return False
        return hit(self.allow_tables or ['*'])

    def mask_rules_for(self, column: str, tables: List[Tuple[str, str]]) -> Optional[MaskRule]:
        for rule in self.masking:
            if rule.applies(column, tables):
                return rule
        return None


# ── parsing ─────────────────────────────────────────────────────────────

def _str(d: Dict[str, Any], key: str, where: str, maxlen: int = 500, default: str = '') -> str:
    v = d.get(key, default)
    if v is None:
        return default
    if not isinstance(v, (str, int, float)):
        raise ConnectorConfigError(f'{where}.{key}: expected text')
    v = str(v).strip()
    if len(v) > maxlen:
        raise ConnectorConfigError(f'{where}.{key}: at most {maxlen} characters')
    return v


def _str_list(v: Any, where: str) -> List[str]:
    if v is None or v == '':
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r'[,\n]', v)]
    if not isinstance(v, list) or not all(isinstance(x, (str, int, float)) for x in v):
        raise ConnectorConfigError(f'{where}: expected a list of names')
    return [str(x).strip() for x in v if str(x).strip()]


def _int(v: Any, where: str, lo: int, hi: int, default: int) -> int:
    if v is None or v == '':
        return default
    if isinstance(v, bool):
        raise ConnectorConfigError(f'{where}: expected a whole number')
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ConnectorConfigError(f'{where}: expected a whole number') from None
    if n < lo:
        raise ConnectorConfigError(f'{where}: at least {lo}')
    return min(n, hi)


def _unknown(d: Dict[str, Any], allowed, where: str) -> None:
    extra = sorted(set(d) - set(allowed))
    if extra:
        raise ConnectorConfigError(f'{where}: unknown field(s) {", ".join(extra)}')


def _options(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConnectorConfigError('options: expected an object')
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not re.match(r'^[A-Za-z_][A-Za-z0-9_.-]{0,63}$', k):
            raise ConnectorConfigError(f'options: invalid key {k!r}')
        if _SECRETISH.search(k):
            raise ConnectorConfigError(f'options.{k}: credentials go under "secrets" as a reference '
                                       f'(env:NAME, file:/path or db:...), never as a value')
        if isinstance(v, (dict, list)):
            if not isinstance(v, list) or not all(isinstance(x, (str, int, float, bool)) for x in v):
                if not isinstance(v, dict) or not all(isinstance(x, (str, int, float, bool)) for x in v.values()):
                    raise ConnectorConfigError(f'options.{k}: only text, numbers, booleans or flat lists/objects')
                for kk in v:
                    if _SECRETISH.search(str(kk)):
                        raise ConnectorConfigError(f'options.{k}.{kk}: credentials go under "secrets"')
        elif v is not None and not isinstance(v, (str, int, float, bool)):
            raise ConnectorConfigError(f'options.{k}: only text, numbers or booleans')
        if v is None or v == '':
            continue
        out[k] = v
    return out


def _secrets(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConnectorConfigError('secrets: expected an object of name -> secret reference')
    out = {}
    for k, v in raw.items():
        if v is None or v == '':
            continue
        if not is_secret_ref(v):
            raise ConnectorConfigError(f'secrets.{k}: must be a secret reference (env:NAME, file:/path or '
                                       f'db:llm_providers/<type>), never the secret itself')
        out[str(k)] = str(v).strip()
    return out


def _masking(raw: Any) -> List[MaskRule]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConnectorConfigError('masking: expected a list of {column, mode}')
    out = []
    for i, m in enumerate(raw):
        w = f'masking[{i}]'
        if not isinstance(m, dict):
            raise ConnectorConfigError(f'{w}: expected {{column, mode}}')
        _unknown(m, ('column', 'mode'), w)
        col = _str(m, 'column', w, 300).lower()
        if not col or not re.match(r'^[a-z0-9_*?\[\]$#.-]+$', col) or col.count('.') > 2:
            raise ConnectorConfigError(f'{w}.column: a glob over column, table.column or schema.table.column')
        mode = _str(m, 'mode', w, 20, 'redact').lower()
        if mode not in MASK_MODES:
            raise ConnectorConfigError(f'{w}.mode: one of {", ".join(MASK_MODES)}')
        out.append(MaskRule(col, mode))
    return out


def _views(raw: Any) -> List[View]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConnectorConfigError('views: expected a list')
    out: List[View] = []
    names = set()
    for i, v in enumerate(raw):
        w = f'views[{i}]'
        if not isinstance(v, dict):
            raise ConnectorConfigError(f'{w}: expected an object')
        _unknown(v, ('name', 'table', 'title', 'description', 'columns', 'filters', 'order_by', 'max_rows'), w)
        name = _str(v, 'name', w, 48).lower()
        if not _VIEW_NAME.match(name) or '__' in name or name in _RESERVED_TOOL_NAMES:
            raise ConnectorConfigError(f'{w}.name: lower case letters, digits and _, a letter first; '
                                       f'not a reserved tool name')
        if name in names:
            raise ConnectorConfigError(f'{w}.name: {name} is used twice')
        names.add(name)
        table = _str(v, 'table', w, 300)
        if not table:
            raise ConnectorConfigError(f'{w}.table: required')
        filters = []
        seen = set()
        for j, f in enumerate(v.get('filters') or []):
            fw = f'{w}.filters[{j}]'
            if not isinstance(f, dict):
                raise ConnectorConfigError(f'{fw}: expected {{column, operators}}')
            _unknown(f, ('column', 'operators', 'required', 'enum', 'description'), fw)
            col = _str(f, 'column', fw, 128)
            if not col:
                raise ConnectorConfigError(f'{fw}.column: required')
            if col.lower() in seen:
                raise ConnectorConfigError(f'{fw}.column: {col} is listed twice')
            seen.add(col.lower())
            ops = [o.lower() for o in _str_list(f.get('operators') or ['eq'], f'{fw}.operators')]
            bad = [o for o in ops if o not in VIEW_OPERATORS]
            if bad or not ops:
                raise ConnectorConfigError(f'{fw}.operators: from {", ".join(VIEW_OPERATORS)}')
            enum = f.get('enum') or []
            if not isinstance(enum, list) or not all(isinstance(x, (str, int, float, bool)) for x in enum):
                raise ConnectorConfigError(f'{fw}.enum: a list of values')
            filters.append(ViewFilter(col, list(dict.fromkeys(ops)), bool(f.get('required')), list(enum),
                                      _str(f, 'description', fw, 500)))
        order = []
        for j, o in enumerate(v.get('order_by') or []):
            if isinstance(o, str):
                o = {'column': o}
            if not isinstance(o, dict):
                raise ConnectorConfigError(f'{w}.order_by[{j}]: expected {{column, direction}}')
            d = str(o.get('direction') or 'asc').lower()
            if d not in ('asc', 'desc'):
                raise ConnectorConfigError(f'{w}.order_by[{j}].direction: asc or desc')
            col = _str(o, 'column', f'{w}.order_by[{j}]', 128)
            if not col:
                raise ConnectorConfigError(f'{w}.order_by[{j}].column: required')
            order.append((col, d))
        out.append(View(name=name, table=table, title=_str(v, 'title', w, 120),
                        description=_str(v, 'description', w, 2000),
                        columns=_str_list(v.get('columns'), f'{w}.columns'), filters=filters, order_by=order,
                        max_rows=_int(v.get('max_rows'), f'{w}.max_rows', 0, settings.max_rows_limit(), 0)))
    return out


def _vector(raw: Any, kind: str) -> Dict[str, Any]:
    if raw is None or raw == {}:
        if kind == 'pgvector':
            raise ConnectorConfigError('vector: a pgvector connection needs {table, vector_column, text_column}')
        return {}
    if not isinstance(raw, dict):
        raise ConnectorConfigError('vector: expected an object')
    _unknown(raw, ('table', 'vector_column', 'text_column', 'id_column', 'metadata_columns', 'distance',
                   'embedding_model', 'vector_name', 'vector_field', 'text_field', 'fields', 'num_candidates'),
             'vector')
    out = {k: v for k, v in raw.items() if v not in (None, '', [])}
    if kind == 'pgvector':
        for k in ('table', 'vector_column', 'text_column'):
            if not out.get(k):
                raise ConnectorConfigError(f'vector.{k}: required for pgvector')
    dist = str(out.get('distance') or 'cosine').lower()
    if dist not in DISTANCES:
        raise ConnectorConfigError(f'vector.distance: one of {", ".join(DISTANCES)}')
    out['distance'] = dist
    for k in ('metadata_columns', 'fields'):
        if k in out:
            out[k] = _str_list(out[k], f'vector.{k}')
    return out


def _auth(raw: Any, kind: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ConnectorConfigError('auth: expected {type: connected_account, provider, scopes}')
    _unknown(raw, ('type', 'provider', 'scopes'), 'auth')
    if raw.get('type') != 'connected_account':
        raise ConnectorConfigError('auth.type: only connected_account (per-user credentials) is supported; '
                                   'service credentials go under secrets')
    if kind not in PER_USER_KINDS:
        raise ConnectorConfigError(f'auth: per-user credentials are supported for {", ".join(PER_USER_KINDS)}, '
                                   f'not {kind}')
    provider = _str(raw, 'provider', 'auth', 64)
    if not provider:
        raise ConnectorConfigError('auth.provider: the connected-account provider id is required')
    import importlib.util
    try:
        available = importlib.util.find_spec('sajha.accounts') is not None
    except (ImportError, ValueError):
        available = False
    if not available:
        raise ConnectorConfigError('auth: per-user credentials need the connected-accounts feature '
                                   '(sajha.accounts), which is not installed')
    return {'type': 'connected_account', 'provider': provider,
            'scopes': _str_list(raw.get('scopes'), 'auth.scopes')}


TOP_FIELDS = ('id', 'kind', 'title', 'description', 'enabled', 'options', 'secrets', 'limits', 'allow', 'masking',
              'tools', 'views', 'vector', 'auth', 'cache_ttl', 'created_at', 'updated_at', 'updated_by')


def parse(raw: Any) -> Connection:
    if not isinstance(raw, dict):
        raise ConnectorConfigError('a connection is a JSON object')
    _unknown(raw, TOP_FIELDS, 'connection')
    cid = _str(raw, 'id', 'connection', 40)
    if not _ID.match(cid) or '__' in cid:
        raise ConnectorConfigError('id: lower case letters, digits and _, a letter first, at most 40 '
                                   'characters, no "__" (it is the tool prefix)')
    kind = _str(raw, 'kind', 'connection', 40).lower()
    if kind not in KINDS:
        raise ConnectorConfigError(f'kind: one of {", ".join(sorted(KINDS))}')
    options = _options(raw.get('options'))
    if kind in FILE_KINDS and not options.get('path'):
        raise ConnectorConfigError(f'options.path: the {kind} database file is required')
    limits = raw.get('limits') or {}
    if not isinstance(limits, dict):
        raise ConnectorConfigError('limits: expected {max_rows, max_bytes, timeout_seconds}')
    _unknown(limits, ('max_rows', 'max_bytes', 'timeout_seconds', 'max_bytes_billed'), 'limits')
    allow = raw.get('allow') or {}
    if not isinstance(allow, dict):
        raise ConnectorConfigError('allow: expected {schemas, tables, deny_tables}')
    _unknown(allow, ('schemas', 'tables', 'deny_tables'), 'allow')
    tools = raw.get('tools') or {}
    if not isinstance(tools, dict) or any(k not in TOOL_SWITCHES for k in tools):
        raise ConnectorConfigError(f'tools: switches from {", ".join(TOOL_SWITCHES)}')
    if 'max_bytes_billed' in limits:
        options = dict(options)
        options['maximum_bytes_billed'] = _int(limits['max_bytes_billed'], 'limits.max_bytes_billed', 0,
                                               2 ** 62, 0)
    conn = Connection(
        id=cid, kind=kind, title=_str(raw, 'title', 'connection', 200),
        description=_str(raw, 'description', 'connection', 2000),
        enabled=bool(raw.get('enabled', True)), options=options, secrets=_secrets(raw.get('secrets')),
        max_rows=_int(limits.get('max_rows'), 'limits.max_rows', 1, settings.max_rows_limit(),
                      min(settings.default_max_rows(), settings.max_rows_limit())),
        max_bytes=_int(limits.get('max_bytes'), 'limits.max_bytes', 1024, settings.max_bytes_limit(),
                       min(settings.default_max_bytes(), settings.max_bytes_limit())),
        timeout_seconds=_int(limits.get('timeout_seconds'), 'limits.timeout_seconds', 1,
                             settings.max_timeout_seconds(),
                             min(settings.default_timeout_seconds(), settings.max_timeout_seconds())),
        allow_schemas=_str_list(allow.get('schemas'), 'allow.schemas'),
        allow_tables=_str_list(allow.get('tables'), 'allow.tables') or ['*'],
        deny_tables=_str_list(allow.get('deny_tables'), 'allow.deny_tables'),
        masking=_masking(raw.get('masking')),
        tools={k: bool(v) for k, v in tools.items()},
        views=_views(raw.get('views')) if KINDS[kind] == 'sql' else [],
        vector=_vector(raw.get('vector'), kind),
        auth=_auth(raw.get('auth'), kind),
        cache_ttl=_int(raw.get('cache_ttl'), 'cache_ttl', 0, 86400, 0),
        raw=copy.deepcopy(raw),
    )
    if raw.get('views') and KINDS[kind] != 'sql':
        raise ConnectorConfigError('views: only SQL connections have curated views')
    return conn


def to_record(conn: Connection) -> Dict[str, Any]:
    """The normalised JSON record (what is stored)."""
    rec: Dict[str, Any] = {
        'id': conn.id, 'kind': conn.kind, 'title': conn.title, 'description': conn.description,
        'enabled': conn.enabled, 'options': {k: v for k, v in conn.options.items() if k != 'maximum_bytes_billed'},
        'secrets': dict(conn.secrets),
        'limits': {'max_rows': conn.max_rows, 'max_bytes': conn.max_bytes, 'timeout_seconds': conn.timeout_seconds},
        'allow': {'schemas': list(conn.allow_schemas), 'tables': list(conn.allow_tables),
                  'deny_tables': list(conn.deny_tables)},
        'masking': [{'column': m.pattern, 'mode': m.mode} for m in conn.masking],
        'tools': dict(conn.tools), 'cache_ttl': conn.cache_ttl,
    }
    if 'maximum_bytes_billed' in conn.options:
        rec['limits']['max_bytes_billed'] = conn.options['maximum_bytes_billed']
    if conn.views:
        rec['views'] = [{
            'name': v.name, 'table': v.table, 'title': v.title, 'description': v.description,
            'columns': list(v.columns),
            'filters': [{'column': f.column, 'operators': list(f.operators), 'required': f.required,
                         'enum': list(f.enum), 'description': f.description} for f in v.filters],
            'order_by': [{'column': c, 'direction': d} for c, d in v.order_by], 'max_rows': v.max_rows,
        } for v in conn.views]
    if conn.vector:
        rec['vector'] = dict(conn.vector)
    if conn.auth:
        rec['auth'] = dict(conn.auth)
    for k in ('created_at', 'updated_at', 'updated_by'):
        if conn.raw.get(k):
            rec[k] = conn.raw[k]
    return rec
