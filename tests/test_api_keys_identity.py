"""
Identity and API keys (wave 1, stream A):

* inner calls run as the caller (composites, sajha_ask), with cycle and depth limits;
* API keys owned by users (owner's roles, key access as a ceiling), unowned keys unchanged,
  revocation records, self-service, default keys kept encrypted;
* persistent keys in a hashed file (database wins, reload on change, owner-only mode);
* revocable sign-in (token version, signed-out tokens, OAuth refresh).
"""
import json
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

PASSWORD = 'Keys-Identity-Pass-1'


# ── helpers ─────────────────────────────────────────────────────────

def _db():
    from sajha.db.engine import get_db_session
    return get_db_session()


def _make_user(role: str, prefix: str = 'keys') -> str:
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.models import User
    uid = f'{prefix}_{role}_{uuid.uuid4().hex[:8]}'
    db = _db()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password(PASSWORD), enabled=True)
        user.roles.append(RoleDAO(db).get_or_create(role))
        UserDAO(db).create(user)
    finally:
        db.close()
    return uid


def _drop_user(uid: str) -> None:
    from sajha.db.dao import UserDAO
    db = _db()
    try:
        user = UserDAO(db).get_by_user_id(uid)
        if user:
            UserDAO(db).delete(user)
    finally:
        db.close()


def _login(c, uid, password=PASSWORD) -> str:
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/api/auth/login', json={'user_id': uid, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()['token']


