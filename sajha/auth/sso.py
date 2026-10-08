"""
Console single sign-on: OpenID Connect against an external identity provider (roadmap X5).

Opt-in (``auth.sso.enabled``, default off).  It signs people in *alongside* the existing
sign-ins: the users file, the database users and password login keep working unchanged.

Flow (authorization code with PKCE, RFC 7636; OpenID Connect Core 1.0):

    GET /auth/sso/login?next=/x     state, nonce and a PKCE verifier are kept in the state store
                                    (one use, 10 minutes) and bound to this browser by a cookie;
                                    redirect to the provider's authorization endpoint
    GET /auth/sso/callback          the code is exchanged at the token endpoint; the ID token's
                                    signature (the provider's JWKS), iss, aud, azp, exp, iat and
                                    nonce are checked; the claims are mapped to a SAJHA user and
                                    roles; a normal SAJHA session (the sajha_token cookie) starts

Several SAJHA instances (a SAJHA Net) get one sign-in by trusting the **same** identity
provider: each instance is a client of it, so a person signed in at the provider is signed in to
each instance's console without typing a password again (``auth.sso.auto_redirect`` makes that
silent).  Each instance still maps the person to *its own* user (SAJHA Net §11.3).
docs/security/Security Model.md "Console single sign-on"

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlsplit

logger = logging.getLogger(__name__)

STATE_TTL = 600
BINDING_COOKIE = 'sajha_sso'
_CACHE_SECONDS = 300
_ALGORITHMS = ('RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512')

#: Tests (and only tests) set an ``httpx`` transport here: a fake identity provider in process.
_TRANSPORT = None

_discovery_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_jwks_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


class SSOError(Exception):
    """A sign-in that must not complete; the message is safe to show to the person."""


# ── Settings (read live) ─────────────────────────────────────────

def _g(key: str, default: str = '') -> str:
    from sajha.core.config import _get
    v = _get(f'auth.sso.{key}', default)
    return default if v is None else str(v)


def _b(key: str, default: bool) -> bool:
    from sajha.core.config import _bool
    return _bool(f'auth.sso.{key}', default)


def _l(key: str, default: Optional[list] = None) -> List[str]:
    from sajha.core.config import _list
    return _list(f'auth.sso.{key}', default or [])


def issuer() -> str:
    return _g('issuer').strip().rstrip('/')


def client_id() -> str:
    return _g('client_id').strip()


def client_secret() -> str:
    return _g('client_secret').strip()


def enabled() -> bool:
    return _b('enabled', False) and bool(issuer()) and bool(client_id())


def label() -> str:
    return _g('label', 'Single sign-on') or 'Single sign-on'


def provider_name() -> str:
    """Stored in ``users.oauth_provider`` for linked accounts."""
    return (_g('provider_name', 'oidc') or 'oidc')[:50]


def auto_redirect() -> bool:
    return enabled() and _b('auto_redirect', False)


def role_map() -> Dict[str, List[str]]:
    """``auth.sso.role_map``: ``["<claim value>=<role>", ...]`` (a value may map to several roles)."""
    out: Dict[str, List[str]] = {}
    for entry in _l('role_map'):
        if '=' not in entry:
            continue
        k, v = entry.split('=', 1)
        if k.strip() and v.strip():
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def public_info() -> Dict[str, Any]:
    return {'enabled': enabled(), 'label': label(), 'login_url': '/auth/sso/login',
            'auto_redirect': auto_redirect()}


def _timeout() -> float:
    from sajha.core.config import _int
    return float(max(1, _int('auth.sso.timeout_seconds', 10)))


# ── HTTP to the provider ─────────────────────────────────────────

def _is_local(url: str) -> bool:
    host = (urlsplit(url).hostname or '').lower()
    return host in ('localhost', '127.0.0.1', '::1')


def _check_url(url: Any, what: str) -> str:
    if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
        raise SSOError(f'The identity provider did not publish a {what}.')
    if url.startswith('http://') and not _is_local(url):
        raise SSOError(f'The identity provider\'s {what} is not https.')
    return url


async def _get_json(url: str) -> Dict[str, Any]:
    import httpx
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=False, transport=_TRANSPORT) as c:
        r = await c.get(url, headers={'Accept': 'application/json'})
    if r.status_code != 200:
        raise SSOError(f'The identity provider answered HTTP {r.status_code}.')
    try:
        data = r.json()
    except ValueError:
        raise SSOError('The identity provider did not answer JSON.')
    if not isinstance(data, dict):
        raise SSOError('The identity provider answered something unexpected.')
    return data


async def discovery(refresh: bool = False) -> Dict[str, Any]:
    """The provider's OpenID configuration (cached for five minutes)."""
    iss = issuer()
    _check_url(iss, 'issuer')
    hit = _discovery_cache.get(iss)
    if hit and not refresh and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    doc = await _get_json(iss + '/.well-known/openid-configuration')
    if str(doc.get('issuer', '')).rstrip('/') != iss:
        raise SSOError('The identity provider\'s discovery document names another issuer.')
    for k, what in (('authorization_endpoint', 'authorization endpoint'), ('token_endpoint', 'token endpoint'),
                    ('jwks_uri', 'key set')):
        _check_url(doc.get(k), what)
    _discovery_cache[iss] = (time.time(), doc)
    return doc


