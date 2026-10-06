"""
SAJHA MCP Server — /mcp as an OAuth 2.1 resource server.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

* RFC 9728 Protected Resource Metadata document.
* ``WWW-Authenticate: Bearer resource_metadata=..., scope=...`` challenges
  (401, and 403 insufficient_scope).
* Bearer validation: signature (built-in key, or the external issuer's JWKS
  found via RFC 8414 / OIDC discovery, cached), ``iss``, ``aud`` == this MCP
  resource (RFC 8707), ``exp``/``nbf``, then per-method scope checks.

Existing SAJHA credentials (X-API-Key / sja_ keys, SAJHA login JWTs, the
session cookie) keep working in every mode; OAuth access tokens are accepted
only on the MCP endpoints (they are minted for the MCP resource, not the REST API).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from sajha.auth.oauth import settings

logger = logging.getLogger(__name__)

PRM_PATH = '/.well-known/oauth-protected-resource'


class TokenError(Exception):
    pass


@dataclass
class TokenInfo:
    subject: str
    scopes: Set[str]
    client_id: Optional[str]
    issuer: str
    claims: Dict[str, Any] = field(default_factory=dict)


# ── discovery documents / challenges ───────────────────────────────

def mcp_path_for(request_path: str) -> str:
    """The MCP endpoint (resource path) a request path belongs to."""
    return '/api/mcp' if request_path.startswith('/api/mcp') else '/mcp'


def issuer_for(request: Request) -> str:
    return external_or_builtin_issuer(request)


def external_or_builtin_issuer(request: Optional[Request]) -> str:
    ext = settings.external_issuer()
    return ext if ext else settings.public_base_url(request)


def protected_resource_metadata(request: Request, path: str = '/mcp') -> Dict[str, Any]:
    from sajha.core.config import get_settings
    doc = {
        'resource': settings.resource_uri(request, path),
        'authorization_servers': [external_or_builtin_issuer(request)],
        'scopes_supported': settings.resource_scopes(),
        'bearer_methods_supported': ['header'],
        'resource_name': get_settings().app_name,
    }
    return doc


def resource_metadata_url(request: Request, path: str) -> str:
    return settings.public_base_url(request) + PRM_PATH + path


def _quote(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def challenge(request: Request, status: int = 401, error: Optional[str] = None,
              description: Optional[str] = None, scope: Optional[str] = None) -> JSONResponse:
    path = mcp_path_for(request.url.path)
    parts = [f'resource_metadata="{_quote(resource_metadata_url(request, path))}"']
    parts.append(f'scope="{_quote(scope or " ".join(settings.resource_scopes()))}"')
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append(f'error_description="{_quote(description)}"')
    body = {'error': error or 'unauthorized',
            'error_description': description or 'Authorization required'}
    return JSONResponse(body, status_code=status, headers={'WWW-Authenticate': 'Bearer ' + ', '.join(parts)})


# ── external issuer discovery + JWKS cache ─────────────────────────

def _discovery_urls(issuer: str) -> List[str]:
    p = urlsplit(issuer)
    origin = f'{p.scheme}://{p.netloc}'
    path = p.path.rstrip('/')
    if path:
        return [f'{origin}/.well-known/oauth-authorization-server{path}',
                f'{origin}/.well-known/openid-configuration{path}',
                f'{origin}{path}/.well-known/openid-configuration']
    return [f'{origin}/.well-known/oauth-authorization-server', f'{origin}/.well-known/openid-configuration']


class _JWKSCache:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._issuer: Optional[str] = None
        self._jwks_uri: Optional[str] = None
        self._keys: Dict[str, Dict] = {}
        self._fetched = 0.0
        self._last_forced = 0.0

    async def _get_json(self, client, url: str) -> Optional[Dict]:
        try:
            resp = await client.get(url, headers={'Accept': 'application/json'})
        except Exception as e:      # network errors -> try next / fail closed
            logger.warning(f'OAuth discovery fetch failed for {url}: {type(e).__name__}')
            return None
        if resp.status_code != 200 or len(resp.content) > 512 * 1024:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def _refresh(self, issuer: str) -> None:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            if self._issuer != issuer or not self._jwks_uri:
                jwks_uri = None
                for url in _discovery_urls(issuer):
                    meta = await self._get_json(client, url)
                    if meta is None:
                        continue
                    if meta.get('issuer') != issuer:
                        logger.warning(f'Authorization server metadata at {url} names issuer '
                                       f'{meta.get("issuer")!r}, expected {issuer!r}; ignored')
                        continue
                    jwks_uri = meta.get('jwks_uri')
                    break
                if not isinstance(jwks_uri, str) or not jwks_uri.startswith(('https://', 'http://')):
                    raise TokenError('authorization server metadata (jwks_uri) unavailable')
                if jwks_uri.startswith('http://') and not issuer.startswith('http://'):
                    raise TokenError('insecure jwks_uri')
                self._issuer, self._jwks_uri = issuer, jwks_uri
            jwks = await self._get_json(client, self._jwks_uri)
            if jwks is None or not isinstance(jwks.get('keys'), list):
                raise TokenError('JWKS unavailable')
            self._keys = {k.get('kid', ''): k for k in jwks['keys']
                          if isinstance(k, dict) and k.get('use', 'sig') == 'sig'}
            self._fetched = time.time()

    async def key_for(self, issuer: str, kid: Optional[str]) -> Dict:
        async with self._lock:
            now = time.time()
            stale = self._issuer != issuer or now - self._fetched > settings.jwks_cache_seconds()
            if stale:
                await self._refresh(issuer)
            key = self._find(kid)
            if key is None and now - self._last_forced > 30:     # key rotation: refetch, rate-limited
                self._last_forced = now
                await self._refresh(issuer)
                key = self._find(kid)
            if key is None:
                raise TokenError('signing key not found')
            return key

    def _find(self, kid: Optional[str]) -> Optional[Dict]:
        if kid:
            return self._keys.get(kid)
        return next(iter(self._keys.values())) if len(self._keys) == 1 else None


_jwks_cache = _JWKSCache()


# ── validation ─────────────────────────────────────────────────────

def _scopes_of(claims: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in ('scope', 'scp'):
        value = claims.get(key)
        if isinstance(value, str):
            out.update(value.split())
        elif isinstance(value, list):
            out.update(v for v in value if isinstance(v, str))
    return out


async def validate_bearer(token: str, request: Request) -> TokenInfo:
    from jose import jwt, JWTError
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise TokenError('malformed token')
    alg = header.get('alg')
    if alg not in settings.allowed_algorithms():
        raise TokenError('token algorithm not accepted')

    issuer = settings.external_issuer()
    if issuer is None:
        from sajha.auth.oauth.keys import get_signing_key
        issuer = settings.public_base_url(request)
        signing = get_signing_key()
        if header.get('kid') not in (None, signing.kid):
            raise TokenError('unknown signing key')
        if str(header.get('typ', '')).lower() not in ('at+jwt', 'application/at+jwt'):
            raise TokenError('not an access token')
        key: Any = signing.public_pem.decode()
    else:
        key = await _jwks_cache.key_for(issuer, header.get('kid'))

    try:
        claims = jwt.decode(token, key, algorithms=[alg], issuer=issuer,
                            options={'verify_aud': False, 'require_exp': True, 'require_iss': True,
                                     'leeway': settings.clock_skew_seconds()})
    except JWTError as e:
        raise TokenError(f'invalid token: {e}')

    aud = claims.get('aud')
    audiences = [aud] if isinstance(aud, str) else [a for a in (aud or []) if isinstance(a, str)]
    accepted = settings.accepted_audiences(request)
    if not any(a in accepted for a in audiences):
        raise TokenError('token audience is not this MCP server')

    if settings.external_issuer() is None:
        subject = claims.get('sub')
    else:
        subject = claims.get(settings.external_user_claim()) or claims.get('sub')
    if not isinstance(subject, str) or not subject:
        raise TokenError('token has no subject')
    return TokenInfo(subject=subject, scopes=_scopes_of(claims),
                     client_id=claims.get('client_id') or claims.get('azp'), issuer=issuer, claims=claims)


def required_scope(method: Optional[str]) -> Optional[str]:
    """The scope an MCP method needs; None when the operator's scope set does not use it."""
    wanted = settings.TOOLS_SCOPE if method == 'tools/call' else settings.READ_SCOPE
    return wanted if wanted in settings.resource_scopes() else None


