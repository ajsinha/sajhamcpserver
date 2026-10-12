# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net agent as a home, and the agent with blocks, residency, re-export, ``assertion`` and
``token_exchange`` (protocol §15.3 to §15.5, §15.9, §16, §17; conformance CALL-07, CALL-13, CALL-14,
CALL-15 and BLK-01 for target A). Several agents in one process, wired by a connector that hands each
request to the agent at its URL; no SAJHA server.

* ``calc-b``: an agent in front of a server with ``add``, ``person`` (an argument marked
  ``eu-personal``) and ``secret`` (a result marked ``confidential``).
* ``home-a``: an agent whose configuration file has users; it serves local clients and calls calc-b.
* ``ledger-c`` and ``desk-d``: for re-export, ledger-c exports ``ledger`` to home-a only, home-a re-exports
  it to desk-d, and desk-d's user calls it through home-a.
"""

import json
import os
import time
from urllib.parse import urlsplit

import pytest

from sajha.net import EXTENSION_ID, conformance, httpsig
from sajha.net.errors import NetError
from sajha.net.library import self_signed
from sajha.net.models import GossipSettings
from sajha.net.plugins import PeerUnreachable
from sajha.net.routing import new_traceparent, trace_of
from sajha.net.trust import FirstUseTrust
from sajhanet_agent import Agent, AgentConfig, CallableMCPClient
from sajhanet_agent.config import ConfigError, parse

NET = 'lab-net'
ALICE = 'alice-key-0123456789abcdef'
BOB = 'bob-key-0123456789abcdef'
DAVE = 'dave-key-0123456789abcdef'


class Wire:
    """Each request goes to the agent at its URL (as the agents' HTTP listeners would pass it)."""

    def __init__(self):
        self.handlers = {}
        self.sent = []

    def send(self, method, url, headers, body, timeout):
        p = urlsplit(url)
        h = self.handlers.get(f'{p.scheme}://{p.netloc}')
        if h is None:
            raise PeerUnreachable(f'{url}: no such agent')
        self.sent.append((url, {k.lower(): v for k, v in headers.items()}))
        return h(method, p.path, p.query, headers, body)

    def to(self, name):
        return [h for u, h in self.sent if u.startswith(f'https://{name}.test') and u.endswith('/mcp')]


def server(tools, seen):
    def handle(msg):
        if 'id' not in msg:
            return None
        m, rid = msg.get('method'), msg['id']
        if m == 'initialize':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                                                           'serverInfo': {'name': 't', 'version': '1'}}}
        if m == 'tools/list':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': tools}}
        if m == 'tools/call':
            name, args = msg['params']['name'], msg['params']['arguments']
            seen.append((name, args))
            if name == 'secret':
                res = {'structuredContent': {'owner': 'x', 'note': 'top secret'},
                       'content': [{'type': 'text', 'text': json.dumps({'owner': 'x', 'note': 'top secret'})}]}
            else:
                res = {'content': [{'type': 'text', 'text': f'{name}:{json.dumps(args, sort_keys=True)}'}]}
            return {'jsonrpc': '2.0', 'id': rid, 'result': res}
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'no'}}
    return handle


OBJ = {'type': 'object', 'properties': {'x': {'type': 'integer'}}}
CALC_TOOLS = [
    {'name': 'add', 'description': 'Add', 'inputSchema': OBJ, 'annotations': {'readOnlyHint': True}},
    {'name': 'person', 'description': 'Look a person up',
     'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'},
                                                      'email': {'type': 'string', 'x-sajha-data-class': 'eu-personal'}}}},
    {'name': 'secret', 'description': 'A secret', 'inputSchema': OBJ,
     'outputSchema': {'type': 'object', 'properties': {'owner': {'type': 'string'},
                                                       'note': {'type': 'string', 'x-sajha-data-class': 'confidential'}}}},
]


def write(path, doc):
    path.write_text(json.dumps(doc))
    t = time.time() + 1 + len(os.listdir(path.parent))
    os.utime(path, (t, t))                       # a new modification time: the agent reads the file again


