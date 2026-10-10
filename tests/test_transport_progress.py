# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Progress and cancellation on every client transport (wave 6 phase 6.2; SAJHA Net conformance STR-06 and
STR-07; docs/protocol/MCP Protocol Guide.md, "Progress and cancellation per transport").

A registry tool that calls ``report_progress``/``report_log`` and polls ``is_cancelled`` reaches its client
on 2026-07-28 HTTP and stdio, 2025-11-25 Streamable HTTP (SSE when the call has ``_meta.progressToken``),
2024-11-05 HTTP+SSE, WebSocket and 2025-11-25 stdio, with the client's own token, ahead of the result; so
does a remote SAJHA Net tool (an in-process net, as tests/net/test_net_streaming.py), whose host's events
are relayed. REST stays buffered. Cancellation reaches the tool on every transport that has it. Two
WebSocket calls run side by side (tools/call no longer runs on the event loop).

STR-07: a remote tool with result data classes, or one a residency rule names, streams numbers only (the
host strips text before signing; the home again on arrival); ``inputResponses`` are checked as arguments.
"""

import asyncio
import io
import json
import os
import sys
import threading
import time
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from sajha.core import mcp_sse_relay  # noqa: E402
from sajha.net import EXTENSION_ID, plugins  # noqa: E402
from sajha.net.integration import residency as NR  # noqa: E402
from tests.net.test_net_streaming import NET, Slow, caller, call, net2  # noqa: E402,F401  (net2: the fixture)
from tests.test_mcp_2026_07_28 import _meta, modern, sse_messages  # noqa: E402

LEGACY = '2025-11-25'
REMOTE = 'acme-net__cust-na__slow'


@pytest.fixture(scope='module')
def client():
    os.environ['SAJHA_MCP_CONFORMANCE_FIXTURES'] = 'true'
    os.environ['SAJHA_MCP_ANONYMOUS_TOOLS'] = '*'
    from sajha.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    os.environ.pop('SAJHA_MCP_ANONYMOUS_TOOLS', None)


def registry():
    from sajha.app import mcp_handler
    return mcp_handler.tools_registry


@pytest.fixture
def local(client):
    t = Slow('tp_slow', owner='local', steps=3)
    registry().register_tool(t)
    yield t
    registry().unregister_tool(t.name)


@pytest.fixture
def remote(client, net2):
    """The home's proxy of cust-na's ``slow``, served by this app (as if SAJHA Net imported it here)."""
    proxy = net2['a'].tools_registry.get_tool(REMOTE)
    assert proxy is not None
    registry().register_tool(proxy)
    yield net2['b'].tools_registry.get_tool('slow')
    registry().unregister_tool(REMOTE)


def legacy_session(client):
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': LEGACY, 'capabilities': {}, 'clientInfo': {'name': 'pytest', 'version': '1'}}})
    return {'Mcp-Session-Id': r.headers['mcp-session-id'], 'MCP-Protocol-Version': LEGACY}


def call_body(name, rid=7, token='tok', x=1, **meta):
    m = {'progressToken': token} if token is not None else {}
    m.update(meta)
    return {'jsonrpc': '2.0', 'id': rid, 'method': 'tools/call',
            'params': {'name': name, 'arguments': {'x': x}, '_meta': m}}


def progress_of(messages, token='tok'):
    p = [m['params'] for m in messages if m.get('method') == 'notifications/progress']
    assert all(x['progressToken'] == token for x in p), p
    return [x['progress'] for x in p]


def final_of(messages, rid=7):
    out = [m for m in messages if m.get('id') == rid and ('result' in m or 'error' in m)]
    assert len(out) == 1, messages
    return out[0]


def text_of(response):
    assert 'result' in response, response
    return response['result']['content'][0]['text']


def expect(name):
    return 'local:tp_slow:1' if name == 'tp_slow' else 'cust-na:slow:1'


def run_in_thread(fn):
    box = {}

    def go():
        try:
            box['value'] = fn()
        except Exception as e:     # pragma: no cover - surfaced by the assertion below
            box['error'] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t, box


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ── STR-06: progress on every transport ─────────────────────────────

@pytest.mark.parametrize('which', ['local', 'remote'])
def test_2025_11_25_http_streams_progress_before_the_result(client, request, which):
    request.getfixturevalue(which)
    name = 'tp_slow' if which == 'local' else REMOTE
    h = dict(legacy_session(client), Accept='application/json, text/event-stream')
    r = client.post('/mcp', json=call_body(name), headers=h)
    msgs = sse_messages(r)
    assert progress_of(msgs) == [1, 2, 3]
    assert msgs.index(final_of(msgs)) == len(msgs) - 1          # every event before the result
    assert text_of(final_of(msgs)) == expect(name)
    # no logLevel asked: no log lines; a client that takes JSON only (or sends no token) gets JSON
    assert not [m for m in msgs if m.get('method') == 'notifications/message']
    r = client.post('/mcp', json=call_body(name), headers=dict(h, Accept='application/json'))
    assert r.headers['content-type'].startswith('application/json') and text_of(r.json()) == expect(name)
    r = client.post('/mcp', json=call_body(name, token=None), headers=h)
    assert r.headers['content-type'].startswith('application/json')


def test_2025_11_25_http_log_level_from_meta(client, local):
    h = dict(legacy_session(client), Accept='application/json, text/event-stream')
    r = client.post('/mcp', json=call_body('tp_slow', **{'io.modelcontextprotocol/logLevel': 'info'}), headers=h)
    logs = [m['params']['data'] for m in sse_messages(r) if m.get('method') == 'notifications/message']
    assert logs == ['local log 1', 'local log 2', 'local log 3']


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_2024_11_05_http_sse_progress_on_the_session_stream(client, request, which):
    request.getfixturevalue(which)
    name = 'tp_slow' if which == 'local' else REMOTE
    for path in ('/mcp', '/mcp/message'):
        sid = f'legacy-{which}-{path[-3:]}'
        q = asyncio.Queue()
        mcp_sse_relay._queues[sid] = q                      # what GET /mcp/sse registers
        try:
            r = client.post(f'{path}?session={sid}', json=call_body(name))
            got = []
            while not q.empty():
                got.append(q.get_nowait())
        finally:
            mcp_sse_relay._queues.pop(sid, None)
        assert progress_of(got) == [1, 2, 3]
        if path == '/mcp':
            assert r.status_code == 202 and text_of(got[-1]) == expect(name)
        else:                                               # the older alias answers inline
            assert text_of(r.json()) == expect(name)


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_websocket_progress_before_the_response(client, request, which):
    request.getfixturevalue(which)
    name = 'tp_slow' if which == 'local' else REMOTE
    with client.websocket_connect('/mcp/ws') as ws:
        ws.send_text(json.dumps(call_body(name)))
        msgs = []
        while True:
            m = json.loads(ws.receive_text())
            msgs.append(m)
            if m.get('id') == 7:
                break
    assert progress_of(msgs) == [1, 2, 3] and text_of(msgs[-1]) == expect(name)


def _stdio(client):
    from sajha.auth.access import mcp_session_for
    from sajha.cli.stdio import StdioServer
    from sajha.app import mcp_handler
    out = io.BytesIO()
    return StdioServer(mcp_handler, mcp_session_for(None), out), out


def _lines(out):
    return [json.loads(x) for x in out.getvalue().decode().splitlines() if x.strip()]


@pytest.mark.parametrize('which', ['local', 'remote'])
@pytest.mark.parametrize('era', ['2025-11-25', '2026-07-28'])
def test_stdio_progress_in_order(client, request, which, era):
    request.getfixturevalue(which)
    name = 'tp_slow' if which == 'local' else REMOTE
    server, out = _stdio(client)
    body = call_body(name)
    if era == '2026-07-28':
        body['params']['_meta'] = _meta(progressToken='tok')

    async def go():
        server.dispatch(json.dumps(body).encode())
        await asyncio.wait_for(asyncio.gather(*list(server.inflight.values())), 10)
    asyncio.run(go())
    msgs = _lines(out)
    assert progress_of(msgs) == [1, 2, 3] and text_of(msgs[-1]) == expect(name)


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_2026_07_28_http_progress(client, request, which):
    request.getfixturevalue(which)
    name = 'tp_slow' if which == 'local' else REMOTE
    r = modern(client, 'tools/call', {'name': name, 'arguments': {'x': 1}}, meta=_meta(progressToken='tok'))
    msgs = sse_messages(r)
    assert progress_of(msgs) == [1, 2, 3] and text_of(msgs[-1]) == expect(name)


def test_rest_stays_buffered(client, local):
    """REST has no channel for progress: the final result only (documented)."""
    from sajha.core.mcp_tool_context import current_context
    seen = []
    orig = local.execute

    def execute(arguments):
        seen.append(current_context())
        return orig(arguments)
    local.execute = execute
    r = client.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    admin = dict(r.cookies)
    client.cookies.clear()
    try:
        r = client.post('/api/tools/execute', cookies=admin, json={'tool': 'tp_slow', 'arguments': {'x': 1}})
    finally:
        local.execute = orig
    assert r.status_code == 200, r.text
    assert r.json()['result'] == 'local:tp_slow:1'
    assert seen == [None]                                       # no tool context: progress goes nowhere


# ── WebSocket: off the event loop ───────────────────────────────────

def test_two_websocket_calls_do_not_block_each_other(client, local):
    local.gate = threading.Event()                              # the first call waits for the second
    other = Slow('tp_quick', owner='local', steps=0)
    registry().register_tool(other)
    try:
        with client.websocket_connect('/mcp/ws') as ws1, client.websocket_connect('/mcp/ws') as ws2:
            ws1.send_text(json.dumps(call_body('tp_slow', rid=1, token=None)))
            assert wait_for(lambda: local.calls == 1)
            ws2.send_text(json.dumps(call_body('tp_quick', rid=2, token=None)))
            r2 = json.loads(ws2.receive_text())                  # answered while the first still runs
            assert r2['id'] == 2 and text_of(r2) == 'local:tp_quick:1'
            assert not local.finished.is_set()
            # and on one socket too: a second call is answered while the first waits
            ws2.send_text(json.dumps(call_body('tp_slow', rid=3, token=None)))
            assert wait_for(lambda: local.calls == 2)
            ws2.send_text(json.dumps(call_body('tp_quick', rid=4, token=None)))
            assert json.loads(ws2.receive_text())['id'] == 4
            local.gate.set()
            assert json.loads(ws1.receive_text())['id'] == 1
            assert json.loads(ws2.receive_text())['id'] == 3
    finally:
        local.gate.set()
        registry().unregister_tool('tp_quick')


# ── cancellation ────────────────────────────────────────────────────

def _cancel(rid=7):
    return {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': rid, 'reason': 'test'}}


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_websocket_cancellation_reaches_the_tool(client, request, which):
    tool = request.getfixturevalue(which)
    tool.steps, tool.hold = 1, 10.0
    name = 'tp_slow' if which == 'local' else REMOTE
    with client.websocket_connect('/mcp/ws') as ws:
        ws.send_text(json.dumps(call_body(name)))
        assert json.loads(ws.receive_text())['method'] == 'notifications/progress'
        ws.send_text(json.dumps(_cancel()))
        assert tool.cancelled.wait(5)


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_2025_11_25_http_cancellation_reaches_the_tool(client, request, which):
    tool = request.getfixturevalue(which)
    tool.steps, tool.hold = 1, 10.0
    name = 'tp_slow' if which == 'local' else REMOTE
    h = legacy_session(client)
    t, box = run_in_thread(lambda: client.post('/mcp', json=call_body(name), headers=dict(
        h, Accept='application/json, text/event-stream')))
    assert wait_for(lambda: tool.calls >= 1)
    time.sleep(0.1)
    assert client.post('/mcp', json=_cancel(), headers=h).status_code == 202
    assert tool.cancelled.wait(5)
    t.join(10)


def test_2024_11_05_http_sse_cancellation_reaches_the_tool(client, local):
    local.steps, local.hold = 1, 10.0
    sid = 'legacy-cancel'
    mcp_sse_relay._queues[sid] = asyncio.Queue()
    try:
        t, box = run_in_thread(lambda: client.post(f'/mcp?session={sid}', json=call_body('tp_slow')))
        assert wait_for(lambda: local.calls >= 1)
        time.sleep(0.1)
        assert client.post(f'/mcp?session={sid}', json=_cancel()).status_code == 202
        assert local.cancelled.wait(5)
        t.join(10)
        # the older alias takes notifications/cancelled too
        local.cancelled.clear()
        t, box = run_in_thread(lambda: client.post(f'/mcp/message?session={sid}', json=call_body('tp_slow', rid=8)))
        assert wait_for(lambda: local.calls >= 2)
        time.sleep(0.1)
        client.post(f'/mcp/message?session={sid}', json=_cancel(8))
        assert local.cancelled.wait(5)
        t.join(10)
    finally:
        mcp_sse_relay._queues.pop(sid, None)


@pytest.mark.parametrize('which', ['local', 'remote'])
def test_stdio_cancellation_reaches_the_tool(client, request, which):
    tool = request.getfixturevalue(which)
    tool.steps, tool.hold = 1, 10.0
    name = 'tp_slow' if which == 'local' else REMOTE
    server, out = _stdio(client)

    async def go():
        server.dispatch(json.dumps(call_body(name)).encode())
        for _ in range(500):
            if tool.calls:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        server.dispatch(json.dumps(_cancel()).encode())
        await asyncio.sleep(0)
    asyncio.run(go())
    assert tool.cancelled.wait(5)


# ── STR-07: residency of streamed content ───────────────────────────

class ResidencyRules(plugins.RuleEvaluator):
    """SAJHA's residency decisions (the rest allowed), as NetRules makes them for a net."""
    name = 'residency_rules'

    def __init__(self, svc):
        self.svc = svc

    def decide(self, rule, s):
        reg = self.svc.tools_registry
        if rule == 'residency_events':
            return NR.events_decision(s, registry=reg)
        if rule in ('residency_offer', 'residency_arguments', 'residency_result'):
            return NR.decide(self.svc.runtimes[NET].node, rule, s, registry=reg)
        return plugins.Decision(True, rule)


