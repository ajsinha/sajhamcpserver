"""
Planners and LLM tools across SAJHA Net (design §13 and §14; Implementation Plan wave 5, phase 5.1
stream B), on the in-process three-instance net of tests/net/test_net_three_instances.py:

* locality-aware shortlists: local tools first, then remote hosts by preference, region, health and
  latency, each with the reason in words; a restriction to local tools or to one net;
* a planner (Ask SAJHA) on risk-eu answering with a tool on cust-na, as the user;
* an LLM tool of cust-na called from risk-eu: it runs on cust-na's models, its spend is reported back
  and charged there;
* the combined hop and depth limit (``sajhanet.max_call_chain``): a loop risk-eu → cust-na → risk-eu is
  refused at cust-na, a chain over the budget is refused at the home and at the host, and nesting inside
  a forwarded call counts towards it.
"""

import json

import pytest

from sajha.ai import locality
from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.core import inner_calls
from sajha.net import EXTENSION_ID
from sajha.net.integration import set_service
from tests.net.test_net_integration import ClientConnector
from tests.net.test_net_three_instances import NET, Instance, Who, as_user, isolate, settle  # noqa: F401


@pytest.fixture
def llm_runtime(tmp_path):
    from sajha import notices as N
    from sajha.ai.llm_tools import LLMToolSettings, set_settings
    from sajha.ai.llm_tools.config import SpoolSettings
    from sajha.ai.llm_tools.runtime import Runtime, set_runtime
    from sajha.core.state.memory import MemoryStateStore
    N.set_service(N.NoticeService(MemoryStateStore('netllm:'), forward=[]))
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / 'spool')))
    set_settings(s)
    set_runtime(Runtime(s))
    yield
    set_runtime(None)
    set_settings(None)
    N.set_service(None)


def llm_tool(name, allow, registry):
    """An answer-mode LLM tool on the mock model, offering ``allow`` from ``registry``."""
    from sajha.ai.llm_tools import LLMTool
    from tests.ai.conftest import make_gateway
    t = LLMTool({'name': name, 'implementation': 'sajha.ai.llm_tools.LLMTool', 'description': f'{name}: asks a model',
                 'inputSchema': {'type': 'object', 'properties': {'question': {'type': 'string'}},
                                 'required': ['question']},
                 'outputSchema': {'type': 'object', 'properties': {'answer': {'type': 'string'},
                                                                   'stopped_by': {'type': 'string'}}},
                 'llm': {'mode': 'answer', 'tools': {'allow': allow}}})
    gw = make_gateway()
    t.registry, t.gateway = registry, gw
    t.service = IntelligenceService(gw, registry, settings=AskSettings(), audit=lambda e: None)
    return t


def three(tmp_path):
    conn = ClientConnector()
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], founder=True)
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join()
    insts = [a]
    for name, tools in (('cust-na', [Who('lookup', owner='cust-na')]),
                        ('treasury-na', [Who('lookup', owner='treasury-na')])):
        i = Instance(tmp_path, name, conn, tools)
        i.svc.start(run_agents=False)
        tok = a.svc.ca_token(NET, name)
        i.svc.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        assert i.node.try_join()
        insts.append(i)
    perms = 'lookup,var_calc,b_ask,acme-net__risk-eu__var_calc,acme-net__treasury-na__lookup'
    for i in insts:
        i.user('alice', roles=('user',) if i is a else ('analyst',), tools=perms)
    kid, raw = a.key('alice')
    settle(insts, 6)
    return insts, kid, raw


def stop(insts):
    for i in insts:
        i.svc.stop()


# ── locality-aware ranking (no net needed) ──────────────────────────

class _T:
    def __init__(self, name, meta=None):
        self.name, self.meta = name, meta


def _remote(name, inst, **kw):
    return _T(name, dict({'locality': 'remote', 'net': 'acme-net', 'instance': inst, 'host_tool': 'lookup'}, **kw))


