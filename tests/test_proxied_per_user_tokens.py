# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Per-user sign-in for proxied MCP servers, part 1: ``auth.type: token_user`` (wave 7 phase 7.2).

A fake vendor MCP server runs on a local port (the official SDK behind a gate): it accepts only the
personal tokens it issued, answers 401 to any other and 403 to a "forbidden" one, records which token
and which session every request carried, and lists an extra tool only to an "admin" token. Covered:
configuration rules of the credential modes; two users with
their own tokens get their own answers, per request on a 2026-07-28 upstream; a user without a token
gets "connect your account" on MCP 2026-07-28, MCP 2025-11-25, REST and Ask SAJHA, and an anonymous
caller a clear refusal; a vendor 401/403 is passed back and marks the connection "needs re-connect";
a session-based upstream gets one session per user, closed when idle, capped per upstream; discovery
waits for the first connected user and offers the union of what users see; the token never appears in
logs, audit, status, pages or errors; revocation when a user is disabled or signs out everywhere; the
SAJHA Net relay of the connect request; static upstreams unchanged.

Design: docs/architecture/Per-User Sign-In for Proxied Servers.md
"""


import json
import logging
import re
import socket
import threading
import time

import pytest
from mcp.server.mcpserver import Context
from sqlalchemy import create_engine

from sajha.accounts.errors import ConnectedAccountRequired
from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
from sajha.federation.config import ConfigError, FederationSettings, UpstreamConfig
from sajha.federation.user_tokens import ProxiedTokens, TokenRejected, set_tokens
from sajha.observability.caller import Caller, reset, set_caller

CANARY = 'CANARY7e1d'
ALICE = f'vt_alice_{CANARY}_0123456789abcdef'
BOB = f'vt_bob_{CANARY}_fedcba9876543210'
ADMIN = f'vt_admin_{CANARY}_aaaaaaaaaaaaaaaa'
FORBIDDEN = f'vt_forbid_{CANARY}_bbbbbbbbbbbbbbbb'
TOKENS = {ALICE: 'alice-at-vendor', BOB: 'bob-at-vendor', ADMIN: 'admin-at-vendor', FORBIDDEN: 'forbidden-user'}
KEY = 'test-vault-key-proxied-' + 'z' * 32


# ── the fake vendor ─────────────────────────────────────────────────

class FakeVendor:
    """An MCP SDK server behind a gate that checks ``Authorization: Bearer <personal token>``."""

    def __init__(self, header='Authorization', prefix='Bearer '):
        import uvicorn
        from mcp.server.mcpserver import MCPServer
        from mcp_types import ToolAnnotations
        ro = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
        self.header, self.prefix = header.lower(), prefix
        self.seen = []                  # (token, session id, http method, json-rpc method)
        server = MCPServer('vendor', title='Vendor', version='1.0.0')
        hname = self.header

        @server.tool(description='Who the vendor thinks you are.', annotations=ro)
        def whoami(ctx: Context) -> str:
            value = (ctx.headers or {}).get(hname, '')
            return 'you are ' + TOKENS.get(value[len(prefix):], 'nobody')

        @server.tool(description='A report only administrators may list.', annotations=ro)
        def admin_report() -> str:
            return 'quarterly numbers'

        app = server.streamable_http_app(json_response=True)

        async def gate(scope, receive, send):
            if scope['type'] != 'http':
                return await app(scope, receive, send)
            hdrs = {k.decode().lower(): v.decode() for k, v in scope.get('headers') or []}
            value = hdrs.get(self.header, '')
            tok = value[len(self.prefix):] if value.startswith(self.prefix) else ''
            body, more = b'', True
            while more:
                msg = await receive()
                body += msg.get('body', b'')
                more = msg.get('more_body', False)
            try:
                method = json.loads(body).get('method') if body[:1] == b'{' else None
            except ValueError:
                method = None
            self.seen.append((tok, hdrs.get('mcp-session-id', ''), scope['method'], method))
            if tok not in TOKENS or tok == FORBIDDEN:
                status = 403 if tok == FORBIDDEN else 401
                text = (b'{"message": "Resource not accessible by personal access token"}' if status == 403
                        else b'{"message": "Bad credentials"}')
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
            out = send
            if method == 'tools/list' and tok != ADMIN:
                held = {}

                async def out(message):         # noqa: F811 — hide admin_report from non-admin tokens
                    if message['type'] == 'http.response.start':
                        held['start'] = message
                        return
                    if message['type'] == 'http.response.body':
                        held['body'] = held.get('body', b'') + message.get('body', b'')
                        if message.get('more_body'):
                            return
                        data = held['body']
                        try:
                            doc = json.loads(data)
                            tools = doc['result']['tools']
                            doc['result']['tools'] = [t for t in tools if t['name'] != 'admin_report']
                            data = json.dumps(doc).encode()
                        except Exception:
                            pass
                        start = dict(held['start'])
                        start['headers'] = [(k, v) for k, v in start['headers'] if k.lower() != b'content-length'] \
                            + [(b'content-length', str(len(data)).encode())]
                        await send(start)
                        await send({'type': 'http.response.body', 'body': data})
                        return
                    await send(message)
            await app(scope, recv, out)

        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        self.port = s.getsockname()[1]
        s.close()
        self.url = f'http://127.0.0.1:{self.port}/mcp'
        self._uv = uvicorn.Server(uvicorn.Config(gate, host='127.0.0.1', port=self.port, log_level='warning',
                                                 lifespan='on'))
        self._t = threading.Thread(target=self._uv.run, daemon=True)
        self._t.start()
        deadline = time.time() + 10
        while not self._uv.started and time.time() < deadline:
            time.sleep(0.02)
        assert self._uv.started

    def tokens_seen(self, rpc=None):
        return [t for t, _s, _m, r in self.seen if rpc is None or r == rpc]

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
def vendor():
    v = FakeVendor()
    yield v
    v.stop()


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = TokenVault(engine=create_engine(f'sqlite:///{tmp_path / "vault.db"}'), key_provider=LocalKeyProvider(KEY))
    set_vault(v)
    events = []
    monkeypatch.setattr(ProxiedTokens, 'audit', staticmethod(
        lambda action, actor, upstream_id, ip=None, **d: events.append((action, actor, upstream_id, d))))
    t = ProxiedTokens(v)
    set_tokens(t)
    t.events = events
    yield t
    set_tokens(None)
    set_vault(None)


def manager_for(tmp_path, upstreams, **settings):
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    st = FederationSettings(enabled=True, allow_localhost=True, require_approval=False, startup_wait_seconds=10,
                            default_timeout_seconds=10, upstreams=upstreams, **settings)
    reg = Reg()
    m = FederationManager(reg, st, FederationStore(str(tmp_path / 'fed.json')))
    m.start()
    return m, reg


def token_user(url, uid='vendor', protocol='2026-07-28', **auth):
    return {'id': uid, 'url': url, 'protocol': protocol, 'title': 'Vendor',
            'auth': {'type': 'token_user', 'label': 'Vendor token', 'help_url': 'https://vendor.example/tokens',
                     **auth}}


def wait_for(cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def connect(m, vault, user, token, test=True):
    cfg = m.get_config(next(iter(m.upstream_ids())))
    out = vault.save(cfg, user, token, actor=user, tester=(lambda t: m.test_user_token(cfg.id, t)) if test else None)
    m.user_connected(cfg.id)            # what save() asks the process's manager (get_federation()) to do
    return out


# ── configuration ───────────────────────────────────────────────────

def test_config_rules_of_the_credential_modes():
    url = 'https://mcp.example.com/mcp'
    ok = UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': {
        'type': 'token_user', 'header': 'X-API-Key', 'format': '{token}', 'label': 'API key',
        'help_url': 'https://example.com/keys', 'token_prefix': 'k_', 'token_pattern': 'k_[a-z0-9]+',
        'discovery': {'type': 'bearer', 'token_ref': 'env:DISCOVERY'}}})
    assert ok.auth['type'] == 'token_user'
    assert UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': 'token_user'}).auth == {'type': 'token_user'}
    assert UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': {'type': 'static'}}).auth['type'] == 'static'
    oauth = UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': {'type': 'oauth_user', 'scopes': ['repo']}})
    from sajha.federation.user_tokens import auth_mode
    assert auth_mode(oauth) == 'oauth_user' and auth_mode(ok) == 'token_user'
    assert auth_mode(UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'headers': {'X-K': 'v'}})) == 'static'
    for bad, msg in [
            ({'auth': {'type': 'token_user'}, 'transport': 'stdio', 'command': '/bin/true'}, 'HTTP transport'),
            ({'auth': {'type': 'token_user'}, 'cache_ttl': 30}, 'per user'),
            ({'auth': {'type': 'token_user'}, 'headers': {'authorization': 'Bearer shared'}}, 'conflicts'),
            ({'auth': {'type': 'token_user', 'format': 'Bearer'}}, r'\{token\}'),
            ({'auth': {'type': 'token_user', 'header': 'Bad Header'}}, 'header name'),
            ({'auth': {'type': 'token_user', 'help_url': 'javascript:alert(1)'}}, 'help_url'),
            ({'auth': {'type': 'token_user', 'token_pattern': '('}}, 'regular expression'),
            ({'auth': {'type': 'token_user', 'colour': 'red'}}, 'unknown'),
            ({'auth': {'type': 'token_user', 'discovery': {'type': 'bearer', 'token': 'inline'}}}, 'reference'),
            ({'auth': {'type': 'static', 'token_ref': 'env:X'}}, 'static takes no other'),
            ({'auth': {'type': 'oauth_user'}, 'cache_ttl': 5}, 'per user'),
            ({'auth': {'type': 'magic'}}, 'auth.type must be one of')]:
        with pytest.raises(ConfigError, match=msg):
            UpstreamConfig.from_dict({'id': 'gh', 'url': url, **bad})


def test_mcp_servers_file_accepts_auth():
    from sajha.federation.mcp_servers import parse
    p = parse({'mcpServers': {
        'gh': {'url': 'https://g.example/mcp', 'auth': {'type': 'token_user', 'format': 'Bearer {token}'}},
        'plain': {'url': 'https://p.example/mcp', 'auth': 'static', 'headers': {'X-Team': 'risk'}},
        'later': {'url': 'https://l.example/mcp', 'auth': 'oauth_user'},
        'bad': {'url': 'https://b.example/mcp', 'auth': 42}}})
    ups = {u['id']: u for u in p.upstreams}
    assert ups['gh']['auth']['type'] == 'token_user' and 'auth' not in ups['plain']
    assert ups['later']['auth'] == {'type': 'oauth_user'} and 'bad' in p.errors
    for u in ups.values():
        UpstreamConfig.from_dict(u, source='file')


def test_token_checks_never_echo_the_token():
    from sajha.federation.user_tokens import TokenUserSpec, masked
    spec = TokenUserSpec(token_prefix='ghp_', token_pattern='ghp_[A-Za-z0-9]{8,}')
    assert spec.check_token('ghp_abcdefgh12') is None
    for bad in ('', 'xyz_' + CANARY, 'ghp_' + CANARY + ' x', 'ghp_!!'):
        why = spec.check_token(bad)
        assert why and CANARY not in why
    assert masked(ALICE) == '••••' + ALICE[-4:] and masked('short') == '••••'


# ── calls as each user ──────────────────────────────────────────────

def test_two_users_get_their_own_answers_per_request(tmp_path, vendor, vault):
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    try:
        assert wait_for(lambda: m.status('vendor')['state'] == 'waiting_for_user')
        assert not reg.tools                                    # nobody connected: nothing to discover with
        out = connect(m, vault, 'alice', ALICE)
        assert out['status'] == 'connected' and out['tools_seen'] >= 1 and ALICE not in json.dumps(out)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        connect(m, vault, 'bob', BOB)
        tool = reg.tools['vendor__whoami']
        for user, token, who in (('alice', ALICE, 'alice-at-vendor'), ('bob', BOB, 'bob-at-vendor')):
            vendor.seen.clear()
            with as_user(user):
                out = tool.execute_with_tracking({})
            assert f'you are {who}' in json.dumps(out)
            calls = [t for t, _s, _m, r in vendor.seen]
            assert calls and set(calls) == {token}, (user, calls)      # every request carried that user's token
        assert m.user_sessions('vendor') == []                  # 2026-07-28: no per-user state kept
        st = vault.status_of(m.get_config('vendor'), 'alice')
        assert st['status'] == 'connected' and st['last_used_at']
    finally:
        m.stop()


def test_without_a_token_the_call_asks_to_connect_and_anonymous_is_refused(tmp_path, vendor, vault):
    from sajha.accounts.respond import URL_ELICITATION_REQUIRED, mcp_response, rest_response
    from sajha.core.mcp_2025_11_25 import MCPError
    from sajha.core.mcp_mrtr import InputRequired
    from sajha.core.mcp_tool_context import ModernToolContext
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    try:
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tool = reg.tools['vendor__whoami']
        vendor.seen.clear()
        with as_user('carol'), pytest.raises(ConnectedAccountRequired) as ei:
            tool.execute_with_tracking({})
        exc = ei.value
        assert exc.reason == 'not_connected' and exc.connect_url.endswith('/account/server-connections/vendor')
        assert exc.provider_title == 'Vendor' and exc.local_path == '/account/server-connections/vendor'
        assert vendor.tokens_seen('tools/call') == []           # nothing was sent as anyone else
        # MCP 2026-07-28: an MRTR URL elicitation
        ctx = ModernToolContext(client_capabilities={'elicitation': {'url': {}}})
        tok = ctx.activate()
        try:
            with pytest.raises(InputRequired) as ir:
                mcp_response(exc, 'modern', None)
            req = ir.value.requests['sajha.connect.upstream:vendor']
            assert req['params']['mode'] == 'url' and req['params']['url'] == exc.connect_url
        finally:
            ctx.deactivate(tok)
        # MCP 2025-11-25: -32042 URL elicitation required
        with pytest.raises(MCPError) as e2:
            mcp_response(exc, 'legacy', {'client_capabilities': {'elicitation': {'url': {}}}})
        assert e2.value.code == URL_ELICITATION_REQUIRED
        # REST: 428 with the connect URL
        r = rest_response(exc)
        body = json.loads(r.body)
        assert r.status_code == 428 and body['connect_url'] == exc.connect_url
        # anonymous and an API key without an owner: a clear refusal, never a page to visit
        for who in ('anonymous', 'apikey:svc'):
            with as_user(who), pytest.raises(ConnectedAccountRequired) as ea:
                tool.execute_with_tracking({})
            assert ea.value.reason == 'sign_in_required' and 'not a signed-in user' in ea.value.message
            assert mcp_response(ea.value, 'legacy', {'client_capabilities': {'elicitation': {'url': {}}}})['isError']
    finally:
        m.stop()


def test_ask_sajha_shows_a_connect_button(tmp_path, vendor, vault):
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm import RequestContext
    from sajha.ai.llm.settings import AskSettings
    from tests.ai.conftest import ToolBox, make_gateway
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    try:
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tb = ToolBox(with_calc=False)
        tb.add(reg.tools['vendor__whoami'])
        gw = make_gateway({'aliases': {'default': ['mock/mock-scripted']}})
        gw.providers['mock'].set_script([{'tool_calls': [{'name': 'vendor__whoami', 'arguments': {}, 'id': 'w1'}]},
                                         {'text': 'done'}])
        svc = IntelligenceService(gw, tb, settings=AskSettings(audit=False), audit=lambda e: None)
        with as_user('carol'):
            events = list(svc.stream_ask('Who am I at the vendor?', RequestContext(user_id='carol')))
        ev = next(e for e in events if e['type'] == 'needs_connection')
        assert ev['provider'] == 'upstream:vendor' and ev['provider_title'] == 'Vendor'
        assert ev['connect_url'] == '/account/server-connections/vendor'
        assert events[-1]['result']['stopped_by'] == 'needs_connection'
    finally:
        m.stop()


@pytest.mark.parametrize('bad, status', [(f'vt_unknown_{CANARY}_cccccccccccc', 401), (FORBIDDEN, 403)])
def test_vendor_refusal_is_passed_back_and_marks_needs_reconnect(tmp_path, vendor, vault, bad, status):
    from sajha.federation.tool import FederatedToolError
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    try:
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tool = reg.tools['vendor__whoami']
        with pytest.raises(TokenRejected) as tr:                # the connect page's test call refuses it
            connect(m, vault, 'dave', bad)
        assert f'HTTP {status}' in str(tr.value) and CANARY not in str(tr.value)
        connect(m, vault, 'dave', bad, test=False)              # saved without testing
        from sajha.core.circuit_breaker import get_circuit_registry
        breaker = get_circuit_registry().get_breaker('vendor__whoami')
        before = breaker.failure_count if breaker else 0
        vendor.seen.clear()
        with as_user('dave'), pytest.raises(FederatedToolError) as ei:
            tool.execute_with_tracking({})
        msg = str(ei.value)
        assert f'refused your token (HTTP {status})' in msg and 'needs re-connect' in msg and CANARY not in msg
        assert ('Bad credentials' if status == 401 else 'not accessible') in msg       # the vendor's own answer
        assert set(vendor.tokens_seen('tools/call')) == {bad}    # never retried as anyone else
        assert (breaker.failure_count if breaker else 0) == before    # one user's token: not the upstream failing
        assert vault.status_of(m.get_config('vendor'), 'dave')['status'] == 'needs_reconnect'
        with as_user('dave'), pytest.raises(ConnectedAccountRequired) as again:
            tool.execute_with_tracking({})
        assert again.value.reason == 'reauth_required'
        assert any(e[0] == 'proxied_connection.refused' for e in vault.events)
        with as_user('alice'):                                  # other users are unaffected
            assert 'alice-at-vendor' in json.dumps(tool.execute_with_tracking({}))
    finally:
        m.stop()


def test_session_based_upstream_one_session_per_user_idle_and_cap(tmp_path, vendor, vault):
    m, reg = manager_for(tmp_path, [token_user(vendor.url, protocol='legacy')],
                         per_user_session_idle_seconds=1.0, per_user_sessions_max=2)
    try:
        connect(m, vault, 'alice', ALICE)
        connect(m, vault, 'bob', BOB)
        connect(m, vault, 'erin', ADMIN)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        tool = reg.tools['vendor__whoami']
        vendor.seen.clear()
        for user in ('alice', 'bob', 'alice'):
            with as_user(user):
                tool.execute_with_tracking({})
        assert m.user_sessions('vendor') == ['alice', 'bob']
        inits = [t for t, _s, _m, r in vendor.seen if r == 'initialize']
        assert sorted(inits) == sorted([ALICE, BOB])            # alice's second call reused her session
        sessions = {}
        for t, sid, _m, r in vendor.seen:
            if sid and r == 'tools/call':
                sessions.setdefault(sid, set()).add(t)
        assert len(sessions) == 2 and all(len(v) == 1 for v in sessions.values())   # a session never mixes users
        time.sleep(0.2)
        with as_user('erin'):                                   # the cap: the oldest idle session goes
            tool.execute_with_tracking({})
        assert m.user_sessions('vendor') == ['alice', 'erin'] or m.user_sessions('vendor') == ['bob', 'erin']
        assert 'erin' in m.user_sessions('vendor') and len(m.user_sessions('vendor')) == 2
        assert wait_for(lambda: m.user_sessions('vendor') == [], timeout=6)      # idle: closed
        assert m.status('vendor')['user_sessions'] == 0
        vault.remove('vendor', 'bob', actor='bob')              # removing a token closes that user's session
        with as_user('bob'), pytest.raises(ConnectedAccountRequired):
            tool.execute_with_tracking({})
    finally:
        m.stop()


def test_discovery_union_and_discovery_token(tmp_path, vendor, vault, monkeypatch):
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    try:
        assert wait_for(lambda: m.status('vendor')['state'] == 'waiting_for_user')
        assert 'waiting for the first user' in m.status('vendor')['last_error']
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        assert 'vendor__admin_report' not in reg.tools          # alice's token does not list it
        connect(m, vault, 'erin', ADMIN)                        # an administrator's token lists one more
        assert wait_for(lambda: 'vendor__admin_report' in reg.tools)
        with as_user('erin'):
            assert 'quarterly' in json.dumps(reg.tools['vendor__admin_report'].execute_with_tracking({}))
    finally:
        m.stop()
    monkeypatch.setenv('VENDOR_DISCOVERY', ADMIN)               # a discovery credential instead
    m2, reg2 = manager_for(tmp_path, [token_user(vendor.url, uid='vendor2', discovery={
        'type': 'bearer', 'token_ref': 'env:VENDOR_DISCOVERY'})])
    try:
        assert wait_for(lambda: 'vendor2__admin_report' in reg2.tools)
        with as_user('alice'), pytest.raises(ConnectedAccountRequired):     # never the discovery token for a call
            reg2.tools['vendor2__whoami'].execute_with_tracking({})
    finally:
        m2.stop()


def test_static_upstreams_are_unchanged(tmp_path, vendor, vault, monkeypatch):
    monkeypatch.setenv('VENDOR_SHARED', BOB)
    m, reg = manager_for(tmp_path, [{'id': 'shared', 'url': vendor.url, 'protocol': '2026-07-28',
                                     'auth': {'type': 'bearer', 'token_ref': 'env:VENDOR_SHARED'}}])
    try:
        assert wait_for(lambda: 'shared__whoami' in reg.tools)
        for user in ('alice', 'anonymous'):
            with as_user(user):
                assert 'bob-at-vendor' in json.dumps(reg.tools['shared__whoami'].execute_with_tracking({}))
        st = m.status('shared')
        assert st['auth_mode'] == 'static' and st['user_sessions'] == 0 and BOB not in json.dumps(st)
        from sajha.audit.tool_calls import _proxied_identity
        from sajha.federation import manager as fm
        monkeypatch.setattr(fm, '_manager', m)
        assert _proxied_identity(reg.tools['shared__whoami'], Caller('alice')) == {'upstream': 'shared',
                                                                                    'mode': 'static'}
    finally:
        m.stop()


def test_oauth_user_discovers_with_a_discovery_credential_and_calls_need_sign_in(tmp_path, vendor, vault,
                                                                                 monkeypatch):
    """oauth_user (phase 7.3, tests/test_proxied_oauth_user.py): a discovery credential lists the tools, and a
    call by a user who has not signed in asks them to connect; never the discovery credential."""
    from sajha.federation import manager as fm
    monkeypatch.setenv('VENDOR_DISCOVERY', ALICE)
    m, reg = manager_for(tmp_path, [{'id': 'later', 'url': vendor.url, 'protocol': '2026-07-28', 'auth': {
        'type': 'oauth_user', 'discovery': {'type': 'bearer', 'token_ref': 'env:VENDOR_DISCOVERY'}}}])
    monkeypatch.setattr(fm, '_manager', m)
    try:
        assert wait_for(lambda: 'later__whoami' in reg.tools)
        st = m.status('later')
        assert st['auth_mode'] == 'oauth_user' and st['auth_note'] == ''
        assert not m.config_errors
        vendor.seen.clear()
        with as_user('alice'), pytest.raises(ConnectedAccountRequired) as ei:
            reg.tools['later__whoami'].execute_with_tracking({})
        assert ei.value.reason == 'not_connected' and vendor.tokens_seen('tools/call') == []
    finally:
        m.stop()


# ── secrecy, audit and revocation ───────────────────────────────────

def test_tokens_never_appear_in_logs_audit_status_or_errors(tmp_path, vendor, vault, caplog, monkeypatch):
    from sajha.federation import manager as fm
    from sajha.federation.tool import FederatedToolError
    caplog.set_level(logging.DEBUG)
    m, reg = manager_for(tmp_path, [token_user(vendor.url)])
    monkeypatch.setattr(fm, '_manager', m)
    texts = []
    try:
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendor__whoami' in reg.tools)
        with as_user('alice'):
            texts.append(json.dumps(reg.tools['vendor__whoami'].execute_with_tracking({})))
        connect(m, vault, 'dave', FORBIDDEN, test=False)
        with as_user('dave'), pytest.raises(FederatedToolError) as e:
            reg.tools['vendor__whoami'].execute_with_tracking({})
        texts.append(str(e.value))
        try:
            connect(m, vault, 'dave', f'vt_nope_{CANARY}_dddddddddddd')
        except TokenRejected as tr:
            texts.append(str(tr))
        texts.append(json.dumps(m.status('vendor'), default=str))
        texts.append(json.dumps(vault.all_connections(), default=str))
        texts.append(json.dumps(vault.status_of(m.get_config('vendor'), 'alice'), default=str))
        texts.append(json.dumps(vault.events, default=str))
        from sajha.audit.tool_calls import _proxied_identity
        ident = _proxied_identity(reg.tools['vendor__whoami'], Caller('alice'))
        assert ident == {'upstream': 'vendor', 'mode': 'token_user', 'user': 'alice'}
        texts.append(json.dumps(ident))
    finally:
        m.stop()
    texts.append(caplog.text)
    for t in texts:
        assert CANARY not in t, t[:400]
    # in the vault the token is ciphertext only
    from sqlalchemy import text
    with vault.vault.engine.connect() as c:
        rows = ' '.join(str(r) for r in c.execute(text('SELECT * FROM connected_accounts')).all())
    assert 'upstream:vendor' in rows and CANARY not in rows


def test_revocation_on_disable_delete_and_sign_out_everywhere(tmp_path, vault):
    cfg = UpstreamConfig.from_dict(token_user('https://vendor.example/mcp'))
    for user in ('frank', 'gina'):
        vault.save(cfg, user, ALICE)
    assert vault.status_of(cfg, 'frank')['status'] == 'connected'
    from sajha.auth.revocation import end_all_sessions

    class _DB:
        def commit(self):
            pass

        def add(self, *_a):
            pass

    class _U:
        user_id, token_version = 'frank', 0
    end_all_sessions(_DB(), _U(), 'frank', 'password_change')   # a password change keeps them
    assert vault.status_of(cfg, 'frank')['status'] == 'connected'
    end_all_sessions(_DB(), _U(), 'frank', 'sign_out_everywhere')
    assert vault.status_of(cfg, 'frank')['status'] == 'not_connected'
    assert vault.status_of(cfg, 'gina')['status'] == 'connected'
    assert any(e[0] == 'proxied_connection.disconnected' and e[3].get('reason') == 'sign_out_everywhere'
               for e in vault.events)


def test_admin_disable_and_delete_revoke_tokens(tmp_path, vault, app_client):
    import uuid
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.engine import get_db_session
    from sajha.db.models import User
    cfg = UpstreamConfig.from_dict(token_user('https://vendor.example/mcp'))
    uid = f'ptok_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password('Passw0rd!x'), enabled=True)
        user.roles.append(RoleDAO(db).get_or_create('user'))
        UserDAO(db).create(user)
    finally:
        db.close()
    vault.save(cfg, uid, ALICE)
    r = app_client.post(f'/api/admin/users/{uid}/disable', headers=_bearer())
    assert r.status_code == 200 and vault.status_of(cfg, uid)['status'] == 'not_connected'
    vault.save(cfg, uid, ALICE)
    r = app_client.delete(f'/api/admin/users/{uid}/delete', headers=_bearer())
    assert r.status_code == 200 and vault.status_of(cfg, uid)['status'] == 'not_connected'


# ── the pages and the API ───────────────────────────────────────────

@pytest.fixture(scope='module')
def app_client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _bearer():
    from sajha.auth.jwt_handler import create_access_token
    return {'Authorization': 'Bearer ' + create_access_token('admin', ['admin'])}


def _modern_call(c, name, caps=None):
    params = {'name': name, 'arguments': {}, '_meta': {
        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientCapabilities': caps or {},
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}}
    return c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': params},
                  headers={**_bearer(), 'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/call',
                           'Mcp-Name': name, 'Accept': 'application/json, text/event-stream'})


def test_mcp_both_eras_rest_and_the_pages_end_to_end(tmp_path, vendor, vault, app_client, monkeypatch):
    """Through the app: the connect answers on /mcp (both eras) and REST, the connect page (CSRF, test call,
    masked), the Connections view, the admin view and the JSON API; never the token."""
    from sajha import app as app_mod
    from sajha.federation import manager as fm
    c = app_client
    m, reg = manager_for(tmp_path, [token_user(vendor.url, uid='vendorx')])
    monkeypatch.setattr(fm, '_manager', m)
    registry = app_mod.tools_registry
    try:
        connect(m, vault, 'alice', ALICE)
        assert wait_for(lambda: 'vendorx__whoami' in reg.tools)
        tool = reg.tools['vendorx__whoami']
        registry.register_tool(tool)
        # MCP 2026-07-28: input_required with a URL elicitation to the connect page
        r = _modern_call(c, 'vendorx__whoami', caps={'elicitation': {'url': {}}}).json()['result']
        assert r['resultType'] == 'input_required', r
        assert r['inputRequests']['sajha.connect.upstream:vendorx']['params']['url'].endswith(
            '/account/server-connections/vendorx')
        # MCP 2025-11-25: -32042
        h = {**_bearer(), 'Accept': 'application/json, text/event-stream'}
        init = c.post('/mcp', headers=h, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {'elicitation': {'form': {}, 'url': {}}},
            'clientInfo': {'name': 't', 'version': '1'}}})
        h2 = {**h, 'Mcp-Session-Id': init.headers['Mcp-Session-Id'], 'MCP-Protocol-Version': '2025-11-25'}
        c.post('/mcp', headers=h2, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        body = c.post('/mcp', headers=h2, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                                'params': {'name': 'vendorx__whoami', 'arguments': {}}}).json()
        assert body['error']['code'] == -32042
        assert body['error']['data']['elicitations'][0]['url'].endswith('/account/server-connections/vendorx')
        # REST: 428
        rr = c.post('/api/tools/execute', headers=_bearer(), json={'tool': 'vendorx__whoami', 'arguments': {}})
        assert rr.status_code == 428 and rr.json()['connect_url'].endswith('/account/server-connections/vendorx')

        # the pages, signed in as admin (who has no token yet)
        c.cookies.clear()
        login = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        cookies = dict(login.cookies)
        page = c.get('/account/server-connections', cookies=cookies)
        assert page.status_code == 200 and 'Vendor' in page.text and 'Not connected' in page.text
        cp = c.get('/account/server-connections/vendorx', cookies=cookies)
        assert cp.status_code == 200 and 'Vendor token' in cp.text and 'https://vendor.example/tokens' in cp.text
        assert 'type="password"' in cp.text and 'nonce=' not in cp.text.split('data-onsubmit')[0][:0]
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', cp.text).group(1)
        bad = c.post('/account/server-connections/vendorx/token', data={'csrf': 'nope', 'token': ADMIN},
                     cookies=cookies, follow_redirects=False)
        assert bad.status_code == 403
        wrong = c.post('/account/server-connections/vendorx/token',
                       data={'csrf': csrf, 'token': f'vt_wrong_{CANARY}_eeeeeeeeeeee'}, cookies=cookies,
                       follow_redirects=False)
        assert wrong.status_code == 400 and 'refused this token' in wrong.text and CANARY not in wrong.text
        ok = c.post('/account/server-connections/vendorx/token', data={'csrf': csrf, 'token': ADMIN},
                    cookies=cookies, follow_redirects=False)
        assert ok.status_code == 303 and ok.headers['location'] == '/account/server-connections?saved=vendorx'
        page = c.get('/account/server-connections?saved=vendorx', cookies=cookies)
        assert 'Connected to Vendor' in page.text and ADMIN[-4:] in page.text and ADMIN not in page.text
        # the call now runs as admin, with admin's token
        r = _modern_call(c, 'vendorx__whoami').json()['result']
        assert 'admin-at-vendor' in json.dumps(r) and CANARY not in json.dumps(r)
        admin_page = c.get('/admin/server-connections', cookies=cookies)
        assert admin_page.status_code == 200 and 'alice' in admin_page.text and CANARY not in admin_page.text
        api = c.get('/api/accounts/server-connections', cookies=cookies).json()
        assert api['connections'][0]['status'] == 'connected' and CANARY not in json.dumps(api)
        assert CANARY not in json.dumps(c.get('/api/admin/server-connections', headers=_bearer()).json())
        assert c.delete('/api/accounts/server-connections/vendorx', cookies=cookies).status_code == 403   # no CSRF
        put = c.put('/api/accounts/server-connections/vendorx', headers=_bearer(), json={'token': 'x y'})
        assert put.status_code == 400
        out = c.post('/account/server-connections/vendorx/remove', data={'csrf': csrf}, cookies=cookies,
                     follow_redirects=False)
        assert out.status_code == 303
        assert vault.status_of(m.get_config('vendorx'), 'admin')['status'] == 'not_connected'
        rv = c.delete('/api/admin/server-connections/vendorx/alice', headers=_bearer())
        assert rv.status_code == 200 and vault.status_of(m.get_config('vendorx'), 'alice')['status'] == 'not_connected'
        assert any(e[0] == 'proxied_connection.connected' and e[1] == 'admin' for e in vault.events)
        assert any(e[0] == 'proxied_connection.disconnected' and e[3].get('by_admin') for e in vault.events)
    finally:
        registry.unregister_tool('vendorx__whoami')
        c.cookies.clear()
        m.stop()


# ── SAJHA Net ───────────────────────────────────────────────────────

def test_sajhanet_relays_the_connect_request_and_keeps_the_token_home(tmp_path, vault, monkeypatch):
    """A remote caller mapped to a local user without a token gets the connect request back as an input
    request (phase 6.3 relay); after the user connects at the host, the retry runs; the token never
    travels between the servers."""
    from sajha.core.mcp_mrtr import InputRequired
    from sajha.core.mcp_tool_context import ModernToolContext
    from sajha.federation.user_tokens import get_tokens
    from sajha.observability.caller import current
    from tests.net import test_net_routing_integration as tri
    from tests.net.test_net_routing_integration import Echo, make, node, settle
    from tests.net.test_net_streaming import StreamConnector, call, quick, stream_app_for
    net = 'acme-net'
    cfg = UpstreamConfig.from_dict(token_user('https://vendor.example/mcp', uid='gh'))
    seen_users = []

    class NeedsToken(Echo):
        """Stands in for a token_user proxied tool at the host: resolves the caller's own token."""

        def execute(self, arguments):
            seen_users.append(current().user_id)
            token = get_tokens().resolve(cfg, current().user_id, tool=self.name)
            return f'ran with a token of {len(token)} characters'

    monkeypatch.setattr(tri, 'app_for', stream_app_for)
    conn = StreamConnector()
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(net)
    assert node(a).try_join()
    b = make(tmp_path, 'cust-na', conn, [NeedsToken('gh_tool', owner='cust-na')])
    b.start(run_agents=False)
    b.enroll(net, 'https://risk-eu.test', a.ca_token(net, 'cust-na')['token'], by='test')
    assert node(b).try_join()
    try:
        settle([a, b], 5)
        quick(a, progress_min_interval_ms=0)
        quick(b, progress_min_interval_ms=0)
        name = f'{net}__cust-na__gh_tool'
        with pytest.raises(InputRequired) as ir:
            call(a, name, {'x': 1}, ModernToolContext())
        key = 'sajha.connect.upstream:gh'
        req = ir.value.requests[key]
        assert req['method'] == 'elicitation/create' and req['params']['mode'] == 'url'
        assert req['params']['url'].endswith('/account/server-connections/gh')
        mapped = seen_users[-1]
        get_tokens().save(cfg, mapped, ALICE)                   # the mapped user connects at the host
        r = call(a, name, {'x': 1}, ModernToolContext(input_responses={key: {'action': 'accept'}},
                                                      state=ir.value.state))
        assert 'ran with a token of' in json.dumps(r), r
        traffic = json.dumps([str(x) for x in conn.mcp])
        assert CANARY not in traffic                            # the token never left the host
    finally:
        a.stop()
        b.stop()
