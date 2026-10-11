"""
SAJHA MCP Server — per-user OAuth sign-in for proxied MCP servers (``auth.type: oauth_user``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A proxied server whose ``auth.type`` is ``oauth_user`` is called **as the person who asked**, with an
OAuth access token that person obtained by signing in at the vendor once ("Connect with <vendor>" on
``/account/server-connections/<upstream>``). This module finds out how to sign in and runs the flow;
the tokens then live where ``token_user`` tokens live (the connected-accounts vault, provider key
``upstream:<id>``) and are looked up, revoked and audited by :mod:`sajha.federation.user_tokens`.

* **Discovery.** The server's protected-resource metadata (RFC 9728), found from the
  ``resource_metadata`` parameter of the ``WWW-Authenticate`` header of its HTTP 401 or at the
  well-known URL, names its authorization server; that server's metadata (RFC 8414, or OpenID
  Connect discovery) gives the endpoints. An operator may instead give ``authorize_url`` and
  ``token_url`` (vendors that publish no metadata). Every discovered URL passes the federation URL
  guard (``federation.allowed_hosts``, no private addresses unless allowed) and must be https
  (plain http only on loopback with ``federation.allow_localhost``). PKCE with S256 is required.
* **The client.** An operator-registered client (``client_id`` and ``client_secret_ref``, a
  reference such as ``env:NAME``), else dynamic client registration (RFC 7591) where the
  authorization server offers it; the registration is kept encrypted in the vault (row
  :data:`CLIENT_ROW`) and redone when SAJHA's redirect URI changes.
* **The flow.** The connected-accounts authorization-code machinery
  (:class:`~sajha.accounts.service.ConnectedAccountsService`): ``state`` in the shared state store,
  bound to the user and the browser, PKCE S256, the exact redirect URI — one callback for every
  upstream, :data:`CALLBACK_PATH` — and the resource indicator (RFC 8707) naming the upstream in the
  authorization, token and refresh requests. ``scopes`` are requested by default; ``write_scopes``
  only for a user who ticks "allow changes" on the connect page.
* **Refresh** shortly before expiry (``accounts.refresh_skew_seconds``) and once after an HTTP 401;
  a refused refresh marks the connection "needs re-connect". **Disconnect** (and every revocation:
  user disabled or deleted, sign-out everywhere, an administrator) revokes at the vendor when it
  advertises a revocation endpoint (RFC 7009), then deletes the row.

Tokens, codes, verifiers and client secrets are never logged, audited, shown or returned.
Design: docs/architecture/Per-User Sign-In for Proxied Servers.md; configuration:
docs/architecture/Federation.md, "Per-user OAuth sign-in".
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from sajha.accounts.errors import OAuthFlowError
from sajha.accounts.providers import REVOKE_STYLES, TOKEN_AUTH_METHODS, Provider
from sajha.accounts.service import ConnectedAccountsService

logger = logging.getLogger(__name__)

#: the one redirect URI path for every oauth_user upstream
CALLBACK_PATH = '/account/server-connections/oauth/callback'
#: the vault row (user id) that holds an upstream's dynamically registered client
CLIENT_ROW = '#client'
#: how long discovered metadata is reused before it is fetched again
METADATA_TTL_SECONDS = 3600.0
_MAX_METADATA_BYTES = 256_000
_RESOURCE_METADATA = re.compile(r'resource_metadata\s*=\s*"([^"]+)"', re.I)


class OAuthUserError(OAuthFlowError):
    """Signing in to an oauth_user upstream cannot proceed; the message is for the user and never
    contains a token, code or secret."""


@dataclass
class OAuthUserSpec:
    """The ``auth`` block of an ``oauth_user`` upstream."""
    scopes: List[str] = field(default_factory=list)
    write_scopes: List[str] = field(default_factory=list)
    vendor: str = ''
    client_id: str = ''
    client_secret_ref: str = ''
    token_auth_method: str = ''
    authorization_server: str = ''
    authorize_url: str = ''
    token_url: str = ''
    revoke_url: str = ''
    revoke_style: str = ''
    resource: str = ''
    resource_indicator: bool = True
    authorize_params: Dict[str, str] = field(default_factory=dict)
    help_url: str = ''

    KEYS = ('type', 'scopes', 'write_scopes', 'vendor', 'client_id', 'client_secret_ref', 'token_auth_method',
            'authorization_server', 'authorize_url', 'token_url', 'revoke_url', 'revoke_style', 'resource',
            'resource_indicator', 'authorize_params', 'help_url', 'discovery')

    @classmethod
    def from_auth(cls, auth: Optional[Dict[str, Any]]) -> 'OAuthUserSpec':
        from sajha.core.config import parse_bool
        a = auth or {}

        def scopes(v):
            if isinstance(v, str):
                v = v.split()
            return [str(s).strip() for s in (v or []) if str(s).strip()]
        params = a.get('authorize_params') if isinstance(a.get('authorize_params'), dict) else {}
        return cls(scopes=scopes(a.get('scopes')), write_scopes=scopes(a.get('write_scopes')),
                   vendor=str(a.get('vendor') or '').strip(), client_id=str(a.get('client_id') or '').strip(),
                   client_secret_ref=str(a.get('client_secret_ref') or '').strip(),
                   token_auth_method=str(a.get('token_auth_method') or '').strip(),
                   authorization_server=str(a.get('authorization_server') or '').strip().rstrip('/'),
                   authorize_url=str(a.get('authorize_url') or '').strip(),
                   token_url=str(a.get('token_url') or '').strip(), revoke_url=str(a.get('revoke_url') or '').strip(),
                   revoke_style=str(a.get('revoke_style') or '').strip(), resource=str(a.get('resource') or '').strip(),
                   resource_indicator=parse_bool(a.get('resource_indicator'), True)
                   if 'resource_indicator' in a else True,
                   authorize_params={str(k): str(v) for k, v in params.items() if not str(k).startswith('_')},
                   help_url=str(a.get('help_url') or '').strip())

    def problems(self) -> List[str]:
        out = []
        from sajha.federation.config import _is_ref
        if self.client_secret_ref and not _is_ref(self.client_secret_ref):
            out.append('auth.client_secret_ref must be a reference (env:NAME, file:/path or db:table/key), '
                       'never the secret itself')
        if self.client_secret_ref and not self.client_id:
            out.append('auth.client_secret_ref needs auth.client_id (the operator-registered client)')
        if self.token_auth_method and self.token_auth_method not in TOKEN_AUTH_METHODS:
            out.append(f'auth.token_auth_method must be one of {", ".join(TOKEN_AUTH_METHODS)}')
        if self.revoke_style and self.revoke_style not in REVOKE_STYLES:
            out.append(f'auth.revoke_style must be one of {", ".join(REVOKE_STYLES)}')
        if bool(self.authorize_url) != bool(self.token_url):
            out.append('auth.authorize_url and auth.token_url go together (or neither: discovered)')
        for key in ('authorization_server', 'authorize_url', 'token_url', 'revoke_url', 'resource', 'help_url'):
            v = getattr(self, key)
            if v and not re.match(r'^https?://', v):
                out.append(f'auth.{key} must be an http(s) URL')
        if self.authorize_url and not self.client_id:
            out.append('auth.authorize_url without discovery needs auth.client_id (no dynamic registration '
                       'without an authorization server\'s metadata)')
        for s in self.scopes + self.write_scopes:
            if any(c.isspace() for c in s) or '"' in s:
                out.append(f'auth scope {s[:40]!r} contains a space or a quote')
                break
        return out

    @property
    def button_vendor(self) -> str:
        return self.vendor


@dataclass
class Endpoints:
    """What discovery found (or the operator gave) for one upstream."""
    issuer: str = ''
    authorize_url: str = ''
    token_url: str = ''
    revoke_url: str = ''
    registration_url: str = ''
    resource: str = ''
    scopes_supported: List[str] = field(default_factory=list)
    auth_methods: List[str] = field(default_factory=list)
    fetched_at: float = 0.0


# ── helpers ─────────────────────────────────────────────────────────

def callback_url(request=None) -> str:
    """The redirect URI: :data:`CALLBACK_PATH` on ``accounts.public_url`` (recommended: one fixed
    value to register at vendors), else on the request's own origin."""
    from sajha.accounts.settings import base_url
    return base_url(request) + CALLBACK_PATH


