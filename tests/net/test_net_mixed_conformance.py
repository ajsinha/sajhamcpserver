# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The wave 5 exit (SAJHA Net design §5.1, phase 8): a mixed net in one process passes the conformance
suite (protocol §20) on all three kinds of participant.

* ``risk-eu``: a SAJHA instance (the founder and CA participant, target S);
* ``vendor-search``: a plain MCP server (a federation upstream of risk-eu) that risk-eu sponsors into
  the net (kind ``sponsored``, sharing risk-eu's URL, reached by ``Sajha-Net-To``);
* ``vendor-agent``: an MCP server fronted by the SAJHA Net agent (kind ``agent``, target A), enrolled
  with a token from risk-eu's CA.

alice of risk-eu calls a tool of each across the net, with her own key verified by each host; the runner
(``sajha.net.conformance``), enrolled as ``conformance``, runs every remote case against each target and
the library cases against the core; no case fails.
"""

import json

import pytest

from sajha.federation.tool import FederatedTool
from sajha.net import EXTENSION_ID, conformance, httpsig
from sajha.net.integration import set_service
from sajha.net.library import enroll
from sajha.net.models import GossipSettings
from sajha.net.plugins import PeerResponse
from sajha.net.trust import CATrust
from sajhanet_agent import Agent, AgentConfig, CallableMCPClient
from tests.net.test_net_integration import ClientConnector
from tests.net.test_net_three_instances import NET, Instance, Who, as_user, isolate, settle  # noqa: F401


class MixedConnector(ClientConnector):
    """TestClients for SAJHA instances, plain handlers for agents."""

    def __init__(self):
        super().__init__()
        self.handlers = {}

    def send(self, method, url, headers, body, timeout):
        from urllib.parse import urlsplit
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        h = self.handlers.get(base)
        if h is not None and base not in self.down:
            return h(method, p.path, p.query, headers, body)
        return super().send(method, url, headers, body, timeout)


class FakeFederation:
    """The federation manager's call surface: the sponsored server answers ``vendor:<tool>:<q>``."""

    def __init__(self):
        self.calls = []

    def call_tool(self, tool, arguments, ctx=None):
        self.calls.append((tool.upstream_name, arguments))
        return {'content': [{'type': 'text', 'text': f'vendor:{tool.upstream_name}:{arguments.get("q")}'}]}


def mcp_server(tools, calls):
    def handle(msg):
        if 'id' not in msg:
            return None
        m, rid = msg.get('method'), msg['id']
        if m == 'initialize':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                                                           'serverInfo': {'name': 'translator', 'version': '1'}}}
        if m == 'tools/list':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': tools}}
        if m == 'tools/call':
            calls.append(msg['params'])
            return {'jsonrpc': '2.0', 'id': rid, 'result': {
                'content': [{'type': 'text', 'text': f'agent:{msg["params"]["name"]}:{msg["params"]["arguments"].get("q")}'}]}}
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'no'}}
    return handle


@pytest.fixture
def mixed(tmp_path, isolate):  # noqa: F811
    conn = MixedConnector()
    fed = FakeFederation()
    search = FederatedTool(fed, 'vendor', 'search', {
        'name': 'vendor__search', 'description': 'Search the vendor index',
        'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string'}}},
        'annotations': {'readOnlyHint': True}})
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu'), search], founder=True)
    a.svc.sponsored_config = [{'net': NET, 'instance_name': 'vendor-search', 'upstream': 'vendor',
                                'vendor': 'vendorco'}]
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join()
    a.user('alice', tools='var_calc,vendor__search')
    kid, raw = a.key('alice')

    calls = []
    tok = a.svc.ca_token(NET, 'vendor-agent')
    agent = Agent(AgentConfig(net=NET, instance='vendor-agent', url='https://vendor-agent.test',
                              seeds=['https://risk-eu.test'], admission='builtin_ca', ca_url='https://risk-eu.test',
                              token=tok['token'], data_dir=str(tmp_path / 'agent'), vendor='translatorco'),
                  CallableMCPClient(mcp_server([{'name': 'translate', 'description': 'Translate text',
                                                 'inputSchema': {'type': 'object',
                                                                 'properties': {'q': {'type': 'string'}}},
                                                 'annotations': {'readOnlyHint': True}}], calls)),
                  connector=conn, gossip=GossipSettings(gossip_interval_ms=3600000, full_sync_interval_seconds=3600))
    conn.handlers['https://vendor-agent.test'] = agent.handle
    agent.start()

    def tick(n=6):
        for _ in range(n):
            agent.tick()
            settle([a], 1)
    tick()
    yield {'a': a, 'agent': agent, 'conn': conn, 'fed': fed, 'calls': calls, 'kid': kid, 'raw': raw, 'tick': tick}
    agent.stop(leave=False)
    a.svc.stop()


