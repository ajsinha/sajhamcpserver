"""
Console single sign-on (roadmap X5): OpenID Connect, authorization code + PKCE, against a fake
identity provider that runs in process (an httpx MockTransport; no network).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import base64
import hashlib
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

ISSUER = 'https://idp.test/realms/acme'


def _rsa_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub


class FakeIdP:
    """Discovery, JWKS, an authorization step (with its own browser session) and a token endpoint."""

    def __init__(self):
        from jose import jwk
        self.priv, pub = _rsa_pem()
        self.other_priv, _ = _rsa_pem()
        self.jwk = {**jwk.construct(pub, 'RS256').to_dict(), 'kid': 'k1', 'use': 'sig', 'alg': 'RS256'}
        self.codes = {}
        self.clients = {'sajha-a': 's3cret-a', 'sajha-b': 's3cret-b'}
        self.session_user = None        # the person signed in at the provider (its own cookie)
        self.password_prompts = 0
        self.tamper = {}                # claim overrides / 'key': 'other'
        self.token_requests = []

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ISSUER + '/.well-known/openid-configuration':
            return httpx.Response(200, json={
                'issuer': ISSUER, 'authorization_endpoint': ISSUER + '/auth',
                'token_endpoint': ISSUER + '/token', 'jwks_uri': ISSUER + '/certs',
                'end_session_endpoint': ISSUER + '/logout',
                'id_token_signing_alg_values_supported': ['RS256']})
        if url == ISSUER + '/certs':
            return httpx.Response(200, json={'keys': [self.jwk]})
        if url == ISSUER + '/token' and request.method == 'POST':
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            authz = request.headers.get('authorization', '')
            cid, _, secret = base64.b64decode(authz[6:]).decode().partition(':') if authz.startswith('Basic ') else ('', '', '')
            if self.clients.get(cid) != secret:
                return httpx.Response(401, json={'error': 'invalid_client'})
            rec = self.codes.pop(form.get('code'), None)
            if rec is None or rec['client_id'] != cid or rec['redirect_uri'] != form.get('redirect_uri'):
                return httpx.Response(400, json={'error': 'invalid_grant'})
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest()).rstrip(b'=').decode()
            if challenge != rec['challenge']:
                return httpx.Response(400, json={'error': 'invalid_grant'})
            return httpx.Response(200, json={'id_token': self.id_token(cid, rec['nonce'], rec['claims']),
                                             'access_token': 'at-' + secrets.token_hex(4), 'token_type': 'Bearer'})
        return httpx.Response(404)

    def id_token(self, client_id, nonce, claims):
        from jose import jwt
        now = int(time.time())
        body = {'iss': ISSUER, 'aud': client_id, 'iat': now, 'exp': now + 300, 'nonce': nonce, **claims}
        body.update({k: v for k, v in self.tamper.items() if k != 'key'})
        key = self.other_priv if self.tamper.get('key') == 'other' else self.priv
        return jwt.encode(body, key, algorithm='RS256', headers={'kid': 'k1'})

    def authorize(self, location: str, claims=None, password_ok=True):
        """The browser at the provider: signs in (once per provider session) and is sent back."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        assert location.startswith(ISSUER + '/auth?')
        assert q['response_type'] == 'code' and q['code_challenge_method'] == 'S256'
        assert 'openid' in q['scope'].split()
        if self.session_user is None:
            self.password_prompts += 1
            if not password_ok:
                return f"{q['redirect_uri']}?error=access_denied&state={q['state']}"
            self.session_user = claims
        code = secrets.token_urlsafe(16)
        self.codes[code] = {'client_id': q['client_id'], 'redirect_uri': q['redirect_uri'], 'nonce': q['nonce'],
                            'challenge': q['code_challenge'], 'claims': self.session_user}
        return f"{q['redirect_uri']}?code={code}&state={q['state']}"


@pytest.fixture(scope='module')
def app():
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    from sajha.app import create_app
    a = create_app()
    with TestClient(a):
        yield a


