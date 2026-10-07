"""Snapshots of users, API keys and tools (snapshots.*; SAJHA Net §20.4, working without a net):
contents, chain, signature, rotation, one writer, audit, permissions, the CLI, restore."""

from __future__ import annotations

import json
import os
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sajha.audit.chain import ChainWriter, Signer
from sajha.db import schema
from sajha.snapshots import SnapshotService, SnapshotSettings
from sajha.snapshots.core import SnapshotStore, diff, diff_lines, load_public_keys, restore


def _pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


@pytest.fixture(scope='module')
def signer():
    return Signer(_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)), 'snap-kid')


def _keys(signer):
    return {signer.kid: signer.public_key()}


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "snap.db"}')
    schema.create_sqlite(engine)
    Session = sessionmaker(bind=engine)
    from sajha.db.dao import ApiKeyDAO
    from sajha.db.models import ApiKey, Role, User
    s = Session()
    admin_role = s.query(Role).filter_by(name='admin').one()
    alice = User(user_id='alice', user_name='Alice', password_hash='$2b$12$secrethash', enabled=True)
    alice.roles.append(admin_role)
    s.add(alice)
    s.flush()
    dao = ApiKeyDAO(s)
    s.add(ApiKey(key_hash=dao.hash_key('sja_ordinary_key'), key_prefix='sja_ordi', name='ordinary', owner_id=alice.id))
    pk = ApiKey(key_hash=dao.hash_key('sja_persistent_key'), key_prefix='sja_pers', name='automation',
                owner_id=alice.id)
    if hasattr(ApiKey, 'persistent'):
        pk.persistent = True
    s.add(pk)
    s.commit()
    s.close()
    return Session


class _Tool:
    def __init__(self, name, enabled=True):
        self.name, self.version, self.enabled = name, '1.2.0', enabled
        self.input_schema = {'type': 'object', 'properties': {'q': {'type': 'string'}}}
        self.output_schema = {}


class _Registry:
    def __init__(self):
        self.tools = {'calc_add': _Tool('calc_add'), 'old_tool': _Tool('old_tool', enabled=False)}


@pytest.fixture
def audit_records():
    from sajha import audit
    got = []
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 6,
                                 signer=Signer(_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)), 'a'),
                                 on_record=got.append))
    yield got
    audit._writer, audit._exporter = old


def _service(tmp_path, db, signer, keep=3, compress=False):
    settings = SnapshotSettings(enabled=True, interval_minutes=10, keep=keep, dir=str(tmp_path / 'snaps'),
                                compress=compress)
    from sajha.core.state.memory import MemoryStateStore
    return SnapshotService(settings, registry_getter=_Registry, session_factory=db, signer=signer,
                           state=MemoryStateStore())


def test_contents_have_no_password_hashes_and_hashes_only_for_persistent_keys(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer)
    name = svc.take()
    body = svc.store.load(name)['snapshot']
    text = json.dumps(body)
    assert 'secrethash' not in text and 'password' not in text
    users = {u['user_id']: u for u in body['users']}
    assert users['alice'] == {'id': users['alice']['id'], 'user_id': 'alice', 'user_name': 'Alice',
                              'roles': ['admin'], 'enabled': True}
    keys = {k['name']: k for k in body['api_keys']}
    assert 'key_hash' not in keys['ordinary'] and keys['ordinary']['owner'] == 'alice'
    from sajha.db.models import ApiKey
    if hasattr(ApiKey, 'persistent'):
        assert keys['automation']['persistent'] is True and len(keys['automation']['key_hash']) == 64
    tools = {t['name']: t for t in body['tools']}
    assert tools['old_tool']['enabled'] is False and tools['calc_add']['version'] == '1.2.0'
    assert len(tools['calc_add']['contract_sha256']) == 64
    assert {r['name'] for r in body['roles']} >= {'admin'}
    assert body['prev'] is None and body['seq'] == 1


def test_chain_signature_rotation_audit_and_permissions(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer, keep=3)
    names = [svc.take() for _ in range(5)]
    kept = svc.store.names()
    assert kept == names[2:]
    envs = [svc.store.load(n) for n in kept]
    for a, b in zip(envs, envs[1:]):
        assert b['snapshot']['prev']['sha256'] == a['sha256'] and b['snapshot']['seq'] == a['snapshot']['seq'] + 1
    report = svc.store.verify(_keys(signer))
    assert report['ok'] and report['count'] == 3 and 'rotation' in report['notes'][0]
    assert stat.S_IMODE(os.stat(svc.store.dir).st_mode) == 0o700
    assert all(stat.S_IMODE(os.stat(svc.store.dir / n).st_mode) == 0o600 for n in kept)
    events = [r['event'] for r in audit_records]
    assert events.count('snapshot.written') == 5 and events.count('snapshot.rotated') == 2
    rotated = [r for r in audit_records if r['event'] == 'snapshot.rotated'][0]
    assert rotated['details']['deleted'][0]['name'] == names[0]