async def _key_for(jwks_uri: str, kid: Optional[str]) -> Dict[str, Any]:
    for attempt in (0, 1):
        hit = _jwks_cache.get(jwks_uri)
        if attempt or not hit or time.time() - hit[0] >= _CACHE_SECONDS:
            data = await _get_json(jwks_uri)
            keys = [k for k in data.get('keys') or [] if isinstance(k, dict)]
            _jwks_cache[jwks_uri] = (time.time(), keys)
            hit = _jwks_cache[jwks_uri]
        keys = [k for k in hit[1] if k.get('use', 'sig') == 'sig']
        found = [k for k in keys if kid is None or k.get('kid') == kid]
        if len(found) == 1 or (found and kid is not None):
            return found[0]
    raise SSOError('The ID token is signed with a key the identity provider does not publish.')


# ── Start ────────────────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _state_store():
    from sajha.core.state import get_state_store
    return get_state_store()


def safe_next(url: Optional[str]) -> str:
    """Local paths only (no open redirect)."""
    url = url or '/dashboard'
    if not url.startswith('/') or url.startswith(('//', '/\\')) or '\\' in url:
        return '/dashboard'
    return url


def redirect_uri(request) -> str:
    configured = _g('redirect_uri').strip()
    if configured:
        return configured
    from sajha.auth.oauth.settings import public_base_url
    return public_base_url(request) + '/auth/sso/callback'


async def begin(request, next_url: Optional[str]) -> Tuple[str, str]:
    """(the provider's authorization URL, the browser-binding cookie value)."""
    doc = await discovery()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, binding = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    ruri = redirect_uri(request)
    _state_store().set(f'sso:state:{state}', {
        'nonce': nonce, 'verifier': verifier, 'next': safe_next(next_url), 'redirect_uri': ruri,
        'binding': hashlib.sha256(binding.encode()).hexdigest(), 'issuer': issuer(),
    }, ttl=STATE_TTL)
    scopes = _g('scopes', 'openid profile email') or 'openid'
    if 'openid' not in scopes.split():
        scopes = 'openid ' + scopes
    params = {
        'response_type': 'code', 'client_id': client_id(), 'redirect_uri': ruri, 'scope': scopes,
        'state': state, 'nonce': nonce, 'code_challenge_method': 'S256',
        'code_challenge': _b64url(hashlib.sha256(verifier.encode()).digest()),
    }
    endpoint = doc['authorization_endpoint']
    return endpoint + ('&' if '?' in endpoint else '?') + urlencode(params), binding


# ── Callback ─────────────────────────────────────────────────────

def take_state(state: str, binding_cookie: Optional[str]) -> Dict[str, Any]:
    """The pending sign-in for ``state`` (one use), bound to this browser."""
    if not state:
        raise SSOError('The sign-in response has no state.')
    rec = _state_store().pop(f'sso:state:{state}')
    if not isinstance(rec, dict):
        raise SSOError('This sign-in has expired or was already used. Start again.')
    if not binding_cookie or not hmac.compare_digest(
            hashlib.sha256(binding_cookie.encode()).hexdigest(), str(rec.get('binding', ''))):
        raise SSOError('This sign-in was started in another browser. Start again.')
    if rec.get('issuer') != issuer():
        raise SSOError('Single sign-on settings changed during the sign-in. Start again.')
    return rec