def test_ranking_prefers_local_then_near_healthy_hosts_and_says_why(monkeypatch):
    monkeypatch.setattr(locality, '_net_context', lambda: ({'acme-net': 'eu'}, {'lookup': ['acme-net/far']}))
    items = [{'name': n, 'score': 0.5, 'tool': t} for n, t in (
        ('acme-net__slow__lookup', _remote('x', 'slow', region='eu', latency_ms_p50=300)),
        ('acme-net__us__lookup', _remote('x', 'us', region='us')),
        ('acme-net__near__lookup', _remote('x', 'near', region='eu', latency_ms_p50=5)),
        ('acme-net__far__lookup', _remote('x', 'far', region='us')),
        ('acme-net__sick__lookup', _remote('x', 'sick', region='eu', health='degraded')),
        ('acme-net__gone__lookup', _remote('x', 'gone', state='unavailable')),
        ('lookup_local', _T('lookup_local')))]
    out = locality.rank(items)
    names = [x['name'] for x in out]
    assert names[0] == 'lookup_local' and 'acme-net__gone__lookup' not in names
    assert names[1] == 'acme-net__near__lookup'                      # same region, fast
    assert names.index('acme-net__far__lookup') < names.index('acme-net__us__lookup')   # a preference
    assert names[-1] == 'acme-net__sick__lookup'
    why = {x['name']: x['locality']['why'] for x in out}
    assert why['lookup_local'] == 'runs on this server'
    assert 'same region (eu)' in why['acme-net__near__lookup'] and 'about 5 ms' in why['acme-net__near__lookup']
    assert 'preference 1' in why['acme-net__far__lookup'] and 'another region (us; this server eu)' in why['acme-net__us__lookup']
    # restrictions
    assert [x['name'] for x in locality.rank(items, 'local')] == ['lookup_local']
    assert len(locality.rank(items, 'net', 'other-net')) == 1
    assert len(locality.rank(items, 'net', 'acme-net')) == 6
    # a shortlist of local tools only keeps the resolver's order
    plain = [{'name': f't{i}', 'score': s, 'tool': _T('t')} for i, s in enumerate((0.2, 0.9, 0.5))]
    assert [x['name'] for x in locality.rank(plain)] == ['t0', 't1', 't2']


def test_locality_spec_parsing_and_precedence():
    assert locality.parse('local') == ('local', '') and locality.parse('net:acme-net') == ('net', 'acme-net')
    assert locality.parse(None) == ('any', '')
    with pytest.raises(locality.LocalityError):
        locality.parse('nowhere')
    assert locality.resolve_spec(None, {'locality': 'local'}, 'any') == ('local', '', 'planner')
    assert locality.resolve_spec('net:x', {'locality': 'local'}, 'any') == ('net', 'x', 'ask')
    assert locality.resolve_spec(None, {}, 'local') == ('local', '', 'ai.ask.locality')


# ── a planner on risk-eu using tools on cust-na ─────────────────────

