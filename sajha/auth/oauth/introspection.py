"""
SAJHA MCP Server — RFC 7662 token introspection for an external authorization server.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Some issuers hand out opaque access tokens (not JWTs), which /mcp cannot verify
by signature.  With ``mcp.auth.external.introspection.mode`` ``opaque`` (tokens
that are not JWTs) or ``always`` (every token), SAJHA asks the issuer's
introspection endpoint instead:

* endpoint: ``mcp.auth.external.introspection.endpoint``, or the
  ``introspection_endpoint`` of the issuer's RFC 8414 / OIDC metadata;
* SAJHA authenticates as a client (``client_id`` + ``client_secret``, the
  secret from the environment), HTTP Basic or form fields;
* the answer must say ``active: true`` and, when it names them, the right
  ``iss``, an unexpired ``exp`` / reached ``nbf``, an ``aud`` of this MCP
  resource (an answer without ``aud`` is refused unless ``require_audience``
  is false), and not a refresh token;
* fail closed: no endpoint, no credentials, a network error, a non-200, a body
  that is not a JSON object -> the token is refused (and nothing is cached);
* answers are cached per process for ``cache_seconds`` (an active one never
  beyond the token's ``exp``), keyed by a SHA-256 of the token, so a token
  revoked at the issuer is refused here within that time at most.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from sajha.auth.oauth import settings

logger = logging.getLogger(__name__)

MAX_CACHE_ENTRIES = 10000
_MAX_BODY = 256 * 1024


class _Introspector:
    def __init__(self):
        self._cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
        self._endpoints: Dict[str, str] = {}      # issuer -> discovered introspection endpoint
        self.calls = 0                             # requests sent to the issuer (tests, observability)

    def clear(self) -> None:
        self._cache.clear()
        self._endpoints.clear()

    # -- endpoint -------------------------------------------------------

    async def _endpoint(self, client, issuer: str) -> str:
        from sajha.auth.oauth.resource_server import TokenError, _discovery_urls
        configured = settings.introspection_endpoint()
        endpoint = configured or self._endpoints.get(issuer)
        if not endpoint:
            for url in _discovery_urls(issuer):
                meta = await _get_json(client, url)
                if meta is None or meta.get('issuer') != issuer:
                    continue
                if isinstance(meta.get('introspection_endpoint'), str):
                    endpoint = meta['introspection_endpoint']
                    break
            if not endpoint:
                raise TokenError('token introspection endpoint unavailable')
            self._endpoints[issuer] = endpoint
        if not endpoint.startswith(('https://', 'http://')):
            raise TokenError('token introspection endpoint is not an http(s) URL')
        if endpoint.startswith('http://') and not issuer.startswith('http://'):
            raise TokenError('insecure token introspection endpoint')
        return endpoint

    # -- the call -------------------------------------------------------

    async def _ask(self, token: str, issuer: str) -> Dict[str, Any]:
        from sajha.auth.oauth.resource_server import TokenError
        import httpx
        client_id, secret = settings.introspection_client_id(), settings.introspection_client_secret()
        if not client_id or not secret:
            raise TokenError('token introspection client credentials are not configured')
        form = {'token': token, 'token_type_hint': 'access_token'}
        headers = {'Accept': 'application/json'}
        if settings.introspection_auth_method() == 'client_secret_post':
            form.update(client_id=client_id, client_secret=secret)
        else:     # RFC 6749 §2.3.1: form-urlencode each part, then Basic
            pair = f'{quote(client_id, safe="")}:{quote(secret, safe="")}'
            headers['Authorization'] = 'Basic ' + base64.b64encode(pair.encode()).decode()
        async with httpx.AsyncClient(timeout=settings.introspection_timeout_seconds(),
                                     follow_redirects=False) as client:
            endpoint = await self._endpoint(client, issuer)
            self.calls += 1
            try:
                resp = await client.post(endpoint, data=form, headers=headers)
            except Exception as e:
                logger.warning(f'Token introspection failed: {type(e).__name__}')
                raise TokenError('token introspection unavailable')
        if resp.status_code != 200 or len(resp.content) > _MAX_BODY:
            logger.warning(f'Token introspection answered HTTP {resp.status_code}')
            raise TokenError('token introspection unavailable')
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise TokenError('token introspection answer is not a JSON object')
        return data

    # -- validation -----------------------------------------------------

    @staticmethod
    def _check(claims: Dict[str, Any], issuer: str, request) -> None:
        """Raise TokenError unless an active answer is usable for this MCP resource."""
        from sajha.auth.oauth.resource_server import TokenError
        now, skew = time.time(), settings.clock_skew_seconds()
        if str(claims.get('token_type', '')).lower() == 'refresh_token':
            raise TokenError('not an access token')
        exp, nbf = claims.get('exp'), claims.get('nbf')
        if exp is not None and (not isinstance(exp, (int, float)) or exp + skew < now):
            raise TokenError('token expired')
        if nbf is not None and (not isinstance(nbf, (int, float)) or nbf - skew > now):
            raise TokenError('token not yet valid')
        if 'iss' in claims and claims.get('iss') != issuer:
            raise TokenError('token issuer mismatch')
        aud = claims.get('aud')
        audiences = [aud] if isinstance(aud, str) else [a for a in (aud or []) if isinstance(a, str)]
        if audiences:
            if not any(a in settings.accepted_audiences(request) for a in audiences):
                raise TokenError('token audience is not this MCP server')
        elif settings.introspection_require_audience():
            raise TokenError('token introspection answer names no audience')

    def _cached(self, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        hit = self._cache.get(key)
        if hit is None:
            return False, None
        if hit[0] <= time.time():
            self._cache.pop(key, None)
            return False, None
        return True, hit[1]

    def _remember(self, key: str, claims: Optional[Dict[str, Any]]) -> None:
        ttl = settings.introspection_cache_seconds()
        if ttl <= 0:
            return
        until = time.time() + ttl
        if claims is not None and isinstance(claims.get('exp'), (int, float)):
            until = min(until, float(claims['exp']))
        if len(self._cache) >= MAX_CACHE_ENTRIES:
            now = time.time()
            for k in [k for k, (t, _) in self._cache.items() if t <= now]:
                self._cache.pop(k, None)
            while len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (until, claims)

    async def introspect(self, token: str, request, issuer: str):
        """A TokenInfo for an active token of this MCP resource, else TokenError."""
        from sajha.auth.oauth.resource_server import TokenError, TokenInfo, _scopes_of
        key = hashlib.sha256(token.encode('utf-8', 'surrogatepass')).hexdigest()
        found, claims = self._cached(key)
        if not found:
            answer = await self._ask(token, issuer)
            claims = answer if answer.get('active') is True else None
            self._remember(key, claims)
        if claims is None:
            raise TokenError('token is not active')
        self._check(claims, issuer, request)
        subject = claims.get(settings.external_user_claim()) or claims.get('sub') or claims.get('username')
        if not isinstance(subject, str) or not subject:
            raise TokenError('token has no subject')
        return TokenInfo(subject=subject, scopes=_scopes_of(claims), client_id=claims.get('client_id'),
                         issuer=issuer, claims=claims)


async def _get_json(client, url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = await client.get(url, headers={'Accept': 'application/json'})
    except Exception as e:
        logger.warning(f'OAuth discovery fetch failed for {url}: {type(e).__name__}')
        return None
    if resp.status_code != 200 or len(resp.content) > _MAX_BODY:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


_introspector = _Introspector()


def get_introspector() -> _Introspector:
    return _introspector


def is_jwt(token: str) -> bool:
    """Does the token look like a JWS (three segments with a decodable header)?"""
    if token.count('.') != 2:
        return False
    from jose import jwt, JWTError
    try:
        jwt.get_unverified_header(token)
        return True
    except (JWTError, Exception):
        return False


def should_introspect(token: str) -> bool:
    """Is this bearer token checked by introspection (external issuer, mode opaque|always)?"""
    if settings.external_issuer() is None:
        return False
    mode = settings.introspection_mode()
    return mode == 'always' or (mode == 'opaque' and not is_jwt(token))