def has_scope(granted: Set[str], needed: Optional[str]) -> bool:
    if not needed:
        return True
    return needed in granted or settings.UMBRELLA_SCOPE in granted


def context_for_token(info: TokenInfo, db):
    """An AuthContext for a validated token (None when it names a missing/disabled built-in user)."""
    from sajha.auth import AuthContext
    from sajha.db.dao import UserDAO
    user = UserDAO(db).get_by_user_id(info.subject)
    if user is not None and user.enabled:
        return AuthContext(authenticated=True, user_id=user.user_id, user_name=user.user_name,
                           roles=user.role_names, auth_type='oauth', is_admin=user.is_admin,
                           _user=user, _db=db)
    if settings.external_issuer() is None:
        return None
    # External IdP identity with no SAJHA account: least privilege, like an API key.
    return AuthContext(authenticated=True, user_id=f'oauth:{info.subject}', user_name=info.subject,
                       roles=['api_consumer'], auth_type='oauth', is_admin=False, _db=db)


def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get('authorization', '')
    if header[:7].lower() == 'bearer ':
        return header[7:].strip() or None
    return None


async def authorize_mcp(request: Request, db, method: Optional[str] = None):
    """
    Authenticate an MCP transport request.  Returns ``(AuthContext, error_response)``;
    when error_response is not None the caller returns it as is.
    """
    from sajha.auth import AuthManager, AuthContext
    ctx = AuthManager.authenticate_request(request, db)
    mode = settings.auth_mode()
    if ctx.authenticated or mode == 'off':
        return ctx, None

    token = _bearer(request)
    if token:
        try:
            info = await validate_bearer(token, request)
        except TokenError as e:
            logger.info(f'Rejected MCP bearer token: {e}')
            return AuthContext(authenticated=False), challenge(request, 401, 'invalid_token', str(e))
        oauth_ctx = context_for_token(info, db)
        if oauth_ctx is None:
            return AuthContext(authenticated=False), challenge(request, 401, 'invalid_token',
                                                               'unknown or disabled user')
        needed = required_scope(method)
        if not has_scope(info.scopes, needed):
            return oauth_ctx, challenge(request, 403, 'insufficient_scope',
                                        f'this operation requires the {needed} scope', scope=needed)
        return oauth_ctx, None

    if mode == 'required':
        return ctx, challenge(request, 401)
    return ctx, None
