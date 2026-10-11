"""
SAJHA MCP Server — per-user tokens for proxied MCP servers (``auth.type: token_user`` and ``oauth_user``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A proxied server whose ``auth.type`` is ``token_user`` is called **as the person who asked**,
with a personal token that person pasted once on the connect page
(``/account/server-connections/<upstream>``). This module owns those tokens:

* **Storage.** The connected-accounts token vault (``sajha/accounts/vault.py``): one row per
  (SAJHA user, upstream) under the provider key ``upstream:<id>``, the token AES-256-GCM
  encrypted and bound to that user and upstream. Only a masked hint (``••••`` and the last four
  characters) is kept in clear, for the pages; the token itself is never shown, logged or
  returned by any API after it is saved.
* **Lookup at call time** (:meth:`ProxiedTokens.resolve`): the caller's own token, or
  :class:`~sajha.accounts.errors.ConnectedAccountRequired` (the same "connect your account"
  answer connected accounts give on every front end) when the caller has none, has one that
  the vendor refused (``needs re-connect``), or is not a signed-in user at all.
* **OAuth tokens** (``oauth_user``) come from the sign-in flow in
  :mod:`sajha.federation.oauth_user` and are kept the same way; :meth:`ProxiedTokens.resolve`
  refreshes one shortly before it expires, :meth:`ProxiedTokens.refresh_after_401` once when the
  vendor refuses it, and removing one revokes it at the vendor when the vendor offers revocation.
* **Status, revocation and audit:** connected / needs re-connect / not connected per user;
  every connect, replace and disconnect audited (``proxied_connection.*``, never the token);
  every token of a user deleted when the user is disabled, deleted or signs out everywhere.

Design: docs/architecture/Per-User Sign-In for Proxied Servers.md; how it fits federation:
docs/architecture/Federation.md, "Per-user credentials".
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: the vault's provider key for an upstream's per-user tokens
PROVIDER_PREFIX = 'upstream:'
#: credential modes (``auth.type``) and what each means for who the vendor sees
PER_USER_MODES = ('token_user', 'oauth_user')
#: the longest token accepted from the connect page
MAX_TOKEN_CHARS = 8192
_HEADER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,63}$')


def auth_mode(config) -> str:
    """``static`` (one shared identity: headers or a configured credential), ``token_user``,
    ``oauth_user`` or ``connected_account``."""
    t = ((getattr(config, 'auth', None) or {}).get('type') or 'none')
    return t if t in ('token_user', 'oauth_user', 'connected_account') else 'static'


def vault_provider(upstream_id: str) -> str:
    return PROVIDER_PREFIX + upstream_id


def header_for(config, token: str):
    """(header, value) carrying ``token`` to the upstream: ``auth.header``/``auth.format`` for
    token_user, ``Authorization: Bearer`` for oauth_user."""
    if auth_mode(config) == 'oauth_user':
        return 'Authorization', f'Bearer {token}'
    return TokenUserSpec.from_auth(config.auth).header_value(token)


def _client_row(user_id: str) -> bool:
    from sajha.federation.oauth_user import CLIENT_ROW
    return user_id == CLIENT_ROW


def masked(token: str) -> str:
    """What the pages show of a saved token: never more than its last four characters."""
    t = token or ''
    return '••••' + t[-4:] if len(t) >= 12 else '••••'


@dataclass
class TokenUserSpec:
    """The ``auth`` block of a ``token_user`` upstream."""
    header: str = 'Authorization'
    format: str = 'Bearer {token}'
    label: str = 'Personal access token'
    help_url: str = ''
    token_prefix: str = ''
    token_pattern: str = ''
    test_call: bool = True

    KEYS = ('type', 'header', 'format', 'label', 'help_url', 'token_prefix', 'token_pattern', 'test_call',
            'discovery')

    @classmethod
    def from_auth(cls, auth: Optional[Dict[str, Any]]) -> 'TokenUserSpec':
        a = auth or {}
        from sajha.core.config import parse_bool
        return cls(header=str(a.get('header') or 'Authorization').strip(),
                   format=str(a.get('format') or 'Bearer {token}'),
                   label=str(a.get('label') or 'Personal access token').strip(),
                   help_url=str(a.get('help_url') or '').strip(),
                   token_prefix=str(a.get('token_prefix') or ''),
                   token_pattern=str(a.get('token_pattern') or ''),
                   test_call=parse_bool(a.get('test_call'), True) if 'test_call' in a else True)

    def problems(self) -> List[str]:
        out = []
        if not _HEADER.match(self.header):
            out.append('auth.header must be an HTTP header name (letters, digits and "-")')
        if self.format.count('{token}') != 1:
            out.append('auth.format must contain {token} exactly once (for example "Bearer {token}")')
        elif any(c in self.format for c in '\r\n'):
            out.append('auth.format must be one line')
        if self.help_url and not re.match(r'^https?://', self.help_url):
            out.append('auth.help_url must be an http(s) URL')
        if self.token_pattern:
            try:
                re.compile(self.token_pattern)
            except re.error as e:
                out.append(f'auth.token_pattern is not a regular expression: {e}')
        return out

    def header_value(self, token: str):
        return self.header, self.format.replace('{token}', token)

    def check_token(self, token: str) -> Optional[str]:
        """Why ``token`` cannot be right (never echoing it), or None."""
        if not token:
            return 'Paste a token first.'
        if len(token) > MAX_TOKEN_CHARS:
            return f'That is longer than any token SAJHA accepts ({MAX_TOKEN_CHARS} characters).'
        if any(c.isspace() for c in token) or any(ord(c) < 32 for c in token):
            return 'A token has no spaces or line breaks; copy it again without them.'
        if self.token_prefix and not token.startswith(self.token_prefix):
            return f'This server expects a token starting with "{self.token_prefix}".'
        if self.token_pattern and not re.fullmatch(self.token_pattern, token):
            return 'That does not look like a token for this server (it does not match the expected format).'
        return None


class TokenRejected(ValueError):
    """A pasted token failed validation or the test call; the message never contains it."""


class ProxiedTokens:
    """Per-user tokens of ``token_user`` upstreams, in the connected-accounts vault."""

    def __init__(self, vault=None):
        self._vault = vault

    @property
    def vault(self):
        if self._vault is not None:
            return self._vault
        from sajha.accounts.vault import get_vault
        return get_vault()

    # ── links and answers ──────────────────────────────────────────
    @staticmethod
    def connect_url(upstream_id: str, request=None) -> str:
        from sajha.accounts.settings import base_url
        return f'{base_url(request)}/account/server-connections/{upstream_id}'

    def required(self, config, reason: str, user_id: str = '', tool: str = ''):
        """The "connect your account" answer for this upstream (every front end renders it)."""
        from sajha.accounts.errors import ConnectedAccountRequired
        return ConnectedAccountRequired(vault_provider(config.id), provider_title=config.display_title,
                                        connect_url=self.connect_url(config.id), reason=reason,
                                        user_id=user_id, tool=tool)

    # ── call time ──────────────────────────────────────────────────
    def resolve(self, config, user_id: str, tool: str = '') -> str:
        """The caller's token for ``config``; raises ConnectedAccountRequired. Never another
        user's token, never the upstream's static credential."""
        from sajha.accounts.service import is_user_caller
        if not is_user_caller(user_id):
            raise self.required(config, 'sign_in_required', user_id or 'anonymous', tool)
        conn = self.vault.get(user_id, vault_provider(config.id))
        if conn is None:
            raise self.required(config, 'not_connected', user_id, tool)
        if conn.status != 'active':
            raise self.required(config, 'reauth_required', user_id, tool)
        if auth_mode(config) == 'oauth_user':
            from sajha.federation.oauth_user import get_oauth
            conn = get_oauth().fresh(config, conn, tool=tool)      # refreshed shortly before it expires
        token = (self.vault.tokens(conn) or {}).get('access_token') or ''
        if not token:
            raise self.required(config, 'not_connected', user_id, tool)
        self.vault.touch(conn)
        return token

    def refresh_after_401(self, config, user_id: str, tool: str = '') -> str:
        """oauth_user: the vendor answered 401 to the caller's token. Refresh it once and return the
        new token; without a refresh token, or when the refresh is refused, the connection is marked
        "needs re-connect" and ConnectedAccountRequired is raised."""
        from sajha.federation.oauth_user import get_oauth
        conn = self.vault.get(user_id, vault_provider(config.id))
        if conn is None:
            raise self.required(config, 'not_connected', user_id, tool)
        if not conn.has_refresh_token:
            self.mark_needs_reconnect(config.id, user_id, 'the server refused the token (HTTP 401) and it '
                                                          'cannot be refreshed')
            raise self.required(config, 'reauth_required', user_id, tool)
        conn = get_oauth().fresh(config, conn, force=True, tool=tool)
        return (self.vault.tokens(conn) or {}).get('access_token') or ''

    def first_token(self, upstream_id: str, config=None) -> Optional[str]:
        """Discovery without a discovery credential: the token of the first user who connected
        (and whose token the vendor still accepts; an OAuth token is refreshed first when due)."""
        try:
            rows = [c for c in self.vault.list_all(provider=vault_provider(upstream_id), limit=500)
                    if c.status == 'active' and not _client_row(c.user_id)]
        except Exception as e:
            logger.debug(f'federation: per-user tokens of {upstream_id} unavailable: {type(e).__name__}')
            return None
        for c in sorted(rows, key=lambda c: (c.created_at is None, c.created_at)):
            try:
                if config is not None and auth_mode(config) == 'oauth_user':
                    from sajha.federation.oauth_user import get_oauth
                    c = get_oauth().fresh(config, c)
                tok = (self.vault.tokens(c) or {}).get('access_token')
            except Exception:
                continue
            if tok:
                return tok
        return None

    def mark_needs_reconnect(self, upstream_id: str, user_id: str, why: str) -> None:
        try:
            self.vault.set_status(user_id, vault_provider(upstream_id), 'reauth_required', why[:300])
        except Exception as e:
            logger.warning(f'federation: could not mark {upstream_id} for re-connect: {type(e).__name__}')
        self.audit('proxied_connection.refused', user_id, upstream_id, user=user_id, why=why[:300])

    # ── connect page ───────────────────────────────────────────────
    def save(self, config, user_id: str, token: str, *, actor: str = '', ip: Optional[str] = None,
             tester=None) -> Dict[str, Any]:
        """Validate, optionally test (``tester(token) -> tools``; raises TokenRejected), encrypt and
        store ``user_id``'s token for ``config``. Returns the public status (never the token)."""
        from sajha.accounts.service import is_user_caller
        if not is_user_caller(user_id):
            raise TokenRejected('Per-user tokens belong to signed-in users.')
        if auth_mode(config) != 'token_user':
            raise TokenRejected(f'{config.display_title} does not take personal tokens.')
        token = (token or '').strip()
        spec = TokenUserSpec.from_auth(config.auth)
        why = spec.check_token(token)
        if why:
            raise TokenRejected(why)
        tools = None
        if tester is not None:
            tools = tester(token)
        replaced = self.vault.get(user_id, vault_provider(config.id)) is not None
        self.vault.save(user_id, vault_provider(config.id), {'access_token': token}, scopes=[], expires_at=None,
                        account_login=masked(token))
        self.audit('proxied_connection.replaced' if replaced else 'proxied_connection.connected',
                   actor or user_id, config.id, ip, user=user_id, tested=tester is not None,
                   tools=len(tools) if tools is not None else None)
        _user_connected(config.id)
        out = self.status_of(config, user_id)
        if tools is not None:
            out['tools_seen'] = len(tools)
        return out

    def remove(self, upstream_id: str, user_id: str, *, actor: str = '', ip: Optional[str] = None,
               reason: str = '') -> bool:
        """Forget ``user_id``'s token for the upstream; an OAuth token is first revoked at the vendor
        when it advertises revocation (best effort: the token is deleted here either way)."""
        done, revoked = False, None
        try:
            revoked = self._revoke_at_vendor(upstream_id, user_id)
        except Exception as e:
            revoked = False
            logger.info(f'federation: revocation at the vendor failed ({type(e).__name__}); deleting anyway')
        try:
            done = self.vault.delete(user_id, vault_provider(upstream_id))
        except Exception as e:
            logger.warning(f'federation: removing a per-user token failed: {type(e).__name__}')
        if done:
            self.audit('proxied_connection.disconnected', actor or user_id, upstream_id, ip, user=user_id,
                       by_admin=bool(actor and actor != user_id), reason=reason, revoked_at_vendor=revoked)
            _close_user_sessions(upstream_id, user_id)
        return done

    def _revoke_at_vendor(self, upstream_id: str, user_id: str) -> Optional[bool]:
        from sajha.federation.oauth_user import UpstreamOAuth, get_oauth
        cfg = UpstreamOAuth.config(upstream_id)
        if cfg is None or auth_mode(cfg) != 'oauth_user':
            return None
        conn = self.vault.get(user_id, vault_provider(upstream_id))
        if conn is None:
            return None
        return get_oauth().revoke(cfg, self.vault.tokens(conn))

    def revoke_user(self, user_id: str, *, actor: str = '', reason: str = '') -> int:
        """Delete every proxied-server token of ``user_id`` (user disabled, deleted, signed out
        everywhere). Returns how many were deleted."""
        try:
            rows = [c for c in self.vault.list_all(user_id=user_id, limit=1000)
                    if c.provider.startswith(PROVIDER_PREFIX)]
        except Exception as e:
            logger.warning(f'federation: per-user tokens of a user could not be listed: {type(e).__name__}')
            return 0
        n = 0
        for c in rows:
            if self.remove(c.provider[len(PROVIDER_PREFIX):], user_id, actor=actor or 'system', reason=reason):
                n += 1
        return n

    # ── views ──────────────────────────────────────────────────────
    def status_of(self, config, user_id: str, conn=None) -> Dict[str, Any]:
        mode = auth_mode(config)
        spec = TokenUserSpec.from_auth(config.auth) if mode == 'token_user' else None
        if conn is None and mode in PER_USER_MODES:
            try:
                conn = self.vault.get(user_id, vault_provider(config.id))
            except Exception:
                conn = None
        status = 'not_connected'
        if conn is not None:
            status = 'connected' if conn.status == 'active' else 'needs_reconnect'
        pub = conn.to_public() if conn is not None else {}
        return {'upstream': config.id, 'title': config.display_title, 'mode': mode, 'status': status,
                'token_hint': pub.get('account_login') or '', 'connected_at': pub.get('created_at'),
                'updated_at': pub.get('updated_at'), 'last_used_at': pub.get('last_used_at'),
                'last_error': pub.get('last_error') or '',
                'label': spec.label if spec else '', 'help_url': spec.help_url if spec else '',
                'header': spec.header if spec else '', 'token_prefix': spec.token_prefix if spec else '',
                **(_oauth_status(config, pub) if mode == 'oauth_user' else {})}

    def all_connections(self, upstream_id: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Who is connected to which upstream (administrators): metadata only, never a token."""
        rows = self.vault.list_all(provider=vault_provider(upstream_id) if upstream_id else None, user_id=user_id,
                                   limit=5000)
        out = []
        for c in rows:
            if not c.provider.startswith(PROVIDER_PREFIX) or _client_row(c.user_id):
                continue
            pub = c.to_public()
            oauth = bool(pub['expires_at'] or pub['refreshable'] or pub['scopes'])
            out.append({'upstream': c.provider[len(PROVIDER_PREFIX):], 'user_id': c.user_id,
                        'status': 'connected' if c.status == 'active' else 'needs_reconnect',
                        'token_hint': pub['account_login'] if not oauth else '', 'connected_at': pub['created_at'],
                        'updated_at': pub['updated_at'], 'last_used_at': pub['last_used_at'],
                        'last_error': pub['last_error'] or '', 'kind': 'oauth' if oauth else 'token',
                        'scopes': pub['scopes'], 'expires_at': pub['expires_at'],
                        'refreshable': pub['refreshable']})
        return out

    # ── audit ──────────────────────────────────────────────────────
    @staticmethod
    def audit(action: str, actor: str, upstream_id: str, ip: Optional[str] = None, **details) -> None:
        try:
            from sajha.core.audit import get_audit_logger
            clean = {k: v for k, v in details.items() if v not in (None, '', [])}
            get_audit_logger().log(action, user_id=actor, resource_type='proxied_connection',
                                   resource_id=upstream_id, details=json.dumps(clean, default=str) if clean else None,
                                   ip_address=ip)
        except Exception as e:
            logger.debug(f'federation: audit {action} failed: {type(e).__name__}')


def _oauth_status(config, pub: Dict[str, Any]) -> Dict[str, Any]:
    """What the pages show of an OAuth connection: scopes, expiry, whether changes were allowed."""
    from sajha.federation.oauth_user import OAuthUserSpec
    spec = OAuthUserSpec.from_auth(config.auth)
    granted = list(pub.get('scopes') or [])
    return {'token_hint': '', 'scopes': granted, 'expires_at': pub.get('expires_at'),
            'refreshable': bool(pub.get('refreshable')), 'read_scopes': spec.scopes,
            'write_scopes': spec.write_scopes, 'write_granted': bool(set(spec.write_scopes) & set(granted)),
            'vendor': spec.vendor or config.display_title, 'help_url': spec.help_url}


def _user_connected(upstream_id: str) -> None:
    try:
        from sajha.federation.manager import get_federation
        m = get_federation()
        if m is not None:
            m.user_connected(upstream_id)
    except Exception as e:
        logger.debug(f'federation: after a connect: {type(e).__name__}')


def _close_user_sessions(upstream_id: str, user_id: str) -> None:
    try:
        from sajha.federation.manager import get_federation
        m = get_federation()
        if m is not None:
            m.close_user_sessions(upstream_id, user_id)
    except Exception as e:
        logger.debug(f'federation: closing sessions after a disconnect: {type(e).__name__}')


_tokens: Optional[ProxiedTokens] = None


def get_tokens() -> ProxiedTokens:
    global _tokens
    if _tokens is None:
        _tokens = ProxiedTokens()
    return _tokens


def set_tokens(tokens: Optional[ProxiedTokens]) -> None:
    global _tokens
    _tokens = tokens


def revoke_user(user_id: str, actor: str = '', reason: str = '') -> int:
    """Hook for user lifecycle events; never raises."""
    try:
        return get_tokens().revoke_user(user_id, actor=actor, reason=reason)
    except Exception as e:
        logger.warning(f'federation: revoking per-user tokens failed: {type(e).__name__}')
        return 0
