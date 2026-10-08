"""
The three-instance test net, end to end in one process (Implementation Plan phase 4.3): three
SajhaNetService instances, each with its own SQLite database (users, API keys, the net key directory),
state store, key files, storage and tools registry, talking over HTTP (TestClient) through
``/sajhanet/v1/`` and the MCP endpoint's net path, with the shipped ``api_key`` identity resolver and
export and import rules.

One scenario: a CA founder and two instances that enroll and join through it as their seed; catalog
exchange; alice calls a tool on another instance as herself (her key verified against the net key
directory, mapped by name to the host's alice); a block refuses her; the host goes down and the plain
name falls back; a contract conflict is quarantined everywhere and re-activated; a restart lists nothing
remote until the peers answer. Also: a net of one (no seeds) that grows without a restart, and the
Instances views and navbar badge.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
from sajha.auth import apikeys
from sajha.auth.presented_key import forget, remember
from sajha.core.state.memory import MemoryStateStore
from sajha.core.storage import LocalStorageBackend
from sajha.db.schema import create_sqlite
from sajha.net import EXTENSION_ID
from sajha.net.integration import SajhaNetService, get_service, set_service
from sajha.net.integration import authz as az
from sajha.net.integration.config import Shared
from sajha.net.models import CASettings, IdentitySettings, NetConfig, PeerCacheSettings
from sajha.observability.caller import Caller, current, reset, set_caller
from tests.net.test_net_integration import ClientConnector
from tests.net.test_net_routing_integration import Echo, Registry, app_for, gossip

NET = 'acme-net'


class Who(Echo):
    """An echo tool that also says who it ran as (the host's caller)."""

    def execute(self, arguments):
        self.calls += 1
        return f'{self.owner}:{self.name}:{arguments.get("x")}:as {current().user_id}'


class Instance:
    def __init__(self, tmp, name, conn, tools, founder=False, seeds=None, store=None, engine=None):
        self.name = name
        d = tmp / name
        d.mkdir(parents=True, exist_ok=True)
        self.engine = engine or create_engine(f'sqlite:///{tmp / (name + ".db")}')
        if engine is None:
            create_sqlite(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        s = Shared(enabled=True, data_dir=str(d), gossip=gossip())
        cfg = NetConfig(name=NET, instance_name=name, founder=founder,
                        seeds=list(seeds if seeds is not None else ([] if founder else ['https://risk-eu.test'])),
                        base_url=f'https://{name}.test', gossip=gossip(),
                        identity=IdentitySettings(cert_ref=f'file:{d}/instance.crt', key_ref=f'file:{d}/instance.key',
                                                  ca_ref=f'file:{d}/ca.pem', revocation_list_ref=f'file:{d}/revoked.json'),
                        ca=CASettings(enabled=founder, key_ref=f'file:{d}/ca.key', cert_ref=f'file:{d}/ca.pem'),
                        peer_cache=PeerCacheSettings(path=str(d / 'peers.json')))
        self.svc = svc = SajhaNetService(s, [cfg], {}, store=store or MemoryStateStore(), connector=conn,
                                         documents=LocalStorageBackend(str(d)))
        svc.tools_registry = Registry()
        for t in tools:
            svc.tools_registry.register_tool(t)
        svc.authz = az.NetAuthz(svc, db_factory=self.Session, engine=self.engine, persistent=lambda: [],
                                settings={NET: az.NetAuthSettings(export=[{'tools': ['*']}], import_=[{'tools': ['*']}])})
        conn.clients[f'https://{name}.test'] = TestClient(app_for(svc), base_url=f'https://{name}.test')

    @property
    def node(self):
        return self.svc.runtimes[NET].node

    @property
    def reg(self):
        return self.svc.tools_registry

    def user(self, login, roles=('user',), tools='lookup,var_calc'):
        """A local account whose roles may execute ``tools`` here (each host decides for itself)."""
        from sajha.db.models import Permission, Role, User
        db = self.Session()
        try:
            u = User(user_id=login, user_name=login.title(), password_hash='x', enabled=True)
            rs = []
            for r in roles:
                role = db.query(Role).filter(Role.name == r).first()
                if role is None:
                    role = Role(name=r, description=r)
                    role.permissions = [Permission(resource_type='tool', resource_name=t, actions='execute,read')
                                        for t in tools.split(',')]
                rs.append(role)
            u.roles = rs
            db.add(u)
            db.commit()
        finally:
            db.close()

    def key(self, login):
        from sajha.db.models import User
        db = self.Session()
        try:
            owner = db.query(User).filter(User.user_id == login).first()
            k, raw = apikeys.create_key(db, name=f'{login} key', created_by='admin', owner=owner)
            return k.id, raw
        finally:
            db.close()


def settle(insts, rounds=4):
    for _ in range(rounds):
        for i in insts:
            if i.node is not None and f'https://{i.name}.test' not in i.svc.connector.down:
                i.node.tick()
        for i in insts:
            i.svc.catalogs.maybe_sync()


def as_user(login, raw, kid, fn):
    """Run ``fn`` as ``login`` who presented API key ``raw`` at this home (what /mcp does)."""
    tok = remember(raw, kid, login)
    c = set_caller(Caller(login, '', ('user',), 'apikey', None, False))
    try:
        return fn()
    finally:
        reset(c)
        forget(tok)


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr('sajha.auth.apikeys._audit', lambda *a, **k: None)
    monkeypatch.setattr('sajha.auth.persistent_keys.get_persistent_keys', lambda: type('P', (), {
        'records': lambda self: [], 'ids': lambda self: set(), 'lookup': lambda self, h: None,
        'upsert': lambda self, r: None, 'remove': lambda self, i: False})())
    set_vault(TokenVault(engine=create_engine(f'sqlite:///{tmp_path / "vault.db"}'),
                         key_provider=LocalKeyProvider('test-three-instances-' + 'k' * 32)))
    old = get_service()
    yield
    set_service(old)
    set_vault(None)
    forget()
    from sajha import notices
    for n in notices.list_notices(state='all'):
        if str(n.get('id', '')).startswith('sajhanet.'):
            notices.clear_notice(n['id'])


def test_three_instances_end_to_end(tmp_path, isolate):
    conn = ClientConnector()
    # the founder: CA instance, no seeds
    a = Instance(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], founder=True)
    a.svc.start(run_agents=False)
    a.svc.ca_init(NET)
    assert a.node.try_join() and a.node.status().get('founder_alone')
    insts = [a]
    # two instances enroll with tokens and join through the founder as their seed
    for name, tools in (('cust-na', [Who('var_calc', owner='cust-na'), Who('lookup', owner='cust-na')]),
                        ('treasury-na', [Who('var_calc', owner='treasury-na'), Who('lookup', owner='treasury-na')])):
        i = Instance(tmp_path, name, conn, tools)
        i.svc.start(run_agents=False)
        assert i.svc.runtimes[NET].error.startswith('no certificate')
        tok = a.svc.ca_token(NET, name)
        i.svc.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        assert i.node.try_join() and i.node.status()['joined_via'] == 'https://risk-eu.test'
        insts.append(i)
    b, c = insts[1], insts[2]
    for i in insts:
        i.user('alice', roles=('user',) if i is a else ('analyst',))
    kid, raw = a.key('alice')
    settle(insts, 6)
    for i in insts:
        assert {m['name']: m['state'] for m in i.node.members()} == {o.name: 'alive' for o in insts if o is not i}

    # catalog exchange: every remote tool is a proxy at the home, the plain name in resolution order
    assert {'acme-net__cust-na__lookup', 'acme-net__treasury-na__lookup', 'lookup'} <= set(a.reg.tools)
    meta = {t['name']: t for t in a.reg.get_all_tools()}['lookup']['_meta'][EXTENSION_ID]
    assert meta['resolution'] == ['acme-net__cust-na__lookup', 'acme-net__treasury-na__lookup']
    # alice's key record reached the hosts' key directories
    assert b.svc.authz.keys_view(NET)['homes'][0]['home'] == 'risk-eu'

    # alice calls a tool on another instance as herself: her key travels, the host maps her by name
    set_service(a.svc)
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 7}))
    assert r['content'][0]['text'] == 'cust-na:lookup:7:as alice', r
    assert r['_meta'][EXTENSION_ID]['instance'] == 'cust-na'
    seen = b.svc.authz.users_view(NET)['seen']
    assert seen and seen[0]['mapping'] == 'name'
    # an anonymous caller never crosses
    r = a.reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 1})
    assert r.get('isError')

    # a block: cust-na blocks alice@risk-eu; by qualified name she is refused (no fallback)
    blk = b.svc.authz.add_block(NET, 'user', '', 'incident 7', user='alice@risk-eu', by='admin')
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 2}))
    assert r.get('isError') and r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'user', r          # a user block
    b.svc.authz.remove_block(NET, blk['id'], by='admin', reason='resolved')
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 3}))
    assert r['content'][0]['text'] == 'cust-na:lookup:3:as alice'

    # the host goes down: the plain name falls back to treasury-na, the qualified name fails fast
    conn.down.add('https://cust-na.test')
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('lookup').execute_with_tracking({'x': 4}))
    assert r['content'][0]['text'] == 'treasury-na:lookup:4:as alice'
    assert [x['host'] for x in r['_meta'][EXTENSION_ID]['attempts']] == ['cust-na', 'treasury-na']
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 4}))
    assert r['isError'] and r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'unreachable'
    conn.down.discard('https://cust-na.test')

    # a contract conflict: cust-na changes var_calc's schema; every member quarantines it; withdrawn, it is active again
    b.reg.register_tool(Who('var_calc', props={'x': {'type': 'string'}}, owner='cust-na'))
    b.svc.catalogs.books[NET].invalidate()
    settle(insts, 4)
    for i in insts:
        q = i.svc.catalogs.books[NET].quarantined()
        assert set(q) == {'var_calc'} and q['var_calc']['differing'] == ['cust-na'], i.name
    assert 'acme-net__treasury-na__var_calc' not in a.reg.tools
    b.reg.unregister_tool('var_calc')
    b.svc.catalogs.books[NET].invalidate()
    settle(insts, 4)
    for i in insts:
        assert i.svc.catalogs.books[NET].quarantined() == {}
    assert 'acme-net__treasury-na__var_calc' in a.reg.tools

    # the Instances view and the navbar badge, at the home
    from sajha.net.integration import console
    view = console.instances_view(None)
    names = [x['name'] for x in view['nets'][0]['instances']]
    assert names[0] == 'risk-eu' and set(names[1:]) == {'cust-na', 'treasury-na'}
    assert console.badge()['label'] == 'Net · risk-eu' and console.badge()['health'] == 'ok'

    # a restart of treasury-na with its state store kept: nothing remote until a peer answers in this run
    store = c.svc.store
    c.svc.stop()
    store.delete(f'sajhanet:{NET}:run')
    c2 = Instance(tmp_path, 'treasury-na', conn, [Who('var_calc', owner='treasury-na'), Who('lookup', owner='treasury-na')],
                  store=store, engine=c.engine)
    c2.svc.start(run_agents=False)
    c2.svc.catalogs.maybe_sync()
    assert not any(n.startswith('acme-net__') for n in c2.reg.tools)
    assert c2.node.try_join()
    settle([a, b, c2], 4)
    assert 'acme-net__cust-na__lookup' in c2.reg.tools
    for i in (a, b, c2):
        i.svc.stop()


