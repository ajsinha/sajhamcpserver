# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Streamed forwarded calls between SAJHA Net members (Roadmap L17a/L17b, wave 6 phase 6.1; protocol §8.9,
§15.10): in-process SajhaNetService instances whose MCP endpoints answer through a connector that passes a
host's streamed answer through as an iterator (or over the real ``_serve_net`` and ``HttpConnector``).

Covers: progress and log from a host tool relayed to the caller's own tool context (with the caller's
token) before the result; cancellation by the caller closing the stream, seen by the host tool; the idle
timeout and the deadline; heartbeats keeping a quiet call alive; JSON both ways (an old home, an old host,
a host that answers JSON to a stream request, streaming switched off); FB-07 (a verified event makes a
failure "may have run": a read-only tool falls back, a destructive one does not); audit fields on both
sides with one transcript digest; A <- B <- C re-export with C's events re-signed by B and cancellation
reaching C; a federated tool at the host relaying its upstream's progress and cancellation.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from sajha.core.mcp_tool_context import ModernToolContext, is_cancelled, report_log, report_progress
from sajha.net import EXTENSION_ID, httpsig, sse
from sajha.net.plugins import HttpConnector, PeerConnector, PeerResponse, PeerUnreachable
from sajha.net.routing import PeerSettings, StreamSettings
from tests.net import test_net_routing_integration as tri
from tests.net.test_net_routing_integration import Authz, Echo, gossip, make, node, settle  # noqa: F401

NET = 'acme-net'


# ── the wiring ──────────────────────────────────────────────────────

def stream_app_for(svc):
    """A participant's routes, with the MCP endpoint served by the real ``_serve_net`` (it streams)."""
    app = FastAPI()
    app.state.svc = svc

    @app.api_route('/sajhanet/{path:path}', methods=['GET', 'POST'])
    async def ep(request: Request, path: str):
        from sajha.routes.sajhanet_routes import serve
        return await serve(svc, request)

    @app.post('/mcp')
    async def mcp(request: Request):
        from sajha.routes.mcp_routes import _serve_net
        return await _serve_net(request, await request.body(), svc=svc)
    return app


class StreamConnector(PeerConnector):
    """Routes requests to the participants of this process. ``/sajhanet/`` goes over HTTP (TestClient);
    ``/mcp`` calls the participant's handler directly, so a streamed answer is an iterator read while the
    host still runs (``http=True``: over HTTP too, buffered by the TestClient). ``tamper(base, headers, r)``
    may replace an MCP answer; ``mcp`` records every forwarded call (url, headers, body)."""
    name = 'test_stream'

    def __init__(self, http: bool = False):
        self.clients = {}
        self.down = set()
        self.http = http
        self.tamper = None
        self.mcp = []

    def send(self, method, url, headers, body, timeout, stream=False):
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        c = self.clients.get(base)
        if c is None or base in self.down:
            raise PeerUnreachable(f'connection refused: {base}')
        is_mcp = p.path == '/mcp'
        if is_mcp:
            self.mcp.append((url, {k.lower(): v for k, v in headers.items()}, body))
        if is_mcp and not self.http:
            r = c.app.state.svc.participant.handle_mcp(method, p.path, p.query, dict(headers), body or b'', True, '')
            r = r if r is not None else PeerResponse(404, {}, b'')
        elif stream:
            resp = c.send(c.build_request(method, p.path, headers=headers, content=body), stream=True)
            r = PeerResponse(resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, b'',
                             stream=resp.iter_raw(), close=resp.close)
        else:
            resp = c.request(method, p.path + (('?' + p.query) if p.query else ''), headers=headers,
                             content=body if method != 'GET' else None)
            r = PeerResponse(resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.content)
        if is_mcp and self.tamper is not None:
            r = self.tamper(base, {k.lower(): v for k, v in headers.items()}, r)
        return r