async def exchange_code(code: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    doc = await discovery()
    form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': rec['redirect_uri'],
            'code_verifier': rec['verifier'], 'client_id': client_id()}
    auth = None
    secret = client_secret()
    method = (_g('token_auth', '') or ('client_secret_basic' if secret else 'none')).strip()
    if method == 'client_secret_basic' and secret:
        auth = httpx.BasicAuth(client_id(), secret)
    elif method == 'client_secret_post' and secret:
        form['client_secret'] = secret
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=False, transport=_TRANSPORT) as c:
        r = await c.post(doc['token_endpoint'], data=form, auth=auth, headers={'Accept': 'application/json'})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or not isinstance(data, dict) or not data.get('id_token'):
        err = data.get('error') if isinstance(data, dict) else None
        raise SSOError('The identity provider refused the sign-in' + (f' ({err}).' if err else '.'))
    return data


async def validate_id_token(id_token: str, nonce: str, access_token: Optional[str] = None) -> Dict[str, Any]:
    from jose import jwt, JWTError
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError:
        raise SSOError('The ID token is malformed.')
    alg = header.get('alg')
    if alg not in _ALGORITHMS:
        raise SSOError('The ID token\'s signing algorithm is not accepted.')
    doc = await discovery()
    key = await _key_for(doc['jwks_uri'], header.get('kid'))
    from sajha.core.config import _int
    try:
        claims = jwt.decode(id_token, key, algorithms=[alg], audience=client_id(), issuer=doc['issuer'],
                            access_token=access_token,
                            options={'leeway': max(0, _int('auth.sso.clock_skew_seconds', 60)),
                                     'require_exp': True, 'require_iat': True, 'require_iss': True,
                                     'require_aud': True, 'require_sub': True})
    except JWTError as e:
        raise SSOError(f'The ID token is not valid ({e}).')
    aud = claims.get('aud')
    if isinstance(aud, list) and len(aud) > 1 and claims.get('azp') != client_id():
        raise SSOError('The ID token was issued to another client.')
    if not nonce or not hmac.compare_digest(str(claims.get('nonce', '')), nonce):
        raise SSOError('The ID token does not answer this sign-in (nonce).')
    if not isinstance(claims.get('sub'), str) or not claims['sub']:
        raise SSOError('The ID token has no subject.')
    return claims


# ── Claims to a SAJHA user ───────────────────────────────────────

def _claim_values(claims: Dict[str, Any], name: str) -> List[str]:
    v: Any = claims
    for part in name.split('.'):        # nested claims: realm_access.roles
        v = v.get(part) if isinstance(v, dict) else None
    if isinstance(v, str):
        return [x for x in v.replace(',', ' ').split() if x]
    if isinstance(v, list):
        return [str(x) for x in v if isinstance(x, (str, int))]
    return []


def mapped_roles(claims: Dict[str, Any]) -> List[str]:
    name = _g('roles_claim').strip()
    if not name:
        return []
    rmap, out = role_map(), []
    for value in _claim_values(claims, name):
        for role in rmap.get(value, []):
            if role not in out:
                out.append(role)
    return out


def user_id_from(claims: Dict[str, Any]) -> str:
    name = _g('user_claim', 'preferred_username').strip() or 'preferred_username'
    if name == 'email' and claims.get('email_verified') is False:
        raise SSOError('The identity provider has not verified this email address.')
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SSOError(f'The ID token has no {name} claim to name the SAJHA user.')
    return value.strip()[:100]


def _known_roles(db, names: List[str]) -> list:
    from sajha.db.dao import RoleDAO
    dao, out = RoleDAO(db), []
    for n in names:
        role = dao.get_by_name(n)
        if role is None:
            logger.warning(f'auth.sso: role {n!r} does not exist; not granted')
        else:
            out.append(role)
    return out


