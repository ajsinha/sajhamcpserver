# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Input requests (MRTR) and tasks across SAJHA Net (wave 6 phase 6.3; protocol §15.6, CALL-16).

Covers: a host tool that asks two questions in turn reaches the home's 2026-07-28 caller as
``InputRequired``; each answer goes back as a new signed request carrying the host's ``requestState``
(the host carries the earlier answers in it); a state presented by another participant or bound to another
user is refused (``state_invalid``, nothing runs); the home's residency rules see ``inputResponses`` as they
see arguments; a caller that cannot answer (a 2025-11-25 transport, REST) gets the "call it over 2026-07-28"
tool error; an input request relayed through a re-exporting intermediary; and a task-augmented call at the
home wrapping the streamed call (``tasks/cancel`` cancels the tool at the host).
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from sajha.core.mcp_mrtr import InputRequired, elicitation_request, sign_state
from sajha.core.mcp_tool_context import ModernToolContext, TransportToolContext, current_context
from sajha.net import EXTENSION_ID, plugins
from sajha.net.integration.catalogs import STATE_KEY
from sajha.net.routing import mrtr_user
from tests.net import test_net_routing_integration as tri
from tests.net.test_net_routing_integration import Echo, make, node, settle
from tests.net.test_net_streaming import (Slow, StreamConnector, call, isolate, quick, refusal,  # noqa: F401
                                         stream_app_for, tool_of)

NET = 'acme-net'
ASK = 'acme-net__cust-na__ask'
SCHEMA = {'type': 'object', 'properties': {'v': {'type': 'string'}}, 'required': ['v']}


class Ask(Echo):
    """Asks for ``a``, then for ``b`` (keeping a note in its state), then answers with both."""

    def __init__(self, owner, name='ask'):
        super().__init__(name, owner=owner)
        self.runs = 0

    def execute(self, arguments):
        self.runs += 1
        ctx = current_context()
        got = ctx.input_responses
        if 'a' not in got:
            ctx.require_input({'a': elicitation_request('first value?', SCHEMA)})
        if 'b' not in got:
            ctx.require_input({'b': elicitation_request('second value?', SCHEMA)}, {'asked': 'b'})
        return f"{got['a']['content']['v']}+{got['b']['content']['v']}:{ctx.state.get('asked')}"


def answer(v):
    return {'action': 'accept', 'content': {'v': v}}


@pytest.fixture
def net3(tmp_path, monkeypatch):
    """risk-eu (home, founder), cust-na (hosts ``ask`` and ``slow``) and treasury-na, listing ``mrtr``."""
    monkeypatch.setattr(tri, 'app_for', stream_app_for)
    conn = StreamConnector()
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(NET)
    assert node(a).try_join()
    out = {'a': a, 'conn': conn}
    for key, name, tools in (('b', 'cust-na', [Ask('cust-na'), Slow('slow', owner='cust-na')]),
                             ('c', 'treasury-na', [Echo('rates', owner='treasury-na')])):
        s = make(tmp_path, name, conn, tools)
        s.start(run_agents=False)
        tok = a.ca_token(NET, name)
        s.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        assert node(s).try_join()
        out[key] = s
    settle([out['a'], out['b'], out['c']], 5)
    host_audits = []
    out['b'].catalogs.hosts[NET].audit = lambda what, d: host_audits.append((what, d))
    out['host_audits'] = host_audits
    for s in (out['a'], out['b'], out['c']):
        quick(s, progress_min_interval_ms=0)
    yield out
    for s in (out['a'], out['b'], out['c']):
        s.stop()


def ask_round(svc, ctx, args=None, name=ASK):
    """One round as the home's 2026-07-28 responder runs it: InputRequired, or the result."""
    try:
        return call(svc, name, args or {'x': 1}, ctx), None
    except InputRequired as ir:
        return None, ir


def test_mrtr_listed(net3):
    assert 'mrtr' in node(net3['b']).features
    assert 'mrtr' in node(net3['a']).member('cust-na')['record']['features']