class Slow(Echo):
    """Reports ``steps`` progress events (and a log line each), ``delay`` apart, polling ``is_cancelled``;
    then waits for ``gate`` (if set) and answers. ``fail``: raise this exception after the progress."""

    def __init__(self, name='slow', owner='', annotations=None, steps=3, delay=0.0, hold=0.0):
        super().__init__(name, props={'x': {'type': 'integer'}}, annotations=annotations, owner=owner)
        self.steps, self.delay, self.hold = steps, delay, hold
        self.gate = None
        self.fail = None
        self.cancelled = threading.Event()
        self.finished = threading.Event()

    def execute(self, arguments):
        self.calls += 1
        try:
            for i in range(self.steps):
                report_progress(i + 1, self.steps, f'{self.owner} step {i + 1}')
                report_log('info', f'{self.owner} log {i + 1}')
                if self._wait(self.delay):
                    return 'stopped'
            if self.fail is not None:
                raise self.fail
            if self.gate is not None and not self.gate.wait(5):
                return 'gate never opened'
            if self._wait(self.hold):
                return 'stopped'
            return f'{self.owner}:{self.name}:{arguments.get("x")}'
        finally:
            self.finished.set()

    def _wait(self, seconds):
        end = time.monotonic() + seconds
        while True:
            if is_cancelled():
                self.cancelled.set()
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.01)


def caller(token='client-tok', level='info'):
    """The caller's tool context at the home (what a 2026-07-28 client's SSE request installs)."""
    seen = []
    ctx = ModernToolContext(progress_token=token, log_level=level, emit=seen.append)
    return ctx, seen


def call(svc, name, args, ctx):
    tok = ctx.activate()
    try:
        return svc.tools_registry.get_tool(name).execute_with_tracking(args)
    finally:
        ModernToolContext.deactivate(tok)


def refusal(r):
    return (r.get('_meta') or {}).get(EXTENSION_ID, {}).get('refusal') or {}


def quick(svc, **kw):
    """Tune one participant's streaming settings (home and host side)."""
    st = StreamSettings(**{**StreamSettings().__dict__, **kw})
    svc.catalogs.settings.streaming = st
    if svc.catalogs.router is not None:
        svc.catalogs.router.streaming = st
    for h in svc.catalogs.hosts.values():
        h.streaming = st
    return st


@pytest.fixture
def net2(tmp_path, monkeypatch):
    """risk-eu (home, founder), cust-na and treasury-na (hosts), all listing ``streaming``."""
    monkeypatch.setattr(tri, 'app_for', stream_app_for)
    conn = StreamConnector()
    tools_b = [Slow('slow', owner='cust-na', annotations={'readOnlyHint': True}),
               Slow('wipe', owner='cust-na', annotations={'destructiveHint': True})]
    tools_c = [Slow('slow', owner='treasury-na', annotations={'readOnlyHint': True}),
               Slow('wipe', owner='treasury-na', annotations={'destructiveHint': True})]
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(NET)
    assert node(a).try_join()
    out = {'a': a, 'conn': conn}
    for key, name, tools in (('b', 'cust-na', tools_b), ('c', 'treasury-na', tools_c)):
        s = make(tmp_path, name, conn, tools)
        s.start(run_agents=False)
        tok = a.ca_token(NET, name)
        s.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        assert node(s).try_join()
        out[key] = s
    settle([out['a'], out['b'], out['c']], 5)
    audits = []
    a.catalogs.router.audit = lambda what, d: audits.append((what, d))
    out['audits'] = audits
    host_audits = []
    out['b'].catalogs.hosts[NET].audit = lambda what, d: host_audits.append((what, d))
    out['host_audits'] = host_audits
    for s in (out['a'], out['b'], out['c']):
        quick(s, progress_min_interval_ms=0)
    yield out
    for s in (out['a'], out['b'], out['c']):
        s.stop()


def tool_of(svc, name):
    return svc.tools_registry.get_tool(name)


# ── features and the wire ───────────────────────────────────────────