def test_a_planner_on_one_instance_uses_a_tool_on_another(tmp_path, isolate):
    from tests.ai.conftest import make_gateway
    insts, kid, raw = three(tmp_path)
    a = insts[0]
    try:
        set_service(a.svc)
        svc = IntelligenceService(make_gateway(), a.reg, settings=AskSettings(), audit=lambda e: None)
        ctx = RequestContext(user_id='alice')
        events = as_user('alice', raw, kid, lambda: list(svc.stream_ask('lookup the value 7', ctx, _objects=True)))
        short = next(e for e in events if e['type'] == 'shortlist')['tools']
        remote = [t for t in short if t['locality']['where'] == 'remote']
        assert remote and all('runs on' in t['locality']['why'] for t in remote)
        res = next(e for e in events if e['type'] == 'done')['result']
        step = res.steps[0]
        assert step.ok and step.net and step.net['instance'] in ('cust-na', 'treasury-na'), res.to_dict()
        assert 'lookup:7:as alice' in step.summary
        # local tools rank first: var_calc is here and on no other instance's shortlist position before it
        r = as_user('alice', raw, kid, lambda: svc.ask('var_calc of 3', ctx))
        assert r.shortlist[0] == 'var_calc'
        # restricted to this server's own tools: no remote tool is offered or called
        r = as_user('alice', raw, kid, lambda: svc.ask('lookup the value 7', ctx, locality='local'))
        assert not any('lookup' in n for n in r.shortlist) and not r.steps
        # restricted to the net: its tools are offered again
        r = as_user('alice', raw, kid, lambda: svc.ask('lookup the value 7', ctx, locality=f'net:{NET}'))
        assert r.steps and r.steps[0].net['net'] == NET
        # the planner option: settings.locality, a reserved setting every planner accepts in an overlay
        local = IntelligenceService(make_gateway(), a.reg, audit=lambda e: None,
                                    settings=AskSettings(planner_config={'react': {'locality': 'local'}}))
        events = as_user('alice', raw, kid, lambda: list(local.stream_ask('lookup the value 7', ctx, _objects=True)))
        ev = next(e for e in events if e['type'] == 'shortlist')
        assert ev['locality'] == {'restrict': 'local', 'by': 'planner'}
        assert not any('lookup' in t['name'] for t in ev['tools'])
        with pytest.raises(Exception, match='locality'):
            IntelligenceService(make_gateway(), a.reg, audit=lambda e: None,
                                settings=AskSettings(planner_config={'react': {'locality': 'mars'}}))
    finally:
        stop(insts)


# ── an LLM tool of cust-na called from risk-eu ──────────────────────

def test_a_remote_llm_tool_runs_on_its_host_and_reports_its_spend(tmp_path, isolate, llm_runtime):
    insts, kid, raw = three(tmp_path)
    a, b = insts[0], insts[1]
    try:
        tool = llm_tool('b_ask', ['lookup'], b.reg)
        b.reg.register_tool(tool)
        b.svc.catalogs.books[NET].invalidate()
        settle(insts, 4)
        assert 'acme-net__cust-na__b_ask' in a.reg.tools
        meta = a.reg.get_tool('acme-net__cust-na__b_ask').meta
        assert meta.get('llm_tool') is True
        seen = []
        a.svc.catalogs.router.audit = lambda what, d: seen.append((what, d))
        set_service(a.svc)
        r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__b_ask').execute_with_tracking(
            {'question': 'lookup the value 4'}))
        assert not r.get('isError'), r
        body = json.dumps(r)
        assert 'cust-na:lookup:4:as alice' in body                   # the inner call ran on cust-na, as alice
        usage = r['_meta'][EXTENSION_ID]['usage']
        assert usage['charged_by'] == 'host' and usage['tokens'] > 0 and usage['models'] == ['mock/mock-planner']
        att = [d for w, d in seen if w == 'net.call_attempt']
        assert att and att[-1]['remote_usage'] == usage                # recorded at the home, not charged there
    finally:
        stop(insts)


def test_remote_llm_tools_can_be_kept_home(tmp_path, isolate, llm_runtime):
    insts, kid, raw = three(tmp_path)
    a, b = insts[0], insts[1]
    try:
        b.svc.catalogs.settings.allow_remote_llm_tools = False
        b.reg.register_tool(llm_tool('b_ask', ['lookup'], b.reg))
        b.svc.catalogs.books[NET].invalidate()
        settle(insts, 4)
        assert 'acme-net__cust-na__b_ask' not in a.reg.tools
    finally:
        stop(insts)


# ── the combined hop and depth limit ────────────────────────────────