@pytest.fixture
def residency(net2):
    a, b = net2['a'], net2['b']
    a.catalogs.router.rules = ResidencyRules(a)
    b.catalogs.hosts[NET].rules = ResidencyRules(b)
    yield net2
    from sajha.policy.engine import set_engine
    set_engine(None)
    NR.set_settings(None)


def _relayed(net2, args=None):
    ctx, seen = caller()
    r = call(net2['a'], REMOTE, args or {'x': 1}, ctx)
    return r, [n['params'] for n in seen]


def test_str_07_a_classified_tool_streams_numbers_only_at_the_host(residency, monkeypatch):
    # the host's overlay classifies its own ``slow`` results; the home does not know (its rule off)
    NR.set_settings(NR.ResidencySettings(tools={'slow': {'results': {'*': ['confidential']}}}))
    monkeypatch.setattr(residency['a'].catalogs, '_event_rule', lambda name, user: None)
    r, events = _relayed(residency)
    assert r['content'][0]['text'] == 'cust-na:slow:1', r
    assert [e['progress'] for e in events] == [1, 2, 3]
    assert all(set(e) <= {'progressToken', 'progress', 'total'} for e in events), events   # no text, no log
    host = [d for w, d in residency['host_audits'] if w == 'net.host_call'][-1]
    assert host['events'] == 3                                   # the log lines were never signed or sent