def test_tampering_is_detected(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer, keep=10)
    names = [svc.take() for _ in range(4)]
    store = svc.store
    # edit one
    p = store.dir / names[1]
    env = json.loads(p.read_text())
    env['snapshot']['users'][0]['enabled'] = False
    p.write_text(json.dumps(env))
    r = store.verify(_keys(signer))
    assert not r['ok'] and any('edited' in x for x in r['problems'])
    # re-hash the edit: the signature still catches it
    from sajha.snapshots.core import canonical, sha256
    env['sha256'] = sha256(canonical(env['snapshot']))
    p.write_text(json.dumps(env))
    r = store.verify(_keys(signer))
    assert any('signature' in x for x in r['problems'])
    # delete one from the middle
    os.unlink(store.dir / names[1])
    r = store.verify(_keys(signer))
    assert any('chain broken' in x for x in r['problems'])
    # an unknown signer
    other = Signer(_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)), 'other')
    assert not SnapshotStore(store.dir).verify({other.kid: other.public_key()})['ok']


def test_compressed_snapshots(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer, compress=True)
    a, b = svc.take(), svc.take()
    assert a.endswith('.json.gz') and svc.store.verify(_keys(signer))['ok']
    assert svc.store.load(b)['snapshot']['prev']['name'] == a


def test_diff(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer)
    a = svc.take()
    from sajha.db.models import User
    s = db()
    s.query(User).filter_by(user_id='alice').one().enabled = False
    s.add(User(user_id='bob', user_name='Bob', password_hash='x'))
    s.commit()
    s.close()
    b = svc.take()
    d = diff(svc.store.load(a), svc.store.load(b))
    assert d['users']['added'] == ['bob']
    assert d['users']['changed'] == [{'user_id': 'alice', 'fields': {'enabled': [True, False]}}]
    lines = diff_lines(d)
    assert '+ users: bob' in lines and any(l.startswith('~ users: alice: enabled') for l in lines)


def test_one_writer_per_interval(tmp_path, db, signer, audit_records):
    from sajha.core.state.memory import MemoryStateStore
    shared = MemoryStateStore()
    settings = SnapshotSettings(enabled=True, interval_minutes=10, keep=5, dir=str(tmp_path / 'one'))
    workers = [SnapshotService(settings, registry_getter=_Registry, session_factory=db, signer=signer, state=shared)
               for _ in range(3)]
    for w in workers:                               # three workers of one process share one WORKER_ID;
        w._is_writer = lambda: True                 # the per-interval claim alone must still allow one write
    now = 1_800_000_000.0
    written = [w.tick(now) for w in workers]
    assert sum(1 for x in written if x) == 1
    assert sum(1 for w in workers if w.tick(now + 30)) == 0          # same interval
    assert sum(1 for w in workers if w.tick(now + 600)) == 1         # next interval
    for w in workers:
        w.stop()


def test_lease_elects_one_writer(tmp_path, db, signer, audit_records):
    from sajha.core.state.memory import MemoryStateStore
    shared = MemoryStateStore()
    settings = SnapshotSettings(enabled=True, interval_minutes=10, keep=5, dir=str(tmp_path / 'lease'))
    a = SnapshotService(settings, session_factory=db, signer=signer, state=shared, registry_getter=_Registry)
    b = SnapshotService(settings, session_factory=db, signer=signer, state=shared, registry_getter=_Registry)
    from sajha.core.state.lease import Lease
    from sajha.snapshots import LEASE_KEY
    b._lease = Lease(LEASE_KEY, ttl=60, holder='another-worker', store=shared)    # a second worker
    assert a._is_writer() and not b._is_writer()
    assert a.tick(1_800_000_000.0) and b.tick(1_800_000_600.0) is None     # only the holder writes
    a.stop()
    b.stop()


def test_disabled_by_setting(tmp_path, db, signer):
    settings = SnapshotSettings(enabled=False, dir=str(tmp_path / 'off'))
    assert SnapshotService(settings, session_factory=db, signer=signer).start() is False