class Lab:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.wire = Wire()
        self.agents = {}
        self.seen = {}
        self.audit = {}

    def agent(self, name, tools=(), config=None, home=False, founder=False, region='', **kw):
        path = ''
        if config is not None:
            path = self.tmp / f'{name}.json'
            write(path, config)
        seen = self.seen.setdefault(name, [])
        log = self.audit.setdefault(name, [])
        a = Agent(AgentConfig(net=NET, instance=name, url=f'https://{name}.test', founder=founder,
                              seeds=[] if founder else ['https://calc-b.test'], data_dir=str(self.tmp / name),
                              vendor='acme', config_path=str(path), home=home, region=region, **kw),
                  CallableMCPClient(server(list(tools) or [{'name': 'note', 'inputSchema': OBJ}], seen)),
                  connector=self.wire, audit=lambda what, d, log=log: log.append((what, d)),
                  gossip=GossipSettings(gossip_interval_ms=3600000, full_sync_interval_seconds=3600))
        self.wire.handlers[f'https://{name}.test'] = a.handle
        a.start()
        self.agents[name] = a
        return a

    def settle(self, rounds=6):
        for _ in range(rounds):
            for a in self.agents.values():
                a.tick()

    def stop(self):
        for a in self.agents.values():
            a.stop(leave=False)


