# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Re-export with hop limits, the ``assertion`` and ``token_exchange`` identity resolvers, and the topology
view's data (Implementation Plan wave 5, phase 5.2 stream C; design §10.2, §14, §17; protocol §15.5, §15.9,
§16), on in-process SajhaNetService instances talking over HTTP (TestClient) as in
tests/net/test_net_three_instances.py.

* Re-export within one net (CALL-13): treasury-na exports ``ledger`` only to cust-na, cust-na re-exports it
  to risk-eu with ``origin``; risk-eu's call carries a user assertion for the origin, cust-na relays it
  unchanged with hop 2 and the visited list, never a raw key; hop limits at the intermediary and at the
  origin; loops refused, in the catalog (a tool never comes back to its origin) and on a call; an expired,
  replayed, other-net or other-audience assertion is ``-32013 assertion_invalid``.
* A bridge between two nets (NET-05): cust-na in acme-net and beta-net offers ``ledger`` of acme-net into
  beta-net as its own only with re-export on for beta-net, and calls into acme-net as its own mapped user
  with an assertion it signs there.
* ``assertion`` and ``token_exchange`` as a net's resolver, end to end with their refusals.
* ``GET /api/sajhanet/topology``'s data.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sajha.core.state.memory import MemoryStateStore
from sajha.core.storage import LocalStorageBackend
from sajha.db.schema import create_sqlite
from sajha.net import EXTENSION_ID, crypto
from sajha.net.integration import SajhaNetService, set_service
from sajha.net.integration import authz as az
from sajha.net.integration import identity as ni
from sajha.net.integration.catalogs import CatalogSettings, NetCatalogs
from sajha.net.integration.config import Shared
from sajha.net.models import CASettings, IdentitySettings, NetConfig, PeerCacheSettings
from sajha.net.routing import new_traceparent, trace_of
from sajha.observability.caller import current
from tests.net.test_net_integration import ClientConnector
from tests.net.test_net_routing_integration import Echo, Registry, app_for, gossip
from tests.net.test_net_three_instances import Instance, as_user, isolate  # noqa: F401

M = 'acme-net'
N = 'beta-net'
PERMS = 'lookup,var_calc,ledger,bounce,acme-net__treasury-na__ledger,acme-net__risk-eu__var_calc'


class Who(Echo):
    def execute(self, arguments):
        self.calls += 1
        return f'{self.owner}:{self.name}:{arguments.get("x")}:as {current().user_id}'


class Bounce(Echo):
    """A tool that calls a remote tool of risk-eu through this server's catalogs (a chain going back)."""

    def execute(self, arguments):
        self.calls += 1
        cat = self.svc.catalogs
        out = cat.call('acme-net__risk-eu__var_calc', {'x': arguments.get('x')})
        return json.dumps(out.get('_meta', {}).get(EXTENSION_ID, {}).get('refusal') or out.get('content'))


