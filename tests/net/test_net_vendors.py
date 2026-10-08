"""
Vendors and external servers (SAJHA Net design §5.6; protocol §5.5) and how a node recognises itself
(protocol §9.4).

* Every member names its ``vendor`` (in its member record and the views).
* An **external server** is a federation upstream listed in ``sajhanet.external_servers`` with its vendor:
  it is never a member of a net; the SAJHA instance that defines it offers its tools as its own, under
  ``<vendor>__<tool>``, with its full governance. ``search`` of acme and of globex then never collide;
  two instances offering acme's identical ``search`` are one fallback set; one with a different contract
  is quarantined, named.
* Internal servers (sponsored ones included) keep their names and the rule as before; a sponsored entry
  or the agent marked external is refused.
* ``rename``, the length rule, export rules and blocks under either name, audit with both names, and
  re-export of a published name.
* Self-recognition: a record signed with the node's own key under another name, or naming its own URL, is
  this node (a notice, never a member); a seed at its own URL is skipped; a sponsored participant sharing
  the sponsor's URL is not mistaken for it.
"""

import os
import subprocess
import sys

import pytest

from sajha.federation.tool import FederatedTool
from sajha.net import EXTENSION_ID, crypto, names, schemas
from sajha.net.integration import set_service
from sajha.net.integration.catalogs import CatalogSettings
from sajha.net.integration.config import ExternalServer, external_servers, naming_problem
from sajha.net.integration.sponsored import SponsoredSpec
from sajha.net.library import NetParticipant
from sajha.net.models import EXTERNAL_KEY, NetConfig, member_record
from sajha.net.node import normalise_url
from sajha.net.plugins import StaticCatalog
from tests.net.test_net_mixed_conformance import FakeFederation
from tests.net.test_net_reexport_identity import M, Capture, Peer, join, settle, start
from tests.net.test_net_three_instances import NET, Instance, Who, as_user, isolate  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
Q = {'q': {'type': 'string'}}
QN = {'q': {'type': 'string'}, 'n': {'type': 'integer'}}


# ── names and configuration (pure) ──────────────────────────────────

def test_vendor_syntax_and_published_names():
    for ok in ('acme', 'globex', 'a', 'acme_corp', 'x1', 'a' * 24):
        assert names.is_vendor(ok), ok
    for bad in ('', 'Acme', '1acme', 'acme__x', 'acme_', 'ac-me', 'a' * 25, None):
        assert not names.is_vendor(bad), bad
    assert names.published_name('search') == 'search'
    assert names.published_name('search', 'acme', True) == 'acme__search'
    assert names.published_name('acme__search', 'acme', True) == 'acme__search'      # never acme__acme__
    assert names.published_name('search', 'acme', True, {'search': 'find'}) == 'find'
    q = names.qualified_name('acme-net', 'risk-eu', names.published_name('files__read', 'acme', True))
    assert q == 'acme-net__risk-eu__acme__files__read'
    assert names.split_qualified(q) == ('acme-net', 'risk-eu', 'acme__files__read')
    assert names.max_tool_part('acme-net', 'risk-eu') == 128 - 8 - 7 - 4
    assert naming_problem('acme', {}) is None
    assert 'not a vendor name' in naming_problem('Acme', {})
    assert 'not a valid published tool name' in naming_problem('acme', {'a': 'b c'})


def test_external_server_configuration(monkeypatch):
    from sajha.net.integration import config as ncfg
    monkeypatch.setattr(ncfg, '_g', lambda key, default: default)
    xs, errs = external_servers({'external_servers': [
        {'upstream': 'acme', 'vendor': 'acme'},
        {'upstream': 'glx', 'vendor': 'globex', 'tools': 'search,fetch_*', 'rename': {'fetch_document': 'gfetch'},
         'nets': ['acme-net']},
        {'upstream': 'nov'}, {'upstream': 'bad', 'vendor': 'Bad'}, {'upstream': 'acme', 'vendor': 'acme'}]})
    assert [x.upstream for x in xs] == ['acme', 'glx']
    assert xs[1].tools == ['search', 'fetch_*'] and xs[1].published('fetch_document') == 'gfetch'
    assert xs[1].published('search') == 'globex__search' and xs[1].nets == ['acme-net']
    assert len(errs) == 3 and any('vendor is required' in e for e in errs) and any('twice' in e for e in errs)