def _bearer(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    from sajha.auth import persistent_keys as pk
    keyfile = tmp_path_factory.mktemp('keys') / 'apikeys.json'
    pk.set_persistent_keys(pk.PersistentKeyStore(keyfile))
    with TestClient(create_app()) as c:
        users = {role: _make_user(role) for role in ('user', 'viewer', 'admin')}
        yield c, users, keyfile
        for uid in users.values():
            _drop_user(uid)
    pk.set_persistent_keys(None)


def _user(uid):
    from sajha.db.dao import UserDAO
    db = _db()
    return db, UserDAO(db).get_by_user_id(uid)


def _new_key(uid=None, **kw):
    from sajha.auth import apikeys as svc
    db = _db()
    try:
        owner = None
        if uid:
            from sajha.db.dao import UserDAO
            owner = UserDAO(db).get_by_user_id(uid)
        key, raw = svc.create_key(db, name=kw.pop('name', 'k-' + uuid.uuid4().hex[:6]), created_by='test',
                                  owner=owner, **kw)
        return key.id, raw
    finally:
        db.close()


def _auth_key(raw):
    from sajha.auth import AuthManager
    db = _db()
    try:
        return AuthManager.authenticate_apikey(db, raw)
    finally:
        db.close()


# ── 1. inner calls run as the caller ────────────────────────────────

class _Echo:
    def __init__(self, name):
        self.name = name
        self.ran = 0

    def execute(self, arguments):
        self.ran += 1
        return {'tool': self.name, 'who': __import__('sajha.observability.caller', fromlist=['current']).current().user_id}


class _Registry:
    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self.tools.get(name)


def _composite(registry, name='combo', master='open_tool', steps=('secret_tool',)):
    from sajha.tools.composite_tool import CompositeTool
    return CompositeTool({'name': name, 'description': 'test', 'master_tool': master, 'arrangement': 'sibling',
                          'steps': [{'tool_name': s, 'output_key': s} for s in steps]}, registry)


def test_composite_steps_run_as_the_caller_and_respect_its_access():
    from sajha.observability.caller import Caller, reset, set_caller
    open_t, secret_t = _Echo('open_tool'), _Echo('secret_tool')
    comp = _composite(_Registry(open_t, secret_t))
    token = set_caller(Caller('alice', access=lambda n: n in ('combo', 'open_tool')))
    try:
        out = comp.execute({})
    finally:
        reset(token)
    assert secret_t.ran == 0, 'a step the caller may not run was executed'
    assert 'access denied' in json.dumps(out)
    assert open_t.ran == 1
    # a caller with access to both: the step runs, and sees the caller (context carried into the pool)
    token = set_caller(Caller('bob', access=lambda n: True))
    try:
        out = comp.execute({})
    finally:
        reset(token)
    assert secret_t.ran == 1
    assert '"who": "bob"' in json.dumps(out)


def test_composite_cycles_and_depth_are_refused():
    from sajha.core import inner_calls
    reg = _Registry(_Echo('open_tool'))
    comp = _composite(reg, name='loop', steps=('loop',))
    reg.tools['loop'] = comp
    out = comp.execute({})
    assert 'already running' in json.dumps(out)
    with inner_calls.entered('a', limit=2):
        with inner_calls.entered('b', limit=2):
            with pytest.raises(inner_calls.CallTooDeep):
                with inner_calls.entered('c', limit=2):
                    pass
    assert inner_calls.chain() == ()


def test_sajha_ask_inner_access_is_the_callers():
    from types import SimpleNamespace
    from sajha.ai.ask_tool import inner_access
    from sajha.observability.caller import Caller
    settings = SimpleNamespace(mcp_allowed_tools=['calc_*', 'wiki_*'])
    caller = Caller('carol', access=lambda n: n.startswith('wiki_'))
    can = inner_access(settings, caller)
    assert can('wiki_search') is True
    assert can('calc_add') is False             # listed, but the caller may not run it
    assert can('secret_tool') is False
    assert can('sajha_ask') is False
    # no ceiling: the caller's access decides
    can = inner_access(SimpleNamespace(mcp_allowed_tools=[]), Caller('dave', access=lambda n: n == 'x'))
    assert can('x') and not can('y')
    # anonymous MCP caller (policy recorded from the session): mcp_allowed_tools no longer widens it
    anon = Caller('anonymous', access=lambda n: False)
    assert inner_access(settings, anon)('calc_add') is False


def test_sajha_ask_runs_as_the_caller(monkeypatch):
    """sajha_ask is an LLM tool (config/tools/sajha_ask.json): the ask it runs carries the caller's identity,
    and the tools it may offer are the caller's, never more."""
    from sajha.ai import ask_tool, intelligence
    from sajha.ai.intelligence import AskResult
    from sajha.observability.caller import Caller, reset, set_caller
    seen = {}

    class Memory:
        def open(self, cid, question, ctx, **kw):
            from sajha.ai.memory import MemoryContext
            return MemoryContext('', True, standalone=question, stored=False)

        def record(self, *a, **kw):
            return None

    class Registry:
        tools = {'wiki_search': object(), 'calc_add': object()}

        def get_tool(self, name):
            return self.tools.get(name)

    class Svc:
        settings = type('S', (), {'mcp_allowed_tools': []})()
        memory = Memory()
        tools_registry = Registry()

        def ask(self, question, ctx, **kw):
            seen['ctx'], seen['kw'] = ctx, kw
            return AskResult(question=question, answer='ok')

    monkeypatch.setattr(intelligence, 'get_intelligence', lambda: Svc())
    token = set_caller(Caller('erin', roles=('user',), access=lambda n: n == 'wiki_search'))
    try:
        out = ask_tool.SajhaAskTool().execute({'question': 'q'})
    finally:
        reset(token)
    assert out['answer'] == 'ok' and out['stopped_by'] == 'answer'
    ctx = seen['ctx']
    assert ctx.user_id == 'erin' and ctx.roles == ['user']
    assert ctx.can_use_tool('wiki_search') and not ctx.can_use_tool('calc_add')
    assert seen['kw']['tools'] == ['wiki_search']


def test_caller_from_session_carries_the_policy():
    from sajha.auth.access import ToolPolicy
    from sajha.observability.caller import from_session
    session = {'user_id': 'u', 'roles': ['user']}
    session.update(ToolPolicy(['wiki_*'], ['wiki_*'], [], ToolPolicy(['wiki_search'])).to_session())
    c = from_session(session)
    assert c.can_execute('wiki_search') is True
    assert c.can_execute('wiki_get_page') is False     # outside the key ceiling
    assert from_session({'user_id': 'x'}).can_execute('anything') is None


# ── 2. API keys owned by users ──────────────────────────────────────

def test_owned_key_signs_in_as_its_owner_with_the_key_as_a_ceiling(app):
    from sajha.auth.access import policy_for
    c, users, _ = app
    kid, raw = _new_key(users['admin'], mode='allowlist', tool_list=['wiki_*'])
    auth = _auth_key(raw)
    assert auth.user_id == users['admin'] and auth.is_admin and auth.api_key_owned and auth.auth_type == 'apikey'
    pol = policy_for(auth)
    assert pol.can_execute('wiki_search') and not pol.can_execute('calc_add')
    # over HTTP: a tool outside the key's list is refused even for an admin owner
    r = c.post('/api/tools/execute', json={'tool': 'calc_percentage_change', 'arguments': {}},
               headers={'X-API-Key': raw})
    assert r.status_code == 403, r.text


def test_viewer_owned_key_gets_no_more_than_the_viewer(app):
    from sajha.auth.access import policy_for
    _, users, _ = app
    _, raw = _new_key(users['viewer'])
    auth = _auth_key(raw)
    assert auth.roles == ['viewer'] and not auth.is_admin
    assert policy_for(auth).can_execute('wiki_search') is False


def test_unowned_key_keeps_the_service_identity(app):
    from sajha.auth.access import policy_for
    _, raw = _new_key(None, name='legacy-ci', mode='allowlist', tool_list=['wiki_*'])
    auth = _auth_key(raw)
    assert auth.user_id == 'apikey:legacy-ci' and auth.roles == ['api_consumer'] and not auth.api_key_owned
    assert policy_for(auth).can_execute('wiki_search') and not policy_for(auth).can_execute('calc_add')


def test_revocation_is_immediate_and_recorded(app):
    from sajha.auth import apikeys as svc
    _, users, _ = app
    kid, raw = _new_key(users['user'])
    assert _auth_key(raw) is not None
    db = _db()
    try:
        key = svc.get_key(db, kid)
        svc.revoke_key(db, key, 'test')
        assert key.revoked_at is not None and key.revoked_by == 'test' and not key.enabled
        with pytest.raises(svc.KeyError_):
            svc.set_enabled(db, key, True, 'test')
    finally:
        db.close()
    assert _auth_key(raw) is None


def test_disabled_owner_disables_the_key(app):
    from sajha.db.dao import UserDAO
    uid = _make_user('user', 'keysdis')
    _, raw = _new_key(uid)
    assert _auth_key(raw) is not None
    db = _db()
    try:
        u = UserDAO(db).get_by_user_id(uid)
        u.enabled = False
        db.commit()
    finally:
        db.close()
    assert _auth_key(raw) is None
    _drop_user(uid)


def test_default_key_is_created_encrypted_and_cannot_be_deleted(app):
    from sajha.auth import apikeys as svc
    uid = _make_user('user', 'keysdef')
    db = _db()
    try:
        from sajha.db.dao import UserDAO
        user = UserDAO(db).get_by_user_id(uid)
        assert svc.ensure_default_keys(db) >= 1
        key = svc.default_key_of(db, user)
        assert key is not None and key.is_default and key.secret_ciphertext and 'sja_' not in key.secret_ciphertext
        raw = svc.default_key_secret(db, user)
        assert raw and raw.startswith('sja_')
        assert svc.ensure_default_key(db, user) is None          # exactly one
        with pytest.raises(svc.KeyError_):
            svc.revoke_key(db, key, 'test')
        with pytest.raises(svc.KeyError_):
            svc.delete_key(db, key, 'test')
        new_raw = svc.rotate_key(db, key, uid)
        assert new_raw != raw and svc.default_key_secret(db, user) == new_raw
    finally:
        db.close()
    assert _auth_key(raw) is None
    assert _auth_key(new_raw).user_id == uid
    _drop_user(uid)


def test_self_service_create_rotate_revoke_over_http(app):
    c, users, _ = app
    token = _login(c, users['user'])
    h = _bearer(token)
    r = c.post('/api/account/apikeys', json={'name': 'laptop', 'tool_access_mode': 'allowlist',
                                              'tool_list': ['wiki_*']}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    raw, kid = body['key'], body['apikey']['id']
    assert body['apikey']['owner'] == users['user'] and 'sha256' not in json.dumps(body['apikey'])
    mine = c.get('/api/account/apikeys', headers=h).json()['apikeys']
    assert any(k['id'] == kid for k in mine) and any(k['is_default'] for k in mine)
    # a key cannot manage keys
    assert c.post('/api/account/apikeys', json={'name': 'x'}, headers={'X-API-Key': raw}).status_code == 403
    # another user cannot touch it
    other = _bearer(_login(c, users['viewer']))
    assert c.post(f'/api/account/apikeys/{kid}/revoke', headers=other).status_code == 404
    r = c.post(f'/api/account/apikeys/{kid}/rotate', headers=h)
    assert r.status_code == 200 and r.json()['key'] != raw
    assert _auth_key(raw) is None
    r = c.post(f'/api/account/apikeys/{kid}/revoke', headers=h)
    assert r.status_code == 200 and r.json()['apikey']['status'] == 'revoked'
    default = next(k for k in mine if k['is_default'])
    assert c.post(f'/api/account/apikeys/{default["id"]}/revoke', headers=h).status_code == 400
    # the page renders for the user
    page = c.get('/account/apikeys', headers=h)
    assert page.status_code == 200 and 'My API keys' in page.text


def test_session_requests_need_the_csrf_token(app):
    c, users, _ = app
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/login', data={'user_id': users['user'], 'password': PASSWORD}, follow_redirects=False)
    cookies = dict(r.cookies)
    c.cookies.clear()
    assert c.post('/api/account/apikeys', json={'name': 'x'}, cookies=cookies).status_code == 403
    page = c.get('/account/apikeys', cookies=cookies).text
    csrf = page.split('data-csrf="', 1)[1].split('"', 1)[0]
    r = c.post('/api/account/apikeys', json={'name': 'x'}, cookies=cookies, headers={'X-CSRF-Token': csrf})
    assert r.status_code == 200, r.text
    c.cookies.clear()


def test_admin_assigns_an_owner_to_an_unowned_key(app):
    c, users, _ = app
    kid, raw = _new_key(None, name='orphan')
    h = _bearer(_login(c, users['admin']))
    listed = c.get('/api/admin/apikeys?owner=-', headers=h).json()['apikeys']
    assert any(k['id'] == kid for k in listed)
    r = c.post(f'/api/admin/apikeys/{kid}/owner', json={'owner': users['user']}, headers=h)
    assert r.status_code == 200, r.text
    assert _auth_key(raw).user_id == users['user']
    assert c.post(f'/api/admin/apikeys/{kid}/owner', json={'owner': users['viewer']}, headers=h).status_code == 400
    assert c.get('/admin/apikeys', headers=h).status_code == 200
    assert c.get(f'/admin/apikeys/{kid}/view', headers=h).status_code == 200
    assert c.get('/admin/apikeys/create', headers=h).status_code == 200


# ── 3. persistent keys in a hashed file ─────────────────────────────

def test_persistent_key_file_holds_hashes_and_survives_a_lost_row(app):
    from sajha.auth import apikeys as svc
    from sajha.db.models import ApiKey
    _, users, keyfile = app
    kid, raw = _new_key(users['user'], persistent=True, name='break-glass')
    text = keyfile.read_text()
    assert raw not in text and svc._hash(raw) in text
    if os.name == 'posix':
        assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600
    rec = json.loads(text)['keys'][0]
    assert rec['owner'] == users['user'] and rec['roles'] == ['user'] and rec['enabled'] is True
    # the database loses the row (not a deletion through SAJHA): the file still signs it in
    db = _db()
    try:
        db.query(ApiKey).filter(ApiKey.id == kid).delete()
        db.commit()
    finally:
        db.close()
    auth = _auth_key(raw)
    assert auth is not None and auth.user_id == users['user'] and auth.api_key_owned


def test_database_wins_over_the_file_and_edits_on_disk_reload(app):
    import time
    from sajha.auth import apikeys as svc
    from sajha.auth.persistent_keys import get_persistent_keys
    _, users, keyfile = app
    kid, raw = _new_key(users['user'], persistent=True)
    db = _db()
    try:
        svc.set_enabled(db, svc.get_key(db, kid), False, 'test')
    finally:
        db.close()
    assert _auth_key(raw) is None                     # disabled in the database: refused
    rec = next(r for r in json.loads(keyfile.read_text())['keys'] if r['id'] == kid)
    assert rec['enabled'] is False
    # an operator revokes a file-only key by editing the file
    kid2, raw2 = _new_key(users['user'], persistent=True)
    from sajha.db.models import ApiKey
    db = _db()
    try:
        db.query(ApiKey).filter(ApiKey.id == kid2).delete()
        db.commit()
    finally:
        db.close()
    assert _auth_key(raw2) is not None
    doc = json.loads(keyfile.read_text())
    for r in doc['keys']:
        if r['id'] == kid2:
            r['enabled'] = False
    time.sleep(0.01)
    keyfile.write_text(json.dumps(doc))
    get_persistent_keys().reload()
    assert _auth_key(raw2) is None


def test_file_key_of_a_deleted_user_is_refused(app, tmp_path):
    from sajha.auth import persistent_keys as pk
    from sajha.auth.apikeys import _hash
    store = pk.PersistentKeyStore(tmp_path / 'k.json')
    store.upsert({'id': 'x1', 'prefix': 'sja_aaaa', 'name': 'ghost', 'sha256': _hash('sja_ghost'),
                  'owner': 'no_such_user_zz', 'roles': ['admin'], 'enabled': True})
    saved = pk.get_persistent_keys()
    pk.set_persistent_keys(store)
    try:
        assert _auth_key('sja_ghost') is None
    finally:
        pk.set_persistent_keys(saved)


def test_old_plaintext_file_is_never_read(tmp_path):
    from sajha.auth import persistent_keys as pk
    from sajha.auth.apikeys import _hash
    f = tmp_path / 'apikeys.json'
    f.write_text(json.dumps({'apikeys': [{'key': 'sja_demo_key_12345', 'enabled': True}]}))
    store = pk.PersistentKeyStore(f)
    assert store.records() == [] and store.lookup(_hash('sja_demo_key_12345')) is None
    store.upsert({'id': 'n', 'sha256': 'ab', 'enabled': True})
    assert 'sja_demo_key_12345' not in f.read_text()
    assert json.loads(f.read_text())['format'] == pk.FORMAT


def test_example_file_is_the_format_and_the_real_one_is_ignored():
    example = json.loads((ROOT / 'config' / 'apikeys.json.example').read_text())
    assert example['format'] == 'sajha-persistent-apikeys/1'
    assert all('key' not in r for r in example['keys'])
    assert 'config/apikeys.json' in (ROOT / '.gitignore').read_text().splitlines()


# ── 4. revocable sign-in ────────────────────────────────────────────

def test_sign_out_revokes_that_token(app):
    c, users, _ = app
    token = _login(c, users['viewer'])
    assert c.get('/api/account/apikeys', headers=_bearer(token)).status_code == 200
    r = c.post('/api/auth/logout', headers=_bearer(token))
    assert r.status_code == 200 and r.json()['revoked'] is True
    assert c.get('/api/account/apikeys', headers=_bearer(token)).status_code == 401
    other = _login(c, users['viewer'])                 # a new sign-in works
    assert c.get('/api/account/apikeys', headers=_bearer(other)).status_code == 200


def test_sign_out_everywhere_and_admin_revoke(app):
    c, users, _ = app
    uid = _make_user('user', 'keysso')
    t1, t2 = _login(c, uid), _login(c, uid)
    _, raw = _new_key(uid)
    assert c.post('/api/auth/sessions/revoke', headers=_bearer(t1)).status_code == 200
    for t in (t1, t2):
        assert c.get('/api/account/apikeys', headers=_bearer(t)).status_code == 401
    assert _auth_key(raw) is not None                  # API keys are not sessions
    t3 = _login(c, uid)
    admin = _bearer(_login(c, users['admin']))
    assert c.post(f'/api/admin/users/{uid}/sessions/revoke', headers=admin).status_code == 200
    assert c.get('/api/account/apikeys', headers=_bearer(t3)).status_code == 401
    assert c.post(f'/api/admin/users/{uid}/sessions/revoke', headers={'X-API-Key': raw}).status_code == 403
    _drop_user(uid)


def test_password_change_ends_other_sessions(app):
    c, _, _ = app
    uid = _make_user('user', 'keyspw')
    old, current = _login(c, uid), _login(c, uid)
    r = c.post('/api/auth/change-password', json={'current_password': PASSWORD, 'new_password': 'An-Other-Pass-2'},
               headers=_bearer(current))
    assert r.status_code == 200, r.text
    fresh = r.json()['token']
    assert c.get('/api/account/apikeys', headers=_bearer(old)).status_code == 401
    assert c.get('/api/account/apikeys', headers=_bearer(fresh)).status_code == 200
    _drop_user(uid)


def test_token_without_a_version_is_version_zero():
    from types import SimpleNamespace
    from sajha.auth.revocation import version_matches
    assert version_matches({}, SimpleNamespace(token_version=0))
    assert not version_matches({}, SimpleNamespace(token_version=1))
    assert version_matches({'tv': 3}, SimpleNamespace(token_version=3))


def test_oauth_refresh_stops_after_sign_out_everywhere():
    from sajha.auth.oauth.authorization_server import AuthorizationStore, OAuthError, RefreshRecord
    from sajha.core.state.memory import MemoryStateStore
    store = AuthorizationStore(MemoryStateStore())
    tok = store.issue_refresh('fam', 'client', 'u', ['mcp:read'], 'r', 'iss', tv=0)
    rec = store.use_refresh(tok, 'client')
    assert isinstance(rec, RefreshRecord) and rec.tv == 0
    store.revoke_family(rec.family)
    with pytest.raises(OAuthError):
        store.issue_refresh('fam', 'client', 'u', ['mcp:read'], 'r', 'iss', tv=1)