class Capture(ClientConnector):
    """Records every forwarded tools/call (URL and headers)."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, method, url, headers, body, timeout):
        h = {k.lower(): v for k, v in headers.items()}
        if url.endswith('/mcp') and h.get('mcp-method') == 'tools/call':
            self.sent.append((url, h))
        return super().send(method, url, headers, body, timeout)

    def to(self, host):
        return [h for u, h in self.sent if u.startswith(f'https://{host}.test')]


class Peer(Instance):
    """An instance in one or more nets, with its own identity and catalog settings per net."""

    def __init__(self, tmp, name, conn, tools, nets, auth=None, cat=None):
        # nets: [(net, founder, seeds)]
        self.name = name
        d = tmp / name
        d.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f'sqlite:///{tmp / (name + ".db")}')
        create_sqlite(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        s = Shared(enabled=True, data_dir=str(d), gossip=gossip())
        cfgs = []
        for net, founder, seeds in nets:
            nd = d / net
            nd.mkdir(exist_ok=True)
            cfgs.append(NetConfig(
                name=net, instance_name=name, founder=founder, seeds=list(seeds), base_url=f'https://{name}.test',
                gossip=gossip(),
                identity=IdentitySettings(cert_ref=f'file:{nd}/instance.crt', key_ref=f'file:{nd}/instance.key',
                                          ca_ref=f'file:{nd}/ca.pem', revocation_list_ref=f'file:{nd}/revoked.json'),
                ca=CASettings(enabled=founder, key_ref=f'file:{nd}/ca.key', cert_ref=f'file:{nd}/ca.pem'),
                peer_cache=PeerCacheSettings(path=str(nd / 'peers.json'))))
        self.nets = [n for n, _f, _s in nets]
        self.svc = svc = SajhaNetService(s, cfgs, {}, store=MemoryStateStore(), connector=conn,
                                         documents=LocalStorageBackend(str(d)))
        svc.tools_registry = Registry()
        for t in tools:
            t.svc = svc
            svc.tools_registry.register_tool(t)
        base = {'export': [{'tools': ['*']}], 'import_': [{'tools': ['*']}]}
        svc.authz = az.NetAuthz(svc, db_factory=self.Session, engine=self.engine, persistent=lambda: [],
                                settings={n: az.NetAuthSettings(**dict(base, **((auth or {}).get(n) or {})))
                                          for n in self.nets})
        svc.catalogs = NetCatalogs(svc, settings=cat or CatalogSettings(), registry=svc.tools_registry)
        conn.clients[f'https://{name}.test'] = TestClient(app_for(svc), base_url=f'https://{name}.test')

    def n(self, net=M):
        return self.svc.runtimes[net].node

    @property
    def node(self):
        return self.n(self.nets[0])


def settle(peers, rounds=6):
    for _ in range(rounds):
        for p in peers:
            for net in p.nets:
                nd = p.svc.runtimes[net].node
                if nd is not None and f'https://{p.name}.test' not in p.svc.connector.down:
                    nd.tick()
        for p in peers:
            p.svc.catalogs.maybe_sync()


def join(founder, others, net=M):
    founder.svc.ca_init(net)
    assert founder.n(net).try_join()
    for o in others:
        tok = founder.svc.ca_token(net, o.name)
        o.svc.enroll(net, f'https://{founder.name}.test', tok['token'], by='test')
        assert o.n(net).try_join(), o.svc.runtimes[net].error


def start(*peers):
    for p in peers:
        p.svc.start(run_agents=False)


def decode(value):
    return json.loads(crypto.unb64url(value).decode())


# ── re-export within one net (CALL-13) ──────────────────────────────

def chain(tmp_path, b_cat=None, c_cat=None, c_tools=None):
    """risk-eu (a) <- cust-na (b) <- treasury-na (c): c exports ledger only to b; b re-exports it to a."""
    conn = Capture()
    c = Peer(tmp_path, 'treasury-na', conn, c_tools or [Who('ledger', owner='treasury-na')], [(M, True, [])],
             auth={M: {'export': [{'tools': ['*'], 'to_instances': ['cust-na']}]}},
             cat=c_cat or CatalogSettings(max_hops=2))
    b = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na')], [(M, False, ['https://treasury-na.test'])],
             cat=b_cat or CatalogSettings(max_hops=2, reexport=True, reexport_rules=[{'tools': ['ledger', 'bounce']}]))
    a = Peer(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], [(M, False, ['https://treasury-na.test'])])
    start(c, b, a)
    join(c, [b, a])
    for p in (a, b, c):
        p.user('alice', roles=('analyst',), tools=PERMS)
    kid, raw = a.key('alice')
    settle([a, b, c])
    return conn, a, b, c, kid, raw


def test_reexport_within_one_net_carries_an_assertion_for_the_origin(tmp_path, isolate):
    conn, a, b, c, kid, raw = chain(tmp_path)
    # c's catalog for a does not hold ledger; b re-exports it with its origin and c's contract
    assert 'acme-net__treasury-na__ledger' not in a.reg.tools
    q = 'acme-net__cust-na__ledger'
    assert q in a.reg.tools and 'ledger' in a.reg.tools
    meta = a.reg.get_tool(q).meta
    assert meta['origin'] == 'treasury-na'
    c_hash = [t for t in c.svc.catalogs.books[M].exports('cust-na') if t['name'] == 'ledger'][0]['_meta'][EXTENSION_ID]
    assert meta['contract_hash'] == c_hash['contract_hash']
    assert 'reexport' in b.node.features
    assert all(t['name'] != 'ledger' for t in b.svc.catalogs.books[M].exports('treasury-na'))   # never back to its host

    set_service(a.svc)
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('ledger').execute_with_tracking({'x': 5}))
    assert r['content'][0]['text'] == 'treasury-na:ledger:5:as alice', r
    assert r['_meta'][EXTENSION_ID]['instance'] == 'cust-na'
    # home -> intermediary: an assertion for the origin, no raw key
    h1 = conn.to('cust-na')[-1]
    assert 'sajha-net-api-key' not in h1 and h1['sajha-net-hop'] == '1'
    s1 = decode(h1['sajha-net-user-assertion'])
    assert (s1['aud'], s1['iss'], s1['net'], s1['user']) == ('treasury-na', 'risk-eu', M, 'alice@risk-eu')
    # intermediary -> origin: the same assertion, unchanged, hop 2, the visited list; never a key
    h2 = conn.to('treasury-na')[-1]
    assert 'sajha-net-api-key' not in h2 and h2['sajha-net-hop'] == '2'
    assert h2['sajha-net-user-assertion'] == h1['sajha-net-user-assertion']
    assert h2['sajha-net-visited'] == '"acme-net/risk-eu", "acme-net/cust-na"'
    assert trace_of(h2['traceparent']) == s1['trace_id']
    seen = {s['user']: s for s in c.svc.authz.users_view(M)['seen']}
    assert seen['alice@risk-eu']['identity'] == 'assertion' and seen['alice@risk-eu']['mapping'] == 'name'
    for p in (a, b, c):
        p.svc.stop()


def test_hop_limits_at_the_intermediary_and_at_the_origin(tmp_path, isolate):
    conn, a, b, c, kid, raw = chain(tmp_path)
    set_service(a.svc)
    call = lambda: as_user('alice', raw, kid, lambda: a.reg.get_tool('ledger').execute_with_tracking({'x': 1}))  # noqa
    c.svc.catalogs.hosts[M].max_hops = 1                       # the origin accepts direct calls only
    r = call()
    rf = r['_meta'][EXTENSION_ID]['refusal']
    assert r.get('isError') and rf['reason'] == 'hop_limit' and rf['executed'] is False, r
    assert rf.get('refused_by') == 'treasury-na'
    c.svc.catalogs.hosts[M].max_hops = 2
    b.svc.catalogs.router.max_hops = 1                         # the intermediary may not forward a second hop
    sent = len(conn.to('treasury-na'))
    r = call()
    assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'hop_limit', r
    assert len(conn.to('treasury-na')) == sent                 # refused at cust-na before sending
    b.svc.catalogs.router.max_hops = 2
    assert call()['content'][0]['text'].startswith('treasury-na:ledger:1')
    # the combined chain budget still bounds it end to end
    b.svc.catalogs.router.max_chain = 1
    assert call()['_meta'][EXTENSION_ID]['refusal']['reason'] == 'chain_limit'
    for p in (a, b, c):
        p.svc.stop()


def test_loops_are_refused_in_the_catalog_and_on_a_call(tmp_path, isolate):
    bounce = Bounce('bounce', owner='treasury-na')
    conn, a, b, c, kid, raw = chain(
        tmp_path, c_cat=CatalogSettings(max_hops=3, reexport=True, reexport_rules=[{'tools': ['*']}]),
        b_cat=CatalogSettings(max_hops=3, reexport=True, reexport_rules=[{'tools': ['*']}]),
        c_tools=[Who('ledger', owner='treasury-na'), bounce])
    # c also re-exports everything, but never a tool whose origin is itself or a tool back to its host
    for t in c.svc.catalogs.books[M].exports('cust-na'):
        assert (t['_meta'][EXTENSION_ID].get('origin') or 'treasury-na') not in ('cust-na',)
    rows = c.svc.catalogs.router.rows()
    assert not [r for r in rows if r['entry']['meta'].get('origin') == 'treasury-na']   # own tools never come back
    assert 'acme-net__cust-na__bounce' in a.reg.tools
    # a -> b -> c, and c's tool calls a: c refuses to send the chain back to an instance it passed
    set_service(a.svc)
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__bounce').execute_with_tracking({'x': 3}))
    assert '"reason": "loop"' in r['content'][0]['text'], r
    assert bounce.calls == 1
    for p in (a, b, c):
        p.svc.stop()


def test_assertion_refusals_on_a_reexported_call(tmp_path, isolate):
    conn, a, b, c, kid, raw = chain(tmp_path)
    alice = {'user_id': 'alice', 'authenticated': True}
    router = b.svc.catalogs.router
    q = 'acme-net__treasury-na__ledger'

    def relay(value, tid):
        out = router.call(q, {'x': 9}, user={'user_id': 'alice', 'roles': ['analyst'], 'authenticated': True},
                          traceparent=new_traceparent(tid), hop_in=(1, [f'{M}/risk-eu']), relay={
                              'Sajha-Net-User-Assertion': value})
        return out

    tid = '1' * 32
    ok = ni.make_assertion(a.svc.authz, M, dict(alice), 'treasury-na', tid)
    assert relay(ok, tid)['content'][0]['text'].startswith('treasury-na:ledger:9')
    reason = lambda out: out['_meta'][EXTENSION_ID]['refusal']['reason']  # noqa: E731
    assert reason(relay(ok, tid)) == 'assertion_invalid'                         # replayed (jti seen)
    now = int(a.n().clock())
    old = ni.make_assertion(a.svc.authz, M, dict(alice), 'treasury-na', tid, override={'iat': now - 300, 'exp': now - 250})
    assert reason(relay(old, tid)) == 'assertion_invalid'                        # expired
    other = ni.make_assertion(a.svc.authz, M, dict(alice), 'treasury-na', tid, override={'net': 'other-net'})
    assert reason(relay(other, tid)) == 'assertion_invalid'                      # another net
    aud = ni.make_assertion(a.svc.authz, M, dict(alice), 'cust-na', tid)
    assert reason(relay(aud, tid)) == 'assertion_invalid'                        # another audience
    trace = ni.make_assertion(a.svc.authz, M, dict(alice), 'treasury-na', '2' * 32)
    assert reason(relay(trace, tid)) == 'assertion_invalid'                      # another trace
    doc = decode(ni.make_assertion(a.svc.authz, M, dict(alice), 'treasury-na', tid))
    doc['user'] = 'mallory@risk-eu'
    forged = crypto.b64url(json.dumps(doc).encode())
    assert reason(relay(forged, tid)) == 'assertion_invalid'                     # signature
    # an intermediary never relays a raw key
    out = router.call(q, {'x': 1}, user=dict(alice), hop_in=(1, [f'{M}/risk-eu']), relay={'Sajha-Net-Api-Key': raw})
    assert reason(out) == 'assertion_invalid' and out['_meta'][EXTENSION_ID]['refusal']['side'] == 'home'
    for p in (a, b, c):
        p.svc.stop()


# ── a bridge between two nets (NET-05) ──────────────────────────────

def bridge(tmp_path, m_ids='assertion,api_key'):
    """desk-ap (beta-net) -> cust-na (in both nets, the bridge) -> treasury-na (acme-net, listing ``m_ids``)."""
    conn = Capture()
    c = Peer(tmp_path, 'treasury-na', conn, [Who('ledger', owner='treasury-na')], [(M, True, [])],
             cat=CatalogSettings(max_hops=2), auth={M: {'user_identity': m_ids}})
    d = Peer(tmp_path, 'desk-ap', conn, [Who('var_calc', owner='desk-ap')], [(N, True, [])])
    b = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na')],
             [(M, False, ['https://treasury-na.test']), (N, False, ['https://desk-ap.test'])],
             cat=CatalogSettings(max_hops=2, per_net={N: {'reexport': True, 'reexport_rules': [{'tools': ['ledger']}]}}),
             auth={M: {'user_identity': m_ids}})
    return conn, b, c, d


def test_bridge_offers_another_nets_tool_as_its_own_and_calls_as_its_user(tmp_path, isolate):
    conn, b, c, d = bridge(tmp_path)              # acme-net lists assertion: the bridge signs one there
    start(c, d, b)
    join(c, [b], M)
    join(d, [b], N)
    for p in (b, c, d):
        p.user('alice', roles=('analyst',), tools=PERMS)
    kid, raw = d.key('alice')
    b.key('alice')                                  # the bridge's own user has a key in acme-net
    settle([b, c, d])
    # in beta-net, ledger is cust-na's own (no origin); in acme-net cust-na re-exports nothing
    q = 'beta-net__cust-na__ledger'
    assert q in d.reg.tools and 'origin' not in d.reg.get_tool(q).meta
    assert 'reexport' in b.n(N).features and 'reexport' not in b.n(M).features
    assert [t['name'] for t in b.svc.catalogs.books[M].exports('treasury-na')] == ['lookup']
    assert 'acme-net__cust-na__var_calc' not in c.reg.tools
    set_service(d.svc)
    r = as_user('alice', raw, kid, lambda: d.reg.get_tool('ledger').execute_with_tracking({'x': 4}))
    assert r['content'][0]['text'] == 'treasury-na:ledger:4:as alice', r
    h = conn.to('treasury-na')[-1]
    assert 'sajha-net-api-key' not in h and h['sajha-net-name'] == M and h['sajha-net-hop'] == '2'
    assert h['sajha-net-visited'] == '"beta-net/desk-ap", "acme-net/cust-na"'
    s = decode(h['sajha-net-user-assertion'])
    assert (s['net'], s['iss'], s['user'], s['aud']) == (M, 'cust-na', 'alice@cust-na', 'treasury-na')
    seen = {x['user'] for x in c.svc.authz.users_view(M)['seen']}
    assert seen == {'alice@cust-na'}                # the host in acme-net sees the bridge's user only
    # with re-export off for beta-net nothing crosses
    b.svc.catalogs.settings.per_net[N]['reexport'] = False
    b.svc.catalogs.books[N].reexport = False
    b.svc.catalogs.books[N].invalidate()
    assert all(t['name'] != 'ledger' for t in b.svc.catalogs.books[N].exports('desk-ap'))
    for p in (b, c, d):
        p.svc.stop()


def test_a_bridge_uses_what_the_target_net_lists_and_a_host_refuses_an_unlisted_assertion(tmp_path, isolate):
    """A bridge's call into another net is an ordinary call there: where that net lists only
    token_exchange, the bridge exchanges a token; a host refuses an assertion its net does not list, except
    in the re-export relay case within one net."""
    conn, b, c, d = bridge(tmp_path, m_ids='token_exchange')
    start(c, d, b)
    join(c, [b], M)
    join(d, [b], N)
    for p in (b, c, d):
        p.user('alice', roles=('analyst',), tools=PERMS)
    kid, raw = d.key('alice')
    b.key('alice')
    settle([b, c, d])
    set_service(d.svc)
    r = as_user('alice', raw, kid, lambda: d.reg.get_tool('ledger').execute_with_tracking({'x': 8}))
    assert r['content'][0]['text'] == 'treasury-na:ledger:8:as alice', r
    h = conn.to('treasury-na')[-1]
    assert h['sajha-net-hop'] == '2' and h['sajha-net-user-token'] and 'sajha-net-user-assertion' not in h
    assert {x['user']: x['identity'] for x in c.svc.authz.users_view(M)['seen']} == {'alice@cust-na': 'token_exchange'}
    # an assertion the bridge signs itself (hop 2, issued by the sender) is not the relay case: refused
    st = b.svc.authz.nets[M]
    bkid = next(r['key_id'] for r in st.keys.own_records())
    user = {'user_id': 'alice', 'roles': ['analyst'], 'key_id': bkid}
    value = ni.make_assertion(b.svc.authz, M, user, 'treasury-na', 'a' * 32)
    with pytest.raises(Exception) as e:
        c.svc.authz.identity.resolve({'sajha-net-name': M, 'sajha-net-user-assertion': value}, 'cust-na',
                                     audience='treasury-na', hop=2, visited=[f'{N}/desk-ap', f'{M}/cust-na'],
                                     trace_id='a' * 32)
    assert getattr(e.value, 'reason', '') == 'assertion_invalid' and 'token_exchange' in str(e.value)
    for p in (b, c, d):
        p.svc.stop()


# ── assertion and token_exchange as a net's resolver ────────────────

def pair(tmp_path, a_ids, b_ids):
    conn = Capture()
    b = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na')], [(M, True, [])],
             auth={M: {'user_identity': b_ids}})
    a = Peer(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], [(M, False, ['https://cust-na.test'])],
             auth={M: {'user_identity': a_ids}})
    start(b, a)
    join(b, [a])
    for p in (a, b):
        p.user('alice', roles=('analyst',), tools=PERMS)
    a.user('bob', roles=('analyst',), tools=PERMS)               # no account at cust-na
    kid, raw = a.key('alice')
    bkid, braw = a.key('bob')
    settle([a, b])
    set_service(a.svc)
    return conn, a, b, (kid, raw), (bkid, braw)


def test_assertion_resolver_end_to_end(tmp_path, isolate):
    conn, a, b, (kid, raw), (bkid, braw) = pair(tmp_path, 'assertion', 'assertion,api_key')
    assert b.node.cfg.user_identity == ['assertion', 'api_key']
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 2}))
    assert r['content'][0]['text'] == 'cust-na:lookup:2:as alice', r
    h = conn.to('cust-na')[-1]
    assert 'sajha-net-api-key' not in h and decode(h['sajha-net-user-assertion'])['key_id'] == kid
    assert {s['user']: s['identity'] for s in b.svc.authz.users_view(M)['seen']} == {'alice@risk-eu': 'assertion'}
    # refusals: no account there, a host that does not accept assertions, a revoked key
    r = as_user('bob', braw, bkid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 2}))
    assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'no_account', r
    b.svc.authz.nets[M].settings.user_identity = 'api_key'
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 2}))
    assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'assertion_invalid', r
    b.svc.authz.nets[M].settings.user_identity = 'assertion'
    from sajha.auth import apikeys
    db = a.Session()
    try:
        apikeys.revoke_key(db, apikeys.get_key(db, kid), by='admin')
    finally:
        db.close()
    a.svc.authz.nets[M].keys.publish()
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 2}))
    assert r.get('isError') and r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'key_disabled', r
    for p in (a, b):
        p.svc.stop()


def test_token_exchange_resolver_end_to_end(tmp_path, isolate):
    conn, a, b, (kid, raw), (bkid, braw) = pair(tmp_path, 'token_exchange', 'token_exchange')
    assert 'token_exchange' in b.node.features
    tx = a.svc.authz.identity.resolvers['token_exchange']
    call = lambda: as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 6}))  # noqa
    assert call()['content'][0]['text'] == 'cust-na:lookup:6:as alice'
    assert call()['content'][0]['text'] == 'cust-na:lookup:6:as alice'
    assert tx.exchanges == 1                                         # cached until shortly before it expires
    h = conn.to('cust-na')[-1]
    assert 'sajha-net-api-key' not in h and 'sajha-net-user-assertion' not in h and h['sajha-net-user-token']
    assert {s['user']: s['identity'] for s in b.svc.authz.users_view(M)['seen']} == {'alice@risk-eu': 'token_exchange'}
    # the host forgets its tokens: the call is refused token_invalid once, the home exchanges again
    for k, _v in list(b.n().kv.scan('tok:')):
        b.n().kv.delete(k)
    assert call()['content'][0]['text'] == 'cust-na:lookup:6:as alice'
    assert tx.exchanges == 2
    # a token is bound to the home it was issued to
    tok = conn.to('cust-na')[-1]['sajha-net-user-token']
    with pytest.raises(Exception) as e:
        b.svc.authz.identity.resolve({'sajha-net-name': M, 'sajha-net-user-token': tok}, 'treasury-na')
    assert getattr(e.value, 'reason', '') == 'token_invalid'
    # the exchange is refused for a user with no account there
    r = as_user('bob', braw, bkid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 6}))
    assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'no_account', r
    # a host that does not accept token_exchange
    b.svc.authz.nets[M].settings.user_identity = 'api_key'
    tx.forget(M, 'cust-na')
    r = call()
    assert r['_meta'][EXTENSION_ID]['refusal']['reason'] in ('token_invalid',), r
    for p in (a, b):
        p.svc.stop()


# ── topology ────────────────────────────────────────────────────────

def test_topology_lists_instances_offers_reexports_and_call_paths(tmp_path, isolate):
    conn, a, b, c, kid, raw = chain(tmp_path)
    set_service(a.svc)
    as_user('alice', raw, kid, lambda: a.reg.get_tool('ledger').execute_with_tracking({'x': 5}))
    t = a.svc.catalogs.topology()
    assert [n['name'] for n in t['nets']] == [M]
    net = t['nets'][0]
    assert {(n['name'], n['self']) for n in net['nodes']} == {('risk-eu', True), ('cust-na', False),
                                                             ('treasury-na', False)}
    assert all(set(n) == {'name', 'kind', 'region', 'state', 'self', 'vendor'} for n in net['nodes'])
    edges = {(e['from'], e['to'], e['kind']): e for e in net['edges']}
    assert edges[('cust-na', 'risk-eu', 'reexports')]['origins'] == ['treasury-na']
    assert edges[('cust-na', 'risk-eu', 'offers')]['tools'] == 1                   # lookup
    assert ('treasury-na', 'risk-eu', 'offers') not in edges                      # exported only to cust-na
    assert edges[('risk-eu', 'cust-na', 'calls')]['calls'] == 1
    ct = {(e['from'], e['to'], e['kind']): e for e in c.svc.catalogs.topology(M)['nets'][0]['edges']}
    assert ct[('risk-eu', 'cust-na', 'calls')]['calls'] == 1 and ct[('cust-na', 'treasury-na', 'calls')]['calls'] == 1
    assert ct[('treasury-na', 'cust-na', 'offers')]['tools'] == 1
    bt = {(e['from'], e['to'], e['kind']): e for e in b.svc.catalogs.topology()['nets'][0]['edges']}
    assert bt[('cust-na', 'risk-eu', 'reexports')] == {'from': 'cust-na', 'to': 'risk-eu', 'kind': 'reexports',
                                                      'tools': 1, 'calls': 0, 'origins': ['treasury-na']}
    assert a.svc.catalogs.topology('nope') == {'nets': []}
    from sajha.routes.sajhanet_routes import router
    assert any(getattr(r, 'path', '') == '/api/sajhanet/topology' for r in router.routes)
    for p in (a, b, c):
        p.svc.stop()
