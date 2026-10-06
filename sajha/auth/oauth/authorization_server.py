"""
SAJHA MCP Server — built-in OAuth 2.1 authorization server (state + token issuance).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Backed by SAJHA's own users.  Authorization code + PKCE (S256 only), refresh
tokens with rotation and reuse detection, short-lived RS256 JWT access tokens
(RFC 9068 ``typ: at+jwt``) whose ``aud`` is the MCP resource URI (RFC 8707).

Pending authorization requests, codes and refresh tokens (hashed) are kept in
the state store (sajha.core.state, ``state.backend``).  With the default
memory backend they live in this process: a restart signs every OAuth client
out (access tokens stay valid until they expire because the signing key is
persisted).  With redis or database they are shared by every worker, so a code
issued on one worker redeems on another, and they survive a restart.  Every
worker must also read the same signing key (shared data directory, or the same
``mcp.auth.builtin.signing_key_path`` file on every host).
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from sajha.auth.oauth import settings

_VERIFIER = re.compile(r'^[A-Za-z0-9\-._~]{43,128}$')
_CHALLENGE = re.compile(r'^[A-Za-z0-9_-]{43}$')
_MAX_PENDING = 5000
_PENDING_TTL = 600


class OAuthError(Exception):
    def __init__(self, error: str, description: str = '', status: int = 400):
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status

    def body(self) -> Dict[str, str]:
        out = {'error': self.error}
        if self.description:
            out['error_description'] = self.description
        return out


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()


def valid_code_challenge(challenge: Optional[str]) -> bool:
    return isinstance(challenge, str) and bool(_CHALLENGE.fullmatch(challenge))


def supported_scopes() -> List[str]:
    scopes = list(settings.resource_scopes())
    if settings.UMBRELLA_SCOPE not in scopes:
        scopes.append(settings.UMBRELLA_SCOPE)
    if settings.refresh_token_policy() == settings.OFFLINE_ACCESS:
        scopes.append(settings.OFFLINE_ACCESS)
    return scopes


def normalize_scope(requested: Optional[str]) -> List[str]:
    """Granted scopes for a request: unknown scopes are dropped; none left -> the resource defaults."""
    known = set(supported_scopes())
    asked = [s for s in (requested or '').split() if s in known]
    out: List[str] = []
    for s in asked:
        if s not in out:
            out.append(s)
    if not [s for s in out if s != settings.OFFLINE_ACCESS]:
        out = settings.resource_scopes() + [s for s in out if s == settings.OFFLINE_ACCESS]
    return out


@dataclass
class PendingAuthorization:
    client_id: str
    client_name: str
    client_host: str
    redirect_uri: str
    state: Optional[str]
    code_challenge: str
    scopes: List[str]
    resource: str
    issuer: str
    browser_hash: str
    created: float = field(default_factory=time.time)


@dataclass
class CodeRecord:
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: List[str]
    resource: str
    issuer: str
    user_id: str
    expires: float
    used: bool = False
    family: Optional[str] = None      # refresh-token family minted from this code


@dataclass
class RefreshRecord:
    family: str
    client_id: str
    user_id: str
    scopes: List[str]
    resource: str
    issuer: str
    expires: float
    used: bool = False


_PENDING = 'oauth:pending:'
_CODE = 'oauth:code:'
_REFRESH = 'oauth:refresh:'
_REVOKED = 'oauth:revoked:'
# a used code is remembered this long past its expiry, so a replay still revokes its grant
_CODE_GRACE = 600


class AuthorizationStore:
    """Consent requests, codes and refresh tokens in a :class:`~sajha.core.state.base.StateStore`."""

    def __init__(self, store=None):
        self._store = store

    @property
    def store(self):
        if self._store is None:
            from sajha.core.state import get_state_store
            return get_state_store()
        return self._store

    # ── pending authorization requests (consent screen) ──
    def add_pending(self, pending: PendingAuthorization) -> str:
        req_id = secrets.token_urlsafe(24)
        st = self.store
        count = st.count(_PENDING)          # cheap only in memory; shared stores rely on the TTL
        if count is not None and count >= _MAX_PENDING:
            raise OAuthError('temporarily_unavailable', 'too many pending authorization requests', 503)
        st.set(_PENDING + req_id, asdict(pending), ttl=max(1.0, _PENDING_TTL - (time.time() - pending.created)))
        return req_id

    def get_pending(self, req_id: str) -> Optional[PendingAuthorization]:
        rec = self.store.get(_PENDING + (req_id or ''))
        if rec is None:
            return None
        p = PendingAuthorization(**rec)
        if time.time() - p.created >= _PENDING_TTL:
            self.store.delete(_PENDING + req_id)
            return None
        return p

    def pop_pending(self, req_id: str) -> Optional[PendingAuthorization]:
        rec = self.store.pop(_PENDING + (req_id or ''))
        return PendingAuthorization(**rec) if rec else None

    # ── authorization codes (single use) ──
    def issue_code(self, pending: PendingAuthorization, user_id: str) -> str:
        code = secrets.token_urlsafe(32)
        ttl = settings.code_ttl()
        rec = CodeRecord(client_id=pending.client_id, redirect_uri=pending.redirect_uri,
                         code_challenge=pending.code_challenge, scopes=list(pending.scopes),
                         resource=pending.resource, issuer=pending.issuer, user_id=user_id,
                         expires=time.time() + ttl)
        self.store.set(_CODE + _h(code), asdict(rec), ttl=ttl + _CODE_GRACE)
        return code

    def redeem_code(self, code: str) -> CodeRecord:
        """
        Mark a code used and return it.  A second redemption revokes what the first one minted.
        The refresh-token family the code may mint is fixed here (``rec.family``), atomically,
        so a replay on any worker revokes exactly that family.
        """
        outcome: Dict[str, Any] = {}

        def mark_used(cur):
            outcome.clear()
            if cur is None:
                outcome['error'] = 'missing'
                return None
            if cur.get('used'):
                outcome['error'] = 'reused'
                outcome['family'] = cur.get('family')
                return cur
            cur = dict(cur, used=True, family=cur.get('family') or uuid.uuid4().hex)
            outcome['record'] = cur
            return cur

        self.store.update(_CODE + _h(code or ''), mark_used)
        if outcome.get('error') == 'missing':
            raise OAuthError('invalid_grant', 'invalid authorization code')
        if outcome.get('error') == 'reused':
            if outcome.get('family'):
                self._revoke_family(outcome['family'])
            raise OAuthError('invalid_grant', 'authorization code already used')
        rec = CodeRecord(**outcome['record'])
        if rec.expires < time.time():
            raise OAuthError('invalid_grant', 'authorization code expired')
        return rec

    # ── refresh tokens (rotation + reuse detection) ──
    def issue_refresh(self, family: str, client_id: str, user_id: str, scopes: List[str], resource: str,
                      issuer: str, expires: Optional[float] = None) -> str:
        token = secrets.token_urlsafe(48)
        rec = RefreshRecord(family=family, client_id=client_id, user_id=user_id, scopes=list(scopes),
                            resource=resource, issuer=issuer,
                            expires=expires or time.time() + settings.refresh_token_ttl())
        if self._revoked(family):
            raise OAuthError('invalid_grant', 'grant revoked')
        self.store.set(_REFRESH + _h(token), asdict(rec), ttl=max(1.0, rec.expires - time.time()))
        return token

    def use_refresh(self, token: str, client_id: str) -> RefreshRecord:
        outcome: Dict[str, Any] = {}

        def rotate(cur):
            outcome.clear()
            if cur is None:
                outcome['error'] = 'missing'
                return None
            if cur.get('client_id') != client_id:
                outcome['error'] = 'client'
                return cur
            if cur.get('used'):
                outcome['error'] = 'reused'
                outcome['family'] = cur.get('family')
                return cur
            cur = dict(cur, used=True)
            outcome['record'] = cur
            return cur

        key = _REFRESH + _h(token or '')
        current = self.store.get(key)
        if current is None or current.get('expires', 0) < time.time() or self._revoked(current.get('family')):
            raise OAuthError('invalid_grant', 'invalid refresh token')
        self.store.update(key, rotate)
        err = outcome.get('error')
        if err == 'missing':
            raise OAuthError('invalid_grant', 'invalid refresh token')
        if err == 'client':
            raise OAuthError('invalid_grant', 'refresh token was issued to another client')
        if err == 'reused':
            # A rotated-out token came back: assume theft, revoke the whole family.
            self._revoke_family(outcome['family'])
            raise OAuthError('invalid_grant', 'refresh token reuse detected; grant revoked')
        return RefreshRecord(**outcome['record'])

    def _revoked(self, family: Optional[str]) -> bool:
        return bool(family) and self.store.get(_REVOKED + family) is not None

    def _revoke_family(self, family: str) -> None:
        """Every refresh token of ``family`` stops working (checked on use; they expire on their own)."""
        self.store.set(_REVOKED + family, True, ttl=max(settings.refresh_token_ttl(), 3600))

    def revoke_refresh(self, token: str, client_id: str) -> None:
        rec = self.store.get(_REFRESH + _h(token or ''))
        if rec and rec.get('client_id') == client_id:
            self._revoke_family(rec['family'])


_store: Optional[AuthorizationStore] = None
_store_lock = threading.Lock()


def get_store() -> AuthorizationStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = AuthorizationStore()
        return _store


# ── browser binding / CSRF for the consent form ────────────────────

def _csrf_key() -> bytes:
    from sajha.core.config import get_settings
    return hashlib.sha256(b'sajha-oauth-consent|' + get_settings().secret_key.encode()).digest()


def consent_csrf(req_id: str, browser_token: str) -> str:
    return hmac.new(_csrf_key(), f'{req_id}|{browser_token}'.encode(), hashlib.sha256).hexdigest()


def browser_hash(browser_token: str) -> str:
    return _h('browser|' + (browser_token or ''))


# ── access tokens ──────────────────────────────────────────────────

def mint_access_token(issuer: str, user_id: str, client_id: str, scopes: List[str], resource: str) -> Dict:
    from jose import jwt
    from sajha.auth.oauth.keys import get_signing_key, ALGORITHM
    key = get_signing_key()
    now = int(time.time())
    ttl = settings.access_token_ttl()
    access_scopes = [s for s in scopes if s != settings.OFFLINE_ACCESS]
    claims = {
        'iss': issuer,
        'sub': user_id,
        'aud': resource,
        'iat': now,
        'nbf': now,
        'exp': now + ttl,
        'jti': uuid.uuid4().hex,
        'client_id': client_id,
        'scope': ' '.join(access_scopes),
    }
    token = jwt.encode(claims, key.private_pem.decode(), algorithm=ALGORITHM,
                       headers={'kid': key.kid, 'typ': 'at+jwt'})
    return {'access_token': token, 'token_type': 'Bearer', 'expires_in': ttl, 'scope': ' '.join(scopes)}


def wants_refresh(scopes: List[str]) -> bool:
    policy = settings.refresh_token_policy()
    if policy == 'always':
        return True
    if policy == 'never':
        return False
    return settings.OFFLINE_ACCESS in scopes


def verify_pkce(verifier: Optional[str], challenge: str) -> bool:
    if not isinstance(verifier, str) or not _VERIFIER.fullmatch(verifier):
        return False
    return hmac.compare_digest(pkce_s256(verifier), challenge)