def test_member_record_carries_vendor_only():
    rec = member_record(NetConfig(name=NET, instance_name='risk-eu', base_url='https://x.test', vendor='acme'),
                        'risk-eu', 1, 1)
    assert rec['vendor'] == 'acme' and EXTERNAL_KEY not in rec and not schemas.errors('member_record', rec)
    old = member_record(NetConfig(name=NET, instance_name='a-b', base_url='https://x.test'), 'a-b', 1, 1)
    assert 'vendor' not in old and not schemas.errors('member_record', old)            # older records stay valid
    assert schemas.errors('member_record', dict(old, vendor='Not A Vendor'))


def test_net_configuration_vendor_rename_and_no_external_member(monkeypatch):
    from sajha.net.integration import config as ncfg
    vals = {'vendor': 'riskco'}
    monkeypatch.setattr(ncfg, '_g', lambda key, default: vals.get(key, default))
    monkeypatch.setattr(ncfg, '_raw', lambda: {'rename': {'var_calc': 'var'}})
    monkeypatch.setattr('sajha.core.net_extension.configured_nets', lambda: [
        {'name': 'acme-net', 'instance_name': 'risk-eu', 'base_url': 'https://r.test'},
        {'name': 'beta-net', 'instance_name': 'risk-eu', 'base_url': 'https://r.test', 'vendor': 'riskbeta',
         'rename': {}},
        {'name': 'gamma-net', 'instance_name': 'risk-eu', 'base_url': 'https://r.test', 'vendor': 'Bad'},
        {'name': 'delta-net', 'instance_name': 'risk-eu', 'base_url': 'https://r.test', EXTERNAL_KEY: True}])
    cfgs, errors = ncfg.net_configs(ncfg.shared())
    by = {c.name: c for c in cfgs}
    assert (by['acme-net'].vendor, by['acme-net'].rename) == ('riskco', {'var_calc': 'var'})
    assert (by['beta-net'].vendor, by['beta-net'].rename) == ('riskbeta', {})
    assert 'not a vendor name' in errors['gamma-net'] and 'acme-net' not in errors
    assert 'always a member' in errors['delta-net'] and 'external_servers' in errors['delta-net']


def test_sponsored_entry_needs_a_vendor_and_is_never_external():
    with pytest.raises(ValueError, match='vendor is required'):
        SponsoredSpec.from_dict({'net': NET, 'instance_name': 'acme-search', 'upstream': 'acme'})
    with pytest.raises(ValueError, match='external_servers'):
        SponsoredSpec.from_dict({'net': NET, 'instance_name': 'acme-search', 'upstream': 'acme', 'vendor': 'acme',
                                 EXTERNAL_KEY: True})
    sp = SponsoredSpec.from_dict({'net': NET, 'instance_name': 'acme-search', 'upstream': 'acme', 'vendor': 'acme',
                                  'rename': {'search': 'find'}})
    assert (sp.vendor, sp.rename) == ('acme', {'search': 'find'})


def test_agent_refuses_external(tmp_path):
    env = dict(os.environ, PYTHONPATH=ROOT)
    out = subprocess.run([sys.executable, '-m', 'sajhanet_agent', '--net', 'lab-net', '--instance', 'x-y',
                          '--url', 'https://h:1', '--mcp-command', 'true', '--vendor', 'acme', f'--{EXTERNAL_KEY}',
                          '--data-dir', str(tmp_path / 'd')], capture_output=True, text=True, env=env, cwd=ROOT,
                         timeout=60)
    assert out.returncode == 2 and 'not a member' in out.stderr and 'external_servers' in out.stderr
    from sajhanet_agent.__main__ import parser
    a = parser().parse_args(['--net', 'n', '--instance', 'x-y', '--url', 'https://h:1', '--mcp-command', 'true',
                             '--vendor', 'acme', '--rename', 'search=find'])
    assert (a.vendor, a.rename) == ('acme', ['search=find'])
    with pytest.raises(SystemExit):                         # --vendor is required
        parser().parse_args(['--net', 'n', '--instance', 'x-y', '--url', 'https://h:1', '--mcp-command', 'true'])


