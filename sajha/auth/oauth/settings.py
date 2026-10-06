"""
SAJHA MCP Server — OAuth 2.1 settings for /mcp (MCP authorization spec).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

All keys live under ``mcp.auth`` in config/application.yml and are read on
every call (SAJHA_ env overrides apply, e.g. SAJHA_MCP_AUTH_MODE=required).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODES = ('off', 'optional', 'required')
BUILTIN = 'builtin'
OFFLINE_ACCESS = 'offline_access'
DEFAULT_SCOPES = 'mcp:read mcp:tools'
# Scope a method needs; "mcp" (if granted) implies every mcp:* scope.
TOOLS_SCOPE = 'mcp:tools'
READ_SCOPE = 'mcp:read'
UMBRELLA_SCOPE = 'mcp'
# Asymmetric algorithms only: "none" and HS* are never accepted for OAuth tokens.
DEFAULT_ALGORITHMS = ('RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512')


def _get(key: str, default: str = '') -> str:
    from sajha.core.config import _get as cfg_get
    return cfg_get(key, default)


def _bool(key: str, default: bool = False) -> bool:
    from sajha.core.config import _bool as cfg_bool
    return cfg_bool(key, default)


def _int(key: str, default: int) -> int:
    from sajha.core.config import _int as cfg_int
    return cfg_int(key, default)


def auth_mode() -> str:
    mode = (_get('mcp.auth.mode', 'off') or 'off').strip().lower()
    if mode not in MODES:
        logger.warning(f"Unknown mcp.auth.mode {mode!r}; treating as 'off'")
        return 'off'
    return mode


def oauth_enabled() -> bool:
    """PRM / AS metadata / OAuth bearer validation are active (mode optional|required)."""
    return auth_mode() != 'off'


def authorization_server_setting() -> str:
    return (_get('mcp.auth.authorization_server', BUILTIN) or BUILTIN).strip()


def is_builtin() -> bool:
    return authorization_server_setting().lower() == BUILTIN


def external_issuer() -> Optional[str]:
    """The configured external issuer URL (exact string, compared verbatim), or None for builtin."""
    value = authorization_server_setting()
    return None if value.lower() == BUILTIN else value


def public_base_url(request=None) -> str:
    """
    This server's externally visible origin (no trailing slash).  Set
    ``mcp.auth.public_url`` in production: token audiences and the built-in
    issuer derive from it.  Unset, it falls back to the request's own
    scheme://host[:port] (fine for local development).
    """
    configured = (_get('mcp.auth.public_url', '') or '').strip().rstrip('/')
    if configured:
        return configured
    if request is None:
        return ''
    url = request.url
    host = (url.hostname or '').lower()
    if ':' in host:          # IPv6 literal
        host = f'[{host}]'
    port = url.port
    default = {'http': 80, 'https': 443}.get(url.scheme)
    netloc = host if port in (None, default) else f'{host}:{port}'
    return f'{url.scheme}://{netloc}'


# The MCP endpoint paths this server answers on; each is its own RFC 8707
# resource.  /mcp is canonical.
RESOURCE_PATHS = ('/mcp', '/api/mcp')


def resource_uri(request=None, path: str = '/mcp') -> str:
    return public_base_url(request) + path


def resource_uris(request=None) -> List[str]:
    return [resource_uri(request, p) for p in RESOURCE_PATHS]


def canonical_resource(value: str, request=None) -> Optional[str]:
    """
    The resource URI of this server that ``value`` names (RFC 8707), comparing
    scheme and host case-insensitively and ignoring one trailing slash; None
    when it names something else.
    """
    from urllib.parse import urlsplit
    try:
        p = urlsplit(value or '')
    except ValueError:
        return None
    if p.query or p.fragment or not p.scheme or not p.netloc:
        return None
    normalized = f'{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip("/")}'
    for uri in resource_uris(request):
        q = urlsplit(uri)
        if normalized == f'{q.scheme.lower()}://{q.netloc.lower()}{q.path.rstrip("/")}':
            return uri
    return None


def resource_scopes() -> List[str]:
    """Scopes listed in PRM scopes_supported and the 401 challenge (never offline_access)."""
    raw = _get('mcp.auth.scopes', DEFAULT_SCOPES) or DEFAULT_SCOPES
    scopes = [s for s in raw.replace(',', ' ').split() if s and s != OFFLINE_ACCESS]
    return scopes or DEFAULT_SCOPES.split()


def accepted_audiences(request=None) -> List[str]:
    """Token ``aud`` values accepted: this server's resource URIs plus mcp.auth.accepted_audiences."""
    extra = [a.strip() for a in (_get('mcp.auth.accepted_audiences', '') or '').split(',') if a.strip()]
    return resource_uris(request) + extra