def test_features_listed_and_the_home_asks_for_a_stream(net2):
    a, b, conn = net2['a'], net2['b'], net2['conn']
    for f in ('streaming', 'progress', 'cancellation'):
        assert f in node(b).features
    rec = node(a).member('cust-na')['record']
    assert 'streaming' in rec['features']
    ctx, seen = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 4}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:4', r
    _url, h, body = conn.mcp[-1]
    import json
    sent = json.loads(body)
    assert sent['params']['_meta'][EXTENSION_ID]['stream'] == 1
    assert 'text/event-stream' in h['accept']
    assert sent['params']['_meta']['progressToken'].startswith(r['_meta'][EXTENSION_ID]['trace_id'])
    assert sent['params']['_meta']['io.modelcontextprotocol/logLevel'] == 'info'
    # the caller saw the host's progress under its own token, and the log lines, in order
    prog = [n for n in seen if n['method'] == 'notifications/progress']
    logs = [n for n in seen if n['method'] == 'notifications/message']
    assert [n['params']['progress'] for n in prog] == [1, 2, 3]
    assert all(n['params']['progressToken'] == 'client-tok' for n in prog)
    assert prog[0]['params']['total'] == 3 and prog[0]['params']['message'] == 'cust-na step 1'
    assert [n['params']['data'] for n in logs] == ['cust-na log 1', 'cust-na log 2', 'cust-na log 3']
    assert all(EXTENSION_ID not in (n['params'].get('_meta') or {}) for n in seen)   # no signatures leak to clients
    # one transcript digest on both sides
    att = [d for w, d in net2['audits'] if w == 'net.call_attempt'][-1]
    host = [d for w, d in net2['host_audits'] if w == 'net.host_call'][-1]
    assert att['streamed'] is True and att['events'] == 6 and att['executed'] is True
    assert host['streamed'] is True and host['events'] == 6
    assert att['transcript'] == host['transcript'] and len(att['transcript']) == 64
    assert isinstance(att['first_event_ms'], int)


def test_no_progress_asked_no_progress_sent(net2):
    a, conn = net2['a'], net2['conn']
    ctx, seen = caller(token=None, level=None)
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:1'
    import json
    meta = json.loads(conn.mcp[-1][2])['params']['_meta']
    assert 'progressToken' not in meta and 'io.modelcontextprotocol/logLevel' not in meta
    assert seen == []
    att = [d for w, d in net2['audits'] if w == 'net.call_attempt'][-1]
    assert att['streamed'] is True and att['events'] == 0


def test_progress_reaches_the_caller_before_the_result(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.gate = threading.Event()
    seen_at = []

    def emit(msg):
        seen_at.append(msg)
        slow.gate.set()                    # the host tool answers only once the home relayed its progress
    ctx = ModernToolContext(progress_token='t', emit=emit)
    r = call(a, 'acme-net__cust-na__slow', {'x': 2}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:2', r
    assert seen_at and seen_at[0]['params']['progress'] == 1


def test_cancel_from_the_caller_stops_the_host_tool(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.steps, slow.delay = 1, 0.0
    slow.hold = 10
    ctx, seen = caller()
    threading.Timer(0.4, ctx.cancel).start()
    t0 = time.monotonic()
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert time.monotonic() - t0 < 3
    rf = refusal(r)
    assert r.get('isError') and rf['reason'] == 'cancelled' and rf.get('executed') is None, r
    assert slow.cancelled.wait(3)                              # the host tool saw is_cancelled()
    assert len(r['_meta'][EXTENSION_ID].get('attempts') or [1]) == 1   # never retried elsewhere
    assert any(w == 'net.host_call' and d['outcome'] == 'cancelled' for w, d in net2['host_audits'])


def test_idle_timeout_and_heartbeats(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.steps, slow.hold = 0, 1.2
    quick(a, idle_timeout_seconds=0.5, progress_min_interval_ms=0)
    quick(b, heartbeat_seconds=0.15, progress_min_interval_ms=0)
    ctx, _ = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 3}, ctx)      # quiet for 1.2 s, kept alive by heartbeats
    assert r['content'][0]['text'] == 'cust-na:slow:3', r
    quick(b, heartbeat_seconds=60, progress_min_interval_ms=0)    # no heartbeat: the home gives up
    ctx, _ = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 3}, ctx)
    rf = refusal(r)
    assert rf['reason'] == 'stream_idle' and rf.get('executed') is None, r
    assert rf['retryable'] is True
    assert slow.cancelled.wait(3)
    assert any(w == 'net.stream_refused' and d['reason'] == 'stream_idle' for w, d in net2['audits'])