# ── external servers across SAJHA instances ─────────────────────────

def _search(fed, upstream, props, name='search'):
    return FederatedTool(fed, upstream, name, {
        'name': f'{upstream}fed__{name}', 'description': 'Search',
        'inputSchema': {'type': 'object', 'properties': props}, 'annotations': {'readOnlyHint': True}})


def _net(tmp_path, defs):
    """cust-na (the home, founder) and one SAJHA instance per ``defs`` entry: (instance, [(upstream, vendor,
    props, rename, tool name)]) defining those external servers."""
    conn = Capture()
    fed = FakeFederation()
    home = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na')], [(M, True, [])])
    peers = []
    for inst, servers in defs:
        tools = [Who('var_calc', owner=inst)] + [_search(fed, up, props, tn) for up, _v, props, _r, tn in servers]
        xs = [ExternalServer(upstream=up, vendor=v, rename=r or {}) for up, v, _p, r, _t in servers]
        peers.append(Peer(tmp_path, inst, conn, tools, [(M, False, ['https://cust-na.test'])],
                          cat=CatalogSettings(external_servers=xs)))
    start(home, *peers)
    join(home, peers)
    every = ','.join(['lookup', 'var_calc', 'acme__search', 'globex__search', 'find']
                     + [f'acme-net__{p.name}__{x}' for p in peers for x in ('acme__search', 'globex__search', 'find')]
                     + [f'{up}fed__{tn}' for _i, ss in defs for up, _v, _p, _r, tn in ss])
    for p in [home] + peers:
        p.user('alice', roles=('analyst',), tools=every)
    kid, raw = home.key('alice')
    settle([home] + peers)
    return conn, fed, home, peers, kid, raw


def _call(home, kid, raw, name, q='x'):
    set_service(home.svc)
    return as_user('alice', raw, kid, lambda: home.reg.get_tool(name).execute_with_tracking({'q': q}))


def test_two_external_servers_of_two_vendors_do_not_collide(tmp_path, isolate):  # noqa: F811
    conn, fed, home, (a,), kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, None, 'search'),
                                                                   ('glx', 'globex', QN, None, 'search')])])
    assert home.svc.catalogs.books[M].quarantined() == {}
    assert {'acme-net__risk-eu__acme__search', 'acme-net__risk-eu__globex__search',
            'acme__search', 'globex__search'} <= set(home.reg.tools)
    # an external server is never a member: no record, no instance name, no traffic of its own
    assert {m['name'] for m in home.n().members()} == {'risk-eu'}
    assert {m['name'] for m in a.n().members()} == {'cust-na'}
    rows = {r['qualified_name']: r for r in home.svc.catalogs.table(M)['rows']}
    row = rows['acme-net__risk-eu__acme__search']
    assert row['vendor'] == 'acme' and row['external'] is True and row['host_instance'] == 'risk-eu'
    audits = []
    a.svc.catalogs.hosts[M].audit = lambda what, d: audits.append((what, d))
    r = _call(home, kid, raw, 'acme__search', 'bonds')
    assert r['content'][0]['text'] == 'vendor:search:bonds' and r['_meta'][EXTENSION_ID]['instance'] == 'risk-eu', r
    r = _call(home, kid, raw, 'globex__search', 'gold')
    assert r['content'][0]['text'] == 'vendor:search:gold', r
    assert [c[0] for c in fed.calls] == ['search', 'search']          # each upstream called by its own name
    host = [d for w, d in audits if w == 'net.host_call']
    assert [(d['tool'], d['local_tool']) for d in host] == [('acme__search', 'acmefed__search'),
                                                             ('globex__search', 'glxfed__search')]
    assert {u.split('/')[2] for u, _h in conn.sent} <= {'risk-eu.test', 'cust-na.test'}
    # the instance page names the vendor and the defining instance
    from sajha.net.integration import console
    from sajha.auth import AuthContext
    admin = AuthContext(authenticated=True, user_id='admin', user_name='admin', roles=['admin'], auth_type='session',
                        is_admin=True)
    monkey = console._may_use
    console._may_use = lambda auth, name: True
    try:
        view = console.instance_view(M, 'risk-eu', admin)
    finally:
        console._may_use = monkey
    t = next(t for t in view['tools'] if t['name'] == 'acme__search')
    assert t['vendor'] == 'acme' and t['external'] is True
    for p in (home, a):
        p.svc.stop()