def test_a_net_of_one_grows_without_a_restart(tmp_path, isolate):
    """No seeds, no peers: the instance is its net's founder and only member, raises no error notice and
    sends nothing; a second instance later joins through it, without a restart of either."""
    from sajha import notices
    conn = ClientConnector()
    a = Instance(tmp_path, 'solo-eu', conn, [Who('var_calc', owner='solo-eu')], founder=False, seeds=[])
    a.svc.start(run_agents=False)
    st = a.svc.status()['nets'][0]
    assert 'not initialised' in st['error'] or 'no certificate' in st['error']
    ids = {n['id']: n for n in notices.list_notices(state='all')}
    assert ids[f'sajhanet.not_joined:{NET}']['severity'] == 'info'          # a net of one, not an error
    set_service(a.svc)
    from sajha.net.integration import console
    assert console.badge()['label'] == 'Net · solo-eu' and console.badge()['health'] == 'solo'
    # its administrator initialises its CA (allowed on a net with no seeds) without a restart
    a.svc.ca_init(NET)
    assert a.node is not None and a.node.try_join()
    assert a.node.status()['single_member'] and a.node.members() == []
    view = console.instances_view(None)
    assert [x['name'] for x in view['nets'][0]['instances']] == ['solo-eu'] and view['nets'][0]['single_member']
    # nothing to talk to: no join retries, no gossip
    sent, real = [], conn.send
    conn.send = lambda *x, **k: sent.append(x) or real(*x, **k)
    for _ in range(3):
        a.node.tick()
    conn.send = real
    assert sent == []
    # a second instance enrolls and joins through it: the net of one grows
    b = Instance(tmp_path, 'solo-na', conn, [Who('lookup', owner='solo-na')], seeds=['https://solo-eu.test'])
    b.svc.start(run_agents=False)
    b.svc.enroll(NET, 'https://solo-eu.test', a.svc.ca_token(NET, 'solo-na')['token'], by='test')
    assert b.node.try_join()
    settle([a, b], 4)
    assert {m['name']: m['state'] for m in a.node.members()} == {'solo-na': 'alive'}
    assert 'acme-net__solo-na__lookup' in a.reg.tools
    for i in (a, b):
        i.svc.stop()