def test_deadline_ends_a_chatty_stream(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.steps, slow.delay = 400, 0.02                          # progress all along: never idle
    a.catalogs.router.peer = PeerSettings(timeout_seconds=0.8)
    ctx, seen = caller()
    t0 = time.monotonic()
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert time.monotonic() - t0 < 3
    rf = refusal(r)
    assert rf['reason'] == 'timeout' and rf.get('executed') is None, r
    assert seen and slow.cancelled.wait(3)


def test_host_coalesces_progress(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.steps, slow.delay = 30, 0.005
    quick(b, progress_min_interval_ms=1000)
    ctx, seen = caller(level=None)
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:1'
    prog = [n['params']['progress'] for n in seen]
    assert prog[0] == 1 and prog[-1] == 30 and len(prog) < 6     # the first at once, the last before the result


def test_host_drops_events_over_its_limits(net2):
    a, b = net2['a'], net2['b']
    slow = tool_of(b, 'slow')
    slow.steps = 12
    quick(b, max_events=5, progress_min_interval_ms=0)
    ctx, seen = caller(level=None)
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:1'          # within the limit, the home still accepts it
    assert len(seen) == 5
    host = [d for w, d in net2['host_audits'] if w == 'net.host_call'][-1]
    assert host['events'] == 5 and host['dropped'] == 7


# ── JSON both ways ──────────────────────────────────────────────────

def test_old_home_gets_json(net2):
    a, b, conn = net2['a'], net2['b'], net2['conn']
    quick(a, enabled=False)                       # an old home: no stream flag (it still sends Accept: ... SSE)
    seen_r = []
    conn.tamper = lambda base, h, r: seen_r.append(r) or r
    ctx, seen = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 5}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:5'
    assert seen_r[-1].stream is None and seen_r[-1].headers['content-type'].startswith('application/json')
    import json
    assert 'stream' not in json.loads(conn.mcp[-1][2])['params']['_meta'][EXTENSION_ID]
    assert 'text/event-stream' in conn.mcp[-1][1]['accept']
    assert seen == []                             # no progress: only the final answer


def test_old_host_is_not_asked(net2):
    a, b, conn = net2['a'], net2['b'], net2['conn']
    for f in ('streaming', 'progress', 'cancellation'):
        node(b).extra_features.remove(f)
    node(b).refresh_record()
    settle([a, b, net2['c']], 4)
    assert 'streaming' not in node(a).member('cust-na')['record']['features']
    ctx, seen = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 6}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:6'
    import json
    assert 'stream' not in json.loads(conn.mcp[-1][2])['params']['_meta'][EXTENSION_ID]
    assert seen == []


def test_host_may_answer_json_to_a_stream_request(net2):
    a, b = net2['a'], net2['b']
    quick(b, enabled=False)                       # lists streaming (record unchanged) but answers JSON
    ctx, seen = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 7}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:7'
    assert seen == []


def test_connector_without_stream_parameter_gets_json(net2):
    a, conn = net2['a'], net2['conn']

    class Old(PeerConnector):
        def send(self, method, url, headers, body, timeout):
            return conn.send(method, url, headers, body, timeout)
    node(a).connector = Old()
    ctx, _ = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 8}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:8'
    import json
    assert 'stream' not in json.loads(conn.mcp[-1][2])['params']['_meta'][EXTENSION_ID]


# ── FB-07: a verified event means "may have run" ────────────────────

def _cut_after_first_event(base, h, r):
    if r.stream is None or base != 'https://cust-na.test':
        return r
    p = sse.Parser()
    src = r.stream

    def gen():
        for chunk in src:
            for typ, data in p.feed(chunk):
                if typ == 'event':
                    yield sse.encode(sse.loads_event(data))
                    return                                  # the connection drops after one event
    return PeerResponse(r.status, r.headers, b'', stream=gen(), close=r.close)