def test_restore_users_roles_and_persistent_keys(tmp_path, db, signer, audit_records):
    svc = _service(tmp_path, db, signer)
    env = svc.store.load(svc.take())
    # a lost database: a fresh one with only the seed
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    schema.create_sqlite(fresh)
    s = sessionmaker(bind=fresh)()
    plan = restore(s, env, dry_run=True)
    assert plan['users_created'] == ['alice'] and 'admin' in plan['users_skipped']
    from sajha.db.models import ApiKey, User
    assert s.query(User).filter_by(user_id='alice').first() is None          # dry run changed nothing
    done = restore(s, env)
    alice = s.query(User).filter_by(user_id='alice').one()
    assert sorted(r.name for r in alice.roles) == ['admin']
    assert alice.must_change_password and alice.password_hash != '$2b$12$secrethash'
    if hasattr(ApiKey, 'is_default'):                                        # a new default key
        assert done.get('default_keys_created') == ['alice']
        assert s.query(ApiKey).filter_by(owner_id=alice.id, is_default=True).count() == 1
    restored_keys = {k.name for k in s.query(ApiKey).all()}
    assert 'ordinary' not in restored_keys                                    # no hash in the snapshot
    if hasattr(ApiKey, 'persistent'):
        assert done['keys_created'] == ['sja_pers'] and 'automation' in restored_keys
        from sajha.db.dao import ApiKeyDAO
        assert ApiKeyDAO(s).get_by_key_hash(ApiKeyDAO(s).hash_key('sja_persistent_key')) is not None
    again = restore(s, env)
    assert not again['users_created'] and not again['keys_created']          # idempotent
    s.close()


def test_cli_list_verify_diff_restore(tmp_path, db, signer, audit_records, capsys, monkeypatch):
    from sajha.snapshots.__main__ import main
    svc = _service(tmp_path, db, signer)
    a, b = svc.take(), svc.take()
    d = str(svc.store.dir)
    import sajha.snapshots.core as core
    monkeypatch.setattr(core, 'default_signer', lambda: signer)
    assert main(['list', '--dir', d]) == 0 and a in capsys.readouterr().out
    assert main(['verify', '--dir', d]) == 0 and 'chain intact' in capsys.readouterr().out
    assert main(['diff', 'previous', 'latest', '--dir', d]) == 0
    assert 'no differences' in capsys.readouterr().out
    fresh = tmp_path / 'cli-fresh.db'
    schema.create_sqlite(create_engine(f'sqlite:///{fresh}'))
    url = f'sqlite:///{fresh}'
    monkeypatch.setattr('builtins.input', lambda prompt='': 'wrong')
    assert main(['restore', 'latest', '--dir', d, '--db-url', url]) == 1         # not confirmed
    assert 'not confirmed' in capsys.readouterr().err
    assert main(['restore', 'latest', '--dir', d, '--db-url', url, '--yes']) == 0
    assert 'restored from' in capsys.readouterr().out
    assert any(r['event'] == 'snapshot.restored' for r in audit_records)
    # a tampered snapshot is refused
    p = svc.store.dir / b
    env = json.loads(p.read_text())
    env['snapshot']['users'].append({'id': 'x', 'user_id': 'mallory', 'user_name': 'M', 'roles': ['admin'],
                                     'enabled': True})
    p.write_text(json.dumps(env))
    assert main(['verify', '--dir', d]) == 1
    assert main(['restore', b, '--dir', d, '--db-url', url, '--yes']) == 1
    assert 'does not verify' in capsys.readouterr().err


def test_public_key_file_for_older_snapshots(tmp_path, signer):
    pub = tmp_path / 'old.pem'
    pub.write_bytes(signer.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo))
    keys = load_public_keys(str(pub))
    assert '*' in keys


def test_settings_from_config(monkeypatch):
    monkeypatch.setenv('SAJHA_SNAPSHOTS_INTERVAL_MINUTES', '15')
    monkeypatch.setenv('SAJHA_SNAPSHOTS_KEEP', '7')
    monkeypatch.setenv('SAJHA_SNAPSHOTS_DIR', '/tmp/x')
    s = SnapshotSettings.from_config()
    assert (s.interval_minutes, s.keep, s.dir, s.compress) == (15.0, 7, '/tmp/x', False)
    monkeypatch.setenv('SAJHA_SNAPSHOTS_KEEP', 'many')
    assert SnapshotSettings.from_config().keep == 20
