# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Per-user sign-in for proxied servers, the remaining parts (Roadmap L20):

* ``auth.type: service_with_user``: one shared service identity, with the calling SAJHA user named in
  an audit header the vendor records. A fake vendor MCP server (the official SDK behind a gate) accepts
  only the service token, answers 403 for a user it will not act for, and records the user header of
  every request. Covered: configuration rules; discovery with the service identity alone; each call
  carries the service credential and the caller's name, per request on a 2026-07-28 upstream and in a
  session per user on a session-based one; anonymous callers refused; a refused service credential or
  user passed back; the audit names the mode and the user; the service token never in errors.
* The shipped policy rule ``approve-proxied-writes`` (config/policies/20-proxied-writes.yaml): a proxied
  server's tool without ``readOnlyHint: true`` needs approval; read-only ones and SAJHA's own tools do
  not; ``enabled: false`` switches it off. The rule-language parts it needs (``proxied`` and a condition
  on an annotation) are tested here too.

Design: docs/architecture/Per-User Sign-In for Proxied Servers.md
"""

import json
import shutil
import socket
import threading
import time
from pathlib import Path

import anyio
import pytest
from mcp.server.mcpserver import Context

from sajha.federation.config import ConfigError, FederationSettings, UpstreamConfig
from sajha.observability.caller import Caller, reset, set_caller

ROOT = Path(__file__).resolve().parents[1]
CANARY = 'CANARYsvc41'
SERVICE = f'svc_{CANARY}_0123456789abcdef'
REFUSED_USER = 'mallory'


class FakeVendor:
    """An MCP SDK server behind a gate: only ``Authorization: Bearer <SERVICE>`` gets in; ``X-SAJHA-User``
    (or the configured header) is recorded for every request and echoed by ``whoami``."""

    def __init__(self, header='x-sajha-user'):
        import uvicorn
        from mcp.server.mcpserver import MCPServer
        from mcp_types import ToolAnnotations
        self.header = header
        self.seen = []                  # (authorization, user header, session id, json-rpc method)
        server = MCPServer('vendor', title='Vendor', version='1.0.0')
        hname = header

        @server.tool(description='Who the vendor records as asking.',
                     annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def whoami(ctx: Context) -> str:
            return 'acting for ' + ((ctx.headers or {}).get(hname) or 'nobody')

        @server.tool(description='Create an issue (a write).')
        def create_issue(title: str) -> str:
            return f'created {title}'

        app = server.streamable_http_app(json_response=True)

        async def gate(scope, receive, send):
            if scope['type'] != 'http':
                return await app(scope, receive, send)
            hdrs = {k.decode().lower(): v.decode() for k, v in scope.get('headers') or []}
            body, more = b'', True
            while more:
                msg = await receive()
                body += msg.get('body', b'')
                more = msg.get('more_body', False)
            try:
                method = json.loads(body).get('method') if body[:1] == b'{' else None
            except ValueError:
                method = None
            user = hdrs.get(self.header, '')
            self.seen.append((hdrs.get('authorization', ''), user, hdrs.get('mcp-session-id', ''), method))
            status = 0
            if hdrs.get('authorization') != f'Bearer {SERVICE}':
                status = 401
            elif user == REFUSED_USER:
                status = 403
            if status:
                text = b'{"message": "not allowed"}'
                await send({'type': 'http.response.start', 'status': status,
                            'headers': [(b'content-type', b'application/json'),
                                        (b'content-length', str(len(text)).encode())]})
                await send({'type': 'http.response.body', 'body': text})
                return
            replayed = {'done': False}

            async def recv():
                if not replayed['done']:
                    replayed['done'] = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            await app(scope, recv, send)

        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        self.port = s.getsockname()[1]
        s.close()
        self.url = f'http://127.0.0.1:{self.port}/mcp'
        self._uv = uvicorn.Server(uvicorn.Config(gate, host='127.0.0.1', port=self.port, log_level='warning',
                                                 lifespan='on', timeout_graceful_shutdown=1))
        self._t = threading.Thread(target=self._uv.run, daemon=True)
        self._t.start()
        deadline = time.time() + 10
        while not self._uv.started and time.time() < deadline:
            time.sleep(0.02)
        assert self._uv.started

    def stop(self):
        self._uv.should_exit = True
        self._t.join(10)


class Reg:
    def __init__(self):
        self.tools = {}

    def register_tool(self, t):
        self.tools[t.name] = t

    def unregister_tool(self, n):
        self.tools.pop(n, None)

    def get_tool(self, n):
        return self.tools.get(n)


class as_user:
    def __init__(self, uid):
        self.uid = uid

    def __enter__(self):
        self.t = set_caller(Caller(self.uid))

    def __exit__(self, *a):
        reset(self.t)


@pytest.fixture(scope='module')
def vendor_server():
    v = FakeVendor()
    yield v
    v.stop()


@pytest.fixture
def vendor(vendor_server):
    vendor_server.seen.clear()            # tests run in random order (pytest-randomly) on one server
    return vendor_server


@pytest.fixture
def no_policy(monkeypatch):
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'false')


@pytest.fixture
def service_env(monkeypatch):
    monkeypatch.setenv('VENDOR_SERVICE_TOKEN', SERVICE)


def swu(url, protocol='2026-07-28', **auth):
    return {'id': 'vendor', 'url': url, 'protocol': protocol, 'title': 'Vendor',
            'auth': {'type': 'service_with_user', 'service': {'type': 'bearer', 'token_ref': 'env:VENDOR_SERVICE_TOKEN'},
                     **auth}}


def manager_for(tmp_path, upstreams):
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    st = FederationSettings(enabled=True, allow_localhost=True, require_approval=False, startup_wait_seconds=10,
                            default_timeout_seconds=10, upstreams=upstreams)
    reg = Reg()
    m = FederationManager(reg, st, FederationStore(str(tmp_path / 'fed.json')))
    m.start()
    return m, reg


def wait_for(cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ── configuration ───────────────────────────────────────────────────

def test_config_rules_of_service_with_user():
    url = 'https://mcp.example.com/mcp'
    from sajha.federation.user_tokens import auth_mode, on_behalf_header
    ok = UpstreamConfig.from_dict(swu(url, user_header='X-On-Behalf-Of', user_format='sajha:{user}'))
    assert auth_mode(ok) == 'service_with_user'
    assert on_behalf_header(ok, 'alice') == ('X-On-Behalf-Of', 'sajha:alice')
    plain = UpstreamConfig.from_dict({'id': 'v', 'url': url, 'auth': 'service_with_user',
                                      'headers': {'X-Api-Key': 'shared'}})
    assert on_behalf_header(plain, 'bob') == ('X-SAJHA-User', 'bob')
    assert on_behalf_header(plain, 'zoë\r\nX: y')[1] == 'zo%C3%AB%0D%0AX:%20y'     # never a header injection
    with pytest.raises(PermissionError):
        on_behalf_header(plain, 'anonymous')
    base = {'id': 'v', 'url': url}
    for bad, msg in [
            ({'auth': {'type': 'service_with_user'}, 'transport': 'stdio', 'command': '/bin/true'}, 'HTTP transport'),
            ({'auth': {'type': 'service_with_user'}, 'cache_ttl': 30}, 'per user'),
            ({'auth': {'type': 'service_with_user', 'service': {'type': 'bearer'}}}, 'token_ref'),
            ({'auth': {'type': 'service_with_user', 'service': {'type': 'bearer', 'token': 'inline'}}}, 'reference'),
            ({'auth': {'type': 'service_with_user', 'service': {'type': 'token_user'}}}, 'service.type'),
            ({'auth': {'type': 'service_with_user', 'user_header': 'Authorization'}}, 'user_header'),
            ({'auth': {'type': 'service_with_user', 'user_header': 'Bad Header'}}, 'user_header'),
            ({'auth': {'type': 'service_with_user'}, 'headers': {'x-sajha-user': 'fixed'}}, 'conflicts'),
            ({'auth': {'type': 'service_with_user', 'user_format': 'nobody'}}, r'\{user\}'),
            ({'auth': {'type': 'service_with_user', 'user_format': '{user}-{email}'}}, r'\{user\}'),
            ({'auth': {'type': 'service_with_user', 'colour': 'red'}}, 'unknown')]:
        with pytest.raises(ConfigError, match=msg):
            UpstreamConfig.from_dict({**base, **bad})


def test_on_behalf_auth_adds_the_header_over_the_service_credential():
    import httpx2
    from sajha.federation.auth import OnBehalfAuth, StaticHeaderAuth
    seen = []

    def handler(request):
        seen.append((request.headers.get('authorization'), request.headers.get('x-sajha-user')))
        return httpx2.Response(200, json={})
    auth = OnBehalfAuth(StaticHeaderAuth('Authorization', 'Bearer s'), 'X-SAJHA-User', 'alice')
    with httpx2.Client(transport=httpx2.MockTransport(handler), auth=auth) as c:
        c.get('https://v.example/')

    async def go():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler), auth=auth) as c:
            await c.get('https://v.example/')
    anyio.run(go)
    assert seen == [('Bearer s', 'alice'), ('Bearer s', 'alice')]
    assert auth.secret_values() == ['Bearer s']
    assert OnBehalfAuth(None, 'X-SAJHA-User', 'bob').secret_values() == []


# ── calls ────────────────────────────────────────────────────────────

def test_each_call_carries_the_service_identity_and_the_callers_name(tmp_path, vendor, service_env, no_policy):
    m, reg = manager_for(tmp_path, [swu(vendor.url)])
    try:
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        assert m.status('vendor')['auth_mode'] == 'service_with_user'
        listing = [s for s in vendor.seen if s[3] == 'tools/list']
        assert listing
        for a, u, _s, _m in listing:                            # the service identity alone
            assert a == f'Bearer {SERVICE}', 'AUTH ' + a
            assert u == '', 'USER ' + u
        tool = reg.tools['vendor__whoami']
        for user in ('alice', 'bob'):
            vendor.seen.clear()
            with as_user(user):
                out = tool.execute_with_tracking({})
            assert f'acting for {user}' in json.dumps(out)
            calls = [(a, u) for a, u, _s, m in vendor.seen if m == 'tools/call']
            assert calls and set(calls) == {(f'Bearer {SERVICE}', user)}
            assert {u for _a, u, _s, _m in vendor.seen} <= {user, ''}   # the shared connection names nobody
        assert m.user_sessions('vendor') == []                  # 2026-07-28: nothing kept per user
    finally:
        m.stop()


def test_session_based_upstream_keeps_a_session_per_user(tmp_path, vendor, service_env, no_policy):
    m, reg = manager_for(tmp_path, [swu(vendor.url, protocol='legacy', user_format='sajha:{user}')])
    try:
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tool = reg.tools['vendor__whoami']
        for user in ('alice', 'bob', 'alice'):
            with as_user(user):
                assert f'acting for sajha:{user}' in json.dumps(tool.execute_with_tracking({}))
        assert sorted(m.user_sessions('vendor')) == ['alice', 'bob']
        sessions = {}
        for _a, u, sid, method in vendor.seen:
            if u and sid and method == 'tools/call':
                sessions.setdefault(u, set()).add(sid)
        assert set(sessions) == {'sajha:alice', 'sajha:bob'}
        assert sessions['sajha:alice'].isdisjoint(sessions['sajha:bob'])
    finally:
        m.stop()


def test_anonymous_and_refusals(tmp_path, vendor, service_env, no_policy, monkeypatch):
    from sajha.federation.tool import FederatedToolError
    m, reg = manager_for(tmp_path, [swu(vendor.url)])
    try:
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tool = reg.tools['vendor__whoami']
        vendor.seen.clear()
        with as_user('anonymous'), pytest.raises(Exception, match='named SAJHA user'):
            tool.execute_with_tracking({})
        assert not [s for s in vendor.seen if s[3] == 'tools/call']        # nothing sent
        with as_user(REFUSED_USER), pytest.raises(FederatedToolError) as ei:
            m.call_tool(tool, {})
        assert 'HTTP 403' in str(ei.value) and ei.value.caller_specific
        # the service credential itself refused (rotated at the vendor): an administrator's problem
        monkeypatch.setenv('VENDOR_SERVICE_TOKEN', 'svc_wrong_' + CANARY)
        m._upstreams['vendor'].service_auth_built = False
        with as_user('alice'), pytest.raises(FederatedToolError) as ei:
            m.call_tool(tool, {})
        assert 'HTTP 401' in str(ei.value) and 'auth.service' in str(ei.value)
        assert not ei.value.caller_specific and SERVICE not in str(ei.value)
    finally:
        m.stop()


def test_audit_names_the_mode_and_the_user(tmp_path, vendor, service_env, no_policy, monkeypatch):
    from sajha.audit import tool_calls
    from sajha.federation import manager as fm
    m, reg = manager_for(tmp_path, [swu(vendor.url)])
    try:
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        monkeypatch.setattr(fm, 'get_federation', lambda: m)
        ident = tool_calls._proxied_identity(reg.tools['vendor__whoami'], Caller('alice'))
        assert ident == {'upstream': 'vendor', 'mode': 'service_with_user', 'user': 'alice'}
    finally:
        m.stop()


# ── the shipped approval rule for proxied writes ────────────────────

@pytest.fixture
def shipped_policies():
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    eng = PolicyEngine(PolicySet(str(ROOT / 'config' / 'policies')))
    set_engine(eng)
    yield eng
    set_engine(None)


def test_proxied_write_needs_approval_and_read_only_does_not(tmp_path, vendor, service_env, shipped_policies):
    from sajha.policy.errors import ApprovalRequired
    m, reg = manager_for(tmp_path, [swu(vendor.url)])
    try:
        assert wait_for(lambda: 'vendor__create_issue' in reg.tools)
        with as_user('alice'):
            assert 'acting for alice' in json.dumps(reg.tools['vendor__whoami'].execute_with_tracking({}))
            vendor.seen.clear()
            with pytest.raises(ApprovalRequired, match='readOnlyHint') as ei:
                reg.tools['vendor__create_issue'].execute_with_tracking({'title': 'x'})
            assert ei.value.rule.endswith('approve-proxied-writes')
            assert not [s for s in vendor.seen if s[3] == 'tools/call']    # nothing reached the vendor
    finally:
        m.stop()


def test_the_rule_matches_only_proxied_tools_without_read_only(shipped_policies):
    from sajha.policy.engine import Call
    eng = shipped_policies
    c = Caller('alice')
    decide = lambda **kw: eng.evaluate(Call('x__y', {}, c, 'mcp', **kw)).effect
    assert decide(proxied=True) == 'require_approval'                       # no annotations: may write
    assert decide(proxied=True, annotations={'readOnlyHint': False}) == 'require_approval'
    assert decide(proxied=True, annotations={'readOnlyHint': True}) == 'allow'
    assert decide(proxied=False) == 'allow'                                  # SAJHA's own and Net tools


def test_the_rule_switches_off(tmp_path):
    from sajha.policy.engine import Call, PolicyEngine
    from sajha.policy.loader import PolicySet
    d = tmp_path / 'policies'
    shutil.copytree(ROOT / 'config' / 'policies', d)
    p = d / '20-proxied-writes.yaml'
    p.write_text(p.read_text().replace('enabled: true', 'enabled: false'))
    eng = PolicyEngine(PolicySet(str(d)))
    assert eng.evaluate(Call('x__y', {}, Caller('alice'), 'mcp', proxied=True)).effect == 'allow'


def test_rule_language_proxied_and_annotation_conditions():
    from sajha.policy.engine import Call
    from sajha.policy.model import PolicyParseError, parse_text
    pol = parse_text('rules: [{id: a, match: {proxied: false, annotations: {destructiveHint: {ne: false}}},'
                     ' effect: deny}]', 't')
    m = pol.rules[0].match
    call = lambda **kw: Call('t', {}, Caller('u'), 'mcp', **kw)
    assert m.matches(call()) and m.matches(call(annotations={'destructiveHint': True}))
    assert not m.matches(call(annotations={'destructiveHint': False}))
    assert not m.matches(call(proxied=True))
    for doc, frag in [('rules: [{id: a, match: {proxied: maybe}}]', 'proxied'),
                      ('rules: [{id: a, match: {annotations: {readOnlyHint: {nope: 1}}}}]', 'unknown key')]:
        with pytest.raises(PolicyParseError, match=frag):
            parse_text(doc, 'bad')