def test_a_loop_through_a_remote_llm_tool_is_refused(tmp_path, isolate, llm_runtime):
    insts, kid, raw = three(tmp_path)
    a, b = insts[0], insts[1]
    try:
        b.reg.register_tool(llm_tool('b_ask', ['acme-net__risk-eu__var_calc'], b.reg))
        b.svc.catalogs.books[NET].invalidate()
        settle(insts, 4)
        for i in insts:                              # hops allowed: only the loop rule may stop it
            i.svc.catalogs.router.max_hops = 4
            i.svc.catalogs.hosts[NET].max_hops = 4
        a_calls = a.reg.get_tool('var_calc').calls
        set_service(a.svc)
        r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__b_ask').execute_with_tracking(
            {'question': 'var_calc of 5'}))
        body = json.dumps(r)
        assert 'the call would loop between servers' in body, body     # refused at cust-na, the home of hop 2
        assert a.reg.get_tool('var_calc').calls == a_calls               # risk-eu never ran it
    finally:
        stop(insts)


def test_the_combined_budget_counts_hops_and_nesting(tmp_path, isolate):
    insts, kid, raw = three(tmp_path)
    a, b, c = insts
    try:
        for i in insts:
            i.svc.catalogs.router.max_hops = 4
            i.svc.catalogs.hosts[NET].max_hops = 4
        # at a home serving a forwarded call (hop 1 from risk-eu, depth 1 carried) inside a nested tool:
        # the next call would be hop 2 + depth 3 = 5 > 4
        b.svc.catalogs.router.max_chain = 4
        set_service(b.svc)
        with inner_calls.net_entered(1, [f'{NET}/risk-eu'], 1), inner_calls.entered('outer'), \
                inner_calls.entered('inner'):
            assert inner_calls.outgoing() == ((1, [f'{NET}/risk-eu']), 3)
            r = b.svc.catalogs.call('acme-net__treasury-na__lookup', {'x': 1})
        ref = r['_meta'][EXTENSION_ID]['refusal']
        assert r['isError'] and ref['reason'] == 'chain_limit' and ref['side'] == 'home', r
        assert ref['hops'] == 2 and ref['depth'] == 3 and ref['limit'] == 4
        # the loop rule at the home: cust-na will not send a chain that started at risk-eu back to it
        with inner_calls.net_entered(1, [f'{NET}/risk-eu'], 0):
            r = b.svc.catalogs.call('acme-net__risk-eu__var_calc', {'x': 1})
        assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'loop'
        # by plain name, a host the chain already passed is skipped and the next one answers
        set_service(a.svc)

        def onward():
            with inner_calls.net_entered(1, [f'{NET}/cust-na'], 0):
                return a.svc.catalogs.call('lookup', {'x': 9})
        r = as_user('alice', raw, kid, onward)
        assert [x['outcome'] for x in r['_meta'][EXTENSION_ID]['attempts']] == ['loop', 'answered'], r
        assert r['_meta'][EXTENSION_ID]['instance'] == 'treasury-na'
        # the host checks too: treasury-na allows a chain of 1; risk-eu sends hop 1 with depth 1
        c.svc.catalogs.hosts[NET].max_chain = 1
        set_service(a.svc)

        def nested():
            with inner_calls.entered('outer'):
                return a.svc.catalogs.call('acme-net__treasury-na__lookup', {'x': 2})
        r = as_user('alice', raw, kid, nested)
        ref = r['_meta'][EXTENSION_ID]['refusal']
        assert ref['reason'] == 'chain_limit' and ref['side'] == 'host' and ref['executed'] is False, r
        # nesting inside a forwarded call counts: a tool entered at the host past the budget is refused
        with inner_calls.net_entered(3, ['n/a', 'n/b', 'n/c'], 5):
            with pytest.raises(inner_calls.CallTooDeep, match='sajhanet.max_call_chain'):
                with inner_calls.entered('x'):
                    pass
        # with no forwarded call, only tools.max_call_depth applies, and nothing is carried
        assert inner_calls.outgoing() == (None, 0)
    finally:
        stop(insts)