def test_two_instances_with_one_vendor_contract_are_a_fallback_set(tmp_path, isolate):  # noqa: F811
    conn, fed, home, (a, b), kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, None, 'search')]),
                                                        ('treasury-na', [('acme', 'acme', Q, None, 'search')])])
    assert home.svc.catalogs.books[M].quarantined() == {}
    router = home.svc.catalogs.router
    order = [c.host for c in router.resolve('acme__search').candidates]
    assert sorted(order) == ['risk-eu', 'treasury-na']
    br = router.breaker(M, order[0])                     # the first host is down: the waterfall goes on
    for _ in range(router.peer.breaker_threshold):
        br.failure()
    r = _call(home, kid, raw, 'acme__search', 'q1')
    assert r['_meta'][EXTENSION_ID]['instance'] == order[1], r
    for p in (home, a, b):
        p.svc.stop()


def test_one_vendor_two_contracts_is_quarantined_naming_the_host(tmp_path, isolate):  # noqa: F811
    conn, fed, home, peers, kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, None, 'search')]),
                                                       ('treasury-na', [('acme', 'acme', Q, None, 'search')]),
                                                       ('risk-apac', [('acme', 'acme', QN, None, 'search')])])
    q = home.svc.catalogs.books[M].quarantined()
    assert set(q) == {'acme__search'}
    assert q['acme__search']['differing'] == ['risk-apac'] and 'risk-apac' in q['acme__search']['text']
    assert 'acme__search' not in home.reg.tools
    for p in [home] + peers:
        p.svc.stop()


def test_rename_and_the_length_rule_on_an_external_server(tmp_path, isolate):  # noqa: F811
    long = 'l' * 110
    conn, fed, home, (a,), kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, {'search': 'find'}, 'search'),
                                                                   ('glx', 'globex', Q, None, long)])])
    assert 'find' in home.reg.tools and 'acme__search' not in home.reg.tools
    assert _call(home, kid, raw, 'find', 'z')['content'][0]['text'] == 'vendor:search:z'
    book = a.svc.catalogs.books[M]
    refused = book.refused[f'glxfed__{long}']
    assert refused['published'] == f'globex__{long}' and 'rename' in refused['reason']
    assert all(t['name'] != f'globex__{long}' for t in book.exports(None))
    from sajha import notices
    assert any(n['id'] == f'sajhanet.name:{M}:glxfed__{long}' for n in notices.list_notices(state='all'))
    for p in (home, a):
        p.svc.stop()


def test_rules_and_blocks_accept_either_name(tmp_path, isolate):  # noqa: F811
    conn, fed, home, (a,), kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, None, 'search')])])
    # an export rule under the local (registry) name exports the published tool
    a.svc.authz.nets[M].settings.export = [{'tools': ['acmefed__search', 'var_calc']}]
    a.svc.catalogs.books[M].invalidate()
    assert 'acme__search' in [t['name'] for t in a.svc.catalogs.books[M].exports('cust-na')]
    # a block on the local name blocks the published tool
    a.svc.authz.add_block(M, 'tool', '*', 'test', by='admin', tool='acmefed__search')
    r = _call(home, kid, raw, 'acme__search')
    assert r.get('isError') and r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'tool', r
    for p in (home, a):
        p.svc.stop()


