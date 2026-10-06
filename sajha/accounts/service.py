"""
SAJHA MCP Server — connected accounts: the OAuth flows, refresh and revocation.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:class:`ConnectedAccountsService` is the one object the routes, the injection layer and
federation use:

* :meth:`start` begins an authorization-code flow for the signed-in user: a random
  ``state``, a PKCE ``code_verifier`` (S256) where the provider supports it, the exact
  ``redirect_uri``, the requested scopes and a hash of a browser-binding nonce (set as a
  cookie by the route) go into the shared state store with a TTL, so the callback can
  land on any worker.
* :meth:`complete` handles the callback: the state is popped (single use), must belong
  to the same SAJHA user and the same browser, and the code is exchanged at the token
  endpoint with the same redirect URI and the verifier.  Tokens go into the vault.
* :meth:`resolve` gives a tool the caller's access token, refreshing it first when it
  expires within ``accounts.refresh_skew_seconds``.  One worker refreshes at a time (a
  lock in the state store), so a provider that rotates refresh tokens never sees two
  refreshes with the same one.  A refused refresh (``invalid_grant``) marks the link
  ``reauth_required``; a provider outage leaves it active and fails only this call.
* :meth:`disconnect` revokes at the provider where it offers revocation (best effort)
  and deletes the row.

Audit events (``audit_log``, resource_type ``connected_account``):
``connected_account_linked``, ``connected_account_link_failed``,
``connected_account_state_rejected``, ``connected_account_refreshed``,
``connected_account_refresh_failed``, ``connected_account_disconnected``,
``connected_account_vault_rotated``.  No token, code or verifier is ever written to the
audit log or the application log.

Design: docs/architecture/Connected Accounts.md
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from sajha.accounts import http as ahttp
from sajha.accounts.errors import (AccountsError, ConnectedAccountRequired, OAuthFlowError,
                                   ProviderNotConfigured)
from sajha.accounts.providers import Provider, get_registry
from sajha.accounts.settings import base_url, get_accounts_settings
from sajha.accounts.vault import Connection, get_vault, utcnow

logger = logging.getLogger(__name__)

FLOW_PREFIX = 'accounts:flow:'
LOCK_PREFIX = 'accounts:refresh:'
_REAUTH_ERRORS = {'invalid_grant', 'invalid_token', 'unauthorized_client', 'token_revoked', 'token_expired',
                  'invalid_refresh_token', 'invalid_auth', 'account_inactive', 'bad_refresh_token'}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode('ascii')).digest())


def _h(value: str) -> str:
    return hashlib.sha256(('sajha-accounts|' + (value or '')).encode()).hexdigest()


def _dig(data: Any, path: str) -> Any:
    cur = data
    for part in (path or '').split('.'):
        if not part:
            continue
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


@dataclass
class AccessToken:
    """The caller's token for one provider, as a tool receives it."""
    provider: Provider
    connection: Connection
    access_token: str = field(repr=False)
    token_type: str = 'Bearer'
    obtained_at: float = field(default_factory=time.time)

    @property
    def user_id(self) -> str:
        return self.connection.user_id

    @property
    def scopes(self) -> List[str]:
        return list(self.connection.scopes)

    def authorization(self) -> str:
        return f'Bearer {self.access_token}'


def is_user_caller(user_id: Optional[str]) -> bool:
    """Connected accounts belong to signed-in SAJHA users, not to API keys or anonymous callers."""
    return bool(user_id) and user_id != 'anonymous' and not user_id.startswith('apikey:')