def client(agent, method, params=None, key=ALICE, rid=1):
    h = {'content-type': 'application/json'}
    if key:
        h['authorization'] = f'Bearer {key}'
    status, _h, body = agent.handle_client('POST', '/mcp', h, json.dumps(
        {'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}}).encode())
    return status, json.loads(body) if body else None


def call(agent, name, args=None, key=ALICE):
    status, out = client(agent, 'tools/call', {'name': name, 'arguments': args or {}}, key=key)
    assert status == 200, out
    return out['result']


def refusal(result):
    assert result.get('isError'), result
    return result['_meta'][EXTENSION_ID]['refusal']


def users(identity=('api_key',), **more):
    doc = {'identity': list(identity), 'users': [
        {'user_name': 'alice', 'roles': ['analyst'], 'keys': [{'id': 'alice-1', 'key': ALICE}]},
        {'user_name': 'bob', 'roles': ['analyst'],
         'keys': [{'id': 'bob-1', 'key': BOB, 'tool_access_mode': 'allowlist', 'tool_access_list': ['note']}]}]}
    doc.update(more)
    return doc


def host_calls(lab, name):
    return [d for what, d in lab.audit[name] if what == 'net.host_call']


@pytest.fixture
def pair(tmp_path):
    lab = Lab(tmp_path)
    lab.agent('calc-b', CALC_TOOLS, config={'identity': ['api_key', 'assertion']}, founder=True, region='us-east')
    lab.agent('home-a', config=users(), home=True, region='eu-west')
    lab.settle()
    yield lab
    lab.stop()


def test_the_configuration_file_is_checked():
    assert parse({}).identity == ['api_key'] and parse({}).import_rules == [{'tools': ['*']}]
    for bad in ({'identity': ['magic']}, {'users': [{'user_name': 'a@b'}]},
                {'users': [{'user_name': 'a', 'keys': [{'id': 'k', 'key': 'x', 'sha256': 'y'}]}]},
                {'blocks': [{'level': 'sideways', 'target_instance': 'x'}]},
                {'residency': {'rules': [{'match': {'flow': 'sideways'}}]}},
                {'residency': {'rules': [{'match': {}, 'effect': 'deny'}]}}, {'surprise': 1}):
        with pytest.raises(ConfigError):
            parse(bad)


def test_a_home_serves_local_clients_and_calls_other_members_tools(pair):
    a, b = pair.agents['home-a'], pair.agents['calc-b']
    # the home publishes its users' keys; the host holds them
    assert b.participant.keys.store.version(NET, 'home-a') >= 1
    assert client(a, 'initialize', {'protocolVersion': '2025-11-25'})[1]['result']['serverInfo']['name'] == \
        'sajhanet-agent'
    names = [t['name'] for t in client(a, 'tools/list')[1]['result']['tools']]
    assert 'note' in names and 'lab-net__calc-b__add' in names and 'add' in names       # own, qualified, plain
    proxy = next(t for t in client(a, 'tools/list')[1]['result']['tools'] if t['name'] == 'lab-net__calc-b__add')
    assert proxy['_meta'][EXTENSION_ID]['instance'] == 'calc-b' and proxy['annotations']['openWorldHint'] is True
    # own tool, qualified name, plain name
    assert call(a, 'note', {'x': 1})['content'][0]['text'] == 'note:{"x": 1}'
    r = call(a, 'lab-net__calc-b__add', {'x': 2})
    assert r['content'][0]['text'] == 'add:{"x": 2}' and r['_meta'][EXTENSION_ID]['instance'] == 'calc-b', r
    assert call(a, 'add', {'x': 3})['content'][0]['text'] == 'add:{"x": 3}'
    last = host_calls(pair, 'calc-b')[-1]
    assert last['user'] == 'alice@home-a' and last['identity'] == 'api_key' and last['key_id'] == 'alice-1'
    assert pair.wire.to('calc-b')[-1]['sajha-net-api-key'] == ALICE
    # the key's tool access is a ceiling, at the home
    assert [t['name'] for t in client(a, 'tools/list', key=BOB)[1]['result']['tools']] == ['note']
    assert call(a, 'lab-net__calc-b__add', {'x': 2}, key=BOB)['isError']
    # no key, or a key that is not one of the agent's
    assert client(a, 'tools/list', key='')[0] == 401
    assert client(a, 'tools/list', key='nope')[0] == 401
    # an agent that is not a home imports nothing
    assert b.status()['home']['remote_tools'] == 0 and not b.participant.book.rows()


def test_assertion_identity_both_ways(pair):
    """CALL-14 (target A): a home that sends assertions; a host that verifies them."""
    a, b = pair.agents['home-a'], pair.agents['calc-b']
    write(pair.tmp / 'home-a.json', users(identity=['assertion']))
    pair.settle(2)
    assert call(a, 'lab-net__calc-b__add', {'x': 5})['content'][0]['text'] == 'add:{"x": 5}'
    h = pair.wire.to('calc-b')[-1]
    assert 'sajha-net-api-key' not in h and h['sajha-net-user-assertion']
    last = host_calls(pair, 'calc-b')[-1]
    assert last['user'] == 'alice@home-a' and last['identity'] == 'assertion' and last['key_id'] == 'alice-1'
    # the host's checks
    user = {'key_id': 'alice-1'}
    tp = new_traceparent()
    good = a.identity.make_assertion(user, 'calc-b', trace_of(tp))
    v = b.identity.verify_assertion(good, 'home-a', audience='calc-b', trace_id=trace_of(tp))
    assert v['name'] == 'alice@home-a' and v['key_id'] == 'alice-1'
    cases = [
        (good, 'home-a', 'calc-b', trace_of(tp)),                                             # replayed
        (a.identity.make_assertion(user, 'other-x'), 'home-a', 'calc-b', None),               # another audience
        (a.identity.make_assertion(user, 'calc-b', trace_of(tp)), 'home-a', 'calc-b', '0' * 32),   # another trace
        (a.identity.make_assertion(user, 'calc-b'), 'desk-x', 'calc-b', None),                # not the sender
        (a.identity.make_assertion(user, 'calc-b', override={'net': 'other-net'}), 'home-a', 'calc-b', None),
        (a.identity.make_assertion(user, 'calc-b', override={'iat': 1, 'exp': 30}), 'home-a', 'calc-b', None),
        (a.identity.make_assertion(user, 'calc-b', override={'user': 'eve@home-a'}), 'home-a', 'calc-b', None),
    ]
    for value, sender, aud, trace in cases:
        with pytest.raises(NetError) as e:
            b.identity.verify_assertion(value, sender, audience=aud, trace_id=trace)
        assert e.value.reason == 'assertion_invalid', (sender, aud)
    # a host that does not list assertion refuses one on a direct call
    write(pair.tmp / 'calc-b.json', {'identity': ['api_key']})
    pair.settle(2)
    assert refusal(call(a, 'lab-net__calc-b__add', {'x': 5}))['reason'] == 'assertion_invalid'


def test_token_exchange_identity_both_ways(pair):
    """CALL-15 (target A): the home exchanges an assertion for a host-scoped token and re-exchanges once
    after the host forgot it; a token presented by another participant is refused."""
    a, b = pair.agents['home-a'], pair.agents['calc-b']
    write(pair.tmp / 'calc-b.json', {'identity': ['token_exchange']})
    write(pair.tmp / 'home-a.json', users(identity=['token_exchange']))
    pair.settle(3)
    assert 'token_exchange' in b.participant.node.features
    assert call(a, 'lab-net__calc-b__add', {'x': 6})['content'][0]['text'] == 'add:{"x": 6}'
    assert call(a, 'lab-net__calc-b__add', {'x': 6})['content'][0]['text'] == 'add:{"x": 6}'
    assert a.identity.exchanges == 1
    h = pair.wire.to('calc-b')[-1]
    assert 'sajha-net-api-key' not in h and 'sajha-net-user-assertion' not in h and h['sajha-net-user-token']
    assert host_calls(pair, 'calc-b')[-1]['identity'] == 'token_exchange'
    for k, _v in list(b.participant.node.kv.scan('tok:')):
        b.participant.node.kv.delete(k)
    assert call(a, 'lab-net__calc-b__add', {'x': 7})['content'][0]['text'] == 'add:{"x": 7}'
    assert a.identity.exchanges == 2
    tok = pair.wire.to('calc-b')[-1]['sajha-net-user-token']
    with pytest.raises(NetError) as e:
        b.identity.resolve({'sajha-net-user-token': tok}, 'desk-x')
    assert e.value.reason == 'token_invalid'
    with pytest.raises(NetError) as e:
        b.identity.resolve({'sajha-net-user-token': tok, 'sajha-net-api-key': ALICE}, 'home-a')
    assert e.value.reason == 'ambiguous_credentials'


def test_blocks_at_the_home_and_at_the_host(pair):
    a, b = pair.agents['home-a'], pair.agents['calc-b']
    # the host: a block on the user, on a tool, on the sending participant
    write(pair.tmp / 'calc-b.json', {'identity': ['api_key'], 'blocks': [
        {'id': 'u1', 'level': 'user', 'user': 'alice@home-a', 'reason': 'test'}]})
    pair.settle(2)
    assert refusal(call(a, 'lab-net__calc-b__add', {'x': 1}))['reason'] == 'user'
    write(pair.tmp / 'calc-b.json', {'identity': ['api_key'], 'blocks': [
        {'id': 't1', 'level': 'tool', 'target_instance': '*', 'tool': 'add', 'direction': 'inbound'}]})
    pair.settle(2)
    assert refusal(call(a, 'lab-net__calc-b__add', {'x': 1}))['reason'] == 'tool'
    write(pair.tmp / 'calc-b.json', {'identity': ['api_key'], 'blocks': [
        {'id': 'i1', 'level': 'inbound', 'target_instance': 'home-a'}]})
    b.tick()                                       # before the home pulls the host's catalog again
    assert refusal(call(a, 'lab-net__calc-b__add', {'x': 1}))['reason'] == 'inbound'
    pair.settle(2)                                 # then the host no longer offers the home anything
    assert not [r for r in a.home.router.rows() if r['host_instance'] == 'calc-b']
    # BLK-01 against the host agent, from outside; the home sees the block naming it
    k, c = self_signed(NET, 'conformance-t', 'conformance.invalid')
    mem = {}
    rep = conformance.run('https://calc-b.test', NET, connector=pair.wire, signer=httpsig.Signer(k, [c]),
                          trust=FirstUseTrust(NET, lambda: mem, mem.__setitem__), ids=['BLK-01', 'CAP-01'])
    assert rep.status('BLK-01') == 'pass' and rep.status('CAP-01') == 'pass', rep.text()
    held = a.participant.node.kv.get('pblocks:calc-b')
    assert held and held['blocks'][0]['target_instance'] == 'home-a'
    write(pair.tmp / 'calc-b.json', {'identity': ['api_key']})
    # the home: an outbound block hides the host's tools and they are not called
    write(pair.tmp / 'home-a.json', users(blocks=[{'id': 'o1', 'level': 'outbound', 'target_instance': 'calc-b'}]))
    pair.settle(2)
    assert 'lab-net__calc-b__add' not in [t['name'] for t in client(a, 'tools/list')[1]['result']['tools']]
    before = len(host_calls(pair, 'calc-b'))
    assert refusal(call(a, 'lab-net__calc-b__add', {'x': 1}))['side'] == 'home'
    assert len(host_calls(pair, 'calc-b')) == before
    write(pair.tmp / 'home-a.json', users(blocks=[{'id': 'o2', 'level': 'tool', 'target_instance': 'calc-b',
                                                   'tool': 'lab-net__calc-b__secret', 'direction': 'outbound'}]))
    pair.settle(2)
    listed = [t['name'] for t in client(a, 'tools/list')[1]['result']['tools']]
    assert 'lab-net__calc-b__add' in listed and 'lab-net__calc-b__secret' not in listed
    assert a.blocks_version() >= 2


def test_residency_at_the_home_and_at_the_host(pair):
    """CALL-07 (target A): arguments refused, held for approval (refused: no approval surface) or redacted at
    the home; a result refused or redacted at the host; the home's rules on a result as it arrives."""
    a, b = pair.agents['home-a'], pair.agents['calc-b']
    deny = {'id': 'eu-stays', 'match': {'data_classes': ['eu-personal'], 'flow': 'arguments',
                                        'destination': {'region': {'ne': 'eu-west'}}}, 'effect': 'deny'}
    write(pair.tmp / 'home-a.json', users(residency={'rules': [deny]}))
    pair.settle(2)
    rf = refusal(call(a, 'lab-net__calc-b__person', {'name': 'Ann', 'email': 'ann@example.eu'}))
    assert rf['reason'] == 'residency_arguments' and rf['side'] == 'home' and rf['executed'] is False
    assert call(a, 'lab-net__calc-b__person', {'name': 'Ann'})['content'][0]['text'] == 'person:{"name": "Ann"}'
    held = dict(deny, effect='require_approval', id='ask-first')
    write(pair.tmp / 'home-a.json', users(residency={'rules': [held]}))
    pair.settle(2)
    r = call(a, 'lab-net__calc-b__person', {'name': 'Ann', 'email': 'ann@example.eu'})
    rf = refusal(r)
    assert rf['reason'] == 'residency_arguments' and 'no approval surface' in rf['detail']
    assert 'no approval surface' in r['content'][0]['text']
    red = {'id': 'mask', 'match': {'data_classes': ['eu-personal'], 'flow': 'arguments'},
           'redact': {'data_classes': ['eu-personal']}}
    write(pair.tmp / 'home-a.json', users(residency={'rules': [red]}))
    pair.settle(2)
    call(a, 'lab-net__calc-b__person', {'name': 'Ann', 'email': 'ann@example.eu'})
    assert pair.seen['calc-b'][-1] == ('person', {'name': 'Ann', 'email': '[REDACTED:eu-personal]'})
    # the host's rules on its result before it leaves
    write(pair.tmp / 'calc-b.json', {'residency': {'rules': [
        {'id': 'secret-stays', 'match': {'data_classes': ['confidential'], 'flow': 'results',
                                         'destination': {'instance': 'home-a'}}, 'effect': 'deny'}]}})
    pair.settle(2)
    rf = refusal(call(a, 'lab-net__calc-b__secret', {'x': 1}))
    assert rf['reason'] == 'residency_result' and rf['executed'] is True and rf['side'] == 'host'
    write(pair.tmp / 'calc-b.json', {'residency': {'rules': [
        {'id': 'mask-secret', 'match': {'data_classes': ['confidential'], 'flow': 'results'},
         'redact': {'data_classes': ['confidential']}}]}})
    pair.settle(2)
    r = call(a, 'lab-net__calc-b__secret', {'x': 1})
    assert r['structuredContent'] == {'owner': 'x', 'note': '[REDACTED:confidential]'}, r
    assert r['_meta'][EXTENSION_ID]['redacted'] == ['note']
    # the home's own rule on the result as it arrives (here)
    write(pair.tmp / 'calc-b.json', {})
    write(pair.tmp / 'home-a.json', users(residency={'rules': [
        {'id': 'no-secrets-here', 'match': {'data_classes': ['confidential'], 'flow': 'results'}, 'effect': 'deny'}]}))
    pair.settle(2)
    rf = refusal(call(a, 'lab-net__calc-b__secret', {'x': 1}))
    assert rf['reason'] == 'residency_result' and rf['side'] == 'home'
    # the catalog states the data classes of the agent's own tools
    entry = next(t for t in b.participant.book.exports(None) if t['name'] == 'secret')
    assert entry['_meta'][EXTENSION_ID]['data_classes'] == {'results': ['confidential']}


def test_reexport_through_an_agent(tmp_path):
    """CALL-13 (target A): ledger-c offers ``ledger`` to home-a only; home-a re-exports it to desk-d with
    ``origin``; desk-d's call carries an assertion for the origin, relayed unchanged by home-a (hop 2,
    visited list), never a raw key."""
    lab = Lab(tmp_path)
    try:
        lab.agent('calc-b', CALC_TOOLS, founder=True)
        lab.agent('ledger-c', [{'name': 'ledger', 'inputSchema': OBJ, 'annotations': {'readOnlyHint': True}}],
                  config={'max_hops': 2}, export_peers=['home-a'])
        a = lab.agent('home-a', config=users(reexport={'enabled': True, 'rules': [
            {'tools': ['ledger'], 'from_instances': ['ledger-c'], 'to_instances': ['desk-d']}]}))
        d = lab.agent('desk-d', config={'users': [{'user_name': 'dave', 'roles': ['analyst'],
                                                   'keys': [{'id': 'dave-1', 'key': DAVE}]}]}, home=True)
        lab.settle(8)
        assert 'reexport' in a.participant.node.features
        assert a.status()['home']['reexported'] == ['ledger']
        listed = [t['name'] for t in client(d, 'tools/list', key=DAVE)[1]['result']['tools']]
        assert 'lab-net__home-a__ledger' in listed and 'lab-net__ledger-c__ledger' not in listed
        r = call(d, 'lab-net__home-a__ledger', {'x': 9}, key=DAVE)
        assert r['content'][0]['text'] == 'ledger:{"x": 9}', r
        assert r['_meta'][EXTENSION_ID]['via']['origin'] == 'ledger-c'
        to_a, to_c = lab.wire.to('home-a')[-1], lab.wire.to('ledger-c')[-1]
        assert to_a['sajha-net-user-assertion'] == to_c['sajha-net-user-assertion']        # relayed unchanged
        assert 'sajha-net-api-key' not in to_a and 'sajha-net-api-key' not in to_c
        assert to_c['sajha-net-hop'] == '2'
        last = host_calls(lab, 'ledger-c')[-1]
        assert last['user'] == 'dave@desk-d' and last['identity'] == 'assertion' and last['hop'] == 2
        assert last['visited'] == ['lab-net/desk-d', 'lab-net/home-a']
        # never offered back to its origin, nor to a peer the rules do not name
        assert 'ledger' not in [t['name'] for t in a.participant.book.exports('ledger-c')]
        assert 'ledger' not in [t['name'] for t in a.participant.book.exports('calc-b')]
    finally:
        lab.stop()


def test_a_restart_keeps_key_record_versions_growing(pair, tmp_path):
    a = pair.agents['home-a']
    v1 = a.participant.keys.own_version()
    assert v1 >= 2
    write(pair.tmp / 'home-a.json', users(users=[{'user_name': 'alice', 'roles': ['analyst'],
                                                  'keys': [{'id': 'alice-1', 'key': ALICE, 'enabled': False}]}]))
    pair.settle(1)
    assert a.participant.keys.own_version() > v1
    path = tmp_path / 'home-a' / 'own_keys.json'
    assert path.exists() and ALICE not in path.read_text()                    # only hashes are kept
