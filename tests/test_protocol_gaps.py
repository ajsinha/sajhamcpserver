# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Roadmap X12, the protocol gaps:

* ``notifications/tasks`` on 2026-07-28 ``subscriptions/listen`` streams (SEP-2663 ``taskIds``);
* ``list_changed`` on a 2025-11-25 streamable-HTTP session's GET /mcp stream;
* RFC 7662 introspection of an external issuer's opaque tokens (fail closed, cached);
* CORS on the OAuth endpoints for browser clients (``mcp.auth.cors.allowed_origins``).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

V = '2026-07-28'
TASKS_EXT = 'io.modelcontextprotocol/tasks'
SUB_ID = 'io.modelcontextprotocol/subscriptionId'
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}}


@pytest.fixture(scope='module')
def client():
    os.environ['SAJHA_MCP_CONFORMANCE_FIXTURES'] = 'true'
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)


def _meta(caps):
    return {'io.modelcontextprotocol/protocolVersion': V, 'io.modelcontextprotocol/clientCapabilities': caps,
            'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}


TASK_CAPS = {'extensions': {TASKS_EXT: {}}}


# ── 1. notifications/tasks on subscriptions/listen (2026-07-28) ─────────

def _listen(notifications, caps=TASK_CAPS, rid='tl-1'):
    from sajha.app import mcp_handler
    from sajha.routes.mcp_routes import _modern_server
    body = {'jsonrpc': '2.0', 'id': rid, 'method': 'subscriptions/listen',
            'params': {'_meta': _meta(caps), 'notifications': notifications}}
    hdrs = {'mcp-protocol-version': V, 'mcp-method': 'subscriptions/listen',
            'accept': 'application/json, text/event-stream'}
    return _modern_server(mcp_handler).handle(body, hdrs, list(hdrs.items()), None)


async def _frames(gen, n, timeout=1.0):
    out = []
    try:
        while len(out) < n:
            out.append(json.loads((await asyncio.wait_for(gen.__anext__(), timeout))['data']))
    except asyncio.TimeoutError:
        pass
    return out


class TestTaskNotifications:
    def test_snapshot_then_change_with_result_inlined(self, client):
        from sajha.core.mcp_modern import ModernStream
        from sajha.core.mcp_tasks import get_task_store

        async def run():
            release = asyncio.Event()

            async def runner(task):
                await release.wait()
                return {'content': [{'type': 'text', 'text': 'done'}], 'isError': False}

            task = get_task_store().create(None, runner)
            stream = await _listen({'taskIds': [task.task_id, 'no-such-task'], 'toolsListChanged': True})
            assert isinstance(stream, ModernStream)
            gen = stream.events()
            frames = await _frames(gen, 2)
            release.set()
            frames += await _frames(gen, 1)
            await gen.aclose()
            return task.task_id, frames

        tid, frames = asyncio.run(run())
        ack, snapshot, done = frames
        assert ack['method'] == 'notifications/subscriptions/acknowledged'
        assert ack['params']['notifications'] == {'toolsListChanged': True, 'taskIds': [tid]}
        assert snapshot['method'] == 'notifications/tasks'
        assert snapshot['params']['taskId'] == tid and snapshot['params']['status'] == 'working'
        assert done['params']['status'] == 'completed'
        assert done['params']['result']['content'][0]['text'] == 'done'
        assert all(f['params']['_meta'][SUB_ID] == 'tl-1' for f in frames)
        assert {'createdAt', 'lastUpdatedAt', 'ttlMs', 'pollIntervalMs'} <= set(done['params'])

    def test_cancel_and_other_tasks_not_sent(self, client):
        from sajha.core.mcp_tasks import get_task_store

        async def run():
            async def runner(task):
                await asyncio.sleep(30)
                return {'content': []}

            store = get_task_store()
            mine, other = store.create(None, runner), store.create(None, runner)
            stream = await _listen({'taskIds': [mine.task_id]})
            gen = stream.events()
            frames = await _frames(gen, 2)
            store.cancel(other.task_id, None)
            store.cancel(mine.task_id, None)
            frames += await _frames(gen, 2, timeout=0.5)
            await gen.aclose()
            return mine.task_id, frames

        tid, frames = asyncio.run(run())
        tasks = [f['params'] for f in frames if f['method'] == 'notifications/tasks']
        assert [t['taskId'] for t in tasks] == [tid, tid]
        assert [t['status'] for t in tasks] == ['working', 'cancelled']

    def test_other_users_tasks_are_not_honored(self, client):
        from sajha.core.mcp_tasks import get_task_store

        async def run():
            async def runner(task):
                return {'content': []}
            task = get_task_store().create('alice', runner)
            stream = await _listen({'taskIds': [task.task_id]})     # anonymous caller
            gen = stream.events()
            frames = await _frames(gen, 2, timeout=0.3)
            await gen.aclose()
            return frames

        frames = asyncio.run(run())
        assert frames[0]['params']['notifications'] == {'taskIds': []}
        assert len(frames) == 1

    def test_needs_tasks_extension_and_valid_ids(self, client):
        def post(notifications, caps):
            return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'subscriptions/listen',
                                             'params': {'_meta': _meta(caps), 'notifications': notifications}},
                               headers={'MCP-Protocol-Version': V, 'Mcp-Method': 'subscriptions/listen',
                                        'Accept': 'application/json, text/event-stream'})
        r = post({'taskIds': ['x']}, {})
        assert r.status_code == 400 and r.json()['error']['code'] == -32021
        assert r.json()['error']['data']['requiredCapabilities'] == {'extensions': {TASKS_EXT: {}}}
        r = post({'taskIds': 'x'}, TASK_CAPS)
        assert r.json()['error']['code'] == -32602

    def test_task_events_skip_sync_listeners(self):
        from sajha.core.change_bus import ChangeBus, TASK
        bus, seen = ChangeBus(), []
        bus.add_listener(seen.append)
        bus.task_changed('abc')
        bus.tools_changed()
        assert TASK not in {e.kind for e in seen} and seen


