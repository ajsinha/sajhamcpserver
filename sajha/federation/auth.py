"""
SAJHA MCP Server — credentials SAJHA presents to an upstream MCP server.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``build_auth(config, settings)`` returns an ``httpx2.Auth`` (or None) for the upstream's
``auth`` block:

* ``none``                      nothing;
* ``bearer``                    ``Authorization: Bearer <token_ref>``;
* ``header``                    ``<header>: <value_ref>`` (an API-key header);
* ``oauth_client_credentials``  a token from an OAuth 2.0 client-credentials grant at
                                ``token_url``, cached until shortly before expiry and
                                fetched again when the upstream answers 401.
* ``connected_account``         per-user token passthrough: every tool call carries the
                                *calling user's* token for ``provider`` (sajha/accounts),
                                on a connection opened for that call; the shared connection
                                discovers tools with ``discovery`` (one of the above) or nothing.
* ``token_user``                per-user personal tokens (sajha/federation/user_tokens.py): each call
                                carries the caller's own token in ``header``/``format``; the shared
                                connection discovers with ``discovery`` or, without one, the token
                                of the first user who connected.
* ``oauth_user``                per-user OAuth sign-in (sajha/federation/oauth_user.py): each call
                                carries the caller's own access token as a bearer token; discovery
                                as for token_user.
* ``service_with_user``         one shared service identity (``service``: one of none, bearer,
                                header, oauth_client_credentials; or the shared ``headers``) with the
                                calling SAJHA user named in an audit header (``user_header``, default
                                ``X-SAJHA-User``) on every tool call (OnBehalfAuth); discovery uses the
                                service identity alone.
* ``static``                    the same as ``none``: the shared credential is in ``headers``.

Secrets are references (``env:``, ``file:``, ``db:``) resolved when the connection is
built; resolved values are held only by the Auth object and never logged.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

import httpx2

from sajha.federation.security import check_url, resolve_ref


class StaticHeaderAuth(httpx2.Auth):
    def __init__(self, header: str, value: str):
        self.header = header
        self._value = value

    def auth_flow(self, request):
        request.headers[self.header] = self._value
        yield request

    def secret_values(self) -> List[str]:
        return [self._value]


class ClientCredentialsAuth(httpx2.Auth):
    """OAuth 2.0 client credentials (RFC 6749 section 4.4), token in the Authorization header."""

    SKEW_SECONDS = 30

    def __init__(self, token_url: str, client_id: str, client_secret: str, scope: str = '',
                 audience: str = '', resource: str = ''):
        self.token_url = token_url
        self.client_id = client_id
        self._secret = client_secret
        self.scope, self.audience, self.resource = scope, audience, resource
        self._token: Optional[str] = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _token_request(self) -> httpx2.Request:
        form = {'grant_type': 'client_credentials', 'client_id': self.client_id,
                'client_secret': self._secret}
        if self.scope:
            form['scope'] = self.scope
        if self.audience:
            form['audience'] = self.audience
        if self.resource:
            form['resource'] = self.resource
        return httpx2.Request('POST', self.token_url, data=form, headers={'Accept': 'application/json'})

    def _absorb(self, response: httpx2.Response) -> None:
        if response.status_code != 200:
            raise PermissionError(f'OAuth token request failed with HTTP {response.status_code}')
        try:
            body = response.json()
        except ValueError:
            raise PermissionError('OAuth token response is not JSON')
        token = body.get('access_token')
        if not token or str(body.get('token_type', 'bearer')).lower() != 'bearer':
            raise PermissionError('OAuth token response has no bearer access_token')
        try:
            ttl = float(body.get('expires_in') or 3600)
        except (TypeError, ValueError):
            ttl = 3600.0
        with self._lock:
            self._token = token
            self._expires_at = time.time() + max(0.0, ttl - self.SKEW_SECONDS)

    def _valid(self) -> Optional[str]:
        with self._lock:
            return self._token if self._token and time.time() < self._expires_at else None

    def sync_auth_flow(self, request):
        token = self._valid()
        if token is None:
            response = yield self._token_request()
            response.read()
            self._absorb(response)
        request.headers['Authorization'] = f'Bearer {self._valid()}'
        response = yield request
        if response.status_code == 401:                 # expired or revoked early: once more
            with self._lock:
                self._token = None
            token_response = yield self._token_request()
            token_response.read()
            self._absorb(token_response)
            request.headers['Authorization'] = f'Bearer {self._valid()}'
            yield request

    async def async_auth_flow(self, request):
        token = self._valid()
        if token is None:
            response = yield self._token_request()
            await response.aread()
            self._absorb(response)
        request.headers['Authorization'] = f'Bearer {self._valid()}'
        response = yield request
        if response.status_code == 401:                 # expired or revoked early: once more
            with self._lock:
                self._token = None
            token_response = yield self._token_request()
            await token_response.aread()
            self._absorb(token_response)
            request.headers['Authorization'] = f'Bearer {self._valid()}'
            yield request

    def secret_values(self) -> List[str]:
        return [v for v in (self._secret, self._token) if v]


class OnBehalfAuth(httpx2.Auth):
    """The shared service credential (``inner``, or none) plus ``header: value`` naming the SAJHA user
    the call is made for (auth.type service_with_user). The user header is not a secret; it is the
    vendor's audit record of who asked."""

    def __init__(self, inner: Optional[httpx2.Auth], header: str, value: str):
        self.inner = inner
        self.header = header
        self.value = value

    def sync_auth_flow(self, request):
        request.headers[self.header] = self.value
        if self.inner is None:
            yield request
            return
        yield from self.inner.sync_auth_flow(request)

    async def async_auth_flow(self, request):
        request.headers[self.header] = self.value
        if self.inner is None:
            yield request
            return
        flow = self.inner.async_auth_flow(request)
        try:
            req = await flow.__anext__()
            while True:
                response = yield req
                req = await flow.asend(response)
        except StopAsyncIteration:
            return

    def secret_values(self) -> List[str]:
        return list(getattr(self.inner, 'secret_values', lambda: [])()) if self.inner is not None else []