def test_mixed_net_members_and_calls(mixed):
    a, agent = mixed['a'], mixed['agent']
    view = {m['name']: (m['state'], m['record'].get('kind'), m['record'].get('sponsor')) for m in a.node.members()}
    assert view == {'vendor-search': ('alive', 'sponsored', 'risk-eu'), 'vendor-agent': ('alive', 'agent', None)}
    seen = {m['name']: m['record']['kind'] for m in agent.participant.node.members()}
    assert seen == {'risk-eu': 'sajha', 'vendor-search': 'sponsored'}
    # the sponsored server's tools, by its own names, are proxies at the sponsor like any member's
    assert {'acme-net__vendor-search__search', 'acme-net__vendor-agent__translate'} <= set(a.reg.tools)
    # the agent holds the sponsor's key records and verifies alice's key itself
    assert agent.participant.keys.store.version(NET, 'risk-eu') >= 1

    set_service(a.svc)
    r = as_user('alice', mixed['raw'], mixed['kid'],
                lambda: a.reg.get_tool('acme-net__vendor-search__search').execute_with_tracking({'q': 'bonds'}))
    assert r['content'][0]['text'] == 'vendor:search:bonds', r
    assert r['_meta'][EXTENSION_ID]['instance'] == 'vendor-search'
    assert mixed['fed'].calls == [('search', {'q': 'bonds'})]
    r = as_user('alice', mixed['raw'], mixed['kid'],
                lambda: a.reg.get_tool('acme-net__vendor-agent__translate').execute_with_tracking({'q': 'hola'}))
    assert r['content'][0]['text'] == 'agent:translate:hola', r
    assert mixed['calls'] == [{'name': 'translate', 'arguments': {'q': 'hola'}}]
    # an anonymous caller crosses to neither
    assert a.reg.get_tool('acme-net__vendor-agent__translate').execute_with_tracking({'q': 'x'}).get('isError')

    # the sponsor's views show the sponsored participant
    sp = a.svc.status()['sponsored']
    assert sp[0]['instance_name'] == 'vendor-search' and sp[0]['running'] and sp[0]['tools'] == ['search']
    from sajha.net.integration import console
    rows = {x['name']: x for x in console.instances_view(None)['nets'][0]['instances']}
    assert rows['vendor-search']['kind'] == 'sponsored' and rows['vendor-search']['sponsor'] == 'risk-eu'
    assert rows['vendor-agent']['kind'] == 'agent'


def test_mixed_net_passes_the_conformance_suite(mixed):
    a, conn = mixed['a'], mixed['conn']
    tok = a.svc.ca_token(NET, 'conformance')
    key, cert, ca = enroll(conn, NET, 'conformance', 'conformance.invalid', 'https://risk-eu.test', tok['token'])
    kw = dict(connector=conn, signer=httpsig.Signer(key, [cert]), trust=CATrust(NET, ca, lambda: None))
    reports = {
        'S': conformance.run('https://risk-eu.test', NET, **kw),
        'sponsored': conformance.run('https://risk-eu.test', NET, instance='vendor-search', **kw),
        'A': conformance.run('https://vendor-agent.test', NET, **kw),
        'L': conformance.run_library(),
    }
    for what, rep in reports.items():
        assert not rep.failed(), f'{what}:\n{rep.text()}'
    assert reports['S'].target['kind'] == 'sajha' and reports['S'].target['code'] == 'S'
    assert reports['sponsored'].target['kind'] == 'sponsored' and reports['sponsored'].target['sponsor'] == 'risk-eu'
    assert reports['A'].target['kind'] == 'agent' and reports['A'].target['code'] == 'A'
    for what in ('S', 'sponsored', 'A'):
        rep = reports[what]
        passed = {r.id for r in rep.results if r.status == conformance.PASS}
        assert {'NET-01', 'CAP-01', 'CAP-02', 'SIG-02', 'SIG-03', 'SIG-06', 'SIG-07', 'SIG-11', 'GOS-01', 'GOS-08',
                'CAT-01', 'CAT-02', 'CAT-03', 'CAT-06', 'CALL-03', 'CALL-05', 'CALL-08', 'FB-01', 'ERR-01',
                'LIM-01'} <= passed, (what, sorted(passed))
        assert len(rep.results) == len(conformance.CASES)
    assert {'KEY-01', 'KEY-03', 'BLK-01'} <= {r.id for r in reports['S'].results if r.status == conformance.PASS}
    lib = {r.id for r in reports['L'].results if r.status == conformance.PASS}
    assert {'NAME-01', 'SIG-01', 'SIG-12', 'SIG-13', 'REC-01', 'REC-02', 'GOS-05', 'KEY-02', 'KEY-03'} <= lib
    # the report is plain data for CI
    assert json.loads(json.dumps(reports['A'].to_dict()))['summary']['fail'] == 0