def _fed_settings():
    from sajha.federation.manager import get_federation
    m = get_federation()
    if m is not None:
        return m.settings
    from sajha.federation.config import FederationSettings
    return FederationSettings.load()


def check_oauth_url(url: str, what: str, settings=None) -> str:
    """``url`` when it may be fetched or sent a user's browser to: https (http only on loopback with
    federation.allow_localhost) and allowed by the federation URL guard."""
    from sajha.federation.security import UnsafeURLError, check_url
    s = settings or _fed_settings()
    p = urlsplit(url or '')
    host = (p.hostname or '').lower()
    loopback = host in ('127.0.0.1', 'localhost', '::1')
    if p.scheme != 'https' and not (p.scheme == 'http' and loopback and s.allow_localhost):
        raise OAuthUserError(f'{what} must be an https URL ({url[:120]})')
    try:
        check_url(url, s)
    except UnsafeURLError as e:
        raise OAuthUserError(f'{what} is not an allowed destination: {e}') from None
    return url


def _get_json(url: str, what: str, settings=None) -> Optional[Dict[str, Any]]:
    """GET ``url`` as JSON; None when absent (404/405/410 or not JSON); OAuthUserError when unreachable."""
    import httpx
    from sajha.accounts import http as ahttp
    check_oauth_url(url, what, settings)
    try:
        with ahttp.client() as c:
            r = c.get(url, headers={'Accept': 'application/json'})
    except httpx.HTTPError as e:
        raise OAuthUserError(f'{what} could not be fetched ({type(e).__name__})') from None
    if r.status_code != 200 or len(r.content) > _MAX_METADATA_BYTES:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _origin(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, '', '', ''))


