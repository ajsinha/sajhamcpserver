"""
Browser and transport hardening (roadmap X6): security headers and the nonce CSP, the session
cookie, session rotation at sign-in, the cross-site (CSRF) check on every state-changing route,
the streamed body cap, allowed hosts, the WebSocket Origin check and outbound timeouts.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import ast
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

EVIL = 'https://evil.example'


@pytest.fixture(scope='module')
def app():
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    from sajha.app import create_app
    return create_app()


@pytest.fixture(scope='module')
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_throttle():
    from sajha.security import _login_throttle
    _login_throttle.reset()
    yield


def _browser(app):
    """A signed-in browser: the session cookie, no Authorization header."""
    c = TestClient(app)
    r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert r.status_code == 302, r.text
    assert c.cookies.get('sajha_token')
    return c


# ── headers and CSP ──────────────────────────────────────────────

def test_headers_on_a_console_page(client):
    r = client.get('/login')
    h = r.headers
    assert h['x-content-type-options'] == 'nosniff'
    assert h['x-frame-options'] == 'SAMEORIGIN'
    assert h['referrer-policy'] == 'strict-origin-when-cross-origin'
    assert 'camera=()' in h['permissions-policy']
    assert h['x-xss-protection'] == '0'
    csp = h['content-security-policy']
    assert "'unsafe-inline'" not in csp.split('style-src')[0], csp       # scripts: no unsafe-inline
    assert "script-src-attr 'none'" in csp and "object-src 'none'" in csp
    assert "frame-ancestors 'self'" in csp and "base-uri 'self'" in csp
    assert 'strict-transport-security' not in h                           # http: no HSTS


def test_every_inline_script_carries_this_responses_nonce(client):
    r = client.get('/login')
    nonce = re.search(r"'nonce-([^']+)'", r.headers['content-security-policy']).group(1)
    scripts = re.findall(r'<script\b([^>]*)>', r.text)
    inline = [a for a in scripts if 'src=' not in a and 'application/json' not in a]
    assert inline, 'the login page has inline scripts'
    assert all(f'nonce="{nonce}"' in a for a in inline), inline
    other = client.get('/login').headers['content-security-policy']
    assert nonce not in other                                             # fresh per response


def test_signed_in_pages_nonce_matches(app):
    c = _browser(app)
    for path in ('/dashboard', '/tools', '/admin/users', '/playground', '/help'):
        r = c.get(path)
        assert r.status_code == 200, path
        m = re.search(r"'nonce-([^']+)'", r.headers['content-security-policy'])
        assert m, path
        for attrs in re.findall(r'<script\b([^>]*)>', r.text):
            if 'src=' not in attrs and 'application/json' not in attrs:
                assert f'nonce="{m.group(1)}"' in attrs, (path, attrs)
        assert not re.search(r'\son(click|change|submit|load|error|input)="', r.text), path


def test_hsts_on_https(client):
    r = client.get('https://testserver/login')
    assert r.headers['strict-transport-security'].startswith('max-age=31536000')


def test_hsts_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv('SAJHA_SECURITY_HSTS_MAX_AGE', '0')
    assert 'strict-transport-security' not in client.get('https://testserver/login').headers


def test_oauth_consent_policy_is_stricter():
    from sajha.routes.oauth_routes import _page_headers
    from sajha.security import _CSP_NONCE
    _CSP_NONCE.set('n1')
    h = _page_headers()
    assert "frame-ancestors 'none'" in h['Content-Security-Policy'] and "'nonce-n1'" in h['Content-Security-Policy']
    assert h['X-Frame-Options'] == 'DENY'


# ── session cookie and rotation ──────────────────────────────────

def test_session_cookie_flags(app):
    c = TestClient(app)
    r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    cookie = r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/' in cookie
    assert 'secure' not in cookie                                         # http: auto -> not Secure
    r = c.post('https://testserver/login', data={'user_id': 'admin', 'password': 'admin123'},
               follow_redirects=False)
    assert '; secure' in r.headers['set-cookie'].lower()


def test_cookie_secure_forced(app, monkeypatch):
    monkeypatch.setenv('SAJHA_AUTH_COOKIE_SECURE', 'true')
    r = TestClient(app).post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert '; secure' in r.headers['set-cookie'].lower()


def test_sign_in_rotates_the_session(app):
    c = _browser(app)
    old = c.cookies.get('sajha_token')
    assert c.get('/dashboard').status_code == 200
    r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert r.status_code == 302
    new = c.cookies.get('sajha_token')
    assert new and new != old
    # the session held before the sign-in no longer works
    probe = TestClient(app)
    probe.cookies.set('sajha_token', old)
    assert probe.get('/dashboard', follow_redirects=False).status_code in (302, 303, 401)
    probe.cookies.set('sajha_token', new)
    assert probe.get('/dashboard', follow_redirects=False).status_code == 200


# ── CSRF: every state-changing route ─────────────────────────────

def _unsafe_routes(app):
    out = []

    def walk(routes, prefix=''):
        for r in routes:
            if hasattr(r, 'original_router'):
                ctx = getattr(r, 'include_context', None)
                walk(r.original_router.routes, prefix + (getattr(ctx, 'prefix', '') or ''))
            elif isinstance(r, APIRoute):
                for m in sorted(r.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}):
                    out.append((m, prefix + r.path))
    walk(app.routes)
    return out


def _concrete(path: str) -> str:
    return re.sub(r'\{[^}:]+(:path)?\}', 'x', path)


def test_every_state_changing_route_refuses_a_cross_site_cookie_request(app, client):
    """Enumerates every POST/PUT/PATCH/DELETE route: with the session cookie and another site's
    Origin (or Referer), each is refused before its handler runs. The MCP endpoints keep their own
    Origin allow-list (mcp.allowed_origins), checked here too."""
    from sajha.security import CSRF_EXEMPT_PREFIXES
    c = _browser(app)
    routes = _unsafe_routes(app)
    assert len(routes) > 100
    unprotected = []
    for method, path in routes:
        url = _concrete(path)
        r = c.request(method, url, headers={'Origin': EVIL}, content=b'{}')
        if path.startswith(CSRF_EXEMPT_PREFIXES):
            ok = r.status_code == 403
        else:
            ok = r.status_code == 403 and 'cross-site request refused' in r.text
        if not ok:
            unprotected.append(f'{method} {path} -> {r.status_code}')
    assert not unprotected, 'state-changing routes without cross-site protection:\n' + '\n'.join(unprotected)


def test_referer_counts_when_origin_is_missing(app):
    c = _browser(app)
    r = c.post('/api/auth/logout', headers={'Referer': EVIL + '/page'})
    assert r.status_code == 403
    r = c.post('/api/auth/logout', headers={'Origin': 'null'})
    assert r.status_code == 403


def test_same_origin_and_non_browser_requests_pass(app):
    c = _browser(app)
    r = c.post('/api/auth/logout', headers={'Origin': 'http://testserver'})
    assert r.status_code == 200
    # no cookie (API clients): never subject to the check
    r = TestClient(app).post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'},
                             headers={'Origin': EVIL})
    assert r.status_code == 200


def test_trusted_origin(app, monkeypatch):
    monkeypatch.setenv('SAJHA_SECURITY_CSRF_TRUSTED_ORIGINS', 'https://ui.example.com')
    c = _browser(app)
    assert c.post('/api/auth/logout', headers={'Origin': 'https://ui.example.com'}).status_code == 200


def test_cross_site_unit():
    from sajha.security import cross_site_refusal
    ck = {'cookie': 'sajha_token=abc', 'host': 'sajha.example.com'}
    assert cross_site_refusal('GET', '/x', {**ck, 'origin': EVIL}) is None
    assert cross_site_refusal('POST', '/x', {**ck, 'origin': 'https://sajha.example.com'}) is None
    assert cross_site_refusal('POST', '/x', {**ck, 'origin': EVIL})
    assert cross_site_refusal('POST', '/x', {'host': 'h', 'origin': EVIL}) is None      # no cookie
    assert cross_site_refusal('POST', '/x', ck) is None                                 # no Origin/Referer


# ── body size, hosts, WebSocket origin ───────────────────────────

def test_request_size_limit_content_length_and_chunked(client, monkeypatch):
    monkeypatch.setenv('SAJHA_SERVER_MAX_REQUEST_BYTES', '2048')
    from sajha.security import RequestSizeLimitMiddleware
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def echo(request):
        body = await request.body()
        return PlainTextResponse(str(len(body)))

    small = Starlette(routes=[Route('/e', echo, methods=['POST'])])
    small.add_middleware(RequestSizeLimitMiddleware)
    c = TestClient(small)
    assert c.post('/e', content=b'a' * 100).text == '100'
    assert c.post('/e', content=b'a' * 5000).status_code == 413

    def gen():
        for _ in range(10):
            yield b'b' * 1000
    assert c.post('/e', content=gen()).status_code == 413                 # chunked, no Content-Length
    # the real app: 10 MB default
    assert client.post('/api/auth/login', content=b'x' * (11 * 1024 * 1024),
                       headers={'Content-Type': 'application/json'}).status_code == 413


def test_allowed_hosts():
    from sajha.security import host_allowed
    assert host_allowed('anything', [])
    assert host_allowed('sajha.example.com:443', ['sajha.example.com'])
    assert host_allowed('a.example.com', ['*.example.com'])
    assert not host_allowed('example.com.evil', ['*.example.com'])
    assert not host_allowed('evil.test', ['sajha.example.com'])
    assert host_allowed('localhost:3002', ['sajha.example.com'])
    assert host_allowed('[::1]:3002', ['sajha.example.com'])


def test_allowed_hosts_middleware():
    from sajha.security import AllowedHostsMiddleware
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    s = Starlette(routes=[Route('/', lambda r: PlainTextResponse('ok'))])
    s.add_middleware(AllowedHostsMiddleware, hosts=['sajha.example.com'])
    assert TestClient(s, base_url='http://sajha.example.com').get('/').status_code == 200
    assert TestClient(s, base_url='http://evil.test').get('/').status_code == 400


def test_websocket_refuses_a_foreign_origin(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect('/mcp/ws', headers={'Origin': EVIL}) as ws:
            ws.receive_text()
    assert e.value.code == 1008
    # loopback origins pass (and then the usual authentication applies)
    with client.websocket_connect('/mcp/ws', headers={'Origin': 'http://localhost:3002'}) as ws:
        ws.send_json({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
        assert ws.receive_json().get('id') == 1


# ── outbound calls have timeouts ─────────────────────────────────

def test_outbound_http_calls_have_timeouts():
    """urlopen, requests.* and httpx clients outside sajha/net (its own suite) pass a timeout."""
    http = {'get', 'post', 'put', 'delete', 'patch', 'head', 'request', 'options'}
    missing = []
    for p in Path('sajha').rglob('*.py'):
        if 'sajha/net/' in p.as_posix():
            continue
        tree = ast.parse(p.read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f, name = n.func, None
            if isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else getattr(f.value, 'attr', None)
                if base in ('requests', 'httpx') and f.attr in http | {'Client', 'AsyncClient'}:
                    name = f'{base}.{f.attr}'
                elif f.attr == 'urlopen':
                    name = 'urlopen'
            elif isinstance(f, ast.Name) and f.id == 'urlopen':
                name = 'urlopen'
            if not name:
                continue
            kws = {k.arg for k in n.keywords}
            if 'timeout' in kws or None in kws or (name == 'urlopen' and len(n.args) >= 3):
                continue
            missing.append(f'{p}:{n.lineno} {name}')
    assert not missing, '\n'.join(missing)