# ── 2. list_changed on a 2025-11-25 streamable-HTTP session ─────────────

def _session(client):
    r = client.post('/mcp', json=INIT)
    assert r.status_code == 200
    return r.json(), r.headers['mcp-session-id']


class TestLegacySessionStream:
    def test_initialize_advertises_list_changed(self, client):
        init, _ = _session(client)
        caps = init['result']['capabilities']
        assert caps['tools']['listChanged'] is True
        assert caps['prompts']['listChanged'] is True and caps['resources']['listChanged'] is True

    def test_get_without_session_405_unknown_404_not_sse_406(self, client):
        hv = {'MCP-Protocol-Version': '2025-11-25', 'Accept': 'text/event-stream'}
        assert client.get('/mcp', headers=hv).status_code == 405
        assert client.get('/mcp', headers={**hv, 'Mcp-Session-Id': 'nope'}).status_code == 404
        _, sid = _session(client)
        r = client.get('/mcp', headers={'Mcp-Session-Id': sid, 'Accept': 'application/json'})
        assert r.status_code == 406

    def test_stream_carries_list_changed_then_ends_with_session(self, client):
        # the route is driven directly: TestClient buffers a whole response, and this one is endless
        from starlette.requests import Request
        import sajha.routes.mcp_routes as routes
        from sajha.core.change_bus import get_change_bus
        from sajha.db.engine import get_db
        _, sid = _session(client)

        def request(method):
            scope = {'type': 'http', 'method': method, 'path': '/mcp', 'query_string': b'', 'scheme': 'http',
                     'server': ('testserver', 80), 'client': ('127.0.0.1', 5000),
                     'headers': [(b'mcp-session-id', sid.encode()), (b'accept', b'text/event-stream'),
                                 (b'mcp-protocol-version', b'2025-11-25'), (b'host', b'testserver')]}

            async def receive():
                await asyncio.sleep(3600)
            return Request(scope, receive)

        async def run():
            db = next(get_db())
            resp = await routes.mcp_sse(request('GET'), db)
            assert resp.status_code == 200
            gen = resp.body_iterator
            before = get_change_bus().subscriber_count
            first = asyncio.ensure_future(gen.__anext__())
            while get_change_bus().subscriber_count <= before:
                await asyncio.sleep(0.01)
            second = await routes.mcp_sse(request('GET'), db)          # one stream per session
            get_change_bus().tools_changed()
            event = await asyncio.wait_for(first, 2)
            deleted = await routes.mcp_delete(request('DELETE'), db)    # ends the stream
            rest = []
            with pytest.raises(StopAsyncIteration):
                while True:
                    rest.append(json.loads((await asyncio.wait_for(gen.__anext__(), 2))['data'])['method'])
            return second.status_code, event, deleted.status_code, rest

        conflict, event, deleted, rest = asyncio.run(run())
        assert conflict == 409 and deleted == 204
        assert json.loads(event['data'])['method'] == 'notifications/tools/list_changed'
        assert rest == ['notifications/resources/list_changed']
        assert sid not in routes._open_session_streams

    def test_other_users_session_is_404(self, client):
        from sajha.core.mcp_sessions import get_session_store
        s = get_session_store().create(protocol_version='2025-11-25', user_id='someone-else')
        r = client.get('/mcp', headers={'Mcp-Session-Id': s.session_id, 'Accept': 'text/event-stream'})
        assert r.status_code == 404
        get_session_store().delete(s.session_id)


