"""
OAuth 2.1 authorization for /mcp: resource server (RFC 9728, RFC 8707, RFC 6750
challenges), the built-in authorization server (RFC 8414, code + PKCE S256,
RFC 9207 iss, refresh rotation, CIMD, opt-in DCR) and the security checks
around them.  Modes are switched per test through SAJHA_ env overrides.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

BASE = 'http://testserver'
RESOURCE = BASE + '/mcp'
REDIRECT = 'http://127.0.0.1:3999/callback'
CLIENT_ID = 'pytest-client'
CONF_CLIENT = 'pytest-confidential'
CONF_SECRET = 's3cret-for-tests'
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    keydir = tmp_path_factory.mktemp('oauth')
    env = {
        'SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PATH': str(keydir / 'key.pem'),
        'SAJHA_MCP_AUTH_BUILTIN_CLIENTS': json.dumps([
            {'client_id': CLIENT_ID, 'client_name': 'Pytest', 'redirect_uris': [REDIRECT]},
            {'client_id': CONF_CLIENT, 'redirect_uris': [REDIRECT], 'client_secret': CONF_SECRET},
        ]),
    }
    os.environ.update(env)
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c
    for k in env:
        os.environ.pop(k, None)


@pytest.fixture
def mode(monkeypatch):
    def set_mode(value):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', value)
    set_mode('required')
    import sajha.security as sec
    sec._auth_limiter.reset()            # the consent-page login is rate limited per IP
    return set_mode


def _admin_cookie():
    from sajha.auth.jwt_handler import create_access_token
    return create_access_token('admin', ['admin'])


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def _authorize(c, client_id=CLIENT_ID, scope='mcp:read mcp:tools offline_access', challenge=None,
               extra=None, approve=True, login=True):
    """Drive the browser part: consent page -> approve -> redirect.  Returns the redirect query."""
    params = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': REDIRECT, 'state': 'st-1',
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'resource': RESOURCE, 'scope': scope}
    params.update(extra or {})
    params = {k: v for k, v in params.items() if v is not None}
    c.cookies.clear()
    if login:
        c.cookies.set('sajha_token', _admin_cookie())
    r = c.get('/oauth/authorize', params=params, follow_redirects=False)
    if r.status_code == 302:
        return parse_qs(urlsplit(r.headers['location']).query), r
    assert r.status_code == 200, r.text
    req_id = re.search(r'name="req_id" value="([^"]+)"', r.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    form = {'req_id': req_id, 'csrf': csrf, 'decision': 'approve' if approve else 'deny'}
    if not login:
        form.update({'user_id': 'admin', 'password': 'admin123'})
    r2 = c.post('/oauth/authorize', data=form, follow_redirects=False)
    assert r2.status_code == 302, r2.text
    loc = r2.headers['location']
    assert loc.startswith(REDIRECT + '?')
    return parse_qs(urlsplit(loc).query), r2


def _token(c, code, verifier, client_id=CLIENT_ID, **extra):
    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT,
            'code_verifier': verifier, 'client_id': client_id, 'resource': RESOURCE}
    data.update(extra)
    return c.post('/oauth/token', data={k: v for k, v in data.items() if v is not None})


def _full_flow(c, scope='mcp:read mcp:tools offline_access'):
    verifier, challenge = _pkce()
    q, _ = _authorize(c, challenge=challenge, scope=scope)
    r = _token(c, q['code'][0], verifier)
    assert r.status_code == 200, r.text
    return r.json()


def _mcp(c, token=None, body=None, headers=None):
    h = dict(headers or {})
    if token:
        h['Authorization'] = f'Bearer {token}'
    c.cookies.clear()
    return c.post('/mcp', json=body or INIT, headers=h)


# ── mode off (default) ──────────────────────────────────────────────

class TestModeOff:
    def test_no_discovery_documents(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        for path in ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp',
                     '/.well-known/oauth-authorization-server', '/oauth/jwks'):
            assert client.get(path).status_code == 404, path

    def test_anonymous_mcp_allowed(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        assert _mcp(client).status_code == 200


# ── credentials that were sent but are invalid: 401 in every mode, never anonymous ──

MODERN_LIST = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {'_meta': {
    'io.modelcontextprotocol/protocolVersion': '2026-07-28', 'io.modelcontextprotocol/clientCapabilities': {},
    'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}}}
MODERN_HEADERS = {'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/list',
                  'Accept': 'application/json, text/event-stream'}
BAD_CREDENTIALS = [{'X-API-Key': 'sja_' + '0' * 32}, {'Authorization': 'Bearer not-a-jwt'},
                   {'Authorization': 'sja_' + '1' * 32}]


class TestInvalidCredentialsRejected:
    @pytest.mark.parametrize('auth_mode', ['off', 'optional', 'required'])
    @pytest.mark.parametrize('headers', BAD_CREDENTIALS, ids=['x-api-key', 'bearer', 'auth-apikey'])
    @pytest.mark.parametrize('body', [INIT, MODERN_LIST], ids=['2025-11-25', '2026-07-28'])
    def test_mcp_post(self, client, monkeypatch, auth_mode, headers, body):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', auth_mode)
        extra = MODERN_HEADERS if body is MODERN_LIST else {}
        r = _mcp(client, body=body, headers={**extra, **headers})
        assert r.status_code == 401, r.text
        assert r.json()['error'] == 'invalid_token'
        assert 'error="invalid_token"' in r.headers['www-authenticate']

    @pytest.mark.parametrize('auth_mode', ['off', 'optional'])
    def test_no_credentials_stays_anonymous(self, client, monkeypatch, auth_mode):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', auth_mode)
        assert _mcp(client).status_code == 200
        assert _mcp(client, body=MODERN_LIST, headers=MODERN_HEADERS).status_code == 200

    def test_stale_session_cookie_alone_stays_anonymous(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        client.cookies.clear()
        client.cookies.set('sajha_token', 'expired-or-forged')
        try:
            assert client.post('/mcp', json=INIT).status_code == 200
        finally:
            client.cookies.clear()

    def test_sse_message_get_and_delete(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        client.cookies.clear()
        bad = {'X-API-Key': 'sja_' + '0' * 32}
        assert client.post('/mcp/message', json=INIT, headers=bad).status_code == 401
        assert client.get('/mcp', headers={**bad, 'Accept': 'text/event-stream'}).status_code == 401
        assert client.delete('/mcp', headers=bad).status_code == 401

    def test_a2a(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        client.cookies.clear()
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/get', 'params': {'id': 'nope'}}
        r = client.post('/a2a', json=body, headers={'X-API-Key': 'sja_' + '0' * 32})
        assert r.status_code == 401 and r.json()['error']['code'] == -32001
        assert client.post('/a2a', json=body).status_code != 401     # anonymous: not an auth error

    def test_websocket_closes_1008(self, client, monkeypatch):
        from starlette.websockets import WebSocketDisconnect
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'off')
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect('/mcp/ws?api_key=sja_' + '0' * 32) as ws:
                ws.receive_text()
        assert e.value.code == 1008


# ── resource server ────────────────────────────────────────────────

class TestResourceServer:
    def test_401_challenge(self, client, mode):
        r = _mcp(client)
        assert r.status_code == 401
        www = r.headers['www-authenticate']
        assert www.startswith('Bearer ')
        assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in www
        assert 'scope="mcp:read mcp:tools"' in www

    def test_optional_mode_allows_anonymous_but_rejects_bad_token(self, client, mode):
        mode('optional')
        assert _mcp(client).status_code == 200
        r = _mcp(client, token='not-a-jwt')
        assert r.status_code == 401 and 'error="invalid_token"' in r.headers['www-authenticate']

    def test_prm_document(self, client, mode):
        for path, resource in (('/.well-known/oauth-protected-resource', RESOURCE),
                               ('/.well-known/oauth-protected-resource/mcp', RESOURCE),
                               ('/.well-known/oauth-protected-resource/api/mcp', BASE + '/api/mcp')):
            doc = client.get(path).json()
            assert doc['resource'] == resource
            assert doc['authorization_servers'] == [BASE]
            assert doc['scopes_supported'] == ['mcp:read', 'mcp:tools']
            assert 'offline_access' not in doc['scopes_supported']

    def test_external_issuer_in_prm_and_no_builtin_as(self, client, mode, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_AUTHORIZATION_SERVER', 'https://idp.example.com/realms/mcp')
        assert client.get('/.well-known/oauth-protected-resource').json()['authorization_servers'] == \
            ['https://idp.example.com/realms/mcp']
        assert client.get('/.well-known/oauth-authorization-server').status_code == 404
        assert client.get('/oauth/authorize').status_code == 404

    def test_api_key_and_sajha_jwt_still_work(self, client, mode):
        from sajha.db.engine import get_db_session
        from sajha.db.models import ApiKey
        raw = 'sja_' + secrets.token_hex(16)
        db = get_db_session()
        key = ApiKey(key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:8],
                     name=f'pytest-{raw[-6:]}', enabled=True)
        db.add(key)
        db.commit()
        try:
            assert _mcp(client, headers={'X-API-Key': raw}).status_code == 200
            assert _mcp(client, token=_admin_cookie()).status_code == 200
        finally:
            db.delete(key)
            db.commit()
            db.close()

    def test_wrong_audience_rejected(self, client, mode):
        from sajha.auth.oauth.authorization_server import mint_access_token
        tok = mint_access_token(BASE, 'admin', CLIENT_ID, ['mcp:read', 'mcp:tools'], 'https://other.example/mcp')
        r = _mcp(client, token=tok['access_token'])
        assert r.status_code == 401 and 'audience' in r.json()['error_description']

    def test_wrong_issuer_rejected(self, client, mode):
        from sajha.auth.oauth.authorization_server import mint_access_token
        tok = mint_access_token('https://evil.example', 'admin', CLIENT_ID, ['mcp'], RESOURCE)
        assert _mcp(client, token=tok['access_token']).status_code == 401

    def test_expired_and_foreign_key_rejected(self, client, mode):
        from jose import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from sajha.auth.oauth.keys import get_signing_key
        now = int(time.time())
        claims = {'iss': BASE, 'sub': 'admin', 'aud': RESOURCE, 'scope': 'mcp', 'iat': now - 7200, 'exp': now - 3600}
        key = get_signing_key()
        expired = jwt.encode(claims, key.private_pem.decode(), algorithm='RS256',
                             headers={'kid': key.kid, 'typ': 'at+jwt'})
        assert _mcp(client, token=expired).status_code == 401
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        forged = jwt.encode(dict(claims, exp=now + 600), other.decode(), algorithm='RS256',
                            headers={'kid': key.kid, 'typ': 'at+jwt'})
        assert _mcp(client, token=forged).status_code == 401
        # HS256 with the public key as secret (algorithm confusion) is never accepted
        assert _mcp(client, token=jwt.encode(dict(claims, exp=now + 600), 'x', algorithm='HS256')).status_code == 401

    def test_insufficient_scope_403(self, client, mode):
        tokens = _full_flow(client, scope='mcp:read')
        at = tokens['access_token']
        assert _mcp(client, token=at).status_code == 200
        r = _mcp(client, token=at, body={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                         'params': {'name': 'calc_npv', 'arguments': {}}})
        assert r.status_code == 403
        www = r.headers['www-authenticate']
        assert 'error="insufficient_scope"' in www and 'scope="mcp:tools"' in www and 'resource_metadata=' in www


# ── built-in authorization server ───────────────────────────────────

class TestAuthorizationServer:
    def test_metadata(self, client, mode):
        r = client.get('/.well-known/oauth-authorization-server')
        assert r.status_code == 200
        doc = r.json()
        assert doc['issuer'] == BASE
        assert doc['code_challenge_methods_supported'] == ['S256']
        assert doc['response_types_supported'] == ['code']
        assert doc['client_id_metadata_document_supported'] is True
        assert doc['authorization_response_iss_parameter_supported'] is True
        assert 'offline_access' in doc['scopes_supported']
        assert 'registration_endpoint' not in doc
        assert client.get('/.well-known/openid-configuration').status_code == 404
        jwks = client.get(doc['jwks_uri'].replace(BASE, '')).json()
        assert jwks['keys'][0]['kty'] == 'RSA' and 'd' not in jwks['keys'][0]

    def test_code_flow_iss_and_token(self, client, mode):
        verifier, challenge = _pkce()
        q, resp = _authorize(client, challenge=challenge)
        assert q['state'] == ['st-1'] and q['iss'] == [BASE]
        r = _token(client, q['code'][0], verifier)
        assert r.status_code == 200
        assert r.headers['cache-control'] == 'no-store'
        body = r.json()
        assert body['token_type'] == 'Bearer' and body['refresh_token']
        from jose import jwt
        claims = jwt.get_unverified_claims(body['access_token'])
        assert claims['aud'] == RESOURCE and claims['iss'] == BASE and claims['sub'] == 'admin'
        assert jwt.get_unverified_header(body['access_token'])['typ'] == 'at+jwt'
        assert _mcp(client, token=body['access_token']).status_code == 200

    def test_login_on_consent_page(self, client, mode):
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge, login=False)
        assert _token(client, q['code'][0], verifier).status_code == 200

    def test_code_is_single_use_and_reuse_revokes(self, client, mode):
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge)
        first = _token(client, q['code'][0], verifier).json()
        again = _token(client, q['code'][0], verifier)
        assert again.status_code == 400 and again.json()['error'] == 'invalid_grant'
        # the refresh token minted from the replayed code is revoked
        r = client.post('/oauth/token', data={'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
                                              'refresh_token': first['refresh_token']})
        assert r.json()['error'] == 'invalid_grant'

    def test_pkce_required_s256_only_and_verified(self, client, mode):
        q, _ = _authorize(client, challenge=None)
        assert q['error'] == ['invalid_request'] and q['iss'] == [BASE] and q['state'] == ['st-1']
        _, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge, extra={'code_challenge_method': 'plain'})
        assert q['error'] == ['invalid_request']
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge)
        r = _token(client, q['code'][0], 'x' * 43)
        assert r.json()['error'] == 'invalid_grant'
        q, _ = _authorize(client, challenge=challenge)
        assert _token(client, q['code'][0], None).json()['error'] == 'invalid_grant'

    def test_no_open_redirect(self, client, mode):
        _, challenge = _pkce()
        c = client
        r = c.get('/oauth/authorize', params={'response_type': 'code', 'client_id': CLIENT_ID,
                                              'redirect_uri': 'https://evil.example/cb', 'code_challenge': challenge,
                                              'code_challenge_method': 'S256'}, follow_redirects=False)
        assert r.status_code == 400 and 'location' not in r.headers
        r = c.get('/oauth/authorize', params={'response_type': 'code', 'client_id': 'nobody',
                                              'redirect_uri': REDIRECT}, follow_redirects=False)
        assert r.status_code == 400 and 'location' not in r.headers
        assert r.headers['x-frame-options'] == 'DENY'

    def test_invalid_resource(self, client, mode):
        _, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge, extra={'resource': 'https://other.example/mcp'})
        assert q['error'] == ['invalid_target']

    def test_token_resource_must_match(self, client, mode):
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge)
        r = _token(client, q['code'][0], verifier, resource=BASE + '/api/mcp')
        assert r.json()['error'] == 'invalid_target'

    def test_deny(self, client, mode):
        _, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge, approve=False)
        assert q['error'] == ['access_denied'] and q['iss'] == [BASE]

    def test_consent_csrf(self, client, mode):
        _, challenge = _pkce()
        client.cookies.clear()
        client.cookies.set('sajha_token', _admin_cookie())
        r = client.get('/oauth/authorize', params={
            'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': REDIRECT,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})
        req_id = re.search(r'name="req_id" value="([^"]+)"', r.text).group(1)
        csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
        assert r.headers['x-frame-options'] == 'DENY'
        assert "frame-ancestors 'none'" in r.headers['content-security-policy']
        # wrong csrf token
        assert client.post('/oauth/authorize', data={'req_id': req_id, 'csrf': 'x', 'decision': 'approve'},
                           follow_redirects=False).status_code == 403
        # another browser (no transaction cookie) cannot submit the victim's request
        txn = client.cookies.get('sajha_oauth_txn')
        client.cookies.delete('sajha_oauth_txn', path='/oauth')
        assert client.post('/oauth/authorize', data={'req_id': req_id, 'csrf': csrf, 'decision': 'approve'},
                           follow_redirects=False).status_code == 403
        assert txn

    def test_refresh_rotation_and_reuse_detection(self, client, mode):
        tokens = _full_flow(client)
        rt1 = tokens['refresh_token']
        r = client.post('/oauth/token', data={'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
                                              'refresh_token': rt1, 'resource': RESOURCE})
        assert r.status_code == 200
        rt2 = r.json()['refresh_token']
        assert rt2 != rt1
        assert _mcp(client, token=r.json()['access_token']).status_code == 200
        # replaying rt1 revokes the family, including rt2
        assert client.post('/oauth/token', data={'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
                                                 'refresh_token': rt1}).json()['error'] == 'invalid_grant'
        assert client.post('/oauth/token', data={'grant_type': 'refresh_token', 'client_id': CLIENT_ID,
                                                 'refresh_token': rt2}).json()['error'] == 'invalid_grant'

    def test_no_refresh_without_offline_access(self, client, mode):
        tokens = _full_flow(client, scope='mcp:read mcp:tools')
        assert 'refresh_token' not in tokens

    def test_confidential_client_auth(self, client, mode):
        verifier, challenge = _pkce()
        q, _ = _authorize(client, client_id=CONF_CLIENT, challenge=challenge)
        data = {'grant_type': 'authorization_code', 'code': q['code'][0], 'redirect_uri': REDIRECT,
                'code_verifier': verifier}
        bad = client.post('/oauth/token', data=data,
                          headers={'Authorization': 'Basic ' + base64.b64encode(f'{CONF_CLIENT}:nope'.encode()).decode()})
        assert bad.status_code == 401 and bad.json()['error'] == 'invalid_client'
        q, _ = _authorize(client, client_id=CONF_CLIENT, challenge=challenge)
        data['code'] = q['code'][0]
        ok = client.post('/oauth/token', data=data,
                         headers={'Authorization': 'Basic ' + base64.b64encode(
                             f'{CONF_CLIENT}:{CONF_SECRET}'.encode()).decode()})
        assert ok.status_code == 200, ok.text

    def test_code_bound_to_client(self, client, mode):
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge)
        r = client.post('/oauth/token', data={'grant_type': 'authorization_code', 'code': q['code'][0],
                                              'redirect_uri': REDIRECT, 'code_verifier': verifier,
                                              'client_id': CONF_CLIENT, 'client_secret': CONF_SECRET})
        assert r.json()['error'] == 'invalid_grant'

    def test_dcr_off_by_default_then_on(self, client, mode, monkeypatch):
        meta = {'redirect_uris': [REDIRECT], 'token_endpoint_auth_method': 'none', 'client_name': 'dcr'}
        assert client.post('/oauth/register', json=meta).status_code == 404
        monkeypatch.setenv('SAJHA_MCP_AUTH_BUILTIN_DYNAMIC_CLIENT_REGISTRATION', 'true')
        assert 'registration_endpoint' in client.get('/.well-known/oauth-authorization-server').json()
        r = client.post('/oauth/register', json=meta)
        assert r.status_code == 201 and 'client_secret' not in r.json()
        bad = client.post('/oauth/register', json={'redirect_uris': ['javascript:alert(1)']})
        assert bad.status_code == 400
        verifier, challenge = _pkce()
        q, _ = _authorize(client, client_id=r.json()['client_id'], challenge=challenge)
        assert _token(client, q['code'][0], verifier, client_id=r.json()['client_id']).status_code == 200


# ── Client ID Metadata Documents (unit level: no network) ───────────

class TestCIMD:
    URL = 'https://app.example.com/oauth/client.json'

    def test_url_checks(self, monkeypatch):
        from sajha.auth.oauth.clients import check_cimd_url
        assert check_cimd_url(self.URL) is None
        assert check_cimd_url('http://app.example.com/c.json')
        assert check_cimd_url('https://app.example.com/')
        assert check_cimd_url('https://user:pw@app.example.com/c.json')
        assert check_cimd_url('https://app.example.com/a/../c.json')
        assert check_cimd_url('http://localhost:9000/c.json')
        monkeypatch.setenv('SAJHA_MCP_AUTH_BUILTIN_CIMD_ALLOW_LOCALHOST', 'true')
        assert check_cimd_url('http://localhost:9000/c.json') is None

    def test_ssrf_private_addresses_blocked(self):
        import asyncio
        from sajha.auth.oauth.clients import ClientError, fetch_cimd
        for url in ('https://127.0.0.1/c.json', 'https://10.0.0.5/c.json', 'https://169.254.169.254/latest',
                    'https://[::1]/c.json', 'https://[::ffff:127.0.0.1]/c.json'):
            with pytest.raises(ClientError):
                asyncio.run(fetch_cimd(url))

    def test_document_validation(self):
        from sajha.auth.oauth.clients import ClientError, client_from_cimd
        good = {'client_id': self.URL, 'client_name': 'App', 'redirect_uris': ['http://127.0.0.1:3000/cb'],
                'token_endpoint_auth_method': 'none'}
        c = client_from_cimd(self.URL, good)
        assert c.is_public and c.display_host() == 'app.example.com'
        for bad in ({**good, 'client_id': 'https://evil.example/c.json'},
                    {**good, 'redirect_uris': []},
                    {**good, 'redirect_uris': ['https://x.example/cb#frag']},
                    {**good, 'token_endpoint_auth_method': 'client_secret_basic'},
                    {**good, 'client_secret': 'x'}):
            with pytest.raises(ClientError):
                client_from_cimd(self.URL, bad)

    def test_cimd_client_flow(self, client, mode, monkeypatch):
        """A URL client_id is resolved via its metadata document (fetch stubbed) and used end to end."""
        from sajha.auth.oauth import clients as mod

        async def fake_fetch(url):
            return {'client_id': url, 'client_name': 'CIMD App', 'redirect_uris': [REDIRECT], '_max_age': 60}
        monkeypatch.setattr(mod, 'fetch_cimd', fake_fetch)
        verifier, challenge = _pkce()
        q, _ = _authorize(client, client_id=self.URL, challenge=challenge)
        assert _token(client, q['code'][0], verifier, client_id=self.URL).status_code == 200


class TestRedirectUriRules:
    def test_rules(self):
        from sajha.auth.oauth.clients import validate_redirect_uri as v
        assert v('https://app.example.com/cb') is None
        assert v('http://127.0.0.1:8080/cb') is None
        assert v('http://localhost/cb') is None
        assert v('com.example.app:/cb') is None
        assert v('http://app.example.com/cb')
        assert v('javascript:alert(1)')
        assert v('data:text/html,x')
        assert v('https://app.example.com/cb#x')
        assert v('myapp:/cb')


class TestHardening:
    def test_resource_case_insensitive_host(self, client, mode):
        from jose import jwt
        verifier, challenge = _pkce()
        q, _ = _authorize(client, challenge=challenge, extra={'resource': 'HTTP://TESTSERVER/mcp/'})
        body = _token(client, q['code'][0], verifier, resource='http://TestServer/mcp').json()
        assert jwt.get_unverified_claims(body['access_token'])['aud'] == RESOURCE
        q, _ = _authorize(client, challenge=challenge, extra={'resource': BASE + '/mcp?x=1'})
        assert q['error'] == ['invalid_target']

    def test_embedded_ipv4_ssrf(self):
        import ipaddress
        from sajha.auth.oauth.clients import _ip_allowed
        for addr in ('::ffff:10.0.0.1', '2002:7f00:1::', '64:ff9b::a9fe:a9fe', '127.0.0.1', '192.168.1.1'):
            assert not _ip_allowed(ipaddress.ip_address(addr), 'h.example'), addr
        assert _ip_allowed(ipaddress.ip_address('93.184.216.34'), 'h.example')

    def test_login_next_open_redirect(self, client):
        client.cookies.clear()
        for nxt in ('https://evil.example/', '//evil.example/', '/\\evil.example'):
            r = client.post('/login?next=' + nxt, data={'user_id': 'admin', 'password': 'admin123'},
                            follow_redirects=False)
            if r.status_code == 302:
                assert r.headers['location'] == '/dashboard'

    def test_data_resource_traversal(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'resources/read',
                                      'params': {'uri': 'sajha://data/../../config/application.yml'}})
        assert 'error' in r.json() and 'admin123' not in r.text
