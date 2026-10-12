# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net agent as a home next to a SAJHA instance (protocol §15.5, §15.9; CALL-14 and CALL-15 across
the two implementations): the agent's local user calls a SAJHA tool with a user assertion the agent
signs, mapped by SAJHA to its own account of the same name; a SAJHA user calls the agent's tool with a
host-scoped token the agent issues; the agent hides SAJHA's tools behind an outbound block. The agent's
own cases (blocks, residency, re-export) are in ``sajhanet_agent/tests/test_home.py``.
"""

import json

import pytest

from sajha.net import EXTENSION_ID
from sajha.net.integration import set_service
from sajha.net.models import GossipSettings
from sajhanet_agent import Agent, AgentConfig, CallableMCPClient
from tests.net.test_net_mixed_conformance import MixedConnector, mcp_server
from tests.net.test_net_three_instances import NET, Instance, Who, as_user, isolate, settle  # noqa: F401

KEY = 'desk-alice-0123456789abcdef'


def _client(agent, name, args):
    status, _h, body = agent.handle_client('POST', '/mcp', {'authorization': f'Bearer {KEY}'}, json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}).encode())
    assert status == 200
    return json.loads(body)['result']


@pytest.fixture
def net(tmp_path, isolate):  # noqa: F811
    conn = MixedConnector()
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], founder=True)
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join()
    st = a.svc.authz.nets[NET]
    st.settings.user_identity = 'token_exchange,assertion,api_key'
    a.node.cfg.user_identity = ['token_exchange', 'assertion', 'api_key']
    a.node.extra_features.append('token_exchange')
    a.node.handlers['/sajhanet/v1/token'] = (
        lambda data, v, st=st: a.svc.authz.identity.resolvers['token_exchange'].serve_token(st, data, v))
    a.node.refresh_record()
    a.user('alice', tools='var_calc')
    kid, raw = a.key('alice')
    cfg = tmp_path / 'desk.json'
    cfg.write_text(json.dumps({'identity': ['assertion', 'token_exchange', 'api_key'], 'users': [
        {'user_name': 'alice', 'roles': ['user'], 'keys': [{'id': 'desk-alice', 'key': KEY}]}]}))
    calls = []
    tok = a.svc.ca_token(NET, 'desk-agent')
    agent = Agent(AgentConfig(net=NET, instance='desk-agent', url='https://desk-agent.test',
                              seeds=['https://risk-eu.test'], admission='builtin_ca', ca_url='https://risk-eu.test',
                              token=tok['token'], data_dir=str(tmp_path / 'agent'), vendor='deskco',
                              config_path=str(cfg), home=True),
                  CallableMCPClient(mcp_server([{'name': 'translate', 'description': 'Translate text',
                                                 'inputSchema': {'type': 'object',
                                                                 'properties': {'q': {'type': 'string'}}},
                                                 'annotations': {'readOnlyHint': True}}], calls)),
                  connector=conn, gossip=GossipSettings(gossip_interval_ms=3600000, full_sync_interval_seconds=3600))
    conn.handlers['https://desk-agent.test'] = agent.handle
    agent.start()
    for _ in range(6):
        agent.tick()
        settle([a], 1)
    yield {'a': a, 'agent': agent, 'kid': kid, 'raw': raw, 'calls': calls, 'cfg': cfg}
    agent.stop(leave=False)
    a.svc.stop()


def test_the_agents_user_calls_a_sajha_tool_with_an_assertion(net):
    a, agent = net['a'], net['agent']
    assert 'token_exchange' in agent.participant.node.features
    r = _client(agent, 'acme-net__risk-eu__var_calc', {'x': 4})
    assert r['content'][0]['text'] == 'risk-eu:var_calc:4:as alice', r          # mapped by name at risk-eu
    seen = {s['user']: s['identity'] for s in a.svc.authz.users_view(NET)['seen']}
    assert seen == {'alice@desk-agent': 'assertion'}
    # the plain name reaches it too, and an outbound block at the agent hides it
    assert _client(agent, 'var_calc', {'x': 5})['content'][0]['text'] == 'risk-eu:var_calc:5:as alice'
    doc = json.loads(net['cfg'].read_text())
    doc['blocks'] = [{'id': 'no-risk', 'level': 'outbound', 'target_instance': 'risk-eu'}]
    net['cfg'].write_text(json.dumps(doc))
    import os
    os.utime(net['cfg'], (1e9 + 5, 1e9 + 5))
    agent.tick()
    r = _client(agent, 'acme-net__risk-eu__var_calc', {'x': 4})
    assert r['isError'] and r['_meta'][EXTENSION_ID]['refusal']['side'] == 'home'


def test_a_sajha_user_calls_the_agent_with_a_token(net):
    a, agent = net['a'], net['agent']
    set_service(a.svc)
    tool = a.reg.get_tool('acme-net__desk-agent__translate')
    assert tool is not None
    r = as_user('alice', net['raw'], net['kid'], lambda: tool.execute_with_tracking({'q': 'hola'}))
    assert r['content'][0]['text'] == 'agent:translate:hola', r
    assert agent.participant.node.kv.scan('tok:')                               # a token the agent issued
    tx = a.svc.authz.identity.resolvers['token_exchange']
    assert tx.exchanges == 1
    r = as_user('alice', net['raw'], net['kid'], lambda: tool.execute_with_tracking({'q': 'adios'}))
    assert r['content'][0]['text'] == 'agent:translate:adios' and tx.exchanges == 1