@pytest.fixture
def idp(monkeypatch):
    from sajha.auth import sso
    from sajha.security import _login_throttle
    _login_throttle.reset()
    fake = FakeIdP()
    monkeypatch.setattr(sso, '_TRANSPORT', fake.transport())
    sso._discovery_cache.clear()
    sso._jwks_cache.clear()
    for k, v in {'ENABLED': 'true', 'ISSUER': ISSUER, 'CLIENT_ID': 'sajha-a', 'CLIENT_SECRET': 's3cret-a',
                 'ROLES_CLAIM': 'groups', 'ROLE_MAP': 'sajha-admins=admin,staff=user', 'LABEL': 'Acme ID'}.items():
        monkeypatch.setenv(f'SAJHA_AUTH_SSO_{k}', v)
    yield fake
    sso._discovery_cache.clear()
    sso._jwks_cache.clear()


def _user(role='user', enabled=True, oauth=None):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO, RoleDAO
    from sajha.db.models import User
    uid = f'sso_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        u = User(user_id=uid, user_name=uid, email='', password_hash='Sso-Test-Pass-1', enabled=enabled)
        u.roles.append(RoleDAO(db).get_or_create(role))
        if oauth:
            u.oauth_provider, u.oauth_subject = oauth
        UserDAO(db).create(u)
    finally:
        db.close()
    return uid


def _get_user(uid):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO
    db = get_db_session()
    try:
        u = UserDAO(db).get_by_user_id(uid)
        return None if u is None else {'roles': sorted(u.role_names), 'provider': u.oauth_provider,
                                       'sub': u.oauth_subject, 'admin': u.is_admin}
    finally:
        db.close()


def _sso(app, idp, claims, next_url='/tools', browser=None):
    """The whole browser round trip; returns (browser, final SAJHA response)."""
    c = browser or TestClient(app)
    r = c.get('/auth/sso/login', params={'next': next_url}, follow_redirects=False)
    assert r.status_code == 302, r.text
    back = idp.authorize(r.headers['location'], claims)
    path = urlsplit(back)
    return c, c.get(f'{path.path}?{path.query}', follow_redirects=False)


# ── off by default ───────────────────────────────────────────────

def test_off_by_default(app):
    from sajha.auth import sso
    assert not sso.enabled()
    c = TestClient(app)
    assert c.get('/auth/sso/login', follow_redirects=False).status_code == 404
    assert c.get('/auth/sso/callback?code=x&state=y').status_code == 404
    assert c.get('/api/auth/sso').json()['enabled'] is False
    assert 'Sign in with' not in c.get('/login').text


# ── sign-in ──────────────────────────────────────────────────────

def test_links_an_existing_user_and_signs_in(app, idp):
    uid = _user('user')
    c, r = _sso(app, idp, {'sub': 'sub-' + uid, 'preferred_username': uid, 'groups': ['staff']})
    assert r.status_code == 302 and r.headers['location'] == '/tools'
    assert c.cookies.get('sajha_token')
    assert c.get('/dashboard', follow_redirects=False).status_code == 200
    u = _get_user(uid)
    assert u['provider'] == 'oidc' and u['sub'] == 'sub-' + uid
    # PKCE and the client secret went to the token endpoint, never the browser
    form = idp.token_requests[-1]
    assert form['code_verifier'] and form['grant_type'] == 'authorization_code' and 'client_secret' not in form
    # the next sign-in finds the account by its link, whatever the user name claim says
    idp.session_user = None
    c2, r2 = _sso(app, idp, {'sub': 'sub-' + uid, 'preferred_username': 'renamed', 'groups': []})
    assert r2.status_code == 302
    from sajha.auth.jwt_handler import decode_access_token
    assert decode_access_token(c2.cookies.get('sajha_token'))['sub'] == uid