# ── 3. RFC 7662 introspection ───────────────────────────────────────────

ISSUER = 'https://idp.example.com/realms/mcp'
INTROSPECT_URL = 'https://idp.example.com/realms/mcp/introspect'


@pytest.fixture
def idp(monkeypatch):
    """An external issuer with opaque tokens: httpx calls are answered by ``answers``."""
    import httpx
    from sajha.auth.oauth.introspection import get_introspector
    for k, v in {'SAJHA_MCP_AUTH_MODE': 'required', 'SAJHA_MCP_AUTH_AUTHORIZATION_SERVER': ISSUER,
                 'SAJHA_MCP_AUTH_PUBLIC_URL': 'http://testserver',
                 'SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_MODE': 'opaque',
                 'SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CLIENT_ID': 'sajha-rs',
                 'SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CLIENT_SECRET': 'rs-secret'}.items():
        monkeypatch.setenv(k, v)
    state = {'answers': {}, 'requests': [], 'status': 200, 'meta': True}

    def handler(request):
        if request.url.path.startswith('/.well-known/'):
            if not state['meta']:
                return httpx.Response(404)
            return httpx.Response(200, json={'issuer': ISSUER, 'introspection_endpoint': INTROSPECT_URL})
        state['requests'].append(request)
        if state['status'] != 200:
            return httpx.Response(state['status'])
        from urllib.parse import parse_qs
        token = parse_qs(request.content.decode())['token'][0]
        return httpx.Response(200, json=state['answers'].get(token, {'active': False}))

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw))
    get_introspector().clear()
    yield state
    get_introspector().clear()


def _active(**extra):
    claims = {'active': True, 'sub': 'ext-user-1', 'scope': 'mcp:read mcp:tools', 'iss': ISSUER,
              'aud': 'http://testserver/mcp', 'exp': int(time.time()) + 600, 'client_id': 'agent'}
    claims.update(extra)
    return claims


def _call(client, token):
    return client.post('/mcp', json=INIT, headers={'Authorization': f'Bearer {token}'})


