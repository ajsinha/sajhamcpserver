"""
SAJHA MCP Server — federation configuration.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``FederationSettings`` (the ``federation.*`` keys) and ``UpstreamConfig`` (one upstream,
parsed and validated). Design and every field: docs/architecture/Federation.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: An upstream id: a letter, then letters, digits, '-' or '_'; no '__' (the separator).
UPSTREAM_ID = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
#: The namespace separator between an upstream's prefix and its own name.
SEPARATOR = '__'
#: MCP tool-name rules (2025-11-25): 1-128 of these characters.
TOOL_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,128}$')

TRANSPORTS = ('streamable_http', 'sse', 'stdio')
PROTOCOLS = ('auto', 'legacy', '2026-07-28')
ON_CHANGE = ('withdraw', 'hold')
#: credential modes: one shared identity ('static' = 'none' plus fixed ``headers``; bearer, header,
#: oauth_client_credentials), the caller's connected account, or per-user sign-in for proxied servers
#: (token_user, oauth_user), or a shared service identity naming the SAJHA user in an audit header
#: (service_with_user). See sajha/federation/user_tokens.py and sajha/federation/oauth_user.py.
AUTH_TYPES = ('none', 'static', 'bearer', 'header', 'oauth_client_credentials', 'connected_account',
              'token_user', 'oauth_user', 'service_with_user')
#: service_with_user: the header that names the SAJHA user, and its value (``{user}`` is the user id)
DEFAULT_USER_HEADER = 'X-SAJHA-User'
DEFAULT_USER_FORMAT = '{user}'
_HEADER_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,63}$')
#: headers service_with_user must never use for the user's name (credentials and hop-by-hop)
_RESERVED_HEADERS = {'authorization', 'proxy-authorization', 'cookie', 'host', 'content-type', 'content-length',
                     'mcp-session-id', 'mcp-protocol-version', 'x-api-key', 'api-key'}
#: gateway scale: shared connections per upstream (per replica) in a worker, and replicas per upstream
POOL_MAX = 32
REPLICAS_MAX = 16
#: what a connected_account upstream may use for discovery (tools/list) when no user is calling
DISCOVERY_AUTH_TYPES = ('none', 'bearer', 'header', 'oauth_client_credentials')


class ConfigError(ValueError):
    """An upstream definition is invalid."""


# ── settings ────────────────────────────────────────────────────────

@dataclass
class FederationSettings:
    enabled: bool = False
    require_approval: bool = True
    allow_stdio: bool = False
    allow_localhost: bool = False
    allow_private_networks: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    refresh_interval_seconds: int = 300
    startup_wait_seconds: float = 5.0
    default_timeout_seconds: float = 30.0
    max_description_chars: int = 1024
    state_path: str = 'config/federation/federation.json'
    upstreams: List[Dict[str, Any]] = field(default_factory=list)
    mcp_servers_file: str = ''           # the mcpServers JSON file ('' : none); see sajha/federation/mcp_servers.py
    mcp_servers_reload_seconds: float = 5.0
    per_user_session_idle_seconds: float = 900.0   # token_user, session-based upstreams: close a user's idle session
    per_user_sessions_max: int = 50                # token_user: open per-user sessions per upstream (oldest idle evicted)
    # gateway scale (sajha/federation/scale.py): defaults for every upstream, each overridable per upstream
    pool_size: int = 1                   # shared connections per upstream (and per replica) in each worker
    max_in_flight: int = 0               # calls in flight per upstream in each worker; 0 = no limit
    max_queue: int = 64                  # calls waiting for a slot when max_in_flight is reached
    queue_timeout_seconds: float = 5.0   # longest wait for a slot before the call is refused
    health_publish_seconds: float = 5.0  # how often this worker publishes its view of each upstream
    health_ttl_seconds: float = 30.0     # a worker's published view expires after this
    follow_peer_breakers: bool = True    # a breaker another worker opened opens this worker's too

    @classmethod
    def load(cls) -> 'FederationSettings':
        """``federation.*`` through SAJHA's usual resolution; the upstream list from the
        YAML as nested data (or ``SAJHA_FEDERATION_UPSTREAMS``, a JSON list)."""
        from sajha.core.config import _bool, _get, _int, _list

        def _float(key, default):
            try:
                return float(_get(key, str(default)) or default)
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=_bool('federation.enabled', False),
            require_approval=_bool('federation.require_approval', True),
            allow_stdio=_bool('federation.allow_stdio', False),
            allow_localhost=_bool('federation.allow_localhost', False),
            allow_private_networks=_bool('federation.allow_private_networks', False),
            allowed_hosts=_list('federation.allowed_hosts', []),
            refresh_interval_seconds=max(0, _int('federation.refresh_interval_seconds', 300)),
            startup_wait_seconds=max(0.0, _float('federation.startup_wait_seconds', 5.0)),
            default_timeout_seconds=max(1.0, _float('federation.default_timeout_seconds', 30.0)),
            max_description_chars=max(64, _int('federation.max_description_chars', 1024)),
            state_path=(_get('federation.state_path', 'config/federation/federation.json')
                        or 'config/federation/federation.json'),
            upstreams=_configured_upstreams(),
            mcp_servers_file=str(_get('federation.mcp_servers_file', 'config/mcp_servers.json') or ''),
            mcp_servers_reload_seconds=max(1.0, _float('federation.mcp_servers_reload_seconds', 5.0)),
            per_user_session_idle_seconds=max(1.0, _float('federation.per_user_session_idle_seconds', 900.0)),
            per_user_sessions_max=max(1, _int('federation.per_user_sessions_max', 50)),
            pool_size=max(1, min(POOL_MAX, _int('federation.pool_size', 1))),
            max_in_flight=max(0, _int('federation.max_in_flight', 0)),
            max_queue=max(0, _int('federation.max_queue', 64)),
            queue_timeout_seconds=max(0.0, _float('federation.queue_timeout_seconds', 5.0)),
            health_publish_seconds=max(0.5, _float('federation.health.publish_seconds', 5.0)),
            health_ttl_seconds=max(1.0, _float('federation.health.ttl_seconds', 30.0)),
            follow_peer_breakers=_bool('federation.health.follow_peer_breakers', True),
        )


def _configured_upstreams() -> List[Dict[str, Any]]:
    raw = os.environ.get('SAJHA_FEDERATION_UPSTREAMS')
    if raw is not None:
        try:
            value = json.loads(raw or '[]')
            return [u for u in value if isinstance(u, dict)] if isinstance(value, list) else []
        except ValueError:
            logger.warning('SAJHA_FEDERATION_UPSTREAMS is not a JSON list; ignored')
            return []
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:      # the main config loader reports a broken file too
        logger.warning(f'federation: cannot read {path}: {e}')
        return []
    ups = ((data.get('federation') or {}).get('upstreams')) or []
    return [_substitute(u) for u in ups if isinstance(u, dict)]


def _substitute(value):
    from sajha.core.config import _substitute_vars
    if isinstance(value, str):
        return _substitute_vars(value)
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    return value


# ── one upstream ────────────────────────────────────────────────────

@dataclass
class UpstreamConfig:
    id: str
    url: str = ''
    title: str = ''
    enabled: bool = True
    transport: str = 'streamable_http'
    protocol: str = 'auto'
    prefix: str = ''
    auth: Dict[str, Any] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: Optional[float] = None
    retries: int = 1
    max_calls_per_minute: int = 0
    cache_ttl: int = 0
    cache_per_user: Optional[bool] = None    # None: cache.per_user_federated (default true)
    breaker: Dict[str, Any] = field(default_factory=dict)
    refresh_interval_seconds: Optional[int] = None
    include_tools: List[str] = field(default_factory=list)
    exclude_tools: List[str] = field(default_factory=list)
    expose_prompts: bool = False
    expose_resources: bool = False
    auto_approve: bool = False
    on_change: str = 'withdraw'      # withdraw | hold: what serves while a changed definition waits
    command: str = ''
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    env_refs: Dict[str, str] = field(default_factory=dict)
    cwd: str = ''
    urls: List[str] = field(default_factory=list)   # replicas: more URLs serving this same upstream
    pool_size: Optional[int] = None                 # None: federation.pool_size
    max_in_flight: Optional[int] = None             # None: federation.max_in_flight (0 = no limit)
    max_queue: Optional[int] = None                 # None: federation.max_queue
    source: str = 'config'          # 'config' (application.yml / env) or 'store' (admin page)

    FIELDS = ('id', 'url', 'title', 'enabled', 'transport', 'protocol', 'prefix', 'auth', 'headers',
              'timeout_seconds', 'retries', 'max_calls_per_minute', 'cache_ttl', 'cache_per_user', 'breaker',
              'refresh_interval_seconds', 'include_tools', 'exclude_tools', 'expose_prompts',
              'expose_resources', 'auto_approve', 'on_change', 'command', 'args', 'env', 'env_refs', 'cwd',
              'urls', 'pool_size', 'max_in_flight', 'max_queue')

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source: str = 'config') -> 'UpstreamConfig':
        if not isinstance(data, dict):
            raise ConfigError('an upstream must be an object')
        unknown = set(data) - set(cls.FIELDS) - {'source'}
        if unknown:
            raise ConfigError(f'unknown upstream field(s): {", ".join(sorted(unknown))}')
        from sajha.core.config import parse_bool

        def _b(key, default):
            return parse_bool(data.get(key), default) if key in data else default

        def _i(key, default):
            v = data.get(key, default)
            try:
                return int(v) if v not in (None, '') else default
            except (TypeError, ValueError):
                raise ConfigError(f'{key} must be an integer')

        def _f(key):
            v = data.get(key)
            if v in (None, ''):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                raise ConfigError(f'{key} must be a number')

        def _lst(key):
            v = data.get(key) or []
            if isinstance(v, str):
                v = [x.strip() for x in v.split(',') if x.strip()]
            if not isinstance(v, list):
                raise ConfigError(f'{key} must be a list')
            return [str(x) for x in v]

        def _d(key):
            v = data.get(key) or {}
            if not isinstance(v, dict):
                raise ConfigError(f'{key} must be an object')
            return dict(v)

        cfg = cls(
            id=str(data.get('id') or '').strip(),
            url=str(data.get('url') or '').strip(),
            title=str(data.get('title') or '').strip(),
            enabled=_b('enabled', True),
            transport=str(data.get('transport') or 'streamable_http').strip(),
            protocol=str(data.get('protocol') or 'auto').strip(),
            prefix=str(data.get('prefix') or '').strip(),
            auth=({'type': data['auth'].strip()} if isinstance(data.get('auth'), str) and data['auth'].strip()
                  else _d('auth')),        # "auth": "token_user" is short for {"type": "token_user"}
            headers={str(k): str(v) for k, v in _d('headers').items()},
            timeout_seconds=_f('timeout_seconds'),
            retries=max(0, min(5, _i('retries', 1))),
            max_calls_per_minute=max(0, _i('max_calls_per_minute', 0)),
            cache_ttl=max(0, _i('cache_ttl', 0)),
            cache_per_user=(None if data.get('cache_per_user') in (None, '')
                            else parse_bool(data.get('cache_per_user'), True)),
            breaker=_d('breaker'),
            refresh_interval_seconds=(None if data.get('refresh_interval_seconds') in (None, '')
                                      else max(0, _i('refresh_interval_seconds', 0))),
            include_tools=_lst('include_tools'),
            exclude_tools=_lst('exclude_tools'),
            expose_prompts=_b('expose_prompts', False),
            expose_resources=_b('expose_resources', False),
            auto_approve=_b('auto_approve', False),
            on_change=str(data.get('on_change') or 'withdraw').strip(),
            command=str(data.get('command') or '').strip(),
            args=_lst('args'),
            env={str(k): str(v) for k, v in _d('env').items()},
            env_refs={str(k): str(v) for k, v in _d('env_refs').items()},
            cwd=str(data.get('cwd') or '').strip(),
            urls=[u.strip() for u in _lst('urls') if u.strip()],
            pool_size=None if data.get('pool_size') in (None, '') else _i('pool_size', 1),
            max_in_flight=None if data.get('max_in_flight') in (None, '') else _i('max_in_flight', 0),
            max_queue=None if data.get('max_queue') in (None, '') else _i('max_queue', 0),
            source=source,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not UPSTREAM_ID.match(self.id) or SEPARATOR in self.id:
            raise ConfigError('id must be 1-32 characters: a lower-case letter, then lower-case letters, '
                              'digits, "-" or "_", without "__"')
        prefix = self.prefix or self.id
        if not re.match(r'^[A-Za-z][A-Za-z0-9_-]{0,31}$', prefix) or SEPARATOR in prefix or prefix.endswith('_'):
            raise ConfigError('prefix must be 1-32 characters: a letter, then letters, digits, "-" or "_", '
                              'without "__" and not ending in "_"')
        if self.on_change not in ON_CHANGE:
            raise ConfigError(f'on_change must be one of {", ".join(ON_CHANGE)}')
        if self.transport not in TRANSPORTS:
            raise ConfigError(f'transport must be one of {", ".join(TRANSPORTS)}')
        if self.protocol not in PROTOCOLS:
            raise ConfigError(f'protocol must be one of {", ".join(PROTOCOLS)}')
        if self.transport == 'stdio':
            if not self.command:
                raise ConfigError('a stdio upstream needs a command')
        elif not self.url:
            raise ConfigError('an HTTP upstream needs a url')
        atype = (self.auth or {}).get('type', 'none') or 'none'
        if atype not in AUTH_TYPES:
            raise ConfigError(f'auth.type must be one of {", ".join(AUTH_TYPES)}')
        for key, value in (self.auth or {}).items():
            if key.endswith('_ref') and value and not _is_ref(value):
                raise ConfigError(f'auth.{key} must be a secret reference (env:NAME, file:/path or db:table/key)')
            if key in ('token', 'value', 'client_secret', 'password', 'api_key'):
                raise ConfigError(f'auth.{key}: put secrets in a reference ({key}_ref: env:NAME), not in the config')
        if atype == 'bearer' and not self.auth.get('token_ref'):
            raise ConfigError('auth.type bearer needs token_ref')
        if atype == 'header' and not (self.auth.get('header') and self.auth.get('value_ref')):
            raise ConfigError('auth.type header needs header and value_ref')
        if atype == 'oauth_client_credentials' and not (self.auth.get('token_url') and self.auth.get('client_id')
                                                         and self.auth.get('client_secret_ref')):
            raise ConfigError('auth.type oauth_client_credentials needs token_url, client_id and client_secret_ref')
        if atype == 'connected_account':
            self._validate_connected_account()
        if atype in ('token_user', 'oauth_user'):
            self._validate_per_user(atype)
        if atype == 'service_with_user':
            self._validate_service_with_user()
        if atype == 'static' and set(self.auth) - {'type'}:
            raise ConfigError('auth.type static takes no other fields: the shared credential goes in headers')
        for name, ref in self.env_refs.items():
            if not _is_ref(ref):
                raise ConfigError(f'env_refs.{name} must be a secret reference')
        if self.urls:
            if self.transport == 'stdio':
                raise ConfigError('urls (replicas) needs an HTTP transport')
            if len(self.urls) > REPLICAS_MAX - 1:
                raise ConfigError(f'urls: at most {REPLICAS_MAX - 1} replicas besides url')
            for u in self.urls:
                if not re.match(r'^https?://', u, re.I):
                    raise ConfigError(f'urls: {u} is not an http or https URL')
            if len(set(self.replica_urls)) != len(self.replica_urls):
                raise ConfigError('urls: each replica URL must differ from url and from the others')
        if self.pool_size is not None and not (1 <= self.pool_size <= POOL_MAX):
            raise ConfigError(f'pool_size must be between 1 and {POOL_MAX}')
        if self.max_in_flight is not None and self.max_in_flight < 0:
            raise ConfigError('max_in_flight must be 0 (no limit) or more')
        if self.max_queue is not None and self.max_queue < 0:
            raise ConfigError('max_queue must be 0 or more')
        if self.timeout_seconds is not None and not (0 < self.timeout_seconds <= 3600):
            raise ConfigError('timeout_seconds must be between 0 and 3600')

    def _validate_connected_account(self) -> None:
        """auth.type connected_account: each call carries the caller's own token for ``provider``
        (sajha/accounts); ``discovery`` is the credential for tools/list, if the upstream needs one."""
        a = self.auth
        if not isinstance(a.get('provider'), str) or not a.get('provider'):
            raise ConfigError('auth.type connected_account needs provider (a connected-accounts provider id)')
        scopes = a.get('scopes', [])
        if isinstance(scopes, str):
            a['scopes'] = scopes.replace(',', ' ').split()
        elif not isinstance(scopes, list):
            raise ConfigError('auth.scopes must be a list')
        if self.transport == 'stdio':
            raise ConfigError('auth.type connected_account needs an HTTP transport (a token per call)')
        if self.cache_ttl:
            raise ConfigError('cache_ttl cannot be used with auth.type connected_account: results are per user')
        disc = a.get('discovery') or {}
        if not isinstance(disc, dict):
            raise ConfigError('auth.discovery must be an object (the credential used for tools/list)')
        dtype = disc.get('type', 'none') or 'none'
        if dtype not in DISCOVERY_AUTH_TYPES:
            raise ConfigError(f'auth.discovery.type must be one of {", ".join(DISCOVERY_AUTH_TYPES)}')
        for key, value in disc.items():
            if key.endswith('_ref') and value and not _is_ref(value):
                raise ConfigError(f'auth.discovery.{key} must be a secret reference (env:NAME, file:/path or db:table/key)')
            if key in ('token', 'value', 'client_secret', 'password', 'api_key'):
                raise ConfigError(f'auth.discovery.{key}: put secrets in a reference ({key}_ref: env:NAME)')
        unknown = set(a) - {'type', 'provider', 'scopes', 'discovery'}
        if unknown:
            raise ConfigError(f'auth: unknown field(s) for connected_account: {", ".join(sorted(unknown))}')

    def _validate_service_with_user(self) -> None:
        """service_with_user: the shared service identity (``service``, one of the discovery credential
        types, or the shared ``headers``) with the calling SAJHA user named in ``user_header`` on every
        tool call (``user_format``, where ``{user}`` is the user id)."""
        a = self.auth
        unknown = set(a) - {'type', 'service', 'user_header', 'user_format'}
        if unknown:
            raise ConfigError(f'auth: unknown field(s) for service_with_user: {", ".join(sorted(unknown))}')
        if self.transport == 'stdio':
            raise ConfigError('auth.type service_with_user needs an HTTP transport (a header per call)')
        if self.cache_ttl:
            raise ConfigError('cache_ttl cannot be used with auth.type service_with_user: results are per user')
        svc = a.get('service') or {}
        if not isinstance(svc, dict):
            raise ConfigError('auth.service must be an object (the shared service credential)')
        stype = svc.get('type', 'none') or 'none'
        if stype not in DISCOVERY_AUTH_TYPES:
            raise ConfigError(f'auth.service.type must be one of {", ".join(DISCOVERY_AUTH_TYPES)}')
        for key, value in svc.items():
            if key.endswith('_ref') and value and not _is_ref(value):
                raise ConfigError(f'auth.service.{key} must be a secret reference (env:NAME, file:/path or db:table/key)')
            if key in ('token', 'value', 'client_secret', 'password', 'api_key'):
                raise ConfigError(f'auth.service.{key}: put secrets in a reference ({key}_ref: env:NAME)')
        if stype == 'bearer' and not svc.get('token_ref'):
            raise ConfigError('auth.service type bearer needs token_ref')
        if stype == 'header' and not (svc.get('header') and svc.get('value_ref')):
            raise ConfigError('auth.service type header needs header and value_ref')
        if stype == 'oauth_client_credentials' and not (svc.get('token_url') and svc.get('client_id')
                                                        and svc.get('client_secret_ref')):
            raise ConfigError('auth.service type oauth_client_credentials needs token_url, client_id and '
                              'client_secret_ref')
        header = a.get('user_header') or DEFAULT_USER_HEADER
        if not isinstance(header, str) or not _HEADER_NAME.match(header) or header.lower() in _RESERVED_HEADERS:
            raise ConfigError('auth.user_header must be a plain header name (letters, digits, "-"), not a '
                              'credential or protocol header')
        if any(k.lower() == header.lower() for k in self.headers or {}):
            raise ConfigError(f'headers.{header} conflicts with auth.user_header: each call names its own user there')
        if stype == 'header' and str(svc.get('header', '')).lower() == header.lower():
            raise ConfigError('auth.user_header and auth.service.header must differ')
        fmt = a.get('user_format') or DEFAULT_USER_FORMAT
        if not isinstance(fmt, str) or '{user}' not in fmt or len(fmt) > 200 \
                or fmt.replace('{user}', '').count('{') or fmt.replace('{user}', '').count('}'):
            raise ConfigError('auth.user_format must contain {user} (the SAJHA user id) and no other placeholder')

    def _validate_per_user(self, atype: str) -> None:
        """token_user: each call carries the caller's own personal token (sajha/federation/user_tokens.py);
        oauth_user: the caller's own OAuth access token (sajha/federation/oauth_user.py). ``discovery`` is
        the credential for tools/list."""
        a = self.auth
        if self.transport == 'stdio':
            raise ConfigError(f'auth.type {atype} needs an HTTP transport (a credential per user)')
        if self.cache_ttl:
            raise ConfigError(f'cache_ttl cannot be used with auth.type {atype}: results are per user')
        disc = a.get('discovery') or {}
        if not isinstance(disc, dict):
            raise ConfigError('auth.discovery must be an object (the credential used for tools/list)')
        dtype = disc.get('type', 'none') or 'none'
        if dtype not in DISCOVERY_AUTH_TYPES:
            raise ConfigError(f'auth.discovery.type must be one of {", ".join(DISCOVERY_AUTH_TYPES)}')
        for key, value in disc.items():
            if key.endswith('_ref') and value and not _is_ref(value):
                raise ConfigError(f'auth.discovery.{key} must be a secret reference (env:NAME, file:/path or db:table/key)')
            if key in ('token', 'value', 'client_secret', 'password', 'api_key'):
                raise ConfigError(f'auth.discovery.{key}: put secrets in a reference ({key}_ref: env:NAME)')
        if atype == 'oauth_user':
            from sajha.federation.oauth_user import OAuthUserSpec
            unknown = set(a) - set(OAuthUserSpec.KEYS)
            if unknown:
                raise ConfigError(f'auth: unknown field(s) for oauth_user: {", ".join(sorted(unknown))}')
            if 'client_secret' in a:
                raise ConfigError('auth.client_secret: put the secret in a reference (client_secret_ref: env:NAME)')
            problems = OAuthUserSpec.from_auth(a).problems()
            if problems:
                raise ConfigError(problems[0])
            if any(k.lower() == 'authorization' for k in self.headers or {}):
                raise ConfigError('headers.Authorization conflicts with auth.type oauth_user: each user\'s own '
                                  'access token is sent in Authorization')
            return
        from sajha.federation.user_tokens import TokenUserSpec
        unknown = set(a) - set(TokenUserSpec.KEYS)
        if unknown:
            raise ConfigError(f'auth: unknown field(s) for token_user: {", ".join(sorted(unknown))}')
        spec = TokenUserSpec.from_auth(a)
        problems = spec.problems()
        if problems:
            raise ConfigError(problems[0])
        if any(k.lower() == spec.header.lower() for k in self.headers or {}):
            raise ConfigError(f'headers.{spec.header} conflicts with auth.header: a token_user upstream never sends a '
                              f'shared value in the header that carries each user\'s token')

    @property
    def replica_urls(self) -> List[str]:
        """``url`` and then the replicas in ``urls`` (one entry for stdio)."""
        return [self.url] + [u for u in self.urls] if self.transport != 'stdio' else [self.url]

    @property
    def effective_prefix(self) -> str:
        return self.prefix or self.id

    @property
    def display_title(self) -> str:
        return self.title or self.id

    def to_dict(self) -> Dict[str, Any]:
        """The definition as stored and shown: references, never resolved secrets."""
        d = asdict(self)
        d.pop('source', None)
        return {k: v for k, v in d.items() if v not in (None, '', [], {}) or k in ('id', 'enabled')}


def _is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.split(':', 1)[0].lower() in ('env', 'file', 'db') and ':' in value


# ── names ───────────────────────────────────────────────────────────

def namespaced(prefix: str, name: str) -> str:
    """``<prefix>__<tool part>``: every character outside ``[A-Za-z0-9_-]`` becomes ``_`` (MCP
    allows ``.``, but not every LLM provider does; ``names.tool_part``), at most 128 characters."""
    from sajha.federation.names import tool_part
    return f'{prefix}{SEPARATOR}{tool_part(name)}'[:128]