def test_login_page_shows_the_button_and_password_login_still_works(app, idp):
    c = TestClient(app)
    page = c.get('/login').text
    assert 'Sign in with Acme ID' in page and 'name="password"' in page
    r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert r.status_code == 302 and c.cookies.get('sajha_token')
    assert TestClient(app).get('/api/auth/sso').json() == {
        'enabled': True, 'label': 'Acme ID', 'login_url': '/auth/sso/login', 'auto_redirect': False}


def test_unknown_user_is_refused_without_auto_provision(app, idp):
    c, r = _sso(app, idp, {'sub': 'nobody-1', 'preferred_username': 'sso_nobody_' + uuid.uuid4().hex[:6]})
    assert r.status_code == 403 and 'no SAJHA account' in r.text
    assert not c.cookies.get('sajha_token')


def test_auto_provision_maps_roles(app, idp, monkeypatch):
    monkeypatch.setenv('SAJHA_AUTH_SSO_AUTO_PROVISION', 'true')
    uid = 'sso_new_' + uuid.uuid4().hex[:6]
    c, r = _sso(app, idp, {'sub': 'n-' + uid, 'preferred_username': uid, 'name': 'New Person',
                           'email': f'{uid}@acme.test', 'groups': ['sajha-admins', 'other']})
    assert r.status_code == 302
    u = _get_user(uid)
    assert u['roles'] == ['admin'] and u['admin'] and u['sub'] == 'n-' + uid
    # no mapped group: the default roles
    uid2 = 'sso_new_' + uuid.uuid4().hex[:6]
    idp.session_user = None
    _sso(app, idp, {'sub': 'n-' + uid2, 'preferred_username': uid2, 'groups': ['other']})
    assert _get_user(uid2)['roles'] == ['user']


def test_require_role_and_sync_roles(app, idp, monkeypatch):
    uid = _user('user')
    monkeypatch.setenv('SAJHA_AUTH_SSO_REQUIRE_ROLE', 'true')
    _, r = _sso(app, idp, {'sub': 's-' + uid, 'preferred_username': uid, 'groups': ['nothing']})
    assert r.status_code == 403
    monkeypatch.setenv('SAJHA_AUTH_SSO_SYNC_ROLES', 'true')
    idp.session_user = None
    _, r = _sso(app, idp, {'sub': 's-' + uid, 'preferred_username': uid, 'groups': ['sajha-admins']})
    assert r.status_code == 302 and _get_user(uid)['roles'] == ['admin']


def test_disabled_user_and_linked_elsewhere_are_refused(app, idp):
    uid = _user('user', enabled=False)
    _, r = _sso(app, idp, {'sub': 'd-' + uid, 'preferred_username': uid})
    assert r.status_code == 403 and 'disabled' in r.text
    uid2 = _user('user', oauth=('oidc', 'someone-else'))
    idp.session_user = None
    _, r = _sso(app, idp, {'sub': 'mine', 'preferred_username': uid2})
    assert r.status_code == 403 and 'another identity' in r.text


@pytest.mark.parametrize('tamper,word', [
    ({'nonce': 'not-the-nonce'}, 'nonce'),
    ({'aud': 'another-client'}, 'not valid'),
    ({'iss': 'https://evil.test'}, 'not valid'),
    ({'exp': int(time.time()) - 3600}, 'not valid'),
    ({'key': 'other'}, 'not valid'),
])
def test_id_token_checks(app, idp, tamper, word):
    uid = _user('user')
    idp.tamper = tamper
    c, r = _sso(app, idp, {'sub': 't-' + uid, 'preferred_username': uid})
    assert r.status_code == 403 and word in r.text, r.text[:300]
    assert not c.cookies.get('sajha_token')


def test_state_is_single_use_and_bound_to_the_browser(app, idp):
    uid = _user('user')
    c = TestClient(app)
    r = c.get('/auth/sso/login', follow_redirects=False)
    back = urlsplit(idp.authorize(r.headers['location'], {'sub': 'b-' + uid, 'preferred_username': uid}))
    # another browser (no binding cookie) cannot complete it: login CSRF
    other = TestClient(app)
    assert other.get(f'{back.path}?{back.query}', follow_redirects=False).status_code == 403
    # and the state was used up by that attempt
    assert c.get(f'{back.path}?{back.query}', follow_redirects=False).status_code == 403