def test_two_round_elicitation(net3):
    a, b, conn = net3['a'], net3['b'], net3['conn']
    r, ir = ask_round(a, ModernToolContext())
    assert r is None and list(ir.requests) == ['a']
    assert ir.requests['a']['params']['message'] == 'first value?'
    st = ir.state[STATE_KEY]
    assert st['tool'] == ASK and st['keys'] == ['a'] and isinstance(st['rs'], str)
    # round 2: the answer to "a" goes back with the host's state, as a new signed request
    r, ir2 = ask_round(a, ModernToolContext(input_responses={'a': answer('one')}, state=ir.state))
    assert r is None and list(ir2.requests) == ['b']
    first, second = json.loads(conn.mcp[-2][2]), json.loads(conn.mcp[-1][2])
    assert 'requestState' not in first['params'] and 'inputResponses' not in first['params']
    assert second['params']['requestState'] == st['rs']
    assert second['params']['inputResponses'] == {'a': answer('one')}
    assert conn.mcp[-1][1]['signature'] != conn.mcp[-2][1]['signature']
    # round 3: only "b" is sent; the host kept "a" (and the tool's state) in its own requestState
    r, ir3 = ask_round(a, ModernToolContext(input_responses={'b': answer('two')}, state=ir2.state))
    assert ir3 is None and r['content'][0]['text'] == 'one+two:b', r
    assert r['_meta'][EXTENSION_ID]['instance'] == 'cust-na'
    assert json.loads(conn.mcp[-1][2])['params']['inputResponses'] == {'b': answer('two')}
    assert tool_of(b, 'ask').runs == 3
    outcomes = [d['outcome'] for w, d in net3['host_audits'] if w == 'net.host_call']
    assert outcomes[-3:] == ['input_required', 'input_required', 'ok']


def test_state_presented_by_another_peer_is_refused(net3):
    a, b, c = net3['a'], net3['b'], net3['c']
    _r, ir = ask_round(a, ModernToolContext())
    rs = ir.state[STATE_KEY]['rs']
    runs = tool_of(b, 'ask').runs
    r = c.catalogs.router.call(ASK, {'x': 1}, input_responses={'a': answer('stolen')}, request_state=rs)
    rf = refusal(r)
    assert r.get('isError') and rf['reason'] == 'state_invalid' and rf['side'] == 'host', r
    assert rf['executed'] is False
    assert tool_of(b, 'ask').runs == runs                       # nothing ran


def test_state_bound_to_another_user_is_refused(net3):
    a, b = net3['a'], net3['b']
    # a state this host would have issued to alice at risk-eu, presented for another (here anonymous) user
    rs = sign_state(method='tools/call', target='ask', arguments={'x': 1},
                    user=mrtr_user(NET, 'risk-eu', {'user_id': 'alice'}), responses={}, state={}, round_no=1)
    r = a.catalogs.router.call(ASK, {'x': 1}, input_responses={'a': answer('x')}, request_state=rs)
    assert refusal(r)['reason'] == 'state_invalid', r
    # the same state for the right user, but other arguments, is refused too
    rs2 = sign_state(method='tools/call', target='ask', arguments={'x': 2}, user=mrtr_user(NET, 'risk-eu', None),
                     responses={}, state={}, round_no=1)
    assert refusal(a.catalogs.router.call(ASK, {'x': 1}, request_state=rs2))['reason'] == 'state_invalid'
    assert refusal(a.catalogs.router.call(ASK, {'x': 1}, request_state='not.a-state'))['reason'] == 'state_invalid'
    assert tool_of(b, 'ask').runs == 0


def test_residency_checks_input_responses(net3):
    a, b, conn = net3['a'], net3['b'], net3['conn']
    seen = []

    class NoSecrets(plugins.RuleEvaluator):
        name = 'no_secrets'

        def decide(self, rule, subject):
            if rule == 'residency_arguments':
                seen.append(subject.get('arguments'))
                if 'secret' in json.dumps(subject.get('arguments')):
                    return plugins.Decision(False, 'no_secrets')
            return plugins.Decision(True, 'no_secrets')
    a.catalogs.router.rules = NoSecrets()
    _r, ir = ask_round(a, ModernToolContext())
    sent = len(conn.mcp)
    r, _ = ask_round(a, ModernToolContext(input_responses={'a': answer('secret')}, state=ir.state))
    rf = refusal(r)
    assert r.get('isError') and rf['reason'] == 'residency_arguments' and rf['side'] == 'home', r
    assert len(conn.mcp) == sent                                # the answer never left this server
    assert {'v': 'secret'} in seen


@pytest.mark.parametrize('ctx', [None, 'transport'])
def test_a_caller_that_cannot_answer_gets_the_era_error(net3, ctx):
    a = net3['a']
    tool = a.tools_registry.get_tool(ASK)
    if ctx is None:
        r = tool.execute_with_tracking({'x': 1})                # REST, A2A: no tool context
    else:
        r = call(a, ASK, {'x': 1}, TransportToolContext())       # 2025-11-25: no input requests
    assert r.get('isError') and '2026-07-28' in r['content'][0]['text'], r