def test_str_07_a_tool_named_by_a_residency_rule_streams_numbers_only_at_the_home(residency):
    from tests.net.test_net_residency import use
    use(textwrap.dedent('''
        rules:
          - id: remote-slow-results-stay-home
            match: {tools: ['acme-net__cust-na__*'], flow: results, data_classes: [confidential]}
            effect: deny
    '''))
    r, events = _relayed(residency)
    assert r['content'][0]['text'] == 'cust-na:slow:1', r
    assert [e['progress'] for e in events] == [1, 2, 3]
    assert all('message' not in e for e in events) and all('level' not in e for e in events)
    host = [d for w, d in residency['host_audits'] if w == 'net.host_call'][-1]
    assert host['events'] == 6                                   # the host (no rule names its tool) sent all


def test_str_07_unclassified_tools_stream_as_before(residency):
    r, events = _relayed(residency)
    assert [e.get('message') for e in events if 'progress' in e] == ['cust-na step 1', 'cust-na step 2',
                                                                     'cust-na step 3']
    assert [e['data'] for e in events if 'level' in e] == ['cust-na log 1', 'cust-na log 2', 'cust-na log 3']


def test_str_07_input_responses_are_checked_as_arguments(residency):
    from tests.net.test_net_residency import RULES, use
    use(RULES)
    NR.set_settings(NR.ResidencySettings(tools={'slow': {'arguments': {'customer_id': ['eu-personal']}}}))
    a, conn = residency['a'], residency['conn']
    router = a.catalogs.router
    n = len(conn.mcp)
    out = router.call(REMOTE, {'x': 1}, input_responses={'who': {'action': 'accept',
                                                                 'content': {'customer_id': 'C-991'}}})
    rf = out['_meta'][EXTENSION_ID]['refusal']
    assert out['isError'] and rf['reason'] == 'residency_arguments' and rf['executed'] is False
    assert len(conn.mcp) == n                                    # nothing left this server
    out = router.call(REMOTE, {'x': 1}, input_responses={'ok': {'action': 'accept', 'content': {'note': 'fine'}}})
    assert not out.get('isError'), out
    sent = json.loads(conn.mcp[-1][2])['params']
    assert sent['inputResponses'] == {'ok': {'action': 'accept', 'content': {'note': 'fine'}}}