def test_fb07_read_only_falls_back_destructive_does_not(net2):
    a, b, c, conn = net2['a'], net2['b'], net2['c'], net2['conn']
    conn.tamper = _cut_after_first_event
    ctx, seen = caller(level=None)
    r = call(a, 'slow', {'x': 1}, ctx)                          # plain name: cust-na first, then treasury-na
    assert r['content'][0]['text'] == 'treasury-na:slow:1', r
    att = r['_meta'][EXTENSION_ID]['attempts']
    assert [(x['host'], x['outcome'], x['executed']) for x in att] == [
        ('cust-na', 'stream_truncated', None), ('treasury-na', 'answered', True)]
    ctx, seen = caller(level=None)
    r = call(a, 'wipe', {'x': 1}, ctx)
    rf = refusal(r)
    assert rf['reason'] == 'stream_truncated' and rf.get('executed') is None, r
    assert tool_of(c, 'wipe').calls == 0                        # may have run at cust-na: never repeated


def test_fb07_a_refusal_after_events_may_have_run(net2):
    from sajha.policy.errors import PolicyDenied
    a, b, c = net2['a'], net2['b'], net2['c']
    tool_of(b, 'slow').fail = PolicyDenied('no', tool='slow')
    tool_of(b, 'wipe').fail = PolicyDenied('no', tool='wipe')
    ctx, seen = caller(level=None)
    r = call(a, 'slow', {'x': 2}, ctx)
    assert r['content'][0]['text'] == 'treasury-na:slow:2', r
    att = r['_meta'][EXTENSION_ID]['attempts']
    assert (att[0]['outcome'], att[0]['executed']) == ('policy', None)
    ctx, _ = caller(level=None)
    r = call(a, 'wipe', {'x': 2}, ctx)
    rf = refusal(r)
    assert rf['reason'] == 'policy' and rf['executed'] is None and tool_of(c, 'wipe').calls == 0, r
    # with no event before it, the same refusal stays executed: false (the first host's answer, §15.8 rule 2)
    tool_of(b, 'wipe').steps = 0
    ctx, _ = caller(level=None)
    r = call(a, 'wipe', {'x': 2}, ctx)
    rf = refusal(r)
    assert rf['reason'] == 'policy' and rf['executed'] is False, r


# ── over HTTP: _serve_net and HttpConnector ─────────────────────────

def test_over_http_with_serve_net_and_http_connector(net2):
    a, conn = net2['a'], net2['conn']
    http = HttpConnector()
    http._clients.update(conn.clients)              # TestClients are httpx clients: the real connector code runs
    node(a).connector = http
    ctx, seen = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 9}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:9', r
    assert [n['params']['progress'] for n in seen if n['method'] == 'notifications/progress'] == [1, 2, 3]
    att = [d for w, d in net2['audits'] if w == 'net.call_attempt'][-1]
    assert att['streamed'] is True and att['events'] == 6


def test_serve_net_streams_signed_headers(net2):
    a, b, conn = net2['a'], net2['b'], net2['conn']
    conn.http = True
    raw_seen = []

    def keep(base, h, r):
        if r.stream is None:
            return r
        body = b''.join(r.stream)
        raw_seen.append((r, body))
        return PeerResponse(r.status, r.headers, b'', stream=iter([body]), close=r.close)
    conn.tamper = keep
    ctx, _ = caller()
    r = call(a, 'acme-net__cust-na__slow', {'x': 1}, ctx)
    assert r['content'][0]['text'] == 'cust-na:slow:1'
    resp, body = raw_seen[-1]
    assert resp.headers['content-type'].startswith('text/event-stream')
    assert 'content-digest' not in resp.headers and '"content-type"' in resp.headers['signature-input']
    items = [sse.loads_event(d) for t, d in sse.parse_all(body) if t == 'event']
    sigs = [i['params']['_meta'][EXTENSION_ID]['event_signature']['seq'] for i in items[:-1]]
    assert sigs == list(range(1, len(items)))
    final = items[-1]
    st = final['result']['_meta'][EXTENSION_ID]['stream']
    assert st['seq'] == len(items) and 'response_signature' in final['result']['_meta'][EXTENSION_ID]


# ── A <- B <- C ─────────────────────────────────────────────────────

