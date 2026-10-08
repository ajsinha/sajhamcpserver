# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net identity and authorization across instances (design §10, §11; protocol §11, §12, §15.3,
§15.4): three participants in one process, each with its own SQLite database (users, API keys and
the ``sajhanet_api_keys`` key directory) and storage, joined in one net. Covers:

* CALL-01: a user's key forwarded from their home runs as that user on the host (name match), with
  the key id; the home forwards the presented key, or the console user's default key from the vault;
* CALL-02 (``key_not_from_home``), CALL-03 (unknown, disabled, expired, revoked), CALL-04 (a key on a
  hop that is not HTTPS), CALL-05 (``ambiguous_credentials``), CALL-10 (the raw key in no row, log
  or audit record);
* users across instances: explicit link, name match, unknown refused (default) or mapped by role
  map, remote administrators (``admin``, ``user``, ``refuse``);
* blocks at every level (inbound, outbound, instance, tool, user) and their publication;
* export and import rules, the key's tool access as a ceiling;
* a key revoked at its home stops working everywhere; the directory converges; the admin API.
"""

import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
from sajha.auth import apikeys
from sajha.auth.presented_key import forget, remember
from sajha.core.storage import LocalStorageBackend
from sajha.db.schema import create_sqlite
from sajha.net import keydir
from sajha.net.errors import NetError
from sajha.net.integration import authz as az
from sajha.net.integration.keystore import DatabaseKeyDirectory
from tests.net.harness import TestNet

NET = 'acme-net'


class StubService:
    """What NetAuthz needs of a SajhaNetService: the storage backend and its data directory."""

    def __init__(self, tmp, name):
        self.docs = LocalStorageBackend(str(tmp / name / 'docs'))

        class S:
            data_dir = 'sajhanet'
        self.shared = S()

    def _doc_io(self, path):
        return (lambda: self.docs.read_json(path) if self.docs.exists(path) else {},
                lambda doc: self.docs.write_json(path, doc))


class Instance:
    def __init__(self, n, tmp, name, settings=None, **add_kw):
        self.name = name
        self.engine = create_engine(f'sqlite:///{tmp / (name + ".db")}')
        create_sqlite(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.svc = StubService(tmp, name)
        self.authz = az.NetAuthz(self.svc, db_factory=self.Session, engine=self.engine, persistent=lambda: [],
                                 settings={NET: settings or az.NetAuthSettings(export=[{'tools': ['*']}],
                                                                               import_=[{'tools': ['*']}])})
        self.svc.authz = self.authz
        self.node = n.add(name, start=False, **add_kw)
        self.st = self.authz.attach(self.node.cfg, self.node)
        self.node.start()

    def db(self):
        return self.Session()

    def user(self, login, roles=('user',), name=None):
        from sajha.db.models import Role, User
        db = self.db()
        try:
            u = User(user_id=login, user_name=name or login.title(), password_hash='x', enabled=True)
            u.roles = [db.query(Role).filter(Role.name == r).first() or Role(name=r, description=r) for r in roles]
            db.add(u)
            db.commit()
            return u.id
        finally:
            db.close()

    def key(self, login, **kw):
        from sajha.db.models import User
        db = self.db()
        try:
            owner = db.query(User).filter(User.user_id == login).first()
            k, raw = apikeys.create_key(db, name=f'{login} key', created_by='admin', owner=owner, **kw)
            return k.id, raw
        finally:
            db.close()

    def ensure_default(self, login):
        from sajha.db.models import User
        db = self.db()
        try:
            apikeys.ensure_default_key(db, db.query(User).filter(User.user_id == login).first())
        finally:
            db.close()

    def headers(self, raw, net=NET, **extra):
        return dict({'sajha-net-name': net, 'sajha-net-api-key': raw}, **extra)


@pytest.fixture
def fab(tmp_path, monkeypatch):
    monkeypatch.setattr('sajha.auth.apikeys._audit', lambda *a, **k: None)
    monkeypatch.setattr('sajha.auth.persistent_keys.get_persistent_keys', lambda: type('P', (), {
        'records': lambda self: [], 'ids': lambda self: set(), 'lookup': lambda self, h: None,
        'upsert': lambda self, r: None, 'remove': lambda self, i: False})())
    audits = []
    monkeypatch.setattr('sajha.net.integration._audit', lambda what, by='system', details=None:
                        audits.append((what, by, details)))
    set_vault(TokenVault(engine=create_engine(f'sqlite:///{tmp_path / "vault.db"}'),
                         key_provider=LocalKeyProvider('test-net-identity-' + 'k' * 32)))
    n = TestNet(tmp_path)

    class F:
        pass
    f = F()
    f.n, f.audits = n, audits
    f.a = Instance(n, tmp_path, 'risk-eu', founder=True, ca_node=True)
    f.b = Instance(n, tmp_path, 'cust-na', seeds=[n.url('risk-eu')])
    f.c = Instance(n, tmp_path, 'treasury-na', seeds=[n.url('risk-eu')])
    n.rounds(4)
    yield f
    set_vault(None)
    forget()


def sync(f, rounds=3):
    f.n.rounds(rounds)


# ── CALL-01: a user calling a tool on another instance as themselves ──

def test_call_01_forwarded_key_runs_as_the_same_user_on_the_host(fab):
    fab.a.user('alice', roles=('user',))
    fab.b.user('alice', roles=('risk_analyst',))
    kid, raw = fab.a.key('alice')
    sync(fab)
    # home: the key the caller presented on this request travels
    tok = remember(raw, kid, 'alice')
    try:
        user = {'user_id': 'alice', 'auth_type': 'apikey', 'roles': ['user']}
        h = fab.a.authz.identity.outbound_headers(user)
    finally:
        forget(tok)
    assert h == {'Sajha-Net-Api-Key': raw} and user['key_id'] == kid
    # host: verified against the directory, mapped by name to its own alice, with its own roles
    u = fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert u['name'] == 'alice@risk-eu' and u['user_id'] == 'alice' and u['mapping'] == 'name'
    assert u['roles'] == ['risk_analyst'] and u['key_id'] == kid and not u['is_admin']
    ctx = fab.b.authz.auth_context(u, fab.b.db())
    assert ctx.user_id == 'alice' and ctx.auth_type == 'sajhanet' and ctx.roles == ['risk_analyst']
    # remote user resolution is recorded for the console
    assert [s['mapping'] for s in fab.b.authz.users_view(NET)['seen']] == ['name']


def test_call_01_console_user_forwards_the_default_key_from_the_vault(fab):
    fab.a.user('bob')
    fab.b.user('bob')
    fab.a.ensure_default('bob')
    sync(fab)
    forget()
    user = {'user_id': 'bob', 'auth_type': 'session', 'roles': ['user']}
    h = fab.a.authz.identity.outbound_headers(user)
    raw = h['Sajha-Net-Api-Key']
    assert raw.startswith('sja_') and user['key_id']
    assert fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')['user_id'] == 'bob'
    # an anonymous caller never crosses (anonymous_may_call_remote off)
    with pytest.raises(NetError) as e:
        fab.a.authz.identity.outbound_headers({'user_id': 'anonymous', 'authenticated': False})
    assert e.value.reason == 'anonymous'


# ── CALL-02, CALL-03, CALL-04, CALL-05 ──

def test_call_02_03_04_05_identity_refusals(fab):
    fab.a.user('alice')
    fab.b.user('alice')
    kid, raw = fab.a.key('alice')
    _, expiring = fab.a.key('alice', expires_in_days=1)
    sync(fab)

    def reason(headers, sender='risk-eu', **kw):
        with pytest.raises(NetError) as e:
            fab.b.authz.identity.resolve(headers, sender, **kw)
        return e.value.reason
    assert reason(fab.b.headers(raw), sender='treasury-na') == 'key_not_from_home'          # CALL-02
    assert reason(fab.b.headers('sja_' + '0' * 48)) == 'key_unknown'                       # CALL-03
    assert reason(fab.b.headers(raw, authorization='Bearer x')) == 'ambiguous_credentials'  # CALL-05
    assert reason(fab.b.headers(raw), secure=False) == 'https_required'                    # CALL-04 (host)
    assert reason(fab.b.headers(raw, net='other-net')) == 'key_unknown'                    # NET-06
    # expired
    fab.n.clock.advance(2 * 86400)
    assert reason(fab.b.headers(expiring)) == 'key_expired'
    # disabled at the home, then revoked
    db = fab.a.db()
    k = apikeys.get_key(db, kid)
    apikeys.set_enabled(db, k, False, 'admin')
    db.close()
    sync(fab)
    assert reason(fab.b.headers(raw)) == 'key_disabled'
    db = fab.a.db()
    k = apikeys.get_key(db, kid)
    apikeys.revoke_key(db, k, 'admin')
    db.close()
    sync(fab)
    assert reason(fab.b.headers(raw)) == 'key_revoked'


def test_key_revoked_at_home_stops_working_everywhere_and_directory_converges(fab):
    fab.a.user('alice')
    fab.b.user('alice')
    fab.c.user('alice')
    kid, raw = fab.a.key('alice')
    sync(fab)
    for inst in (fab.b, fab.c):
        assert inst.authz.identity.resolve(inst.headers(raw), 'risk-eu')['user_id'] == 'alice'
    v = fab.a.st.keys.own_version()
    assert fab.b.st.store.version(NET, 'risk-eu') == v == fab.c.st.store.version(NET, 'risk-eu')
    db = fab.a.db()
    apikeys.delete_key(db, apikeys.get_key(db, kid), 'admin')                  # deleted: a tombstone
    db.close()
    sync(fab)
    for inst in (fab.b, fab.c):
        with pytest.raises(NetError) as e:
            inst.authz.identity.resolve(inst.headers(raw), 'risk-eu')
        assert e.value.reason == 'key_revoked'
        assert inst.st.store.version(NET, 'risk-eu') == fab.a.st.keys.own_version()
    # the home's own sign-in refuses it at once, so it can never be forwarded again
    from sajha.auth import AuthManager
    db = fab.a.db()
    assert AuthManager.authenticate_apikey(db, raw) is None
    db.close()


# ── users across instances (design §11.3) ──

def test_unknown_user_refused_by_default_link_and_role_map(fab):
    fab.a.user('carol', roles=('analyst',))
    _, raw = fab.a.key('carol')
    fab.b.user('c.smith', roles=('risk_analyst',))
    sync(fab)
    with pytest.raises(NetError) as e:
        fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert e.value.reason == 'no_account'
    # an explicit link
    fab.b.authz.link_user(NET, 'carol@risk-eu', 'c.smith', by='admin')
    u = fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert u['user_id'] == 'c.smith' and u['mapping'] == 'link'
    assert fab.b.authz.unlink_user(NET, 'carol@risk-eu', by='admin')
    # map_roles: a guest identity with the mapped roles; unmapped roles map to nothing
    fab.b.st.settings.users.unknown = 'map_roles'
    with pytest.raises(NetError):
        fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    fab.b.authz.set_role_map(NET, 'risk-eu', {'analyst': ['risk_analyst']}, by='admin')
    u = fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert u['user_id'] == 'carol@risk-eu' and u['guest'] and u['roles'] == ['risk_analyst']
    # name matching off for an instance
    fab.b.user('carol')
    fab.b.st.settings.users.unknown = 'refuse'
    assert fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')['mapping'] == 'name'
    fab.b.authz.set_name_matching(NET, 'risk-eu', False, by='admin')
    with pytest.raises(NetError):
        fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    # net settings only by a locally signed-in administrator
    from sajha.net.integration import ServiceError
    with pytest.raises(ServiceError) as e:
        fab.b.authz.link_user(NET, 'carol@risk-eu', 'carol', by='admin@risk-eu', by_auth_type='sajhanet')
    assert e.value.status == 403
    assert {a[0] for a in fab.audits} >= {'user_linked', 'user_unlinked', 'role_map_set', 'name_matching_set'}


def test_remote_administrators(fab):
    _, raw = fab.a.key('admin')                         # the seed admin exists everywhere
    sync(fab)
    u = fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert u['user_id'] == 'admin' and u['is_admin']                        # remote_admin: admin (default)
    fab.b.st.settings.users.remote_admin = 'user'
    u = fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert u['user_id'] == 'admin' and not u['is_admin']                    # matched, but no admin by name
    fab.b.st.settings.users.remote_admin = 'refuse'
    with pytest.raises(NetError) as e:
        fab.b.authz.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert e.value.reason == 'remote_admin'


# ── blocks (design §11.4, protocol §12) ──

def test_blocks_at_every_level_and_publication(fab):
    fab.a.user('alice')
    fab.b.user('alice')
    _, raw = fab.a.key('alice')
    sync(fab)
    b = fab.b.authz
    dec = lambda inst, rule, **s: inst.authz.rules.decide(rule, dict(s, net=NET))   # noqa: E731
    assert dec(fab.b, 'block_peer', peer='risk-eu', direction='inbound').allow
    blk = b.add_block(NET, 'inbound', 'risk-eu', 'incident 42', by='admin')
    assert 'refused' in blk['effect']
    d = dec(fab.b, 'block_peer', peer='risk-eu', direction='inbound')
    assert not d.allow and d.reason == 'inbound'
    assert dec(fab.b, 'block_peer', peer='risk-eu', direction='outbound').allow    # still calls risk-eu
    assert not dec(fab.b, 'export', peer='risk-eu', tool='var_calc').allow
    b.remove_block(NET, blk['id'], by='admin', reason='resolved')
    assert dec(fab.b, 'block_peer', peer='risk-eu', direction='inbound').allow
    # outbound: risk-eu stops calling cust-na's tools (import refused) but still serves it
    fab.a.authz.add_block(NET, 'outbound', 'cust-na', 'cost', by='admin')
    assert not dec(fab.a, 'block_peer', peer='cust-na', direction='outbound').allow
    assert not dec(fab.a, 'import', host='cust-na', tool='x', user={'roles': ['user']}).allow
    assert dec(fab.a, 'block_peer', peer='cust-na', direction='inbound').allow
    # tool: inbound on the host, outbound (hidden) at the home
    b.add_block(NET, 'tool', '*', 'secret', tool='wire_*', by='admin')
    assert not dec(fab.b, 'block_tool', peer='risk-eu', tool='wire_send').allow
    assert dec(fab.b, 'block_tool', peer='risk-eu', tool='var_calc').allow
    fab.c.authz.add_block(NET, 'tool', 'cust-na', 'hide', tool='acme-net__cust-na__var_*', direction='outbound',
                          by='admin')
    assert not dec(fab.c, 'block_tool', peer='cust-na', tool='var_calc', direction='outbound',
                   qualified_name='acme-net__cust-na__var_calc').allow
    # user: refused whatever the mapping, before mapping
    b.add_block(NET, 'user', '', 'abuse', user='alice@risk-eu', by='admin', expires_in_minutes=10)
    with pytest.raises(NetError) as e:
        b.identity.resolve(fab.b.headers(raw), 'risk-eu')
    assert e.value.reason == 'user'
    fab.n.clock.advance(11 * 60)                                             # expiry
    assert b.identity.resolve(fab.b.headers(raw), 'risk-eu')['user_id'] == 'alice'
    # instance: no calls either way, updates ignored
    b.add_block(NET, 'instance', 'treasury-na', 'gone rogue', by='admin')
    assert not dec(fab.b, 'block_peer', peer='treasury-na', direction='inbound').allow
    assert not dec(fab.b, 'block_peer', peer='treasury-na', direction='outbound').allow
    # published in gossip digests; the target hears of it (notice source)
    sync(fab, 4)
    pub = fab.c.st.pub.peer_document('cust-na')
    assert pub and pub['version'] == fab.b.st.blocks_version()
    assert any(x['level'] == 'instance' and x['target_instance'] == 'treasury-na' for x in pub['blocks'])
    view = fab.c.authz.blocks_view(NET)
    assert 'cust-na' in view['published']
    # refused input
    from sajha.net.integration import ServiceError
    for kw in ({'level': 'nope', 'target_instance': 'x', 'reason': 'r'},
               {'level': 'inbound', 'target_instance': 'risk-eu', 'reason': ''},
               {'level': 'inbound', 'target_instance': 'cust-na', 'reason': 'self'}):
        with pytest.raises(ServiceError):
            b.add_block(NET, kw['level'], kw['target_instance'], kw['reason'], by='admin')
    assert {a[0] for a in fab.audits} >= {'block_added', 'block_removed'}


def test_blocked_by_peer_raises_a_notice(fab, monkeypatch):
    seen = []
    monkeypatch.setattr('sajha.net.integration._notice', lambda nid, sev, title, detail, ttl=None:
                        seen.append((nid, sev)))
    monkeypatch.setattr('sajha.net.integration._clear', lambda nid: seen.append((nid, 'clear')))
    blk = fab.b.authz.add_block(NET, 'inbound', 'risk-eu', 'audit', by='admin')
    sync(fab, 4)
    assert (f'sajhanet.blocked_by:{NET}:cust-na', 'info') in seen
    fab.b.authz.remove_block(NET, blk['id'], by='admin')
    sync(fab, 4)
    assert (f'sajhanet.blocked_by:{NET}:cust-na', 'clear') in seen


# ── export and import rules (design §11.2) ──

def test_export_and_import_rules_and_the_key_ceiling(fab):
    fab.b.st.settings.export = [{'tools': ['var_*', 'stress_*'], 'to_instances': ['risk-*'],
                                 'for_roles': ['risk_analyst']},
                                {'tools': ['*_delete*'], 'to_instances': []}]
    fab.a.st.settings.import_ = [{'instances': ['cust-na'], 'tools': ['var_*'], 'for_roles': ['analyst']},
                                 {'instances': ['*'], 'tools': ['*'], 'for_roles': ['admin']}]
    dec = lambda inst, rule, **s: inst.authz.rules.decide(rule, dict(s, net=NET))   # noqa: E731
    analyst = {'roles': ['risk_analyst'], 'name': 'alice@risk-eu'}
    assert dec(fab.b, 'export', peer='risk-eu', tool='var_calc', user=analyst).allow
    assert dec(fab.b, 'export', peer='risk-eu', tool='var_calc', user=None).allow     # catalog time
    assert not dec(fab.b, 'export', peer='treasury-na', tool='var_calc', user=analyst).allow
    assert not dec(fab.b, 'export', peer='risk-eu', tool='var_calc', user={'roles': ['user']}).allow
    assert not dec(fab.b, 'export', peer='risk-eu', tool='var_delete_all', user=analyst).allow   # never exported
    assert not dec(fab.b, 'export', peer='risk-eu', tool='other', user=analyst).allow          # no rule: no export
    capped = dict(analyst, tool_access_mode='allowlist', tool_access_list=['acme-net__cust-na__stress_*'])
    d = dec(fab.b, 'export', peer='risk-eu', tool='var_calc', user=capped)
    assert not d.allow and d.reason == 'access'
    assert dec(fab.b, 'export', peer='risk-eu', tool='stress_test', user=capped).allow
    assert dec(fab.a, 'import', host='cust-na', tool='var_calc', user={'roles': ['analyst']}).allow
    assert not dec(fab.a, 'import', host='treasury-na', tool='var_calc', user={'roles': ['analyst']}).allow
    assert dec(fab.a, 'import', host='treasury-na', tool='anything', user={'roles': ['admin']}).allow
    assert not dec(fab.a, 'service_call', peer='cust-na').allow


# ── CALL-10: the raw key appears nowhere ──

def test_call_10_the_raw_key_is_never_stored_logged_or_audited(fab, caplog, monkeypatch):
    # the hashed-storage guarantee; under auth.credential_storage: plain the owner chose to keep raw keys
    monkeypatch.setenv('SAJHA_AUTH_CREDENTIAL_STORAGE', 'hashed')
    caplog.set_level(logging.DEBUG)
    fab.a.user('alice')
    fab.b.user('alice')
    kid, raw = fab.a.key('alice')
    sync(fab)
    tok = remember(raw, kid, 'alice')
    try:
        h = fab.a.authz.identity.outbound_headers({'user_id': 'alice'})
    finally:
        forget(tok)
    fab.b.authz.identity.resolve(fab.b.headers(h['Sajha-Net-Api-Key']), 'risk-eu')
    fab.b.authz.add_block(NET, 'inbound', 'treasury-na', 'x', by='admin')
    for inst in (fab.a, fab.b, fab.c):
        with inst.engine.connect() as c:
            dump = json.dumps([list(r) for r in c.execute(text('SELECT * FROM sajhanet_api_keys')).all()],
                              default=str)
            assert raw not in dump and keydir.key_hash(raw) in dump
        for _k, v in inst.node.kv.scan(''):
            assert raw not in json.dumps(v, default=str)
    assert raw not in caplog.text
    assert raw not in json.dumps(fab.audits, default=str)
    from sajha.auth.presented_key import PresentedKey
    assert raw not in repr(PresentedKey('k', 'alice', raw))


def test_linked_audit_strips_the_key(monkeypatch):
    got = []
    monkeypatch.setattr('sajha.audit.record', lambda event, **kw: got.append((event, kw)))
    az.linked_audit('net.host_call', {'net': NET, 'peer': 'risk-eu', 'tool': 'var_calc', 'trace_id': 'a' * 32,
                                      'key_id': 'k1', 'api_key': 'sja_secret', 'outcome': 'ok'})
    (event, kw), = got
    assert event == 'net.host_call' and kw['details']['key_id'] == 'k1' and 'api_key' not in kw['details']
    assert kw['details']['trace_id'] == 'a' * 32


def test_database_store_contract_and_plugins_registered():
    from sajha.net import contract, plugins
    contract.check('key_directory_store', lambda: DatabaseKeyDirectory())
    contract.check('identity', lambda: plugins.create('identity', 'api_key'))
    contract.check('rules', lambda: plugins.create('rules', 'policy_engine'))


def test_extension_advertises_api_key_and_features(fab):
    rec = fab.b.node.own_entry()['record']
    assert rec['user_identity'] == ['api_key']
    assert {'key_directory', 'key_verification', 'blocks'} <= set(rec['features'])
    assert fab.b.authz.status(NET)['user_identity'] == 'api_key'
    view = fab.b.authz.keys_view(NET, home='risk-eu')
    assert 'homes' in view and 'records' in view
    assert fab.b.authz.resync(NET)['net'] == NET
