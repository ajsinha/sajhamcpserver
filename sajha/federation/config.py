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
_TOOL_NAME_BAD = re.compile(r'[^A-Za-z0-9_.-]')

TRANSPORTS = ('streamable_http', 'sse', 'stdio')
PROTOCOLS = ('auto', 'legacy', '2026-07-28')
AUTH_TYPES = ('none', 'bearer', 'header', 'oauth_client_credentials')


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
    breaker: Dict[str, Any] = field(default_factory=dict)
    refresh_interval_seconds: Optional[int] = None
    include_tools: List[str] = field(default_factory=list)
    exclude_tools: List[str] = field(default_factory=list)
    expose_prompts: bool = False
    expose_resources: bool = False
    auto_approve: bool = False
    command: str = ''
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    env_refs: Dict[str, str] = field(default_factory=dict)
    cwd: str = ''
    source: str = 'config'          # 'config' (application.yml / env) or 'store' (admin page)

    FIELDS = ('id', 'url', 'title', 'enabled', 'transport', 'protocol', 'prefix', 'auth', 'headers',
              'timeout_seconds', 'retries', 'max_calls_per_minute', 'cache_ttl', 'breaker',
              'refresh_interval_seconds', 'include_tools', 'exclude_tools', 'expose_prompts',
              'expose_resources', 'auto_approve', 'command', 'args', 'env', 'env_refs', 'cwd')

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
            auth=_d('auth'),
            headers={str(k): str(v) for k, v in _d('headers').items()},
            timeout_seconds=_f('timeout_seconds'),
            retries=max(0, min(5, _i('retries', 1))),
            max_calls_per_minute=max(0, _i('max_calls_per_minute', 0)),
            cache_ttl=max(0, _i('cache_ttl', 0)),
            breaker=_d('breaker'),
            refresh_interval_seconds=(None if data.get('refresh_interval_seconds') in (None, '')
                                      else max(0, _i('refresh_interval_seconds', 0))),
            include_tools=_lst('include_tools'),
            exclude_tools=_lst('exclude_tools'),
            expose_prompts=_b('expose_prompts', False),
            expose_resources=_b('expose_resources', False),
            auto_approve=_b('auto_approve', False),
            command=str(data.get('command') or '').strip(),
            args=_lst('args'),
            env={str(k): str(v) for k, v in _d('env').items()},
            env_refs={str(k): str(v) for k, v in _d('env_refs').items()},
            cwd=str(data.get('cwd') or '').strip(),
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
        for name, ref in self.env_refs.items():
            if not _is_ref(ref):
                raise ConfigError(f'env_refs.{name} must be a secret reference')
        if self.timeout_seconds is not None and not (0 < self.timeout_seconds <= 3600):
            raise ConfigError('timeout_seconds must be between 0 and 3600')

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
    """``<prefix>__<name>``, cleaned to the MCP tool-name rules (a bad character -> '_', <= 128)."""
    full = f'{prefix}{SEPARATOR}{name}'
    if TOOL_NAME.match(full):
        return full
    return _TOOL_NAME_BAD.sub('_', full)[:128]
