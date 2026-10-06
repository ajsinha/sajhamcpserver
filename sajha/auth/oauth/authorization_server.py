"""
SAJHA MCP Server — built-in OAuth 2.1 authorization server (state + token issuance).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Backed by SAJHA's own users.  Authorization code + PKCE (S256 only), refresh
tokens with rotation and reuse detection, short-lived RS256 JWT access tokens
(RFC 9068 ``typ: at+jwt``) whose ``aud`` is the MCP resource URI (RFC 8707).

Pending authorization requests, codes and refresh tokens are kept in process
memory (hashed): a restart signs every OAuth client out (access tokens stay
valid until they expire because the signing key is persisted).  Run one worker
or sticky sessions, as for the tasks extension.
"""

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

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


class AuthorizationStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[str, PendingAuthorization] = {}
        self._codes: Dict[str, CodeRecord] = {}
        self._refresh: Dict[str, RefreshRecord] = {}
        self._revoked_families: Set[str] = set()

    def _sweep(self, now: float) -> None:
        self._pending = {k: v for k, v in self._pending.items() if now - v.created < _PENDING_TTL}
        self._codes = {k: v for k, v in self._codes.items() if v.expires > now - 600}
        self._refresh = {k: v for k, v in self._refresh.items() if v.expires > now}

    # ── pending authorization requests (consent screen) ──
    def add_pending(self, pending: PendingAuthorization) -> str:
        req_id = secrets.token_urlsafe(24)
        with self._lock:
            self._sweep(time.time())
            if len(self._pending) >= _MAX_PENDING:
                raise OAuthError('temporarily_unavailable', 'too many pending authorization requests', 503)
            self._pending[req_id] = pending
        return req_id

    def get_pending(self, req_id: str) -> Optional[PendingAuthorization]:
        with self._lock:
            p = self._pending.get(req_id or '')
            if p and time.time() - p.created >= _PENDING_TTL:
                self._pending.pop(req_id, None)
                return None
            return p

    def pop_pending(self, req_id: str) -> Optional[PendingAuthorization]:
        with self._lock:
            return self._pending.pop(req_id or '', None)

    # ── authorization codes (single use) ──
    def issue_code(self, pending: PendingAuthorization, user_id: str) -> str:
        code = secrets.token_urlsafe(32)
        rec = CodeRecord(client_id=pending.client_id, redirect_uri=pending.redirect_uri,
                         code_challenge=pending.code_challenge, scopes=list(pending.scopes),
                         resource=pending.resource, issuer=pending.issuer, user_id=user_id,
                         expires=time.time() + settings.code_ttl())
        with self._lock:
            self._codes[_h(code)] = rec
        return code

    def redeem_code(self, code: str) -> CodeRecord:
        """Mark a code used and return it.  A second redemption revokes what the first one minted."""
        with self._lock:
            rec = self._codes.get(_h(code or ''))
            if rec is None:
                raise OAuthError('invalid_grant', 'invalid authorization code')
            if rec.used:
                if rec.family:
                    self._revoke_family_locked(rec.family)
                raise OAuthError('invalid_grant', 'authorization code already used')
            rec.used = True
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
        with self._lock:
            if family in self._revoked_families:
                raise OAuthError('invalid_grant', 'grant revoked')
            self._refresh[_h(token)] = rec
        return token

    def use_refresh(self, token: str, client_id: str) -> RefreshRecord:
        with self._lock:
            rec = self._refresh.get(_h(token or ''))
            if rec is None or rec.expires < time.time() or rec.family in self._revoked_families:
                raise OAuthError('invalid_grant', 'invalid refresh token')
            if rec.client_id != client_id:
                raise OAuthError('invalid_grant', 'refresh token was issued to another client')
            if rec.used:
                # A rotated-out token came back: assume theft, revoke the whole family.
                self._revoke_family_locked(rec.family)
                raise OAuthError('invalid_grant', 'refresh token reuse detected; grant revoked')
            rec.used = True
            return rec

    def _revoke_family_locked(self, family: str) -> None:
        self._revoked_families.add(family)
        for k in [k for k, v in self._refresh.items() if v.family == family]:
            self._refresh.pop(k, None)

    def revoke_refresh(self, token: str, client_id: str) -> None:
        with self._lock:
            rec = self._refresh.get(_h(token or ''))
            if rec and rec.client_id == client_id:
                self._revoke_family_locked(rec.family)


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