class TestIntrospection:
    def test_active_token_accepted_and_cached(self, client, idp):
        import base64
        idp['answers']['opaque-1'] = _active()
        assert _call(client, 'opaque-1').status_code == 200
        assert _call(client, 'opaque-1').status_code == 200
        assert len(idp['requests']) == 1                           # cached
        req = idp['requests'][0]
        assert str(req.url) == INTROSPECT_URL                      # discovered from the metadata
        assert req.headers['authorization'] == 'Basic ' + base64.b64encode(b'sajha-rs:rs-secret').decode()
        assert b'token_type_hint=access_token' in req.content

    @pytest.mark.parametrize('answer', [
        {'active': False},
        _active(aud='https://someone-else.example.com'),
        _active(iss='https://evil.example.com'),
        _active(exp=int(time.time()) - 3600),
        _active(token_type='refresh_token'),
        {k: v for k, v in _active().items() if k != 'aud'},
        {k: v for k, v in _active().items() if k != 'sub'},
        {'active': 'true', 'sub': 'x', 'aud': 'http://testserver/mcp'},
    ])
    def test_refused_answers(self, client, idp, answer):
        idp['answers']['opaque-bad'] = answer
        r = _call(client, 'opaque-bad')
        assert r.status_code == 401 and 'invalid_token' in r.headers['www-authenticate']

    def test_audience_optional_when_configured(self, client, idp, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_REQUIRE_AUDIENCE', 'false')
        idp['answers']['opaque-noaud'] = {k: v for k, v in _active().items() if k != 'aud'}
        assert _call(client, 'opaque-noaud').status_code == 200

    def test_scope_enforced(self, client, idp):
        idp['answers']['opaque-read'] = _active(scope='mcp:read')
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                      'params': {'name': 'x', 'arguments': {}}},
                        headers={'Authorization': 'Bearer opaque-read'})
        assert r.status_code == 403 and 'insufficient_scope' in r.headers['www-authenticate']

    def test_fail_closed(self, client, idp, monkeypatch):
        idp['answers']['opaque-2'] = _active()
        idp['status'] = 500
        assert _call(client, 'opaque-2').status_code == 401
        idp['status'] = 200
        assert _call(client, 'opaque-2').status_code == 200        # the failure was not cached
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CLIENT_SECRET', '')
        assert _call(client, 'opaque-3').status_code == 401        # no credentials: refused
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CLIENT_SECRET', 'rs-secret')
        from sajha.auth.oauth.introspection import get_introspector
        get_introspector().clear()
        idp['meta'] = False                                        # no endpoint anywhere
        assert _call(client, 'opaque-3').status_code == 401

    def test_configured_endpoint_post_auth_and_no_cache(self, client, idp, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_ENDPOINT', 'https://idp.example.com/other')
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_AUTH_METHOD', 'client_secret_post')
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_CACHE_SECONDS', '0')
        idp['answers']['opaque-4'] = _active()
        assert _call(client, 'opaque-4').status_code == 200
        assert _call(client, 'opaque-4').status_code == 200
        assert len(idp['requests']) == 2
        req = idp['requests'][0]
        assert str(req.url) == 'https://idp.example.com/other' and 'authorization' not in req.headers
        assert b'client_secret=rs-secret' in req.content

    def test_mode_off_and_builtin_never_introspect(self, client, idp, monkeypatch):
        idp['answers']['opaque-5'] = _active()
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_MODE', 'off')
        assert _call(client, 'opaque-5').status_code == 401
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_MODE', 'always')
        monkeypatch.setenv('SAJHA_MCP_AUTH_AUTHORIZATION_SERVER', 'builtin')
        assert _call(client, 'opaque-5').status_code == 401
        assert idp['requests'] == []

    def test_always_mode_introspects_jwts(self, client, idp, monkeypatch):
        from sajha.auth.oauth.introspection import is_jwt, should_introspect
        jwt_like = 'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln'
        assert is_jwt(jwt_like) and not is_jwt('opaque-1')
        assert not should_introspect(jwt_like)
        monkeypatch.setenv('SAJHA_MCP_AUTH_EXTERNAL_INTROSPECTION_MODE', 'always')
        assert should_introspect(jwt_like)
        idp['answers'][jwt_like] = _active()
        assert _call(client, jwt_like).status_code == 200


# ── 4. CORS on the OAuth endpoints ──────────────────────────────────────

APP_ORIGIN = 'https://app.example.com'


class TestOAuthCors:
    @pytest.fixture(autouse=True)
    def _oauth_on(self, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_MODE', 'optional')

    def test_off_by_default(self, client):
        r = client.get('/.well-known/oauth-authorization-server', headers={'Origin': APP_ORIGIN})
        assert r.status_code == 200 and 'access-control-allow-origin' not in r.headers
        r = client.options('/oauth/token', headers={'Origin': APP_ORIGIN, 'Access-Control-Request-Method': 'POST'})
        assert r.headers.get('access-control-allow-origin') is None

    def test_allowed_origin(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_CORS_ALLOWED_ORIGINS', APP_ORIGIN)
        for path in ('/.well-known/oauth-authorization-server', '/.well-known/oauth-protected-resource/mcp',
                     '/oauth/jwks'):
            r = client.get(path, headers={'Origin': APP_ORIGIN})
            assert r.status_code == 200, path
            assert r.headers['access-control-allow-origin'] == APP_ORIGIN
            assert 'access-control-allow-credentials' not in r.headers
            assert 'Origin' in r.headers.get('vary', '')
        pre = client.options('/oauth/token', headers={'Origin': APP_ORIGIN, 'Access-Control-Request-Method': 'POST',
                                                      'Access-Control-Request-Headers': 'content-type'})
        assert pre.status_code == 204
        assert pre.headers['access-control-allow-origin'] == APP_ORIGIN
        assert 'POST' in pre.headers['access-control-allow-methods']
        assert 'Authorization' in pre.headers['access-control-allow-headers']
        r = client.post('/oauth/token', data={'grant_type': 'authorization_code'}, headers={'Origin': APP_ORIGIN})
        assert r.status_code in (400, 401) and r.headers['access-control-allow-origin'] == APP_ORIGIN

    def test_other_origins_and_authorize_get_none(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_CORS_ALLOWED_ORIGINS', APP_ORIGIN)
        r = client.get('/.well-known/oauth-authorization-server', headers={'Origin': 'https://evil.example.com'})
        assert 'access-control-allow-origin' not in r.headers
        r = client.get('/oauth/authorize', headers={'Origin': APP_ORIGIN})
        assert 'access-control-allow-origin' not in r.headers
        r = client.get('/.well-known/oauth-authorization-server', headers={'Origin': 'null'})
        assert 'access-control-allow-origin' not in r.headers

    def test_wildcard(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_AUTH_CORS_ALLOWED_ORIGINS', '*')
        r = client.get('/.well-known/oauth-authorization-server', headers={'Origin': 'https://any.example.org'})
        assert r.headers['access-control-allow-origin'] == '*'
        assert 'access-control-allow-credentials' not in r.headers

    def test_loopback_keeps_app_cors(self, client):
        # an origin the application-wide CORS middleware allows is untouched when not on this list
        r = client.get('/.well-known/oauth-authorization-server', headers={'Origin': 'http://localhost:3002'})
        assert r.headers.get('access-control-allow-origin') == 'http://localhost:3002'