def _well_known(base: str, suffix: str) -> List[str]:
    """RFC 8414 / RFC 9728 well-known URLs for ``base``: the path-inserted form first."""
    p = urlsplit(base)
    path = p.path.rstrip('/')
    out = []
    if path:
        out.append(urlunsplit((p.scheme, p.netloc, f'/.well-known/{suffix}{path}', '', '')))
    out.append(urlunsplit((p.scheme, p.netloc, f'/.well-known/{suffix}', '', '')))
    return out


def _probe_resource_metadata_url(url: str, settings) -> Optional[str]:
    """The ``resource_metadata`` URL from the server's 401 (MCP authorization, RFC 9728 §5.1)."""
    import httpx
    from sajha.accounts import http as ahttp
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                       'clientInfo': {'name': 'sajha-oauth-discovery', 'version': '1'}}}
    try:
        with ahttp.client() as c:
            r = c.post(url, json=body, headers={'Accept': 'application/json, text/event-stream'})
    except httpx.HTTPError:
        return None
    if r.status_code != 401:
        return None
    m = _RESOURCE_METADATA.search(r.headers.get('www-authenticate', ''))
    return m.group(1) if m else None


# ── the per-upstream registry and service ───────────────────────────

class UpstreamOAuth:
    """Discovery, client registration and the OAuth flow for every oauth_user upstream."""

    def __init__(self, tokens=None):
        self._tokens = tokens
        self._lock = threading.Lock()
        self._endpoints: Dict[str, Tuple[str, Endpoints]] = {}     # upstream id -> (config hash, endpoints)
        self.service = _Service(self)

    @property
    def tokens(self):
        if self._tokens is not None:
            return self._tokens
        from sajha.federation.user_tokens import get_tokens
        return get_tokens()

    @property
    def vault(self):
        return self.tokens.vault

    # ── configuration lookup ───────────────────────────────────────
    @staticmethod
    def config(upstream_id: str):
        from sajha.federation.manager import get_federation
        m = get_federation()
        return m.get_config(upstream_id) if m is not None else None

    @staticmethod
    def _key(cfg) -> str:
        import json
        return json.dumps([cfg.url, cfg.auth], sort_keys=True, default=str)

    # ── discovery ──────────────────────────────────────────────────
    def endpoints(self, cfg, refresh: bool = False) -> Endpoints:
        key = self._key(cfg)
        with self._lock:
            hit = self._endpoints.get(cfg.id)
        if hit and hit[0] == key and not refresh and time.time() - hit[1].fetched_at < METADATA_TTL_SECONDS:
            return hit[1]
        ep = self._discover(cfg)
        with self._lock:
            self._endpoints[cfg.id] = (key, ep)
        return ep

    def forget(self, upstream_id: str) -> None:
        with self._lock:
            self._endpoints.pop(upstream_id, None)

    def _discover(self, cfg) -> Endpoints:
        spec = OAuthUserSpec.from_auth(cfg.auth)
        settings = _fed_settings()
        resource = spec.resource or cfg.url
        if spec.authorize_url and spec.token_url:            # the operator gave the endpoints
            for k in ('authorize_url', 'token_url', 'revoke_url'):
                if getattr(spec, k):
                    check_oauth_url(getattr(spec, k), f'auth.{k}', settings)
            return Endpoints(issuer=_origin(spec.authorize_url), authorize_url=spec.authorize_url,
                             token_url=spec.token_url, revoke_url=spec.revoke_url, resource=resource,
                             fetched_at=time.time())
        title = cfg.display_title
        prm = None
        prm_url = _probe_resource_metadata_url(cfg.url, settings)
        candidates = ([prm_url] if prm_url else []) + _well_known(cfg.url, 'oauth-protected-resource')
        for u in candidates:
            prm = _get_json(u, f'{title}\'s protected-resource metadata', settings)
            if prm:
                break
        issuer = spec.authorization_server
        if prm:
            if prm.get('resource') and _origin(str(prm['resource'])) != _origin(cfg.url):
                raise OAuthUserError(f'{title}\'s protected-resource metadata names another server '
                                     f'({str(prm["resource"])[:120]}); refusing it')
            resource = spec.resource or str(prm.get('resource') or cfg.url)
            servers = [str(s) for s in prm.get('authorization_servers') or [] if isinstance(s, str)]
            if not issuer and servers:
                issuer = servers[0].rstrip('/')
        if not issuer:
            if not prm:
                raise OAuthUserError(f'{title} publishes no OAuth metadata (RFC 9728) and none is configured: '
                                     f'an administrator sets auth.authorization_server, or auth.authorize_url '
                                     f'and auth.token_url')
            raise OAuthUserError(f'{title}\'s metadata names no authorization server')
        asm = None
        for u in (_well_known(issuer, 'oauth-authorization-server') + _well_known(issuer, 'openid-configuration')
                  + ([issuer + '/.well-known/openid-configuration'] if urlsplit(issuer).path.strip('/') else [])):
            asm = _get_json(u, f'{title}\'s authorization server metadata', settings)
            if asm:
                break
        if not asm:
            raise OAuthUserError(f'The authorization server of {title} ({issuer[:120]}) publishes no metadata '
                                 f'(RFC 8414 or OpenID Connect discovery)')
        if str(asm.get('issuer') or '').rstrip('/') != issuer:
            raise OAuthUserError(f'The authorization server metadata of {title} names a different issuer; '
                                 f'refusing it')
        methods = asm.get('code_challenge_methods_supported')
        if not isinstance(methods, list) or 'S256' not in methods:
            raise OAuthUserError(f'The authorization server of {title} does not advertise PKCE with S256, '
                                 f'which SAJHA requires')
        ep = Endpoints(issuer=issuer, authorize_url=str(asm.get('authorization_endpoint') or ''),
                       token_url=str(asm.get('token_endpoint') or ''),
                       revoke_url=spec.revoke_url or str(asm.get('revocation_endpoint') or ''),
                       registration_url=str(asm.get('registration_endpoint') or ''), resource=resource,
                       scopes_supported=[str(s) for s in asm.get('scopes_supported') or []],
                       auth_methods=[str(s) for s in asm.get('token_endpoint_auth_methods_supported') or []],
                       fetched_at=time.time())
        if not ep.authorize_url or not ep.token_url:
            raise OAuthUserError(f'The authorization server of {title} lists no authorization or token endpoint')
        for k in ('authorize_url', 'token_url', 'revoke_url', 'registration_url'):
            if getattr(ep, k):
                check_oauth_url(getattr(ep, k), f'{title}\'s {k.replace("_", " ")}', settings)
        return ep

    # ── the client ────────────────────────────────────────────────
    def client(self, cfg, redirect: Optional[str] = None) -> Dict[str, str]:
        """{client_id, client_secret, auth_method, source}. ``redirect`` given: register (again) when
        there is no dynamic registration for that redirect URI yet."""
        spec = OAuthUserSpec.from_auth(cfg.auth)
        if spec.client_id:
            return {'client_id': spec.client_id, 'client_secret': '', 'source': 'operator',
                    'auth_method': spec.token_auth_method or ('client_secret_post' if spec.client_secret_ref
                                                              else 'none')}
        from sajha.federation.user_tokens import vault_provider
        pid = vault_provider(cfg.id)
        ep = self.endpoints(cfg)
        row = self.vault.get(CLIENT_ROW, pid)
        doc = self.vault.tokens(row) if row is not None else {}
        if doc.get('client_id') and doc.get('issuer') == ep.issuer and (redirect is None
                                                                        or doc.get('redirect_uri') == redirect):
            return {'client_id': doc['client_id'], 'client_secret': doc.get('client_secret') or '',
                    'auth_method': doc.get('auth_method') or 'none', 'source': 'dynamic'}
        if redirect is None:
            raise OAuthUserError(f'{cfg.display_title} has no registered client yet; connect from the '
                                 f'Server connections page first')
        return self._register(cfg, ep, redirect, spec)

    def _register(self, cfg, ep: Endpoints, redirect: str, spec: OAuthUserSpec) -> Dict[str, str]:
        import httpx
        from sajha.accounts import http as ahttp
        from sajha.federation.user_tokens import vault_provider
        title = cfg.display_title
        if not ep.registration_url:
            raise OAuthUserError(f'The authorization server of {title} does not offer dynamic client registration; '
                                 f'an administrator registers a client there and sets auth.client_id and '
                                 f'auth.client_secret_ref')
        method = 'none'
        if ep.auth_methods and 'none' not in ep.auth_methods:
            method = 'client_secret_post' if 'client_secret_post' in ep.auth_methods else 'client_secret_basic'
        body = {'client_name': 'SAJHA MCP Server', 'redirect_uris': [redirect],
                'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                'token_endpoint_auth_method': method}
        if spec.scopes or spec.write_scopes:
            body['scope'] = ' '.join(spec.scopes + [s for s in spec.write_scopes if s not in spec.scopes])
        try:
            with ahttp.client() as c:
                r = c.post(ep.registration_url, json=body, headers={'Accept': 'application/json'})
        except httpx.HTTPError as e:
            raise OAuthUserError(f'Registering SAJHA at {title}\'s authorization server failed '
                                 f'({type(e).__name__})') from None
        data = ahttp.parse_token_response(r)
        if r.status_code not in (200, 201) or not data.get('client_id'):
            code = str(data.get('error') or f'HTTP {r.status_code}')[:80]
            raise OAuthUserError(f'{title}\'s authorization server refused to register SAJHA ({code})')
        doc = {'client_id': str(data['client_id']), 'client_secret': str(data.get('client_secret') or ''),
               'auth_method': str(data.get('token_endpoint_auth_method') or method), 'redirect_uri': redirect,
               'issuer': ep.issuer}
        self.vault.save(CLIENT_ROW, vault_provider(cfg.id), doc, scopes=[], expires_at=None,
                        account_login='registered client')
        self.tokens.audit('proxied_connection.client_registered', 'system', cfg.id, issuer=ep.issuer)
        return {'client_id': doc['client_id'], 'client_secret': doc['client_secret'],
                'auth_method': doc['auth_method'], 'source': 'dynamic'}

    # ── the Provider the connected-accounts flow runs on ───────────
    def provider(self, cfg, redirect: Optional[str] = None) -> Provider:
        from sajha.federation.user_tokens import vault_provider
        spec = OAuthUserSpec.from_auth(cfg.auth)
        ep = self.endpoints(cfg)
        client = self.client(cfg, redirect)
        params = dict(spec.authorize_params)
        token_params: Dict[str, str] = {}
        if spec.resource_indicator and ep.resource:
            params['resource'] = ep.resource
            token_params['resource'] = ep.resource
        style = spec.revoke_style or ('rfc7009' if ep.revoke_url else 'none')
        p = Provider(id=vault_provider(cfg.id), title=cfg.display_title, authorize_url=ep.authorize_url,
                     token_url=ep.token_url, revoke_url=ep.revoke_url, revoke_style=style,
                     scopes=list(spec.scopes), pkce=True,
                     token_auth_method=client['auth_method'] if client['auth_method'] in TOKEN_AUTH_METHODS
                     else 'client_secret_post',
                     authorize_params=params, token_params=token_params,
                     api_hosts=[(urlsplit(cfg.url).hostname or '').lower()], client_id=client['client_id'],
                     client_secret_ref=spec.client_secret_ref if client['source'] == 'operator' else '')
        p.client_secret = client['client_secret']          # a dynamically registered secret (never logged)
        return p

    # ── the flow ───────────────────────────────────────────────────
    def start(self, cfg, user_id: str, *, browser_nonce: str, request=None, write: bool = False) -> str:
        """The vendor's authorize URL for ``user_id`` (read scopes, plus write scopes when ``write``)."""
        from sajha.federation.user_tokens import auth_mode
        if auth_mode(cfg) != 'oauth_user':
            raise OAuthUserError(f'{cfg.display_title} does not sign users in with OAuth.')
        spec = OAuthUserSpec.from_auth(cfg.auth)
        redirect = callback_url(request)
        p = self.provider(cfg, redirect)
        wanted = list(spec.write_scopes) if write else []
        return self.service.start(user_id, p.id, browser_nonce=browser_nonce, request=request, scopes=wanted,
                                  keep_granted=False)

    def flow_upstream(self, state: str) -> Optional[str]:
        """Which upstream a callback's ``state`` belongs to (without using it up)."""
        from sajha.accounts.service import FLOW_PREFIX
        from sajha.federation.user_tokens import PROVIDER_PREFIX
        rec = self.service.store.get(FLOW_PREFIX + state) if state else None
        pid = rec.get('p') if isinstance(rec, dict) else ''
        return pid[len(PROVIDER_PREFIX):] if isinstance(pid, str) and pid.startswith(PROVIDER_PREFIX) else None

    def complete(self, cfg, user_id: str, *, state: str, code: str = '', error: str = '',
                 error_description: str = '', browser_nonce: str = '', ip: Optional[str] = None):
        from sajha.federation.user_tokens import vault_provider
        out = self.service.complete(user_id, vault_provider(cfg.id), state=state, code=code, error=error,
                                    error_description=error_description, browser_nonce=browser_nonce, ip=ip)
        conn = out['connection']
        spec = OAuthUserSpec.from_auth(cfg.auth)
        self.tokens.audit('proxied_connection.connected', user_id, cfg.id, ip, user=user_id, mode='oauth_user',
                          scopes=list(conn.scopes),
                          write=bool(set(spec.write_scopes) & set(conn.scopes)))
        return conn

    # ── tokens ─────────────────────────────────────────────────────
    def fresh(self, cfg, conn, force: bool = False, tool: str = ''):
        """``conn`` refreshed when it expires soon (or ``force``: the vendor answered 401)."""
        from sajha.accounts.settings import get_accounts_settings
        if not force and not conn.expires_within(get_accounts_settings().refresh_skew_seconds):
            return conn
        p = self.provider(cfg)
        return self.service._refresh(p, conn, force=force, tool=tool)

    def revoke(self, cfg, doc: Dict[str, Any]) -> Optional[bool]:
        """Revoke at the vendor (best effort): True/False, or None when it advertises no endpoint."""
        p = self.provider(cfg)
        if p.revoke_style == 'none' or not p.revoke_url:
            return None
        return self.service._revoke(p, doc)


class _Registry:
    """The connected-accounts registry view of oauth_user upstreams (provider id ``upstream:<id>``)."""

    def __init__(self, owner: UpstreamOAuth):
        self.owner = owner
        self.errors: Dict[str, str] = {}

    def get(self, pid: str) -> Optional[Provider]:
        from sajha.federation.user_tokens import PROVIDER_PREFIX
        if not pid.startswith(PROVIDER_PREFIX):
            return None
        cfg = self.owner.config(pid[len(PROVIDER_PREFIX):])
        if cfg is None:
            return None
        try:
            return self.owner.provider(cfg)
        except OAuthFlowError:
            return None

    def all(self) -> List[Provider]:
        return []


class _Service(ConnectedAccountsService):
    """The connected-accounts flow with upstream answers: "connect" links point at Server connections,
    and the redirect URI is the one oauth_user callback."""

    def __init__(self, owner: UpstreamOAuth):
        super().__init__(registry=_Registry(owner))
        self.owner = owner

    @property
    def vault(self):
        return self.owner.vault

    def redirect_uri(self, p: Provider, request=None) -> str:
        return callback_url(request)

    def required(self, pid: str, reason: str, user_id: str = '', scopes=None, tool: str = ''):
        from sajha.accounts.errors import ConnectedAccountRequired
        from sajha.federation.user_tokens import PROVIDER_PREFIX
        uid = pid[len(PROVIDER_PREFIX):] if pid.startswith(PROVIDER_PREFIX) else pid
        cfg = self.owner.config(uid)
        if cfg is not None:
            return self.owner.tokens.required(cfg, reason, user_id, tool)
        return ConnectedAccountRequired(pid, provider_title=uid, connect_url=self.owner.tokens.connect_url(uid),
                                        reason=reason, user_id=user_id, tool=tool)

    @staticmethod
    def audit(action: str, user_id: str, provider: str, ip: Optional[str] = None, **details) -> None:
        # the flow's own events, under the proxied-connection resource (never a token)
        from sajha.federation.user_tokens import PROVIDER_PREFIX, ProxiedTokens
        names = {'connected_account_state_rejected': 'proxied_connection.state_rejected',
                 'connected_account_link_failed': 'proxied_connection.connect_failed',
                 'connected_account_refreshed': 'proxied_connection.refreshed',
                 'connected_account_refresh_failed': 'proxied_connection.refresh_failed'}
        if action not in names:
            return           # linked / disconnected are audited by the callers with more detail
        upstream = provider[len(PROVIDER_PREFIX):] if provider.startswith(PROVIDER_PREFIX) else provider
        ProxiedTokens.audit(names[action], user_id, upstream, ip, user=user_id, **details)


_oauth: Optional[UpstreamOAuth] = None
_olock = threading.Lock()


def get_oauth() -> UpstreamOAuth:
    global _oauth
    if _oauth is None:
        with _olock:
            if _oauth is None:
                _oauth = UpstreamOAuth()
    return _oauth


def set_oauth(oauth: Optional[UpstreamOAuth]) -> None:
    global _oauth
    _oauth = oauth