def test_reexport_chain_re_signs_and_cancels(tmp_path, isolate, monkeypatch):
    from tests.net import test_net_reexport_identity as rx
    from tests.net import test_net_three_instances as t3
    from sajha.net.integration import set_service
    monkeypatch.setattr(rx, 'app_for', stream_app_for)
    monkeypatch.setattr(t3, 'app_for', stream_app_for)
    monkeypatch.setattr(rx, 'Capture', StreamConnector)
    ledger = Slow('ledger', owner='treasury-na', steps=2)
    conn, a, b, c, kid, raw = rx.chain(tmp_path, c_tools=[ledger])
    for p in (a, b, c):
        quick(p.svc, progress_min_interval_ms=0)
    b_audits, c_audits = [], []
    b.svc.catalogs.hosts[rx.M].audit = lambda w, d: b_audits.append((w, d))
    b.svc.catalogs.router.audit = lambda w, d: b_audits.append((w, d))
    c.svc.catalogs.hosts[rx.M].audit = lambda w, d: c_audits.append((w, d))
    set_service(a.svc)
    ctx, seen = caller()
    r = rx.as_user('alice', raw, kid, lambda: call(a.svc, 'ledger', {'x': 5}, ctx))
    assert r['content'][0]['text'] == 'treasury-na:ledger:5', r
    prog = [n['params'] for n in seen if n['method'] == 'notifications/progress']
    assert [p['progress'] for p in prog] == [1, 2] and all(p['progressToken'] == 'client-tok' for p in prog)
    assert [n['params']['data'] for n in seen if n['method'] == 'notifications/message'] == \
        ['treasury-na log 1', 'treasury-na log 2']
    # B verified C's stream, re-signed the events into its own stream to A; both transcripts audited at B
    b_host = [d for w, d in b_audits if w == 'net.host_call'][-1]
    b_home = [d for w, d in b_audits if w == 'net.call_attempt'][-1]
    c_host = [d for w, d in c_audits if w == 'net.host_call'][-1]
    assert b_home['events'] == 4 and b_host['events'] == 4 and b_home['trace_id'] == b_host['trace_id']
    assert b_home['transcript'] == c_host['transcript'] and b_host['transcript'] != c_host['transcript']

    # a tampered C -> B event is refused at B; A gets B's answer naming the refusal
    def forge(base, h, resp):
        if resp.stream is None or base != 'https://treasury-na.test':
            return resp
        p = sse.Parser()
        src = resp.stream

        def gen():
            for chunk in src:
                for typ, data in p.feed(chunk):
                    if typ != 'event':
                        continue
                    ev = sse.loads_event(data)
                    if 'method' in ev:
                        ev['params']['message'] = 'forged'
                    yield sse.encode(ev)
        return PeerResponse(resp.status, resp.headers, b'', stream=gen(), close=resp.close)
    conn.tamper = forge
    ctx, seen = caller()
    r = rx.as_user('alice', raw, kid, lambda: call(a.svc, 'ledger', {'x': 6}, ctx))
    assert r.get('isError'), r
    rf = refusal(r)
    assert rf['reason'] == 'event_invalid' and rf['instance'] == 'cust-na' and rf['side'] == 'home', r
    assert not [n for n in seen if 'forged' in str(n)]
    assert any(w == 'net.stream_refused' and d['reason'] == 'event_invalid' for w, d in b_audits)

    # cancellation at A reaches C
    conn.tamper = None
    ledger.steps, ledger.hold = 1, 10
    ledger.cancelled.clear()
    ctx, seen = caller()
    threading.Timer(0.5, ctx.cancel).start()
    t0 = time.monotonic()
    r = rx.as_user('alice', raw, kid, lambda: call(a.svc, 'ledger', {'x': 7}, ctx))
    assert refusal(r)['reason'] == 'cancelled' and time.monotonic() - t0 < 3, r
    assert ledger.cancelled.wait(3)
    for p in (a, b, c):
        p.svc.stop()


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    from tests.net.test_net_three_instances import isolate as iso
    gen = iso.__wrapped__(tmp_path, monkeypatch)
    next(gen)
    yield
    try:
        next(gen)
    except StopIteration:
        pass


# ── a federated tool at the host ────────────────────────────────────

class Fed(Echo):
    """A host tool that runs a federated (proxied MCP server) tool: its upstream's events reach the net."""

    def __init__(self, name, target, owner='cust-na'):
        super().__init__(name, props={'steps': {'type': 'integer'}, 'seconds': {'type': 'number'}},
                         annotations={'readOnlyHint': True}, owner=owner)
        self.target = target
        self.registry = None

    def execute(self, arguments):
        self.calls += 1
        return self.registry.tools[self.target].execute(dict(arguments))