def test_task_at_the_home_wraps_the_streamed_call(net3):
    """A task-augmented call at the home runs the remote tool in the task's context: tasks/cancel cancels that
    context, the home closes the stream, the host tool sees is_cancelled()."""
    from sajha.core.mcp_modern import ModernMCPServer
    from sajha.core.mcp_tasks import TaskStore
    a, b = net3['a'], net3['b']
    slow = tool_of(b, 'slow')
    slow.steps, slow.hold = 1, 10

    class Handler:
        def _fixtures(self):
            return None

        def _handle_tools_call(self, params, session, era):
            return a.tools_registry.get_tool(params['name']).execute_with_tracking(params.get('arguments') or {})
    srv = ModernMCPServer.__new__(ModernMCPServer)
    srv.handler = Handler()
    store = TaskStore()

    async def scenario():
        runner = srv._task_runner('acme-net__cust-na__slow', {'name': 'acme-net__cust-na__slow',
                                                              'arguments': {'x': 1}}, {}, None)
        task = store.create(None, runner)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5 and slow.calls == 0:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
        assert task.status == 'working'
        store.cancel(task.task_id, None)
        return task
    task = asyncio.run(scenario())
    assert task.status == 'cancelled'
    assert slow.cancelled.wait(3)                               # the host tool stopped
    assert any(w == 'net.host_call' and d['outcome'] == 'cancelled' for w, d in net3['host_audits'])


def test_input_request_through_a_reexporting_intermediary(tmp_path, isolate, monkeypatch):
    """A <- B <- C, users mapped: C's tool asks; B asks A's caller again under its own requestState (C's
    state inside it); each answer reaches C through B, as alice."""
    from sajha.net.integration import set_service
    from tests.net import test_net_reexport_identity as rx
    from tests.net import test_net_three_instances as t3
    monkeypatch.setattr(rx, 'app_for', stream_app_for)
    monkeypatch.setattr(t3, 'app_for', stream_app_for)
    monkeypatch.setattr(rx, 'Capture', StreamConnector)
    ledger = Ask('treasury-na', 'ledger')
    conn, a, b, c, kid, raw = rx.chain(tmp_path, c_tools=[ledger])
    set_service(a.svc)
    try:
        def rnd(ctx):
            return rx.as_user('alice', raw, kid, lambda: ask_round(a.svc, ctx, {'x': 5}, name='ledger'))
        r, ir = rnd(ModernToolContext())
        assert r is None and list(ir.requests) == ['a'], r
        r, ir = rnd(ModernToolContext(input_responses={'a': answer('1')}, state=ir.state))
        assert r is None and list(ir.requests) == ['b'], r
        r, ir = rnd(ModernToolContext(input_responses={'b': answer('2')}, state=ir.state))
        assert ir is None and r['content'][0]['text'] == '1+2:b', r
        assert ledger.runs == 3
    finally:
        for p in (a, b, c):
            p.svc.stop()


def test_a_dropped_home_closes_the_host_stream_at_once():
    """On ASGI 2.4 servers a dropped home is an error from send(); the host stream is closed then (cancelling
    the tool), not when the suspended body generator is garbage collected."""
    from types import SimpleNamespace
    from sajha.net.plugins import PeerResponse
    from sajha.routes.mcp_routes import _serve_net
    closed = []

    def chunks():
        while True:
            yield b'data: {}\n\n'
    r = PeerResponse(200, {'content-type': 'text/event-stream'}, b'', stream=chunks(), close=lambda: closed.append(1))
    svc = SimpleNamespace(participant=SimpleNamespace(enabled=True, handle_mcp=lambda *a: r))
    request = SimpleNamespace(headers={}, url=SimpleNamespace(scheme='http', path='/mcp', query=''),
                              client=None, method='POST')

    async def scenario():
        resp = await _serve_net(request, b'{}', svc=svc)
        sent = []

        async def send(message):
            sent.append(message)
            if len(sent) > 2:
                raise OSError('the home went away')

        async def receive():
            return {'type': 'http.disconnect'}
        scope = {'type': 'http', 'asgi': {'spec_version': '2.4'}, 'method': 'POST', 'path': '/mcp', 'headers': []}
        try:
            await resp(scope, receive, send)
        except Exception:
            pass
        return closed[:]
    assert asyncio.run(scenario()) == [1]