def test_a_net_of_one_creates_its_ca_at_first_start(tmp_path, isolate, monkeypatch):
    """Owner decision (sajhanet.ca_auto_init, default on): a net of one creates its CA at first start,
    audited, with a warning notice to back up the key; a peer can enroll at once; restart reuses it."""
    from sajha import notices
    monkeypatch.setenv('SAJHA_SAJHANET_CA_AUTO_INIT', 'true')
    conn = ClientConnector()
    a = Instance(tmp_path, 'auto-eu', conn, [Who('var_calc', owner='auto-eu')], founder=False, seeds=[])
    a.svc.start(run_agents=False)
    assert (tmp_path / 'auto-eu' / 'ca.key').exists() and a.svc.status()['nets'][0]['error'] in ('', None)
    assert a.node is not None and a.node.try_join() and a.node.status()['single_member']
    ids = {n['id']: n for n in notices.list_notices(state='all')}
    assert ids[f'sajhanet.ca_created.{NET}']['severity'] == 'warning'
    key_before = (tmp_path / 'auto-eu' / 'ca.key').read_bytes()
    b = Instance(tmp_path, 'auto-na', conn, [Who('lookup', owner='auto-na')], seeds=['https://auto-eu.test'])
    b.svc.start(run_agents=False)
    b.svc.enroll(NET, 'https://auto-eu.test', a.svc.ca_token(NET, 'auto-na')['token'], by='test')
    assert b.node.try_join()
    settle([a, b], 4)
    assert 'acme-net__auto-na__lookup' in a.reg.tools
    a.svc.stop()
    a.svc.start(run_agents=False)                          # restart: the same CA, not a new one
    assert (tmp_path / 'auto-eu' / 'ca.key').read_bytes() == key_before and a.svc.runtimes[NET].ca is not None
    for i in (a, b):
        i.svc.stop()