def test_reexport_keeps_the_external_published_name(tmp_path, isolate):  # noqa: F811
    """treasury-na defines the external server tre (vendor treasury) and exports only to cust-na, which
    re-exports treasury__ledger to risk-eu under the same name."""
    conn = Capture()
    fed = FakeFederation()
    ledger = FederatedTool(fed, 'tre', 'ledger', {'name': 'trefed__ledger', 'inputSchema': {'type': 'object'}})
    perms = 'lookup,var_calc,trefed__ledger,treasury__ledger,acme-net__cust-na__treasury__ledger'
    c = Peer(tmp_path, 'treasury-na', conn, [ledger], [(M, True, [])],
             auth={M: {'export': [{'tools': ['*'], 'to_instances': ['cust-na']}]}},
             cat=CatalogSettings(max_hops=2, external_servers=[ExternalServer(upstream='tre', vendor='treasury')]))
    b = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na')], [(M, False, ['https://treasury-na.test'])],
             cat=CatalogSettings(max_hops=2, reexport=True, reexport_rules=[{'tools': ['treasury__ledger']}]))
    a = Peer(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], [(M, False, ['https://treasury-na.test'])])
    start(c, b, a)
    join(c, [b, a])
    for p in (a, b, c):
        p.user('alice', roles=('analyst',), tools=perms)
    kid, raw = a.key('alice')
    settle([a, b, c])
    q = 'acme-net__cust-na__treasury__ledger'
    assert q in a.reg.tools and a.reg.get_tool(q).meta['origin'] == 'treasury-na'
    assert a.reg.get_tool(q).meta.get('vendor') == 'treasury' and a.reg.get_tool(q).meta.get('external') is True
    set_service(a.svc)
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('treasury__ledger').execute_with_tracking({'q': 5}))
    assert r['content'][0]['text'] == 'vendor:ledger:5', r
    for p in (a, b, c):
        p.svc.stop()


def test_internal_sponsored_servers_keep_one_name_one_contract(tmp_path, isolate):  # noqa: F811
    from tests.net.test_net_mixed_conformance import MixedConnector
    from tests.net.test_net_three_instances import settle as settle1
    conn = MixedConnector()
    fed = FakeFederation()
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu'), _search(fed, 'ua', Q),
                                             _search(fed, 'ug', QN), _search(fed, 'ua2', Q)], founder=True)
    a.svc.sponsored_config = [{'net': NET, 'instance_name': i, 'upstream': up, 'vendor': v}
                              for i, up, v in (('acme-search', 'ua', 'acme'), ('globex-search', 'ug', 'globex'),
                                               ('acme-search-2', 'ua2', 'acme'))]
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join()
    for _ in range(6):
        settle1([a], 1)
    vendors = {m['name']: m['record'].get('vendor') for m in a.node.members()}
    assert vendors == {'acme-search': 'acme', 'globex-search': 'globex', 'acme-search-2': 'acme'}
    q = a.svc.catalogs.books[NET].quarantined()
    assert set(q) == {'search'} and q['search']['differing'] == ['globex-search']
    a.svc.stop()


# ── recognising itself (protocol §9.4) ──────────────────────────────

def _p(name, url, kind='agent', seeds=(), sponsor=''):
    p = NetParticipant.build(net='lab-net', instance=name, base_url=url, source=StaticCatalog([]),
                             execute=lambda ctx, args: {'content': []}, seeds=list(seeds), founder=not seeds,
                             kind=kind, require_https=False, verify_keys=False)
    p.node.cfg.sponsor = sponsor
    seen = []
    p.node.observers.append(lambda kind, data: seen.append((kind, data)))
    p.start()
    return p, seen


def test_url_normalisation():
    assert normalise_url('HTTPS://Risk-EU.example:443/') == 'https://risk-eu.example'
    assert normalise_url('http://h:80/mcp/') == 'http://h/mcp'
    assert normalise_url('http://h:8080') == 'http://h:8080'
    assert normalise_url('http://[2001:DB8::7]:3002/') == 'http://[2001:db8::7]:3002'
    assert normalise_url('') == '' and normalise_url('not a url') == ''