def clock_skew_seconds() -> int:
    return max(0, _int('mcp.auth.clock_skew_seconds', 60))


def allowed_algorithms() -> List[str]:
    raw = _get('mcp.auth.algorithms', '') or ''
    algs = [a.strip() for a in raw.split(',') if a.strip()] or list(DEFAULT_ALGORITHMS)
    return [a for a in algs if a.upper() != 'NONE' and not a.upper().startswith('HS')]


def jwks_cache_seconds() -> int:
    return max(60, _int('mcp.auth.jwks_cache_seconds', 3600))


def external_user_claim() -> str:
    return (_get('mcp.auth.external.user_claim', 'sub') or 'sub').strip()


# ── built-in authorization server ──────────────────────────────────

def signing_key_path() -> Path:
    raw = (_get('mcp.auth.builtin.signing_key_path', '') or '').strip()
    if raw:
        return Path(raw)
    from sajha.core.config import get_settings
    return Path(get_settings().data_dir) / 'oauth' / 'signing_key.pem'


def access_token_ttl() -> int:
    return max(60, _int('mcp.auth.builtin.access_token_ttl_seconds', 900))


def refresh_token_ttl() -> int:
    return max(300, _int('mcp.auth.builtin.refresh_token_ttl_seconds', 30 * 24 * 3600))


def code_ttl() -> int:
    return min(600, max(30, _int('mcp.auth.builtin.code_ttl_seconds', 60)))


def refresh_token_policy() -> str:
    """offline_access (issue only when that scope is granted) | always | never."""
    value = (_get('mcp.auth.builtin.refresh_tokens', OFFLINE_ACCESS) or OFFLINE_ACCESS).strip().lower()
    return value if value in (OFFLINE_ACCESS, 'always', 'never') else OFFLINE_ACCESS


def dcr_enabled() -> bool:
    return _bool('mcp.auth.builtin.dynamic_client_registration', False)


def cimd_enabled() -> bool:
    return _bool('mcp.auth.builtin.cimd.enabled', True)


def cimd_allow_localhost() -> bool:
    """Dev only: accept http://localhost / 127.0.0.1 client_id URLs (normally https only)."""
    return _bool('mcp.auth.builtin.cimd.allow_localhost', False)


def cimd_allow_private_networks() -> bool:
    return _bool('mcp.auth.builtin.cimd.allow_private_networks', False)


def cimd_timeout_seconds() -> float:
    return float(max(1, min(30, _int('mcp.auth.builtin.cimd.timeout_seconds', 5))))


def cimd_max_bytes() -> int:
    return max(1024, min(1024 * 1024, _int('mcp.auth.builtin.cimd.max_bytes', 16384)))


def _raw_yaml_value(dotted: str) -> Any:
    """A non-scalar YAML value (lists are flattened to strings by sajha.core.config)."""
    from sajha.core.config import _CONFIG_FILE
    import yaml
    path = Path(_CONFIG_FILE)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        with open(path, 'r', encoding='utf-8') as f:
            node = yaml.safe_load(f) or {}
    except (OSError, ValueError) as e:
        logger.warning(f'Could not read {path}: {e}')
        return None
    for part in dotted.split('.'):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def static_clients() -> List[Dict[str, Any]]:
    """
    Pre-registered clients: ``mcp.auth.builtin.clients`` (a YAML list), or the
    env var SAJHA_MCP_AUTH_BUILTIN_CLIENTS holding the same list as JSON.
    """
    env = os.environ.get('SAJHA_MCP_AUTH_BUILTIN_CLIENTS')
    if env:
        try:
            value = json.loads(env)
        except ValueError:
            logger.warning('SAJHA_MCP_AUTH_BUILTIN_CLIENTS is not valid JSON; ignored')
            value = []
    else:
        value = _raw_yaml_value('mcp.auth.builtin.clients')
    if not isinstance(value, list):
        return []
    from sajha.core.config import _substitute_vars
    out = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get('client_id'), str):
            entry = dict(item)
            if isinstance(entry.get('client_secret'), str):
                entry['client_secret'] = _substitute_vars(entry['client_secret'])
            out.append(entry)
    return out