def build_auth(config, settings) -> Optional[httpx2.Auth]:
    a = dict(config.auth or {})
    kind = a.get('type') or 'none'
    if kind == 'service_with_user':
        # the shared connection (discovery, and the credential under every call) is the service identity;
        # each tool call adds the user header on a connection of its own (FederationManager)
        a = dict(a.get('service') or {})
        kind = a.get('type') or 'none'
    if kind == 'connected_account':
        # the shared connection only discovers (tools/list): it uses auth.discovery, if any.
        # Tool calls carry the caller's own token on a connection of their own (call_tool_as).
        a = dict(a.get('discovery') or {})
        kind = a.get('type') or 'none'
    elif kind in ('token_user', 'oauth_user'):
        disc = dict(a.get('discovery') or {})
        if (disc.get('type') or 'none') == 'none':
            # no discovery credential: discover as the first user who connected (the union of what
            # users see is completed from each user's own listing when they connect); an OAuth
            # token is refreshed first when due
            from sajha.federation.user_tokens import get_tokens, header_for
            token = get_tokens().first_token(config.id, config)
            if not token:
                return None
            return StaticHeaderAuth(*header_for(config, token))
        a, kind = disc, disc.get('type') or 'none'
    if kind in ('none', 'static'):
        return None
    if kind == 'bearer':
        token = resolve_ref(a.get('token_ref'), f'upstream {config.id} auth.token_ref')
        return StaticHeaderAuth('Authorization', f'Bearer {token}')
    if kind == 'header':
        value = resolve_ref(a.get('value_ref'), f'upstream {config.id} auth.value_ref')
        return StaticHeaderAuth(str(a['header']), value)
    if kind == 'oauth_client_credentials':
        check_url(a['token_url'], settings)
        secret = resolve_ref(a.get('client_secret_ref'), f'upstream {config.id} auth.client_secret_ref')
        return ClientCredentialsAuth(a['token_url'], str(a['client_id']), secret, str(a.get('scope') or ''),
                                     str(a.get('audience') or ''), str(a.get('resource') or ''))
    raise ValueError(f'unknown auth.type {kind!r}')
