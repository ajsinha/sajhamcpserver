"""
The administrators' credential files and plain storage (owner decisions, docs/security/Security
Model.md "Credential storage and files"): config/users.json wins over the database and is applied
to it; config/apikeys.json is checked first and wins; config/apikeys_db.json is the database dump;
test admin records count only while sajhanet.test_admin_key.enabled; per-member keys are local
configuration; the two admin pages are for administrators with CSRF.
"""

import json

import pytest

from tests.test_api_keys_identity import _auth_key, _bearer, _db, _login, _new_key, app  # noqa: F401


@pytest.fixture()
def files(tmp_path, monkeypatch):
    from sajha.auth import persistent_keys as pk, users_file as uf
    keys = pk.PersistentKeyStore(tmp_path / 'apikeys.json')
    users = uf.UsersFile(tmp_path / 'users.json')
    dump = pk.DumpKeyStore(tmp_path / 'apikeys_db.json')
    saved = (pk.get_persistent_keys(), uf.get_users_file(), pk.get_dump_keys())
    pk.set_persistent_keys(keys)
    uf.set_users_file(users)
    pk.set_dump_keys(dump)
    yield keys, users, dump
    pk.set_persistent_keys(saved[0])
    uf.set_users_file(saved[1])
    pk.set_dump_keys(saved[2])


def _sync():
    from sajha.auth.users_file import get_users_file, sync_to_database
    db = _db()
    try:
        return sync_to_database(db, get_users_file())
    finally:
        db.close()


def test_users_file_user_signs_in_and_the_file_wins(app, files):  # noqa: F811
    c, _users, _ = app
    _, users, _ = files
    users.upsert({'user_id': 'cf_alice', 'user_name': 'Alice', 'password': 'alice-pass-1', 'roles': ['user'],
                  'enabled': True})
    assert _sync()[0] == 1
    token = _login(c, 'cf_alice', 'alice-pass-1')
    assert token
    from sajha.db.models import User
    db = _db()
    try:
        u = db.query(User).filter(User.user_id == 'cf_alice').first()
        assert u.password_hash == 'alice-pass-1'            # plain storage (owner decision)
        u.password_hash = 'changed-elsewhere'
        db.commit()
    finally:
        db.close()
    _sync()                                                 # the file wins on the next apply
    assert _login(c, 'cf_alice', 'alice-pass-1')


def test_users_file_unknown_role_is_reported_not_applied(app, files):  # noqa: F811
    _, users, _ = files
    users.upsert({'user_id': 'cf_bad', 'password': 'x-pass-123', 'roles': ['no_such_role']})
    n, problems = _sync()
    assert n == 0 and any('no_such_role' in p for p in problems)


def test_test_admin_user_counts_only_while_enabled(app, files, monkeypatch):  # noqa: F811
    c, _, _ = app
    _, users, _ = files
    users.upsert({'user_id': 'cf_testadmin', 'password': 'ta-pass-123', 'roles': ['admin'], 'test_admin': True})
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'false')
    _sync()
    from sajha.security import _login_throttle
    _login_throttle.reset()
    assert c.post('/api/auth/login', json={'user_id': 'cf_testadmin', 'password': 'ta-pass-123'}).status_code != 200
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'true')
    _sync()
    assert _login(c, 'cf_testadmin', 'ta-pass-123')


def test_keys_file_is_checked_first_and_wins(app, files):  # noqa: F811
    _, users_map, _ = app
    keys, _, _ = files
    kid, raw = _new_key(users_map['user'])
    from sajha.auth import apikeys as svc
    db = _db()
    try:
        svc.set_enabled(db, svc.get_key(db, kid), False, 'test')     # disabled in the database
    finally:
        db.close()
    assert _auth_key(raw) is None
    keys.upsert({'id': 'f1', 'name': 'override', 'key': raw, 'owner': users_map['user'], 'roles': ['user'],
                 'enabled': True})
    auth = _auth_key(raw)                                            # the file wins
    assert auth is not None and auth.user_id == users_map['user']


def test_test_admin_key_only_while_enabled(app, files, monkeypatch):  # noqa: F811
    keys, _, _ = files
    keys.upsert({'id': 'ta', 'name': 'test admin', 'key': 'sja_test_admin_unit_0001', 'roles': ['admin'],
                 'enabled': True, 'test_admin': True})
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'false')
    assert _auth_key('sja_test_admin_unit_0001') is None
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'true')
    auth = _auth_key('sja_test_admin_unit_0001')
    assert auth is not None and auth.is_admin
    from sajha.auth.persistent_keys import test_admin_key
    assert test_admin_key()['key'] == 'sja_test_admin_unit_0001'


def test_database_dump_holds_raw_keys_in_plain_mode_and_is_the_last_fallback(app, files):  # noqa: F811
    _, users_map, _ = app
    _, _, dump = files
    kid, raw = _new_key(users_map['user'])
    from sajha.auth.persistent_keys import write_dump
    db = _db()
    try:
        assert write_dump(db) >= 1
    finally:
        db.close()
    recs = json.loads(dump.config_path.read_text())['keys']
    assert any(r.get('key') == raw for r in recs)
    from sajha.db.models import ApiKey
    db = _db()
    try:
        db.query(ApiKey).filter(ApiKey.id == kid).delete()            # the database loses the row
        db.commit()
    finally:
        db.close()
    assert _auth_key(raw) is not None                                 # the dump still signs it in


def test_peer_keys_are_local_configuration(monkeypatch):
    from sajha.net.integration.authz import peer_key_for
    monkeypatch.setenv('SAJHA_SAJHANET_PEER_KEYS', json.dumps({'acme/peer-b': 'sja_x', 'peer-c': '${CF_PEER_C:sja_y}'}))
    assert peer_key_for('acme', 'peer-b') == 'sja_x'
    assert peer_key_for('other', 'peer-c') == 'sja_y'
    assert peer_key_for('acme', 'nobody') == ''


def test_pages_are_admin_only_and_new_keys_show_once(app, files):  # noqa: F811
    c, users_map, _ = app
    user_tok = _login(c, users_map['user'])
    assert c.get('/api/admin/apikeys/file', headers=_bearer(user_tok)).status_code in (401, 403)
    admin_tok = _login(c, users_map['admin'])
    assert c.get('/admin/apikeys/file', headers=_bearer(admin_tok)).status_code == 200
    assert c.get('/admin/users/file', headers=_bearer(admin_tok)).status_code == 200
    r = c.post('/api/admin/apikeys/file', headers=_bearer(admin_tok), json={'name': 'made here', 'roles': 'user'})
    assert r.status_code == 200 and r.json()['raw'].startswith('sja_')
    listed = c.get('/api/admin/apikeys/file', headers=_bearer(admin_tok)).json()['keys']
    assert all(r.json()['raw'] not in json.dumps(k) for k in listed)   # masked in lists
    u = c.post('/api/admin/users/file', headers=_bearer(admin_tok),
               json={'user_id': 'cf_paged', 'password': 'paged-pass-1', 'roles': 'user'})
    assert u.status_code == 200 and 'password' not in json.dumps(u.json()['user']).replace('has_password', '')