class ConnectedAccountsService:
    def __init__(self, registry=None, vault=None, store=None):
        self._registry = registry
        self._vault = vault
        self._store = store

    # ── collaborators ──────────────────────────────────────────────
    @property
    def registry(self):
        return self._registry or get_registry()

    @property
    def vault(self):
        return self._vault or get_vault()

    @property
    def store(self):
        if self._store is not None:
            return self._store
        from sajha.core.state import get_state_store
        return get_state_store()

    def provider(self, pid: str, require_configured: bool = True) -> Provider:
        p = self.registry.get(pid)
        if p is None or (require_configured and not p.configured):
            raise ProviderNotConfigured(f'provider {pid!r} is not configured on this server')
        return p

    def connect_url(self, pid: str, scopes: Optional[List[str]] = None, request=None) -> str:
        q = {'connect': pid}
        if scopes:
            q['scope'] = ' '.join(scopes)
        return f'{base_url(request)}/account/connections?{urlencode(q)}'

    def redirect_uri(self, p: Provider, request=None) -> str:
        return p.redirect_uri or f'{base_url(request)}/account/connections/{p.id}/callback'

    # ── audit ──────────────────────────────────────────────────────
    @staticmethod
    def audit(action: str, user_id: str, provider: str, ip: Optional[str] = None, **details) -> None:
        try:
            from sajha.core.audit import get_audit_logger
            clean = {k: v for k, v in details.items() if v not in (None, '', [])}
            get_audit_logger().log(action, user_id=user_id, resource_type='connected_account',
                                   resource_id=provider, details=json.dumps(clean, default=str) if clean else None,
                                   ip_address=ip)
        except Exception as e:
            logger.debug(f'accounts: audit {action} failed: {type(e).__name__}')

    # ── the authorization-code flow ──────────────────────────────────
    def start(self, user_id: str, pid: str, *, browser_nonce: str, request=None,
              scopes: Optional[List[str]] = None, return_to: str = '') -> str:
        """The provider's authorize URL for a new flow (state, PKCE, exact redirect URI)."""
        if not is_user_caller(user_id):
            raise OAuthFlowError('sign in as a SAJHA user to link accounts')
        p = self.provider(pid)
        wanted = list(p.scopes)
        for s in scopes or []:
            if s not in wanted:
                wanted.append(s)
        # keep scopes the user already granted, so re-consent for one more never loses others
        existing = self.vault.get(user_id, pid)
        if existing is not None:
            for s in existing.scopes:
                if s not in wanted and p.normalize_scope(s) not in p.expand(wanted):
                    wanted.append(s)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)[:96] if p.pkce else ''
        redirect = self.redirect_uri(p, request)
        ttl = get_accounts_settings().flow_ttl_seconds
        self.store.set(FLOW_PREFIX + state, {'u': user_id, 'p': pid, 'v': verifier, 'r': redirect, 's': wanted,
                                             'b': _h(browser_nonce), 't': return_to or '',
                                             'x': int(time.time()) + ttl}, ttl=ttl)
        params = {'response_type': 'code', 'client_id': p.client_id, 'redirect_uri': redirect, 'state': state}
        if wanted:
            params[p.scope_param or 'scope'] = (p.scope_separator or ' ').join(wanted)
        if p.pkce:
            params['code_challenge'] = pkce_challenge(verifier)
            params['code_challenge_method'] = 'S256'
        for k, v in (p.authorize_params or {}).items():
            params.setdefault(k, str(v))
        sep = '&' if '?' in p.url('authorize_url') else '?'
        return p.url('authorize_url') + sep + urlencode(params)

    def complete(self, user_id: str, pid: str, *, state: str, code: str = '', error: str = '',
                 error_description: str = '', browser_nonce: str = '', ip: Optional[str] = None) -> Dict[str, Any]:
        """Finish a flow: verify the state, exchange the code, store the tokens. Returns {connection, return_to}."""
        rec = self.store.pop(FLOW_PREFIX + state) if state else None
        if not isinstance(rec, dict) or rec.get('x', 0) < time.time():
            self.audit('connected_account_state_rejected', user_id, pid, ip, why='unknown or expired state')
            raise OAuthFlowError('This sign-in link is unknown or has expired. Start again from Connected accounts.')
        if rec.get('u') != user_id or rec.get('p') != pid:
            self.audit('connected_account_state_rejected', user_id, pid, ip, why='state issued to another user')
            raise OAuthFlowError('This sign-in was started by a different SAJHA user or for another service.')
        if not browser_nonce or rec.get('b') != _h(browser_nonce):
            self.audit('connected_account_state_rejected', user_id, pid, ip, why='browser binding mismatch')
            raise OAuthFlowError('This sign-in was started in a different browser. Start again from Connected accounts.')
        p = self.provider(pid)
        if error:
            self.audit('connected_account_link_failed', user_id, pid, ip, error=error[:100])
            raise OAuthFlowError(f'{p.title} did not grant access: {error}'
                                 + (f' ({error_description[:200]})' if error_description else ''))
        if not code:
            raise OAuthFlowError('The provider returned no authorization code.')
        form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': rec['r']}
        if rec.get('v'):
            form['code_verifier'] = rec['v']
        try:
            data = self._token_request(p, form)
        except OAuthFlowError as e:
            self.audit('connected_account_link_failed', user_id, pid, ip, error=str(e)[:200])
            raise
        tokens, expires_at, granted = self._absorb(p, data, requested=rec.get('s') or [])
        login, account_id = self._identity(p, tokens['access_token'], data)
        conn = self.vault.save(user_id, pid, tokens, scopes=granted, expires_at=expires_at,
                               account_login=login, account_id=account_id)
        self.audit('connected_account_linked', user_id, pid, ip, account=login, scopes=granted,
                   refreshable=bool(tokens.get('refresh_token')))
        return {'connection': conn, 'return_to': rec.get('t') or ''}

    # ── token endpoint ──────────────────────────────────────────────
    def _token_request(self, p: Provider, form: Dict[str, str], *, refresh: bool = False) -> Dict[str, Any]:
        from sajha.federation.security import resolve_ref
        body = dict(form)
        body.update({k: str(v) for k, v in (p.token_params or {}).items()})
        headers = {'Accept': 'application/json'}
        auth = None
        secret = ''
        if p.client_secret_ref:
            try:
                secret = resolve_ref(p.client_secret_ref, f'provider {p.id} client_secret_ref')
            except Exception as e:
                raise OAuthFlowError(f'{p.title}: the client secret could not be resolved ({e})')
        if p.token_auth_method == 'client_secret_basic' and secret:
            auth = (p.client_id, secret)
        else:
            body['client_id'] = p.client_id
            if secret and p.token_auth_method != 'none':
                body['client_secret'] = secret
        try:
            with ahttp.client() as c:
                if p.token_request_format == 'json':
                    resp = c.post(p.url('token_url'), json=body, headers=headers, auth=auth)
                else:
                    resp = c.post(p.url('token_url'), data=body, headers=headers, auth=auth)
        except httpx.HTTPError as e:
            raise AccountsError(f'{p.title} token endpoint unreachable ({type(e).__name__})') from None
        data = ahttp.parse_token_response(resp)
        nested = _dig(data, p.token_response_path) if p.token_response_path else None
        err = data.get('error') or ((data.get('ok') is False) and 'error') or ''
        if resp.status_code >= 500:
            raise AccountsError(f'{p.title} token endpoint answered HTTP {resp.status_code}')
        if resp.status_code >= 400 or err:
            code = str(data.get('error') or f'http_{resp.status_code}')
            e = OAuthFlowError(f'{p.title} refused the token request: {code}')
            e.oauth_error = code
            raise e
        if isinstance(nested, dict) and nested.get('access_token'):
            merged = dict(nested)
            for k in ('team', 'enterprise', 'workspace_name', 'bot_id'):
                if k in data:
                    merged.setdefault(k, data[k])
            data = merged
        if not data.get('access_token'):
            raise OAuthFlowError(f'{p.title} returned no access token')
        ttype = str(data.get('token_type') or 'bearer').lower()
        if ttype not in ('bearer', 'user', 'bot'):
            raise OAuthFlowError(f'{p.title} returned a {ttype} token; only bearer tokens are supported')
        return data

    def _absorb(self, p: Provider, data: Dict[str, Any], requested: List[str],
                previous: Optional[Dict[str, Any]] = None):
        tokens = {'access_token': str(data['access_token']), 'token_type': 'Bearer'}
        rt = data.get('refresh_token') or (previous or {}).get('refresh_token')
        if rt:
            tokens['refresh_token'] = str(rt)
        expires_at = None
        try:
            if data.get('expires_in') not in (None, ''):
                expires_at = utcnow() + timedelta(seconds=max(0, int(float(data['expires_in']))))
        except (TypeError, ValueError):
            expires_at = None
        granted = p.split_scopes(data.get('scope')) if data.get('scope') not in (None, '') else list(requested)
        return tokens, expires_at, granted

    def _identity(self, p: Provider, access_token: str, data: Dict[str, Any]):
        login = str(_dig(data, p.login_field) or '') if p.login_field else ''
        account_id = str(_dig(data, p.id_field) or '') if p.id_field else ''
        if not p.userinfo_url:
            return login, account_id
        try:
            url = ahttp.check_api_url(p, p.url('userinfo_url'))
            headers = {**(p.api_headers or {}), 'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}
            with ahttp.client() as c:
                resp = c.get(url, headers=headers)
            info = resp.json() if resp.status_code == 200 else {}
            login = str(_dig(info, p.login_field) or login or '')
            account_id = str(_dig(info, p.id_field) or account_id or '')
        except Exception as e:
            logger.info(f'accounts: {p.id} user info unavailable ({type(e).__name__})')
        return login, account_id

    # ── tokens for tools ─────────────────────────────────────────────
    def required(self, pid: str, reason: str, user_id: str = '', scopes: Optional[List[str]] = None,
                 tool: str = '') -> ConnectedAccountRequired:
        p = self.registry.get(pid)
        return ConnectedAccountRequired(pid, provider_title=p.title if p else pid,
                                        connect_url=self.connect_url(pid, scopes if reason == 'insufficient_scope' else None),
                                        reason=reason, scopes=scopes, user_id=user_id, tool=tool)

    def resolve(self, user_id: str, pid: str, scopes: Optional[List[str]] = None, tool: str = '') -> AccessToken:
        """The user's access token for ``pid`` with ``scopes``; raises ConnectedAccountRequired."""
        if not get_accounts_settings().enabled:
            raise ProviderNotConfigured('connected accounts are turned off (accounts.enabled)')
        p = self.registry.get(pid)
        if p is None or not p.configured:
            raise ProviderNotConfigured(f'{(p.title if p else pid)} is not configured on this server; '
                                        f'an administrator sets accounts.providers.{pid}')
        if not is_user_caller(user_id):
            raise self.required(pid, 'sign_in_required', user_id, tool=tool)
        conn = self.vault.get(user_id, pid)
        if conn is None:
            raise self.required(pid, 'not_connected', user_id, scopes, tool)
        if conn.status != 'active':
            raise self.required(pid, 'reauth_required', user_id, scopes, tool)
        missing = p.missing_scopes(conn.scopes, list(scopes or []))
        if missing:
            raise self.required(pid, 'insufficient_scope', user_id, missing, tool)
        skew = get_accounts_settings().refresh_skew_seconds
        if conn.expires_within(skew):
            conn = self._refresh(p, conn, scopes=scopes, tool=tool)
        doc = self.vault.tokens(conn)
        self.vault.touch(conn)
        return AccessToken(p, conn, doc['access_token'])

    def refresh_after_rejection(self, token: AccessToken, tool: str = '') -> AccessToken:
        """The provider rejected the token (HTTP 401): refresh once, or mark the link for re-auth."""
        p, conn = token.provider, token.connection
        if not conn.has_refresh_token:
            self.vault.set_status(conn.user_id, p.id, 'reauth_required', 'the provider rejected the token')
            self.audit('connected_account_refresh_failed', conn.user_id, p.id, why='token rejected, no refresh token')
            raise self.required(p.id, 'reauth_required', conn.user_id, tool=tool)
        conn = self._refresh(p, conn, force=True, tool=tool)
        doc = self.vault.tokens(conn)
        return AccessToken(p, conn, doc['access_token'])

    def mark_rejected(self, token: AccessToken, why: str = 'the provider rejected the token') -> None:
        self.vault.set_status(token.user_id, token.provider.id, 'reauth_required', why)
        self.audit('connected_account_refresh_failed', token.user_id, token.provider.id, why=why)

    def _refresh(self, p: Provider, conn: Connection, force: bool = False, scopes=None, tool: str = '') -> Connection:
        store = self.store
        lock = f'{LOCK_PREFIX}{conn.user_id}:{p.id}'
        from sajha.core.state import WORKER_ID
        got = store.add(lock, WORKER_ID, ttl=30)
        if not got:
            deadline = time.time() + 15
            while time.time() < deadline and store.get(lock) is not None:
                time.sleep(0.1)
            fresh = self.vault.get(conn.user_id, p.id)
            if fresh is not None and fresh.status == 'active' and (
                    (fresh.last_refreshed_at or datetime.min) > (conn.last_refreshed_at or datetime.min)):
                return fresh
            got = store.add(lock, WORKER_ID, ttl=30)
            if not got:
                raise AccountsError(f'{p.title}: another worker is refreshing this token; retry')
        try:
            fresh = self.vault.get(conn.user_id, p.id)
            if fresh is None:
                raise self.required(p.id, 'not_connected', conn.user_id, scopes, tool)
            if fresh.status != 'active':
                raise self.required(p.id, 'reauth_required', conn.user_id, scopes, tool)
            newer = (fresh.last_refreshed_at or datetime.min) > (conn.last_refreshed_at or datetime.min)
            skew = get_accounts_settings().refresh_skew_seconds
            if newer and not fresh.expires_within(skew):
                return fresh                     # another worker refreshed it meanwhile
            if not force and not fresh.expires_within(skew):
                return fresh
            doc = self.vault.tokens(fresh)
            rt = doc.get('refresh_token')
            if not rt:
                if not fresh.expired and not force:
                    return fresh                 # nothing to refresh with; use it until it expires
                self.vault.set_status(fresh.user_id, p.id, 'reauth_required', 'expired and not refreshable')
                self.audit('connected_account_refresh_failed', fresh.user_id, p.id, why='expired, no refresh token')
                raise self.required(p.id, 'reauth_required', fresh.user_id, scopes, tool)
            try:
                data = self._token_request(p, {'grant_type': 'refresh_token', 'refresh_token': rt}, refresh=True)
            except OAuthFlowError as e:
                code = getattr(e, 'oauth_error', '') or ''
                if code in _REAUTH_ERRORS or code.startswith('http_4'):
                    self.vault.set_status(fresh.user_id, p.id, 'reauth_required', f'refresh refused: {code}')
                    self.audit('connected_account_refresh_failed', fresh.user_id, p.id, error=code)
                    raise self.required(p.id, 'reauth_required', fresh.user_id, scopes, tool)
                raise AccountsError(str(e)) from None
            except AccountsError:
                # provider outage: keep the link; use the old token while it is still valid
                if not fresh.expired and not force:
                    return fresh
                raise
            tokens, expires_at, granted = self._absorb(p, data, requested=fresh.scopes, previous=doc)
            conn2 = self.vault.update_tokens(fresh, tokens, expires_at=expires_at,
                                             scopes=granted if data.get('scope') else None)
            self.audit('connected_account_refreshed', fresh.user_id, p.id,
                       rotated=bool(data.get('refresh_token')))
            return conn2
        finally:
            store.delete(lock)

    # ── disconnect ──────────────────────────────────────────────────
    def disconnect(self, user_id: str, pid: str, *, actor: str = '', ip: Optional[str] = None,
                   revoke: bool = True) -> bool:
        """Revoke at the provider (best effort) and delete the link. True when there was one."""
        conn = self.vault.get(user_id, pid)
        if conn is None:
            return False
        revoked = None
        p = self.registry.get(pid)
        if revoke and p is not None and p.configured and p.revoke_style != 'none':
            try:
                revoked = self._revoke(p, self.vault.tokens(conn))
            except Exception as e:
                revoked = False
                logger.info(f'accounts: revocation at {pid} failed ({type(e).__name__}); deleting the link anyway')
        self.vault.delete(user_id, pid)
        self.audit('connected_account_disconnected', actor or user_id, pid, ip, user=user_id,
                   by_admin=bool(actor and actor != user_id), revoked_at_provider=revoked)
        return True

    def _revoke(self, p: Provider, doc: Dict[str, Any]) -> bool:
        from sajha.federation.security import resolve_ref
        token = doc.get('refresh_token') or doc.get('access_token')
        url = p.url('revoke_url')
        if not url or not token:
            return False
        with ahttp.client() as c:
            if p.revoke_style == 'github':
                secret = resolve_ref(p.client_secret_ref, f'provider {p.id} client_secret_ref') \
                    if p.client_secret_ref else ''
                r = c.request('DELETE', url, json={'access_token': doc.get('access_token')},
                              auth=(p.client_id, secret), headers={'Accept': 'application/vnd.github+json'})
                return r.status_code in (204, 404)
            if p.revoke_style == 'slack':
                r = c.post(url, headers={'Authorization': f'Bearer {doc.get("access_token")}'})
                return r.status_code == 200 and bool(ahttp.parse_token_response(r).get('ok'))
            if p.revoke_style == 'google':
                r = c.post(url, data={'token': token})
                return r.status_code == 200
            form = {'token': token, 'client_id': p.client_id}
            if doc.get('refresh_token'):
                form['token_type_hint'] = 'refresh_token'
            r = c.post(url, data=form)
            return r.status_code == 200

    # ── views ───────────────────────────────────────────────────────
    def connections_for(self, user_id: str) -> List[Dict[str, Any]]:
        out = []
        for conn in self.vault.list_for_user(user_id):
            out.append(conn.to_public())
        return out


_service: Optional[ConnectedAccountsService] = None


def get_service() -> ConnectedAccountsService:
    global _service
    if _service is None:
        _service = ConnectedAccountsService()
    return _service


def set_service(service: Optional[ConnectedAccountsService]) -> None:
    global _service
    _service = service