def _open(inst):
    inst.svc.runtimes[NET].cfg.admission = 'open'
    return inst


def test_open_admission_needs_no_ca_and_holds_names_to_their_first_key(tmp_path, isolate):
    """admission: open (owner decision, for now): no CA, no tokens; self-signed certificates are
    accepted on first use, then each name is held to its key (an impostor is refused), across restarts."""
    conn = ClientConnector()
    a = _open(Instance(tmp_path, 'open-eu', conn, [Who('var_calc', owner='open-eu')], seeds=[]))
    b = _open(Instance(tmp_path, 'open-na', conn, [Who('lookup', owner='open-na')], seeds=['https://open-eu.test']))
    c = _open(Instance(tmp_path, 'open-ap', conn, [Who('lookup2', owner='open-ap')], seeds=['https://open-eu.test']))
    for i in (a, b, c):
        i.svc.start(run_agents=False)
        assert i.node is not None, i.svc.status()['nets'][0]['error']
    assert not (tmp_path / 'open-eu' / 'ca.key').exists()
    assert a.node.try_join() and b.node.try_join() and c.node.try_join()
    settle([a, b, c], 4)
    assert {m['name'] for m in a.node.members()} == {'open-na', 'open-ap'}
    assert 'acme-net__open-na__lookup' in a.reg.tools
    known = a.svc.first_use_keys(NET)
    assert set(known) >= {'open-na', 'open-ap'}
    # an impostor: another server with the name open-na (a different key) is refused by open-eu
    imp_dir = tmp_path / 'imp'
    imp_dir.mkdir()
    imp = _open(Instance(imp_dir, 'open-na', ClientConnector(), [], seeds=['https://open-eu.test']))
    imp_conn = imp.svc.connector
    imp_conn.clients['https://open-eu.test'] = conn.clients['https://open-eu.test']
    imp.svc.start(run_agents=False)
    assert not imp.node.try_join()
    assert imp.node.refused() or 'name_conflict' in str(imp.node.status()), imp.node.status()
    assert a.svc.first_use_keys(NET)['open-na'] == known['open-na']
    # restart: the remembered keys are on disk
    a.svc.stop()
    a.svc.start(run_agents=False)
    assert a.svc.first_use_keys(NET) == known
    assert a.svc.forget_peer_key(NET, 'open-ap', by='test') and 'open-ap' not in a.svc.first_use_keys(NET)
    for i in (a, b, c, imp):
        i.svc.stop()