def test_federated_tool_at_the_host_relays_upstream_progress_and_cancel(tmp_path, monkeypatch):
    pytest.importorskip('mcp')
    pytest.importorskip('uvicorn')
    from tests.test_federation import Registry as FedRegistry, Upstream
    from sajha.federation.config import FederationSettings
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    up = Upstream()
    m = None
    try:
        settings = FederationSettings(**{'enabled': True, 'allow_localhost': True, 'require_approval': False,
                                         'startup_wait_seconds': 10, 'default_timeout_seconds': 10,
                                         'upstreams': [{'id': 'units', 'url': up.url}]})
        freg = FedRegistry()
        m = FederationManager(freg, settings, FederationStore(str(tmp_path / 'fed.json')))
        m.start()
        assert 'units__countdown' in freg.tools
        monkeypatch.setattr(tri, 'app_for', stream_app_for)
        conn = StreamConnector()
        countdown, linger = Fed('countdown', 'units__countdown'), Fed('linger', 'units__linger')
        for t in (countdown, linger):
            t.registry = freg
        a = make(tmp_path, 'risk-eu', conn, [], founder=True)
        a.start(run_agents=False)
        a.ca_init(NET)
        assert node(a).try_join()
        b = make(tmp_path, 'cust-na', conn, [countdown, linger])
        b.start(run_agents=False)
        b.enroll(NET, 'https://risk-eu.test', a.ca_token(NET, 'cust-na')['token'], by='test')
        assert node(b).try_join()
        settle([a, b], 5)
        quick(b, progress_min_interval_ms=0)
        ctx, seen = caller(level=None)
        r = call(a, 'acme-net__cust-na__countdown', {'steps': 3}, ctx)
        assert 'lift-off' in r['content'][0]['text'], r
        prog = [n['params'] for n in seen if n['method'] == 'notifications/progress']
        assert [p['progress'] for p in prog] == [1, 2, 3] and all(p['progressToken'] == 'client-tok' for p in prog)
        assert prog[0]['message'] == '2 to go'
        # cancellation at the home reaches the upstream server
        before = up.calls.get('cancelled', 0)
        ctx, _ = caller(level=None)
        threading.Timer(0.5, ctx.cancel).start()
        r = call(a, 'acme-net__cust-na__linger', {'seconds': 10}, ctx)
        assert refusal(r)['reason'] == 'cancelled', r
        deadline = time.time() + 5
        while up.calls.get('cancelled', 0) == before and time.time() < deadline:
            time.sleep(0.05)
        assert up.calls.get('cancelled', 0) == before + 1
        a.stop()
        b.stop()
    finally:
        if m is not None:
            m.stop()
        up.stop()


# ── the signed parts in isolation ───────────────────────────────────

def test_event_chain_round_trip_and_transcript():
    from sajha.net import crypto
    key = crypto.generate_key()
    cert = crypto.self_signed_certificate(key, NET, 'cust-na', 'cust-na.test')
    signer = httpsig.Signer(key, [cert])
    req_sig = b'\x01' * 64
    host, home = httpsig.EventChain(req_sig), httpsig.EventChain(req_sig)
    evs = [host.sign_event(signer, {'jsonrpc': '2.0', 'method': 'notifications/progress',
                                    'params': {'progressToken': 't', 'progress': i}}) for i in (1, 2)]
    for e in evs:
        assert home.verify_event(cert, e)
    final = httpsig.sign_message(signer, host.close({'jsonrpc': '2.0', 'id': 1, 'result': {'content': []}}), 'n' * 22)
    assert final['result']['_meta'][EXTENSION_ID]['stream']['seq'] == 3
    assert home.verify_close(final) and httpsig.verify_message(final, 'n' * 22, cert)
    assert home.transcript == host.transcript
    other = httpsig.EventChain(b'\x02' * 64)                 # another request's chain
    assert other.check_event(cert, evs[0]) == 'event_invalid'
    fresh = httpsig.EventChain(req_sig)
    assert fresh.check_event(cert, evs[1]) == 'event_order'