def test_every_protocol_case_is_listed():
    """Each §20 id appears once in the runner, with the targets the specification gives it."""
    import re
    from pathlib import Path
    spec = Path(__file__).resolve().parents[2] / 'docs' / 'protocol' / 'SAJHA Net Protocol.md'
    rows = re.findall(r'^\| ([A-Z]+-\d+) \| ([SAL ]+)', spec.read_text(encoding='utf-8'), flags=re.M)
    assert rows
    want = {i: ' '.join(t.split()) for i, t in rows}
    got = {c.id: c.targets for c in conformance.CASES}
    assert got == want
    assert len(conformance.CASES) == len(set(c.id for c in conformance.CASES))


def test_sponsoring_through_the_admin_api_and_enrollment(tmp_path, isolate):  # noqa: F811
    """An instance that is not the CA participant sponsors a server: it needs a certificate for it from
    the CA (a token), then the sponsored participant joins; it can be removed again."""
    from sajha.net.integration import ServiceError
    from sajha.net.integration.sponsored import get_sponsorships
    conn = MixedConnector()
    fed = FakeFederation()
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], founder=True)
    a.svc.sponsored_config = []
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join()
    tool = FederatedTool(fed, 'units', 'convert', {'name': 'units__convert', 'inputSchema': {'type': 'object'}})
    b = Instance(tmp_path, 'cust-na', conn, [tool])
    b.svc.sponsored_config = []
    b.svc.start(run_agents=False)
    b.svc.enroll(NET, 'https://risk-eu.test', a.svc.ca_token(NET, 'cust-na')['token'], by='test')
    assert b.node.try_join()
    sp = get_sponsorships(b.svc)
    with pytest.raises(ServiceError):
        sp.add({'net': NET, 'instance_name': 'Bad_Name', 'upstream': 'units'})
    with pytest.raises(ServiceError):                                  # a sponsored entry names its vendor
        sp.add({'net': NET, 'instance_name': 'units-svc', 'upstream': 'units'})
    row = sp.add({'net': NET, 'instance_name': 'units-svc', 'upstream': 'units', 'vendor': 'units'}, by='admin')
    assert not row['running'] and 'enroll it with a token' in row['error']
    sp.enroll(NET, 'units-svc', 'https://risk-eu.test', a.svc.ca_token(NET, 'units-svc')['token'], by='admin')
    row = next(r for r in sp.view() if r['instance_name'] == 'units-svc')
    assert row['running'] and row['tools'] == ['convert'] and row['sponsor'] == 'cust-na'
    for _ in range(5):
        settle([a, b], 1)
    assert {m['name']: m['record']['kind'] for m in a.node.members()} == {'cust-na': 'sajha', 'units-svc': 'sponsored'}
    assert 'acme-net__units-svc__convert' in a.reg.tools
    assert sp.remove(NET, 'units-svc', by='admin') and sp.view() == []
    assert not sp.remove(NET, 'units-svc')
    for _ in range(3):
        settle([a, b], 1)
    assert a.node.member('units-svc')['state'] == 'left'
    a.svc.stop()
    b.svc.stop()