def test_provider_error_is_shown(app, idp):
    c = TestClient(app)
    r = c.get('/auth/sso/login', follow_redirects=False)
    back = urlsplit(idp.authorize(r.headers['location'], None, password_ok=False))
    r = c.get(f'{back.path}?{back.query}', follow_redirects=False)
    assert r.status_code == 403 and 'access_denied' in r.text


def test_next_is_local_only(app, idp):
    uid = _user('user')
    _, r = _sso(app, idp, {'sub': 'x-' + uid, 'preferred_username': uid}, next_url='https://evil.test/')
    assert r.headers['location'] == '/dashboard'


# ── sign-out ─────────────────────────────────────────────────────

def test_sign_out_ends_the_provider_session(app, idp):
    uid = _user('user')
    c, _ = _sso(app, idp, {'sub': 'o-' + uid, 'preferred_username': uid})
    token = c.cookies.get('sajha_token')
    r = c.get('/logout', follow_redirects=False)
    loc = r.headers['location']
    assert loc.startswith(ISSUER + '/logout?')
    q = parse_qs(urlsplit(loc).query)
    assert q['client_id'] == ['sajha-a'] and q['id_token_hint'][0].count('.') == 2
    assert q['post_logout_redirect_uri'][0].endswith('/login')
    probe = TestClient(app)
    probe.cookies.set('sajha_token', token)
    assert probe.get('/dashboard', follow_redirects=False).status_code != 200
    # a password session signs out locally only
    c2 = TestClient(app)
    c2.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert c2.get('/logout', follow_redirects=False).headers['location'] == '/'


# ── several instances, one sign-in ───────────────────────────────

def test_instances_trusting_one_provider_share_one_sign_in(app, idp, monkeypatch):
    """Instance A and instance B are both clients of the same provider: the person types a
    password once (at the provider), and B signs them in from the provider's session. With
    auto_redirect, B's /login goes straight there."""
    uid = _user('user')
    claims = {'sub': 'net-' + uid, 'preferred_username': uid}
    _, r = _sso(app, idp, claims)                                  # instance A
    assert r.status_code == 302 and idp.password_prompts == 1
    monkeypatch.setenv('SAJHA_AUTH_SSO_CLIENT_ID', 'sajha-b')       # instance B (its own client)
    monkeypatch.setenv('SAJHA_AUTH_SSO_CLIENT_SECRET', 's3cret-b')
    monkeypatch.setenv('SAJHA_AUTH_SSO_AUTO_REDIRECT', 'true')
    b = TestClient(app)
    r = b.get('/login', params={'next': '/tools'}, follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'].startswith('/auth/sso/login')
    _, r = _sso(app, idp, None, browser=b)
    assert r.status_code == 302 and b.cookies.get('sajha_token')
    assert idp.password_prompts == 1                                # no second password
    assert 'name="password"' in b.get('/login?local=1').text        # the form stays reachable


def test_role_map_and_claim_helpers(monkeypatch):
    from sajha.auth import sso
    monkeypatch.setenv('SAJHA_AUTH_SSO_ROLES_CLAIM', 'realm_access.roles')
    monkeypatch.setenv('SAJHA_AUTH_SSO_ROLE_MAP', '["ops=admin", "ops=developer", "dev=developer"]')
    assert sso.mapped_roles({'realm_access': {'roles': ['ops', 'x']}}) == ['admin', 'developer']
    monkeypatch.setenv('SAJHA_AUTH_SSO_USER_CLAIM', 'email')
    with pytest.raises(sso.SSOError):
        sso.user_id_from({'email': 'a@b', 'email_verified': False})
    assert sso.user_id_from({'email': 'a@b', 'email_verified': True}) == 'a@b'