def resolve_user(db, claims: Dict[str, Any]):
    """The SAJHA user for these verified claims (linked, matched or created), or SSOError."""
    from sajha.db.dao import UserDAO, AuditDAO
    from sajha.db.models import User
    dao, provider, sub = UserDAO(db), provider_name(), claims['sub']
    roles = mapped_roles(claims)
    if _b('require_role', False) and not roles:
        raise SSOError('Your identity provider account has no role that this server accepts.')
    user = dao.get_by_oauth(provider, sub)
    created = False
    if user is None:
        uid = user_id_from(claims)
        user = dao.get_by_user_id(uid)
        if user is not None:
            if not _b('link_existing', True):
                raise SSOError('A SAJHA account with this name exists but is not linked to single sign-on.')
            if user.oauth_subject and (user.oauth_provider, user.oauth_subject) != (provider, sub):
                raise SSOError('This SAJHA account is linked to another identity.')
            user.oauth_provider, user.oauth_subject = provider, sub
            db.commit()
            AuditDAO(db).log('user.sso_linked', uid, 'user', uid, details={'issuer': issuer(), 'sub': sub})
        elif _b('auto_provision', False):
            from sajha.auth.password import hash_password
            user = User(user_id=uid, user_name=str(claims.get('name') or uid)[:255],
                        email=str(claims.get('email') or '')[:255],
                        password_hash=hash_password(secrets.token_urlsafe(32)), enabled=True)
            user.must_change_password = False
            user.oauth_provider, user.oauth_subject = provider, sub
            for role in _known_roles(db, roles or _l('default_roles', ['user'])):
                user.roles.append(role)
            dao.create(user)
            created = True
            AuditDAO(db).log('user.create', 'sso', 'user', uid,
                             details={'via': 'sso', 'issuer': issuer(), 'roles': user.role_names})
            try:
                from sajha.auth.apikeys import ensure_default_key
                ensure_default_key(db, user, by='sso')
            except Exception as e:  # noqa: BLE001
                logger.warning(f'default API key for {uid} not created: {e}')
        else:
            raise SSOError('There is no SAJHA account for you on this server. Ask an administrator.')
    if not user.enabled:
        raise SSOError('Your SAJHA account is disabled.')
    if not created and _b('sync_roles', False):
        from sajha.auth.users_file import get_users_file
        try:
            in_file = get_users_file().get(user.user_id) is not None
        except Exception:  # noqa: BLE001
            in_file = False
        if not in_file:   # the users file always wins
            new = _known_roles(db, roles or _l('default_roles', ['user']))
            if sorted(r.name for r in new) != sorted(user.role_names):
                user.roles = new
                db.commit()
                AuditDAO(db).log('user.sso_roles', 'sso', 'user', user.user_id,
                                 details={'roles': [r.name for r in new]})
    return user


def sign_in(db, user, claims: Dict[str, Any], id_token: str, ip: Optional[str] = None) -> str:
    """A SAJHA JWT for the user (the same session as a password sign-in)."""
    from sajha.auth.jwt_handler import create_access_token
    from sajha.auth.revocation import token_version_of
    from sajha.db.dao import UserDAO, AuditDAO
    token = create_access_token(user.user_id, user.role_names, extra_claims={'amr': ['sso']},
                                token_version=token_version_of(user))
    UserDAO(db).update_last_login(user.user_id)
    AuditDAO(db).log('user.login', user.user_id, 'user', user.user_id,
                     details={'method': 'sso', 'issuer': issuer(), 'sub': claims.get('sub')}, ip_address=ip)
    try:
        from sajha.auth.jwt_handler import decode_access_token
        from sajha.core.config import get_settings
        jti = (decode_access_token(token) or {}).get('jti')
        if jti and id_token:
            _state_store().set(f'sso:idt:{jti}', id_token,
                               ttl=max(60, int(get_settings().jwt_expiry_minutes or 60) * 60))
    except Exception as e:  # noqa: BLE001 - only the provider sign-out needs it
        logger.debug(f'id token not kept for sign-out: {e}')
    return token


# ── Sign-out ─────────────────────────────────────────────────────

async def logout_url(request, payload: Optional[Dict[str, Any]]) -> Optional[str]:
    """The provider's end-session URL for a session that SSO started (``auth.sso.idp_logout``)."""
    if not enabled() or not _b('idp_logout', True) or not isinstance(payload, dict):
        return None
    if 'sso' not in (payload.get('amr') or []):
        return None
    jti = payload.get('jti')
    id_token = _state_store().pop(f'sso:idt:{jti}') if jti else None
    try:
        doc = await discovery()
    except SSOError:
        return None
    end = doc.get('end_session_endpoint')
    try:
        _check_url(end, 'end-session endpoint')
    except SSOError:
        return None
    from sajha.auth.oauth.settings import public_base_url
    params = {'client_id': client_id(), 'post_logout_redirect_uri': public_base_url(request) + '/login'}
    if id_token:
        params['id_token_hint'] = id_token
    return end + ('&' if '?' in end else '?') + urlencode(params)