def test_a_record_with_the_own_key_under_another_name_is_self():
    a, seen = _p('node-a', 'http://10.0.0.1:8790')
    entry = a.node.own_entry()
    rec = dict(entry['record'], name='node-renamed')
    sig = crypto.sign_record('member', rec, a.node.signer.key, a.node.signer.keyid)
    assert a.node.merge(dict(entry, record=rec, signature=sig)) is False
    assert a.node.member('node-renamed') is None
    ev = [d for k, d in seen if k == 'self_seen']
    assert ev and ev[0]['why'] == 'own_key' and ev[0]['claimant'] == 'node-renamed'


def test_a_record_naming_the_own_url_is_self_and_a_seed_at_it_is_skipped():
    a, seen = _p('node-a', 'http://10.0.0.1:8790')
    b, _ = _p('node-b', 'http://10.0.0.1:8790/')                       # another key, the same address
    assert a.node.merge(b.node.own_entry()) is False and a.node.member('node-b') is None
    ev = [d for k, d in seen if k == 'self_seen']
    assert ev and ev[0]['why'] == 'own_url' and ev[0]['claimant'] == 'node-b'
    c, _ = _p('node-c', 'http://10.0.0.1:8790', seeds=['http://10.0.0.1:8790/', 'http://10.0.0.2:8790'])
    assert [u for _k, u, _n in c.node.join_sources()] == ['http://10.0.0.2:8790']
    # an agent-fronted node at its own URL is an ordinary member
    d, _ = _p('node-d', 'http://10.0.0.4:8790')
    assert a.node.merge(d.node.own_entry()) is True and a.node.member('node-d')['state'] == 'alive'


def test_a_sponsored_participant_sharing_the_sponsors_url_is_not_self():
    a, seen = _p('node-a', 'http://10.0.0.1:8790', kind='sajha')
    s, _ = _p('node-s', 'http://10.0.0.1:8790', kind='sponsored', sponsor='node-a')
    assert a.node.merge(s.node.own_entry()) is True and a.node.member('node-s')['record']['sponsor'] == 'node-a'
    assert s.node.merge(a.node.own_entry()) is True                    # the sponsored node sees its sponsor
    s2, _ = _p('node-s2', 'http://10.0.0.1:8790', kind='sponsored', sponsor='node-a')
    assert s.node.merge(s2.node.own_entry()) is True                   # and its siblings
    other, _ = _p('node-x', 'http://10.0.0.1:8790', kind='sponsored', sponsor='node-z')
    assert a.node.merge(other.node.own_entry()) is False               # sponsored by someone else
    assert not [d for k, d in seen if k == 'self_seen' and d['claimant'] == 'node-s']


def test_external_servers_from_the_mcp_servers_file_and_prefix_clashes(tmp_path, isolate, monkeypatch):  # noqa: F811
    """Federation's file entries are external servers here too; a prefix is unique across upstreams and
    external servers and never a local tool's name (the second is not offered, with a notice)."""
    from types import SimpleNamespace
    ups = {'github': 'github', 'units': 'units', 'other': 'acme'}
    fed = SimpleNamespace(external_servers=lambda: [{'upstream': 'github', 'vendor': 'github', 'prefix': 'github'}],
                          upstream_ids=lambda: sorted(ups),
                          get_config=lambda uid: SimpleNamespace(effective_prefix=ups[uid]))
    monkeypatch.setattr('sajha.federation.manager.get_federation', lambda: fed)
    p = Peer(tmp_path, 'risk-eu', Capture(), [Who('var_calc', owner='risk-eu')], [(M, True, [])],
             cat=CatalogSettings(external_servers=[ExternalServer(upstream='units', vendor='units'),
                                                   ExternalServer(upstream='acme', vendor='acme'),
                                                   ExternalServer(upstream='calc', vendor='calc', prefix='var_calc')]))
    xs = p.svc.catalogs.external_servers()
    assert [x.upstream for x in xs] == ['units', 'github']
    problems = p.svc.catalogs._external_problems
    assert any('acme' in e and 'federation upstream other' in e for e in problems)
    assert any('var_calc' in e and 'local tool' in e for e in problems)
    from sajha import notices
    assert any(n['id'] == 'sajhanet.external_servers' for n in notices.list_notices(state='all'))
